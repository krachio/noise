use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};

use midiman::output::{self, OutputSink};
use midiman::scheduler::{self, SchedulerConfig};

fn main() {
    let socket_path = socket_path();
    eprintln!("midiman starting...");
    eprintln!("  socket: {}", socket_path.display());

    let config = SchedulerConfig::default();
    eprintln!("  bpm: {}", config.bpm);
    eprintln!("  lookahead: {}ms", config.lookahead_secs * 1000.0);

    let (event_tx, event_rx) = crossbeam_channel::unbounded();

    // Start scheduler with no initial slots (IPC will add them)
    let (sched_handle, slots, shared_bpm) = scheduler::start(config, HashMap::new(), event_tx);

    // Start IPC server
    let ipc_handle = midiman::ipc::start(socket_path, Arc::clone(&slots), shared_bpm)
        .expect("failed to start IPC server");

    eprintln!("midiman ready. listening on {}", ipc_handle.socket_path().display());

    // Output dispatch loop on main thread
    let mut midi_sink = try_connect_midi();
    let mut osc_sink = try_connect_osc();

    // Handle SIGINT gracefully
    let running = Arc::new(std::sync::atomic::AtomicBool::new(true));
    let running_clone = Arc::clone(&running);
    ctrlc_handler(running_clone);

    while running.load(std::sync::atomic::Ordering::Relaxed) {
        match event_rx.recv_timeout(Duration::from_millis(100)) {
            Ok(timed_event) => {
                // Wait until fire time
                let now = Instant::now();
                if timed_event.fire_at > now {
                    spin_sleep::sleep(timed_event.fire_at - now);
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

    eprintln!("\nmidiman shutting down...");
    ipc_handle.stop();
    sched_handle.stop();
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
