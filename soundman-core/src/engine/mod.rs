pub mod config;

use std::collections::HashMap;

use config::EngineConfig;

use crate::control::ControlInput;
use crate::graph::compiler::{self, CompileError};
use crate::ir::{ConnectionIr, GraphIr, NodeInstance};
use crate::nodes::dac::{dac_type_decl, DacFactory};
use crate::nodes::oscillator::{oscillator_type_decl, OscillatorFactory};
use crate::output::MockAudioOutput;
use crate::protocol::ClientMessage;
use crate::registry::NodeRegistry;
use crate::swap::GraphSwapper;
use crate::swap::command::Command;

pub struct AudioEngine {
    config: EngineConfig,
    registry: NodeRegistry,
    swapper: GraphSwapper,
    shadow_graph: GraphIr,
    exposed_controls: HashMap<String, (String, String)>,
}

impl AudioEngine {
    #[must_use]
    pub fn new(config: EngineConfig) -> Self {
        let mut registry = NodeRegistry::new();
        // Built-in types registered into a fresh registry — cannot fail
        let _ = registry.register(oscillator_type_decl(), OscillatorFactory);
        let _ = registry.register(dac_type_decl(), DacFactory);

        let crossfade_samples = config.crossfade_samples();

        Self {
            config,
            registry,
            swapper: GraphSwapper::new(crossfade_samples),
            shadow_graph: GraphIr {
                nodes: vec![],
                connections: vec![],
                exposed_controls: HashMap::new(),
            },
            exposed_controls: HashMap::new(),
        }
    }

    /// Process a single audio block through the swapper.
    pub fn process_block(&mut self, output: &mut [f32]) {
        self.swapper.process(output);
    }

    /// Handle a client message, updating shadow graph and swapper as needed.
    ///
    /// # Errors
    /// Returns `CompileError` if a graph mutation produces an invalid graph.
    pub fn handle_message(&mut self, msg: ClientMessage) -> Result<(), CompileError> {
        match msg {
            ClientMessage::LoadGraph(ir) => {
                self.exposed_controls = ir.exposed_controls.clone();
                self.shadow_graph = ir;
                self.recompile_and_swap()?;
            }
            ClientMessage::AddNode { id, type_id, controls } => {
                self.shadow_graph.nodes.push(NodeInstance {
                    id,
                    type_id,
                    controls,
                });
                self.recompile_and_swap()?;
            }
            ClientMessage::RemoveNode { id } => {
                self.shadow_graph.nodes.retain(|n| n.id != id);
                self.shadow_graph
                    .connections
                    .retain(|c| c.from_node != id && c.to_node != id);
                self.recompile_and_swap()?;
            }
            ClientMessage::Connect {
                from_node,
                from_port,
                to_node,
                to_port,
            } => {
                self.shadow_graph.connections.push(ConnectionIr {
                    from_node,
                    from_port,
                    to_node,
                    to_port,
                });
                self.recompile_and_swap()?;
            }
            ClientMessage::Disconnect {
                from_node,
                from_port,
                to_node,
                to_port,
            } => {
                self.shadow_graph.connections.retain(|c| {
                    !(c.from_node == from_node
                        && c.from_port == from_port
                        && c.to_node == to_node
                        && c.to_port == to_port)
                });
                self.recompile_and_swap()?;
            }
            ClientMessage::ExposeControl {
                label,
                node_id,
                control_name,
            } => {
                self.exposed_controls
                    .insert(label, (node_id, control_name));
            }
            ClientMessage::SetControl { label, value } => {
                if let Some((node_id, control_name)) = self.exposed_controls.get(&label) {
                    self.swapper.drain_commands(std::iter::once(Command::SetParam {
                        node_id: node_id.clone(),
                        name: control_name.clone(),
                        value,
                    }));
                }
            }
            ClientMessage::SetMasterGain { gain } => {
                self.swapper
                    .drain_commands(std::iter::once(Command::SetMasterGain(gain)));
            }
            ClientMessage::RegisterNodeType(_) | ClientMessage::Ping | ClientMessage::Shutdown => {}
        }
        Ok(())
    }

    /// Process pending control messages from a control input source.
    pub fn poll_control(&mut self, control: &mut dyn ControlInput) {
        let messages = control.poll();
        for msg in messages {
            let _ = self.handle_message(msg);
        }
    }

    /// Run the engine in offline mode for testing: process blocks with a mock output.
    pub fn run_offline(&mut self, mock: &mut MockAudioOutput, num_blocks: usize) {
        let config = self.config.clone();
        // We need to process blocks through the swapper directly
        for _ in 0..num_blocks {
            let mut buf = vec![0.0_f32; config.block_size * config.channels];
            // Process mono into the first channel's worth of samples
            let mono_size = config.block_size;
            let mut mono_buf = vec![0.0_f32; mono_size];
            self.swapper.process(&mut mono_buf);

            // Duplicate mono to all channels (interleaved)
            for (i, &sample) in mono_buf.iter().enumerate() {
                for ch in 0..config.channels {
                    buf[i * config.channels + ch] = sample;
                }
            }
            mock.captured_blocks_mut().push(buf);
        }
    }

