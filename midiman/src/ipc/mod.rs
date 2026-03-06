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

fn process_message(msg: ClientMessage, slots: &Slots, shared_bpm: &SharedBpm) -> ServerMessage {
    match msg {
        ClientMessage::SetPattern { slot, pattern } => match ir::compile(&pattern) {
            Ok(compiled) => {
                let mut guard = slots.lock().expect("slots lock");
                if let Some(existing) = guard.get(&slot) {
                    existing.swap(compiled);
                } else {
                    guard.insert(slot.clone(), Arc::new(SwapSlot::new(compiled)));
                }
                ServerMessage::Ok {
                    msg: format!("pattern set on {slot}"),
                }
            }
            Err(e) => ServerMessage::Error {
                msg: format!("compile error: {e}"),
            },
        },
        ClientMessage::Hush { slot } => {
            let mut guard = slots.lock().expect("slots lock");
            if let Some(existing) = guard.get(&slot) {
                existing.swap(CompiledPattern::silence());
            } else {
                guard.insert(
                    slot.clone(),
                    Arc::new(SwapSlot::new(CompiledPattern::silence())),
                );
            }
            ServerMessage::Ok {
                msg: format!("{slot} hushed"),
            }
        }
        ClientMessage::HushAll => {
            let guard = slots.lock().expect("slots lock");
            for slot in guard.values() {
                slot.swap(CompiledPattern::silence());
            }
            ServerMessage::Ok {
                msg: "all slots hushed".into(),
            }
        }
        ClientMessage::SetBpm { bpm } => {
            shared_bpm.set(bpm);
            ServerMessage::Ok {
                msg: format!("bpm set to {bpm}"),
            }
        }
        ClientMessage::Ping => ServerMessage::Pong,
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
