//! Unix socket IPC server for frontend communication.
//!
//! Accepts newline-delimited JSON messages defined in [`protocol`].
//! Each connection is handled sequentially on the IPC thread.
//! Pattern compilation and slot insertion happen inline on message receipt.

pub mod protocol;

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use crate::ir;
use crate::pattern::CompiledPattern;
use crate::scheduler::clock::SharedBpm;
use crate::scheduler::hotswap::SwapSlot;
use crate::scheduler::Slots;

use protocol::{ClientMessage, ServerMessage};

/// Handle to a running IPC server.
pub struct IpcHandle {
    socket_path: PathBuf,
    stop: Arc<AtomicBool>,
    thread: Option<thread::JoinHandle<()>>,
}

impl IpcHandle {
    /// Returns the path to the Unix domain socket.
    pub fn socket_path(&self) -> &Path {
        &self.socket_path
    }

    /// Signal the IPC server to stop, join the thread, and remove the socket file.
    pub fn stop(mut self) {
        self.shutdown();
    }

    fn shutdown(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        // Connect to unblock the listener's accept()
        let _ = UnixStream::connect(&self.socket_path);
        if let Some(handle) = self.thread.take() {
            let _ = handle.join();
        }
        let _ = std::fs::remove_file(&self.socket_path);
    }
}

impl Drop for IpcHandle {
    fn drop(&mut self) {
        self.shutdown();
    }
}

/// Start the IPC server on a Unix domain socket.
/// Accepts one connection at a time, processing newline-delimited JSON messages.
pub fn start(socket_path: PathBuf, slots: Slots, shared_bpm: SharedBpm) -> std::io::Result<IpcHandle> {
    let _ = std::fs::remove_file(&socket_path);

    let listener = UnixListener::bind(&socket_path)?;
    // Set a short timeout so accept() periodically wakes to check stop flag
    listener.set_nonblocking(false)?;

    let stop = Arc::new(AtomicBool::new(false));
    let stop_clone = Arc::clone(&stop);
    let path = socket_path.clone();

    let thread = thread::Builder::new()
        .name("midiman-ipc".into())
        .spawn(move || {
            run_server(listener, slots, stop_clone, shared_bpm);
        })
        .expect("failed to spawn IPC thread");

    Ok(IpcHandle {
        socket_path: path,
        stop,
        thread: Some(thread),
    })
}

fn run_server(listener: UnixListener, slots: Slots, stop: Arc<AtomicBool>, shared_bpm: SharedBpm) {
    // Use a short accept timeout so we can check the stop flag
    listener
        .set_nonblocking(false)
        .expect("set listener blocking");

    for stream in listener.incoming() {
        if stop.load(Ordering::Relaxed) {
            break;
        }
        match stream {
            Ok(stream) => {
                stream
                    .set_read_timeout(Some(Duration::from_millis(100)))
                    .ok();
                handle_connection(stream, &slots, &stop, &shared_bpm);
            }
            Err(_) => break,
        }
    }
}

fn handle_connection(stream: UnixStream, slots: &Slots, stop: &AtomicBool, shared_bpm: &SharedBpm) {
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

        let response = match serde_json::from_str::<ClientMessage>(&line) {
            Ok(msg) => process_message(msg, slots, shared_bpm),
            Err(e) => ServerMessage::Error {
                msg: format!("parse error: {e}"),
            },
        };

        let mut json = serde_json::to_string(&response).expect("serialize response");
        json.push('\n');
        if writer.write_all(json.as_bytes()).is_err() {
            break;
        }
    }
}

/// A pre-validated action ready to apply under the slots lock.
enum BatchAction {
    SetPattern { slot: String, compiled: CompiledPattern },
    Hush { slot: String },
    HushAll,
    SetBpm { bpm: f64 },
    Ping,
}

/// Validate and compile a single command into a `BatchAction`.
/// Returns `Err` for compile errors or nested batches.
fn prepare_command(msg: &ClientMessage) -> Result<BatchAction, String> {
    match msg {
        ClientMessage::SetPattern { slot, pattern } => {
            let compiled = ir::compile(pattern).map_err(|e| format!("compile error: {e}"))?;
            Ok(BatchAction::SetPattern { slot: slot.clone(), compiled })
        }
        ClientMessage::Hush { slot } => Ok(BatchAction::Hush { slot: slot.clone() }),
        ClientMessage::HushAll => Ok(BatchAction::HushAll),
        ClientMessage::SetBpm { bpm } => Ok(BatchAction::SetBpm { bpm: *bpm }),
        ClientMessage::Ping => Ok(BatchAction::Ping),
        ClientMessage::Batch { .. } => Err("nested Batch is not allowed".into()),
    }
}

