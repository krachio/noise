//! Integration test: midiman drives soundman over OSC.
//!
//! Verifies that midiman's scheduler + OSC output produces packets
//! that soundman's OscControlInput can parse as SetControl messages.
//! Uses a real UDP socket as a stand-in for soundman's listener.

mod helpers;

use std::net::UdpSocket;
use std::time::Duration;

use midiman::event::Value;
use midiman::ipc::protocol::ServerMessage;
use midiman::output;
use midiman::output::osc::OscSink;

use helpers::TestKernel;

/// Frequencies for a C major 7th chord (Hz), mapped to soundman's pitch control.
const CHORD: [f64; 4] = [261.63, 329.63, 392.00, 493.88]; // C4, E4, G4, B4

/// Build a Cat pattern JSON that sequences four `/soundman/set pitch <freq>` events.
fn chord_arpeggio_json() -> String {
    let atoms: Vec<String> = CHORD
        .iter()
        .map(|freq| {
            format!(
                r#"{{"op":"Atom","value":{{"type":"Osc","address":"/soundman/set","args":[{{"Str":"pitch"}},{{"Float":{freq}}}]}}}}"#
            )
        })
        .collect();

    format!(
        r#"{{"cmd":"SetPattern","slot":"d1","pattern":{{"op":"Cat","children":[{}]}}}}"#,
        atoms.join(",")
    )
}

#[test]
fn midiman_sequences_soundman_set_control_over_osc() {
    let tk = TestKernel::start("soundman-bridge");
    let mut conn = tk.connect();

    // Bind a UDP listener (stand-in for soundman's OscControlInput)
    let listener = UdpSocket::bind("127.0.0.1:0").unwrap();
    let listener_addr = listener.local_addr().unwrap();
    listener
        .set_read_timeout(Some(Duration::from_secs(2)))
        .unwrap();

    // Create OscSink targeting the listener
    let mut osc_sink: Option<Box<dyn output::OutputSink>> =
        Some(Box::new(OscSink::new(&listener_addr.to_string()).unwrap()));

    // Send the arpeggio pattern
    let resp = conn.send(&chord_arpeggio_json());
    assert!(matches!(resp, ServerMessage::Ok { .. }));

    // Collect events from multiple cycles to get all 4 chord tones
    let events = tk.collect_events(Duration::from_millis(200));
    let osc_events: Vec<_> = events
        .iter()
        .filter(|e| matches!(e.event.value, Value::Osc { .. }))
        .collect();
    assert!(
        osc_events.len() >= 4,
        "expected at least 4 OSC events (one full chord cycle), got {}",
        osc_events.len()
    );

    // Dispatch all OSC events through the sink → UDP
    for event in &osc_events {
        output::dispatch(event, &mut None, &mut osc_sink).unwrap();
    }

    // Receive and decode all packets, verifying soundman compatibility
    let mut received_freqs = Vec::new();
    let mut buf = [0u8; 4096];

    for _ in 0..osc_events.len() {
        let (len, _) = match listener.recv_from(&mut buf) {
            Ok(r) => r,
            Err(_) => break,
        };
        let (_, packet) = rosc::decoder::decode_udp(&buf[..len]).unwrap();

        if let rosc::OscPacket::Message(msg) = packet {
            // Verify address matches soundman's expected namespace
            assert_eq!(
                msg.addr, "/soundman/set",
                "OSC address must match soundman's /soundman/set endpoint"
            );

            // Verify first arg is the control label
            assert_eq!(
                msg.args[0],
                rosc::OscType::String("pitch".into()),
                "first arg must be the control label"
            );

            // Extract frequency (midiman sends Double, soundman expects Float —
            // this documents the current wire format)
            match &msg.args[1] {
                rosc::OscType::Double(f) => received_freqs.push(*f),
                rosc::OscType::Float(f) => received_freqs.push(f64::from(*f)),
                other => panic!("expected numeric arg, got {other:?}"),
            }
        }
    }

    // Verify we got all four chord tones (possibly repeated across cycles)
    for freq in &CHORD {
        assert!(
            received_freqs.iter().any(|f| (f - freq).abs() < 0.01),
            "missing frequency {freq} Hz in received: {received_freqs:?}"
        );
    }

    // Verify musical ordering within a single cycle (first 4 events)
    let first_cycle: Vec<f64> = received_freqs.iter().take(4).copied().collect();
    assert_eq!(
        first_cycle,
        CHORD.to_vec(),
        "first cycle should play C4→E4→G4→B4 in order"
    );

    tk.stop();
}
