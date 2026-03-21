//! Unified binary merging the pattern sequencer (midiman) and audio engine
//! (soundman-core + soundman-faust) into a single process.
//!
//! Eliminates OSC overhead between the two — pattern events are dispatched
//! directly to the audio engine's control thread via function calls.

use std::cmp::Reverse;
use std::collections::BinaryHeap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant};

use log::{error, info, warn};

use midiman::engine::{Engine, EngineCommand};
use midiman::event::{OscArg, Value};
use midiman::output::{self, OutputSink};
use soundman_core::engine::config::EngineConfig;
use soundman_core::output::cpal_backend::{CpalBackend, DeviceConfig};
use soundman_core::output::AudioOutput;
use soundman_core::protocol::ClientMessage;
use soundman_faust::hot_reload::HotReloadEngine;

const DEFAULT_BPM: f64 = 120.0;
const BEATS_PER_CYCLE: f64 = 4.0;
const LOOKAHEAD: Duration = Duration::from_millis(100);
const MAX_SLEEP: Duration = Duration::from_millis(1);

/// Commands routed from the IPC thread to the main loop.
/// Single channel, single try_recv(), single match.
enum LoopCommand {
    Pattern(EngineCommand),
    Graph(ClientMessage),
}

/// A pending MIDI note-off to fire at a specific wall-clock time.
#[derive(Debug, Eq, PartialEq)]
struct PendingNoteOff {
    fire_at: Instant,
    channel: u8,
    note: u8,
}

impl Ord for PendingNoteOff {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.fire_at.cmp(&other.fire_at)
    }
}

impl PartialOrd for PendingNoteOff {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

/// A pending SetControl event scheduled for future dispatch.
struct PendingControl {
    fire_at: Instant,
    label: String,
    value: f32,
}

fn resolve_dsp_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("SOUNDMAN_DSP_DIR") {
        return PathBuf::from(dir);
    }
    std::env::var("HOME").map_or_else(
        |_| PathBuf::from("/tmp/soundman/dsp"),
        |h| PathBuf::from(h).join(".krach/dsp"),
    )
}

