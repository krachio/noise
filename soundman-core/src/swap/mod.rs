//! Graph hot-swap with linear crossfade.
//!
//! [`GraphSwapper`] manages the active and retiring graphs on the audio thread.
//! When a new graph arrives, it crossfades from the old graph over a
//! configurable number of samples — no clicks, no allocation.

pub mod command;

use crate::graph::DspGraph;

use command::Command;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SwapState {
    Idle,
    Crossfading { samples_remaining: usize },
}

/// Manages graph lifecycle on the audio thread: swap, crossfade, and master gain.
///
/// All buffers are pre-allocated at construction. No heap allocation occurs
/// during [`process`](Self::process).
pub struct GraphSwapper {
    active: Option<Box<DspGraph>>,
    retiring: Option<Box<DspGraph>>,
    /// Retired graph waiting to be returned to the control thread for node reuse.
    retired_ready: Option<Box<DspGraph>>,
    state: SwapState,
    crossfade_samples: usize,
    master_gain: f32,
    fade_buf_old: Vec<f32>,
    fade_buf_new: Vec<f32>,
}

impl GraphSwapper {
    #[must_use]
    pub fn new(crossfade_samples: usize, block_size: usize) -> Self {
        Self {
            active: None,
            retiring: None,
            retired_ready: None,
            state: SwapState::Idle,
            crossfade_samples,
            master_gain: 1.0,
            fade_buf_old: vec![0.0; block_size],
            fade_buf_new: vec![0.0; block_size],
        }
    }

    pub fn drain_commands(&mut self, commands: impl Iterator<Item = Command>) {
        for cmd in commands {
            match cmd {
                Command::SwapGraph(new_graph) => self.begin_swap(new_graph),
                Command::SetParam { node_id, name, value } => {
                    if let Some(graph) = &mut self.active {
                        let _ = graph.set_param(&node_id, &name, value);
                    }
                }
                Command::SetMasterGain(gain) => self.master_gain = gain,
                Command::Shutdown => {}
            }
        }
    }

    #[allow(clippy::cast_precision_loss)]
    pub fn process(&mut self, output: &mut [f32]) {
        output.fill(0.0);

        match self.state {
            SwapState::Idle => {
                if let Some(graph) = &mut self.active {
                    graph.process(output);
                }
            }
            SwapState::Crossfading { samples_remaining } => {
                let fade_len = output.len().min(samples_remaining);
                let len = output.len();

                self.fade_buf_old[..len].fill(0.0);
                if let Some(old_graph) = &mut self.retiring {
                    old_graph.process(&mut self.fade_buf_old[..len]);
                }

                self.fade_buf_new[..len].fill(0.0);
                if let Some(new_graph) = &mut self.active {
                    new_graph.process(&mut self.fade_buf_new[..len]);
                }

                // Linear crossfade
                let total = self.crossfade_samples as f32;
                for (i, sample) in output.iter_mut().enumerate() {
                    let remaining_f = (samples_remaining as f32 - i as f32).max(0.0);
                    let fade_out = remaining_f / total;
                    let fade_in = 1.0 - fade_out;
                    *sample = self.fade_buf_old[i].mul_add(fade_out, self.fade_buf_new[i] * fade_in);
                }

                let new_remaining = samples_remaining.saturating_sub(fade_len);
                if new_remaining == 0 {
                    self.state = SwapState::Idle;
                    // Move retired graph to return slot (for node reuse + off-audio dealloc)
                    self.retired_ready = self.retiring.take();
                } else {
                    self.state = SwapState::Crossfading {
                        samples_remaining: new_remaining,
                    };
                }
            }
        }

        // Apply master gain, clamp to [-1.0, 1.0], and silence any NaN.
        // NaN can arise from unstable IIR filters at extreme cutoff frequencies.
        // Both NaN and clipping can kill the CoreAudio stream.
        for sample in output.iter_mut() {
            let s = *sample * self.master_gain;
            *sample = if s.is_finite() { s.clamp(-1.0, 1.0) } else { 0.0 };
        }
    }

    fn begin_swap(&mut self, new_graph: Box<DspGraph>) {
        if self.active.is_some() {
            self.retiring = self.active.take();
            self.active = Some(new_graph);
            self.state = SwapState::Crossfading {
                samples_remaining: self.crossfade_samples,
            };
        } else {
            self.active = Some(new_graph);
        }
    }

    #[must_use]
    pub const fn has_active_graph(&self) -> bool {
        self.active.is_some()
    }

    /// Take the retired graph (if ready) for return to the control thread.
    /// Called by AudioProcessor after process() to avoid deallocation on the audio path.
    pub fn take_retired(&mut self) -> Option<Box<DspGraph>> {
        self.retired_ready.take()
    }

