//! Graph hot-swap with linear crossfade.
//!
//! [`GraphSwapper`] manages the active and retiring graphs on the audio thread.
//! When a new graph arrives, it crossfades from the old graph over a
//! configurable number of samples — no clicks, no allocation.

pub mod command;

use std::collections::HashMap;

use crate::automation::Automation;
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
    automations: HashMap<String, Automation>,
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
            automations: HashMap::new(),
        }
    }

    pub fn drain_commands(&mut self, commands: impl Iterator<Item = Command>) {
        for cmd in commands {
            match cmd {
                Command::SwapGraph(new_graph) => self.begin_swap(new_graph),
                Command::SetParam { node_id, name, value } => {
                    // Audio thread: silently ignore unknown nodes/params.
                    // New voices' controls may arrive before/after the graph
                    // that contains them. The retiring graph may not have
                    // nodes that exist in the active graph.
                    if let Some(graph) = &mut self.active {
                        let _ = graph.set_param(&node_id, &name, value);
                    }
                    if let Some(graph) = &mut self.retiring {
                        let _ = graph.set_param(&node_id, &name, value);
                    }
                }
                Command::SetMasterGain(gain) => self.master_gain = gain,
                Command::SetCrossfade(samples) => self.crossfade_samples = samples,
                Command::SetAutomation { id, automation } => {
                    self.automations.insert(id, automation);
                }
                Command::ClearAutomation { id } => {
                    self.automations.remove(&id);
                }
                Command::Shutdown => {}
            }
        }
    }

    #[allow(clippy::cast_precision_loss)]
    pub fn process(&mut self, output: &mut [f32]) {
        // Clamp to pre-allocated buffer size — OS can deliver oversized buffers.
        let len = output.len().min(self.fade_buf_old.len());
        let output = &mut output[..len];

        self.tick_automations(len);
        output.fill(0.0);

        match self.state {
            SwapState::Idle => {
                if let Some(graph) = &mut self.active {
                    graph.process(output);
                }
            }
            SwapState::Crossfading { samples_remaining } => {
                let fade_len = len.min(samples_remaining);

                self.fade_buf_old[..len].fill(0.0);
                if let Some(old_graph) = &mut self.retiring {
                    old_graph.process(&mut self.fade_buf_old[..len]);
                }

                self.fade_buf_new[..len].fill(0.0);
                if let Some(new_graph) = &mut self.active {
                    new_graph.process(&mut self.fade_buf_new[..len]);
                }

                // Linear crossfade (guard: total=0 → skip blend, use new graph only)
                let total = self.crossfade_samples.max(1) as f32;
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
            // If already crossfading, move the old retiring graph to
            // retired_ready so it's not dropped on the audio thread
            // (RT-safe deallocation) and can be returned for node reuse.
            if self.retiring.is_some() {
                self.retired_ready = self.retiring.take();
            }
            self.retiring = self.active.take();
            self.active = Some(new_graph);
            self.state = SwapState::Crossfading {
                samples_remaining: self.crossfade_samples,
            };
        } else {
            self.active = Some(new_graph);
        }
    }

    fn tick_automations(&mut self, block_size: usize) {
        for auto in self.automations.values_mut() {
            if !auto.active {
                continue;
            }
            let value = auto.eval();
            if let Some(graph) = &mut self.active {
                let _ = graph.set_param(&auto.node_id, &auto.param, value);
            }
            auto.advance(block_size);
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
            .field("automations", &self.automations.len())
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

    #[test]
    fn set_param_reaches_retiring_graph_during_crossfade() {
        // During crossfade, SetParam must reach BOTH active and retiring graphs.
        // Test: set freq=880 during crossfade. The retiring graph (started at 440)
        // must change to 880. If SetParam only goes to active, the retiring graph
        // stays at 440 and the crossfade blend has mismatched frequencies.
        let registry = test_registry();
        let block_size = 256;
        let crossfade_samples = 512; // 2 blocks

        let graph1 = make_graph(&registry, 440.0, block_size);
        let graph2 = make_graph(&registry, 440.0, block_size);

        let mut swapper = GraphSwapper::new(crossfade_samples, block_size);
        swapper.drain_commands(std::iter::once(Command::SwapGraph(graph1)));

        let mut buf = vec![0.0_f32; block_size];
        swapper.process(&mut buf); // establish oscillator

        // Trigger crossfade: graph1 → retiring, graph2 → active.
        swapper.drain_commands(std::iter::once(Command::SwapGraph(graph2)));
        assert!(swapper.is_crossfading());

        // Set freq=880 during crossfade. Must affect BOTH graphs.
        swapper.drain_commands(std::iter::once(Command::SetParam {
            node_id: "osc1".into(),
            name: "freq".into(),
            value: 880.0,
        }));

        // Process during crossfade.
        swapper.process(&mut buf);
        let crossings_during: usize = buf.windows(2)
            .filter(|w| w[0] <= 0.0 && w[1] > 0.0)
            .count();

        // After crossfade completes, process at 880Hz for reference.
        swapper.process(&mut buf); // finishes crossfade
        swapper.process(&mut buf); // pure 880Hz
        let crossings_after: usize = buf.windows(2)
            .filter(|w| w[0] <= 0.0 && w[1] > 0.0)
            .count();

        // If retiring graph got the SetParam, crossings_during ≈ crossings_after
        // (both graphs at 880). If not, crossings_during is a blend of 440+880.
        // The blend would have ~fewer clear crossings due to interference.
        assert!(
            crossings_during >= crossings_after / 2,
            "retiring graph should have received SetParam during crossfade \
             (during={crossings_during}, after={crossings_after})"
        );
    }

    #[test]
    fn swap_during_crossfade_preserves_retiring_for_reuse() {
        // If begin_swap is called during an active crossfade, the old
        // retiring graph must be moved to retired_ready (not dropped on
        // the audio thread). This ensures RT-safe deallocation and
        // enables node reuse for the next compilation.
        let registry = test_registry();
        let block_size = 64;
        let crossfade_samples = 256; // 4 blocks

        let g1 = make_graph(&registry, 440.0, block_size);
        let g2 = make_graph(&registry, 880.0, block_size);
        let g3 = make_graph(&registry, 220.0, block_size);

        let mut swapper = GraphSwapper::new(crossfade_samples, block_size);

        // Load g1, process to establish it
        swapper.drain_commands(std::iter::once(Command::SwapGraph(g1)));
        let mut buf = vec![0.0_f32; block_size];
        swapper.process(&mut buf);

        // Swap to g2 — starts crossfade (g1 → retiring, g2 → active)
        swapper.drain_commands(std::iter::once(Command::SwapGraph(g2)));
        assert!(swapper.is_crossfading());
        swapper.process(&mut buf); // 1 block into crossfade

        // Swap to g3 during active crossfade — g1 should be preserved
        // in retired_ready, not dropped on the audio thread.
        swapper.drain_commands(std::iter::once(Command::SwapGraph(g3)));
        assert!(swapper.is_crossfading());

        // The old retiring graph (g1) should now be in retired_ready.
        let retired = swapper.take_retired();
        assert!(retired.is_some(), "old retiring graph must be preserved in retired_ready");
    }

    // ---- Automation integration tests ----

    use crate::automation::{AutoShape, Automation};
    use crate::nodes::gain::{gain_type_decl, GainFactory};

    fn gain_registry() -> NodeRegistry {
        let mut registry = NodeRegistry::new();
        registry
            .register(oscillator_type_decl(), OscillatorFactory)
            .unwrap();
        registry.register(dac_type_decl(), DacFactory).unwrap();
        registry
            .register(gain_type_decl(), GainFactory)
            .unwrap();
        registry
    }

    fn make_gain_graph(registry: &NodeRegistry, freq: f32, gain: f32, block_size: usize) -> Box<DspGraph> {
        let ir = GraphIr {
            nodes: vec![
                NodeInstance {
                    id: "osc1".into(),
                    type_id: "oscillator".into(),
                    controls: HashMap::from([("freq".into(), freq)]),
                },
                NodeInstance {
                    id: "gain1".into(),
                    type_id: "gain".into(),
                    controls: HashMap::from([("gain".into(), gain)]),
                },
                NodeInstance {
                    id: "out".into(),
                    type_id: "dac".into(),
                    controls: HashMap::new(),
                },
            ],
            connections: vec![
                ConnectionIr {
                    from_node: "osc1".into(),
                    from_port: "out".into(),
                    to_node: "gain1".into(),
                    to_port: "in".into(),
                },
                ConnectionIr {
                    from_node: "gain1".into(),
                    from_port: "out".into(),
                    to_node: "out".into(),
                    to_port: "in".into(),
                },
            ],
            exposed_controls: HashMap::new(),
        };
        Box::new(compile(&ir, registry, 48000, block_size).unwrap())
    }

    #[test]
    fn test_automation_modulates_gain() {
        let registry = gain_registry();
        let block_size = 256;
        let graph = make_gain_graph(&registry, 440.0, 0.0, block_size);

        let mut swapper = GraphSwapper::new(0, block_size);
        swapper.drain_commands(std::iter::once(Command::SwapGraph(graph)));

        // Process one block at gain=0 to establish baseline
        let mut buf_silent = vec![0.0_f32; block_size];
        swapper.process(&mut buf_silent);
        let energy_silent: f32 = buf_silent.iter().map(|s| s * s).sum();

        // Add a Ramp automation: gain goes from 0.0 to 1.0 over period_samples
        let auto = Automation {
            node_id: "gain1".into(),
            param: "gain".into(),
            shape: AutoShape::Ramp,
            lo: 0.5,
            hi: 1.0,
            period_samples: block_size * 4,
            phase: 0,
            active: true,
            one_shot: false,
        };
        swapper.drain_commands(std::iter::once(Command::SetAutomation {
            id: "gain_auto".into(),
            automation: auto,
        }));

        // Process several blocks — automation should increase gain
        let mut buf_auto = vec![0.0_f32; block_size];
        for _ in 0..4 {
            swapper.process(&mut buf_auto);
        }
        let energy_auto: f32 = buf_auto.iter().map(|s| s * s).sum();

        assert!(
            energy_auto > energy_silent + 0.001,
            "automation should modulate gain upward (silent={energy_silent}, auto={energy_auto})"
        );
    }

    #[test]
    fn test_automation_one_shot_holds_at_target() {
        let registry = gain_registry();
        let block_size = 64;
        let period = block_size * 2; // 2 blocks to complete

        let graph = make_gain_graph(&registry, 440.0, 0.0, block_size);
        let mut swapper = GraphSwapper::new(0, block_size);
        swapper.drain_commands(std::iter::once(Command::SwapGraph(graph)));

        let auto = Automation {
            node_id: "gain1".into(),
            param: "gain".into(),
            shape: AutoShape::Ramp,
            lo: 0.0,
            hi: 1.0,
            period_samples: period,
            phase: 0,
            active: true,
            one_shot: true,
        };
        swapper.drain_commands(std::iter::once(Command::SetAutomation {
            id: "a1".into(),
            automation: auto,
        }));

        // Process past the one-shot period
        let mut buf = vec![0.0_f32; block_size];
        for _ in 0..4 {
            swapper.process(&mut buf);
        }

        // The automation should have deactivated
        let auto_ref = swapper.automations.get("a1").unwrap();
        assert!(!auto_ref.active, "one-shot should deactivate after period");
    }

    #[test]
    fn test_automation_replaces_existing() {
        let registry = gain_registry();
        let block_size = 64;
        let graph = make_gain_graph(&registry, 440.0, 1.0, block_size);

        let mut swapper = GraphSwapper::new(0, block_size);
        swapper.drain_commands(std::iter::once(Command::SwapGraph(graph)));

        let auto1 = Automation {
            node_id: "gain1".into(),
            param: "gain".into(),
            shape: AutoShape::Sine,
            lo: 0.0,
            hi: 1.0,
            period_samples: 1000,
            phase: 0,
            active: true,
            one_shot: false,
        };
        swapper.drain_commands(std::iter::once(Command::SetAutomation {
            id: "a1".into(),
            automation: auto1,
        }));
        assert_eq!(swapper.automations.len(), 1);

        // Replace with a different shape
        let auto2 = Automation {
            node_id: "gain1".into(),
            param: "gain".into(),
            shape: AutoShape::Ramp,
            lo: 0.2,
            hi: 0.8,
            period_samples: 2000,
            phase: 0,
            active: true,
            one_shot: false,
        };
        swapper.drain_commands(std::iter::once(Command::SetAutomation {
            id: "a1".into(),
            automation: auto2,
        }));

        assert_eq!(swapper.automations.len(), 1, "same id should replace, not add");
        let a = swapper.automations.get("a1").unwrap();
        assert!((a.lo - 0.2).abs() < 1e-5, "should have the second automation's lo");
    }

    #[test]
    fn test_clear_automation() {
        let mut swapper = GraphSwapper::new(0, 64);

        let auto = Automation {
            node_id: "n".into(),
            param: "p".into(),
            shape: AutoShape::Sine,
            lo: 0.0,
            hi: 1.0,
            period_samples: 1000,
            phase: 0,
            active: true,
            one_shot: false,
        };
        swapper.drain_commands(
            [
                Command::SetAutomation { id: "a1".into(), automation: auto },
            ]
            .into_iter(),
        );
        assert_eq!(swapper.automations.len(), 1);

        swapper.drain_commands(std::iter::once(Command::ClearAutomation {
            id: "a1".into(),
        }));
        assert_eq!(swapper.automations.len(), 0, "clear should remove the automation");
    }
}
