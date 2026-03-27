use std::collections::HashMap;

use audio_engine::control::MockControlInput;
use audio_engine::engine::config::EngineConfig;
use audio_engine::engine::{self, AudioProcessor, EngineController};
use audio_engine::ir::{ConnectionIr, GraphIr, NodeInstance};
use audio_engine::protocol::ClientMessage;

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

fn setup(config: &EngineConfig) -> (EngineController, AudioProcessor) {
    engine::engine(config)
}

#[test]
fn end_to_end_load_graph_produces_audio() {
    let config = EngineConfig {
        block_size: 64,
        channels: 1,
        ..Default::default()
    };
    let (mut ctrl, mut proc) = setup(&config);
    ctrl.handle_message(ClientMessage::LoadGraph(osc_dac_graph(440.0)))
        .unwrap();

    let mut output = vec![0.0_f32; 64];
    proc.process(&mut output);

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
    let (mut ctrl, mut proc) = setup(&config);
    ctrl.handle_message(ClientMessage::LoadGraph(osc_dac_graph(440.0)))
        .unwrap();

    let mut buf_440 = vec![0.0_f32; 256];
    proc.process(&mut buf_440);

    ctrl.handle_message(ClientMessage::SetControl {
        label: "pitch".into(),
        value: 880.0,
    })
    .unwrap();

    let mut buf_880 = vec![0.0_f32; 256];
    proc.process(&mut buf_880);

    let count_crossings =
        |buf: &[f32]| -> usize { buf.windows(2).filter(|w| w[0] <= 0.0 && w[1] > 0.0).count() };
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
    let (mut ctrl, mut proc) = setup(&config);

    ctrl.handle_message(ClientMessage::LoadGraph(osc_dac_graph(440.0)))
        .unwrap();

    // Run several blocks to establish steady state
    let mut prev_last = 0.0_f32;
    for _ in 0..10 {
        let mut buf = vec![0.0_f32; 64];
        proc.process(&mut buf);
        prev_last = *buf.last().unwrap();
    }

    // Hot-swap to different frequency
    ctrl.handle_message(ClientMessage::LoadGraph(osc_dac_graph(880.0)))
        .unwrap();

    // Check that the crossfade doesn't introduce a glitch > 0.5
    let mut buf = vec![0.0_f32; 64];
    proc.process(&mut buf);

    let jump = (buf[0] - prev_last).abs();
    assert!(
        jump < 0.5,
        "hot-swap produced a glitch: jump={jump} (prev_last={prev_last}, first={first})",
        first = buf[0]
    );

    // Continue processing through crossfade — all samples bounded
    for _ in 0..20 {
        proc.process(&mut buf);
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
    let (mut ctrl, mut proc) = setup(&config);
    let mut input = MockControlInput::new();

    input.send(ClientMessage::LoadGraph(osc_dac_graph(440.0)));
    ctrl.poll_control(&mut input);

    let mut output = vec![0.0_f32; 64];
    proc.process(&mut output);
    assert!(proc.has_active_graph());

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
    let (mut ctrl, mut proc) = setup(&config);
    ctrl.handle_message(ClientMessage::LoadGraph(osc_dac_graph(440.0)))
        .unwrap();

    let mut blocks = Vec::new();
    for _ in 0..10 {
        let mut mono = vec![0.0_f32; config.block_size];
        proc.process(&mut mono);

        let mut interleaved = vec![0.0_f32; config.block_size * config.channels];
        for (i, &sample) in mono.iter().enumerate() {
            for ch in 0..config.channels {
                interleaved[i * config.channels + ch] = sample;
            }
        }
        blocks.push(interleaved);
    }

    assert_eq!(blocks.len(), 10);
    for block in &blocks {
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
    let (mut ctrl, mut proc) = setup(&config);
    ctrl.handle_message(msg).unwrap();

    let mut output = vec![0.0_f32; 64];
    proc.process(&mut output);
    let energy: f32 = output.iter().map(|s| s * s).sum();
    assert!(energy > 0.0, "graph loaded from JSON should produce audio");
}

// ─── Graph continuity (bugs #12, #13) ───

#[test]
fn test_add_node_preserves_existing_audio() {
    let config = EngineConfig {
        block_size: 64,
        channels: 1,
        crossfade_ms: 10,
        ..Default::default()
    };
    let (mut ctrl, mut proc) = setup(&config);

    ctrl.handle_message(ClientMessage::LoadGraph(osc_dac_graph(440.0)))
        .unwrap();

    // Establish steady state — 10 blocks of audio.
    for _ in 0..10 {
        let mut buf = vec![0.0_f32; 64];
        proc.process(&mut buf);
    }

    // Add a second oscillator via incremental mutation (not LoadGraph).
    ctrl.handle_message(ClientMessage::AddNode {
        id: "osc2".into(),
        type_id: "oscillator".into(),
        controls: HashMap::from([("freq".into(), 880.0)]),
    })
    .unwrap();
    ctrl.handle_message(ClientMessage::Connect {
        from_node: "osc2".into(),
        from_port: "out".into(),
        to_node: "out".into(),
        to_port: "in".into(),
    })
    .unwrap();

    // Process blocks during the rebuild — existing audio should not drop to silence.
    let mut had_silence = false;
    for _ in 0..5 {
        let mut buf = vec![0.0_f32; 64];
        proc.process(&mut buf);
        let energy: f32 = buf.iter().map(|s| s * s).sum();
        if energy < 1e-6 {
            had_silence = true;
        }
    }
    assert!(
        !had_silence,
        "existing audio was silenced during node addition (bug #12)"
    );
}

#[test]
fn test_full_reload_preserves_continuity() {
    let config = EngineConfig {
        block_size: 64,
        channels: 1,
        crossfade_ms: 10,
        ..Default::default()
    };
    let (mut ctrl, mut proc) = setup(&config);

    ctrl.handle_message(ClientMessage::LoadGraph(osc_dac_graph(440.0)))
        .unwrap();

    // Establish steady state.
    for _ in 0..10 {
        let mut buf = vec![0.0_f32; 64];
        proc.process(&mut buf);
    }

    // Full reload — should crossfade smoothly.
    ctrl.handle_message(ClientMessage::LoadGraph(osc_dac_graph(880.0)))
        .unwrap();

    for _ in 0..20 {
        let mut buf = vec![0.0_f32; 64];
        proc.process(&mut buf);
        for &s in &buf {
            assert!(
                (-1.1..=1.1).contains(&s),
                "crossfade sample out of bounds: {s} (bug #13)"
            );
        }
    }
}

#[test]
fn test_rapid_graph_swaps_no_panic() {
    let config = EngineConfig {
        block_size: 64,
        channels: 1,
        crossfade_ms: 5,
        ..Default::default()
    };
    let (mut ctrl, mut proc) = setup(&config);

    ctrl.handle_message(ClientMessage::LoadGraph(osc_dac_graph(440.0)))
        .unwrap();

    // 10 rapid graph swaps without processing between them.
    for freq in (220..=660).step_by(44) {
        ctrl.handle_message(ClientMessage::LoadGraph(osc_dac_graph(freq as f32)))
            .unwrap();
    }

    // Process several blocks — should not panic or produce NaN.
    for _ in 0..30 {
        let mut buf = vec![0.0_f32; 64];
        proc.process(&mut buf);
        for &s in &buf {
            assert!(!s.is_nan(), "NaN produced after rapid graph swaps");
            assert!(
                (-2.0..=2.0).contains(&s),
                "sample out of range after rapid swaps: {s}"
            );
        }
    }
}
