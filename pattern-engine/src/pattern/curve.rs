//! Compile pattern evaluation output to block-rate wavetables.
//!
//! Given the events from querying one cycle of a Control-voice pattern,
//! [`compile_wavetable`] produces per-parameter wavetables suitable for
//! `AutoShape::Custom` automation on the audio thread.

use std::collections::HashMap;

use crate::event::{Event, Value};

/// Compile Control events from one cycle into per-parameter block-rate wavetables.
///
/// Each parameter gets a `Vec<f32>` of length `table_len` (one entry per audio
/// block in the cycle). Values are sample-and-hold: an event's value persists
/// until the next event on the same parameter. Parameters default to 0.0 before
/// their first event.
///
/// Non-Control events are silently ignored.
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss
)]
#[must_use] pub fn compile_wavetable(events: &[Event<Value>], table_len: usize) -> HashMap<String, Vec<f32>> {
    if table_len == 0 {
        return HashMap::new();
    }

    // Collect (onset_frac, value) per label.
    let mut by_label: HashMap<String, Vec<(f64, f32)>> = HashMap::new();

    for event in events {
        if let Value::Control { label, value } = &event.value
            && let Some(whole) = event.whole {
                // Fractional position within the cycle [0, 1).
                let frac = whole.start.fract();
                let onset = frac.num as f64 / frac.den as f64;
                by_label
                    .entry(label.clone())
                    .or_default()
                    .push((onset, *value));
            }
    }

    // Build wavetable per label.
    let mut tables = HashMap::with_capacity(by_label.len());
    for (label, mut events) in by_label {
        events.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));

        let mut table = vec![0.0_f32; table_len];
        let mut current = 0.0_f32;

        let mut event_idx = 0;
        for i in 0..table_len {
            let t = i as f64 / table_len as f64;
            // Apply all events at or before this block position.
            while event_idx < events.len() && events[event_idx].0 <= t {
                current = events[event_idx].1;
                event_idx += 1;
            }
            table[i] = current;
        }

        tables.insert(label, table);
    }

    tables
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ir;
    use crate::ir::IrNode;
    use crate::pattern::query;
    use crate::time::Arc;

    fn control_event(label: &str, value: f32) -> Value {
        Value::Control {
            label: label.into(),
            value,
        }
    }

    #[test]
    fn single_gate_on_fills_entire_table() {
        let ir = IrNode::Atom {
            value: control_event("gate", 1.0),
        };
        let pat = ir::compile(&ir).unwrap();
        let events = query(&pat, pat.root, Arc::cycle(0));
        let tables = compile_wavetable(&events, 8);
        let gate = &tables["gate"];
        assert_eq!(gate.len(), 8);
        assert!(gate.iter().all(|&v| (v - 1.0).abs() < 1e-5));
    }

    #[test]
    fn cat_gate_on_off_produces_step() {
        // Cat([gate=1, gate=0]) → first half 1.0, second half 0.0
        let ir = IrNode::Cat {
            children: vec![
                IrNode::Atom {
                    value: control_event("gate", 1.0),
                },
                IrNode::Atom {
                    value: control_event("gate", 0.0),
                },
            ],
        };
        let pat = ir::compile(&ir).unwrap();
        let events = query(&pat, pat.root, Arc::cycle(0));
        let tables = compile_wavetable(&events, 8);
        let gate = &tables["gate"];
        assert_eq!(gate.len(), 8);
        // First half = 1.0 (gate on at t=0)
        assert!(
            gate[0..4].iter().all(|&v| (v - 1.0).abs() < 1e-5),
            "first half should be 1.0, got {gate:?}"
        );
        // Second half = 0.0 (gate off at t=0.5)
        assert!(
            gate[4..8].iter().all(|&v| v.abs() < 1e-5),
            "second half should be 0.0, got {gate:?}"
        );
    }

    #[test]
    fn seq_freq_produces_step_function() {
        // Cat([freq=261, freq=330, silence]) → 3-step freq table
        let ir = IrNode::Cat {
            children: vec![
                IrNode::Atom {
                    value: control_event("freq", 261.0),
                },
                IrNode::Atom {
                    value: control_event("freq", 330.0),
                },
                IrNode::Silence,
            ],
        };
        let pat = ir::compile(&ir).unwrap();
        let events = query(&pat, pat.root, Arc::cycle(0));
        let tables = compile_wavetable(&events, 9);
        let freq = &tables["freq"];
        assert_eq!(freq.len(), 9);
        // First third = 261
        assert!(freq[0..3].iter().all(|&v| (v - 261.0).abs() < 1e-3));
        // Second third = 330
        assert!(freq[3..6].iter().all(|&v| (v - 330.0).abs() < 1e-3));
        // Last third = 330 (sample-and-hold, no new event in silence)
        assert!(freq[6..9].iter().all(|&v| (v - 330.0).abs() < 1e-3));
    }

    #[test]
    fn multiple_params_produce_separate_tables() {
        // Stack([freq=440, gate=1]) → two separate tables
        let ir = IrNode::Stack {
            children: vec![
                IrNode::Atom {
                    value: control_event("freq", 440.0),
                },
                IrNode::Atom {
                    value: control_event("gate", 1.0),
                },
            ],
        };
        let pat = ir::compile(&ir).unwrap();
        let events = query(&pat, pat.root, Arc::cycle(0));
        let tables = compile_wavetable(&events, 4);
        assert!(tables.contains_key("freq"));
        assert!(tables.contains_key("gate"));
        assert!(tables["freq"].iter().all(|&v| (v - 440.0).abs() < 1e-3));
        assert!(tables["gate"].iter().all(|&v| (v - 1.0).abs() < 1e-5));
    }

    #[test]
    fn empty_events_produce_empty_map() {
        let tables = compile_wavetable(&[], 8);
        assert!(tables.is_empty());
    }

    #[test]
    fn table_len_one_works() {
        let ir = IrNode::Atom {
            value: control_event("gain", 0.7),
        };
        let pat = ir::compile(&ir).unwrap();
        let events = query(&pat, pat.root, Arc::cycle(0));
        let tables = compile_wavetable(&events, 1);
        assert_eq!(tables["gain"], vec![0.7]);
    }

    #[test]
    fn four_hit_pattern() {
        // hit() * 4 equivalent: Cat([gate=1, gate=0]) repeated 4 times via Fast(4)
        // Simplified: Cat([gate=1, gate=0, gate=1, gate=0, gate=1, gate=0, gate=1, gate=0])
        let ir = IrNode::Fast {
            factor: [4, 1],
            child: Box::new(IrNode::Cat {
                children: vec![
                    IrNode::Atom {
                        value: control_event("gate", 1.0),
                    },
                    IrNode::Atom {
                        value: control_event("gate", 0.0),
                    },
                ],
            }),
        };
        let pat = ir::compile(&ir).unwrap();
        let events = query(&pat, pat.root, Arc::cycle(0));
        let tables = compile_wavetable(&events, 16);
        let gate = &tables["gate"];
        assert_eq!(gate.len(), 16);
        // 4 pulses: each takes 4 blocks (2 on, 2 off)
        for pulse in 0..4 {
            let start = pulse * 4;
            assert!(
                (gate[start] - 1.0).abs() < 1e-5,
                "pulse {pulse} should start with 1.0"
            );
            assert!(
                (gate[start + 2]).abs() < 1e-5,
                "pulse {pulse} should end with 0.0"
            );
        }
    }
}