fn socket_path() -> PathBuf {
    if let Ok(path) = std::env::var("NOISE_SOCKET") {
        PathBuf::from(path)
    } else {
        std::env::temp_dir().join("noise-engine.sock")
    }
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

/// Parse a midiman OSC event into a (label, value) pair for direct dispatch.
///
/// Matches events with address "/soundman/set" and args [Str(label), Float(value)].
/// Returns None for non-SetControl events (MIDI notes, CCs, other OSC addresses).
fn parse_set_control(event: &midiman::engine::TimedEvent) -> Option<(&str, f32)> {
    match &event.event.value {
        Value::Osc { address, args } if address == "/soundman/set" => {
            let label = match args.first()? {
                OscArg::Str(s) => s.as_str(),
                _ => return None,
            };
            #[allow(clippy::cast_possible_truncation)]
            let value = match args.get(1)? {
                OscArg::Float(f) => *f as f32,
                OscArg::Int(i) => *i as f32,
                _ => return None,
            };
            Some((label, value))
        }
        _ => None,
    }
}

/// Parse a midiman OSC event into a SetMasterGain value.
fn parse_set_gain(event: &midiman::engine::TimedEvent) -> Option<f32> {
    match &event.event.value {
        Value::Osc { address, args } if address == "/soundman/gain" => {
            #[allow(clippy::cast_possible_truncation)]
            match args.first()? {
                OscArg::Float(f) => Some(*f as f32),
                OscArg::Int(i) => Some(*i as f32),
                _ => None,
            }
        }
        _ => None,
    }
}

fn run(device: &DeviceConfig, dsp_dir: &PathBuf) -> Result<(), String> {
    let config = EngineConfig {
        sample_rate: device.sample_rate,
        channels: device.channels,
        ..Default::default()
    };

    let (mut audio_engine, processor) = HotReloadEngine::new(&config, dsp_dir)?;

    let callback = make_audio_callback(processor, config.block_size, config.channels);
    let mut backend = CpalBackend::new();
    backend.start(&config, Box::new(callback))?;

    info!("audio started ({}Hz, {} ch)", config.sample_rate, config.channels);

    // Pattern engine.
    let mut pattern_engine = Engine::new(DEFAULT_BPM, BEATS_PER_CYCLE, LOOKAHEAD);

    // Shared node types list for direct ListNodes response in IPC thread.
    let node_types: Arc<RwLock<Vec<String>>> =
        Arc::new(RwLock::new(audio_engine.controller_mut().list_node_types()));

    // Single command channel: IPC thread → main loop.
    let (cmd_tx, cmd_rx) = crossbeam_channel::unbounded::<LoopCommand>();

    let sock = socket_path();
    let ipc_handle = start_ipc(sock, cmd_tx, Arc::clone(&node_types))?;

    info!("noise-engine ready");
    info!("  socket: {}", ipc_handle.socket_path.display());
    info!("  DSP dir: {}", dsp_dir.display());
    info!("  bpm: {DEFAULT_BPM}");
    info!("  lookahead: {}ms", LOOKAHEAD.as_millis());

    midiman::rt::set_realtime_priority();

    let mut midi_sink = try_connect_midi();
    let midi_clock_enabled = std::env::var("MIDIMAN_MIDI_CLOCK").is_ok_and(|v| v == "1");
    let mut next_clock_tick: Option<Instant> = None;
    if midi_clock_enabled {
        if let Some(sink) = midi_sink.as_mut() {
            let _ = sink.send_clock_start();
        }
        next_clock_tick = Some(Instant::now());
        info!("  midi clock: enabled (24 ppqn)");
    }

    let mut note_offs: BinaryHeap<Reverse<PendingNoteOff>> = BinaryHeap::new();

    // Pending SetControl events (drained from pattern engine with lookahead,
    // dispatched to audio engine when due). Small n — linear scan + swap_remove.
    let mut pending: Vec<PendingControl> = Vec::new();

    let stop = Arc::new(AtomicBool::new(false));

    loop {
        if stop.load(Ordering::Relaxed) {
            break;
        }

        let now = Instant::now();

        // ① Drain IPC commands (single channel, sum type).
        while let Ok(cmd) = cmd_rx.try_recv() {
            match cmd {
                LoopCommand::Pattern(c) => pattern_engine.apply(c),
                LoopCommand::Graph(msg) => {
                    match msg {
                        ClientMessage::Shutdown => {
                            backend.stop();
                            return Ok(());
                        }
                        ClientMessage::LoadGraph(ir) => {
                            if let Err(e) = audio_engine.load_graph(ir) {
                                warn!("load_graph: {e}");
                            }
                            // Update shared node types after potential registry change.
                            if let Ok(mut types) = node_types.write() {
                                *types = audio_engine.controller_mut().list_node_types();
                            }
                        }
                        other => {
                            if let Err(e) = audio_engine.controller_mut().handle_message(other) {
                                warn!("handle_message: {e}");
                            }
                        }
                    }
                }
            }
        }

        // ② Fill pattern heap.
        pattern_engine.fill(now);

        // ③ Drain events with lookahead.
        //    OSC → SetControl: schedule in pending vec for sample-accurate dispatch.
        //    MIDI notes/CC: dispatch immediately when due (no lookahead for MIDI).
        for timed_event in pattern_engine.drain(now + LOOKAHEAD) {
            if let Some((label, value)) = parse_set_control(&timed_event) {
                pending.push(PendingControl {
                    fire_at: timed_event.fire_at,
                    label: label.to_owned(),
                    value,
                });
            } else if let Some(gain) = parse_set_gain(&timed_event) {
                pending.push(PendingControl {
                    fire_at: timed_event.fire_at,
                    label: String::new(), // empty label = master gain
                    value: gain,
                });
            } else {
                // MIDI note/CC — dispatch when due.
                match &timed_event.event.value {
                    Value::Note { channel, note, dur, .. } => {
                        if timed_event.fire_at <= now {
                            let cycle_dur_secs =
                                BEATS_PER_CYCLE * 60.0 / pattern_engine.bpm();
                            let note_off_at = timed_event.fire_at
                                + Duration::from_secs_f64(dur * cycle_dur_secs);
                            note_offs.push(Reverse(PendingNoteOff {
                                fire_at: note_off_at,
                                channel: *channel,
                                note: *note,
                            }));
                            let _ =
                                output::dispatch(&timed_event, &mut midi_sink, &mut None);
                        }
                    }
                    _ => {
                        if timed_event.fire_at <= now {
                            let _ =
                                output::dispatch(&timed_event, &mut midi_sink, &mut None);
                        }
                    }
                }
            }
        }

        // ④ Dispatch pending SetControl events that are now due.
        let mut i = 0;
        while i < pending.len() {
            if pending[i].fire_at <= now {
                let ctrl = pending.swap_remove(i);
                if ctrl.label.is_empty() {
                    // Master gain.
                    if let Err(e) = audio_engine
                        .controller_mut()
                        .handle_message(ClientMessage::SetMasterGain { gain: ctrl.value })
                    {
                        warn!("set_master_gain: {e}");
                    }
                } else if let Err(e) = audio_engine
                    .controller_mut()
                    .handle_message(ClientMessage::SetControl {
                        label: ctrl.label,
                        value: ctrl.value,
                    })
                {
                    warn!("set_control: {e}");
                }
            } else {
                i += 1;
            }
        }

        // ⑤ Check FAUST background reload (non-blocking).
        if let Err(e) = audio_engine.poll_reload() {
            warn!("poll_reload: {e}");
        }

        // ⑥ Drain any note-offs that are now due.
        drain_note_offs(&mut note_offs, &mut midi_sink);

        // ⑦ MIDI clock ticks.
        if let Some(ref mut next_tick) = next_clock_tick {
            let tick_now = Instant::now();
            while *next_tick <= tick_now {
                if let Some(sink) = midi_sink.as_mut() {
                    let _ = sink.send_clock_tick();
                }
                let tick_interval =
                    Duration::from_secs_f64(60.0 / (pattern_engine.bpm() * 24.0));
                *next_tick += tick_interval;
            }
        }

        // ⑧ Sleep until next event (capped at 1ms for command responsiveness).
        let deadline = earliest_deadline(
            pattern_engine.next_deadline(),
            note_offs.peek().map(|Reverse(n)| n.fire_at),
            next_clock_tick,
            pending.iter().map(|p| p.fire_at).min(),
        );
        let sleep = deadline.saturating_duration_since(Instant::now()).min(MAX_SLEEP);
        if sleep > Duration::ZERO {
            spin_sleep::sleep(sleep);
        }
    }

    Ok(())
}

fn earliest_deadline(
    a: Option<Instant>,
    b: Option<Instant>,
    c: Option<Instant>,
    d: Option<Instant>,
) -> Instant {
    let fallback = Instant::now() + MAX_SLEEP;
    [a, b, c, d].into_iter().flatten().min().unwrap_or(fallback)
}

fn drain_note_offs(
    heap: &mut BinaryHeap<Reverse<PendingNoteOff>>,
    midi_sink: &mut Option<Box<dyn OutputSink>>,
) {
    let now = Instant::now();
    while let Some(Reverse(pending)) = heap.peek() {
        if pending.fire_at > now {
            break;
        }
        let pending = heap.pop().expect("just peeked").0;
        if let Some(sink) = midi_sink.as_mut() {
            let _ = sink.send_note_off(pending.channel, pending.note);
        }
    }
}

fn try_connect_midi() -> Option<Box<dyn OutputSink>> {
    match midiman::output::midi::MidiSink::connect_first("noise-engine") {
        Ok(sink) => {
            info!("  midi: connected to '{}'", sink.name());
            Some(Box::new(sink))
        }
        Err(e) => {
            info!("  midi: {e} (running without MIDI)");
            None
        }
    }
}

// ── IPC ─────────────────────────────────────────────────────────────────────

/// Handle to the IPC server thread.
struct IpcHandle {
    socket_path: PathBuf,
    stop: Arc<AtomicBool>,
    _thread: std::thread::JoinHandle<()>,
}

impl Drop for IpcHandle {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        // Wake the blocking accept() by connecting.
        let _ = std::os::unix::net::UnixStream::connect(&self.socket_path);
        let _ = std::fs::remove_file(&self.socket_path);
    }
}

