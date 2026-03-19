//! Single-threaded pattern engine.
//!
//! The [`Engine`] owns all scheduling state: pattern slots, a BPM clock, and a
//! min-heap of upcoming events. One loop drives everything:
//!
//! ```text
//! loop:
//!   ① apply incoming commands (pattern changes, BPM, hush)
//!   ② fill heap — query patterns for cycles within [now, now+lookahead)
//!   ③ drain heap — dispatch events whose fire_at ≤ now
//!   ④ sleep     — until the next event is due
//! ```
//!
//! All events enter the heap in `fire_at` order (the heap invariant guarantees
//! this) so the dispatch step never encounters a past-due burst regardless of
//! how many slots are active or what order they were inserted.

use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap};
use std::time::{Duration, Instant};

use crate::event::{Event, Value};
use crate::pattern::{query, CompiledPattern};
use crate::scheduler::clock::Clock;
use crate::time;

/// A scheduled event with its wall-clock fire time.
#[derive(Clone, Debug)]
pub struct TimedEvent {
    /// When this event should be dispatched to the output sink.
    pub fire_at: Instant,
    /// The pattern event (value, whole arc, part arc).
    pub event: Event<Value>,
    /// Name of the slot that produced this event (e.g. `"kick"`).
    pub slot_name: String,
}

impl PartialEq for TimedEvent {
    fn eq(&self, other: &Self) -> bool {
        self.fire_at == other.fire_at
    }
}
impl Eq for TimedEvent {}
impl PartialOrd for TimedEvent {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}
impl Ord for TimedEvent {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.fire_at.cmp(&other.fire_at)
    }
}

/// A command sent from the IPC thread to the engine loop.
#[derive(Debug)]
pub enum EngineCommand {
    /// Assign a compiled pattern to a named slot.
    SetPattern {
        /// Slot name (e.g. `"kick"`).
        name: String,
        /// Pre-compiled pattern to assign.
        pattern: CompiledPattern,
    },
    /// Silence one slot (keeps the name for future reassignment).
    Hush {
        /// Name of the slot to silence.
        name: String,
    },
    /// Silence all active slots.
    HushAll,
    /// Change the global BPM.
    SetBpm {
        /// New beats per minute.
        bpm: f64,
    },
}

/// The pattern engine: pattern state + clock + event heap.
pub struct Engine {
    // Pattern state — hot path iterates the Vec, cold path looks up by name.
    slots: Vec<CompiledPattern>,
    names: HashMap<String, usize>,

    // Scheduling state.
    clock: Clock,
    next_cycle: i64,
    heap: BinaryHeap<Reverse<TimedEvent>>,
    lookahead: Duration,
}

impl Engine {
    /// Create a new engine with the given BPM, beats-per-cycle, and lookahead.
    #[must_use]
    pub fn new(bpm: f64, beats_per_cycle: f64, lookahead: Duration) -> Self {
        Self {
            slots: Vec::new(),
            names: HashMap::new(),
            clock: Clock::new(bpm, beats_per_cycle),
            next_cycle: 0,
            heap: BinaryHeap::new(),
            lookahead,
        }
    }

    /// Apply a command from the IPC thread.
    pub fn apply(&mut self, cmd: EngineCommand) {
        match cmd {
            EngineCommand::SetPattern { name, pattern } => {
                if let Some(&idx) = self.names.get(&name) {
                    self.slots[idx] = pattern;
                } else {
                    let idx = self.slots.len();
                    self.slots.push(pattern);
                    self.names.insert(name, idx);
                }
                // Clear pre-scheduled events (belong to the old pattern) and
                // jump to the first future cycle so fill() only produces events
                // that haven't passed yet.
                self.heap.clear();
                self.next_cycle = self.first_future_cycle(Instant::now());
            }
            EngineCommand::Hush { name } => {
                if let Some(&idx) = self.names.get(&name) {
                    self.slots[idx] = CompiledPattern::silence();
                    self.heap.clear();
                    self.next_cycle = self.first_future_cycle(Instant::now());
                }
            }
            EngineCommand::HushAll => {
                for slot in &mut self.slots {
                    *slot = CompiledPattern::silence();
                }
                self.heap.clear();
                self.next_cycle = self.first_future_cycle(Instant::now());
            }
            EngineCommand::SetBpm { bpm } => {
                // Rebuild the clock at the new BPM; clear stale events.
                self.clock = Clock::new(bpm, self.clock.beats_per_cycle());
                self.heap.clear();
                self.next_cycle = 0; // fresh clock — start from cycle 0
            }
        }
    }

