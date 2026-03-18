//! Real-time audio engine with graph-based DSP routing.
//!
//! soundman processes audio through a directed acyclic graph of [`DspNode`]s.
//! Graphs are described as JSON IR ([`GraphIr`]), compiled into a runnable
//! [`DspGraph`], and hot-swapped with crossfade — all without blocking the
//! audio thread.
//!
//! # Architecture
//!
//! ```text
//! EngineController ──rtrb──▶ AudioProcessor ──▶ audio output
//!       │                          │
//!  shadow graph              GraphSwapper
//!  + compiler               (linear crossfade)
//!       │                          │
//!  NodeRegistry               DspGraph
//!  (pluggable)             (topo-sorted DAG)
//! ```
//!
//! The engine is split into two halves connected by a lock-free SPSC channel:
//!
//! - [`EngineController`] lives on the control thread. It receives
//!   [`ClientMessage`]s, maintains a shadow copy of the graph IR, compiles
//!   new graphs, and sends [`Command`]s to the audio side.
//! - [`AudioProcessor`] lives on the audio thread. It drains commands and
//!   calls [`GraphSwapper::process`] each block. No locks, no allocation.
//!
//! # Quick start
//!
//! ```no_run
//! use soundman::engine::{self, config::EngineConfig};
//! use soundman::protocol::ClientMessage;
//! use soundman::ir::{GraphIr, NodeInstance, ConnectionIr};
//! use std::collections::HashMap;
//!
//! let config = EngineConfig::default();
//! let (mut ctrl, mut proc) = engine::engine(&config);
//!
//! let graph = GraphIr {
//!     nodes: vec![
//!         NodeInstance { id: "osc1".into(), type_id: "oscillator".into(),
//!                        controls: HashMap::from([("freq".into(), 440.0)]) },
//!         NodeInstance { id: "out".into(), type_id: "dac".into(),
//!                        controls: HashMap::new() },
//!     ],
//!     connections: vec![ConnectionIr {
//!         from_node: "osc1".into(), from_port: "out".into(),
//!         to_node: "out".into(), to_port: "in".into(),
//!     }],
//!     exposed_controls: HashMap::from([("pitch".into(), ("osc1".into(), "freq".into()))]),
//! };
//!
//! ctrl.handle_message(ClientMessage::LoadGraph(graph)).unwrap();
//!
//! let mut buf = vec![0.0_f32; config.block_size];
//! proc.process(&mut buf);
//! // buf now contains one block of 440 Hz sine
//! ```
//!
//! # Custom node types
//!
//! soundman is DSP-agnostic — register your own node types via the
//! [`NodeRegistry`]. Each type needs a [`NodeTypeDecl`] (port/control
//! metadata) and a [`NodeFactory`] (instantiation).
//!
//! ```no_run
//! use soundman::engine::{self, config::EngineConfig};
//! use soundman::graph::node::{DspNode, ParamError};
//! use soundman::ir::types::{NodeTypeDecl, PortDecl, ChannelLayout};
//! use soundman::registry::{NodeFactory, NodeRegistry};
//!
//! struct MyNode;
//! impl DspNode for MyNode {
//!     fn process(&mut self, inputs: &[&[f32]], outputs: &mut [&mut [f32]]) {
//!         // your DSP here
//!     }
//!     fn num_inputs(&self) -> usize { 1 }
//!     fn num_outputs(&self) -> usize { 1 }
//!     fn set_param(&mut self, name: &str, _: f32) -> Result<(), ParamError> {
//!         Err(ParamError::NotFound(name.into()))
//!     }
//!     fn reset(&mut self, _sample_rate: u32) {}
//! }
//!
//! struct MyFactory;
//! impl NodeFactory for MyFactory {
//!     fn create(&self, _sr: u32, _bs: usize) -> Result<Box<dyn DspNode>, String> {
//!         Ok(Box::new(MyNode))
//!     }
//! }
//!
//! let config = EngineConfig::default();
//! let (mut ctrl, proc) = engine::engine(&config);
//!
//! // Register
//! let decl = NodeTypeDecl {
//!     type_id: "my_node".into(),
//!     audio_inputs: vec![PortDecl { name: "in".into(), channels: ChannelLayout::Mono }],
//!     audio_outputs: vec![PortDecl { name: "out".into(), channels: ChannelLayout::Mono }],
//!     controls: vec![],
//! };
//! ctrl.registry_mut().register(decl, MyFactory).unwrap();
//!
//! // Hot-reload: swap the factory for an existing type
//! // ctrl.registry_mut().reregister(updated_decl, NewFactory).unwrap();
//! ```
//!
//! [`NodeRegistry`]: registry::NodeRegistry
//! [`NodeTypeDecl`]: ir::types::NodeTypeDecl
//! [`NodeFactory`]: registry::NodeFactory
//!
//! [`DspNode`]: graph::node::DspNode
//! [`DspGraph`]: graph::DspGraph
//! [`GraphIr`]: ir::GraphIr
//! [`EngineController`]: engine::EngineController
//! [`AudioProcessor`]: engine::AudioProcessor
//! [`ClientMessage`]: protocol::ClientMessage
//! [`Command`]: swap::command::Command
//! [`GraphSwapper::process`]: swap::GraphSwapper::process

pub mod control;
pub mod engine;
pub mod graph;
pub mod ir;
pub mod nodes;
pub mod output;
pub mod protocol;
pub mod registry;
pub mod swap;