    #[must_use]
    pub const fn is_crossfading(&self) -> bool {
        matches!(self.state, SwapState::Crossfading { .. })
    }
}

impl std::fmt::Debug for GraphSwapper {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("GraphSwapper")
            .field("has_active", &self.active.is_some())
            .field("has_retiring", &self.retiring.is_some())
            .field("has_retired_ready", &self.retired_ready.is_some())
            .field("state", &self.state)
            .field("crossfade_samples", &self.crossfade_samples)
            .field("master_gain", &self.master_gain)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;
    use crate::graph::compiler::compile;
    use crate::graph::{BufferPool, Connection, DspGraph};
    use crate::graph::node::{DspNode, NodeId, ParamError};
    use crate::ir::{ConnectionIr, GraphIr, NodeInstance};
    use crate::nodes::dac::{DacNode, dac_type_decl, DacFactory};
    use crate::nodes::oscillator::{oscillator_type_decl, OscillatorFactory};
    use crate::registry::NodeRegistry;

    /// Node that outputs NaN on every sample — simulates an unstable IIR filter.
    struct NanNode;

    impl DspNode for NanNode {
        fn process(&mut self, _: &[&[f32]], outputs: &mut [&mut [f32]]) {
            if let Some(out) = outputs.first_mut() { out.fill(f32::NAN); }
        }
        fn num_inputs(&self) -> usize { 0 }
        fn num_outputs(&self) -> usize { 1 }
        fn set_param(&mut self, name: &str, _: f32) -> Result<(), ParamError> {
            Err(ParamError::NotFound(name.into()))
        }
        fn reset(&mut self, _: u32) {}
    }

    fn nan_graph(block_size: usize) -> Box<DspGraph> {
        let nodes: Vec<Box<dyn DspNode>> = vec![Box::new(NanNode), Box::new(DacNode)];
        let connections = vec![Connection {
            from_node: NodeId(0), from_port: 0, to_node: NodeId(1), to_port: 0,
        }];
        let buffers = BufferPool::new(2, block_size);
        Box::new(DspGraph::new(
            nodes,
            vec!["nan".into(), "out".into()],
            vec!["nan".into(), "dac".into()],
            vec![0; 2],
            connections,
            vec![NodeId(0), NodeId(1)],
            Some(NodeId(1)),
            buffers,
            vec![vec![0], vec![1]],
        ))
    }

    fn test_registry() -> NodeRegistry {
        let mut registry = NodeRegistry::new();
        registry
            .register(oscillator_type_decl(), OscillatorFactory)
            .unwrap();
        registry.register(dac_type_decl(), DacFactory).unwrap();
        registry
    }

