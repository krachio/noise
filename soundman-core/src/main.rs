use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use soundman::control::ControlInput;
use soundman::control::osc::OscControlInput;
use soundman::engine::AudioEngine;
use soundman::engine::config::EngineConfig;
use soundman::ir::{ConnectionIr, GraphIr, NodeInstance};
use soundman::output::AudioOutput;
use soundman::output::cpal_backend::CpalBackend;
use soundman::protocol::ClientMessage;

fn default_graph() -> GraphIr {
    GraphIr {
        nodes: vec![
            NodeInstance {
                id: "osc1".into(),
                type_id: "oscillator".into(),
                controls: HashMap::from([("freq".into(), 440.0)]),
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

fn main() {
    let config = EngineConfig::default();
    let engine = Arc::new(Mutex::new(AudioEngine::new(config.clone())));

    // Load default graph
    {
        let mut eng = engine.lock().unwrap();
        eng.handle_message(ClientMessage::LoadGraph(default_graph()))
            .unwrap();
    }

    // Start audio output
    let mut backend = CpalBackend::new();
    let engine_audio = Arc::clone(&engine);
    let block_size = config.block_size;
    let channels = config.channels;

    backend
        .start(&config, Box::new(move |data: &mut [f32]| {
            let mono_len = data.len() / channels;
            let actual_len = mono_len.min(block_size);
            let mut mono_buf = vec![0.0_f32; actual_len];

            engine_audio.lock().unwrap().process_block(&mut mono_buf);

            for (i, &sample) in mono_buf.iter().enumerate() {
                for ch in 0..channels {
                    if let Some(out) = data.get_mut(i * channels + ch) {
                        *out = sample;
                    }
                }
            }
        }))
        .expect("failed to start audio output");

    println!("soundman running — 440 Hz sine on default output");
    println!("OSC control on 127.0.0.1:9000");
    println!("  /soundman/set pitch <freq>");
    println!("  /soundman/gain <0.0-1.0>");
    println!("  /soundman/shutdown");
    println!("Press Ctrl+C to stop");

    // Start OSC control input
    let mut osc = OscControlInput::new("127.0.0.1:9000");
    if let Err(e) = osc.start() {
        eprintln!("failed to start OSC input: {e}");
        return;
    }

    // Main control loop
    loop {
        let messages = osc.poll();
        let mut should_shutdown = false;

        for msg in messages {
            if matches!(msg, ClientMessage::Shutdown) {
                should_shutdown = true;
            }
            let mut eng = engine.lock().unwrap();
            let _ = eng.handle_message(msg);
        }

        if should_shutdown {
            break;
        }

        std::thread::sleep(std::time::Duration::from_millis(10));
    }

    backend.stop();
    osc.stop();
    println!("soundman stopped");
}
