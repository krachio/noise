use smallvec::SmallVec;

use crate::pattern::{CompiledPattern, PatternNode};
use crate::time::Time;

use super::{IrError, IrNode};

/// Compile a validated IR tree into a `CompiledPattern`.
/// Walks the IR recursively, appending nodes to the arena.
pub fn compile(ir: &IrNode) -> Result<CompiledPattern, IrError> {
    super::validate(ir)?;
    let mut pattern = CompiledPattern {
        nodes: Vec::new(),
        root: 0,
        is_control: false,
    };
    let root = compile_node(ir, &mut pattern);
    pattern.root = root;
    pattern.is_control = CompiledPattern::detect_control(&pattern.nodes);
    Ok(pattern)
}

fn compile_node(ir: &IrNode, pattern: &mut CompiledPattern) -> usize {
    match ir {
        IrNode::Atom { value } => pattern.push(PatternNode::Atom {
            value: value.clone(),
        }),
        IrNode::Silence => pattern.push(PatternNode::Silence),
        IrNode::Freeze { child } => {
            let child_idx = compile_node(child, pattern);
            pattern.push(PatternNode::Freeze { child: child_idx })
        }
        IrNode::Cat { children } => {
            let child_indices: SmallVec<[usize; 8]> =
                children.iter().map(|c| compile_node(c, pattern)).collect();
            pattern.push(PatternNode::Cat {
                children: child_indices,
            })
        }
        IrNode::Stack { children } => {
            let child_indices: SmallVec<[usize; 8]> =
                children.iter().map(|c| compile_node(c, pattern)).collect();
            pattern.push(PatternNode::Stack {
                children: child_indices,
            })
        }
        IrNode::Fast { factor, child } => {
            let child_idx = compile_node(child, pattern);
            let factor = time_from_pair(*factor);
            pattern.push(PatternNode::Fast {
                factor,
                child: child_idx,
            })
        }
        IrNode::Slow { factor, child } => {
            let child_idx = compile_node(child, pattern);
            let factor = time_from_pair(*factor);
            pattern.push(PatternNode::Slow {
                factor,
                child: child_idx,
            })
        }
        IrNode::Early { offset, child } => {
            let child_idx = compile_node(child, pattern);
            let offset = time_from_pair(*offset);
            pattern.push(PatternNode::Early {
                offset,
                child: child_idx,
            })
        }
        IrNode::Late { offset, child } => {
            let child_idx = compile_node(child, pattern);
            let offset = time_from_pair(*offset);
            pattern.push(PatternNode::Late {
                offset,
                child: child_idx,
            })
        }
        IrNode::Rev { child } => {
            let child_idx = compile_node(child, pattern);
            pattern.push(PatternNode::Rev { child: child_idx })
        }
        IrNode::Every { n, transform, child } => {
            let transform_idx = compile_node(transform, pattern);
            let child_idx = compile_node(child, pattern);
            pattern.push(PatternNode::Every {
                n: *n,
                transform: transform_idx,
                child: child_idx,
            })
        }
        IrNode::Euclid {
            pulses,
            steps,
            rotation,
            child,
        } => {
            let child_idx = compile_node(child, pattern);
            pattern.push(PatternNode::Euclid {
                pulses: *pulses,
                steps: *steps,
                rotation: *rotation,
                child: child_idx,
            })
        }
        IrNode::Degrade { prob, seed, child } => {
            let child_idx = compile_node(child, pattern);
            pattern.push(PatternNode::Degrade {
                prob: *prob,
                seed: *seed,
                child: child_idx,
            })
        }
        IrNode::Warp { kind, amount, grid, child } => {
            let child_idx = compile_node(child, pattern);
            let kind_id = match kind.as_str() {
                "swing" => crate::pattern::WARP_SWING,
                _ => 0, // validation catches unknown kinds before we get here
            };
            pattern.push(PatternNode::Warp {
                kind: kind_id,
                amount: *amount,
                grid: *grid,
                child: child_idx,
            })
        }
    }
}