/// Apply a prepared action. Caller holds the slots lock.
fn apply_action(
    action: BatchAction,
    slots: &mut std::collections::HashMap<String, Arc<SwapSlot>>,
    shared_bpm: &SharedBpm,
) {
    match action {
        BatchAction::SetPattern { slot, compiled } => {
            if let Some(existing) = slots.get(&slot) {
                existing.swap(compiled);
            } else {
                slots.insert(slot, Arc::new(SwapSlot::new(compiled)));
            }
        }
        BatchAction::Hush { slot } => {
            if let Some(existing) = slots.get(&slot) {
                existing.swap(CompiledPattern::silence());
            } else {
                slots.insert(slot, Arc::new(SwapSlot::new(CompiledPattern::silence())));
            }
        }
        BatchAction::HushAll => {
            for s in slots.values() {
                s.swap(CompiledPattern::silence());
            }
        }
        BatchAction::SetBpm { bpm } => {
            shared_bpm.set(bpm);
        }
        BatchAction::Ping => {}
    }
}

fn process_message(msg: ClientMessage, slots: &Slots, shared_bpm: &SharedBpm) -> ServerMessage {
    match msg {
        ClientMessage::Batch { commands } => {
            // Phase 1: validate and compile all commands (no lock held)
            let mut actions = Vec::with_capacity(commands.len());
            for cmd in &commands {
                match prepare_command(cmd) {
                    Ok(action) => actions.push(action),
                    Err(e) => return ServerMessage::Error { msg: e },
                }
            }

            // Phase 2: apply all under one lock — atomic from scheduler's perspective
            let mut guard = slots.lock().expect("slots lock");
            for action in actions {
                apply_action(action, &mut guard, shared_bpm);
            }

            ServerMessage::Ok {
                msg: format!("batch applied ({} commands)", commands.len()),
            }
        }

        // Single commands go through the same prepare → apply path
        other => match prepare_command(&other) {
            Ok(action) => {
                if matches!(action, BatchAction::Ping) {
                    return ServerMessage::Pong;
                }
                let mut guard = slots.lock().expect("slots lock");
                let msg = describe_action(&action);
                apply_action(action, &mut guard, shared_bpm);
                ServerMessage::Ok { msg }
            }
            Err(e) => ServerMessage::Error { msg: e },
        },
    }
}

