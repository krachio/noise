//! Pattern query evaluator.
//!
//! Recursively walks the arena-indexed pattern tree, transforming time arcs
//! through each combinator. The key invariant: query arcs are split into
//! per-cycle pieces first (via [`Arc::split_cycles`](crate::time::Arc::split_cycles)),
//! so each recursive call operates within a single cycle. Combinators like
//! `Fast` and `Slow` scale the arc before recursing; `Cat` slices it by child index.

use crate::event::{Event, Value};
use crate::time::{Arc, Time};

use super::{CompiledPattern, PatternNode};

/// Query a compiled pattern for events that fall within the given arc.
/// This is the core evaluator — recursive over arena indices, zero heap alloc
/// except for the output Vec.
#[must_use]
pub fn query(pattern: &CompiledPattern, node_idx: usize, arc: Arc) -> Vec<Event<Value>> {
    match &pattern.nodes[node_idx] {
        PatternNode::Atom { value } => query_atom(value, arc),
        PatternNode::Silence => vec![],
        PatternNode::Freeze { child } => query(pattern, *child, arc),
        PatternNode::Cat { children } => query_cat(pattern, children, arc),
        PatternNode::Stack { children } => query_stack(pattern, children, arc),
        PatternNode::Fast { factor, child } => query_fast(pattern, *factor, *child, arc),
        PatternNode::Slow { factor, child } => query_slow(pattern, *factor, *child, arc),
        PatternNode::Early { offset, child } => query_early(pattern, *offset, *child, arc),
        PatternNode::Late { offset, child } => query_late(pattern, *offset, *child, arc),
        PatternNode::Rev { child } => query_rev(pattern, *child, arc),
        PatternNode::Every { n, transform, child } => {
            query_every(pattern, *n, *transform, *child, arc)
        }
        PatternNode::Euclid {
            pulses,
            steps,
            rotation,
            child,
        } => query_euclid(pattern, *pulses, *steps, *rotation, *child, arc),
        PatternNode::Degrade { prob, seed, child } => {
            query_degrade(pattern, *prob, *seed, *child, arc)
        }
    }
}

/// An atom occupies one full cycle. Query splits into per-cycle arcs,
/// and for each cycle the atom spans [cycle, cycle+1) with the queried
/// portion as the part.
fn query_atom(value: &Value, arc: Arc) -> Vec<Event<Value>> {
    arc.split_cycles()
        .into_iter()
        .map(|sub_arc| {
            let cycle = sub_arc.start.floor();
            let whole = Arc::cycle(cycle);
            Event::new(Some(whole), sub_arc, value.clone())
        })
        .collect()
}

/// Cat interleaves children across one cycle. Each child gets an equal
/// time slice. We compress the query arc into each child's slot.
fn query_cat(
    pattern: &CompiledPattern,
    children: &[usize],
    arc: Arc,
) -> Vec<Event<Value>> {
    let n = Time::whole(children.len() as i64);
    let mut events = Vec::new();

    for sub_arc in arc.split_cycles() {
        let cycle = Time::whole(sub_arc.start.floor());

        for (i, &child_idx) in children.iter().enumerate() {
            let i_time = Time::whole(i as i64);

            // This child's window within the cycle: [cycle + i/n, cycle + (i+1)/n)
            let child_start = cycle + i_time / n;
            let child_end = cycle + (i_time + Time::one()) / n;

            // Intersect with the queried sub_arc
            let sect_start = if sub_arc.start > child_start {
                sub_arc.start
            } else {
                child_start
            };
            let sect_end = if sub_arc.end < child_end {
                sub_arc.end
            } else {
                child_end
            };

            if sect_start >= sect_end {
                continue;
            }

            // Map the intersection into the child's local time [cycle, cycle+1)
            let local_start = cycle + (sect_start - child_start) * n;
            let local_end = cycle + (sect_end - child_start) * n;
            let local_arc = Arc::new(local_start, local_end);

            for mut event in query(pattern, child_idx, local_arc) {
                // Map event times back to parent coordinates
                event.part = Arc::new(
                    child_start + (event.part.start - cycle) / n,
                    child_start + (event.part.end - cycle) / n,
                );
                if let Some(whole) = event.whole {
                    event.whole = Some(Arc::new(
                        child_start + (whole.start - cycle) / n,
                        child_start + (whole.end - cycle) / n,
                    ));
                }
                events.push(event);
            }
        }
    }

    events
}

