use std::collections::HashMap;

use crate::ir::{ConnectionIr, GraphIr};
use crate::registry::{NodeRegistry, RegistryError};

use super::node::NodeId;
use super::{topological_sort, BufferPool, Connection, DspGraph};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CompileError {
    Registry(RegistryError),
    UnknownNode(String),
    UnknownPort { node_id: String, port_name: String },
    DuplicateNodeId(String),
    Cycle,
}

impl std::fmt::Display for CompileError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Registry(e) => write!(f, "registry error: {e}"),
            Self::UnknownNode(id) => write!(f, "unknown node: {id}"),
            Self::UnknownPort { node_id, port_name } => {
                write!(f, "unknown port '{port_name}' on node '{node_id}'")
            }
            Self::DuplicateNodeId(id) => write!(f, "duplicate node id: {id}"),
            Self::Cycle => write!(f, "graph contains a cycle"),
        }
    }
}

impl std::error::Error for CompileError {}

impl From<RegistryError> for CompileError {
    fn from(e: RegistryError) -> Self {
        Self::Registry(e)
    }
}

/// Compile a `GraphIr` into a runnable `DspGraph`.
///
/// # Errors
/// Returns `CompileError` if validation fails: unknown types, missing ports,
/// duplicate node IDs, or cycles in the graph.
pub fn compile(
    ir: &GraphIr,
    registry: &NodeRegistry,
    sample_rate: u32,
    block_size: usize,
) -> Result<DspGraph, CompileError> {
    // Check for duplicate node IDs
    let mut id_set = HashMap::with_capacity(ir.nodes.len());
    for (idx, node) in ir.nodes.iter().enumerate() {
        if id_set.insert(&node.id, idx).is_some() {
            return Err(CompileError::DuplicateNodeId(node.id.clone()));
        }
    }

    // Validate all type_ids exist and instantiate nodes
    let mut nodes: Vec<Box<dyn super::node::DspNode>> = Vec::with_capacity(ir.nodes.len());
    let mut node_ids: Vec<String> = Vec::with_capacity(ir.nodes.len());

    for ir_node in &ir.nodes {
        let mut node = registry.create_node(&ir_node.type_id, sample_rate, block_size)?;
        // Apply initial control values
        for (name, &value) in &ir_node.controls {
            // Ignore errors for initial controls — allows forward-compatible IR
            let _ = node.set_param(name, value);
        }
        nodes.push(node);
        node_ids.push(ir_node.id.clone());
    }

    // Resolve connections: string IDs -> NodeId indices
    let connections = resolve_connections(&ir.connections, &id_set, &ir.nodes, registry)?;

    // Topological sort
    let process_order =
        topological_sort(nodes.len(), &connections).map_err(|_| CompileError::Cycle)?;

    // Allocate buffers: one per output port
    let mut buffer_count = 0;
    let mut output_buffer_map: Vec<Vec<usize>> = Vec::with_capacity(nodes.len());

    for node in &nodes {
        let num_outputs = node.num_outputs();
        let port_buffers: Vec<usize> = (buffer_count..buffer_count + num_outputs).collect();
        buffer_count += num_outputs;
        output_buffer_map.push(port_buffers);
    }

    let buffers = BufferPool::new(buffer_count.max(1), block_size);

    // Find the output node (type_id "dac")
    let output_node = ir
        .nodes
        .iter()
        .enumerate()
        .find(|(_, n)| n.type_id == "dac")
        .map(|(i, _)| NodeId(i));

    Ok(DspGraph::new(
        nodes,
        node_ids,
        connections,
        process_order,
        output_node,
        buffers,
        output_buffer_map,
    ))
}

