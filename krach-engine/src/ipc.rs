//! Unified IPC server — accepts both pattern-engine (pattern) and audio-engine (graph)
//! message formats on a single Unix socket.
//!
//! Pattern messages use `"cmd"` tag: SetPattern, Hush, HushAll, SetBpm, Batch, Ping.
//! Audio messages use `"type"` tag: load_graph, set_control, set_master_gain, list_nodes.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, RwLock};
use std::time::Duration;

use audio_engine::protocol::ClientMessage;
use log::warn;
use pattern_engine::ipc::protocol::ClientMessage as PatternMsg;
use pattern_engine::ipc::{compile_command, describe};

use crate::LoopCommand;

/// Unified IPC response type.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(tag = "status")]
pub enum IpcResponse {
    Ok { msg: String },
    Error { msg: String },
    Pong,
    NodeTypes { types: Vec<String> },
}

/// Handle to the IPC server thread.
pub struct IpcHandle {
    pub socket_path: PathBuf,
    stop: Arc<AtomicBool>,
    _thread: std::thread::JoinHandle<()>,
}

impl Drop for IpcHandle {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        let _ = std::os::unix::net::UnixStream::connect(&self.socket_path);
        let _ = std::fs::remove_file(&self.socket_path);
        let _ = std::fs::remove_file(self.socket_path.with_extension("pid"));
    }
}

/// Start the unified IPC server.
pub fn start(
    socket_path: PathBuf,
    cmd_tx: crossbeam_channel::Sender<LoopCommand>,
    node_types: Arc<RwLock<Vec<String>>>,
) -> Result<IpcHandle, String> {
    // Stale socket detection: check PID lock file.
    let lock_path = socket_path.with_extension("pid");
    if socket_path.exists() && lock_path.exists() {
        if let Ok(pid_str) = std::fs::read_to_string(&lock_path) {
            if let Ok(pid) = pid_str.trim().parse::<u32>() {
                // Check if /proc/{pid} exists (Linux) or try connecting (macOS).
                let proc_path = format!("/proc/{pid}");
                if std::path::Path::new(&proc_path).exists() {
                    return Err(format!(
                        "another krach-engine (PID {pid}) owns {}",
                        socket_path.display()
                    ));
                }
                // macOS: try connecting — if it succeeds, another instance is running.
                if std::os::unix::net::UnixStream::connect(&socket_path).is_ok() {
                    return Err(format!(
                        "another krach-engine (PID {pid}) owns {}",
                        socket_path.display()
                    ));
                }
            }
        }
    }
    let _ = std::fs::remove_file(&socket_path);
    std::fs::write(&lock_path, std::process::id().to_string())
        .map_err(|e| format!("write PID lock: {e}"))?;
    let listener = std::os::unix::net::UnixListener::bind(&socket_path)
        .map_err(|e| format!("bind {}: {e}", socket_path.display()))?;
    listener.set_nonblocking(false).map_err(|e| e.to_string())?;

    let stop = Arc::new(AtomicBool::new(false));
    let stop_clone = Arc::clone(&stop);
    let path = socket_path.clone();

    let thread = std::thread::Builder::new()
        .name("noise-ipc".into())
        .spawn(move || run_server(listener, cmd_tx, node_types, stop_clone))
        .expect("failed to spawn IPC thread");

    Ok(IpcHandle {
        socket_path: path,
        stop,
        _thread: thread,
    })
}

fn run_server(
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
                handle_connection(stream, &cmd_tx, &node_types, &stop);
            }
            Err(_) => break,
        }
    }
}

fn handle_connection(
    stream: std::os::unix::net::UnixStream,
    cmd_tx: &crossbeam_channel::Sender<LoopCommand>,
    node_types: &Arc<RwLock<Vec<String>>>,
    stop: &AtomicBool,
) {
    use std::io::{BufRead, BufReader, Write};

    let reader = BufReader::new(stream.try_clone().expect("clone stream"));
    let mut writer = stream;

    // Protocol version handshake: engine announces version on connect.
    let version_line = r#"{"protocol":1,"engine":"krach-engine"}"#;
    let _ = writer.write_all(format!("{version_line}\n").as_bytes());

    // Message size limit: 1MB per line.
    const MAX_LINE_BYTES: usize = 1_048_576;

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
        if line.len() > MAX_LINE_BYTES {
            let err = IpcResponse::Error {
                msg: format!(
                    "message too large ({} bytes, max {MAX_LINE_BYTES})",
                    line.len()
                ),
            };
            let mut json = serde_json::to_string(&err).expect("serialize");
            json.push('\n');
            let _ = writer.write_all(json.as_bytes());
            continue;
        }

        let response = dispatch(&line, cmd_tx, node_types);
        let mut json = serde_json::to_string(&response).expect("serialize response");
        json.push('\n');
        if writer.write_all(json.as_bytes()).is_err() {
            break;
        }
    }
}