/// Start the unified IPC server.
///
/// Handles both midiman pattern commands and soundman graph commands.
/// ListNodes is handled directly (no round-trip through main loop).
fn start_ipc(
    socket_path: PathBuf,
    cmd_tx: crossbeam_channel::Sender<LoopCommand>,
    node_types: Arc<RwLock<Vec<String>>>,
) -> Result<IpcHandle, String> {
    let _ = std::fs::remove_file(&socket_path);
    let listener = std::os::unix::net::UnixListener::bind(&socket_path)
        .map_err(|e| format!("bind {}: {e}", socket_path.display()))?;
    listener
        .set_nonblocking(false)
        .map_err(|e| e.to_string())?;

    let stop = Arc::new(AtomicBool::new(false));
    let stop_clone = Arc::clone(&stop);
    let path = socket_path.clone();

    let thread = std::thread::Builder::new()
        .name("noise-ipc".into())
        .spawn(move || ipc_server(listener, cmd_tx, node_types, stop_clone))
        .expect("failed to spawn IPC thread");

    Ok(IpcHandle {
        socket_path: path,
        stop,
        _thread: thread,
    })
}

fn ipc_server(
    listener: std::os::unix::net::UnixListener,
    cmd_tx: crossbeam_channel::Sender<LoopCommand>,
    node_types: Arc<RwLock<Vec<String>>>,
    stop: Arc<AtomicBool>,
) {
    for stream in listener.incoming() {
        if stop.load(Ordering::Relaxed) {
            break;
        }
        match stream {
            Ok(stream) => {
                stream
                    .set_read_timeout(Some(Duration::from_millis(100)))
                    .ok();
                ipc_handle_connection(stream, &cmd_tx, &node_types, &stop);
            }
            Err(_) => break,
        }
    }
}

