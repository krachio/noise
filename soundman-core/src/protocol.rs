//! JSON message protocol between control sources and the engine.
//!
//! Messages are serde-tagged with `"type"` and `snake_case` variants, so
//! `LoadGraph` serializes as `{"type": "load_graph", ...}`.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use crate::ir::GraphIr;
use crate::ir::types::NodeTypeDecl;

/// Commands sent to the engine from control sources (OSC, IPC, tests).
///
/// Graph-mutating messages (`LoadGraph`, `AddNode`, `RemoveNode`, `Connect`,
/// `Disconnect`) trigger a recompile of the shadow graph. `SetControl` and
/// `SetMasterGain` are forwarded to the audio thread without recompilation.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ClientMessage {
    /// Replace the entire graph. Crossfades from the current graph.
    LoadGraph(GraphIr),
    /// Add a node to the shadow graph.
    AddNode {
        id: String,
        type_id: String,
        #[serde(default)]
        controls: HashMap<String, f32>,
    },
    /// Remove a node and all its connections.
    RemoveNode { id: String },
    /// Connect two ports.
    Connect {
        from_node: String,
        from_port: String,
        to_node: String,
        to_port: String,
    },
    /// Remove a connection.
    Disconnect {
        from_node: String,
        from_port: String,
        to_node: String,
        to_port: String,
    },
    /// Map a user-facing label to a node parameter for `SetControl`.
    ExposeControl {
        label: String,
        node_id: String,
        control_name: String,
    },
    /// Set an exposed control parameter by label.
    SetControl { label: String, value: f32 },
    /// Register a new node type declaration.
    RegisterNodeType(NodeTypeDecl),
    /// Set the master output gain (0.0–1.0).
    SetMasterGain { gain: f32 },
    /// Request the list of registered node type IDs.
    /// soundman sends a `/soundman/node_types` OSC reply to `127.0.0.1:<reply_port>`.
    ListNodes { reply_port: u16 },
    /// Atomic batch of graph mutations. All mutations are applied to the
    /// shadow graph before a single recompile + SwapGraph.
    GraphBatch { commands: Vec<ClientMessage> },
    /// Health check — engine responds with `ServerMessage::Pong`.
    Ping,
    /// Shut down the engine.
    Shutdown,
}

/// Responses from the engine.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    /// Command accepted.
    Ok,
    /// Command failed.
    Error { message: String },
    /// Response to `Ping`.
    Pong,
    /// List of registered node type IDs.
    NodeTypes { types: Vec<String> },
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn set_control_serde_roundtrip() {
        let msg = ClientMessage::SetControl {
            label: "pitch".into(),
            value: 880.0,
        };
        let json = serde_json::to_string(&msg).unwrap();
        let parsed: ClientMessage = serde_json::from_str(&json).unwrap();

        assert!(matches!(
            parsed,
            ClientMessage::SetControl { ref label, .. } if label == "pitch"
        ));
    }

    #[test]
    fn ping_serde() {
        let msg = ClientMessage::Ping;
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains("ping"));

        let parsed: ClientMessage = serde_json::from_str(&json).unwrap();
        assert!(matches!(parsed, ClientMessage::Ping));
    }

    #[test]
    fn load_graph_from_json() {
        let json = r#"{
            "type": "load_graph",
            "nodes": [
                {"id": "osc1", "type_id": "oscillator", "controls": {"freq": 440.0}}
            ],
            "connections": [],
            "exposed_controls": {}
        }"#;
        let msg: ClientMessage = serde_json::from_str(json).unwrap();
        assert!(matches!(msg, ClientMessage::LoadGraph(_)));
    }

    #[test]
    fn server_error_response() {
        let msg = ServerMessage::Error {
            message: "unknown node type".into(),
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains("unknown node type"));
    }

    #[test]
    fn graph_batch_serde_roundtrip() {
        let msg = ClientMessage::GraphBatch {
            commands: vec![
                ClientMessage::AddNode {
                    id: "osc2".into(),
                    type_id: "oscillator".into(),
                    controls: HashMap::from([("freq".into(), 880.0)]),
                },
                ClientMessage::Connect {
                    from_node: "osc2".into(),
                    from_port: "out".into(),
                    to_node: "out".into(),
                    to_port: "in".into(),
                },
            ],
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains("graph_batch"));
        let parsed: ClientMessage = serde_json::from_str(&json).unwrap();
        match parsed {
            ClientMessage::GraphBatch { commands } => assert_eq!(commands.len(), 2),
            other => panic!("expected GraphBatch, got {other:?}"),
        }
    }

    #[test]
    fn server_pong() {
        let msg = ServerMessage::Pong;
        let json = serde_json::to_string(&msg).unwrap();
        let parsed: ServerMessage = serde_json::from_str(&json).unwrap();
        assert!(matches!(parsed, ServerMessage::Pong));
    }
}
