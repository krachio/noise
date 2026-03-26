//! Unified binary merging the pattern sequencer (pattern-engine) and audio engine
//! (audio-engine + audio-faust) into a single process.
//!
//! Eliminates OSC overhead between the two — pattern events are dispatched
//! directly to the audio engine's control thread via function calls.

mod ipc;

use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap};
use std::path::PathBuf;
use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant};

use log::{error, info, warn};

use audio_engine::automation::{AutoShape, Automation};
use audio_engine::engine::config::EngineConfig;
use audio_engine::output::AudioOutput;
use audio_engine::output::cpal_backend::{CpalBackend, DeviceConfig};
use audio_engine::protocol::ClientMessage;
use audio_faust::hot_reload::HotReloadEngine;
use pattern_engine::engine::{Engine, EngineCommand};
use pattern_engine::event::{OscArg, Value};
use pattern_engine::output::{self, OutputSink};

const DEFAULT_BPM: f64 = 120.0;
const BEATS_PER_CYCLE: f64 = 4.0;
const LOOKAHEAD: Duration = Duration::from_millis(100);
const MAX_SLEEP: Duration = Duration::from_millis(1);

/// Crossfade = 1/2 beat (one 8th note). Long enough that the pattern engine
/// triggers each voice at least once during the blend, so both old and new
/// graphs produce audio throughout the crossfade.
///
/// | BPM | 1/2 beat |
/// |-----|----------|
/// | 60  | 500ms    |
/// | 120 | 250ms    |
/// | 138 | 217ms    |
/// | 180 | 167ms    |
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
fn crossfade_samples(bpm: f64, sample_rate: u32) -> usize {
    let bpm = bpm.max(1.0); // guard: zero/negative BPM → treat as 1
    let half_beat_secs = 60.0 / bpm / 2.0;
    (half_beat_secs * f64::from(sample_rate)) as usize
}

/// Number of audio blocks per pattern cycle.
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss
)]
fn compute_blocks_per_cycle(bpm: f64, beats_per_cycle: f64, sample_rate: u32, block_size: usize) -> usize {
    let cycle_secs = beats_per_cycle * 60.0 / bpm.max(1.0);
    (cycle_secs * f64::from(sample_rate) / block_size as f64)
        .round()
        .max(1.0) as usize
}

/// Process a graph command on the main loop. Returns Ok(description) or Err(error).
/// Caller is responsible for logging errors and sending ack if needed.
fn handle_graph_cmd(
    msg: ClientMessage,
    audio_engine: &mut audio_faust::hot_reload::HotReloadEngine,
    backend: &mut audio_engine::output::cpal_backend::CpalBackend,
    pattern_engine: &pattern_engine::engine::Engine,
    config: &audio_engine::engine::config::EngineConfig,
    node_types: &Arc<RwLock<Vec<String>>>,
    midi_mappings: &mut HashMap<(u8, u8), MidiMapping>,
) -> Result<String, String> {
    match msg {
        ClientMessage::Shutdown => Ok("shutting down".into()),
        ClientMessage::LoadGraph(ir) => {
            let cf = crossfade_samples(pattern_engine.bpm(), config.sample_rate);
            audio_engine.controller_mut().set_crossfade_samples(cf);
            audio_engine.load_graph(ir).map_err(|e| format!("load_graph: {e}"))?;
            if let Ok(mut types) = node_types.write() {
                *types = audio_engine.controller_mut().list_node_types();
            }
            Ok("graph loaded".into())
        }
        ClientMessage::StartInput { channel } => {
            let consumer = backend
                .start_input(config.sample_rate, channel as usize)
                .map_err(|e| format!("start_input: {e}"))?;
            let adc = audio_engine::nodes::adc::AdcNode::new(consumer);
            audio_engine
                .controller_mut()
                .inject_node("adc_in".into(), Box::new(adc));
            info!("audio input started (ch {channel})");
            Ok(format!("input started (ch {channel})"))
        }
        ClientMessage::MidiMap {
            channel,
            cc,
            label,
            lo,
            hi,
        } => {
            midi_mappings.insert((channel, cc), MidiMapping { label: label.clone(), lo, hi });
            info!("midi_map: ch{channel} cc{cc} → [{lo}, {hi}]");
            Ok(format!("midi_map: ch{channel} cc{cc} → {label}"))
        }
        other => {
            audio_engine
                .controller_mut()
                .handle_message(other)
                .map_err(|e| format!("handle_message: {e}"))?;
            Ok("ok".into())
        }
    }
}