/// Route a JSON line to the correct handler.
/// Tries pattern-engine protocol first ("cmd" tag), then audio-engine ("type" tag).
fn dispatch(
    line: &str,
    cmd_tx: &crossbeam_channel::Sender<LoopCommand>,
    node_types: &Arc<RwLock<Vec<String>>>,
) -> IpcResponse {
    if let Ok(msg) = serde_json::from_str::<PatternMsg>(line) {
        return handle_pattern(msg, cmd_tx);
    }
    if let Ok(msg) = serde_json::from_str::<ClientMessage>(line) {
        return handle_graph(msg, cmd_tx, node_types);
    }
    IpcResponse::Error {
        msg: format!("unrecognized message: {line}"),
    }
}

fn handle_pattern(msg: PatternMsg, cmd_tx: &crossbeam_channel::Sender<LoopCommand>) -> IpcResponse {
    match msg {
        PatternMsg::Ping => IpcResponse::Pong,
        PatternMsg::Batch { commands } => {
            let mut compiled = Vec::with_capacity(commands.len());
            for cmd in &commands {
                match compile_command(cmd) {
                    Ok(Some(engine_cmd)) => compiled.push(engine_cmd),
                    Ok(None) => {}
                    Err(e) => return IpcResponse::Error { msg: e },
                }
            }
            let n = compiled.len();
            for engine_cmd in compiled {
                if cmd_tx.send(LoopCommand::Pattern(engine_cmd)).is_err() {
                    warn!("main loop disconnected");
                }
            }
            IpcResponse::Ok {
                msg: format!("batch applied ({n} commands)"),
            }
        }
        other => match compile_command(&other) {
            Ok(Some(engine_cmd)) => {
                let description = describe(&engine_cmd);
                if cmd_tx.send(LoopCommand::Pattern(engine_cmd)).is_err() {
                    warn!("main loop disconnected");
                }
                IpcResponse::Ok { msg: description }
            }
            Ok(None) => IpcResponse::Pong,
            Err(e) => IpcResponse::Error { msg: e },
        },
    }
}

