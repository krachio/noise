use std::collections::HashMap;

use log::{error, info};
use soundman_core::control::ControlInput;
use soundman_core::control::osc::{OscControlInput, send_node_types_reply};
use soundman_core::engine::config::EngineConfig;
use soundman_core::ir::{ConnectionIr, GraphIr, NodeInstance};
use soundman_core::output::AudioOutput;
use soundman_core::output::cpal_backend::CpalBackend;
use soundman_core::protocol::ClientMessage;

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
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .format_timestamp_millis()
        .init();

    let device = CpalBackend::query_device().expect("no audio device");
    info!("audio device: {}Hz, {} ch", device.sample_rate, device.channels);

    let config = EngineConfig {
        sample_rate: device.sample_rate,
        channels: device.channels,
        ..Default::default()
    };
    let (mut controller, processor) = soundman_core::engine::engine(&config);

    // Load default graph
    controller
        .handle_message(ClientMessage::LoadGraph(default_graph()))
        .unwrap();

    // Start audio output — processor moves into the audio callback, no mutex
    let mut backend = CpalBackend::new();
    let block_size = config.block_size;
    let channels = config.channels;

    let mut mono_buf = vec![0.0_f32; block_size];
    let mut processor = processor;

    backend
        .start(&config, Box::new(move |data: &mut [f32]| {
            let total_frames = data.len() / channels;
            let mut frame_offset = 0;

            while frame_offset < total_frames {
                let chunk_frames = block_size.min(total_frames - frame_offset);
                mono_buf[..chunk_frames].fill(0.0);
                processor.process(&mut mono_buf[..chunk_frames]);

                for i in 0..chunk_frames {
                    for ch in 0..channels {
                        data[(frame_offset + i) * channels + ch] = mono_buf[i];
                    }
                }
                frame_offset += chunk_frames;
            }
        }))
        .expect("failed to start audio output");

    info!("audio output started ({}Hz, {} ch, block={})", config.sample_rate, config.channels, config.block_size);

    info!("soundman running — 440 Hz sine on default output");
    info!("OSC control on 127.0.0.1:9000");
    info!("  /soundman/set pitch <freq>");
    info!("  /soundman/gain <0.0-1.0>");
    info!("  /soundman/list_nodes <reply_port>");
    info!("  /soundman/shutdown");
    info!("set RUST_LOG=soundman=debug for verbose output");

    // Start OSC control input
    let mut osc = OscControlInput::new("127.0.0.1:9000");
    if let Err(e) = osc.start() {
        error!("failed to start OSC input: {e}");
        return;
    }

    // Main control loop — controller stays on this thread
    loop {
        let messages = osc.poll();
        let mut should_shutdown = false;

        for msg in messages {
            match &msg {
                ClientMessage::Shutdown => { should_shutdown = true; }
                ClientMessage::ListNodes { reply_port } => {
                    let types = controller.list_node_types();
                    send_node_types_reply("127.0.0.1", *reply_port, &types);
                }
                _ => {}
            }
            let _ = controller.handle_message(msg);
        }

        if should_shutdown {
            break;
        }

        std::thread::sleep(std::time::Duration::from_millis(10));
    }

    backend.stop();
    osc.stop();
    info!("soundman stopped");
}