/// Wire protocol: the unified binary accepts BOTH midiman and soundman message
/// formats on a single socket. Discrimination is by the tag field:
///
/// - midiman messages use `"cmd"` tag: SetPattern, Hush, HushAll, SetBpm, Batch, Ping
/// - soundman messages use `"type"` tag: load_graph, set_control, set_master_gain, list_nodes, shutdown, ping
///
/// This lets both the pattern frontend and the graph frontend talk to the same socket.
fn ipc_handle_connection(
    stream: std::os::unix::net::UnixStream,
    cmd_tx: &crossbeam_channel::Sender<LoopCommand>,
    node_types: &Arc<RwLock<Vec<String>>>,
    stop: &AtomicBool,
) {
    use std::io::{BufRead, BufReader, Write};

    let reader = BufReader::new(stream.try_clone().expect("clone stream"));
    let mut writer = stream;

    for line in reader.lines() {
        if stop.load(Ordering::Relaxed) {
            break;
        }
        let line = match line {
            Ok(l) => l,
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => continue,
            Err(_) => break,
        };
        if line.trim().is_empty() {
            continue;
        }

        let response = dispatch_ipc_message(&line, cmd_tx, node_types);
        let mut json = serde_json::to_string(&response).expect("serialize response");
        json.push('\n');
        if writer.write_all(json.as_bytes()).is_err() {
            break;
        }
    }
}

/// Try to parse as a midiman message first (has "cmd" field), then as a
/// soundman message (has "type" field).
fn dispatch_ipc_message(
    line: &str,
    cmd_tx: &crossbeam_channel::Sender<LoopCommand>,
    node_types: &Arc<RwLock<Vec<String>>>,
) -> IpcResponse {
    // Try midiman protocol first (pattern commands).
    if let Ok(msg) = serde_json::from_str::<midiman::ipc::protocol::ClientMessage>(line) {
        return handle_midiman_message(msg, cmd_tx);
    }

    // Try soundman protocol (graph commands).
    if let Ok(msg) = serde_json::from_str::<ClientMessage>(line) {
        return handle_soundman_message(msg, cmd_tx, node_types);
    }

    IpcResponse::Error {
        msg: format!("unrecognized message: {line}"),
    }
}

