pub mod compiler;
pub mod node;

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

pub struct DspGraph {
    nodes: Vec<Box<dyn DspNode>>,
    node_ids: Vec<String>,
    connections: Vec<Connection>,
    process_order: Vec<NodeId>,
    output_node: Option<NodeId>,
    buffers: BufferPool,
    output_buffer_map: OutputBufferMap,
    // Reusable scratch buffers to avoid per-block allocations
    scratch_inputs: Vec<Vec<f32>>,
    scratch_outputs: Vec<Vec<f32>>,
}

impl DspGraph {
    #[must_use]
    pub fn new(
        nodes: Vec<Box<dyn DspNode>>,
        node_ids: Vec<String>,
        connections: Vec<Connection>,
        process_order: Vec<NodeId>,
        output_node: Option<NodeId>,
        buffers: BufferPool,
        output_buffer_map: OutputBufferMap,
    ) -> Self {
        let block_size = buffers.block_size();
        // Pre-compute max input/output port counts for scratch buffer sizing
        let max_inputs = nodes.iter().map(|n| n.num_inputs()).max().unwrap_or(0);
        let max_outputs = nodes.iter().map(|n| n.num_outputs()).max().unwrap_or(0);

        Self {
            nodes,
            node_ids,
            connections,
            process_order,
            output_node,
            buffers,
            output_buffer_map,
            scratch_inputs: vec![vec![0.0; block_size]; max_inputs],
            scratch_outputs: vec![vec![0.0; block_size]; max_outputs],
        }
    }

    pub fn process(&mut self, output: &mut [f32]) {
        self.buffers.clear_all();

        for order_idx in 0..self.process_order.len() {
            let node_id = self.process_order[order_idx];
            let idx = node_id.0;
            let num_inputs = self.nodes[idx].num_inputs();
            let num_outputs = self.nodes[idx].num_outputs();

            // Copy input data from buffer pool into scratch inputs
            let mut input_port = 0;
            for conn in &self.connections {
                if conn.to_node == node_id {
                    let src_buf_idx = self.output_buffer_map[conn.from_node.0][conn.from_port];
                    if input_port < num_inputs {
                        self.scratch_inputs[input_port]
                            .copy_from_slice(&self.buffers.buffers[src_buf_idx]);
                        input_port += 1;
                    }
                }
            }

            // Clear scratch outputs
            for i in 0..num_outputs {
                self.scratch_outputs[i].fill(0.0);
            }

            // Build slice references for DspNode::process
            let input_refs: Vec<&[f32]> = self.scratch_inputs[..num_inputs]
                .iter()
                .map(Vec::as_slice)
                .collect();
            let mut output_refs: Vec<&mut [f32]> = self.scratch_outputs[..num_outputs]
                .iter_mut()
                .map(Vec::as_mut_slice)
                .collect();

            self.nodes[idx].process(&input_refs, &mut output_refs);

            // Copy scratch outputs back into buffer pool
            for (port, &buf_idx) in self.output_buffer_map[idx].iter().enumerate() {
                if port < num_outputs {
                    self.buffers.buffers[buf_idx]
                        .copy_from_slice(&self.scratch_outputs[port]);
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

    #[test]
    fn topo_sort_linear_chain() {
        // A -> B -> C
        let connections = vec![
            Connection { from_node: NodeId(0), from_port: 0, to_node: NodeId(1), to_port: 0 },
            Connection { from_node: NodeId(1), from_port: 0, to_node: NodeId(2), to_port: 0 },
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
            Connection { from_node: NodeId(0), from_port: 0, to_node: NodeId(1), to_port: 0 },
            Connection { from_node: NodeId(0), from_port: 0, to_node: NodeId(2), to_port: 0 },
            Connection { from_node: NodeId(1), from_port: 0, to_node: NodeId(3), to_port: 0 },
            Connection { from_node: NodeId(2), from_port: 0, to_node: NodeId(3), to_port: 0 },
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
            Connection { from_node: NodeId(0), from_port: 0, to_node: NodeId(1), to_port: 0 },
            Connection { from_node: NodeId(1), from_port: 0, to_node: NodeId(0), to_port: 0 },
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

        let nodes: Vec<Box<dyn DspNode>> = vec![
            Box::new(Oscillator::new(sample_rate)),
            Box::new(DacNode),
        ];
        let node_ids = vec!["osc1".into(), "out".into()];
        let connections = vec![Connection {
            from_node: NodeId(0),
            from_port: 0,
            to_node: NodeId(1),
            to_port: 0,
        }];
        let process_order = vec![NodeId(0), NodeId(1)];
        // osc has 1 output buffer (index 0), dac has 1 output buffer (index 1)
        let buffers = BufferPool::new(2, block_size);
        let output_buffer_map = vec![vec![0], vec![1]];

        let mut graph = DspGraph::new(
            nodes,
            node_ids,
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

        let nodes: Vec<Box<dyn DspNode>> = vec![
            Box::new(Oscillator::new(sample_rate)),
            Box::new(DacNode),
        ];
        let node_ids = vec!["osc1".into(), "out".into()];
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
            node_ids,
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
        let count_crossings = |buf: &[f32]| -> usize {
            buf.windows(2)
                .filter(|w| w[0] <= 0.0 && w[1] > 0.0)
                .count()
        };
        let c440 = count_crossings(&output_440);
        let c880 = count_crossings(&output_880);
        assert!(c880 > c440, "880 Hz should have more zero crossings than 440 Hz");
    }

    #[test]
    fn graph_set_param_unknown_node() {
        let graph = DspGraph::new(
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
}
