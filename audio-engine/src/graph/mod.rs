pub mod compiler;
pub mod node;

use smallvec::SmallVec;

use node::{DspNode, NodeId, ParamError};

#[derive(Debug, Clone)]
pub struct Connection {
    pub from_node: NodeId,
    pub from_port: usize,
    pub to_node: NodeId,
    pub to_port: usize,
}

pub struct BufferPool {
    buffers: Vec<Vec<f32>>,
    block_size: usize,
}

impl BufferPool {
    #[must_use]
    pub fn new(count: usize, block_size: usize) -> Self {
        Self {
            buffers: vec![vec![0.0; block_size]; count],
            block_size,
        }
    }

    pub fn get_mut(&mut self, index: usize) -> &mut [f32] {
        &mut self.buffers[index]
    }

    #[must_use]
    pub fn get(&self, index: usize) -> &[f32] {
        &self.buffers[index]
    }

    pub fn clear_all(&mut self) {
        for buf in &mut self.buffers {
            buf.fill(0.0);
        }
    }

    #[must_use]
    pub const fn block_size(&self) -> usize {
        self.block_size
    }
}

impl std::fmt::Debug for BufferPool {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("BufferPool")
            .field("count", &self.buffers.len())
            .field("block_size", &self.block_size)
            .finish()
    }
}

/// Maps each node's output ports to buffer indices in the `BufferPool`.
/// `output_buffers[node_index][port_index]` = buffer index.
type OutputBufferMap = Vec<Vec<usize>>;

/// Pre-computed input wiring for a single node: (`source_buffer_index`, `target_port`).
/// Built once at graph construction, avoids O(nodes × connections) scan per block.
type InputMap = Vec<Vec<(usize, usize)>>;

pub struct DspGraph {
    nodes: Vec<Box<dyn DspNode>>,
    node_ids: Vec<String>,
    node_type_ids: Vec<String>,
    node_versions: Vec<u64>,
    connections: Vec<Connection>,
    process_order: Vec<NodeId>,
    output_node: Option<NodeId>,
    buffers: BufferPool,
    output_buffer_map: OutputBufferMap,
    /// Per-node input map: `input_map[node_idx]` = vec of `(src_buf_idx, to_port)`.
    input_map: InputMap,
    // Reusable scratch buffers to avoid per-block allocations
    scratch_inputs: Vec<Vec<f32>>,
    scratch_outputs: Vec<Vec<f32>>,
}

/// A node extracted from a consumed graph, carrying its type and version
/// so the compiler can decide whether to reuse it.
pub struct ReusableNode {
    pub type_id: String,
    pub version: u64,
    pub node: Box<dyn DspNode>,
}

impl std::fmt::Debug for ReusableNode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ReusableNode")
            .field("type_id", &self.type_id)
            .field("version", &self.version)
            .finish_non_exhaustive()
    }
}

