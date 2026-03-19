use std::cmp::Reverse;
use std::collections::BinaryHeap;
use std::path::PathBuf;
use std::time::Instant;

/// Wrapper for `(Instant, ClientMessage)` that orders by `Instant` only.
/// Used in the timed command priority queue.
struct Timed(Instant, ClientMessage);
impl PartialEq for Timed {
    fn eq(&self, o: &Self) -> bool { self.0 == o.0 }
}
impl Eq for Timed {}
impl PartialOrd for Timed {
    fn partial_cmp(&self, o: &Self) -> Option<std::cmp::Ordering> { Some(self.cmp(o)) }
}
impl Ord for Timed {
    fn cmp(&self, o: &Self) -> std::cmp::Ordering { self.0.cmp(&o.0) }
}

use log::{error, info, warn};
use soundman_core::control::osc::{send_node_types_reply, OscControlInput};
use soundman_core::control::ControlInput;
use soundman_core::engine::config::EngineConfig;
use soundman_core::output::cpal_backend::{CpalBackend, DeviceConfig};
use soundman_core::output::AudioOutput;
use soundman_core::protocol::ClientMessage;
use soundman_faust::hot_reload::HotReloadEngine;

fn resolve_dsp_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("SOUNDMAN_DSP_DIR") {
        return PathBuf::from(dir);
    }
    std::env::var("HOME").map_or_else(
        |_| PathBuf::from("/tmp/soundman/dsp"),
        |h| PathBuf::from(h).join(".krach/dsp"),
    )
}

fn resolve_osc_addr() -> String {
    std::env::var("SOUNDMAN_OSC_ADDR").unwrap_or_else(|_| "127.0.0.1:9001".to_string())
}

fn make_audio_callback(
    mut processor: soundman_core::engine::AudioProcessor,
    block_size: usize,
    channels: usize,
) -> impl FnMut(&mut [f32]) + Send + 'static {
    let mut mono_buf = vec![0.0_f32; block_size];
    move |data: &mut [f32]| {
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
    }
}

fn run(device: &DeviceConfig, dsp_dir: &PathBuf, osc_addr: &str) -> Result<(), String> {
    let config = EngineConfig {
        sample_rate: device.sample_rate,
        channels: device.channels,
        ..Default::default()
    };

    let (mut engine, processor) = HotReloadEngine::new(&config, dsp_dir)?;

    let callback = make_audio_callback(processor, config.block_size, config.channels);
    let mut backend = CpalBackend::new();
    backend.start(&config, Box::new(callback))?;

    info!("audio started ({}Hz, {} ch)", config.sample_rate, config.channels);
    info!("soundman ready — FAUST + built-in nodes");
    info!("DSP dir:     {}", dsp_dir.display());
    info!("OSC control: {osc_addr}");
    info!("  /soundman/load_graph <json>");
    info!("  /soundman/set <label> <value>");
    info!("  /soundman/gain <0.0–1.0>");
    info!("  /soundman/list_nodes <reply_port>");
    info!("  /soundman/shutdown");

    let mut osc = OscControlInput::new(osc_addr);
    osc.start()?;

    // Priority queue for time-tagged SetControl commands.
    // Messages sent by midiman as OSC bundles arrive here up to ~100ms before
    // their scheduled time. We dequeue them when their timestamp arrives and
    // pass them to the audio thread — firing in the block that CONTAINS the
    // scheduled time rather than the block after it.
    let mut pending: BinaryHeap<Reverse<Timed>> = BinaryHeap::new();

    loop {
        // ① Receive OSC messages, preserving bundle time tags.
        for (time_tag, msg) in osc.timed_poll() {
            match (time_tag, msg) {
                // SetControl with a time tag → queue for sample-accurate firing.
                (Some(fire_at), msg @ ClientMessage::SetControl { .. }) => {
                    pending.push(Reverse(Timed(fire_at, msg)));
                }
                // All other messages (including immediate SetControl) → apply now.
                (_, ClientMessage::Shutdown) => {
                    backend.stop();
                    osc.stop();
                    return Ok(());
                }
                (_, ClientMessage::ListNodes { reply_port }) => {
                    let types = engine.controller_mut().list_node_types();
                    send_node_types_reply("127.0.0.1", reply_port, &types);
                }
                (_, ClientMessage::LoadGraph(ir)) => {
                    if let Err(e) = engine.load_graph(ir) {
                        warn!("load_graph: {e}");
                    }
                }
                (_, other) => {
                    let _ = engine.controller_mut().handle_message(other);
                }
            }
        }

        // ② Dequeue timed SetControl commands whose scheduled time has arrived.
        let now = Instant::now();
        while pending
            .peek()
            .is_some_and(|Reverse(Timed(t, _))| *t <= now)
        {
            let Reverse(Timed(_, msg)) = pending.pop().expect("just peeked");
            let _ = engine.controller_mut().handle_message(msg);
        }

        if let Err(e) = engine.poll_reload() {
            warn!("poll_reload: {e}");
        }

        spin_sleep::sleep(std::time::Duration::from_millis(1));
    }
}

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .format_timestamp_millis()
        .init();

    let dsp_dir = resolve_dsp_dir();
    if let Err(e) = std::fs::create_dir_all(&dsp_dir) {
        error!("cannot create DSP dir {}: {e}", dsp_dir.display());
        return;
    }

    let osc_addr = resolve_osc_addr();
    let device = CpalBackend::query_device().expect("no audio device");
    info!("audio device: {}Hz, {} ch", device.sample_rate, device.channels);

    if let Err(e) = run(&device, &dsp_dir, &osc_addr) {
        error!("{e}");
    }
}
