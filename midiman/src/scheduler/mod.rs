//! Real-time scheduler for pattern evaluation.
//!
//! The scheduler runs on a dedicated thread, querying all active pattern
//! slots each tick and sending [`TimedEvent`]s to a channel for output
//! dispatch. Pattern hot-swap is lock-free via [`hotswap::SwapSlot`]
//! (backed by `arc-swap`).

pub mod clock;
pub mod hotswap;

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use crossbeam_channel::Sender;

use crate::event::{Event, Value};
use crate::pattern::query;
use crate::time::{self, Time};

use clock::Clock;
use hotswap::SwapSlot;

/// A scheduled event with its wall-clock fire time.
#[derive(Clone, Debug)]
pub struct TimedEvent {
    /// When this event should be dispatched to the output sink.
    pub fire_at: Instant,
    /// The pattern event (value, whole arc, part arc).
    pub event: Event<Value>,
    /// Name of the slot that produced this event (e.g. `"d1"`).
    pub slot_name: String,
}

/// Configuration for the scheduler.
#[allow(missing_docs)]
pub struct SchedulerConfig {
    pub bpm: f64,
    pub beats_per_cycle: f64,
    /// How far ahead (in seconds) to query for events.
    pub lookahead_secs: f64,
    /// How often (in seconds) the scheduler tick fires.
    pub tick_interval_secs: f64,
}

impl Default for SchedulerConfig {
    fn default() -> Self {
        Self {
            bpm: 120.0,
            beats_per_cycle: 4.0,
            lookahead_secs: 0.1,
            tick_interval_secs: 0.001,
        }
    }
}

/// Shared slots map — the IPC layer inserts/swaps patterns here.
pub type Slots = Arc<Mutex<HashMap<String, Arc<SwapSlot>>>>;

/// Handle to control a running scheduler.
pub struct SchedulerHandle {
    stop: Arc<AtomicBool>,
    thread: Option<thread::JoinHandle<()>>,
}

impl SchedulerHandle {
    /// Signal the scheduler to stop and wait for the thread to finish.
    pub fn stop(mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(handle) = self.thread.take() {
            let _ = handle.join();
        }
    }

    /// Returns `true` if the scheduler thread is still alive.
    pub fn is_running(&self) -> bool {
        self.thread
            .as_ref()
            .is_some_and(|h| !h.is_finished())
    }
}

/// Start the scheduler on a dedicated thread.
/// Accepts initial slots so patterns are ready before the first tick.
pub fn start(
    config: SchedulerConfig,
    initial_slots: HashMap<String, Arc<SwapSlot>>,
    event_tx: Sender<TimedEvent>,
) -> (SchedulerHandle, Slots) {
    let stop = Arc::new(AtomicBool::new(false));
    let stop_clone = Arc::clone(&stop);

    let slots: Slots = Arc::new(Mutex::new(initial_slots));
    let slots_clone = Arc::clone(&slots);

    let thread = thread::Builder::new()
        .name("midiman-scheduler".into())
        .spawn(move || {
            run_loop(config, stop_clone, slots_clone, event_tx);
        })
        .expect("failed to spawn scheduler thread");

    let handle = SchedulerHandle {
        stop,
        thread: Some(thread),
    };
    (handle, slots)
}