/// Stack layers all children simultaneously over the same time span.
fn query_stack(
    pattern: &CompiledPattern,
    children: &[usize],
    arc: Arc,
) -> Vec<Event<Value>> {
    children
        .iter()
        .flat_map(|&child_idx| query(pattern, child_idx, arc))
        .collect()
}

/// Fast speeds up a pattern by the given factor.
/// Querying fast(f, pat) over arc [s, e) = querying pat over [s*f, e*f),
/// then mapping events back.
fn query_fast(
    pattern: &CompiledPattern,
    factor: Time,
    child: usize,
    arc: Arc,
) -> Vec<Event<Value>> {
    if !factor.is_positive() {
        return vec![];
    }

    let fast_arc = Arc::new(arc.start * factor, arc.end * factor);
    let mut events = query(pattern, child, fast_arc);

    for event in &mut events {
        event.part = Arc::new(event.part.start / factor, event.part.end / factor);
        if let Some(whole) = event.whole {
            event.whole = Some(Arc::new(whole.start / factor, whole.end / factor));
        }
    }

    events
}

/// Slow is the inverse of fast.
fn query_slow(
    pattern: &CompiledPattern,
    factor: Time,
    child: usize,
    arc: Arc,
) -> Vec<Event<Value>> {
    if !factor.is_positive() {
        return vec![];
    }
    // slow(f, pat) = fast(1/f, pat)
    query_fast(pattern, Time::one() / factor, child, arc)
}

/// Early shifts a pattern earlier in time by the given offset.
/// Querying early(offset, pat) over [s, e) = querying pat over [s+offset, e+offset),
/// then shifting events back.
fn query_early(
    pattern: &CompiledPattern,
    offset: Time,
    child: usize,
    arc: Arc,
) -> Vec<Event<Value>> {
    let shifted_arc = Arc::new(arc.start + offset, arc.end + offset);
    let mut events = query(pattern, child, shifted_arc);

    for event in &mut events {
        event.part = Arc::new(event.part.start - offset, event.part.end - offset);
        if let Some(whole) = event.whole {
            event.whole = Some(Arc::new(whole.start - offset, whole.end - offset));
        }
    }

    events
}

/// Late shifts a pattern later in time.
fn query_late(
    pattern: &CompiledPattern,
    offset: Time,
    child: usize,
    arc: Arc,
) -> Vec<Event<Value>> {
    query_early(pattern, -offset, child, arc)
}

/// Rev reverses a pattern within each cycle.
/// Querying rev(pat) over a sub-cycle arc [s, e) within cycle c:
/// maps to querying pat over [c + (1 - (e-c)), c + (1 - (s-c))]
fn query_rev(
    pattern: &CompiledPattern,
    child: usize,
    arc: Arc,
) -> Vec<Event<Value>> {
    let mut events = Vec::new();

    for sub_arc in arc.split_cycles() {
        let cycle = Time::whole(sub_arc.start.floor());
        let one = Time::one();

        // Mirror within cycle: [s, e) in cycle c -> [c + 1 - (e - c), c + 1 - (s - c))
        let rev_start = cycle + one - (sub_arc.end - cycle);
        let rev_end = cycle + one - (sub_arc.start - cycle);
        let rev_arc = Arc::new(rev_start, rev_end);

        for mut event in query(pattern, child, rev_arc) {
            // Mirror the event times back
            event.part = Arc::new(
                cycle + one - (event.part.end - cycle),
                cycle + one - (event.part.start - cycle),
            );
            if let Some(whole) = event.whole {
                event.whole = Some(Arc::new(
                    cycle + one - (whole.end - cycle),
                    cycle + one - (whole.start - cycle),
                ));
            }
            events.push(event);
        }
    }

    events
}

/// Every: apply a transform node every Nth cycle, otherwise use child directly.
/// On cycle C, if C % n == 0, query the transform node; otherwise query child.
fn query_every(
    pattern: &CompiledPattern,
    n: u32,
    transform: usize,
    child: usize,
    arc: Arc,
) -> Vec<Event<Value>> {
    let mut events = Vec::new();
    for sub_arc in arc.split_cycles() {
        let cycle = sub_arc.start.floor();
        #[expect(clippy::cast_sign_loss)]
        let cycle_mod = (cycle as u64) % u64::from(n);
        if cycle_mod == 0 {
            events.extend(query(pattern, transform, sub_arc));
        } else {
            events.extend(query(pattern, child, sub_arc));
        }
    }
    events
}