impl DspGraph {
    #[must_use]
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        nodes: Vec<Box<dyn DspNode>>,
        node_ids: Vec<String>,
        node_type_ids: Vec<String>,
        node_versions: Vec<u64>,
        connections: Vec<Connection>,
        process_order: Vec<NodeId>,
        output_node: Option<NodeId>,
        buffers: BufferPool,
        output_buffer_map: OutputBufferMap,
    ) -> Self {
        let block_size = buffers.block_size();
        let max_inputs = nodes.iter().map(|n| n.num_inputs()).max().unwrap_or(0);
        let max_outputs = nodes.iter().map(|n| n.num_outputs()).max().unwrap_or(0);

        // Pre-compute per-node input map: for each node, which source buffers
        // feed which input ports. Turns O(nodes × connections) into O(connections).
        let mut input_map: InputMap = vec![vec![]; nodes.len()];
        for conn in &connections {
            let src_buf_idx = output_buffer_map[conn.from_node.0][conn.from_port];
            input_map[conn.to_node.0].push((src_buf_idx, conn.to_port));
        }

        Self {
            nodes,
            node_ids,
            node_type_ids,
            node_versions,
            connections,
            process_order,
            output_node,
            buffers,
            output_buffer_map,
            input_map,
            scratch_inputs: vec![vec![0.0; block_size]; max_inputs],
            scratch_outputs: vec![vec![0.0; block_size]; max_outputs],
        }
    }

    /// Consume the graph and extract nodes for reuse in a new compilation.
    /// Returns a map of `node_id → ReusableNode` with type and version info.
    #[must_use]
    pub fn into_reusable_nodes(self) -> std::collections::HashMap<String, ReusableNode> {
        self.node_ids
            .into_iter()
            .zip(
                self.node_type_ids
                    .into_iter()
                    .zip(self.node_versions),
            )
            .zip(self.nodes)
            .map(|((id, (type_id, version)), node)| {
                (
                    id,
                    ReusableNode {
                        type_id,
                        version,
                        node,
                    },
                )
            })
            .collect()
    }

    pub fn process(&mut self, output: &mut [f32]) {
        self.buffers.clear_all();

        for order_idx in 0..self.process_order.len() {
            let node_id = self.process_order[order_idx];
            let idx = node_id.0;
            let num_inputs = self.nodes[idx].num_inputs();
            let num_outputs = self.nodes[idx].num_outputs();

            // Zero scratch inputs, then sum all sources into their target port (fan-in mixing).
            // Uses pre-computed input_map: O(connections_to_this_node) not O(all_connections).
            for i in 0..num_inputs {
                self.scratch_inputs[i].fill(0.0);
            }
            for &(src_buf_idx, to_port) in &self.input_map[idx] {
                if to_port < num_inputs {
                    for (d, s) in self.scratch_inputs[to_port]
                        .iter_mut()
                        .zip(self.buffers.buffers[src_buf_idx].iter())
                    {
                        // Sanitize NaN: a diverged IIR filter in one voice must not
                        // silence all other voices by poisoning the fan-in sum.
                        *d += if s.is_finite() { *s } else { 0.0 };
                    }
                }
            }

            // Clear scratch outputs
            for i in 0..num_outputs {
                self.scratch_outputs[i].fill(0.0);
            }

            // Build slice references for DspNode::process.
            // SmallVec<[_; 4]> keeps data on the stack for ≤4 ports (typical),
            // avoiding heap allocation on the audio hot path.
            let input_refs: SmallVec<[&[f32]; 4]> = self.scratch_inputs[..num_inputs]
                .iter()
                .map(Vec::as_slice)
                .collect();
            let mut output_refs: SmallVec<[&mut [f32]; 4]> = self.scratch_outputs[..num_outputs]
                .iter_mut()
                .map(Vec::as_mut_slice)
                .collect();

            self.nodes[idx].process(&input_refs, &mut output_refs);
            drop(output_refs); // release mutable borrow before re-reading scratch_outputs

            // Copy scratch outputs back into buffer pool
            for (port, &buf_idx) in self.output_buffer_map[idx].iter().enumerate() {
                if port < num_outputs {
                    self.buffers.buffers[buf_idx].copy_from_slice(&self.scratch_outputs[port]);
                }
            }
        }

        // Copy output node's buffer to the output slice
        if let Some(output_node) = self.output_node
            && !self.output_buffer_map[output_node.0].is_empty()
        {
            let buf_idx = self.output_buffer_map[output_node.0][0];
            let src = self.buffers.get(buf_idx);
            let len = output.len().min(src.len());
            output[..len].copy_from_slice(&src[..len]);
        }
    }

    /// # Errors
    /// Returns `ParamError` if the node doesn't have this parameter.
    pub fn set_param(&mut self, node_id: &str, name: &str, value: f32) -> Result<(), ParamError> {
        let idx = self
            .node_ids
            .iter()
            .position(|id| id == node_id)
            .ok_or_else(|| ParamError::NotFound(format!("node '{node_id}' not found")))?;
        self.nodes[idx].set_param(name, value)
    }

    #[must_use]
    pub fn node_count(&self) -> usize {
        self.nodes.len()
    }
}

