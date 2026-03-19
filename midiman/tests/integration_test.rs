mod helpers;

use std::net::UdpSocket;
use std::time::Duration;

use midiman::event::Value;
use midiman::ipc::protocol::ServerMessage;
use midiman::output;
use midiman::output::osc::OscSink;
use midiman::pattern::query;
use midiman::time::Arc;

use helpers::TestKernel;

// ─── Existing tests, refactored to use TestKernel ───

#[test]
fn end_to_end_set_pattern_via_ipc() {
    let tk = TestKernel::start("setpat");
    let mut conn = tk.connect();

    let pattern_json = r#"{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Fast","factor":[2,1],"child":{"op":"Cat","children":[{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}},{"op":"Atom","value":{"type":"Note","channel":0,"note":64,"velocity":100,"dur":0.5}}]}}}"#;
    let resp = conn.send(pattern_json);
    assert!(matches!(resp, ServerMessage::Ok { .. }));

    // Verify slot exists and pattern evaluates correctly
    {
        let guard = tk.slots.lock().unwrap();
        let slot = guard.get("d1").expect("d1 slot should exist");
        let pat = slot.load();
        let events = query(&pat, pat.root, Arc::cycle(0));
        assert_eq!(events.len(), 4, "fast 2 $ cat [n60, n64] -> 4 events");
    }

    // Wait for scheduler to emit events
    let events = tk.collect_events(Duration::from_millis(100));
    assert!(!events.is_empty(), "scheduler should have emitted events");
    assert_eq!(events[0].slot_name, "d1");

    // Hush
    let resp = conn.send(r#"{"cmd":"Hush","slot":"d1"}"#);
    assert!(matches!(resp, ServerMessage::Ok { .. }));

    tk.stop();
}

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
    let events = query(&pat, pat.root, Arc::cycle(0));

    // Stack of cat[a,b,~,c] + cc -> 3 (from cat, silence excluded) + 1 (cc) = 4
    assert_eq!(events.len(), 4);

    let cc_events: Vec<_> = events
        .iter()
        .filter(|e| matches!(e.value, Value::Cc { .. }))
        .collect();
    assert_eq!(cc_events.len(), 1);
    assert_eq!(cc_events[0].part, Arc::cycle(0));
}

// ─── New E2E tests ───

