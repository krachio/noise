//! Unified binary merging the pattern sequencer (midiman) and audio engine
//! (soundman-core + soundman-faust) into a single process.
//!
//! Eliminates OSC overhead between the two — pattern events are dispatched
//! directly to the audio engine's control thread via function calls.

mod ipc;

use std::cmp::Reverse;
use std::collections::BinaryHeap;
use std::path::PathBuf;
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

/// A timed audio-engine command waiting for its scheduled dispatch time.
enum PendingEvent {
    Control { fire_at: Instant, label: String, value: f32 },
    Gain { fire_at: Instant, value: f32 },
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
    let ipc_handle = ipc::start(sock, cmd_tx, Arc::clone(&node_types))?;

    info!("noise-engine ready");
    info!("  socket: {}", ipc_handle.socket_path.display());
    info!("  DSP dir: {}", dsp_dir.display());
    info!("  bpm: {DEFAULT_BPM}");
    info!("  lookahead: {}ms", LOOKAHEAD.as_millis());

    midiman::rt::set_realtime_priority();

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

    let mut note_offs: BinaryHeap<Reverse<PendingNoteOff>> = BinaryHeap::new();

    // Pending SetControl events (drained from pattern engine with lookahead,
    // dispatched to audio engine when due). Small n — linear scan + swap_remove.
    let mut pending: Vec<PendingEvent> = Vec::new();
    let mut pending_midi: Vec<midiman::engine::TimedEvent> = Vec::new();

    loop {
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
                            let cf = crossfade_samples(
                                pattern_engine.bpm(),
                                config.sample_rate,
                            );
                            audio_engine.controller_mut().set_crossfade_samples(cf);
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
                match &ev.event.value {
                    Value::Note { channel, note, dur, .. } => {
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
                    _ => {}
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
                let tick_interval =
                    Duration::from_secs_f64(60.0 / (pattern_engine.bpm() * 24.0));
                *next_tick += tick_interval;
            }
        }

        // ⑨ Sleep until next event (capped at 1ms for command responsiveness).
        let midi_deadline = pending_midi.iter().map(|e| e.fire_at).min();
        let ctrl_deadline = pending.iter().map(|p| p.fire_at()).min();
        let deadline = earliest_deadline(
            pattern_engine.next_deadline(),
            note_offs.peek().map(|Reverse(n)| n.fire_at),
            next_clock_tick,
            [midi_deadline, ctrl_deadline].into_iter().flatten().min(),
        );
        let sleep = deadline.saturating_duration_since(Instant::now()).min(MAX_SLEEP);
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

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use midiman::engine::TimedEvent;
    use midiman::event::{Event, OscArg, Value};
    use midiman::time::{Arc, Time};

    fn make_osc_event(address: &str, args: Vec<OscArg>) -> TimedEvent {
        TimedEvent {
            fire_at: Instant::now(),
            event: Event::new(
                Some(Arc::new(Time::zero(), Time::one())),
                Arc::new(Time::zero(), Time::one()),
                Value::Osc { address: address.into(), args },
            ),
            slot_idx: 0,
        }
    }

    // ── parse_set_control ───────────────────────────────────────────────

    #[test]
    fn parse_set_control_extracts_label_and_value() {
        let event = make_osc_event(
            "/soundman/set",
            vec![OscArg::Str("pitch".into()), OscArg::Float(440.0)],
        );
        let (label, value) = parse_set_control(&event).unwrap();
        assert_eq!(label, "pitch");
        assert!((value - 440.0).abs() < f32::EPSILON);
    }

    #[test]
    fn parse_set_control_accepts_int_value() {
        let event = make_osc_event(
            "/soundman/set",
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
        let event = make_osc_event("/soundman/set", vec![]);
        assert!(parse_set_control(&event).is_none());
    }

    #[test]
    fn parse_set_control_returns_none_for_midi_note() {
        let event = TimedEvent {
            fire_at: Instant::now(),
            event: Event::new(
                Some(Arc::new(Time::zero(), Time::one())),
                Arc::new(Time::zero(), Time::one()),
                Value::Note { channel: 0, note: 60, velocity: 100, dur: 0.5 },
            ),
            slot_idx: 0,
        };
        assert!(parse_set_control(&event).is_none());
    }

    // ── parse_set_gain ──────────────────────────────────────────────────

    #[test]
    fn parse_set_gain_extracts_float() {
        let event = make_osc_event("/soundman/gain", vec![OscArg::Float(0.75)]);
        let gain = parse_set_gain(&event).unwrap();
        assert!((gain - 0.75).abs() < f32::EPSILON);
    }

    #[test]
    fn parse_set_gain_returns_none_for_wrong_address() {
        let event = make_osc_event("/soundman/set", vec![OscArg::Float(0.5)]);
        assert!(parse_set_gain(&event).is_none());
    }

    #[test]
    fn parse_set_gain_returns_none_for_empty_args() {
        let event = make_osc_event("/soundman/gain", vec![]);
        assert!(parse_set_gain(&event).is_none());
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
        assert!((dur_secs - 0.0).abs() < f64::EPSILON, "NaN dur should become 0.0");
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
    info!("audio device: {}Hz, {} ch", device.sample_rate, device.channels);

    if let Err(e) = run(&device, &dsp_dir) {
        error!("{e}");
    }
}