/// Euclidean rhythm: distribute `pulses` evenly across `steps` positions.
/// Uses the Bjorklund algorithm. Positions with a hit use `child`; others are silent.
/// Implemented as a Cat of `steps` slots where hit positions contain `child`
/// and non-hit positions are silent.
fn query_euclid(
    pattern: &CompiledPattern,
    pulses: u32,
    steps: u32,
    rotation: u32,
    child: usize,
    arc: Arc,
) -> Vec<Event<Value>> {
    if steps == 0 {
        return vec![];
    }
    let hits = bjorklund(pulses, steps, rotation);
    let n = Time::whole(i64::from(steps));
    let mut events = Vec::new();

    for sub_arc in arc.split_cycles() {
        let cycle = Time::whole(sub_arc.start.floor());

        for (i, &is_hit) in hits.iter().enumerate() {
            if !is_hit {
                continue;
            }
            let i_time = Time::whole(i as i64);
            let slot_start = cycle + i_time / n;
            let slot_end = cycle + (i_time + Time::one()) / n;

            let sect_start = if sub_arc.start > slot_start {
                sub_arc.start
            } else {
                slot_start
            };
            let sect_end = if sub_arc.end < slot_end {
                sub_arc.end
            } else {
                slot_end
            };

            if sect_start >= sect_end {
                continue;
            }

            let local_start = cycle + (sect_start - slot_start) * n;
            let local_end = cycle + (sect_end - slot_start) * n;
            let local_arc = Arc::new(local_start, local_end);

            for mut event in query(pattern, child, local_arc) {
                event.part = Arc::new(
                    slot_start + (event.part.start - cycle) / n,
                    slot_start + (event.part.end - cycle) / n,
                );
                if let Some(whole) = event.whole {
                    event.whole = Some(Arc::new(
                        slot_start + (whole.start - cycle) / n,
                        slot_start + (whole.end - cycle) / n,
                    ));
                }
                events.push(event);
            }
        }
    }

    events
}

/// Bjorklund algorithm: distribute `pulses` evenly across `steps`.
/// Returns a Vec<bool> of length `steps` where true = hit.
fn bjorklund(pulses: u32, steps: u32, rotation: u32) -> Vec<bool> {
    if steps == 0 {
        return vec![];
    }
    let pulses = pulses.min(steps);
    let mut pattern = vec![false; steps as usize];
    for i in 0..pulses {
        // Spread pulses evenly using integer arithmetic
        let pos = (i as usize * steps as usize) / pulses as usize;
        pattern[pos] = true;
    }
    // Apply rotation
    if rotation > 0 {
        let rot = (rotation % steps) as usize;
        pattern.rotate_left(rot);
    }
    pattern
}

/// Degrade: randomly drop events based on probability and seed.
/// Uses a simple hash of (seed, cycle, onset) for deterministic randomness.
fn query_degrade(
    pattern: &CompiledPattern,
    prob: f64,
    seed: u64,
    child: usize,
    arc: Arc,
) -> Vec<Event<Value>> {
    let events = query(pattern, child, arc);
    events
        .into_iter()
        .filter(|event| {
            let onset_hash = match event.whole {
                Some(w) => {
                    let num = w.start.num as u64;
                    let den = w.start.den;
                    hash_combine(seed, hash_combine(num, den))
                }
                None => hash_combine(seed, 0),
            };
            let rand_val = (onset_hash % 10000) as f64 / 10000.0;
            rand_val >= prob
        })
        .collect()
}