#[test]
fn e2e_ping_pong() {
    let tk = TestKernel::start("ping");
    let resp = tk.send(r#"{"cmd":"Ping"}"#);
    assert!(matches!(resp, ServerMessage::Pong));
    tk.stop();
}

#[test]
fn e2e_multi_slot() {
    let tk = TestKernel::start("multi");
    let mut conn = tk.connect();

    // Set patterns on d1 and d2
    let d1 = r#"{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}}}"#;
    let d2 = r#"{"cmd":"SetPattern","slot":"d2","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":72,"velocity":100,"dur":0.5}}}"#;
    assert!(matches!(conn.send(d1), ServerMessage::Ok { .. }));
    assert!(matches!(conn.send(d2), ServerMessage::Ok { .. }));

    let events = tk.collect_events(Duration::from_millis(150));
    let has_d1 = events.iter().any(|e| e.slot_name == "d1");
    let has_d2 = events.iter().any(|e| e.slot_name == "d2");
    assert!(has_d1, "expected events from d1");
    assert!(has_d2, "expected events from d2");

    tk.stop();
}

#[test]
fn e2e_hotswap_pattern() {
    let tk = TestKernel::start("hotswap");
    let mut conn = tk.connect();

    // Set note 60
    conn.send(r#"{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}}}"#);
    let events_before = tk.collect_events(Duration::from_millis(100));
    assert!(
        events_before.iter().any(|e| matches!(e.event.value, Value::Note { note: 60, .. })),
        "expected note 60 before swap"
    );

    // Swap to note 72
    conn.send(r#"{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":72,"velocity":100,"dur":0.5}}}"#);
    // Drain any stale events, then collect fresh ones
    tk.drain_events();
    let events_after = tk.collect_events(Duration::from_millis(100));
    assert!(
        events_after.iter().any(|e| matches!(e.event.value, Value::Note { note: 72, .. })),
        "expected note 72 after swap"
    );

    tk.stop();
}

#[test]
fn e2e_hush_all() {
    let tk = TestKernel::start("hushall");
    let mut conn = tk.connect();

    // Set two patterns
    conn.send(r#"{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}}}"#);
    conn.send(r#"{"cmd":"SetPattern","slot":"d2","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":64,"velocity":100,"dur":0.5}}}"#);

    // Verify events are flowing
    let events = tk.collect_events(Duration::from_millis(100));
    assert!(!events.is_empty(), "expected events before hush");

    // HushAll
    let resp = conn.send(r#"{"cmd":"HushAll"}"#);
    assert!(matches!(resp, ServerMessage::Ok { .. }));

    // Drain and verify silence
    tk.drain_events();
    let events_after = tk.collect_events(Duration::from_millis(100));
    assert!(events_after.is_empty(), "expected silence after HushAll");

    tk.stop();
}

#[test]
fn e2e_combinators() {
    let tk = TestKernel::start("comb");
    let mut conn = tk.connect();

    // fast 2 $ stack [euclid(3,8) note, cat [a, b]]
    let pattern = r#"{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Fast","factor":[2,1],"child":{"op":"Stack","children":[{"op":"Euclid","pulses":3,"steps":8,"rotation":0,"child":{"op":"Atom","value":{"type":"Note","channel":9,"note":36,"velocity":100,"dur":0.25}}},{"op":"Cat","children":[{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}},{"op":"Atom","value":{"type":"Note","channel":0,"note":64,"velocity":100,"dur":0.5}}]}]}}}"#;
    let resp = conn.send(pattern);
    assert!(matches!(resp, ServerMessage::Ok { .. }));

    // Query the compiled pattern directly for deterministic check
    {
        let guard = tk.slots.lock().unwrap();
        let slot = guard.get("d1").unwrap();
        let pat = slot.load();
        let events = query(&pat, pat.root, Arc::cycle(0));
        // fast 2 doubles: stack of euclid(3,8)=3 + cat[a,b]=2 per half-cycle, ×2 = 10
        // euclid(3,8) → 3 per cycle, fast 2 → 6
        // cat [a,b] → 2 per cycle, fast 2 → 4
        // total = 10
        assert_eq!(events.len(), 10, "fast 2 $ stack [euclid(3,8), cat[a,b]] -> 10 events");
    }

    tk.stop();
}

#[test]
fn e2e_error_invalid_json() {
    let tk = TestKernel::start("err-json");
    let resp = tk.send("not valid json at all");
    assert!(matches!(resp, ServerMessage::Error { .. }));
    tk.stop();
}

#[test]
fn e2e_error_empty_cat() {
    let tk = TestKernel::start("err-cat");
    let resp = tk.send(r#"{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Cat","children":[]}}"#);
    match resp {
        ServerMessage::Error { msg } => {
            assert!(msg.contains("at least one child"), "error should mention empty children: {msg}");
        }
        other => panic!("expected Error, got {other:?}"),
    }
    tk.stop();
}

#[test]
fn e2e_error_zero_denom_fast() {
    let tk = TestKernel::start("err-denom");
    let resp = tk.send(
        r#"{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Fast","factor":[1,0],"child":{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}}}}"#,
    );
    match resp {
        ServerMessage::Error { msg } => {
            assert!(msg.contains("zero denominator"), "error should mention zero denominator: {msg}");
        }
        other => panic!("expected Error, got {other:?}"),
    }
    tk.stop();
}

// ─── OSC loopback E2E ───

#[test]
fn e2e_osc_loopback() {
    let tk = TestKernel::start("osc");
    let mut conn = tk.connect();

    // Bind a UDP listener for OSC packets
    let listener = UdpSocket::bind("127.0.0.1:0").unwrap();
    let listener_addr = listener.local_addr().unwrap();
    listener
        .set_read_timeout(Some(Duration::from_secs(2)))
        .unwrap();

    // Create OscSink targeting the listener
    let mut osc_sink: Option<Box<dyn output::OutputSink>> =
        Some(Box::new(OscSink::new(&listener_addr.to_string()).unwrap()));

    // Set an OSC pattern via IPC
    let pattern = r#"{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Atom","value":{"type":"Osc","address":"/test/kick","args":[{"Float":1.0},{"Int":42},{"Str":"hello"}]}}}"#;
    let resp = conn.send(pattern);
    assert!(matches!(resp, ServerMessage::Ok { .. }));

    // Wait for scheduler to produce events, then dispatch through OscSink
    let events = tk.collect_events(Duration::from_millis(150));
    assert!(!events.is_empty(), "scheduler should emit OSC events");

    // Dispatch the first OSC event through the output sink
    let osc_event = events
        .iter()
        .find(|e| matches!(e.event.value, Value::Osc { .. }))
        .expect("should have at least one OSC event");
    output::dispatch(osc_event, &mut None, &mut osc_sink).unwrap();

    // Receive and verify the OSC packet
    let mut buf = [0u8; 1024];
    let (len, _) = listener.recv_from(&mut buf).unwrap();
    let (_, packet) = rosc::decoder::decode_udp(&buf[..len]).unwrap();

    match packet {
        rosc::OscPacket::Message(msg) => {
            assert_eq!(msg.addr, "/test/kick");
            assert_eq!(msg.args.len(), 3);
            assert_eq!(msg.args[0], rosc::OscType::Double(1.0));
            assert_eq!(msg.args[1], rosc::OscType::Int(42));
            assert_eq!(msg.args[2], rosc::OscType::String("hello".into()));
        }
        rosc::OscPacket::Bundle(_) => panic!("expected message, got bundle"),
    }

    tk.stop();
}