fn handle_graph(
    msg: ClientMessage,
    cmd_tx: &crossbeam_channel::Sender<LoopCommand>,
    node_types: &Arc<RwLock<Vec<String>>>,
) -> IpcResponse {
    match msg {
        ClientMessage::Ping => IpcResponse::Pong,
        ClientMessage::ListNodes { .. } => {
            let types = node_types.read().map_or_else(|_| vec![], |g| g.clone());
            IpcResponse::NodeTypes { types }
        }
        ClientMessage::StartInput { channel } => {
            if cmd_tx
                .send(LoopCommand::Graph(ClientMessage::StartInput { channel }))
                .is_err()
            {
                warn!("main loop disconnected");
            }
            IpcResponse::Ok {
                msg: format!("input started (ch {channel})"),
            }
        }
        ClientMessage::MidiMap {
            channel,
            cc,
            label,
            lo,
            hi,
        } => {
            if cmd_tx
                .send(LoopCommand::Graph(ClientMessage::MidiMap {
                    channel,
                    cc,
                    label: label.clone(),
                    lo,
                    hi,
                }))
                .is_err()
            {
                warn!("main loop disconnected");
            }
            IpcResponse::Ok {
                msg: format!("midi_map: ch{channel} cc{cc} → {label}"),
            }
        }
        ClientMessage::Shutdown => {
            if cmd_tx
                .send(LoopCommand::Graph(ClientMessage::Shutdown))
                .is_err()
            {
                warn!("main loop disconnected");
            }
            IpcResponse::Ok {
                msg: "shutting down".into(),
            }
        }
        other => {
            if cmd_tx.send(LoopCommand::Graph(other)).is_err() {
                warn!("main loop disconnected");
            }
            IpcResponse::Ok { msg: "ok".into() }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pattern_engine::engine::EngineCommand;

    #[test]
    fn ipc_response_ok_roundtrip() {
        let resp = IpcResponse::Ok { msg: "done".into() };
        let json = serde_json::to_string(&resp).unwrap();
        assert!(json.contains(r#""status":"Ok"#));
        let parsed: IpcResponse = serde_json::from_str(&json).unwrap();
        assert!(matches!(parsed, IpcResponse::Ok { msg } if msg == "done"));
    }

    #[test]
    fn ipc_response_error_roundtrip() {
        let resp = IpcResponse::Error { msg: "bad".into() };
        let json = serde_json::to_string(&resp).unwrap();
        let parsed: IpcResponse = serde_json::from_str(&json).unwrap();
        assert!(matches!(parsed, IpcResponse::Error { msg } if msg == "bad"));
    }

    #[test]
    fn ipc_response_pong_roundtrip() {
        let json = serde_json::to_string(&IpcResponse::Pong).unwrap();
        let parsed: IpcResponse = serde_json::from_str(&json).unwrap();
        assert!(matches!(parsed, IpcResponse::Pong));
    }

    #[test]
    fn ipc_response_node_types_roundtrip() {
        let resp = IpcResponse::NodeTypes {
            types: vec!["osc".into(), "dac".into()],
        };
        let json = serde_json::to_string(&resp).unwrap();
        let parsed: IpcResponse = serde_json::from_str(&json).unwrap();
        match parsed {
            IpcResponse::NodeTypes { types } => assert_eq!(types, vec!["osc", "dac"]),
            other => panic!("expected NodeTypes, got {other:?}"),
        }
    }

    #[test]
    fn dispatch_routes_pattern_engine_ping() {
        let (tx, _rx) = crossbeam_channel::unbounded();
        let types = Arc::new(RwLock::new(vec![]));
        let resp = dispatch(r#"{"cmd":"Ping"}"#, &tx, &types);
        assert!(matches!(resp, IpcResponse::Pong));
    }

    #[test]
    fn dispatch_routes_audio_engine_ping() {
        let (tx, _rx) = crossbeam_channel::unbounded();
        let types = Arc::new(RwLock::new(vec![]));
        let resp = dispatch(r#"{"type":"ping"}"#, &tx, &types);
        assert!(matches!(resp, IpcResponse::Pong));
    }

    #[test]
    fn dispatch_returns_error_for_garbage() {
        let (tx, _rx) = crossbeam_channel::unbounded();
        let types = Arc::new(RwLock::new(vec![]));
        let resp = dispatch("not json", &tx, &types);
        assert!(matches!(resp, IpcResponse::Error { .. }));
    }

    #[test]
    fn dispatch_list_nodes_returns_types() {
        let (tx, _rx) = crossbeam_channel::unbounded();
        let types = Arc::new(RwLock::new(vec!["osc".into(), "dac".into()]));
        let resp = dispatch(r#"{"type":"list_nodes","reply_port":0}"#, &tx, &types);
        match resp {
            IpcResponse::NodeTypes { types } => assert_eq!(types, vec!["osc", "dac"]),
            other => panic!("expected NodeTypes, got {other:?}"),
        }
    }

    #[test]
    fn dispatch_routes_set_pattern_to_channel() {
        let (tx, rx) = crossbeam_channel::unbounded();
        let types = Arc::new(RwLock::new(vec![]));
        let msg = r#"{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}}}"#;
        let resp = dispatch(msg, &tx, &types);
        assert!(matches!(resp, IpcResponse::Ok { .. }));
        let cmd = rx.try_recv().unwrap();
        assert!(
            matches!(cmd, LoopCommand::Pattern(EngineCommand::SetPattern { name, .. }) if name == "d1")
        );
    }

    #[test]
    fn dispatch_routes_load_graph_to_channel() {
        let (tx, rx) = crossbeam_channel::unbounded();
        let types = Arc::new(RwLock::new(vec![]));
        let msg = r#"{"type":"load_graph","nodes":[],"connections":[],"exposed_controls":{}}"#;
        let resp = dispatch(msg, &tx, &types);
        assert!(matches!(resp, IpcResponse::Ok { .. }));
        let cmd = rx.try_recv().unwrap();
        assert!(matches!(
            cmd,
            LoopCommand::Graph(ClientMessage::LoadGraph(_))
        ));
    }
}
