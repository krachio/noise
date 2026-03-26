//! Unix socket IPC server for frontend communication.
//!
//! Accepts newline-delimited JSON messages defined in [`protocol`].
//! Each connection is handled sequentially on the IPC thread.
//!
//! Pattern compilation happens here (CPU work, no lock needed). The compiled
//! [`EngineCommand`]s are sent over a channel to the engine loop, which owns
//! the pattern state and event heap exclusively.

pub mod protocol;

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::Duration;

use crossbeam_channel::Sender;

use crate::engine::EngineCommand;
use crate::ir;

use protocol::{ClientMessage, ServerMessage};

/// Handle to a running IPC server.
pub struct IpcHandle {
    socket_path: PathBuf,
    stop: Arc<AtomicBool>,
    thread: Option<thread::JoinHandle<()>>,
}

impl IpcHandle {
    /// Returns the path to the Unix domain socket.
    #[must_use]
    pub fn socket_path(&self) -> &Path {
        &self.socket_path
    }

    /// Signal the IPC server to stop, join the thread, and remove the socket file.
    pub fn stop(mut self) {
        self.shutdown();
    }

    fn shutdown(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
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
///
/// # Errors
/// Returns an error if the socket cannot be bound.
///
/// # Panics
/// Panics if the IPC thread cannot be spawned.
#[allow(clippy::needless_pass_by_value)] // PathBuf cloned into IpcHandle; cmd_tx moved into thread
pub fn start(socket_path: PathBuf, cmd_tx: Sender<EngineCommand>) -> std::io::Result<IpcHandle> {
    let _ = std::fs::remove_file(&socket_path);
    let listener = UnixListener::bind(&socket_path)?;
    listener.set_nonblocking(false)?;

    let stop = Arc::new(AtomicBool::new(false));
    let stop_clone = Arc::clone(&stop);
    let path = socket_path.clone();

    let thread = thread::Builder::new()
        .name("pattern-engine-ipc".into())
        .spawn(move || run_server(listener, cmd_tx, stop_clone))
        .expect("failed to spawn IPC thread");

    Ok(IpcHandle {
        socket_path: path,
        stop,
        thread: Some(thread),
    })
}

#[allow(clippy::needless_pass_by_value)] // all three are owned by the spawned thread
fn run_server(listener: UnixListener, cmd_tx: Sender<EngineCommand>, stop: Arc<AtomicBool>) {
    for stream in listener.incoming() {
        if stop.load(Ordering::Relaxed) {
            break;
        }
        match stream {
            Ok(stream) => {
                stream
                    .set_read_timeout(Some(Duration::from_millis(100)))
                    .ok();
                handle_connection(stream, &cmd_tx, &stop);
            }
            Err(_) => break,
        }
    }
}

fn handle_connection(stream: UnixStream, cmd_tx: &Sender<EngineCommand>, stop: &AtomicBool) {
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
            Ok(msg) => process_message(msg, cmd_tx),
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

fn process_message(msg: ClientMessage, cmd_tx: &Sender<EngineCommand>) -> ServerMessage {
    match msg {
        ClientMessage::Ping => ServerMessage::Pong,

        ClientMessage::Batch { commands } => {
            // Phase 1: compile all commands (no lock, may fail).
            let mut compiled = Vec::with_capacity(commands.len());
            for cmd in &commands {
                match compile_command(cmd) {
                    Ok(Some(engine_cmd)) => compiled.push(engine_cmd),
                    Ok(None) => {} // Ping in a batch — skip
                    Err(e) => return ServerMessage::Error { msg: e },
                }
            }
            // Phase 2: all compiled — send atomically (sequential channel sends
            // are consumed in order before the engine fills the heap).
            let n = compiled.len();
            for engine_cmd in compiled {
                let _ = cmd_tx.send(engine_cmd);
            }
            ServerMessage::Ok {
                msg: format!("batch applied ({n} commands)"),
            }
        }

        other => match compile_command(&other) {
            Ok(Some(engine_cmd)) => {
                let description = describe(&engine_cmd);
                let _ = cmd_tx.send(engine_cmd);
                ServerMessage::Ok { msg: description }
            }
            Ok(None) => ServerMessage::Pong, // unreachable: Ping handled above
            Err(e) => ServerMessage::Error { msg: e },
        },
    }
}

/// Compile one [`ClientMessage`] into an [`EngineCommand`].
/// Returns `Ok(None)` for `Ping` (no engine action needed).
/// Returns `Err` if the pattern IR fails to compile or nesting is detected.
pub fn compile_command(msg: &ClientMessage) -> Result<Option<EngineCommand>, String> {
    match msg {
        ClientMessage::SetPattern { slot, pattern } => {
            let compiled = ir::compile(pattern).map_err(|e| format!("compile error: {e}"))?;
            Ok(Some(EngineCommand::SetPattern {
                name: slot.clone(),
                pattern: compiled,
            }))
        }
        ClientMessage::SetPatternFromZero { slot, pattern } => {
            let compiled = ir::compile(pattern).map_err(|e| format!("compile error: {e}"))?;
            Ok(Some(EngineCommand::SetPatternFromZero {
                name: slot.clone(),
                pattern: compiled,
            }))
        }
        ClientMessage::Hush { slot } => Ok(Some(EngineCommand::Hush { name: slot.clone() })),
        ClientMessage::HushAll => Ok(Some(EngineCommand::HushAll)),
        ClientMessage::SetBpm { bpm } => Ok(Some(EngineCommand::SetBpm { bpm: *bpm })),
        ClientMessage::SetBeatsPerCycle { beats } => {
            Ok(Some(EngineCommand::SetBeatsPerCycle { beats: *beats }))
        }
        ClientMessage::SetClockSource { source } => {
            let cs = match source.as_str() {
                "internal" => crate::scheduler::clock::ClockSource::Internal,
                "external" | "midi" => crate::scheduler::clock::ClockSource::External,
                other => return Err(format!("unknown clock source: {other:?} (expected \"internal\" or \"midi\")")),
            };
            Ok(Some(EngineCommand::SetClockSource(cs)))
        }
        ClientMessage::Ping => Ok(None),
        ClientMessage::Batch { .. } => Err("nested Batch is not allowed".into()),
    }
}

/// Human-readable description of an engine command (for IPC responses).
#[must_use] pub fn describe(cmd: &EngineCommand) -> String {
    match cmd {
        EngineCommand::SetPattern { name, .. } => format!("pattern set on {name}"),
        EngineCommand::SetPatternFromZero { name, .. } => {
            format!("pattern set on {name} (from zero)")
        }
        EngineCommand::Hush { name } => format!("{name} hushed"),
        EngineCommand::HushAll => "all slots hushed".into(),
        EngineCommand::SetBpm { bpm } => format!("bpm set to {bpm}"),
        EngineCommand::SetBeatsPerCycle { beats } => format!("beats per cycle set to {beats}"),
        EngineCommand::SetClockSource(source) => format!("clock source set to {source:?}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixStream;

    fn temp_socket_path(suffix: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "pattern-engine-test-{}-{suffix}.sock",
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

    fn make_server(
        suffix: &str,
    ) -> (
        PathBuf,
        Sender<EngineCommand>,
        crossbeam_channel::Receiver<EngineCommand>,
        IpcHandle,
    ) {
        let path = temp_socket_path(suffix);
        let (tx, rx) = crossbeam_channel::unbounded();
        let handle = start(path.clone(), tx.clone()).unwrap();
        (path, tx, rx, handle)
    }

    #[test]
    fn ipc_ping_pong() {
        let (path, _tx, _rx, handle) = make_server("ping");
        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);
        let resp = send_recv(&mut writer, &mut reader, r#"{"cmd":"Ping"}"#);
        assert!(matches!(resp, ServerMessage::Pong));
        drop(writer);
        handle.stop();
    }

    #[test]
    fn ipc_set_pattern_sends_engine_command() {
        let (path, _tx, rx, handle) = make_server("setpat");
        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        let msg = r#"{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}}}"#;
        let resp = send_recv(&mut writer, &mut reader, msg);
        assert!(matches!(resp, ServerMessage::Ok { .. }));

        let cmd = rx
            .recv_timeout(Duration::from_millis(100))
            .expect("engine command sent");
        assert!(matches!(cmd, EngineCommand::SetPattern { name, .. } if name == "d1"));

        drop(writer);
        handle.stop();
    }

    #[test]
    fn ipc_hush_sends_engine_command() {
        let (path, _tx, rx, handle) = make_server("hush");
        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        let resp = send_recv(&mut writer, &mut reader, r#"{"cmd":"Hush","slot":"d1"}"#);
        assert!(matches!(resp, ServerMessage::Ok { .. }));

        let cmd = rx
            .recv_timeout(Duration::from_millis(100))
            .expect("engine command sent");
        assert!(matches!(cmd, EngineCommand::Hush { name } if name == "d1"));

        drop(writer);
        handle.stop();
    }

    #[test]
    fn ipc_batch_sends_all_commands() {
        let (path, _tx, rx, handle) = make_server("batch");
        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        let msg = r#"{"cmd":"Batch","commands":[{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}}},{"cmd":"SetPattern","slot":"d2","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":72,"velocity":100,"dur":0.5}}},{"cmd":"SetBpm","bpm":140.0}]}"#;
        let resp = send_recv(&mut writer, &mut reader, msg);
        assert!(matches!(resp, ServerMessage::Ok { .. }));

        let cmd1 = rx.recv_timeout(Duration::from_millis(100)).unwrap();
        let cmd2 = rx.recv_timeout(Duration::from_millis(100)).unwrap();
        let cmd3 = rx.recv_timeout(Duration::from_millis(100)).unwrap();

        assert!(matches!(cmd1, EngineCommand::SetPattern { name, .. } if name == "d1"));
        assert!(matches!(cmd2, EngineCommand::SetPattern { name, .. } if name == "d2"));
        assert!(
            matches!(cmd3, EngineCommand::SetBpm { bpm } if (bpm - 140.0).abs() < f64::EPSILON)
        );

        drop(writer);
        handle.stop();
    }

    #[test]
    fn ipc_batch_sends_nothing_on_compile_failure() {
        let (path, _tx, rx, handle) = make_server("batch-fail");
        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        // Second command has zero denominator — batch should fail, send nothing.
        let msg = r#"{"cmd":"Batch","commands":[{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}}},{"cmd":"SetPattern","slot":"d2","pattern":{"op":"Fast","factor":[1,0],"child":{"op":"Atom","value":{"type":"Note","channel":0,"note":72,"velocity":100,"dur":0.5}}}}]}"#;
        let resp = send_recv(&mut writer, &mut reader, msg);
        assert!(matches!(resp, ServerMessage::Error { .. }));

        // No commands should have been sent.
        assert!(
            rx.try_recv().is_err(),
            "no commands should be sent on batch failure"
        );

        drop(writer);
        handle.stop();
    }

    #[test]
    fn ipc_batch_rejects_nested_batch() {
        let (path, _tx, _rx, handle) = make_server("batch-nest");
        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        let msg = r#"{"cmd":"Batch","commands":[{"cmd":"Batch","commands":[{"cmd":"Ping"}]}]}"#;
        let resp = send_recv(&mut writer, &mut reader, msg);
        assert!(matches!(resp, ServerMessage::Error { msg } if msg.contains("nested")));

        drop(writer);
        handle.stop();
    }

    #[test]
    fn ipc_batch_empty_succeeds() {
        let (path, _tx, _rx, handle) = make_server("batch-empty");
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
        let (path, _tx, _rx, handle) = make_server("invalid");
        let stream = UnixStream::connect(&path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        let resp = send_recv(&mut writer, &mut reader, "not valid json");
        assert!(matches!(resp, ServerMessage::Error { .. }));

        drop(writer);
        handle.stop();
    }
}