fn run_loop(
    config: SchedulerConfig,
    stop: Arc<AtomicBool>,
    slots: Slots,
    event_tx: Sender<TimedEvent>,
) {
    let clock = Clock::new(config.bpm, config.beats_per_cycle);
    let tick_dur = Duration::from_secs_f64(config.tick_interval_secs);

    let cycle_dur_us = (clock.cycle_duration_secs() * 1_000_000.0) as i64;
    let lookahead_us = (config.lookahead_secs * 1_000_000.0) as i64;
    let lookahead_cycles = Time::new(lookahead_us, cycle_dur_us as u64);

    let mut last_query_end = Time::zero();

    while !stop.load(Ordering::Relaxed) {
        let now = Instant::now();
        let now_cycle = clock.instant_to_cycle(now);
        let query_end = now_cycle + lookahead_cycles;

        if query_end > last_query_end {
            let query_start = if last_query_end > now_cycle {
                last_query_end
            } else {
                now_cycle
            };
            let query_arc = time::Arc::new(query_start, query_end);

            let slots_guard = slots.lock().expect("slots mutex poisoned");
            for (name, slot) in &*slots_guard {
                let pattern = slot.load();
                let events = query(&pattern, pattern.root, query_arc);

                for event in events {
                    if event.has_onset() {
                        let onset = event.whole.expect("onset implies whole").start;
                        let fire_at = clock.onset_to_instant(onset);

                        let _ = event_tx.send(TimedEvent {
                            fire_at,
                            event,
                            slot_name: name.clone(),
                        });
                    }
                }
            }
            drop(slots_guard);

            last_query_end = query_end;
        }

        spin_sleep::sleep(tick_dur);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::Value;
    use crate::pattern::CompiledPattern;

    fn note(n: u8) -> Value {
        Value::Note {
            channel: 0,
            note: n,
            velocity: 100,
            dur: 0.5,
        }
    }

    /// Very fast BPM so cycles complete quickly in tests.
    fn fast_config() -> SchedulerConfig {
        SchedulerConfig {
            bpm: 6000.0,       // 1 cycle = 0.04s at 4 beats/cycle
            beats_per_cycle: 4.0,
            lookahead_secs: 0.1, // ~2.5 cycles ahead
            tick_interval_secs: 0.001,
        }
    }

    #[test]
    fn scheduler_starts_and_stops() {
        let (tx, _rx) = crossbeam_channel::unbounded();
        let (handle, _slots) = start(fast_config(), HashMap::new(), tx);
        assert!(handle.is_running());
        handle.stop();
    }

    #[test]
    fn scheduler_emits_events_for_initial_slot() {
        let (tx, rx) = crossbeam_channel::unbounded();

        let mut initial = HashMap::new();
        initial.insert(
            "d1".into(),
            Arc::new(SwapSlot::new(CompiledPattern::atom(note(60)))),
        );

        let (handle, _slots) = start(fast_config(), initial, tx);

        // At 6000 BPM, one cycle = 40ms. Wait for a few cycles.
        thread::sleep(Duration::from_millis(100));
        handle.stop();

        let events: Vec<_> = rx.try_iter().collect();
        assert!(
            !events.is_empty(),
            "expected events from scheduler, got none"
        );
        assert_eq!(events[0].slot_name, "d1");
        assert_eq!(events[0].event.value, note(60));
    }

    #[test]
    fn scheduler_hot_swaps_pattern() {
        let (tx, rx) = crossbeam_channel::unbounded();

        let slot = Arc::new(SwapSlot::new(CompiledPattern::atom(note(60))));
        let mut initial = HashMap::new();
        initial.insert("d1".into(), Arc::clone(&slot));

        let (handle, _slots) = start(fast_config(), initial, tx);

        // Wait for some events with note 60
        thread::sleep(Duration::from_millis(60));

        // Hot-swap to note 72
        slot.swap(CompiledPattern::atom(note(72)));

        // Wait for events with note 72
        thread::sleep(Duration::from_millis(100));
        handle.stop();

        let events: Vec<_> = rx.try_iter().collect();
        let has_60 = events.iter().any(|e| e.event.value == note(60));
        let has_72 = events.iter().any(|e| e.event.value == note(72));
        assert!(has_60, "expected note 60 before swap");
        assert!(has_72, "expected note 72 after swap");
    }

    #[test]
    fn scheduler_multiple_slots() {
        let (tx, rx) = crossbeam_channel::unbounded();

        let mut initial = HashMap::new();
        initial.insert(
            "d1".into(),
            Arc::new(SwapSlot::new(CompiledPattern::atom(note(60)))),
        );
        initial.insert(
            "d2".into(),
            Arc::new(SwapSlot::new(CompiledPattern::atom(note(64)))),
        );

        let (handle, _slots) = start(fast_config(), initial, tx);

        thread::sleep(Duration::from_millis(100));
        handle.stop();

        let events: Vec<_> = rx.try_iter().collect();
        let has_d1 = events.iter().any(|e| e.slot_name == "d1");
        let has_d2 = events.iter().any(|e| e.slot_name == "d2");
        assert!(has_d1, "expected events from d1");
        assert!(has_d2, "expected events from d2");
    }
}
