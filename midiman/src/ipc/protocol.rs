use serde::{Deserialize, Serialize};

use crate::ir::IrNode;

/// Message from client (Python frontend) to server (midiman kernel).
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "cmd")]
pub enum ClientMessage {
    /// Set a pattern on a named slot (e.g., "d1").
    SetPattern { slot: String, pattern: IrNode },
    /// Silence a named slot.
    Hush { slot: String },
    /// Silence all slots.
    HushAll,
    /// Set BPM.
    SetBpm { bpm: f64 },
    /// Ping / health check.
    Ping,
}

/// Message from server to client.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "status")]
pub enum ServerMessage {
    Ok { msg: String },
    Error { msg: String },
    Pong,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::Value;

    #[test]
    fn client_message_set_pattern_roundtrip() {
        let msg = ClientMessage::SetPattern {
            slot: "d1".into(),
            pattern: IrNode::Atom {
                value: Value::Note {
                    channel: 0,
                    note: 60,
                    velocity: 100,
                    dur: 0.5,
                },
            },
        };
        let json = serde_json::to_string(&msg).unwrap();
        let decoded: ClientMessage = serde_json::from_str(&json).unwrap();
        match decoded {
            ClientMessage::SetPattern { slot, pattern } => {
                assert_eq!(slot, "d1");
                match pattern {
                    IrNode::Atom { value } => match value {
                        Value::Note { note, .. } => assert_eq!(note, 60),
                        _ => panic!("expected Note"),
                    },
                    _ => panic!("expected Atom"),
                }
            }
            _ => panic!("expected SetPattern"),
        }
    }

    #[test]
    fn client_message_hush_roundtrip() {
        let msg = ClientMessage::Hush {
            slot: "d2".into(),
        };
        let json = serde_json::to_string(&msg).unwrap();
        let decoded: ClientMessage = serde_json::from_str(&json).unwrap();
        match decoded {
            ClientMessage::Hush { slot } => assert_eq!(slot, "d2"),
            _ => panic!("expected Hush"),
        }
    }

    #[test]
    fn client_message_ping_roundtrip() {
        let json = serde_json::to_string(&ClientMessage::Ping).unwrap();
        let decoded: ClientMessage = serde_json::from_str(&json).unwrap();
        assert!(matches!(decoded, ClientMessage::Ping));
    }

    #[test]
    fn server_message_roundtrip() {
        let ok = serde_json::to_string(&ServerMessage::Ok {
            msg: "done".into(),
        })
        .unwrap();
        let decoded: ServerMessage = serde_json::from_str(&ok).unwrap();
        assert!(matches!(decoded, ServerMessage::Ok { .. }));

        let pong = serde_json::to_string(&ServerMessage::Pong).unwrap();
        let decoded: ServerMessage = serde_json::from_str(&pong).unwrap();
        assert!(matches!(decoded, ServerMessage::Pong));
    }
}
