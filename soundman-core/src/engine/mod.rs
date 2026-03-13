pub mod config;

use std::collections::HashMap;

use log::{debug, warn};
use rtrb::{Consumer, Producer, RingBuffer};

use config::EngineConfig;

use crate::control::ControlInput;
use crate::graph::compiler::{self, CompileError};
use crate::ir::{ConnectionIr, GraphIr, NodeInstance};
use crate::nodes::dac::{dac_type_decl, DacFactory};
use crate::nodes::oscillator::{oscillator_type_decl, OscillatorFactory};
use crate::protocol::ClientMessage;
use crate::registry::NodeRegistry;
use crate::swap::GraphSwapper;
use crate::swap::command::Command;

const COMMAND_QUEUE_CAPACITY: usize = 256;

/// Control-thread side: handles client messages, compiles graphs, sends commands.
pub struct EngineController {
    config: EngineConfig,
    registry: NodeRegistry,
    shadow_graph: GraphIr,
    exposed_controls: HashMap<String, (String, String)>,
    producer: Producer<Command>,
}

/// Audio-thread side: drains commands, processes audio. No locks, no allocation.
pub struct AudioProcessor {
    swapper: GraphSwapper,
    consumer: Consumer<Command>,
}

/// Create a paired controller + processor connected by a lock-free command channel.
#[must_use]
pub fn engine(config: &EngineConfig) -> (EngineController, AudioProcessor) {
    let mut registry = NodeRegistry::new();
    let _ = registry.register(oscillator_type_decl(), OscillatorFactory);
    let _ = registry.register(dac_type_decl(), DacFactory);

    let crossfade_samples = config.crossfade_samples();
    let block_size = config.block_size;

    let (producer, consumer) = RingBuffer::new(COMMAND_QUEUE_CAPACITY);

    let controller = EngineController {
        config: config.clone(),
        registry,
        shadow_graph: GraphIr {
            nodes: vec![],
            connections: vec![],
            exposed_controls: HashMap::new(),
        },
        exposed_controls: HashMap::new(),
        producer,
    };

    let processor = AudioProcessor {
        swapper: GraphSwapper::new(crossfade_samples, block_size),
        consumer,
    };

    (controller, processor)
}

impl EngineController {
    /// Handle a client message, updating shadow graph and sending commands.
    ///
    /// # Errors
    /// Returns `CompileError` if a graph mutation produces an invalid graph.
    pub fn handle_message(&mut self, msg: ClientMessage) -> Result<(), CompileError> {
        match msg {
            ClientMessage::LoadGraph(ir) => {
                debug!("load_graph: {} nodes, {} connections", ir.nodes.len(), ir.connections.len());
                self.exposed_controls = ir.exposed_controls.clone();
                self.shadow_graph = ir;
                self.recompile_and_send()?;
                debug!("graph compiled and queued for swap");
            }
            ClientMessage::AddNode { id, type_id, controls } => {
                debug!("add_node: id={id}, type={type_id}, controls={controls:?}");
                self.shadow_graph.nodes.push(NodeInstance {
                    id,
                    type_id,
                    controls,
                });
                self.recompile_and_send()?;
            }
            ClientMessage::RemoveNode { id } => {
                debug!("remove_node: {id}");
                self.shadow_graph.nodes.retain(|n| n.id != id);
                self.shadow_graph
                    .connections
                    .retain(|c| c.from_node != id && c.to_node != id);
                self.recompile_and_send()?;
            }
            ClientMessage::Connect {
                from_node,
                from_port,
                to_node,
                to_port,
            } => {
                debug!("connect: {from_node}:{from_port} -> {to_node}:{to_port}");
                self.shadow_graph.connections.push(ConnectionIr {
                    from_node,
                    from_port,
                    to_node,
                    to_port,
                });
                self.recompile_and_send()?;
            }
            ClientMessage::Disconnect {
                from_node,
                from_port,
                to_node,
                to_port,
            } => {
                debug!("disconnect: {from_node}:{from_port} -> {to_node}:{to_port}");
                self.shadow_graph.connections.retain(|c| {
                    !(c.from_node == from_node
                        && c.from_port == from_port
                        && c.to_node == to_node
                        && c.to_port == to_port)
                });
                self.recompile_and_send()?;
            }
            ClientMessage::ExposeControl {
                label,
                node_id,
                control_name,
            } => {
                debug!("expose_control: {label} -> {node_id}:{control_name}");
                self.exposed_controls
                    .insert(label, (node_id, control_name));
            }
            ClientMessage::SetControl { label, value } => {
                if let Some((node_id, control_name)) = self.exposed_controls.get(&label) {
                    debug!("set_control: {label}={value} (-> {node_id}:{control_name})");
                    self.send_command(Command::SetParam {
                        node_id: node_id.clone(),
                        name: control_name.clone(),
                        value,
                    });
                } else {
                    warn!("set_control: unknown label '{label}', available: {:?}", self.exposed_controls.keys().collect::<Vec<_>>());
                }
            }
            ClientMessage::SetMasterGain { gain } => {
                debug!("set_master_gain: {gain}");
                self.send_command(Command::SetMasterGain(gain));
            }
            ClientMessage::Ping => { debug!("ping"); }
            ClientMessage::Shutdown => { debug!("shutdown"); }
            ClientMessage::RegisterNodeType(_) => {}
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

    #[must_use]
    pub const fn config(&self) -> &EngineConfig {
        &self.config
    }

    fn recompile_and_send(&mut self) -> Result<(), CompileError> {
        let graph = compiler::compile(
            &self.shadow_graph,
            &self.registry,
            self.config.sample_rate,
            self.config.block_size,
        )?;
        self.send_command(Command::SwapGraph(Box::new(graph)));
        Ok(())
    }

    fn send_command(&mut self, cmd: Command) {
        if self.producer.push(cmd).is_err() {
            warn!("command queue full, dropping command");
        }
    }
}

impl std::fmt::Debug for EngineController {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("EngineController")
            .field("config", &self.config)
            .finish_non_exhaustive()
    }
}

impl AudioProcessor {
    /// Drain pending commands and process one audio block.
    pub fn process(&mut self, output: &mut [f32]) {
        while let Ok(cmd) = self.consumer.pop() {
            self.swapper.drain_commands(std::iter::once(cmd));
        }
        self.swapper.process(output);
    }

