use std::collections::HashMap;

use audio_engine::engine;
use audio_engine::engine::config::EngineConfig;
use audio_engine::ir::{ConnectionIr, GraphIr, NodeInstance};
use audio_engine::protocol::ClientMessage;
use audio_faust::{faust_version, register_faust_node};

#[test]
fn faust_version_returns_nonempty() {
    let v = faust_version();
    assert!(!v.is_empty(), "FAUST version should not be empty");
    println!("FAUST version: {v}");
}

/// Minimal sine generator in FAUST — no library imports needed.
const SINE_DSP: &str = r#"
import("stdfaust.lib");
freq = hslider("freq", 440, 20, 20000, 1);
process = os.osc(freq);
"#;

/// Simple gain processor — 1 input, 1 output.
const GAIN_DSP: &str = r#"
gain = hslider("gain", 0.5, 0.0, 1.0, 0.01);
process = *(gain);
"#;

/// Stereo passthrough — 2 inputs, 2 outputs.
const STEREO_DSP: &str = r"
process = _, _;
";

/// Invalid FAUST code — should fail compilation.
const INVALID_DSP: &str = r"
process = this_is_not_valid_faust!!!;
";

#[test]
fn compile_sine_dsp() {
    let dsp = audio_faust::dsp::FaustDsp::from_code("sine", SINE_DSP, 48000, 256).unwrap();
    assert_eq!(dsp.num_inputs(), 0);
    assert_eq!(dsp.num_outputs(), 1);
    assert!(dsp.params().contains_key("freq"));
}

#[test]
fn compile_gain_dsp() {
    let dsp = audio_faust::dsp::FaustDsp::from_code("gain", GAIN_DSP, 48000, 256).unwrap();
    assert_eq!(dsp.num_inputs(), 1);
    assert_eq!(dsp.num_outputs(), 1);
    assert!(dsp.params().contains_key("gain"));
}

#[test]
fn sine_produces_audio() {
    let mut dsp = audio_faust::dsp::FaustDsp::from_code("sine", SINE_DSP, 48000, 256).unwrap();

    let inputs: Vec<&[f32]> = vec![];
    let mut out_buf = vec![0.0_f32; 256];
    {
        let mut out_slices: Vec<&mut [f32]> = vec![out_buf.as_mut_slice()];
        dsp.compute(&inputs, &mut out_slices);
    }

    let energy: f32 = out_buf.iter().map(|s| s * s).sum();
    assert!(
        energy > 0.0,
        "sine DSP should produce audio, energy={energy}"
    );
}

#[test]
fn gain_processes_input() {
    let mut dsp = audio_faust::dsp::FaustDsp::from_code("gain", GAIN_DSP, 48000, 256).unwrap();

    // Feed a DC signal of 1.0
    let input = vec![1.0_f32; 256];
    let inputs: Vec<&[f32]> = vec![input.as_slice()];
    let mut out_buf = vec![0.0_f32; 256];
    {
        let mut out_slices: Vec<&mut [f32]> = vec![out_buf.as_mut_slice()];
        dsp.compute(&inputs, &mut out_slices);
    }

    // Default gain is 0.5, so output should be ~0.5
    let avg: f32 = out_buf.iter().sum::<f32>() / 256.0;
    assert!(
        (avg - 0.5).abs() < 0.01,
        "gain DSP with default 0.5 should output ~0.5, got {avg}"
    );

    // Change gain to 0.25
    dsp.set_param("gain", 0.25);
    {
        let mut out_slices: Vec<&mut [f32]> = vec![out_buf.as_mut_slice()];
        dsp.compute(&inputs, &mut out_slices);
    }
    let avg2: f32 = out_buf.iter().sum::<f32>() / 256.0;
    assert!(
        (avg2 - 0.25).abs() < 0.01,
        "gain DSP with 0.25 should output ~0.25, got {avg2}"
    );
}

#[test]
fn faust_factory_creates_node_type_decl() {
    let factory = audio_faust::factory::FaustFactory::new("sine", SINE_DSP);
    let decl = factory.probe_type_decl("faust:sine").unwrap();

    assert_eq!(decl.type_id, "faust:sine");
    assert!(decl.audio_inputs.is_empty());
    assert_eq!(decl.audio_outputs.len(), 1);
    assert_eq!(decl.audio_outputs[0].name, "out");
    assert!(!decl.controls.is_empty());
}