/// Result sent back from the main loop to the IPC thread for acknowledged commands.
pub type AckResult = Result<String, String>;

/// Commands routed from the IPC thread to the main loop.
/// Single channel, single `try_recv()`, single match.
enum LoopCommand {
    Pattern(EngineCommand),
    /// Graph command with acknowledgment — IPC thread waits for the result.
    Graph(ClientMessage, crossbeam_channel::Sender<AckResult>),
    /// Status query — returns combined snapshot of both engines.
    Status(crossbeam_channel::Sender<ipc::IpcResponse>),
}

/// A MIDI CC → exposed control mapping. CC values (0–127) are scaled to [lo, hi].
struct MidiMapping {
    label: String,
    lo: f32,
    hi: f32,
}

/// Messages received from MIDI input hardware.
/// Parsed from raw MIDI bytes in the midir callback — pattern-engine never sees raw bytes.
#[derive(Debug, Clone)]
#[cfg_attr(not(test), allow(dead_code))]
enum MidiInputMsg {
    Cc { channel: u8, cc: u8, value: u8 },
    ClockTick(Instant),
    ClockStart,
    ClockStop,
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

/// A timed audio-engine command waiting for its scheduled dispatch time.
enum PendingEvent {
    Control {
        fire_at: Instant,
        label: String,
        value: f32,
    },
    Gain {
        fire_at: Instant,
        value: f32,
    },
}

impl PendingEvent {
    const fn fire_at(&self) -> Instant {
        match self {
            Self::Control { fire_at, .. } | Self::Gain { fire_at, .. } => *fire_at,
        }
    }
}

fn resolve_dsp_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("NOISE_DSP_DIR") {
        return PathBuf::from(dir);
    }
    std::env::var("HOME").map_or_else(
        |_| PathBuf::from("/tmp/noise/dsp"),
        |h| PathBuf::from(h).join(".krach/dsp"),
    )
}

fn socket_path() -> PathBuf {
    std::env::var("NOISE_SOCKET").map_or_else(
        |_| std::env::temp_dir().join("krach.sock"),
        PathBuf::from,
    )
}

fn tcp_addr() -> Option<std::net::SocketAddr> {
    // Check --tcp CLI arg first, then NOISE_TCP_ADDR env var.
    let args: Vec<String> = std::env::args().collect();
    let addr_str = args
        .windows(2)
        .find(|w| w[0] == "--tcp")
        .map(|w| w[1].clone())
        .or_else(|| std::env::var("NOISE_TCP_ADDR").ok())?;
    addr_str.parse().ok()
}

