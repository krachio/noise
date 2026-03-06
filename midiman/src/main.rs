use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};

use midiman::event::Value;
use midiman::output::{self, OutputSink};
use midiman::scheduler::{self, SchedulerConfig};

/// A pending note-off event to be fired at a specific wall-clock time.
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

    let config = SchedulerConfig::default();
    eprintln!("  bpm: {}", config.bpm);
    eprintln!("  lookahead: {}ms", config.lookahead_secs * 1000.0);

    let beats_per_cycle = config.beats_per_cycle;
    let (event_tx, event_rx) = crossbeam_channel::unbounded();

    // Start scheduler with no initial slots (IPC will add them)
    let (sched_handle, slots, shared_bpm) = scheduler::start(config, HashMap::new(), event_tx);

    // Start IPC server
    let ipc_handle = midiman::ipc::start(socket_path, Arc::clone(&slots), shared_bpm.clone())
        .expect("failed to start IPC server");

    eprintln!("midiman ready. listening on {}", ipc_handle.socket_path().display());

    // Output dispatch loop on main thread
    let mut midi_sink = try_connect_midi();
    let mut osc_sink = try_connect_osc();

    // Handle SIGINT gracefully
    let running = Arc::new(std::sync::atomic::AtomicBool::new(true));
    let running_clone = Arc::clone(&running);
    ctrlc_handler(running_clone);

    let mut note_offs: BinaryHeap<Reverse<PendingNoteOff>> = BinaryHeap::new();

    // MIDI clock sync (24 ppqn), opt-in via env var
    let midi_clock_enabled = std::env::var("MIDIMAN_MIDI_CLOCK").is_ok_and(|v| v == "1");
    let mut next_clock_tick: Option<Instant> = None;
    if midi_clock_enabled {
        if let Some(sink) = midi_sink.as_mut() {
            let _ = sink.send_clock_start();
        }
        next_clock_tick = Some(Instant::now());
        eprintln!("  midi clock: enabled (24 ppqn)");
    }

    while running.load(std::sync::atomic::Ordering::Relaxed) {
        // Drain due note-offs
        drain_note_offs(&mut note_offs, &mut midi_sink);

        // Send due MIDI clock ticks
        if let Some(ref mut next_tick) = next_clock_tick {
            let now = Instant::now();
            while *next_tick <= now {
                if let Some(sink) = midi_sink.as_mut() {
                    let _ = sink.send_clock_tick();
                }
                let bpm = shared_bpm.get();
                let tick_interval = Duration::from_secs_f64(60.0 / (bpm * 24.0));
                *next_tick += tick_interval;
            }
        }

        // Compute recv timeout: min of 100ms, time to next note-off, time to next clock tick
        let mut timeout = next_timeout(&note_offs, Duration::from_millis(100));
        if let Some(next_tick) = next_clock_tick {
            let now = Instant::now();
            if next_tick > now {
                timeout = timeout.min(next_tick - now);
            } else {
                timeout = Duration::ZERO;
            }
        }

        match event_rx.recv_timeout(timeout) {
            Ok(timed_event) => {
                // Wait until fire time
                let now = Instant::now();
                if timed_event.fire_at > now {
                    spin_sleep::sleep(timed_event.fire_at - now);
                }

                // Schedule note-off if this is a Note event
                if let Value::Note { channel, note, dur, .. } = &timed_event.event.value {
                    let cycle_dur_secs = beats_per_cycle * 60.0 / shared_bpm.get();
                    let note_off_at = timed_event.fire_at
                        + Duration::from_secs_f64(dur * cycle_dur_secs);
                    note_offs.push(Reverse(PendingNoteOff {
                        fire_at: note_off_at,
                        channel: *channel,
                        note: *note,
                    }));
                }

                let _ = output::dispatch(
                    &timed_event,
                    &mut midi_sink,
                    &mut osc_sink,
                );
            }
            Err(crossbeam_channel::RecvTimeoutError::Timeout) => {}
            Err(crossbeam_channel::RecvTimeoutError::Disconnected) => break,
        }
    }

    // Send all remaining note-offs before shutdown
    drain_all_note_offs(&mut note_offs, &mut midi_sink);

    // Send MIDI clock stop
    if midi_clock_enabled {
        if let Some(sink) = midi_sink.as_mut() {
            let _ = sink.send_clock_stop();
        }
    }

    eprintln!("\nmidiman shutting down...");
    ipc_handle.stop();
    sched_handle.stop();
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

fn drain_all_note_offs(
    heap: &mut BinaryHeap<Reverse<PendingNoteOff>>,
    midi_sink: &mut Option<Box<dyn OutputSink>>,
) {
    while let Some(Reverse(pending)) = heap.pop() {
        if let Some(sink) = midi_sink.as_mut() {
            let _ = sink.send_note_off(pending.channel, pending.note);
        }
    }
}

fn next_timeout(
    heap: &BinaryHeap<Reverse<PendingNoteOff>>,
    default: Duration,
) -> Duration {
    if let Some(Reverse(pending)) = heap.peek() {
        let now = Instant::now();
        if pending.fire_at <= now {
            return Duration::ZERO;
        }
        (pending.fire_at - now).min(default)
    } else {
        default
    }
}

fn socket_path() -> PathBuf {
    if let Ok(path) = std::env::var("MIDIMAN_SOCKET") {
        PathBuf::from(path)
    } else {
        let dir = std::env::temp_dir();
        dir.join("midiman.sock")
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

fn ctrlc_handler(running: Arc<std::sync::atomic::AtomicBool>) {
    // Best-effort signal handling — not critical for correctness
    std::thread::spawn(move || {
        // Simple approach: read from a signal-catching mechanism
        // For now, rely on the default SIGINT behavior (process exit)
        // TODO: proper signal handling with signal-hook crate
        let _ = running;
    });
}
