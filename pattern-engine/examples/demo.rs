/// Programmatic usage of pattern-engine without IPC.
///
/// Builds patterns from IR, compiles them, and queries events for a cycle.
/// Run with: `cargo run --example demo`
use pattern_engine::event::Value;
use pattern_engine::ir::{self, IrNode};
use pattern_engine::pattern::query;
use pattern_engine::time::Arc;

fn main() {
    println!("=== pattern-engine demo ===\n");

    // 1. Simple Cat: two notes per cycle
    let cat = IrNode::Cat {
        children: vec![
            IrNode::Atom {
                value: Value::Note {
                    channel: 0,
                    note: 60,
                    velocity: 100,
                    dur: 0.5,
                },
            },
            IrNode::Atom {
                value: Value::Note {
                    channel: 0,
                    note: 64,
                    velocity: 100,
                    dur: 0.5,
                },
            },
        ],
    };
    print_pattern("cat [c4, e4]", &cat, 0);

    // 2. Fast 2: doubles the speed → 4 events per cycle
    let fast = IrNode::Fast {
        factor: [2, 1],
        child: Box::new(cat.clone()),
    };
    print_pattern("fast 2 $ cat [c4, e4]", &fast, 0);

    // 3. Stack: layers two patterns simultaneously
    let stack = IrNode::Stack {
        children: vec![
            IrNode::Atom {
                value: Value::Note {
                    channel: 0,
                    note: 60,
                    velocity: 100,
                    dur: 0.5,
                },
            },
            IrNode::Atom {
                value: Value::Cc {
                    channel: 0,
                    controller: 1,
                    value: 64,
                },
            },
        ],
    };
    print_pattern("stack [note c4, cc 1 64]", &stack, 0);

    // 4. Euclid(3,8): 3 hits spread across 8 slots
    let euclid = IrNode::Euclid {
        pulses: 3,
        steps: 8,
        rotation: 0,
        child: Box::new(IrNode::Atom {
            value: Value::Note {
                channel: 9,
                note: 36,
                velocity: 100,
                dur: 0.25,
            },
        }),
    };
    print_pattern("euclid(3,8) kick", &euclid, 0);

    // 5. Degrade: randomly drops events (prob=0.5, seed=42)
    let degrade = IrNode::Degrade {
        prob: 0.5,
        seed: 42,
        child: Box::new(IrNode::Fast {
            factor: [4, 1],
            child: Box::new(IrNode::Atom {
                value: Value::Note {
                    channel: 0,
                    note: 60,
                    velocity: 100,
                    dur: 0.25,
                },
            }),
        }),
    };
    print_pattern("degrade 0.5 $ fast 4 c4", &degrade, 0);
    print_pattern("degrade 0.5 $ fast 4 c4 (cycle 1)", &degrade, 1);

    println!("Done.");
}

fn print_pattern(label: &str, ir: &IrNode, cycle: i64) {
    let compiled = ir::compile(ir).expect("compile failed");
    let events = query(&compiled, compiled.root, Arc::cycle(cycle));
    println!("--- {label} (cycle {cycle}) ---");
    println!("  {} events:", events.len());
    for (i, e) in events.iter().enumerate() {
        let onset = if e.has_onset() { " [onset]" } else { "" };
        println!("  [{i}] part={:?} value={:?}{onset}", e.part, e.value);
    }
    println!();
}
