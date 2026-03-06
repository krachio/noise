use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;

use midiman::ipc;
use midiman::ipc::protocol::ServerMessage;
use midiman::pattern::query;
use midiman::scheduler::{self, SchedulerConfig};

/// End-to-end: send IR JSON over socket, verify pattern compiles and events fire.
#[test]
fn end_to_end_set_pattern_via_ipc() {
    let socket_path =
        std::env::temp_dir().join(format!("midiman-e2e-{}.sock", std::process::id()));

    let (event_tx, event_rx) = crossbeam_channel::unbounded();

    // Start scheduler at fast BPM for quick test
    let config = SchedulerConfig {
        bpm: 6000.0,
        beats_per_cycle: 4.0,
        lookahead_secs: 0.1,
        tick_interval_secs: 0.001,
    };
    let (sched_handle, slots) = scheduler::start(config, HashMap::new(), event_tx);

    // Start IPC server
    let ipc_handle = ipc::start(socket_path.clone(), Arc::clone(&slots)).unwrap();

    // Connect as client and send a pattern
    let stream = UnixStream::connect(&socket_path).unwrap();
    let mut writer = stream.try_clone().unwrap();
    let mut reader = BufReader::new(stream);

    let pattern_json = r#"{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Fast","factor":[2,1],"child":{"op":"Cat","children":[{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}},{"op":"Atom","value":{"type":"Note","channel":0,"note":64,"velocity":100,"dur":0.5}}]}}}"#;
    writeln!(writer, "{pattern_json}").unwrap();

    let mut resp = String::new();
    reader.read_line(&mut resp).unwrap();
    let msg: ServerMessage = serde_json::from_str(&resp).unwrap();
    assert!(matches!(msg, ServerMessage::Ok { .. }));

    // Verify slot exists and pattern evaluates correctly
    {
        let guard = slots.lock().unwrap();
        let slot = guard.get("d1").expect("d1 slot should exist");
        let pat = slot.load();
        let events = query(&pat, pat.root, midiman::time::Arc::cycle(0));
        // fast 2 $ cat [note60, note64] -> 4 events per cycle
        assert_eq!(events.len(), 4);
    }

    // Wait for scheduler to emit events
    std::thread::sleep(Duration::from_millis(100));

    let events: Vec<_> = event_rx.try_iter().collect();
    assert!(!events.is_empty(), "scheduler should have emitted events");
    assert_eq!(events[0].slot_name, "d1");

    // Hush
    resp.clear();
    writeln!(writer, r#"{{"cmd":"Hush","slot":"d1"}}"#).unwrap();
    reader.read_line(&mut resp).unwrap();
    let msg: ServerMessage = serde_json::from_str(&resp).unwrap();
    assert!(matches!(msg, ServerMessage::Ok { .. }));

    drop(writer);
    ipc_handle.stop();
    sched_handle.stop();
}

/// Verify JSON -> IR -> CompiledPattern -> query produces correct results.
#[test]
fn ir_compile_and_query_integration() {
    let json = r#"{
        "op": "Stack",
        "children": [
            {
                "op": "Cat",
                "children": [
                    {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 60, "velocity": 100, "dur": 0.5}},
                    {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 64, "velocity": 100, "dur": 0.5}},
                    {"op": "Silence"},
                    {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 67, "velocity": 100, "dur": 0.5}}
                ]
            },
            {
                "op": "Atom",
                "value": {"type": "Cc", "channel": 0, "controller": 1, "value": 64}
            }
        ]
    }"#;

    let ir: midiman::ir::IrNode = serde_json::from_str(json).unwrap();
    let pat = midiman::ir::compile(&ir).unwrap();
    let events = query(&pat, pat.root, midiman::time::Arc::cycle(0));

    // Stack of cat[a,b,~,c] + cc -> 3 (from cat, silence excluded) + 1 (cc) = 4
    assert_eq!(events.len(), 4);

    // The CC event should span the full cycle
    let cc_events: Vec<_> = events
        .iter()
        .filter(|e| matches!(e.value, midiman::event::Value::Cc { .. }))
        .collect();
    assert_eq!(cc_events.len(), 1);
    assert_eq!(cc_events[0].part, midiman::time::Arc::cycle(0));
}