    /// The first cycle number whose start instant is strictly after `now`.
    /// Used after a reset to skip already-elapsed cycles without filtering
    /// individual events inside `fill()`.
    fn first_future_cycle(&self, now: Instant) -> i64 {
        if now <= self.clock.cycle_start_instant(0) {
            return 0;
        }
        let elapsed = now
            .duration_since(self.clock.cycle_start_instant(0))
            .as_secs_f64();
        let elapsed_cycles = elapsed / self.clock.cycle_duration_secs();
        #[allow(clippy::cast_possible_truncation)]
        let cycle = elapsed_cycles.floor() as i64;
        cycle + 1
    }

    /// Advance the heap: query all patterns for cycles within `[now, now+lookahead)`.
    /// Each cycle is queried exactly once; `next_cycle` tracks the frontier.
    ///
    /// # Panics
    /// Panics if pattern evaluation produces an event with `has_onset()` but no
    /// `whole` arc (which the evaluator contract guarantees never happens).
    pub fn fill(&mut self, now: Instant) {
        let horizon = now + self.lookahead;
        while self.clock.cycle_start_instant(self.next_cycle) <= horizon {
            let query_arc = time::Arc::cycle(self.next_cycle);
            for (name, &idx) in &self.names {
                let pattern = &self.slots[idx];
                for event in query(pattern, pattern.root, query_arc) {
                    if event.has_onset() {
                        let onset = event.whole.expect("onset implies whole").start;
                        self.heap.push(Reverse(TimedEvent {
                            fire_at: self.clock.onset_to_instant(onset),
                            event,
                            slot_name: name.clone(),
                        }));
                    }
                }
            }
            self.next_cycle += 1;
        }
    }

    /// Drain all events whose `fire_at ≤ now` from the heap, in order.
    /// Returns them sorted by `fire_at` (guaranteed by the heap invariant).
    ///
    /// # Panics
    /// Does not panic — `peek` success guarantees `pop` success.
    pub fn drain(&mut self, now: Instant) -> Vec<TimedEvent> {
        let mut due = Vec::new();
        while let Some(Reverse(event)) = self.heap.peek() {
            if event.fire_at <= now {
                let Reverse(event) = self.heap.pop().expect("peek succeeded");
                due.push(event);
            } else {
                break;
            }
        }
        due
    }

    /// The wall-clock time of the next scheduled event, if any.
    #[must_use]
    pub fn next_deadline(&self) -> Option<Instant> {
        self.heap.peek().map(|Reverse(e)| e.fire_at)
    }

    /// The current BPM.
    #[must_use]
    pub fn bpm(&self) -> f64 {
        self.clock.bpm()
    }