fn time_from_pair(pair: [i64; 2]) -> Time {
    #[expect(clippy::cast_sign_loss)]
    Time::new(pair[0], pair[1] as u64)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::Value;
    use crate::pattern::query;
    use crate::time::Arc;

    fn note(n: u8) -> Value {
        Value::Note {
            channel: 0,
            note: n,
            velocity: 100,
            dur: 0.5,
        }
    }

    #[test]
    fn compile_atom_and_query() {
        let ir = IrNode::Atom { value: note(60) };
        let pat = compile(&ir).unwrap();
        let events = query(&pat, pat.root, Arc::cycle(0));
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].value, note(60));
    }

    #[test]
    fn compile_cat_and_query() {
        let ir = IrNode::Cat {
            children: vec![
                IrNode::Atom { value: note(60) },
                IrNode::Atom { value: note(64) },
            ],
        };
        let pat = compile(&ir).unwrap();
        let events = query(&pat, pat.root, Arc::cycle(0));
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].value, note(60));
        assert_eq!(events[1].value, note(64));
    }

    #[test]
    fn compile_fast_cat_and_query() {
        // fast 2 $ cat [60, 64] -> 4 events per cycle
        let ir = IrNode::Fast {
            factor: [2, 1],
            child: Box::new(IrNode::Cat {
                children: vec![
                    IrNode::Atom { value: note(60) },
                    IrNode::Atom { value: note(64) },
                ],
            }),
        };
        let pat = compile(&ir).unwrap();
        let events = query(&pat, pat.root, Arc::cycle(0));
        assert_eq!(events.len(), 4);
    }

    #[test]
    fn compile_from_json() {
        let json = r#"{
            "op": "Cat",
            "children": [
                {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 60, "velocity": 100, "dur": 0.5}},
                {"op": "Silence"},
                {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 64, "velocity": 100, "dur": 0.5}}
            ]
        }"#;
        let ir: IrNode = serde_json::from_str(json).unwrap();
        let pat = compile(&ir).unwrap();
        let events = query(&pat, pat.root, Arc::cycle(0));
        // Cat [atom, silence, atom] -> 2 events (silence produces none)
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].value, note(60));
        assert_eq!(events[1].value, note(64));
    }

    #[test]
    fn compile_stack_from_json() {
        let json = r#"{
            "op": "Stack",
            "children": [
                {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 60, "velocity": 100, "dur": 0.5}},
                {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 64, "velocity": 100, "dur": 0.5}}
            ]
        }"#;
        let ir: IrNode = serde_json::from_str(json).unwrap();
        let pat = compile(&ir).unwrap();
        let events = query(&pat, pat.root, Arc::cycle(0));
        assert_eq!(events.len(), 2);
    }

    #[test]
    fn compile_nested_fast_from_json() {
        let json = r#"{
            "op": "Fast",
            "factor": [3, 1],
            "child": {
                "op": "Cat",
                "children": [
                    {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 60, "velocity": 100, "dur": 0.5}},
                    {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 64, "velocity": 100, "dur": 0.5}}
                ]
            }
        }"#;
        let ir: IrNode = serde_json::from_str(json).unwrap();
        let pat = compile(&ir).unwrap();
        let events = query(&pat, pat.root, Arc::cycle(0));
        // fast 3 $ cat [a, b] -> 6 events per cycle
        assert_eq!(events.len(), 6);
    }

    #[test]
    fn compile_rejects_invalid_ir() {
        let ir = IrNode::Cat { children: vec![] };
        assert!(compile(&ir).is_err());
    }

    #[test]
    fn compile_rev_from_json() {
        let json = r#"{
            "op": "Rev",
            "child": {
                "op": "Cat",
                "children": [
                    {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 60, "velocity": 100, "dur": 0.5}},
                    {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 64, "velocity": 100, "dur": 0.5}}
                ]
            }
        }"#;
        let ir: IrNode = serde_json::from_str(json).unwrap();
        let pat = compile(&ir).unwrap();
        let mut events = query(&pat, pat.root, Arc::cycle(0));
        events.sort_by(|a, b| a.part.start.cmp(&b.part.start));
        assert_eq!(events.len(), 2);
        // Reversed: 64 first, 60 second
        assert_eq!(events[0].value, note(64));
        assert_eq!(events[1].value, note(60));
    }

    #[test]
    fn freeze_deserializes_from_json() {
        let json = r#"{
            "op": "Freeze",
            "child": {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 60, "velocity": 100, "dur": 0.5}}
        }"#;
        let ir: IrNode = serde_json::from_str(json).unwrap();
        assert!(matches!(ir, IrNode::Freeze { .. }));

        let pat = compile(&ir).unwrap();
        let events = query(&pat, pat.root, Arc::cycle(0));
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].value, note(60));
    }

    #[test]
    fn freeze_hit_compound_from_json() {
        // What Python sends for: rest() + mix.hit("clap", "gate")
        // = Cat([Silence, Freeze(Cat([trig, reset]))])
        let json = r#"{
            "op": "Cat",
            "children": [
                {"op": "Silence"},
                {
                    "op": "Freeze",
                    "child": {
                        "op": "Cat",
                        "children": [
                            {"op": "Atom", "value": {"type": "Osc", "address": "/set", "args": [{"Str": "gate"}, {"Float": 1.0}]}},
                            {"op": "Atom", "value": {"type": "Osc", "address": "/set", "args": [{"Str": "gate"}, {"Float": 0.0}]}}
                        ]
                    }
                }
            ]
        }"#;
        let ir: IrNode = serde_json::from_str(json).unwrap();
        let pat = compile(&ir).unwrap();

        // Query 2 cycles — each cycle: trig + reset = 2. Over 2 cycles = 4.
        let events = query(&pat, pat.root, Arc::new(Time::zero(), Time::whole(2)));
        assert_eq!(events.len(), 4, "expected 4 events over 2 cycles, got {}", events.len());

        // All events must be schedulable
        for (i, e) in events.iter().enumerate() {
            assert!(e.has_onset(), "event {i} should have onset");
        }
    }

    #[test]
    fn compile_warp_from_json() {
        let json = r#"{
            "op": "Warp",
            "kind": "swing",
            "amount": 0.67,
            "grid": 8,
            "child": {
                "op": "Cat",
                "children": [
                    {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 60, "velocity": 100, "dur": 0.5}},
                    {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 64, "velocity": 100, "dur": 0.5}}
                ]
            }
        }"#;
        let ir: IrNode = serde_json::from_str(json).unwrap();
        let pat = compile(&ir).unwrap();
        // 2 atoms + 1 cat + 1 warp = 4 nodes
        assert_eq!(pat.nodes.len(), 4);
    }

    #[test]
    fn is_control_true_for_all_control_atoms() {
        let ir = IrNode::Cat {
            children: vec![
                IrNode::Atom {
                    value: Value::Control { label: "gate".into(), value: 1.0 },
                },
                IrNode::Atom {
                    value: Value::Control { label: "gate".into(), value: 0.0 },
                },
            ],
        };
        let pat = compile(&ir).unwrap();
        assert!(pat.is_control);
    }

    #[test]
    fn is_control_false_for_note_atoms() {
        let ir = IrNode::Cat {
            children: vec![
                IrNode::Atom { value: note(60) },
                IrNode::Atom { value: note(64) },
            ],
        };
        let pat = compile(&ir).unwrap();
        assert!(!pat.is_control);
    }

    #[test]
    fn is_control_false_for_mixed_atoms() {
        let ir = IrNode::Cat {
            children: vec![
                IrNode::Atom {
                    value: Value::Control { label: "freq".into(), value: 440.0 },
                },
                IrNode::Atom { value: note(60) },
            ],
        };
        let pat = compile(&ir).unwrap();
        assert!(!pat.is_control);
    }

    #[test]
    fn is_control_false_for_silence_only() {
        let ir = IrNode::Silence;
        let pat = compile(&ir).unwrap();
        assert!(!pat.is_control);
    }
}