fn handle_midiman_message(
    msg: midiman::ipc::protocol::ClientMessage,
    cmd_tx: &crossbeam_channel::Sender<LoopCommand>,
) -> IpcResponse {
    use midiman::ipc::protocol::ClientMessage as MidimanMsg;

    match msg {
        MidimanMsg::Ping => IpcResponse::Pong,
        MidimanMsg::Batch { commands } => {
            // Phase 1: compile all (fail-safe).
            let mut compiled = Vec::with_capacity(commands.len());
            for cmd in &commands {
                match compile_midiman_command(cmd) {
                    Ok(Some(engine_cmd)) => compiled.push(engine_cmd),
                    Ok(None) => {}
                    Err(e) => return IpcResponse::Error { msg: e },
                }
            }
            // Phase 2: send atomically.
            let n = compiled.len();
            for engine_cmd in compiled {
                let _ = cmd_tx.send(LoopCommand::Pattern(engine_cmd));
            }
            IpcResponse::Ok {
                msg: format!("batch applied ({n} commands)"),
            }
        }
        other => match compile_midiman_command(&other) {
            Ok(Some(engine_cmd)) => {
                let description = describe_engine_command(&engine_cmd);
                let _ = cmd_tx.send(LoopCommand::Pattern(engine_cmd));
                IpcResponse::Ok { msg: description }
            }
            Ok(None) => IpcResponse::Pong,
            Err(e) => IpcResponse::Error { msg: e },
        },
    }
}

fn compile_midiman_command(
    msg: &midiman::ipc::protocol::ClientMessage,
) -> Result<Option<EngineCommand>, String> {
    use midiman::ipc::protocol::ClientMessage as MidimanMsg;

    match msg {
        MidimanMsg::SetPattern { slot, pattern } => {
            let compiled =
                midiman::ir::compile(pattern).map_err(|e| format!("compile error: {e}"))?;
            Ok(Some(EngineCommand::SetPattern {
                name: slot.clone(),
                pattern: compiled,
            }))
        }
        MidimanMsg::Hush { slot } => Ok(Some(EngineCommand::Hush { name: slot.clone() })),
        MidimanMsg::HushAll => Ok(Some(EngineCommand::HushAll)),
        MidimanMsg::SetBpm { bpm } => Ok(Some(EngineCommand::SetBpm { bpm: *bpm })),
        MidimanMsg::Ping => Ok(None),
        MidimanMsg::Batch { .. } => Err("nested Batch is not allowed".into()),
    }
}

fn handle_soundman_message(
    msg: ClientMessage,
    cmd_tx: &crossbeam_channel::Sender<LoopCommand>,
    node_types: &Arc<RwLock<Vec<String>>>,
) -> IpcResponse {
    match msg {
        ClientMessage::Ping => IpcResponse::Pong,
        ClientMessage::ListNodes { .. } => {
            // Handled directly — no round-trip through main loop.
            let types = node_types.read().map_or_else(
                |_| vec![],
                |guard| guard.clone(),
            );
            IpcResponse::NodeTypes { types }
        }
        ClientMessage::Shutdown => {
            let _ = cmd_tx.send(LoopCommand::Graph(ClientMessage::Shutdown));
            IpcResponse::Ok {
                msg: "shutting down".into(),
            }
        }
        other => {
            let _ = cmd_tx.send(LoopCommand::Graph(other));
            IpcResponse::Ok {
                msg: "ok".into(),
            }
        }
    }
}

fn describe_engine_command(cmd: &EngineCommand) -> String {
    match cmd {
        EngineCommand::SetPattern { name, .. } => format!("pattern set on {name}"),
        EngineCommand::Hush { name } => format!("{name} hushed"),
        EngineCommand::HushAll => "all slots hushed".into(),
        EngineCommand::SetBpm { bpm } => format!("bpm set to {bpm}"),
    }
}

/// Unified IPC response type.
/// Compatible with both midiman and soundman response formats.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(tag = "status")]
enum IpcResponse {
    Ok { msg: String },
    Error { msg: String },
    Pong,
    NodeTypes { types: Vec<String> },
}

// ── Entry point ─────────────────────────────────────────────────────────────

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .format_timestamp_millis()
        .init();

    let dsp_dir = resolve_dsp_dir();
    if let Err(e) = std::fs::create_dir_all(&dsp_dir) {
        error!("cannot create DSP dir {}: {e}", dsp_dir.display());
        return;
    }

    let device = CpalBackend::query_device().expect("no audio device");
    info!("audio device: {}Hz, {} ch", device.sample_rate, device.channels);

    if let Err(e) = run(&device, &dsp_dir) {
        error!("{e}");
    }
}
