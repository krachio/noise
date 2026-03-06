use std::collections::HashMap;

use soundman::control::MockControlInput;
use soundman::engine::AudioEngine;
use soundman::engine::config::EngineConfig;
use soundman::ir::{ConnectionIr, GraphIr, NodeInstance};
use soundman::output::MockAudioOutput;
use soundman::protocol::ClientMessage;

fn osc_dac_graph(freq: f32) -> GraphIr {
    GraphIr {
        nodes: vec![
            NodeInstance {
                id: "osc1".into(),
                type_id: "oscillator".into(),
                controls: HashMap::from([("freq".into(), freq)]),
            },
            NodeInstance {
                id: "out".into(),
                type_id: "dac".into(),
                controls: HashMap::new(),
            },
        ],
        connections: vec![ConnectionIr {
            from_node: "osc1".into(),
            from_port: "out".into(),
            to_node: "out".into(),
            to_port: "in".into(),
        }],
        exposed_controls: HashMap::from([("pitch".into(), ("osc1".into(), "freq".into()))]),
    }
}

#[test]
fn end_to_end_load_graph_produces_audio() {
    let config = EngineConfig {
        block_size: 64,
        channels: 1,
        ..Default::default()
    };
    let mut engine = AudioEngine::new(config);
    engine
        .handle_message(ClientMessage::LoadGraph(osc_dac_graph(440.0)))
        .unwrap();

    let mut output = vec![0.0_f32; 64];
    engine.process_block(&mut output);

    let energy: f32 = output.iter().map(|s| s * s).sum();
    assert!(energy > 0.0, "engine should produce audio after LoadGraph");

    for &s in &output {
        assert!((-1.0..=1.0).contains(&s), "sample out of range: {s}");
    }
}

#[test]
fn end_to_end_set_control_changes_frequency() {
    let config = EngineConfig {
        block_size: 256,
        channels: 1,
        ..Default::default()
    };
    let mut engine = AudioEngine::new(config);
    engine
        .handle_message(ClientMessage::LoadGraph(osc_dac_graph(440.0)))
        .unwrap();

    let mut buf_440 = vec![0.0_f32; 256];
    engine.process_block(&mut buf_440);

    engine
        .handle_message(ClientMessage::SetControl {
            label: "pitch".into(),
            value: 880.0,
        })
        .unwrap();

    let mut buf_880 = vec![0.0_f32; 256];
    engine.process_block(&mut buf_880);

    let count_crossings = |buf: &[f32]| -> usize {
        buf.windows(2)
            .filter(|w| w[0] <= 0.0 && w[1] > 0.0)
            .count()
    };
    assert!(
        count_crossings(&buf_880) > count_crossings(&buf_440),
        "880 Hz should have more zero crossings"
    );
}

#[test]
fn end_to_end_hot_swap_no_glitch() {
    let config = EngineConfig {
        block_size: 64,
        channels: 1,
        crossfade_ms: 10,
        ..Default::default()
    };
    let mut engine = AudioEngine::new(config);

    engine
        .handle_message(ClientMessage::LoadGraph(osc_dac_graph(440.0)))
        .unwrap();

    // Run several blocks to establish steady state
    let mut prev_last = 0.0_f32;
    for _ in 0..10 {
        let mut buf = vec![0.0_f32; 64];
        engine.process_block(&mut buf);
        prev_last = *buf.last().unwrap();
    }

    // Hot-swap to different frequency
    engine
        .handle_message(ClientMessage::LoadGraph(osc_dac_graph(880.0)))
        .unwrap();

    // Check that the crossfade doesn't introduce a glitch > 0.5
    let mut buf = vec![0.0_f32; 64];
    engine.process_block(&mut buf);

    let jump = (buf[0] - prev_last).abs();
    assert!(
        jump < 0.5,
        "hot-swap produced a glitch: jump={jump} (prev_last={prev_last}, first={first})",
        first = buf[0]
    );

    // Continue processing through crossfade — all samples bounded
    for _ in 0..20 {
        engine.process_block(&mut buf);
        for &s in &buf {
            assert!(
                (-1.1..=1.1).contains(&s),
                "sample during crossfade out of bounds: {s}"
            );
        }
    }
}

#[test]
fn end_to_end_control_input_integration() {
    let config = EngineConfig {
        block_size: 64,
        channels: 1,
        ..Default::default()
    };
    let mut engine = AudioEngine::new(config);
    let mut ctrl = MockControlInput::new();

    // Send graph via control input
    ctrl.send(ClientMessage::LoadGraph(osc_dac_graph(440.0)));
    engine.poll_control(&mut ctrl);

    assert!(engine.has_active_graph());

    let mut output = vec![0.0_f32; 64];
    engine.process_block(&mut output);

    let energy: f32 = output.iter().map(|s| s * s).sum();
    assert!(energy > 0.0);
}

#[test]
fn end_to_end_offline_rendering() {
    let config = EngineConfig {
        block_size: 128,
        channels: 2,
        ..Default::default()
    };
    let mut engine = AudioEngine::new(config);
    engine
        .handle_message(ClientMessage::LoadGraph(osc_dac_graph(440.0)))
        .unwrap();

    let mut mock = MockAudioOutput::new();
    engine.run_offline(&mut mock, 10);

    assert_eq!(mock.captured_blocks().len(), 10);

    // Each block: 128 samples * 2 channels = 256 floats
    for block in mock.captured_blocks() {
        assert_eq!(block.len(), 256);
        let energy: f32 = block.iter().map(|s| s * s).sum();
        assert!(energy > 0.0, "offline block should have audio");
    }
}

#[test]
fn end_to_end_graph_ir_from_json() {
    let json = r#"{
        "type": "load_graph",
        "nodes": [
            {"id": "osc1", "type_id": "oscillator", "controls": {"freq": 440.0}},
            {"id": "out", "type_id": "dac", "controls": {}}
        ],
        "connections": [
            {"from_node": "osc1", "from_port": "out", "to_node": "out", "to_port": "in"}
        ],
        "exposed_controls": {"pitch": ["osc1", "freq"]}
    }"#;

    let msg: ClientMessage = serde_json::from_str(json).unwrap();

    let config = EngineConfig {
        block_size: 64,
        channels: 1,
        ..Default::default()
    };
    let mut engine = AudioEngine::new(config);
    engine.handle_message(msg).unwrap();

    let mut output = vec![0.0_f32; 64];
    engine.process_block(&mut output);
    let energy: f32 = output.iter().map(|s| s * s).sum();
    assert!(energy > 0.0, "graph loaded from JSON should produce audio");
}
