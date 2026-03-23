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
    /// Index into the engine's slot table. Use [`Engine::slot_name`] to resolve.
    pub slot_idx: usize,
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
    /// Assign a compiled pattern to a named slot, resetting phase to start from 0.
    SetPatternFromZero {
        /// Slot name.
        name: String,
        /// Pre-compiled pattern to assign.
        pattern: CompiledPattern,
    },
    /// Change the global BPM.
    SetBpm {
        /// New beats per minute.
        bpm: f64,
    },
    /// Change beats per cycle (meter).
    SetBeatsPerCycle {
        /// New beats per cycle.
        beats: f64,
    },
}

/// The pattern engine: pattern state + clock + event heap.
pub struct Engine {
    // Pattern state — hot path iterates the Vec, cold path looks up by name.
    slots: Vec<CompiledPattern>,
    names: HashMap<String, usize>,
    // Per-slot cycle frontier: next_cycle[idx] is the next cycle to query for slot idx.
    next_cycle: Vec<i64>,
    // Per-slot phase offset: added to next_cycle when querying patterns.
    // 0 = absolute positioning (default). -current_cycle = start from 0.
    phase_offset: Vec<i64>,

    // Scheduling state.
    clock: Clock,
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
            next_cycle: Vec::new(),
            phase_offset: Vec::new(),
            clock: Clock::new(bpm, beats_per_cycle),
            heap: BinaryHeap::new(),
            lookahead,
        }
    }

    /// Apply a command from the IPC thread.
    pub fn apply(&mut self, cmd: EngineCommand) {
        match cmd {
            EngineCommand::SetPattern { name, pattern } => {
                let now = Instant::now();
                if let Some(&idx) = self.names.get(&name) {
                    self.slots[idx] = pattern;
                    self.clear_slot_events(idx);
                    self.next_cycle[idx] = self.current_cycle(now);
                    self.phase_offset[idx] = 0;
                } else {
                    let idx = self.slots.len();
                    self.slots.push(pattern);
                    self.names.insert(name, idx);
                    self.next_cycle.push(self.first_future_cycle(now));
                    self.phase_offset.push(0);
                }
            }
            EngineCommand::SetPatternFromZero { name, pattern } => {
                let now = Instant::now();
                let offset = -self.current_cycle(now);
                if let Some(&idx) = self.names.get(&name) {
                    self.slots[idx] = pattern;
                    self.clear_slot_events(idx);
                    self.next_cycle[idx] = self.current_cycle(now);
                    self.phase_offset[idx] = offset;
                } else {
                    let idx = self.slots.len();
                    self.slots.push(pattern);
                    self.names.insert(name, idx);
                    self.next_cycle.push(self.first_future_cycle(now));
                    self.phase_offset.push(offset);
                }
            }
            EngineCommand::Hush { name } => {
                if let Some(&idx) = self.names.get(&name) {
                    self.slots[idx] = CompiledPattern::silence();
                    self.clear_slot_events(idx);
                    self.next_cycle[idx] = self.current_cycle(Instant::now());
                }
            }
            EngineCommand::HushAll => {
                for slot in &mut self.slots {
                    *slot = CompiledPattern::silence();
                }
                self.heap.clear();
                let future = self.first_future_cycle(Instant::now());
                self.next_cycle.fill(future);
                self.phase_offset.fill(0);
            }
            EngineCommand::SetBpm { bpm } => {
                if !bpm.is_finite() || bpm <= 0.0
                    || (bpm - self.clock.bpm()).abs() < f64::EPSILON
                {
                    return;
                }
                self.clock = Clock::new(bpm, self.clock.beats_per_cycle());
                self.heap.clear();
                self.next_cycle.fill(0);
                self.phase_offset.fill(0);
            }
            EngineCommand::SetBeatsPerCycle { beats } => {
                if !beats.is_finite() || beats <= 0.0
                    || (beats - self.clock.beats_per_cycle()).abs() < f64::EPSILON
                {
                    return;
                }
                self.clock = Clock::new(self.clock.bpm(), beats);
                self.heap.clear();
                self.next_cycle.fill(0);
                self.phase_offset.fill(0);
            }
        }
    }

    /// Remove all heap events belonging to a specific slot.
    fn clear_slot_events(&mut self, slot_idx: usize) {
        let old = std::mem::take(&mut self.heap);
        self.heap = old.into_iter()
            .filter(|Reverse(e)| e.slot_idx != slot_idx)
            .collect();
    }

    /// The cycle that contains `now`.
    fn current_cycle(&self, now: Instant) -> i64 {
        let start = self.clock.cycle_start_instant(0);
        if now <= start {
            return 0;
        }
        let elapsed = now.duration_since(start).as_secs_f64();
        let cycles = elapsed / self.clock.cycle_duration_secs();
        #[allow(clippy::cast_possible_truncation)]
        let cycle = cycles.floor() as i64;
        cycle
    }

    /// The first cycle that starts strictly after `now`.
    /// Used for **new** slots to skip cycles that elapsed before the slot
    /// existed — prevents a burst of past-due events on first appearance.
    fn first_future_cycle(&self, now: Instant) -> i64 {
        self.current_cycle(now) + 1
    }

    /// Advance the heap: query all patterns for cycles within `[now, now+lookahead)`.
    /// Each cycle is queried exactly once; `next_cycle` tracks the frontier.
    ///
    /// # Panics
    /// Panics if pattern evaluation produces an event with `has_onset()` but no
    /// `whole` arc (which the evaluator contract guarantees never happens).
    pub fn fill(&mut self, now: Instant) {
        let horizon = now + self.lookahead;
        for (_name, &idx) in &self.names {
            while self.clock.cycle_start_instant(self.next_cycle[idx]) <= horizon {
                let query_arc = time::Arc::cycle(self.next_cycle[idx] + self.phase_offset[idx]);
                let pattern = &self.slots[idx];
                for event in query(pattern, pattern.root, query_arc) {
                    if event.has_onset() {
                        let onset = event.whole.expect("onset implies whole").start;
                        let fire_at = self.clock.onset_to_instant(onset);
                        if fire_at >= now {
                            self.heap.push(Reverse(TimedEvent {
                                fire_at,
                                event,
                                slot_idx: idx,
                            }));
                        }
                    }
                }
                self.next_cycle[idx] += 1;
            }
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

    /// Resolve a slot index to its name. Returns `"?"` for unknown indices.
    #[must_use]
    pub fn slot_name(&self, idx: usize) -> &str {
        self.names
            .iter()
            .find_map(|(name, &i)| if i == idx { Some(name.as_str()) } else { None })
            .unwrap_or("?")
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
            address: "/audio/set".into(),
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
        assert!(e.next_cycle.iter().all(|&c| c == 0), "BPM change should reset cycle counters");
    }

    #[test]
    fn test_set_beats_per_cycle() {
        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "kick".into(),
            pattern: CompiledPattern::atom(note(36)),
        });
        e.fill(Instant::now());
        let before = e.heap.len();
        assert!(before > 0, "heap should have events after fill");

        e.apply(EngineCommand::SetBeatsPerCycle { beats: 3.0 });
        assert_eq!(e.heap.len(), 0, "meter change should clear heap");
        assert!(e.next_cycle.iter().all(|&c| c == 0), "meter change should reset cycle counters");
        assert_eq!(e.clock.beats_per_cycle(), 3.0);
    }

    #[test]
    fn test_set_beats_per_cycle_same_value_is_noop() {
        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "kick".into(),
            pattern: CompiledPattern::atom(note(36)),
        });
        e.fill(Instant::now());
        let before = e.heap.len();
        assert!(before > 0);

        // Same value as fast_engine (4.0) — should be no-op.
        e.apply(EngineCommand::SetBeatsPerCycle { beats: 4.0 });
        assert_eq!(e.heap.len(), before, "same meter should preserve heap");
    }

    #[test]
    fn apply_set_bpm_same_value_preserves_heap() {
        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "kick".into(),
            pattern: CompiledPattern::atom(note(36)),
        });
        e.fill(Instant::now());
        let before = e.heap.len();
        assert!(before > 0, "heap should have events after fill");
        let before_cycle = e.next_cycle.clone();

        // Same BPM as fast_engine() — should be a no-op.
        e.apply(EngineCommand::SetBpm { bpm: 6000.0 });
        assert_eq!(e.heap.len(), before, "same BPM should preserve heap");
        assert_eq!(e.next_cycle, before_cycle, "same BPM should preserve cycle counter");
    }

    // ── fill ─────────────────────────────────────────────────────────────────

    #[test]
    fn fill_advances_next_cycle() {
        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "s".into(),
            pattern: CompiledPattern::atom(note(60)),
        });
        let before = e.next_cycle[0];
        e.fill(Instant::now());
        assert!(e.next_cycle[0] > before, "fill should advance next_cycle");
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
                window[0].slot_idx, window[0].fire_at,
                window[1].slot_idx, window[1].fire_at,
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
                is_control: false,
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
                window[0].slot_idx, window[0].fire_at,
                window[1].slot_idx, window[1].fire_at,
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
    fn test_set_pattern_from_zero_starts_at_beginning() {
        // A pattern set with SetPatternFromZero should evaluate from cycle 0
        // regardless of how many real cycles have elapsed.
        let mut e = fast_engine();

        // Let the clock run for a few cycles.
        std::thread::sleep(Duration::from_millis(120));

        let now = Instant::now();
        let current = e.current_cycle(now);
        assert!(current > 0, "clock should have advanced past cycle 0");

        e.apply(EngineCommand::SetPatternFromZero {
            name: "mod".into(),
            pattern: CompiledPattern::atom(note(60)),
        });

        // The phase_offset should be set so that effective cycle = next_cycle + offset starts near 0.
        // For a new slot, next_cycle = first_future_cycle = current+1,
        // offset = -current_cycle => effective = (current+1) + (-current) = 1
        // The key point: the effective cycle is near 0, not near `current`.
        let idx = *e.names.get("mod").unwrap();
        let effective = e.next_cycle[idx] + e.phase_offset[idx];
        assert!(effective.abs() <= 1, "effective cycle should be near 0, got {effective}");
    }

    #[test]
    fn test_set_pattern_from_zero_existing_slot() {
        // SetPatternFromZero on an existing slot resets phase offset.
        let mut e = fast_engine();
        e.apply(EngineCommand::SetPattern {
            name: "s".into(),
            pattern: CompiledPattern::atom(note(60)),
        });

        std::thread::sleep(Duration::from_millis(120));

        e.apply(EngineCommand::SetPatternFromZero {
            name: "s".into(),
            pattern: CompiledPattern::atom(note(64)),
        });

        let idx = *e.names.get("s").unwrap();
        assert!(e.phase_offset[idx] < 0, "phase_offset should be negative (= -current_cycle)");
    }

    #[test]
    fn test_normal_set_pattern_keeps_zero_offset() {
        // Normal SetPattern should always set phase_offset = 0.
        let mut e = fast_engine();
        std::thread::sleep(Duration::from_millis(80));
        e.apply(EngineCommand::SetPattern {
            name: "s".into(),
            pattern: CompiledPattern::atom(note(60)),
        });

        let idx = *e.names.get("s").unwrap();
        assert_eq!(e.phase_offset[idx], 0, "normal SetPattern should have offset 0");
    }

    #[test]
    fn test_fill_uses_phase_offset() {
        // SetPatternFromZero should cause fill() to query from effective cycle 0,
        // not the real cycle. We verify by checking that events are produced.
        let mut e = fast_engine();

        std::thread::sleep(Duration::from_millis(80));

        e.apply(EngineCommand::SetPatternFromZero {
            name: "mod".into(),
            pattern: CompiledPattern::atom(note(60)),
        });

        e.fill(Instant::now());
        // Should have events — the pattern starts from effective cycle 0.
        assert!(e.heap.len() > 0, "fill with phase offset should produce events");
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
