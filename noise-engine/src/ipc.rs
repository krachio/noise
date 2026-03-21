//! Unified IPC server — accepts both midiman (pattern) and soundman (graph)
//! message formats on a single Unix socket.
//!
//! Midiman messages use `"cmd"` tag: SetPattern, Hush, HushAll, SetBpm, Batch, Ping.
//! Soundman messages use `"type"` tag: load_graph, set_control, set_master_gain, list_nodes.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, RwLock};
use std::time::Duration;

use log::warn;
use midiman::ipc::{compile_command, describe};
use midiman::ipc::protocol::ClientMessage as MidimanMsg;
use soundman_core::protocol::ClientMessage;

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
    }
}

/// Start the unified IPC server.
pub fn start(
    socket_path: PathBuf,
    cmd_tx: crossbeam_channel::Sender<LoopCommand>,
    node_types: Arc<RwLock<Vec<String>>>,
) -> Result<IpcHandle, String> {
    let _ = std::fs::remove_file(&socket_path);
    let listener = std::os::unix::net::UnixListener::bind(&socket_path)
        .map_err(|e| format!("bind {}: {e}", socket_path.display()))?;
    listener
        .set_nonblocking(false)
        .map_err(|e| e.to_string())?;

    let stop = Arc::new(AtomicBool::new(false));
    let stop_clone = Arc::clone(&stop);
    let path = socket_path.clone();

    let thread = std::thread::Builder::new()
        .name("noise-ipc".into())
        .spawn(move || run_server(listener, cmd_tx, node_types, stop_clone))
        .expect("failed to spawn IPC thread");

    Ok(IpcHandle { socket_path: path, stop, _thread: thread })
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
                stream.set_read_timeout(Some(Duration::from_millis(100))).ok();
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

        let response = dispatch(&line, cmd_tx, node_types);
        let mut json = serde_json::to_string(&response).expect("serialize response");
        json.push('\n');
        if writer.write_all(json.as_bytes()).is_err() {
            break;
        }
    }
}

/// Route a JSON line to the correct handler.
/// Tries midiman protocol first ("cmd" tag), then soundman ("type" tag).
fn dispatch(
    line: &str,
    cmd_tx: &crossbeam_channel::Sender<LoopCommand>,
    node_types: &Arc<RwLock<Vec<String>>>,
) -> IpcResponse {
    if let Ok(msg) = serde_json::from_str::<MidimanMsg>(line) {
        return handle_pattern(msg, cmd_tx);
    }
    if let Ok(msg) = serde_json::from_str::<ClientMessage>(line) {
        return handle_graph(msg, cmd_tx, node_types);
    }
    IpcResponse::Error { msg: format!("unrecognized message: {line}") }
}

fn handle_pattern(
    msg: MidimanMsg,
    cmd_tx: &crossbeam_channel::Sender<LoopCommand>,
) -> IpcResponse {
    match msg {
        MidimanMsg::Ping => IpcResponse::Pong,
        MidimanMsg::Batch { commands } => {
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
            IpcResponse::Ok { msg: format!("batch applied ({n} commands)") }
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
        ClientMessage::Shutdown => {
            if cmd_tx.send(LoopCommand::Graph(ClientMessage::Shutdown)).is_err() {
                warn!("main loop disconnected");
            }
            IpcResponse::Ok { msg: "shutting down".into() }
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
    use midiman::engine::EngineCommand;

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
        let resp = IpcResponse::NodeTypes { types: vec!["osc".into(), "dac".into()] };
        let json = serde_json::to_string(&resp).unwrap();
        let parsed: IpcResponse = serde_json::from_str(&json).unwrap();
        match parsed {
            IpcResponse::NodeTypes { types } => assert_eq!(types, vec!["osc", "dac"]),
            other => panic!("expected NodeTypes, got {other:?}"),
        }
    }

    #[test]
    fn dispatch_routes_midiman_ping() {
        let (tx, _rx) = crossbeam_channel::unbounded();
        let types = Arc::new(RwLock::new(vec![]));
        let resp = dispatch(r#"{"cmd":"Ping"}"#, &tx, &types);
        assert!(matches!(resp, IpcResponse::Pong));
    }

    #[test]
    fn dispatch_routes_soundman_ping() {
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
        assert!(matches!(cmd, LoopCommand::Pattern(EngineCommand::SetPattern { name, .. }) if name == "d1"));
    }

    #[test]
    fn dispatch_routes_load_graph_to_channel() {
        let (tx, rx) = crossbeam_channel::unbounded();
        let types = Arc::new(RwLock::new(vec![]));
        let msg = r#"{"type":"load_graph","nodes":[],"connections":[],"exposed_controls":{}}"#;
        let resp = dispatch(msg, &tx, &types);
        assert!(matches!(resp, IpcResponse::Ok { .. }));
        let cmd = rx.try_recv().unwrap();
        assert!(matches!(cmd, LoopCommand::Graph(ClientMessage::LoadGraph(_))));
    }
}