#[test]
fn register_and_use_faust_node_in_engine() {
    let config = EngineConfig {
        block_size: 256,
        channels: 1,
        ..Default::default()
    };
    let (mut ctrl, mut proc) = engine::engine(&config);

    // Register a FAUST sine node
    register_faust_node(ctrl.registry_mut(), "faust:sine", "sine", SINE_DSP).unwrap();

    // Build a graph using the FAUST node
    let graph = GraphIr {
        nodes: vec![
            NodeInstance {
                id: "faust_osc".into(),
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
            from_node: "faust_osc".into(),
            from_port: "out".into(),
            to_node: "out".into(),
            to_port: "in".into(),
        }],
        exposed_controls: HashMap::from([("freq".into(), ("faust_osc".into(), "freq".into()))]),
    };

    ctrl.handle_message(ClientMessage::LoadGraph(graph))
        .unwrap();

    let mut output = vec![0.0_f32; 256];
    proc.process(&mut output);

    let energy: f32 = output.iter().map(|s| s * s).sum();
    assert!(
        energy > 0.0,
        "FAUST sine through engine should produce audio"
    );
}

// -- Error handling tests --

#[test]
fn invalid_code_returns_error() {
    let result = audio_faust::dsp::FaustDsp::from_code("bad", INVALID_DSP, 48000, 256);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(
        err.contains("FAUST compilation failed"),
        "error should mention compilation failure, got: {err}"
    );
}

#[test]
fn invalid_code_factory_probe_returns_error() {
    let factory = audio_faust::factory::FaustFactory::new("bad", INVALID_DSP);
    let result = factory.probe_type_decl("faust:bad");
    assert!(result.is_err());
}

#[test]
fn register_invalid_faust_node_returns_error() {
    let config = EngineConfig::default();
    let (mut ctrl, _proc) = engine::engine(&config);
    let result = register_faust_node(ctrl.registry_mut(), "faust:bad", "bad", INVALID_DSP);
    assert!(result.is_err());
}

// -- Reset tests --

#[test]
fn reset_changes_sample_rate_affects_output() {
    let mut dsp = audio_faust::dsp::FaustDsp::from_code("sine", SINE_DSP, 48000, 256).unwrap();

    // Compute one block at 48kHz
    let mut out_48k = vec![0.0_f32; 256];
    {
        let mut slices: Vec<&mut [f32]> = vec![out_48k.as_mut_slice()];
        dsp.compute(&[], &mut slices);
    }

    // Reset to 96kHz and compute again
    dsp.reset(96000);
    let mut out_96k = vec![0.0_f32; 256];
    {
        let mut slices: Vec<&mut [f32]> = vec![out_96k.as_mut_slice()];
        dsp.compute(&[], &mut slices);
    }

    // Both should produce audio
    let energy_48k: f32 = out_48k.iter().map(|s| s * s).sum();
    let energy_96k: f32 = out_96k.iter().map(|s| s * s).sum();
    assert!(energy_48k > 0.0, "48kHz sine should produce audio");
    assert!(energy_96k > 0.0, "96kHz sine should produce audio");

    // Output should differ — same 440Hz osc at different sample rates
    // produces different phase increments, so the sample values diverge
    assert_ne!(
        out_48k, out_96k,
        "output at 48kHz and 96kHz should differ for same oscillator"
    );
}

// -- Stereo / multi-channel tests --

#[test]
fn stereo_passthrough_channels() {
    let dsp = audio_faust::dsp::FaustDsp::from_code("stereo", STEREO_DSP, 48000, 256).unwrap();
    assert_eq!(dsp.num_inputs(), 2);
    assert_eq!(dsp.num_outputs(), 2);
}

#[test]
fn stereo_passthrough_copies_input_to_output() {
    let mut dsp = audio_faust::dsp::FaustDsp::from_code("stereo", STEREO_DSP, 48000, 256).unwrap();

    let left_in: Vec<f32> = (0..256u16).map(|i| f32::from(i) / 256.0).collect();
    let right_in: Vec<f32> = (0..256u16).map(|i| 1.0 - f32::from(i) / 256.0).collect();
    let inputs: Vec<&[f32]> = vec![&left_in, &right_in];

    let mut left_out = vec![0.0_f32; 256];
    let mut right_out = vec![0.0_f32; 256];
    {
        let mut out_slices: Vec<&mut [f32]> = vec![&mut left_out, &mut right_out];
        dsp.compute(&inputs, &mut out_slices);
    }

    assert_eq!(left_out, left_in, "left channel should pass through");
    assert_eq!(right_out, right_in, "right channel should pass through");
}

#[test]
fn stereo_factory_probe_has_two_ports() {
    let factory = audio_faust::factory::FaustFactory::new("stereo", STEREO_DSP);
    let decl = factory.probe_type_decl("faust:stereo").unwrap();

    assert_eq!(decl.audio_inputs.len(), 2);
    assert_eq!(decl.audio_outputs.len(), 2);
    assert_eq!(decl.audio_inputs[0].name, "in0");
    assert_eq!(decl.audio_inputs[1].name, "in1");
    assert_eq!(decl.audio_outputs[0].name, "out0");
    assert_eq!(decl.audio_outputs[1].name, "out1");
    assert!(decl.controls.is_empty());
}