    fn make_graph(registry: &NodeRegistry, freq: f32, block_size: usize) -> Box<DspGraph> {
        let ir = GraphIr {
            nodes: vec![
                NodeInstance {
                    id: "osc1".into(),
                    type_id: "oscillator".into(),
                    controls: HashMap::from([("freq".into(), freq)]),
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
        Box::new(compile(&ir, registry, 48000, block_size).unwrap())
    }

    #[test]
    fn swapper_starts_silent() {
        let mut swapper = GraphSwapper::new(480, 64);
        let mut output = vec![0.0_f32; 64];
        swapper.process(&mut output);

        #[allow(clippy::float_cmp)]
        let all_zero = output.iter().all(|&s| s == 0.0);
        assert!(all_zero);
        assert!(!swapper.has_active_graph());
    }

    #[test]
    fn swap_first_graph_no_crossfade() {
        let registry = test_registry();
        let graph = make_graph(&registry, 440.0, 64);

        let mut swapper = GraphSwapper::new(480, 64);
        swapper.drain_commands(std::iter::once(Command::SwapGraph(graph)));

        assert!(swapper.has_active_graph());
        assert!(!swapper.is_crossfading());

        let mut output = vec![0.0_f32; 64];
        swapper.process(&mut output);
        let energy: f32 = output.iter().map(|s| s * s).sum();
        assert!(energy > 0.0, "should produce audio after first graph load");
    }

    #[test]
    fn swap_triggers_crossfade() {
        let registry = test_registry();
        let block_size = 64;
        let crossfade_samples = 128; // 2 blocks

        let graph1 = make_graph(&registry, 440.0, block_size);
        let graph2 = make_graph(&registry, 880.0, block_size);

        let mut swapper = GraphSwapper::new(crossfade_samples, block_size);
        swapper.drain_commands(std::iter::once(Command::SwapGraph(graph1)));

        let mut buf = vec![0.0_f32; block_size];
        swapper.process(&mut buf);

        swapper.drain_commands(std::iter::once(Command::SwapGraph(graph2)));
        assert!(swapper.is_crossfading());

        swapper.process(&mut buf);
        assert!(swapper.is_crossfading(), "should still be crossfading after 1 block");

        swapper.process(&mut buf);
        assert!(!swapper.is_crossfading(), "should finish crossfade after 2 blocks");
    }

    #[test]
    fn crossfade_no_discontinuity() {
        let registry = test_registry();
        let block_size = 64;
        let crossfade_samples = 256;

        let graph1 = make_graph(&registry, 440.0, block_size);
        let graph2 = make_graph(&registry, 440.0, block_size);

        let mut swapper = GraphSwapper::new(crossfade_samples, block_size);
        swapper.drain_commands(std::iter::once(Command::SwapGraph(graph1)));

        let mut buf = vec![0.0_f32; block_size];
        for _ in 0..4 {
            swapper.process(&mut buf);
        }
        let last_sample_before = *buf.last().unwrap();

        swapper.drain_commands(std::iter::once(Command::SwapGraph(graph2)));
        swapper.process(&mut buf);
        let first_sample_after = buf[0];

        let jump = (first_sample_after - last_sample_before).abs();
        assert!(
            jump < 0.5,
            "discontinuity too large: {jump} (before={last_sample_before}, after={first_sample_after})"
        );
    }

    #[test]
    fn master_gain_applies() {
        let registry = test_registry();
        let block_size = 64;

        let graph = make_graph(&registry, 440.0, block_size);
        let mut swapper = GraphSwapper::new(480, block_size);
        swapper.drain_commands(
            [Command::SwapGraph(graph), Command::SetMasterGain(0.5)]
                .into_iter(),
        );

        let mut output = vec![0.0_f32; block_size];
        swapper.process(&mut output);

        for &s in &output {
            assert!(
                (-0.51..=0.51).contains(&s),
                "sample {s} exceeds master gain bound"
            );
        }
    }

    #[test]
    fn output_always_clamped_to_unit_range() {
        // A gain > 1.0 would push a sine oscillator (peak ±1.0) beyond ±1.0.
        // The output must be clamped regardless of gain to protect the audio device.
        let registry = test_registry();
        let block_size = 64;

        let graph = make_graph(&registry, 440.0, block_size);
        let mut swapper = GraphSwapper::new(480, block_size);
        swapper.drain_commands(
            [Command::SwapGraph(graph), Command::SetMasterGain(5.0)]
                .into_iter(),
        );

        let mut output = vec![0.0_f32; block_size];
        swapper.process(&mut output);

        let has_audio = output.iter().any(|&s| s != 0.0);
        assert!(has_audio, "should produce audio");

        for &s in &output {
            assert!(
                (-1.0..=1.0).contains(&s),
                "sample {s} exceeds unit range after high-gain processing"
            );
        }
    }

    #[test]
    fn nan_from_dsp_produces_silence_not_nan() {
        // IIR filters at extreme cutoffs can produce NaN. It must not reach the
        // audio device — NaN samples should be replaced with silence (0.0).
        let block_size = 64;
        let mut swapper = GraphSwapper::new(0, block_size);
        swapper.drain_commands(std::iter::once(Command::SwapGraph(nan_graph(block_size))));

        let mut output = vec![0.0_f32; block_size];
        swapper.process(&mut output);

        for &s in &output {
            assert!(s.is_finite(), "NaN from DSP must not reach output");
            assert_eq!(s, 0.0, "NaN from DSP should be silenced");
        }
    }

    #[test]
    fn set_param_forwarded_to_active_graph() {
        let registry = test_registry();
        let block_size = 256;

        let graph = make_graph(&registry, 440.0, block_size);
        let mut swapper = GraphSwapper::new(480, block_size);
        swapper.drain_commands(std::iter::once(Command::SwapGraph(graph)));

        let mut buf1 = vec![0.0_f32; block_size];
        swapper.process(&mut buf1);

        swapper.drain_commands(std::iter::once(Command::SetParam {
            node_id: "osc1".into(),
            name: "freq".into(),
            value: 880.0,
        }));

        let mut buf2 = vec![0.0_f32; block_size];
        swapper.process(&mut buf2);

        let count_crossings = |buf: &[f32]| -> usize {
            buf.windows(2)
                .filter(|w| w[0] <= 0.0 && w[1] > 0.0)
                .count()
        };
        assert!(
            count_crossings(&buf2) > count_crossings(&buf1),
            "880 Hz should have more crossings than 440 Hz"
        );
    }
}
