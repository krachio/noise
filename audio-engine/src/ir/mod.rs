//! Graph intermediate representation — the JSON wire format.
//!
//! A [`GraphIr`] describes the audio graph declaratively: which nodes exist,
//! how they connect, and which controls are exposed for external manipulation.
//! The engine compiles this IR into a runnable [`DspGraph`](crate::graph::DspGraph).

pub mod types;

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

/// A node in the graph IR. References a registered `type_id` and provides
/// initial control values.
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct NodeInstance {
    /// Unique identifier within this graph (e.g. `"osc1"`, `"filter2"`).
    pub id: String,
    /// Registered node type (e.g. `"oscillator"`, `"dac"`, `"faust:lowpass2"`).
    pub type_id: String,
    /// Initial parameter values, keyed by parameter name.
    #[serde(default)]
    pub controls: HashMap<String, f32>,
}

/// A directed edge between two node ports.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConnectionIr {
    pub from_node: String,
    pub from_port: String,
    pub to_node: String,
    pub to_port: String,
}

/// Complete graph description — nodes, connections, and exposed controls.
///
/// Exposed controls map a user-facing label (e.g. `"pitch"`) to a
/// `(node_id, param_name)` pair, allowing external control via
/// [`ClientMessage::SetControl`](crate::protocol::ClientMessage::SetControl).
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GraphIr {
    pub nodes: Vec<NodeInstance>,
    pub connections: Vec<ConnectionIr>,
    /// Maps `label → (node_id, param_name)` for external control.
    #[serde(default)]
    pub exposed_controls: HashMap<String, (String, String)>,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_graph_ir() -> GraphIr {
        GraphIr {
            nodes: vec![
                NodeInstance {
                    id: "osc1".into(),
                    type_id: "oscillator".into(),
                    controls: HashMap::from([("freq".into(), 440.0), ("waveform".into(), 0.0)]),
                },
                NodeInstance {
                    id: "out".into(),
                    type_id: "dac".into(),
                    controls: HashMap::new(),
                },
            ],
            connections: vec![ConnectionIr {
                from_node: "osc1".into(),
                from_port: "out".into(),
                to_node: "out".into(),
                to_port: "in".into(),
            }],
            exposed_controls: HashMap::from([("pitch".into(), ("osc1".into(), "freq".into()))]),
        }
    }

    #[test]
    fn graph_ir_serde_roundtrip() {
        let graph = sample_graph_ir();
        let json = serde_json::to_string(&graph).unwrap();
        let roundtripped: GraphIr = serde_json::from_str(&json).unwrap();
        assert_eq!(graph, roundtripped);
    }

    #[test]
    fn graph_ir_deserializes_from_wire_format() {
        let json = r#"{
            "nodes": [
                {"id": "osc1", "type_id": "oscillator", "controls": {"freq": 440.0, "waveform": 0.0}},
                {"id": "filt1", "type_id": "faust:lowpass2", "controls": {"cutoff": 1000.0}},
                {"id": "out", "type_id": "dac", "controls": {}}
            ],
            "connections": [
                {"from_node": "osc1", "from_port": "out", "to_node": "filt1", "to_port": "in"},
                {"from_node": "filt1", "from_port": "out", "to_node": "out", "to_port": "in"}
            ],
            "exposed_controls": {
                "pitch": ["osc1", "freq"],
                "brightness": ["filt1", "cutoff"]
            }
        }"#;

        let graph: GraphIr = serde_json::from_str(json).unwrap();
        assert_eq!(graph.nodes.len(), 3);
        assert_eq!(graph.connections.len(), 2);
        assert_eq!(
            graph.exposed_controls.get("pitch"),
            Some(&("osc1".into(), "freq".into()))
        );
    }

    #[test]
    fn graph_ir_empty_controls_default() {
        let json = r#"{
            "nodes": [{"id": "out", "type_id": "dac"}],
            "connections": []
        }"#;

        let graph: GraphIr = serde_json::from_str(json).unwrap();
        assert!(graph.nodes[0].controls.is_empty());
        assert!(graph.exposed_controls.is_empty());
    }
}
