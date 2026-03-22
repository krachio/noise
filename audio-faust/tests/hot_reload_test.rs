use std::collections::HashMap;
use std::fs;
use std::time::Duration;

use audio_engine::engine::config::EngineConfig;
use audio_engine::ir::{ConnectionIr, GraphIr, NodeInstance};
use audio_faust::hot_reload::HotReloadEngine;

const SINE_DSP: &str = r#"
import("stdfaust.lib");
freq = hslider("freq", 440, 20, 20000, 1);
process = os.osc(freq);
"#;

const GAIN_DSP: &str = r#"
gain = hslider("gain", 0.5, 0.0, 1.0, 0.01);
process = *(gain);
"#;

fn sine_graph() -> GraphIr {
    GraphIr {
        nodes: vec![
            NodeInstance {
                id: "osc".into(),
                type_id: "faust:sine".into(),
                controls: HashMap::from([("freq".into(), 440.0)]),
            },
            NodeInstance {
                id: "out".into(),
                type_id: "dac".into(),
                controls: HashMap::new(),
            },
        ],
        connections: vec![ConnectionIr {
            from_node: "osc".into(),
            from_port: "out".into(),
            to_node: "out".into(),
            to_port: "in".into(),
        }],
        exposed_controls: HashMap::from([("freq".into(), ("osc".into(), "freq".into()))]),
    }
}

#[test]
fn hot_reload_engine_loads_dir_and_produces_audio() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(dir.path().join("sine.dsp"), SINE_DSP).unwrap();

    let config = EngineConfig {
        block_size: 256,
        channels: 1,
        ..Default::default()
    };
    let (mut engine, mut proc) = HotReloadEngine::new(&config, dir.path()).unwrap();

    engine.load_graph(sine_graph()).unwrap();

    let mut output = vec![0.0_f32; 256];
    proc.process(&mut output);

    let energy: f32 = output.iter().map(|s| s * s).sum();
    assert!(energy > 0.0, "should produce audio after initial load");
}

#[test]
fn hot_reload_engine_reloads_on_file_change() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(dir.path().join("sine.dsp"), SINE_DSP).unwrap();

    let config = EngineConfig {
        block_size: 256,
        channels: 1,
        ..Default::default()
    };
    let (mut engine, mut proc) = HotReloadEngine::new(&config, dir.path()).unwrap();

    engine.load_graph(sine_graph()).unwrap();

    // Process initial audio
    let mut output1 = vec![0.0_f32; 256];
    proc.process(&mut output1);
    let energy1: f32 = output1.iter().map(|s| s * s).sum();
    assert!(energy1 > 0.0);

    // Modify the .dsp file (change default freq)
    let modified = r#"
import("stdfaust.lib");
freq = hslider("freq", 880, 20, 20000, 1);
process = os.osc(freq);
"#;
    fs::write(dir.path().join("sine.dsp"), modified).unwrap();

    // Give watcher time to detect + debounce
    std::thread::sleep(Duration::from_millis(500));

    // Poll for reload events
    let reloaded = engine.poll_reload().unwrap();
    assert!(!reloaded.is_empty(), "should detect file change");
    assert!(reloaded.contains(&"faust:sine".to_string()));

    // Process audio after reload — graph was reloaded with new factory
    let mut output2 = vec![0.0_f32; 256];
    proc.process(&mut output2);
    let energy2: f32 = output2.iter().map(|s| s * s).sum();
    assert!(energy2 > 0.0, "should produce audio after reload");

    // Outputs should differ (different default freq → different phase increment)
    assert_ne!(output1, output2, "audio should change after reload");
}

#[test]
fn hot_reload_engine_handles_new_dsp_file() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(dir.path().join("sine.dsp"), SINE_DSP).unwrap();

    let config = EngineConfig {
        block_size: 256,
        channels: 1,
        ..Default::default()
    };
    let (mut engine, _proc) = HotReloadEngine::new(&config, dir.path()).unwrap();

    // gain.dsp doesn't exist yet
    assert!(engine.registry().get_type("faust:gain").is_none());

    // Add a new .dsp file
    fs::write(dir.path().join("gain.dsp"), GAIN_DSP).unwrap();
    std::thread::sleep(Duration::from_millis(500));

    let reloaded = engine.poll_reload().unwrap();
    assert!(reloaded.contains(&"faust:gain".to_string()));
    assert!(engine.registry().get_type("faust:gain").is_some());
}