    #[must_use]
    pub const fn has_active_graph(&self) -> bool {
        self.swapper.has_active_graph()
    }
}

impl std::fmt::Debug for AudioProcessor {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AudioProcessor")
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
    fn load_graph_and_process() {
        let config = EngineConfig {
            block_size: 64,
            ..Default::default()
        };
        let (mut ctrl, mut proc) = engine(&config);
        ctrl.handle_message(ClientMessage::LoadGraph(simple_graph_ir()))
            .unwrap();

        let mut output = vec![0.0_f32; 64];
        proc.process(&mut output);

        assert!(proc.has_active_graph());
        let energy: f32 = output.iter().map(|s| s * s).sum();
        assert!(energy > 0.0, "engine should produce audio");
    }

    #[test]
    fn set_control_via_exposed_label() {
        let config = EngineConfig {
            block_size: 256,
            ..Default::default()
        };
        let (mut ctrl, mut proc) = engine(&config);
        ctrl.handle_message(ClientMessage::LoadGraph(simple_graph_ir()))
            .unwrap();

        let mut buf1 = vec![0.0_f32; 256];
        proc.process(&mut buf1);

        ctrl.handle_message(ClientMessage::SetControl {
            label: "pitch".into(),
            value: 880.0,
        })
        .unwrap();

        let mut buf2 = vec![0.0_f32; 256];
        proc.process(&mut buf2);

        let count_crossings = |buf: &[f32]| -> usize {
            buf.windows(2)
                .filter(|w| w[0] <= 0.0 && w[1] > 0.0)
                .count()
        };
        assert!(count_crossings(&buf2) > count_crossings(&buf1));
    }

    #[test]
    fn poll_control_input() {
        let config = EngineConfig {
            block_size: 64,
            ..Default::default()
        };
        let (mut ctrl, mut proc) = engine(&config);
        let mut input = MockControlInput::new();
        input.send(ClientMessage::LoadGraph(simple_graph_ir()));

        ctrl.poll_control(&mut input);

        let mut output = vec![0.0_f32; 64];
        proc.process(&mut output);
        assert!(proc.has_active_graph());
    }

    #[test]
    fn offline_rendering() {
        let config = EngineConfig {
            block_size: 64,
            channels: 2,
            ..Default::default()
        };
        let (mut ctrl, mut proc) = engine(&config);
        ctrl.handle_message(ClientMessage::LoadGraph(simple_graph_ir()))
            .unwrap();

        let mut blocks = Vec::new();
        for _ in 0..4 {
            let mut mono = vec![0.0_f32; config.block_size];
            proc.process(&mut mono);

            // Expand mono to interleaved stereo
            let mut interleaved = vec![0.0_f32; config.block_size * config.channels];
            for (i, &sample) in mono.iter().enumerate() {
                for ch in 0..config.channels {
                    interleaved[i * config.channels + ch] = sample;
                }
            }
            blocks.push(interleaved);
        }

        assert_eq!(blocks.len(), 4);
        assert_eq!(blocks[0].len(), 64 * 2);
        let energy: f32 = blocks[0].iter().map(|s| s * s).sum();
        assert!(energy > 0.0);
    }

    #[test]
    fn incremental_add_node() {
        let config = EngineConfig {
            block_size: 64,
            ..Default::default()
        };
        let (mut ctrl, mut proc) = engine(&config);

        let ir = GraphIr {
            nodes: vec![NodeInstance {
                id: "out".into(),
                type_id: "dac".into(),
                controls: HashMap::new(),
            }],
            connections: vec![],
            exposed_controls: HashMap::new(),
        };
        ctrl.handle_message(ClientMessage::LoadGraph(ir)).unwrap();

        ctrl.handle_message(ClientMessage::AddNode {
            id: "osc1".into(),
            type_id: "oscillator".into(),
            controls: HashMap::from([("freq".into(), 440.0)]),
        })
        .unwrap();

        ctrl.handle_message(ClientMessage::Connect {
            from_node: "osc1".into(),
            from_port: "out".into(),
            to_node: "out".into(),
            to_port: "in".into(),
        })
        .unwrap();

        let mut output = vec![0.0_f32; 64];
        proc.process(&mut output);
        let energy: f32 = output.iter().map(|s| s * s).sum();
        assert!(energy > 0.0, "incrementally built graph should produce audio");
    }
}
