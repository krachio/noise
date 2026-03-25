//! Unified IPC server — accepts both pattern-engine (pattern) and audio-engine (graph)
//! message formats on a single Unix socket.
//!
//! Pattern messages use `"cmd"` tag: `SetPattern`, `Hush`, `HushAll`, `SetBpm`, `Batch`, `Ping`.
//! Audio messages use `"type"` tag: `load_graph`, `set_control`, `set_master_gain`, `list_nodes`.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, RwLock};
use std::time::Duration;

use audio_engine::engine::EngineSnapshot;
use audio_engine::ir::{ConnectionIr, NodeInstance};
use audio_engine::protocol::ClientMessage;
use log::warn;
use pattern_engine::ipc::protocol::ClientMessage as PatternMsg;
use pattern_engine::ipc::{compile_command, describe};

use crate::LoopCommand;

/// Timeout for waiting on main loop acknowledgment.
const ACK_TIMEOUT: Duration = Duration::from_secs(5);

/// Transport state snapshot.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct TransportInfo {
    pub bpm: f64,
    pub meter: f64,
}

/// Slot info from pattern engine.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct SlotInfo {
    pub name: String,
}

/// Unified IPC response type.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(tag = "status")]
pub enum IpcResponse {
    Ok { msg: String },
    Error { msg: String },
    Pong,
    NodeTypes { types: Vec<String> },
    State {
        nodes: Vec<NodeInstance>,
        connections: Vec<ConnectionIr>,
        exposed_controls: std::collections::HashMap<String, (String, String)>,
        control_values: std::collections::HashMap<String, f32>,
        slots: Vec<SlotInfo>,
        transport: TransportInfo,
    },
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
    if socket_path.exists() && lock_path.exists()
        && let Ok(pid_str) = std::fs::read_to_string(&lock_path)
        && let Ok(pid) = pid_str.trim().parse::<u32>()
    {
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
    let _ = std::fs::remove_file(&socket_path);
    std::fs::write(&lock_path, std::process::id().to_string())
        .map_err(|e| format!("write PID lock: {e}"))?;
    let listener = std::os::unix::net::UnixListener::bind(&socket_path)
        .map_err(|e| format!("bind {}: {e}", socket_path.display()))?;
    listener.set_nonblocking(false).map_err(|e| e.to_string())?;

    let stop = Arc::new(AtomicBool::new(false));
    let stop_clone = Arc::clone(&stop);

    let thread = std::thread::Builder::new()
        .name("noise-ipc".into())
        .spawn(move || run_server(&listener, &cmd_tx, &node_types, &stop_clone))
        .expect("failed to spawn IPC thread");

    Ok(IpcHandle {
        socket_path,
        stop,
        _thread: thread,
    })
}

fn run_server(
    listener: &std::os::unix::net::UnixListener,
    cmd_tx: &crossbeam_channel::Sender<LoopCommand>,
    node_types: &Arc<RwLock<Vec<String>>>,
    stop: &Arc<AtomicBool>,
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
                handle_connection(stream, cmd_tx, node_types, stop);
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

    // Message size limit: 1MB per line.
    const MAX_LINE_BYTES: usize = 1_048_576;

    let reader = BufReader::new(stream.try_clone().expect("clone stream"));
    let mut writer = stream;

    // Protocol version handshake: engine announces version on connect.
    let version_line = r#"{"protocol":1,"engine":"krach-engine"}"#;
    let _ = writer.write_all(format!("{version_line}\n").as_bytes());

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

/// Build an `IpcResponse::State` from an `EngineSnapshot` and slot/transport info.
pub fn build_state_response(
    snap: EngineSnapshot,
    slot_names: Vec<String>,
    bpm: f64,
    meter: f64,
) -> IpcResponse {
    IpcResponse::State {
        nodes: snap.nodes,
        connections: snap.connections,
        exposed_controls: snap.exposed_controls,
        control_values: snap.control_values,
        slots: slot_names.into_iter().map(|name| SlotInfo { name }).collect(),
        transport: TransportInfo { bpm, meter },
    }
}

/// Route a JSON line to the correct handler.
/// Tries Status first (unified command), then pattern-engine ("cmd" tag),
/// then audio-engine ("type" tag).
fn dispatch(
    line: &str,
    cmd_tx: &crossbeam_channel::Sender<LoopCommand>,
    node_types: &Arc<RwLock<Vec<String>>>,
) -> IpcResponse {
    // Status is a unified command that spans both engines.
    if let Ok(v) = serde_json::from_str::<serde_json::Value>(line)
        && v.get("cmd").and_then(|c| c.as_str()) == Some("Status")
    {
        return handle_status(cmd_tx);
    }
    if let Ok(ref msg) = serde_json::from_str::<PatternMsg>(line) {
        return handle_pattern(msg, cmd_tx);
    }
    if let Ok(msg) = serde_json::from_str::<ClientMessage>(line) {
        return handle_graph(msg, cmd_tx, node_types);
    }
    IpcResponse::Error {
        msg: format!("unrecognized message: {line}"),
    }
}

fn handle_status(cmd_tx: &crossbeam_channel::Sender<LoopCommand>) -> IpcResponse {
    let (ack_tx, ack_rx) = crossbeam_channel::bounded::<IpcResponse>(1);
    if cmd_tx.send(LoopCommand::Status(ack_tx)).is_err() {
        return IpcResponse::Error {
            msg: "main loop disconnected".into(),
        };
    }
    ack_rx.recv_timeout(ACK_TIMEOUT).unwrap_or_else(|_| IpcResponse::Error {
        msg: "main loop did not respond within 5s".into(),
    })
}

fn handle_pattern(msg: &PatternMsg, cmd_tx: &crossbeam_channel::Sender<LoopCommand>) -> IpcResponse {
    match msg {
        PatternMsg::Ping => IpcResponse::Pong,
        PatternMsg::Batch { commands } => {
            let mut compiled = Vec::with_capacity(commands.len());
            for cmd in commands {
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
        other => match compile_command(other) {
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
        other => send_and_wait(other, cmd_tx),
    }
}

/// Send a graph command to the main loop and wait for acknowledgment.
fn send_and_wait(
    msg: ClientMessage,
    cmd_tx: &crossbeam_channel::Sender<LoopCommand>,
) -> IpcResponse {
    let (ack_tx, ack_rx) = crossbeam_channel::bounded::<crate::AckResult>(1);
    if cmd_tx.send(LoopCommand::Graph(msg, ack_tx)).is_err() {
        return IpcResponse::Error {
            msg: "main loop disconnected".into(),
        };
    }
    match ack_rx.recv_timeout(ACK_TIMEOUT) {
        Ok(Ok(description)) => IpcResponse::Ok { msg: description },
        Ok(Err(error)) => IpcResponse::Error { msg: error },
        Err(_) => IpcResponse::Error {
            msg: "main loop did not respond within 5s".into(),
        },
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
    fn ipc_response_state_roundtrip() {
        use std::collections::HashMap;
        let resp = IpcResponse::State {
            nodes: vec![],
            connections: vec![],
            exposed_controls: HashMap::new(),
            control_values: HashMap::new(),
            slots: vec![SlotInfo { name: "kick".into() }],
            transport: TransportInfo { bpm: 120.0, meter: 4.0 },
        };
        let json = serde_json::to_string(&resp).unwrap();
        assert!(json.contains(r#""status":"State"#));
        let parsed: IpcResponse = serde_json::from_str(&json).unwrap();
        match parsed {
            IpcResponse::State { slots, transport, .. } => {
                assert_eq!(slots.len(), 1);
                assert_eq!(slots[0].name, "kick");
                assert!((transport.bpm - 120.0).abs() < f64::EPSILON);
                assert!((transport.meter - 4.0).abs() < f64::EPSILON);
            }
            other => panic!("expected State, got {other:?}"),
        }
    }

    #[test]
    fn dispatch_routes_status_to_channel() {
        let (tx, rx) = crossbeam_channel::unbounded();
        let types = Arc::new(RwLock::new(vec![]));
        // Spawn responder to handle the Status command.
        let responder = std::thread::spawn(move || {
            let cmd = rx.recv().unwrap();
            if let LoopCommand::Status(reply_tx) = cmd {
                let snap = audio_engine::engine::EngineSnapshot {
                    nodes: vec![],
                    connections: vec![],
                    exposed_controls: std::collections::HashMap::new(),
                    control_values: std::collections::HashMap::new(),
                };
                let _ = reply_tx.send(build_state_response(snap, vec!["kick".into()], 128.0, 4.0));
            } else {
                panic!("expected Status command");
            }
        });
        let resp = dispatch(r#"{"cmd":"Status"}"#, &tx, &types);
        responder.join().unwrap();
        match resp {
            IpcResponse::State { slots, transport, .. } => {
                assert_eq!(slots.len(), 1);
                assert_eq!(slots[0].name, "kick");
                assert!((transport.bpm - 128.0).abs() < f64::EPSILON);
            }
            other => panic!("expected State, got {other:?}"),
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
        // dispatch() sends the command and blocks waiting for ack.
        // Spawn a thread to respond so dispatch doesn't timeout.
        let responder = std::thread::spawn(move || {
            let cmd = rx.recv().unwrap();
            if let LoopCommand::Graph(_, ack_tx) = cmd {
                let _ = ack_tx.send(Ok("ok".into()));
            }
        });
        let resp = dispatch(msg, &tx, &types);
        responder.join().unwrap();
        assert!(matches!(resp, IpcResponse::Ok { .. }));
    }
}