fn make_audio_callback(
    mut processor: audio_engine::engine::AudioProcessor,
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

/// Parse a pattern-engine OSC event into a (label, value) pair for direct dispatch.
///
/// Matches events with address "/audio/set" and args `[Str(label), Float(value)]`.
/// Returns `None` for non-`SetControl` events (MIDI notes, CCs, other OSC addresses).
fn parse_set_control(event: &pattern_engine::engine::TimedEvent) -> Option<(&str, f32)> {
    match &event.event.value {
        Value::Osc { address, args } if address == "/audio/set" => {
            let label = match args.first()? {
                OscArg::Str(s) => s.as_str(),
                OscArg::Float(_) | OscArg::Int(_) => return None,
            };
            #[allow(clippy::cast_possible_truncation, clippy::cast_precision_loss)]
            let value = match args.get(1)? {
                OscArg::Float(f) => *f as f32,
                OscArg::Int(i) => *i as f32,
                OscArg::Str(_) => return None,
            };
            Some((label, value))
        }
        _ => None,
    }
}

/// Parse a pattern-engine OSC event into a `SetMasterGain` value.
fn parse_set_gain(event: &pattern_engine::engine::TimedEvent) -> Option<f32> {
    match &event.event.value {
        Value::Osc { address, args } if address == "/audio/gain" =>
        {
            #[allow(clippy::cast_possible_truncation, clippy::cast_precision_loss)]
            match args.first()? {
                OscArg::Float(f) => Some(*f as f32),
                OscArg::Int(i) => Some(*i as f32),
                OscArg::Str(_) => None,
            }
        }
        _ => None,
    }
}

#[allow(clippy::too_many_lines, clippy::cognitive_complexity)]
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

    info!(
        "audio started ({}Hz, {} ch)",
        config.sample_rate, config.channels
    );

    // Pattern engine.
    let mut pattern_engine = Engine::new(DEFAULT_BPM, BEATS_PER_CYCLE, LOOKAHEAD);

    // Shared node types list for direct ListNodes response in IPC thread.
    let node_types: Arc<RwLock<Vec<String>>> =
        Arc::new(RwLock::new(audio_engine.controller_mut().list_node_types()));

    // Single command channel: IPC thread → main loop.
    let (cmd_tx, cmd_rx) = crossbeam_channel::unbounded::<LoopCommand>();

    let sock = socket_path();
    let ipc_handle = ipc::start(sock, cmd_tx.clone(), Arc::clone(&node_types))?;

    // Optional TCP listener (--tcp <addr> or NOISE_TCP_ADDR env var).
    let _tcp_handle = if let Some(addr) = tcp_addr() {
        let handle = ipc::start_tcp(addr, cmd_tx, Arc::clone(&node_types))?;
        info!("tcp: listening on {}", handle.addr);
        // Write token to ~/.krach/token for clients to read.
        let token_path = std::env::var("HOME").map_or_else(
            |_| PathBuf::from("/tmp/krach.token"),
            |h| PathBuf::from(h).join(".krach/token"),
        );
        let _ = std::fs::write(&token_path, &handle.token);
        info!("tcp: token written to {}", token_path.display());
        Some(handle)
    } else {
        drop(cmd_tx);
        None
    };

    info!("krach-engine ready");
    info!("  socket: {}", ipc_handle.socket_path.display());
    info!("  DSP dir: {}", dsp_dir.display());
    info!("  bpm: {DEFAULT_BPM}");
    info!("  lookahead: {}ms", LOOKAHEAD.as_millis());

    let _ = pattern_engine::rt::set_realtime_priority();

    let mut midi_sink = try_connect_midi();
    let midi_clock_enabled = std::env::var("NOISE_MIDI_CLOCK").is_ok_and(|v| v == "1");
    let mut next_clock_tick: Option<Instant> = None;
    if midi_clock_enabled {
        if let Some(sink) = midi_sink.as_mut() {
            let _ = sink.send_clock_start();
        }
        next_clock_tick = Some(Instant::now());
        info!("  midi clock: enabled (24 ppqn)");
    }

    // MIDI input — receives CC and clock messages from a connected MIDI controller.
    let midi_input_rx = try_connect_midi_input();

    // MIDI CC → exposed control mappings. Key = (channel, cc_number).
    let mut midi_mappings: HashMap<(u8, u8), MidiMapping> = HashMap::new();

    let mut note_offs: BinaryHeap<Reverse<PendingNoteOff>> = BinaryHeap::new();

    // Pending SetControl events (drained from pattern engine with lookahead,
    // dispatched to audio engine when due). Small n — linear scan + swap_remove.
    let mut pending: Vec<PendingEvent> = Vec::new();
    let mut pending_midi: Vec<pattern_engine::engine::TimedEvent> = Vec::new();

    // ── Control-voice curve compilation state ──
    let mut blocks_per_cycle = compute_blocks_per_cycle(
        DEFAULT_BPM,
        BEATS_PER_CYCLE,
        config.sample_rate,
        config.block_size,
    );
    // Active automation IDs per slot index — for cleanup on hush/replace.
    let mut active_curve_ids: HashMap<usize, Vec<String>> = HashMap::new();

    loop {
        let now = Instant::now();

        // ① Drain IPC commands (single channel, sum type).
        while let Ok(cmd) = cmd_rx.try_recv() {
            match cmd {
                LoopCommand::Pattern(c) => {
                    // Clear active automations for affected control-voice slots
                    // BEFORE applying the command (slot may be overwritten).
                    match &c {
                        EngineCommand::SetPattern { name, .. }
                        | EngineCommand::SetPatternFromZero { name, .. }
                        | EngineCommand::Hush { name } => {
                            if let Some(idx) = pattern_engine.slot_idx(name)
                                && let Some(ids) = active_curve_ids.remove(&idx)
                            {
                                for id in ids {
                                    audio_engine.controller_mut().clear_automation(id);
                                }
                            }
                        }
                        EngineCommand::HushAll => {
                            for (_, ids) in active_curve_ids.drain() {
                                for id in ids {
                                    audio_engine.controller_mut().clear_automation(id);
                                }
                            }
                        }
                        EngineCommand::SetBpm { .. }
                        | EngineCommand::SetBeatsPerCycle { .. }
                        | EngineCommand::SetClockSource(_) => {}
                    }
                    pattern_engine.apply(c);
                    // Recompute blocks_per_cycle on tempo/meter change.
                    blocks_per_cycle = compute_blocks_per_cycle(
                        pattern_engine.bpm(),
                        BEATS_PER_CYCLE,
                        config.sample_rate,
                        config.block_size,
                    );
                }
                LoopCommand::Graph(msg, ack_tx) => {
                    if matches!(msg, ClientMessage::Shutdown) {
                        let _ = ack_tx.send(Ok("shutting down".into()));
                        backend.stop();
                        return Ok(());
                    }
                    let result = handle_graph_cmd(
                        msg, &mut audio_engine, &mut backend,
                        &pattern_engine, &config, &node_types, &mut midi_mappings,
                    );
                    if let Err(ref e) = result {
                        warn!("{e}");
                    }
                    let _ = ack_tx.send(result);
                }
                LoopCommand::Status(reply_tx) => {
                    let snap = audio_engine.controller_mut().snapshot();
                    let slot_info = pattern_engine.slot_info();
                    let response = ipc::build_state_response(
                        snap,
                        slot_info,
                        pattern_engine.bpm(),
                        BEATS_PER_CYCLE,
                        f64::from(audio_engine.controller_mut().master_gain()),
                    );
                    let _ = reply_tx.send(response);
                }
            }
        }

        // ② Fill pattern heap (skips control-voice slots).
        pattern_engine.fill(now);

        // ②b Compile control-voice patterns to block-rate wavetables.
        #[allow(
            clippy::cast_possible_truncation,
            clippy::cast_sign_loss,
            clippy::cast_precision_loss
        )]
        {
            let curves = pattern_engine.fill_control_curves(now, blocks_per_cycle);
            for curve in curves {
                let slot_name = pattern_engine.slot_name(curve.slot_idx);
                let id = format!("{slot_name}/{}", curve.label);
                if let Some((node_id, param)) =
                    audio_engine.controller_mut().resolve_label(&curve.label)
                {
                    let cycle_secs = BEATS_PER_CYCLE * 60.0 / pattern_engine.bpm();
                    let period_samples =
                        (cycle_secs * f64::from(config.sample_rate)).round() as usize;
                    let automation = Automation {
                        node_id: node_id.to_owned(),
                        param: param.to_owned(),
                        shape: AutoShape::Custom { table: curve.table },
                        lo: 0.0,
                        hi: 1.0,
                        period_samples,
                        phase: 0,
                        active: true,
                        one_shot: true,
                    };
                    audio_engine
                        .controller_mut()
                        .send_automation(id.clone(), automation);
                    active_curve_ids.entry(curve.slot_idx).or_default().push(id);
                }
            }
        }

        // ③ Drain events with lookahead.
        //    OSC → SetControl: schedule in pending vec for sample-accurate dispatch.
        //    MIDI notes/CC: dispatch immediately when due (no lookahead for MIDI).
        for timed_event in pattern_engine.drain(now + LOOKAHEAD) {
            if let Value::Control { ref label, value } = timed_event.event.value {
                // Direct typed control — no OSC string parsing needed.
                pending.push(PendingEvent::Control {
                    fire_at: timed_event.fire_at,
                    label: label.clone(),
                    value,
                });
            } else if let Some((label, value)) = parse_set_control(&timed_event) {
                // Legacy OSC-based control (backward compatible).
                pending.push(PendingEvent::Control {
                    fire_at: timed_event.fire_at,
                    label: label.to_owned(),
                    value,
                });
            } else if let Some(value) = parse_set_gain(&timed_event) {
                pending.push(PendingEvent::Gain {
                    fire_at: timed_event.fire_at,
                    value,
                });
            } else {
                // MIDI note/CC — hold in pending_midi until fire_at.
                pending_midi.push(timed_event);
            }
        }

        // ④ Dispatch pending events that are now due.
        let mut i = 0;
        while i < pending.len() {
            if pending[i].fire_at() <= now {
                let msg = match pending.swap_remove(i) {
                    PendingEvent::Control { label, value, .. } => {
                        ClientMessage::SetControl { label, value }
                    }
                    PendingEvent::Gain { value, .. } => {
                        ClientMessage::SetMasterGain { gain: value }
                    }
                };
                if let Err(e) = audio_engine.controller_mut().handle_message(msg) {
                    warn!("dispatch pending: {e}");
                }
            } else {
                i += 1;
            }
        }

        // ⑤ Dispatch pending MIDI events that are now due.
        let mut m = 0;
        while m < pending_midi.len() {
            if pending_midi[m].fire_at <= now {
                let ev = pending_midi.swap_remove(m);
                if let Value::Note {
                    channel, note, dur, ..
                } = &ev.event.value
                {
                    let cycle_dur = BEATS_PER_CYCLE * 60.0 / pattern_engine.bpm();
                    let dur_secs = (dur * cycle_dur).max(0.0);
                    if dur_secs.is_finite() {
                        note_offs.push(Reverse(PendingNoteOff {
                            fire_at: ev.fire_at + Duration::from_secs_f64(dur_secs),
                            channel: *channel,
                            note: *note,
                        }));
                    }
                }
                if let Err(e) = output::dispatch(&ev, &mut midi_sink, &mut None) {
                    warn!("midi dispatch: {e}");
                }
            } else {
                m += 1;
            }
        }

        // ⑥ Check FAUST background reload (non-blocking).
        match audio_engine.poll_reload() {
            Ok(reloaded) if !reloaded.is_empty() => {
                // Update shared node types so list_nodes reflects new FAUST types.
                if let Ok(mut types) = node_types.write() {
                    *types = audio_engine.controller_mut().list_node_types();
                }
            }
            Err(e) => warn!("poll_reload: {e}"),
            _ => {}
        }

        // ⑦ Drain any note-offs that are now due.
        drain_note_offs(&mut note_offs, &mut midi_sink);

        // ⑧ MIDI clock ticks.
        if let Some(ref mut next_tick) = next_clock_tick {
            let tick_now = Instant::now();
            while *next_tick <= tick_now {
                if let Some(sink) = midi_sink.as_mut() {
                    let _ = sink.send_clock_tick();
                }
                let tick_interval = Duration::from_secs_f64(60.0 / (pattern_engine.bpm() * 24.0));
                *next_tick += tick_interval;
            }
        }

        // ⑨ Poll MIDI input and dispatch mapped controls / clock messages.
        while let Ok(midi_msg) = midi_input_rx.try_recv() {
            match midi_msg {
                MidiInputMsg::Cc { channel, cc, value } => {
                    if let Some(mapping) = midi_mappings.get(&(channel, cc)) {
                        #[allow(clippy::cast_precision_loss)]
                        let scaled = (mapping.hi - mapping.lo).mul_add(f32::from(value) / 127.0, mapping.lo);
                        let msg = ClientMessage::SetControl {
                            label: mapping.label.clone(),
                            value: scaled,
                        };
                        if let Err(e) = audio_engine.controller_mut().handle_message(msg) {
                            warn!("midi_map dispatch: {e}");
                        }
                    }
                }
                MidiInputMsg::ClockTick(_) | MidiInputMsg::ClockStart | MidiInputMsg::ClockStop => {
                    // Consumed by ClockFollower once main loop integration lands.
                }
            }
        }

        // ⑩ Sleep until next event (capped at 1ms for command responsiveness).
        let midi_deadline = pending_midi.iter().map(|e| e.fire_at).min();
        let ctrl_deadline = pending.iter().map(PendingEvent::fire_at).min();
        let deadline = earliest_deadline(
            pattern_engine.next_deadline(),
            note_offs.peek().map(|Reverse(n)| n.fire_at),
            next_clock_tick,
            [midi_deadline, ctrl_deadline].into_iter().flatten().min(),
        );
        let sleep = deadline
            .saturating_duration_since(Instant::now())
            .min(MAX_SLEEP);
        if sleep > Duration::ZERO {
            spin_sleep::sleep(sleep);
        }
    }
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

