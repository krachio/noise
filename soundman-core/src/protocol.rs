use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use crate::ir::GraphIr;
use crate::ir::types::NodeTypeDecl;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ClientMessage {
    LoadGraph(GraphIr),
    AddNode {
        id: String,
        type_id: String,
        #[serde(default)]
        controls: HashMap<String, f32>,
    },
    RemoveNode { id: String },
    Connect {
        from_node: String,
        from_port: String,
        to_node: String,
        to_port: String,
    },
    Disconnect {
        from_node: String,
        from_port: String,
        to_node: String,
        to_port: String,
    },
    ExposeControl {
        label: String,
        node_id: String,
        control_name: String,
    },
    SetControl { label: String, value: f32 },
    RegisterNodeType(NodeTypeDecl),
    SetMasterGain { gain: f32 },
    Ping,
    Shutdown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    Ok,
    Error { message: String },
    Pong,
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
    fn server_pong() {
        let msg = ServerMessage::Pong;
        let json = serde_json::to_string(&msg).unwrap();
        let parsed: ServerMessage = serde_json::from_str(&json).unwrap();
        assert!(matches!(parsed, ServerMessage::Pong));
    }
}
