use std::collections::HashMap;

use log::{debug, warn};

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

/// Compile a `GraphIr` into a runnable `DspGraph`, creating fresh node instances.
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
    compile_with_reuse(ir, registry, None, sample_rate, block_size)
}

/// Compile a `GraphIr`, reusing node instances from a previous graph when the
/// node ID, type, and registry version all match. This preserves DSP state
/// (ADSR phase, filter memory, reverb tails) for unchanged voices across
/// graph swaps.
///
/// # Errors
/// Returns `CompileError` if validation fails.
pub fn compile_with_reuse(
    ir: &GraphIr,
    registry: &NodeRegistry,
    previous: Option<DspGraph>,
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

    // Extract reusable nodes from previous graph (if any)
    let mut reusable = previous.map_or_else(HashMap::new, DspGraph::into_reusable_nodes);
    let reusable_count = reusable.len();

    // Instantiate nodes — reuse when ID + type + version match
    let mut nodes: Vec<Box<dyn super::node::DspNode>> = Vec::with_capacity(ir.nodes.len());
    let mut node_ids: Vec<String> = Vec::with_capacity(ir.nodes.len());
    let mut node_type_ids: Vec<String> = Vec::with_capacity(ir.nodes.len());
    let mut node_versions: Vec<u64> = Vec::with_capacity(ir.nodes.len());
    let mut reused = 0_usize;

    for ir_node in &ir.nodes {
        let current_version = registry.version(&ir_node.type_id);

        let node = if let Some(cached) = reusable.remove(&ir_node.id) {
            if cached.type_id == ir_node.type_id && cached.version == current_version {
                // Reuse — internal DSP state (filter memory, reverb tails) preserved.
                // Apply initial controls to reset gate=0 (prevents stuck-gate silence)
                // and update freq/cutoff to match the new IR.
                reused += 1;
                let mut node = cached.node;
                for (name, &value) in &ir_node.controls {
                    if let Err(e) = node.set_param(name, value) {
                        warn!("set_param on reused {}/{name}: {e}", ir_node.id);
                    }
                }
                node
            } else {
                // Type or factory changed — create fresh
                let mut fresh = registry.create_node(&ir_node.type_id, sample_rate, block_size)?;
                for (name, &value) in &ir_node.controls {
                    if let Err(e) = fresh.set_param(name, value) {
                        warn!("set_param on fresh {}/{name}: {e}", ir_node.id);
                    }
                }
                fresh
            }
        } else {
            // New node
            let mut fresh = registry.create_node(&ir_node.type_id, sample_rate, block_size)?;
            for (name, &value) in &ir_node.controls {
                if let Err(e) = fresh.set_param(name, value) {
                    warn!("set_param on new {}/{name}: {e}", ir_node.id);
                }
            }
            fresh
        };

        nodes.push(node);
        node_ids.push(ir_node.id.clone());
        node_type_ids.push(ir_node.type_id.clone());
        node_versions.push(current_version);
    }

    debug!(
        "compile_with_reuse: {}/{} nodes reused (from {} reusable candidates)",
        reused,
        ir.nodes.len(),
        reusable_count,
    );

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
        node_type_ids,
        node_versions,
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

    #[test]
    fn compile_with_reuse_preserves_oscillator_phase() {
        // Compile a graph, process a few blocks to advance oscillator phase,
        // then recompile with reuse. The reused oscillator should continue
        // from the same phase (not restart from zero).
        let registry = test_registry();
        let ir = simple_graph_ir();

        let mut graph1 = compile(&ir, &registry, 48000, 64).unwrap();

        // Process 10 blocks to advance phase
        let mut buf = vec![0.0_f32; 64];
        for _ in 0..10 {
            graph1.process(&mut buf);
        }
        let last_sample_before = buf[63];

        // Recompile with reuse — oscillator should keep its phase
        let mut graph2 = compile_with_reuse(&ir, &registry, Some(graph1), 48000, 64).unwrap();
        let mut buf2 = vec![0.0_f32; 64];
        graph2.process(&mut buf2);
        let first_sample_after = buf2[0];

        // Phase continuity: no large discontinuity
        let jump = (first_sample_after - last_sample_before).abs();
        assert!(
            jump < 0.15,
            "reused oscillator should preserve phase: jump={jump} (before={last_sample_before}, after={first_sample_after})"
        );
    }

    #[test]
    fn compile_with_reuse_creates_fresh_for_new_node() {
        let registry = test_registry();
        let ir = simple_graph_ir();

        let graph1 = compile(&ir, &registry, 48000, 64).unwrap();

        // Change the graph: different node ID → can't reuse
        let ir2 = GraphIr {
            nodes: vec![
                NodeInstance {
                    id: "osc_new".into(),  // different ID
                    type_id: "oscillator".into(),
                    controls: HashMap::from([("freq".into(), 880.0)]),
                },
                NodeInstance {
                    id: "out".into(),
                    type_id: "dac".into(),
                    controls: HashMap::new(),
                },
            ],
            connections: vec![ConnectionIr {
                from_node: "osc_new".into(),
                from_port: "out".into(),
                to_node: "out".into(),
                to_port: "in".into(),
            }],
            exposed_controls: HashMap::new(),
        };

        let mut graph2 = compile_with_reuse(&ir2, &registry, Some(graph1), 48000, 64).unwrap();
        let mut buf = vec![0.0_f32; 64];
        graph2.process(&mut buf);

        // Should produce audio (new fresh node at 880 Hz)
        let energy: f32 = buf.iter().map(|s| s * s).sum();
        assert!(energy > 0.0, "new node should produce audio");
    }

    #[test]
    fn compile_with_reuse_creates_fresh_after_reregister() {
        let mut registry = test_registry();
        let ir = simple_graph_ir();

        let graph1 = compile(&ir, &registry, 48000, 64).unwrap();

        // Reregister oscillator with a different factory (simulates hot-reload)
        registry.reregister(oscillator_type_decl(), OscillatorFactory).unwrap();

        // Recompile with reuse — version mismatch, should NOT reuse
        let mut graph2 = compile_with_reuse(&ir, &registry, Some(graph1), 48000, 64).unwrap();
        let mut buf = vec![0.0_f32; 64];
        graph2.process(&mut buf);

        // Should still produce audio (fresh instance)
        let energy: f32 = buf.iter().map(|s| s * s).sum();
        assert!(energy > 0.0, "fresh node after reregister should produce audio");
    }

    #[test]
    fn compile_with_reuse_applies_initial_controls_to_reused_node() {
        // Compile at 440 Hz, process, then recompile with reuse at 1000 Hz.
        // The reused oscillator should produce audio at the NEW frequency (1000 Hz)
        // because initial controls from the IR are applied on reuse.
        // This also ensures gate=0 is applied on reuse (prevents stuck-gate silence).
        let registry = test_registry();
        let ir_440 = simple_graph_ir(); // freq=440

        let mut graph1 = compile(&ir_440, &registry, 48000, 256).unwrap();
        let mut buf_440 = vec![0.0_f32; 256];
        graph1.process(&mut buf_440);

        // Recompile with freq=1000
        let ir_1000 = GraphIr {
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

        let mut graph2 = compile_with_reuse(&ir_1000, &registry, Some(graph1), 48000, 256).unwrap();
        let mut buf_1000 = vec![0.0_f32; 256];
        graph2.process(&mut buf_1000);

        // Count zero crossings — 1000 Hz should have more than 440 Hz
        let count_crossings = |buf: &[f32]| -> usize {
            buf.windows(2).filter(|w| w[0] <= 0.0 && w[1] > 0.0).count()
        };
        let c440 = count_crossings(&buf_440);
        let c1000 = count_crossings(&buf_1000);
        assert!(
            c1000 > c440,
            "reused node should have freq=1000 applied (got {c1000} crossings vs {c440} at 440Hz)"
        );
    }
}