/// Try to open a MIDI input port and return a channel receiver for MIDI messages.
/// Parses CC (0xB0–0xBF), clock tick (0xF8), start (0xFA), and stop (0xFC).
fn try_connect_midi_input() -> crossbeam_channel::Receiver<MidiInputMsg> {
    let (tx, rx) = crossbeam_channel::unbounded();
    match midir::MidiInput::new("krach-engine-in") {
        Ok(mut midi_in) => {
            // Ignore sysex and active sense, but NOT timing — we need clock bytes.
            midi_in.ignore(midir::Ignore::SysexAndActiveSense);
            let ports = midi_in.ports();
            if let Some(port) = ports.first() {
                let port_name = midi_in.port_name(port).unwrap_or_default();
                match midi_in.connect(
                    port,
                    "noise-in",
                    move |_stamp, msg, ()| {
                        let parsed = match msg {
                            [status, cc, value] if (status & 0xF0) == 0xB0 => {
                                Some(MidiInputMsg::Cc {
                                    channel: status & 0x0F,
                                    cc: *cc,
                                    value: *value,
                                })
                            }
                            [0xF8] => Some(MidiInputMsg::ClockTick(Instant::now())),
                            [0xFA] => Some(MidiInputMsg::ClockStart),
                            [0xFC] => Some(MidiInputMsg::ClockStop),
                            _ => None,
                        };
                        if let Some(msg) = parsed {
                            let _ = tx.send(msg);
                        }
                    },
                    (),
                ) {
                    Ok(conn) => {
                        info!("  midi input: connected to '{port_name}'");
                        // Leak the connection to keep it alive for the process lifetime.
                        // This is intentional — the MIDI input thread runs until process exit.
                        std::mem::forget(conn);
                    }
                    Err(e) => info!("  midi input: connect failed: {e}"),
                }
            } else {
                info!("  midi input: no ports available");
            }
        }
        Err(e) => info!("  midi input: {e} (running without MIDI input)"),
    }
    rx
}