impl std::fmt::Debug for DspGraph {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("DspGraph")
            .field("node_ids", &self.node_ids)
            .field("connections", &self.connections)
            .field("process_order", &self.process_order)
            .field("output_node", &self.output_node)
            .field("buffers", &self.buffers)
            .finish_non_exhaustive()
    }
}

/// Topological sort using Kahn's algorithm.
/// Returns nodes in processing order (sources first, sinks last).
///
/// # Errors
/// Returns an error string if the graph contains a cycle.
pub fn topological_sort(
    node_count: usize,
    connections: &[Connection],
) -> Result<Vec<NodeId>, String> {
    let mut in_degree = vec![0_usize; node_count];
    let mut adjacency: Vec<Vec<NodeId>> = vec![vec![]; node_count];

    for conn in connections {
        in_degree[conn.to_node.0] += 1;
        adjacency[conn.from_node.0].push(conn.to_node);
    }

    let mut queue: Vec<NodeId> = (0..node_count)
        .filter(|&i| in_degree[i] == 0)
        .map(NodeId)
        .collect();

    let mut order = Vec::with_capacity(node_count);

    while let Some(node) = queue.pop() {
        order.push(node);
        for &neighbor in &adjacency[node.0] {
            in_degree[neighbor.0] -= 1;
            if in_degree[neighbor.0] == 0 {
                queue.push(neighbor);
            }
        }
    }

    if order.len() == node_count {
        Ok(order)
    } else {
        Err("graph contains a cycle".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::nodes::dac::DacNode;
    use crate::nodes::oscillator::Oscillator;

    /// Emits a constant value on its single output — useful for deterministic graph tests.
    struct ConstantNode(f32);

    impl DspNode for ConstantNode {
        fn process(&mut self, _inputs: &[&[f32]], outputs: &mut [&mut [f32]]) {
            if let Some(out) = outputs.first_mut() {
                out.fill(self.0);
            }
        }
        fn num_inputs(&self) -> usize {
            0
        }
        fn num_outputs(&self) -> usize {
            1
        }
        fn set_param(&mut self, name: &str, _value: f32) -> Result<(), ParamError> {
            Err(ParamError::NotFound(name.into()))
        }
        fn reset(&mut self, _sample_rate: u32) {}
    }

    /// Emits NaN on every sample — simulates a diverged IIR filter.
    struct NanNode;

    impl DspNode for NanNode {
        fn process(&mut self, _: &[&[f32]], outputs: &mut [&mut [f32]]) {
            if let Some(out) = outputs.first_mut() {
                out.fill(f32::NAN);
            }
        }
        fn num_inputs(&self) -> usize {
            0
        }
        fn num_outputs(&self) -> usize {
            1
        }
        fn set_param(&mut self, name: &str, _: f32) -> Result<(), ParamError> {
            Err(ParamError::NotFound(name.into()))
        }
        fn reset(&mut self, _: u32) {}
    }

    /// Two-input node: output = input[0] − input[1].
    /// Used to verify that the graph routes connections to the correct port index.
    struct SubtractNode;

    impl DspNode for SubtractNode {
        fn process(&mut self, inputs: &[&[f32]], outputs: &mut [&mut [f32]]) {
            if let Some(out) = outputs.first_mut() {
                let in0 = inputs.first().map_or(0.0_f32, |s| s[0]);
                let in1 = inputs.get(1).map_or(0.0_f32, |s| s[0]);
                out.fill(in0 - in1);
            }
        }
        fn num_inputs(&self) -> usize {
            2
        }
        fn num_outputs(&self) -> usize {
            1
        }
        fn set_param(&mut self, name: &str, _value: f32) -> Result<(), ParamError> {
            Err(ParamError::NotFound(name.into()))
        }
        fn reset(&mut self, _sample_rate: u32) {}
    }

    fn make_graph(
        nodes: Vec<Box<dyn DspNode>>,
        node_ids: Vec<String>,
        connections: Vec<Connection>,
        process_order: Vec<NodeId>,
        output_node: Option<NodeId>,
        block_size: usize,
    ) -> DspGraph {
        let buffer_count: usize = nodes.iter().map(|n| n.num_outputs()).sum();
        let buffers = BufferPool::new(buffer_count.max(1), block_size);
        let mut buf_idx = 0;
        let output_buffer_map: Vec<Vec<usize>> = nodes
            .iter()
            .map(|n| {
                let ports: Vec<usize> = (buf_idx..buf_idx + n.num_outputs()).collect();
                buf_idx += n.num_outputs();
                ports
            })
            .collect();
        let n = node_ids.len();
        DspGraph::new(
            nodes,
            node_ids,
            vec!["test".into(); n],
            vec![0; n],
            connections,
            process_order,
            output_node,
            buffers,
            output_buffer_map,
        )
    }

    #[test]
    fn topo_sort_linear_chain() {
        // A -> B -> C
        let connections = vec![
            Connection {
                from_node: NodeId(0),
                from_port: 0,
                to_node: NodeId(1),
                to_port: 0,
            },
            Connection {
                from_node: NodeId(1),
                from_port: 0,
                to_node: NodeId(2),
                to_port: 0,
            },
        ];
        let order = topological_sort(3, &connections).unwrap();
        assert_eq!(order.len(), 3);

        let pos = |id: NodeId| order.iter().position(|&n| n == id).unwrap();
        assert!(pos(NodeId(0)) < pos(NodeId(1)));
        assert!(pos(NodeId(1)) < pos(NodeId(2)));
    }

    #[test]
    fn topo_sort_diamond() {
        // A -> B, A -> C, B -> D, C -> D
        let connections = vec![
            Connection {
                from_node: NodeId(0),
                from_port: 0,
                to_node: NodeId(1),
                to_port: 0,
            },
            Connection {
                from_node: NodeId(0),
                from_port: 0,
                to_node: NodeId(2),
                to_port: 0,
            },
            Connection {
                from_node: NodeId(1),
                from_port: 0,
                to_node: NodeId(3),
                to_port: 0,
            },
            Connection {
                from_node: NodeId(2),
                from_port: 0,
                to_node: NodeId(3),
                to_port: 0,
            },
        ];
        let order = topological_sort(4, &connections).unwrap();
        assert_eq!(order.len(), 4);

        let pos = |id: NodeId| order.iter().position(|&n| n == id).unwrap();
        assert!(pos(NodeId(0)) < pos(NodeId(1)));
        assert!(pos(NodeId(0)) < pos(NodeId(2)));
        assert!(pos(NodeId(1)) < pos(NodeId(3)));
        assert!(pos(NodeId(2)) < pos(NodeId(3)));
    }

    #[test]
    fn topo_sort_no_connections() {
        let order = topological_sort(3, &[]).unwrap();
        assert_eq!(order.len(), 3);
    }

    #[test]
    fn topo_sort_cycle_detected() {
        let connections = vec![
            Connection {
                from_node: NodeId(0),
                from_port: 0,
                to_node: NodeId(1),
                to_port: 0,
            },
            Connection {
                from_node: NodeId(1),
                from_port: 0,
                to_node: NodeId(0),
                to_port: 0,
            },
        ];
        let result = topological_sort(2, &connections);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("cycle"));
    }

    #[test]
    fn buffer_pool_clear_and_access() {
        let mut pool = BufferPool::new(3, 64);
        assert_eq!(pool.block_size(), 64);

        pool.get_mut(1).fill(0.5);
        assert!((pool.get(1)[0] - 0.5).abs() < f32::EPSILON);

        pool.clear_all();
        assert!((pool.get(1)[0]).abs() < f32::EPSILON);
    }

    #[test]
    fn graph_osc_to_dac_produces_audio() {
        let block_size = 64;
        let sample_rate = 48000;

        let nodes: Vec<Box<dyn DspNode>> =
            vec![Box::new(Oscillator::new(sample_rate)), Box::new(DacNode)];
        let connections = vec![Connection {
            from_node: NodeId(0),
            from_port: 0,
            to_node: NodeId(1),
            to_port: 0,
        }];
        let process_order = vec![NodeId(0), NodeId(1)];
        let buffers = BufferPool::new(2, block_size);
        let output_buffer_map = vec![vec![0], vec![1]];

        let mut graph = DspGraph::new(
            nodes,
            vec!["osc1".into(), "out".into()],
            vec!["oscillator".into(), "dac".into()],
            vec![0; 2],
            connections,
            process_order,
            Some(NodeId(1)),
            buffers,
            output_buffer_map,
        );

        let mut output = vec![0.0_f32; block_size];
        graph.process(&mut output);

        // Output should be non-silent (sine wave from oscillator)
        let energy: f32 = output.iter().map(|s| s * s).sum();
        assert!(energy > 0.0, "graph should produce non-silent output");

        // All samples should be in [-1, 1]
        for &s in &output {
            assert!((-1.0..=1.0).contains(&s), "sample out of range: {s}");
        }
    }

    #[test]
    fn graph_set_param_changes_frequency() {
        let block_size = 256;
        let sample_rate = 48000;

        let nodes: Vec<Box<dyn DspNode>> =
            vec![Box::new(Oscillator::new(sample_rate)), Box::new(DacNode)];
        let connections = vec![Connection {
            from_node: NodeId(0),
            from_port: 0,
            to_node: NodeId(1),
            to_port: 0,
        }];
        let process_order = vec![NodeId(0), NodeId(1)];
        let buffers = BufferPool::new(2, block_size);
        let output_buffer_map = vec![vec![0], vec![1]];

        let mut graph = DspGraph::new(
            nodes,
            vec!["osc1".into(), "out".into()],
            vec!["oscillator".into(), "dac".into()],
            vec![0; 2],
            connections,
            process_order,
            Some(NodeId(1)),
            buffers,
            output_buffer_map,
        );

        // Get baseline output at 440 Hz
        let mut output_440 = vec![0.0_f32; block_size];
        graph.process(&mut output_440);

        // Change frequency and get new output
        graph.set_param("osc1", "freq", 880.0).unwrap();
        let mut output_880 = vec![0.0_f32; block_size];
        graph.process(&mut output_880);

        // Count zero crossings — 880 Hz should have roughly 2x the crossings of 440 Hz
        let count_crossings =
            |buf: &[f32]| -> usize { buf.windows(2).filter(|w| w[0] <= 0.0 && w[1] > 0.0).count() };
        let c440 = count_crossings(&output_440);
        let c880 = count_crossings(&output_880);
        assert!(
            c880 > c440,
            "880 Hz should have more zero crossings than 440 Hz"
        );
    }

    #[test]
    fn graph_set_param_unknown_node() {
        let graph = DspGraph::new(
            vec![],
            vec![],
            vec![],
            vec![],
            vec![],
            vec![],
            None,
            BufferPool::new(0, 64),
            vec![],
        );
        // set_param requires &mut but we need to test the error path
        let mut graph = graph;
        let result = graph.set_param("missing", "freq", 440.0);
        assert!(matches!(result, Err(ParamError::NotFound(_))));
    }

    #[test]
    fn fan_in_two_sources_summed_at_same_port() {
        // Two ConstantNodes both connected to DAC's single input port.
        // Output must be their sum (0.5 + 0.3 = 0.8), not just one of them.
        let block_size = 16;
        let mut graph = make_graph(
            vec![
                Box::new(ConstantNode(0.5)),
                Box::new(ConstantNode(0.3)),
                Box::new(DacNode),
            ],
            vec!["c1".into(), "c2".into(), "out".into()],
            vec![
                Connection {
                    from_node: NodeId(0),
                    from_port: 0,
                    to_node: NodeId(2),
                    to_port: 0,
                },
                Connection {
                    from_node: NodeId(1),
                    from_port: 0,
                    to_node: NodeId(2),
                    to_port: 0,
                },
            ],
            vec![NodeId(0), NodeId(1), NodeId(2)],
            Some(NodeId(2)),
            block_size,
        );

        let mut output = vec![0.0_f32; block_size];
        graph.process(&mut output);

        for &s in &output {
            assert!((s - 0.8).abs() < 1e-6, "expected 0.5 + 0.3 = 0.8, got {s}");
        }
    }

    #[test]
    fn fan_in_routes_to_correct_port_index() {
        // Connections stored in reverse port order (port 1 first, then port 0).
        // SubtractNode output = input[0] − input[1] = 0.7 − 0.3 = 0.4.
        // If conn.to_port is ignored (sequential counter bug), ports are swapped
        // and the result would be 0.3 − 0.7 = −0.4.
        let block_size = 16;
        let mut graph = make_graph(
            vec![
                Box::new(ConstantNode(0.7)), // NodeId(0) → port 0
                Box::new(ConstantNode(0.3)), // NodeId(1) → port 1
                Box::new(SubtractNode),
                Box::new(DacNode),
            ],
            vec!["c1".into(), "c2".into(), "sub".into(), "out".into()],
            vec![
                // Reversed: port 1 connection listed before port 0
                Connection {
                    from_node: NodeId(1),
                    from_port: 0,
                    to_node: NodeId(2),
                    to_port: 1,
                },
                Connection {
                    from_node: NodeId(0),
                    from_port: 0,
                    to_node: NodeId(2),
                    to_port: 0,
                },
                Connection {
                    from_node: NodeId(2),
                    from_port: 0,
                    to_node: NodeId(3),
                    to_port: 0,
                },
            ],
            vec![NodeId(0), NodeId(1), NodeId(2), NodeId(3)],
            Some(NodeId(3)),
            block_size,
        );

        let mut output = vec![0.0_f32; block_size];
        graph.process(&mut output);

        for &s in &output {
            assert!(
                (s - 0.4).abs() < 1e-6,
                "expected input[0]-input[1] = 0.4, got {s}"
            );
        }
    }

    #[test]
    fn nan_source_does_not_silence_healthy_sources() {
        // NaN from a diverged FAUST IIR filter must not poison the fan-in sum
        // and silence other voices (e.g. drums when acid bass diverges).
        let block_size = 16;
        let mut graph = make_graph(
            vec![
                Box::new(ConstantNode(0.5)),
                Box::new(NanNode),
                Box::new(DacNode),
            ],
            vec!["good".into(), "nan".into(), "out".into()],
            vec![
                Connection {
                    from_node: NodeId(0),
                    from_port: 0,
                    to_node: NodeId(2),
                    to_port: 0,
                },
                Connection {
                    from_node: NodeId(1),
                    from_port: 0,
                    to_node: NodeId(2),
                    to_port: 0,
                },
            ],
            vec![NodeId(0), NodeId(1), NodeId(2)],
            Some(NodeId(2)),
            block_size,
        );

        let mut output = vec![0.0_f32; block_size];
        graph.process(&mut output);

        for &s in &output {
            assert!(
                s.is_finite(),
                "NaN from one source must not poison the output"
            );
            assert!(
                (s - 0.5).abs() < 1e-6,
                "healthy source output must survive NaN neighbour"
            );
        }
    }
}