fn resolve_connections(
    ir_connections: &[ConnectionIr],
    id_map: &HashMap<&String, usize>,
    ir_nodes: &[crate::ir::NodeInstance],
    registry: &NodeRegistry,
) -> Result<Vec<Connection>, CompileError> {
    let mut connections = Vec::with_capacity(ir_connections.len());

    for conn in ir_connections {
        let &from_idx = id_map
            .get(&conn.from_node)
            .ok_or_else(|| CompileError::UnknownNode(conn.from_node.clone()))?;
        let &to_idx = id_map
            .get(&conn.to_node)
            .ok_or_else(|| CompileError::UnknownNode(conn.to_node.clone()))?;

        let from_type = registry
            .get_type(&ir_nodes[from_idx].type_id)
            .ok_or_else(|| CompileError::UnknownNode(ir_nodes[from_idx].type_id.clone()))?;
        let to_type = registry
            .get_type(&ir_nodes[to_idx].type_id)
            .ok_or_else(|| CompileError::UnknownNode(ir_nodes[to_idx].type_id.clone()))?;

        let from_port = from_type
            .audio_outputs
            .iter()
            .position(|p| p.name == conn.from_port)
            .ok_or_else(|| CompileError::UnknownPort {
                node_id: conn.from_node.clone(),
                port_name: conn.from_port.clone(),
            })?;
        let to_port = to_type
            .audio_inputs
            .iter()
            .position(|p| p.name == conn.to_port)
            .ok_or_else(|| CompileError::UnknownPort {
                node_id: conn.to_node.clone(),
                port_name: conn.to_port.clone(),
            })?;

        connections.push(Connection {
            from_node: NodeId(from_idx),
            from_port,
            to_node: NodeId(to_idx),
            to_port,
        });
    }

    Ok(connections)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ir::NodeInstance;
    use crate::nodes::dac::{dac_type_decl, DacFactory};
    use crate::nodes::oscillator::{oscillator_type_decl, OscillatorFactory};

    fn test_registry() -> NodeRegistry {
        let mut registry = NodeRegistry::new();
        registry
            .register(oscillator_type_decl(), OscillatorFactory)
            .unwrap();
        registry.register(dac_type_decl(), DacFactory).unwrap();
        registry
    }

    fn simple_graph_ir() -> GraphIr {
        GraphIr {
            nodes: vec![
                NodeInstance {
                    id: "osc1".into(),
                    type_id: "oscillator".into(),
                    controls: HashMap::from([("freq".into(), 440.0)]),
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
    fn compile_simple_graph() {
        let registry = test_registry();
        let ir = simple_graph_ir();
        let graph = compile(&ir, &registry, 48000, 512).unwrap();

        assert_eq!(graph.node_count(), 2);
    }

    #[test]
    fn compiled_graph_produces_audio() {
        let registry = test_registry();
        let ir = simple_graph_ir();
        let mut graph = compile(&ir, &registry, 48000, 64).unwrap();

        let mut output = vec![0.0_f32; 64];
        graph.process(&mut output);

        let energy: f32 = output.iter().map(|s| s * s).sum();
        assert!(energy > 0.0, "compiled graph should produce audio");
    }

    #[test]
    fn compile_unknown_type_fails() {
        let registry = test_registry();
        let ir = GraphIr {
            nodes: vec![NodeInstance {
                id: "x".into(),
                type_id: "nonexistent".into(),
                controls: HashMap::new(),
            }],
            connections: vec![],
            exposed_controls: HashMap::new(),
        };
        let result = compile(&ir, &registry, 48000, 512);
        assert!(matches!(result, Err(CompileError::Registry(RegistryError::TypeNotFound(_)))));
    }

    #[test]
    fn compile_unknown_port_fails() {
        let registry = test_registry();
        let ir = GraphIr {
            nodes: vec![
                NodeInstance {
                    id: "osc1".into(),
                    type_id: "oscillator".into(),
                    controls: HashMap::new(),
                },
                NodeInstance {
                    id: "out".into(),
                    type_id: "dac".into(),
                    controls: HashMap::new(),
                },
            ],
            connections: vec![ConnectionIr {
                from_node: "osc1".into(),
                from_port: "nonexistent".into(),
                to_node: "out".into(),
                to_port: "in".into(),
            }],
            exposed_controls: HashMap::new(),
        };
        let result = compile(&ir, &registry, 48000, 512);
        assert!(matches!(result, Err(CompileError::UnknownPort { .. })));
    }

    #[test]
    fn compile_duplicate_node_id_fails() {
        let registry = test_registry();
        let ir = GraphIr {
            nodes: vec![
                NodeInstance {
                    id: "osc1".into(),
                    type_id: "oscillator".into(),
                    controls: HashMap::new(),
                },
                NodeInstance {
                    id: "osc1".into(),
                    type_id: "oscillator".into(),
                    controls: HashMap::new(),
                },
            ],
            connections: vec![],
            exposed_controls: HashMap::new(),
        };
        let result = compile(&ir, &registry, 48000, 512);
        assert!(matches!(result, Err(CompileError::DuplicateNodeId(_))));
    }

    #[test]
    fn compile_unknown_connection_node_fails() {
        let registry = test_registry();
        let ir = GraphIr {
            nodes: vec![NodeInstance {
                id: "osc1".into(),
                type_id: "oscillator".into(),
                controls: HashMap::new(),
            }],
            connections: vec![ConnectionIr {
                from_node: "osc1".into(),
                from_port: "out".into(),
                to_node: "missing".into(),
                to_port: "in".into(),
            }],
            exposed_controls: HashMap::new(),
        };
        let result = compile(&ir, &registry, 48000, 512);
        assert!(matches!(result, Err(CompileError::UnknownNode(_))));
    }

    #[test]
    fn compile_applies_initial_controls() {
        let registry = test_registry();
        let ir = GraphIr {
            nodes: vec![
                NodeInstance {
                    id: "osc1".into(),
                    type_id: "oscillator".into(),
                    controls: HashMap::from([("freq".into(), 1000.0)]),
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
            exposed_controls: HashMap::new(),
        };
        let mut graph = compile(&ir, &registry, 48000, 128).unwrap();

        let mut output = vec![0.0_f32; 128];
        graph.process(&mut output);

        // At 1000 Hz / 48000 SR, we expect ~2.67 cycles in 128 samples
        let crossings = output
            .windows(2)
            .filter(|w| w[0] <= 0.0 && w[1] > 0.0)
            .count();
        assert!((2..=4).contains(&crossings), "expected ~3 crossings at 1000Hz, got {crossings}");
    }
}
