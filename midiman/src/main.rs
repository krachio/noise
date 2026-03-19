use std::cmp::Reverse;
use std::collections::BinaryHeap;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use midiman::engine::{Engine, EngineCommand};
use midiman::event::Value;
use midiman::output::{self, OutputSink};

const DEFAULT_BPM: f64 = 120.0;
const BEATS_PER_CYCLE: f64 = 4.0;
const LOOKAHEAD: Duration = Duration::from_millis(100);
const MAX_SLEEP: Duration = Duration::from_millis(10);

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

fn main() {
    let socket_path = socket_path();
    eprintln!("midiman starting...");
    eprintln!("  socket: {}", socket_path.display());
    eprintln!("  bpm: {DEFAULT_BPM}");
    eprintln!("  lookahead: {}ms", LOOKAHEAD.as_millis());

    // Engine owns all pattern state and the event heap.
    let mut engine = Engine::new(DEFAULT_BPM, BEATS_PER_CYCLE, LOOKAHEAD);

    // IPC thread compiles patterns and sends EngineCommands to us.
    let (cmd_tx, cmd_rx) = crossbeam_channel::unbounded::<EngineCommand>();
    let ipc_handle = midiman::ipc::start(socket_path, cmd_tx)
        .expect("failed to start IPC server");

    eprintln!("midiman ready. listening on {}", ipc_handle.socket_path().display());

    midiman::rt::set_realtime_priority();

    let mut midi_sink = try_connect_midi();
    let mut osc_sink  = try_connect_osc();

    let midi_clock_enabled = std::env::var("MIDIMAN_MIDI_CLOCK").is_ok_and(|v| v == "1");
    let mut next_clock_tick: Option<Instant> = None;
    if midi_clock_enabled {
        if let Some(sink) = midi_sink.as_mut() {
            let _ = sink.send_clock_start();
        }
        next_clock_tick = Some(Instant::now());
        eprintln!("  midi clock: enabled (24 ppqn)");
    }

    let mut note_offs: BinaryHeap<Reverse<PendingNoteOff>> = BinaryHeap::new();

    loop {
        let now = Instant::now();

        // ① Drain all pending commands from IPC.
        while let Ok(cmd) = cmd_rx.try_recv() {
            engine.apply(cmd);
        }

        // ② Fill heap with events up to the lookahead horizon.
        engine.fill(now);

        // ③ Drain due events from the heap and dispatch them.
        for timed_event in engine.drain(now) {
            // Schedule note-off for MIDI notes.
            if let Value::Note { channel, note, dur, .. } = &timed_event.event.value {
                let cycle_dur_secs = BEATS_PER_CYCLE * 60.0 / engine.bpm();
                let note_off_at = timed_event.fire_at
                    + Duration::from_secs_f64(dur * cycle_dur_secs);
                note_offs.push(Reverse(PendingNoteOff {
                    fire_at: note_off_at,
                    channel: *channel,
                    note: *note,
                }));
            }
            let _ = output::dispatch(&timed_event, &mut midi_sink, &mut osc_sink);
        }

        // ④ Drain any note-offs that are now due.
        drain_note_offs(&mut note_offs, &mut midi_sink);

        // ⑤ MIDI clock ticks.
        if let Some(ref mut next_tick) = next_clock_tick {
            let now = Instant::now();
            while *next_tick <= now {
                if let Some(sink) = midi_sink.as_mut() {
                    let _ = sink.send_clock_tick();
                }
                let tick_interval = Duration::from_secs_f64(60.0 / (engine.bpm() * 24.0));
                *next_tick += tick_interval;
            }
        }

        // ⑥ Sleep until the next due event (or a short cap to process new commands).
        let deadline = earliest_deadline(
            engine.next_deadline(),
            note_offs.peek().map(|Reverse(n)| n.fire_at),
            next_clock_tick,
        );
        let sleep = deadline.saturating_duration_since(Instant::now()).min(MAX_SLEEP);
        if sleep > Duration::ZERO {
            spin_sleep::sleep(sleep);
        }
    }
}

/// Return the earliest of up to three optional deadlines.
fn earliest_deadline(
    a: Option<Instant>,
    b: Option<Instant>,
    c: Option<Instant>,
) -> Instant {
    let fallback = Instant::now() + MAX_SLEEP;
    [a, b, c].into_iter().flatten().min().unwrap_or(fallback)
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

fn socket_path() -> PathBuf {
    if let Ok(path) = std::env::var("MIDIMAN_SOCKET") {
        PathBuf::from(path)
    } else {
        std::env::temp_dir().join("midiman.sock")
    }
}

fn try_connect_midi() -> Option<Box<dyn OutputSink>> {
    match midiman::output::midi::MidiSink::connect_first("midiman") {
        Ok(sink) => {
            eprintln!("  midi: connected to '{}'", sink.name());
            Some(Box::new(sink))
        }
        Err(e) => {
            eprintln!("  midi: {e} (running without MIDI)");
            None
        }
    }
}

fn try_connect_osc() -> Option<Box<dyn OutputSink>> {
    let addr = std::env::var("MIDIMAN_OSC_TARGET").unwrap_or_else(|_| "127.0.0.1:57120".into());
    match midiman::output::osc::OscSink::new(&addr) {
        Ok(sink) => {
            eprintln!("  osc: targeting {addr}");
            Some(Box::new(sink))
        }
        Err(e) => {
            eprintln!("  osc: {e} (running without OSC)");
            None
        }
    }
}