    #[must_use]
    pub const fn has_active_graph(&self) -> bool {
        self.swapper.has_active_graph()
    }

    #[must_use]
    pub const fn config(&self) -> &EngineConfig {
        &self.config
    }

    fn recompile_and_swap(&mut self) -> Result<(), CompileError> {
        let graph = compiler::compile(
            &self.shadow_graph,
            &self.registry,
            self.config.sample_rate,
            self.config.block_size,
        )?;
        self.swapper
            .drain_commands(std::iter::once(Command::SwapGraph(Box::new(graph))));
        Ok(())
    }
}

impl std::fmt::Debug for AudioEngine {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AudioEngine")
            .field("config", &self.config)
            .field("has_active_graph", &self.swapper.has_active_graph())
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::control::MockControlInput;

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
    fn engine_load_graph_and_process() {
        let config = EngineConfig {
            block_size: 64,
            ..Default::default()
        };
        let mut engine = AudioEngine::new(config);
        engine
            .handle_message(ClientMessage::LoadGraph(simple_graph_ir()))
            .unwrap();

        assert!(engine.has_active_graph());

        let mut output = vec![0.0_f32; 64];
        engine.process_block(&mut output);
        let energy: f32 = output.iter().map(|s| s * s).sum();
        assert!(energy > 0.0, "engine should produce audio");
    }

    #[test]
    fn engine_set_control_via_exposed_label() {
        let config = EngineConfig {
            block_size: 256,
            ..Default::default()
        };
        let mut engine = AudioEngine::new(config);
        engine
            .handle_message(ClientMessage::LoadGraph(simple_graph_ir()))
            .unwrap();

        let mut buf1 = vec![0.0_f32; 256];
        engine.process_block(&mut buf1);

        engine
            .handle_message(ClientMessage::SetControl {
                label: "pitch".into(),
                value: 880.0,
            })
            .unwrap();

        let mut buf2 = vec![0.0_f32; 256];
        engine.process_block(&mut buf2);

        let count_crossings = |buf: &[f32]| -> usize {
            buf.windows(2)
                .filter(|w| w[0] <= 0.0 && w[1] > 0.0)
                .count()
        };
        assert!(count_crossings(&buf2) > count_crossings(&buf1));
    }

    #[test]
    fn engine_poll_control_input() {
        let config = EngineConfig {
            block_size: 64,
            ..Default::default()
        };
        let mut engine = AudioEngine::new(config);
        let mut ctrl = MockControlInput::new();
        ctrl.send(ClientMessage::LoadGraph(simple_graph_ir()));

        engine.poll_control(&mut ctrl);
        assert!(engine.has_active_graph());
    }

    #[test]
    fn engine_offline_produces_audio() {
        let config = EngineConfig {
            block_size: 64,
            channels: 2,
            ..Default::default()
        };
        let mut engine = AudioEngine::new(config);
        engine
            .handle_message(ClientMessage::LoadGraph(simple_graph_ir()))
            .unwrap();

        let mut mock = MockAudioOutput::new();
        engine.run_offline(&mut mock, 4);

        assert_eq!(mock.captured_blocks().len(), 4);
        // Each block should be block_size * channels
        assert_eq!(mock.captured_blocks()[0].len(), 64 * 2);
        // Should have non-zero audio
        let energy: f32 = mock.captured_blocks()[0].iter().map(|s| s * s).sum();
        assert!(energy > 0.0);
    }

    #[test]
    fn engine_incremental_add_node() {
        let config = EngineConfig {
            block_size: 64,
            ..Default::default()
        };
        let mut engine = AudioEngine::new(config);

        // Start with just a dac
        let ir = GraphIr {
            nodes: vec![NodeInstance {
                id: "out".into(),
                type_id: "dac".into(),
                controls: HashMap::new(),
            }],
            connections: vec![],
            exposed_controls: HashMap::new(),
        };
        engine
            .handle_message(ClientMessage::LoadGraph(ir))
            .unwrap();

        // Add an oscillator
        engine
            .handle_message(ClientMessage::AddNode {
                id: "osc1".into(),
                type_id: "oscillator".into(),
                controls: HashMap::from([("freq".into(), 440.0)]),
            })
            .unwrap();

        // Connect it
        engine
            .handle_message(ClientMessage::Connect {
                from_node: "osc1".into(),
                from_port: "out".into(),
                to_node: "out".into(),
                to_port: "in".into(),
            })
            .unwrap();

        let mut output = vec![0.0_f32; 64];
        engine.process_block(&mut output);
        let energy: f32 = output.iter().map(|s| s * s).sum();
        assert!(energy > 0.0, "incrementally built graph should produce audio");
    }
}