fn describe_action(action: &BatchAction) -> String {
    match action {
        BatchAction::SetPattern { slot, .. } => format!("pattern set on {slot}"),
        BatchAction::Hush { slot } => format!("{slot} hushed"),
        BatchAction::HushAll => "all slots hushed".into(),
        BatchAction::SetBpm { bpm } => format!("bpm set to {bpm}"),
        BatchAction::Ping => "pong".into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixStream;
    use std::sync::Mutex;

    use crate::scheduler::clock::SharedBpm;

    fn test_slots() -> Slots {
        Arc::new(Mutex::new(HashMap::new()))
    }

    fn test_bpm() -> SharedBpm {
        SharedBpm::new(120.0)
    }

    fn temp_socket_path(suffix: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "midiman-test-{}-{suffix}.sock",
            std::process::id()
        ))
    }

    fn send_recv(
        writer: &mut UnixStream,
        reader: &mut BufReader<UnixStream>,
        msg: &str,
    ) -> ServerMessage {
        writeln!(writer, "{msg}").unwrap();
        let mut resp = String::new();
        reader.read_line(&mut resp).unwrap();
        serde_json::from_str(&resp).unwrap()
    }

    #[test]
    fn ipc_ping_pong() {
        let path = temp_socket_path("ping");
        let handle = start(path.clone(), test_slots(), test_bpm()).unwrap();

        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        let resp = send_recv(&mut writer, &mut reader, r#"{"cmd":"Ping"}"#);
        assert!(matches!(resp, ServerMessage::Pong));

        drop(writer);
        handle.stop();
    }

    #[test]
    fn ipc_set_pattern_creates_slot() {
        let path = temp_socket_path("setpat");
        let slots = test_slots();
        let slots_ref = Arc::clone(&slots);
        let handle = start(path.clone(), slots, test_bpm()).unwrap();

        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        let msg = r#"{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}}}"#;
        let resp = send_recv(&mut writer, &mut reader, msg);
        assert!(matches!(resp, ServerMessage::Ok { .. }));

        let guard = slots_ref.lock().unwrap();
        assert!(guard.contains_key("d1"));

        drop(writer);
        handle.stop();
    }

    #[test]
    fn ipc_hush_silences_slot() {
        let path = temp_socket_path("hush");
        let handle = start(path.clone(), test_slots(), test_bpm()).unwrap();

        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        send_recv(
            &mut writer,
            &mut reader,
            r#"{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}}}"#,
        );

        let resp = send_recv(&mut writer, &mut reader, r#"{"cmd":"Hush","slot":"d1"}"#);
        assert!(matches!(resp, ServerMessage::Ok { .. }));

        drop(writer);
        handle.stop();
    }

    #[test]
    fn ipc_batch_applies_all_commands() {
        let path = temp_socket_path("batch");
        let slots = test_slots();
        let slots_ref = Arc::clone(&slots);
        let handle = start(path.clone(), slots, test_bpm()).unwrap();

        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        let msg = r#"{"cmd":"Batch","commands":[{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}}},{"cmd":"SetPattern","slot":"d2","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":72,"velocity":100,"dur":0.5}}},{"cmd":"SetBpm","bpm":140.0}]}"#;
        let resp = send_recv(&mut writer, &mut reader, msg);
        assert!(matches!(resp, ServerMessage::Ok { .. }));

        // Both slots should exist — applied atomically
        let guard = slots_ref.lock().unwrap();
        assert!(guard.contains_key("d1"), "d1 should exist after batch");
        assert!(guard.contains_key("d2"), "d2 should exist after batch");

        drop(writer);
        handle.stop();
    }

    #[test]
    fn ipc_batch_rolls_back_on_failure() {
        let path = temp_socket_path("batch-fail");
        let slots = test_slots();
        let slots_ref = Arc::clone(&slots);
        let handle = start(path.clone(), slots, test_bpm()).unwrap();

        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        // First command valid, second has zero denominator — entire batch should fail
        let msg = r#"{"cmd":"Batch","commands":[{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}}},{"cmd":"SetPattern","slot":"d2","pattern":{"op":"Fast","factor":[1,0],"child":{"op":"Atom","value":{"type":"Note","channel":0,"note":72,"velocity":100,"dur":0.5}}}}]}"#;
        let resp = send_recv(&mut writer, &mut reader, msg);
        assert!(matches!(resp, ServerMessage::Error { .. }));

        // Neither slot should exist — all-or-nothing
        let guard = slots_ref.lock().unwrap();
        assert!(!guard.contains_key("d1"), "d1 should not exist after failed batch");
        assert!(!guard.contains_key("d2"), "d2 should not exist after failed batch");

        drop(writer);
        handle.stop();
    }

    #[test]
    fn ipc_batch_rejects_nested_batch() {
        let path = temp_socket_path("batch-nest");
        let handle = start(path.clone(), test_slots(), test_bpm()).unwrap();

        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        let msg = r#"{"cmd":"Batch","commands":[{"cmd":"Batch","commands":[{"cmd":"Ping"}]}]}"#;
        let resp = send_recv(&mut writer, &mut reader, msg);
        match resp {
            ServerMessage::Error { msg } => {
                assert!(msg.contains("nested"), "error should mention nesting: {msg}");
            }
            other => panic!("expected Error for nested batch, got {other:?}"),
        }

        drop(writer);
        handle.stop();
    }

    #[test]
    fn ipc_batch_empty_succeeds() {
        let path = temp_socket_path("batch-empty");
        let handle = start(path.clone(), test_slots(), test_bpm()).unwrap();

        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        let resp = send_recv(&mut writer, &mut reader, r#"{"cmd":"Batch","commands":[]}"#);
        assert!(matches!(resp, ServerMessage::Ok { .. }));

        drop(writer);
        handle.stop();
    }

    #[test]
    fn ipc_invalid_json_returns_error() {
        let path = temp_socket_path("invalid");
        let handle = start(path.clone(), test_slots(), test_bpm()).unwrap();

        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        let resp = send_recv(&mut writer, &mut reader, "not valid json");
        assert!(matches!(resp, ServerMessage::Error { .. }));

        drop(writer);
        handle.stop();
    }
}