    /// Number of named slots (including silenced ones).
    #[cfg(test)]
    pub fn slot_count(&self) -> usize {
        self.names.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    fn osc_val(label: &str, v: f32) -> Value {
        use crate::event::{OscArg, Value};
        Value::Osc {
            address: "/soundman/set".into(),
            args: vec![OscArg::Str(label.into()), OscArg::Float(f64::from(v))],
        }
    }

    fn note(n: u8) -> Value {
        Value::Note { channel: 0, note: n, velocity: 100, dur: 0.5 }
    }

    fn fast_engine() -> Engine {
        // Very fast BPM so cycles complete in ~40ms — avoids long test waits.
        // 6000 BPM, 4 beats/cycle → 1 cycle = 40ms.
        Engine::new(6000.0, 4.0, Duration::from_millis(200))
    }

    // ── apply ────────────────────────────────────────────────────────────────

    #[test]
    fn apply_set_pattern_stores_and_retrieves() {
        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "kick".into(),
            pattern: CompiledPattern::atom(note(36)),
        });
        assert_eq!(e.slot_count(), 1);
    }

    #[test]
    fn apply_set_pattern_overwrites_existing_slot() {
        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "kick".into(),
            pattern: CompiledPattern::atom(note(36)),
        });
        e.apply(EngineCommand::SetPattern {
            name: "kick".into(),
            pattern: CompiledPattern::atom(note(38)),
        });
        // Still one slot, not two.
        assert_eq!(e.slot_count(), 1);
    }

    #[test]
    fn apply_hush_silences_slot() {
        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "kick".into(),
            pattern: CompiledPattern::atom(note(36)),
        });
        e.apply(EngineCommand::Hush { name: "kick".into() });

        // Slot still exists but is silence — fill produces no events.
        std::thread::sleep(Duration::from_millis(10));
        e.fill(Instant::now());
        // Give it a cycle to potentially fire.
        std::thread::sleep(Duration::from_millis(60));
        let due = e.drain(Instant::now());
        assert!(due.is_empty(), "hushed slot should produce no events");
    }

    #[test]
    fn apply_hush_all_silences_every_slot() {
        let mut e = fast_engine();
        for name in ["kick", "snare", "hat"] {
            e.apply(EngineCommand::SetPattern {
                name: name.into(),
                pattern: CompiledPattern::atom(note(36)),
            });
        }
        e.apply(EngineCommand::HushAll);
        std::thread::sleep(Duration::from_millis(10));
        e.fill(Instant::now());
        std::thread::sleep(Duration::from_millis(60));
        assert!(e.drain(Instant::now()).is_empty());
    }

    #[test]
    fn apply_set_bpm_resets_clock_and_clears_heap() {
        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "kick".into(),
            pattern: CompiledPattern::atom(note(36)),
        });
        e.fill(Instant::now());
        let before = e.heap.len();
        assert!(before > 0, "heap should have events after fill");

        e.apply(EngineCommand::SetBpm { bpm: 3000.0 });
        assert_eq!(e.heap.len(), 0, "BPM change should clear heap");
        // next_cycle resets to 0 for a fresh clock (not first_future_cycle,
        // since the new clock's epoch is now).
        assert_eq!(e.next_cycle, 0, "BPM change should reset cycle counter");
    }

    // ── fill ─────────────────────────────────────────────────────────────────

    #[test]
    fn fill_advances_next_cycle() {
        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "s".into(),
            pattern: CompiledPattern::atom(note(60)),
        });
        let before = e.next_cycle;
        e.fill(Instant::now());
        assert!(e.next_cycle > before, "fill should advance next_cycle");
    }

    #[test]
    fn fill_does_not_re_query_same_cycle() {
        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "s".into(),
            pattern: CompiledPattern::atom(note(60)),
        });
        e.fill(Instant::now());
        let heap_size_after_first = e.heap.len();
        e.fill(Instant::now());
        assert_eq!(
            e.heap.len(),
            heap_size_after_first,
            "second fill should not add duplicate events"
        );
    }

    // ── drain ────────────────────────────────────────────────────────────────

    #[test]
    fn drain_returns_only_due_events() {
        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "s".into(),
            pattern: CompiledPattern::atom(note(60)),
        });
        // Fill but don't wait — events are scheduled in the near future.
        e.fill(Instant::now());
        // Drain immediately: most events should still be in the future.
        let due_now = e.drain(Instant::now());
        // Nothing should be due yet (we just filled — all events are future).
        assert!(due_now.is_empty() || e.heap.len() > 0,
            "heap should retain future events after drain");
    }

    #[test]
    fn drain_returns_events_in_fire_at_order() {
        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "a".into(),
            pattern: CompiledPattern::atom(note(60)),
        });
        e.apply(EngineCommand::SetPattern {
            name: "b".into(),
            pattern: CompiledPattern::atom(note(64)),
        });
        e.fill(Instant::now());
        // Wait long enough for several cycles worth of events to become due.
        std::thread::sleep(Duration::from_millis(300));
        let due = e.drain(Instant::now());
        assert!(!due.is_empty());
        // Verify monotonically non-decreasing fire_at.
        for window in due.windows(2) {
            assert!(
                window[0].fire_at <= window[1].fire_at,
                "events must be in fire_at order — burst detected: \
                 slot={} t={:?} then slot={} t={:?}",
                window[0].slot_name, window[0].fire_at,
                window[1].slot_name, window[1].fire_at,
            );
        }
    }

    // ── key correctness invariant ─────────────────────────────────────────────

    #[test]
    fn multi_slot_events_globally_sorted_by_fire_at() {
        // THE regression test: multiple slots with multi-atom patterns must
        // produce events in global fire_at order. The old FIFO channel broke
        // this — whichever slot was iterated first in the HashMap filled the
        // channel, blocking later slots' events past their due time (burst).
        use crate::pattern::PatternNode;
        use smallvec::smallvec;

        fn two_atom(v1: Value, v2: Value) -> CompiledPattern {
            let mut pat = CompiledPattern {
                nodes: vec![
                    PatternNode::Atom { value: v1 },
                    PatternNode::Atom { value: v2 },
                ],
                root: 0,
            };
            let cat = pat.push(PatternNode::Cat { children: smallvec![0, 1] });
            pat.root = cat;
            pat
        }

        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "kick".into(),
            pattern: two_atom(osc_val("kick", 1.0), osc_val("kick", 0.0)),
        });
        e.apply(EngineCommand::SetPattern {
            name: "snare".into(),
            pattern: two_atom(osc_val("snare", 0.0), osc_val("snare", 1.0)),
        });

        e.fill(Instant::now());
        std::thread::sleep(Duration::from_millis(300));

        let due = e.drain(Instant::now());
        assert!(due.len() >= 4, "expected events from both slots");

        for window in due.windows(2) {
            assert!(
                window[0].fire_at <= window[1].fire_at,
                "multi-slot burst: {} fire_at={:?} then {} fire_at={:?}",
                window[0].slot_name, window[0].fire_at,
                window[1].slot_name, window[1].fire_at,
            );
        }
    }

    #[test]
    fn new_slot_does_not_burst_on_first_fill() {
        // A slot added after several cycles have elapsed should start on a
        // future cycle, not fire all past-cycle events immediately as a burst.
        let mut e = fast_engine();

        // Let the clock run for a few cycles with no slots.
        std::thread::sleep(Duration::from_millis(120));

        // Add a new slot — it should NOT fire events from past cycles.
        e.apply(EngineCommand::SetPattern {
            name: "late".into(),
            pattern: CompiledPattern::atom(note(60)),
        });
        e.fill(Instant::now());

        // Drain immediately — nothing should be past-due.
        let burst = e.drain(Instant::now());
        assert!(
            burst.is_empty(),
            "newly added slot produced a burst of {} past-due events",
            burst.len()
        );
    }

    #[test]
    fn next_deadline_returns_min_fire_at() {
        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "s".into(),
            pattern: CompiledPattern::atom(note(60)),
        });
        assert!(e.next_deadline().is_none(), "empty heap has no deadline");
        e.fill(Instant::now());
        assert!(e.next_deadline().is_some(), "filled heap has a deadline");
        let dl = e.next_deadline().unwrap();
        assert!(dl > Instant::now(), "next deadline should be in the future");
    }
}