fn try_connect_midi() -> Option<Box<dyn OutputSink>> {
    match pattern_engine::output::midi::MidiSink::connect_first("krach-engine") {
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

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use pattern_engine::engine::TimedEvent;
    use pattern_engine::event::{Event, OscArg, Value};
    use pattern_engine::time::{Arc, Time};

    fn make_osc_event(address: &str, args: Vec<OscArg>) -> TimedEvent {
        TimedEvent {
            fire_at: Instant::now(),
            event: Event::new(
                Some(Arc::new(Time::zero(), Time::one())),
                Arc::new(Time::zero(), Time::one()),
                Value::Osc {
                    address: address.into(),
                    args,
                },
            ),
            slot_idx: 0,
        }
    }

    // ── parse_set_control ───────────────────────────────────────────────

    #[test]
    fn parse_set_control_extracts_label_and_value() {
        let event = make_osc_event(
            "/audio/set",
            vec![OscArg::Str("pitch".into()), OscArg::Float(440.0)],
        );
        let (label, value) = parse_set_control(&event).unwrap();
        assert_eq!(label, "pitch");
        assert!((value - 440.0).abs() < f32::EPSILON);
    }

    #[test]
    fn parse_set_control_accepts_int_value() {
        let event = make_osc_event(
            "/audio/set",
            vec![OscArg::Str("gate".into()), OscArg::Int(1)],
        );
        let (label, value) = parse_set_control(&event).unwrap();
        assert_eq!(label, "gate");
        assert!((value - 1.0).abs() < f32::EPSILON);
    }

    #[test]
    fn parse_set_control_returns_none_for_wrong_address() {
        let event = make_osc_event(
            "/other/set",
            vec![OscArg::Str("pitch".into()), OscArg::Float(440.0)],
        );
        assert!(parse_set_control(&event).is_none());
    }

    #[test]
    fn parse_set_control_returns_none_for_missing_args() {
        let event = make_osc_event("/audio/set", vec![]);
        assert!(parse_set_control(&event).is_none());
    }

    #[test]
    fn parse_set_control_returns_none_for_midi_note() {
        let event = TimedEvent {
            fire_at: Instant::now(),
            event: Event::new(
                Some(Arc::new(Time::zero(), Time::one())),
                Arc::new(Time::zero(), Time::one()),
                Value::Note {
                    channel: 0,
                    note: 60,
                    velocity: 100,
                    dur: 0.5,
                },
            ),
            slot_idx: 0,
        };
        assert!(parse_set_control(&event).is_none());
    }

    // ── parse_set_gain ──────────────────────────────────────────────────

    #[test]
    fn parse_set_gain_extracts_float() {
        let event = make_osc_event("/audio/gain", vec![OscArg::Float(0.75)]);
        let gain = parse_set_gain(&event).unwrap();
        assert!((gain - 0.75).abs() < f32::EPSILON);
    }

    #[test]
    fn parse_set_gain_returns_none_for_wrong_address() {
        let event = make_osc_event("/audio/set", vec![OscArg::Float(0.5)]);
        assert!(parse_set_gain(&event).is_none());
    }

    #[test]
    fn parse_set_gain_returns_none_for_empty_args() {
        let event = make_osc_event("/audio/gain", vec![]);
        assert!(parse_set_gain(&event).is_none());
    }

    // ── Control variant dispatch ────────────────────────────────────────

    #[test]
    fn test_control_event_dispatches() {
        // Value::Control should be recognized directly (no OSC parsing needed)
        let event = TimedEvent {
            fire_at: Instant::now(),
            event: Event::new(
                Some(Arc::new(Time::zero(), Time::one())),
                Arc::new(Time::zero(), Time::one()),
                Value::Control {
                    label: "bass/cutoff".into(),
                    value: 1200.0,
                },
            ),
            slot_idx: 0,
        };
        // parse_set_control should return None for Control variant (it only handles Osc)
        assert!(parse_set_control(&event).is_none());
        // parse_set_gain should also return None
        assert!(parse_set_gain(&event).is_none());

        // The dispatch code should match Value::Control directly
        match &event.event.value {
            Value::Control { label, value } => {
                assert_eq!(label, "bass/cutoff");
                assert!((value - 1200.0).abs() < f32::EPSILON);
            }
            _ => panic!("expected Control variant"),
        }
    }

    // ── MidiInputMsg ──────────────────────────────────────────────────

    #[test]
    fn midi_input_msg_cc_from_raw_bytes() {
        // Status 0xB2 = CC on channel 2, cc=74, value=100
        let status: u8 = 0xB2;
        let cc: u8 = 74;
        let value: u8 = 100;
        let msg = MidiInputMsg::Cc {
            channel: status & 0x0F,
            cc,
            value,
        };
        match msg {
            MidiInputMsg::Cc { channel, cc, value } => {
                assert_eq!(channel, 2);
                assert_eq!(cc, 74);
                assert_eq!(value, 100);
            }
            _ => panic!("expected Cc variant"),
        }
    }

    #[test]
    fn midi_input_msg_clock_tick_captures_instant() {
        let before = Instant::now();
        let msg = MidiInputMsg::ClockTick(Instant::now());
        match msg {
            MidiInputMsg::ClockTick(t) => assert!(t >= before),
            _ => panic!("expected ClockTick"),
        }
    }

    #[test]
    fn midi_input_msg_clock_start_stop_are_distinct() {
        let start = MidiInputMsg::ClockStart;
        let stop = MidiInputMsg::ClockStop;
        assert!(matches!(start, MidiInputMsg::ClockStart));
        assert!(matches!(stop, MidiInputMsg::ClockStop));
    }

    #[test]
    fn midi_input_channel_receives_all_message_types() {
        let (tx, rx) = crossbeam_channel::unbounded();
        tx.send(MidiInputMsg::Cc { channel: 0, cc: 1, value: 64 }).unwrap();
        tx.send(MidiInputMsg::ClockTick(Instant::now())).unwrap();
        tx.send(MidiInputMsg::ClockStart).unwrap();
        tx.send(MidiInputMsg::ClockStop).unwrap();

        assert!(matches!(rx.recv().unwrap(), MidiInputMsg::Cc { .. }));
        assert!(matches!(rx.recv().unwrap(), MidiInputMsg::ClockTick(_)));
        assert!(matches!(rx.recv().unwrap(), MidiInputMsg::ClockStart));
        assert!(matches!(rx.recv().unwrap(), MidiInputMsg::ClockStop));
    }

    #[test]
    fn midi_cc_dispatch_ignores_unmapped_channels() {
        let mappings: HashMap<(u8, u8), MidiMapping> = HashMap::new();
        let msg = MidiInputMsg::Cc { channel: 5, cc: 74, value: 100 };
        if let MidiInputMsg::Cc { channel, cc, .. } = &msg {
            // No mapping → no dispatch
            assert!(mappings.get(&(*channel, *cc)).is_none());
        }
    }

    // ── crossfade_samples ───────────────────────────────────────────────

    #[test]
    fn crossfade_at_120_bpm_is_one_eighth_note() {
        // 120 BPM → 1 beat = 500ms → 1/2 beat = 250ms → 12000 samples at 48kHz
        assert_eq!(crossfade_samples(120.0, 48000), 12000);
    }

    #[test]
    fn crossfade_at_60_bpm() {
        // 60 BPM → 1 beat = 1000ms → 1/2 beat = 500ms → 24000 samples at 48kHz
        assert_eq!(crossfade_samples(60.0, 48000), 24000);
    }

    #[test]
    fn crossfade_at_180_bpm() {
        // 180 BPM → 1 beat = 333ms → 1/2 beat = 167ms → 8000 samples at 48kHz
        assert_eq!(crossfade_samples(180.0, 48000), 8000);
    }

    #[test]
    fn crossfade_scales_with_sample_rate() {
        let at_48k = crossfade_samples(120.0, 48000);
        let at_44k = crossfade_samples(120.0, 44100);
        assert!(at_48k > at_44k);
        assert_eq!(at_44k, 11025); // 250ms * 44100 = 11025
    }

    // ── note-off duration guard ───────────────────────────────────────────

    #[test]
    fn negative_note_dur_does_not_panic() {
        // Duration::from_secs_f64 panics on negative values.
        // Guard: (dur * cycle_dur).max(0.0) + is_finite check.
        let dur = -0.5_f64;
        let cycle_dur = 2.0;
        let dur_secs = (dur * cycle_dur).max(0.0);
        assert!(dur_secs.is_finite());
        assert!(dur_secs >= 0.0);
        // Should not panic:
        let _ = Duration::from_secs_f64(dur_secs);
    }

    #[test]
    fn nan_note_dur_becomes_zero() {
        // NaN * anything = NaN, but NaN.max(0.0) = 0.0 in Rust (IEEE 754 maximum).
        // This means NaN durations become immediate note-offs, which is safe.
        let dur = f64::NAN;
        let cycle_dur = 2.0;
        let dur_secs = (dur * cycle_dur).max(0.0);
        assert!(dur_secs.is_finite());
        assert!(
            (dur_secs - 0.0).abs() < f64::EPSILON,
            "NaN dur should become 0.0"
        );
        // Must not panic:
        let _ = std::time::Duration::from_secs_f64(dur_secs);
    }
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
    info!(
        "audio device: {}Hz, {} ch",
        device.sample_rate, device.channels
    );

    if let Err(e) = run(&device, &dsp_dir) {
        error!("{e}");
    }
}