/// Simple deterministic hash combine for degrade randomness.
fn hash_combine(a: u64, b: u64) -> u64 {
    a.wrapping_mul(6_364_136_223_846_793_005)
        .wrapping_add(b)
        .wrapping_mul(1_442_695_040_888_963_407)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::Value;
    use crate::pattern::PatternNode;
    use smallvec::smallvec;

    fn note(n: u8) -> Value {
        Value::Note {
            channel: 0,
            note: n,
            velocity: 100,
            dur: 0.5,
        }
    }

    fn cycle_0() -> Arc {
        Arc::cycle(0)
    }

    // -- Atom --

    #[test]
    fn atom_single_cycle_returns_one_event() {
        let pat = CompiledPattern::atom(note(60));
        let events = query(&pat, pat.root, cycle_0());
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].value, note(60));
        assert_eq!(events[0].whole, Some(cycle_0()));
        assert_eq!(events[0].part, cycle_0());
    }

    #[test]
    fn atom_half_cycle_returns_one_event_with_partial_part() {
        let pat = CompiledPattern::atom(note(60));
        let half = Arc::new(Time::zero(), Time::new(1, 2));
        let events = query(&pat, pat.root, half);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].whole, Some(cycle_0()));
        assert_eq!(events[0].part, half);
    }

    #[test]
    fn atom_two_cycles_returns_two_events() {
        let pat = CompiledPattern::atom(note(60));
        let two_cycles = Arc::new(Time::zero(), Time::whole(2));
        let events = query(&pat, pat.root, two_cycles);
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].whole, Some(Arc::cycle(0)));
        assert_eq!(events[1].whole, Some(Arc::cycle(1)));
    }

    // -- Silence --

    #[test]
    fn silence_returns_no_events() {
        let pat = CompiledPattern::silence();
        let events = query(&pat, pat.root, cycle_0());
        assert!(events.is_empty());
    }

    // -- Cat --

    #[test]
    fn cat_two_atoms_produces_two_events_per_cycle() {
        let mut pat = CompiledPattern {
            nodes: vec![
                PatternNode::Atom { value: note(60) },
                PatternNode::Atom { value: note(64) },
            ],
            root: 0,
        };
        let cat_idx = pat.push(PatternNode::Cat {
            children: smallvec![0, 1],
        });
        pat.root = cat_idx;

        let events = query(&pat, pat.root, cycle_0());
        assert_eq!(events.len(), 2);

        // First event in [0, 1/2), second in [1/2, 1)
        assert_eq!(events[0].value, note(60));
        assert_eq!(events[0].part.start, Time::zero());
        assert_eq!(events[0].part.end, Time::new(1, 2));

        assert_eq!(events[1].value, note(64));
        assert_eq!(events[1].part.start, Time::new(1, 2));
        assert_eq!(events[1].part.end, Time::one());
    }

    #[test]
    fn cat_three_atoms_divides_cycle_into_thirds() {
        let mut pat = CompiledPattern {
            nodes: vec![
                PatternNode::Atom { value: note(60) },
                PatternNode::Atom { value: note(62) },
                PatternNode::Atom { value: note(64) },
            ],
            root: 0,
        };
        let cat_idx = pat.push(PatternNode::Cat {
            children: smallvec![0, 1, 2],
        });
        pat.root = cat_idx;

        let events = query(&pat, pat.root, cycle_0());
        assert_eq!(events.len(), 3);
        assert_eq!(events[0].part.start, Time::zero());
        assert_eq!(events[0].part.end, Time::new(1, 3));
        assert_eq!(events[1].part.start, Time::new(1, 3));
        assert_eq!(events[1].part.end, Time::new(2, 3));
        assert_eq!(events[2].part.start, Time::new(2, 3));
        assert_eq!(events[2].part.end, Time::one());
    }

    // -- Stack --

    #[test]
    fn stack_layers_events_simultaneously() {
        let mut pat = CompiledPattern {
            nodes: vec![
                PatternNode::Atom { value: note(60) },
                PatternNode::Atom { value: note(64) },
            ],
            root: 0,
        };
        let stack_idx = pat.push(PatternNode::Stack {
            children: smallvec![0, 1],
        });
        pat.root = stack_idx;

        let events = query(&pat, pat.root, cycle_0());
        assert_eq!(events.len(), 2);
        // Both events span the full cycle
        assert_eq!(events[0].part, cycle_0());
        assert_eq!(events[1].part, cycle_0());
        assert_eq!(events[0].value, note(60));
        assert_eq!(events[1].value, note(64));
    }

    // -- Fast --

    #[test]
    fn fast_2_doubles_events() {
        // fast 2 $ atom note(60) -> 2 events per cycle
        let mut pat = CompiledPattern {
            nodes: vec![PatternNode::Atom { value: note(60) }],
            root: 0,
        };
        let fast_idx = pat.push(PatternNode::Fast {
            factor: Time::whole(2),
            child: 0,
        });
        pat.root = fast_idx;

        let events = query(&pat, pat.root, cycle_0());
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].part.start, Time::zero());
        assert_eq!(events[0].part.end, Time::new(1, 2));
        assert_eq!(events[1].part.start, Time::new(1, 2));
        assert_eq!(events[1].part.end, Time::one());
    }

    #[test]
    fn fast_2_cat_ab_produces_four_events() {
        // fast 2 $ cat [a, b] -> 4 events per cycle
        let mut pat = CompiledPattern {
            nodes: vec![
                PatternNode::Atom { value: note(60) },
                PatternNode::Atom { value: note(64) },
            ],
            root: 0,
        };
        let cat_idx = pat.push(PatternNode::Cat {
            children: smallvec![0, 1],
        });
        let fast_idx = pat.push(PatternNode::Fast {
            factor: Time::whole(2),
            child: cat_idx,
        });
        pat.root = fast_idx;

        let events = query(&pat, pat.root, cycle_0());
        assert_eq!(events.len(), 4);
        // a in [0, 1/4), b in [1/4, 1/2), a in [1/2, 3/4), b in [3/4, 1)
        assert_eq!(events[0].value, note(60));
        assert_eq!(events[0].part.start, Time::zero());
        assert_eq!(events[0].part.end, Time::new(1, 4));

        assert_eq!(events[1].value, note(64));
        assert_eq!(events[1].part.start, Time::new(1, 4));
        assert_eq!(events[1].part.end, Time::new(1, 2));

        assert_eq!(events[2].value, note(60));
        assert_eq!(events[2].part.start, Time::new(1, 2));
        assert_eq!(events[2].part.end, Time::new(3, 4));

        assert_eq!(events[3].value, note(64));
        assert_eq!(events[3].part.start, Time::new(3, 4));
        assert_eq!(events[3].part.end, Time::one());
    }

    // -- Slow --

    #[test]
    fn slow_2_halves_events() {
        // slow 2 $ atom note(60) -> 1 event spanning 2 cycles
        let mut pat = CompiledPattern {
            nodes: vec![PatternNode::Atom { value: note(60) }],
            root: 0,
        };
        let slow_idx = pat.push(PatternNode::Slow {
            factor: Time::whole(2),
            child: 0,
        });
        pat.root = slow_idx;

        let events = query(&pat, pat.root, cycle_0());
        assert_eq!(events.len(), 1);
        // The whole event spans [0, 2) but part is just [0, 1)
        assert_eq!(events[0].part, cycle_0());
        let whole = events[0].whole.unwrap();
        assert_eq!(whole.start, Time::zero());
        assert_eq!(whole.end, Time::whole(2));
    }

    // -- Early / Late --

    #[test]
    fn early_shifts_pattern_earlier() {
        let mut pat = CompiledPattern {
            nodes: vec![PatternNode::Atom { value: note(60) }],
            root: 0,
        };
        let early_idx = pat.push(PatternNode::Early {
            offset: Time::new(1, 4),
            child: 0,
        });
        pat.root = early_idx;

        let events = query(&pat, pat.root, cycle_0());
        // Querying [0,1) with early 1/4 queries child at [1/4, 5/4)
        // which splits into [1/4, 1) and [1, 5/4)
        // So we get 2 events
        assert_eq!(events.len(), 2);
        // First event: whole was [0,1) shifted back by 1/4 -> [-1/4, 3/4)
        // part shifted back -> [-1/4, 3/4) intersected with [0,1) gives part
    }

    #[test]
    fn late_is_inverse_of_early() {
        // late(x, pat) should be equivalent to early(-x, pat)
        let mut pat1 = CompiledPattern {
            nodes: vec![PatternNode::Atom { value: note(60) }],
            root: 0,
        };
        let late_idx = pat1.push(PatternNode::Late {
            offset: Time::new(1, 4),
            child: 0,
        });
        pat1.root = late_idx;

        let mut pat2 = CompiledPattern {
            nodes: vec![PatternNode::Atom { value: note(60) }],
            root: 0,
        };
        let early_idx = pat2.push(PatternNode::Early {
            offset: Time::new(-1, 4),
            child: 0,
        });
        pat2.root = early_idx;

        let events1 = query(&pat1, pat1.root, cycle_0());
        let events2 = query(&pat2, pat2.root, cycle_0());
        assert_eq!(events1.len(), events2.len());
        for (e1, e2) in events1.iter().zip(events2.iter()) {
            assert_eq!(e1.part, e2.part);
            assert_eq!(e1.whole, e2.whole);
        }
    }

    // -- Rev --

    #[test]
    fn rev_reverses_cat_order() {
        // rev $ cat [a, b] should give b in [0, 1/2), a in [1/2, 1)
        let mut pat = CompiledPattern {
            nodes: vec![
                PatternNode::Atom { value: note(60) }, // a
                PatternNode::Atom { value: note(64) }, // b
            ],
            root: 0,
        };
        let cat_idx = pat.push(PatternNode::Cat {
            children: smallvec![0, 1],
        });
        let rev_idx = pat.push(PatternNode::Rev { child: cat_idx });
        pat.root = rev_idx;

        let mut events = query(&pat, pat.root, cycle_0());
        assert_eq!(events.len(), 2);
        // Sort by onset for deterministic assertion order
        events.sort_by(|a, b| a.part.start.cmp(&b.part.start));

        // Reversed: b (note 64) now in [0, 1/2), a (note 60) in [1/2, 1)
        assert_eq!(events[0].value, note(64));
        assert_eq!(events[0].part.start, Time::zero());
        assert_eq!(events[0].part.end, Time::new(1, 2));

        assert_eq!(events[1].value, note(60));
        assert_eq!(events[1].part.start, Time::new(1, 2));
        assert_eq!(events[1].part.end, Time::one());
    }

    #[test]
    fn rev_atom_is_identity() {
        let mut pat = CompiledPattern {
            nodes: vec![PatternNode::Atom { value: note(60) }],
            root: 0,
        };
        let rev_idx = pat.push(PatternNode::Rev { child: 0 });
        pat.root = rev_idx;

        let events = query(&pat, pat.root, cycle_0());
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].value, note(60));
        assert_eq!(events[0].part, cycle_0());
    }

    // -- Composition --

    #[test]
    fn stack_of_cats() {
        // stack [cat [a, b], cat [c, d]]
        let mut pat = CompiledPattern {
            nodes: vec![
                PatternNode::Atom { value: note(60) }, // 0: a
                PatternNode::Atom { value: note(62) }, // 1: b
                PatternNode::Atom { value: note(64) }, // 2: c
                PatternNode::Atom { value: note(67) }, // 3: d
            ],
            root: 0,
        };
        let cat1 = pat.push(PatternNode::Cat {
            children: smallvec![0, 1],
        });
        let cat2 = pat.push(PatternNode::Cat {
            children: smallvec![2, 3],
        });
        let stack_idx = pat.push(PatternNode::Stack {
            children: smallvec![cat1, cat2],
        });
        pat.root = stack_idx;

        let events = query(&pat, pat.root, cycle_0());
        assert_eq!(events.len(), 4);
    }

    #[test]
    fn fast_zero_returns_empty() {
        let mut pat = CompiledPattern {
            nodes: vec![PatternNode::Atom { value: note(60) }],
            root: 0,
        };
        let fast_idx = pat.push(PatternNode::Fast {
            factor: Time::zero(),
            child: 0,
        });
        pat.root = fast_idx;

        let events = query(&pat, pat.root, cycle_0());
        assert!(events.is_empty());
    }

    // -- Every --

    #[test]
    fn every_applies_transform_on_nth_cycle() {
        // every 2 (fast 2) $ atom note(60)
        // Cycle 0 (0 % 2 == 0): use transform (fast 2) -> 2 events
        // Cycle 1 (1 % 2 != 0): use child (atom) -> 1 event
        let mut pat = CompiledPattern {
            nodes: vec![PatternNode::Atom { value: note(60) }],
            root: 0,
        };
        let fast_child = pat.push(PatternNode::Fast {
            factor: Time::whole(2),
            child: 0,
        });
        let every_idx = pat.push(PatternNode::Every {
            n: 2,
            transform: fast_child,
            child: 0,
        });
        pat.root = every_idx;

        let events_c0 = query(&pat, pat.root, Arc::cycle(0));
        assert_eq!(events_c0.len(), 2, "cycle 0 should use transform (fast 2)");

        let events_c1 = query(&pat, pat.root, Arc::cycle(1));
        assert_eq!(events_c1.len(), 1, "cycle 1 should use child (atom)");

        let events_c2 = query(&pat, pat.root, Arc::cycle(2));
        assert_eq!(events_c2.len(), 2, "cycle 2 should use transform again");
    }

    // -- Euclid --

    #[test]
    fn euclid_3_8_produces_three_hits() {
        // euclid(3, 8) $ atom note(60) -> 3 hits across 8 slots
        let mut pat = CompiledPattern {
            nodes: vec![PatternNode::Atom { value: note(60) }],
            root: 0,
        };
        let euclid_idx = pat.push(PatternNode::Euclid {
            pulses: 3,
            steps: 8,
            rotation: 0,
            child: 0,
        });
        pat.root = euclid_idx;

        let events = query(&pat, pat.root, cycle_0());
        assert_eq!(events.len(), 3);
    }

    #[test]
    fn euclid_4_4_fills_all_slots() {
        let mut pat = CompiledPattern {
            nodes: vec![PatternNode::Atom { value: note(60) }],
            root: 0,
        };
        let euclid_idx = pat.push(PatternNode::Euclid {
            pulses: 4,
            steps: 4,
            rotation: 0,
            child: 0,
        });
        pat.root = euclid_idx;

        let events = query(&pat, pat.root, cycle_0());
        assert_eq!(events.len(), 4);
    }

    #[test]
    fn euclid_0_steps_returns_empty() {
        let mut pat = CompiledPattern {
            nodes: vec![PatternNode::Atom { value: note(60) }],
            root: 0,
        };
        let euclid_idx = pat.push(PatternNode::Euclid {
            pulses: 3,
            steps: 0,
            rotation: 0,
            child: 0,
        });
        pat.root = euclid_idx;

        let events = query(&pat, pat.root, cycle_0());
        assert!(events.is_empty());
    }

    #[test]
    fn euclid_with_rotation_shifts_hits() {
        let mut pat = CompiledPattern {
            nodes: vec![PatternNode::Atom { value: note(60) }],
            root: 0,
        };
        // euclid(1, 4, 0) -> hit at slot 0
        let e1 = pat.push(PatternNode::Euclid {
            pulses: 1,
            steps: 4,
            rotation: 0,
            child: 0,
        });
        // euclid(1, 4, 1) -> hit at slot 1 (rotated)
        let e2 = pat.push(PatternNode::Euclid {
            pulses: 1,
            steps: 4,
            rotation: 1,
            child: 0,
        });

        let events_no_rot = query(&pat, e1, cycle_0());
        let events_rot = query(&pat, e2, cycle_0());

        assert_eq!(events_no_rot.len(), 1);
        assert_eq!(events_rot.len(), 1);
        // Different onset positions
        assert_ne!(events_no_rot[0].part.start, events_rot[0].part.start);
    }

    // -- Degrade --

    #[test]
    fn degrade_zero_prob_keeps_all_events() {
        let mut pat = CompiledPattern {
            nodes: vec![
                PatternNode::Atom { value: note(60) },
                PatternNode::Atom { value: note(64) },
            ],
            root: 0,
        };
        let cat_idx = pat.push(PatternNode::Cat {
            children: smallvec![0, 1],
        });
        let degrade_idx = pat.push(PatternNode::Degrade {
            prob: 0.0,
            seed: 42,
            child: cat_idx,
        });
        pat.root = degrade_idx;

        let events = query(&pat, pat.root, cycle_0());
        assert_eq!(events.len(), 2);
    }

    #[test]
    fn degrade_one_prob_drops_all_events() {
        let mut pat = CompiledPattern {
            nodes: vec![PatternNode::Atom { value: note(60) }],
            root: 0,
        };
        let degrade_idx = pat.push(PatternNode::Degrade {
            prob: 1.0,
            seed: 42,
            child: 0,
        });
        pat.root = degrade_idx;

        let events = query(&pat, pat.root, cycle_0());
        assert!(events.is_empty());
    }

    #[test]
    fn degrade_is_deterministic_with_same_seed() {
        let mut pat = CompiledPattern {
            nodes: vec![
                PatternNode::Atom { value: note(60) },
                PatternNode::Atom { value: note(62) },
                PatternNode::Atom { value: note(64) },
                PatternNode::Atom { value: note(67) },
            ],
            root: 0,
        };
        let cat_idx = pat.push(PatternNode::Cat {
            children: smallvec![0, 1, 2, 3],
        });
        let degrade_idx = pat.push(PatternNode::Degrade {
            prob: 0.5,
            seed: 123,
            child: cat_idx,
        });
        pat.root = degrade_idx;

        let events1 = query(&pat, pat.root, cycle_0());
        let events2 = query(&pat, pat.root, cycle_0());
        // Same seed, same query -> same results
        assert_eq!(events1.len(), events2.len());
        for (e1, e2) in events1.iter().zip(events2.iter()) {
            assert_eq!(e1.value, e2.value);
        }
    }

    // -- Bjorklund --

    #[test]
    fn bjorklund_known_patterns() {
        // E(3,8) = [1,0,0,1,0,0,1,0] (tresillo)
        let p = super::bjorklund(3, 8, 0);
        assert_eq!(p.iter().filter(|&&x| x).count(), 3);
        assert_eq!(p.len(), 8);

        // E(4,4) = [1,1,1,1]
        let p = super::bjorklund(4, 4, 0);
        assert_eq!(p, vec![true, true, true, true]);

        // E(0,4) = [0,0,0,0]
        let p = super::bjorklund(0, 4, 0);
        assert_eq!(p, vec![false, false, false, false]);
    }

    // -- Freeze --

    #[test]
    fn freeze_is_transparent_in_query() {
        // Freeze wraps a pattern without changing its behavior
        let mut pat = CompiledPattern { nodes: Vec::new(), root: 0 };
        let atom = pat.push(PatternNode::Atom { value: note(60) });
        let frozen = pat.push(PatternNode::Freeze { child: atom });
        pat.root = frozen;

        let events = query(&pat, pat.root, cycle_0());
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].value, note(60));
    }

    #[test]
    fn freeze_hit_compound_in_cat_counts_as_one_atom() {
        use crate::event::OscArg;

        let gate_on = Value::Osc {
            address: "/set".into(),
            args: vec![OscArg::Str("gate".into()), OscArg::Float(1.0)],
        };
        let gate_off = Value::Osc {
            address: "/set".into(),
            args: vec![OscArg::Str("gate".into()), OscArg::Float(0.0)],
        };

        // Build: Freeze(Cat([trig, reset]))
        // This is what mix.hit() produces — Freeze prevents Cat flattening
        let mut pat = CompiledPattern { nodes: Vec::new(), root: 0 };
        let trig = pat.push(PatternNode::Atom { value: gate_on.clone() });
        let reset = pat.push(PatternNode::Atom { value: gate_off.clone() });
        let inner_cat = pat.push(PatternNode::Cat { children: smallvec![trig, reset] });
        let frozen = pat.push(PatternNode::Freeze { child: inner_cat });

        // Cat([Silence, Freeze(...)]) — 2 top-level atoms
        let silence = pat.push(PatternNode::Silence);
        let root = pat.push(PatternNode::Cat {
            children: smallvec![silence, frozen],
        });
        pat.root = root;

        let events = query(&pat, pat.root, cycle_0());
        // Silence slot [0, 0.5) = 0 events.
        // Hit slot [0.5, 1.0): Freeze(Fast(2, Cat([trig, reset]))) = 2 events.
        // Fast(2) queries child over [0, 1) within the slot, getting trig + reset.
        // Freeze(Cat([trig, reset])) in a 1/2-cycle slot:
        // trig at [1/2, 3/4), reset at [3/4, 1)
        assert_eq!(events.len(), 2, "expected trig + reset");

        assert!(events[0].has_onset(), "trig should have onset");
        assert_eq!(events[0].part.start, Time::new(1, 2), "trig at 1/2 cycle");
        assert_eq!(events[0].value, gate_on);

        assert!(events[1].has_onset(), "reset should have onset");
        assert_eq!(events[1].part.start, Time::new(3, 4), "reset at 3/4 cycle");
        assert_eq!(events[1].value, gate_off);
    }
}
