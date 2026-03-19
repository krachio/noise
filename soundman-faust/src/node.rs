//! `FaustNode` — adapts a `FaustDsp` instance to soundman's `DspNode` trait.

use soundman_core::graph::node::{DspNode, ParamError};

use crate::dsp::FaustDsp;

/// A soundman graph node backed by a FAUST LLVM JIT compiled DSP.
pub struct FaustNode {
    dsp: FaustDsp,
}

impl FaustNode {
    /// Wrap a compiled [`FaustDsp`] as a soundman graph node.
    #[must_use]
    pub const fn new(dsp: FaustDsp) -> Self {
        Self { dsp }
    }
}

impl DspNode for FaustNode {
    fn process(&mut self, inputs: &[&[f32]], outputs: &mut [&mut [f32]]) {
        // Delegate directly — FaustDsp::compute handles channel mapping
        self.dsp.compute(inputs, outputs);
    }

    fn num_inputs(&self) -> usize {
        self.dsp.num_inputs()
    }

    fn num_outputs(&self) -> usize {
        self.dsp.num_outputs()
    }

    fn set_param(&mut self, name: &str, value: f32) -> Result<(), ParamError> {
        if self.dsp.set_param(name, value) {
            Ok(())
        } else {
            Err(ParamError::NotFound(name.into()))
        }
    }

    fn reset(&mut self, sample_rate: u32) {
        self.dsp.reset(sample_rate);
    }
}

impl std::fmt::Debug for FaustNode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("FaustNode")
            .field("dsp", &self.dsp)
            .finish_non_exhaustive()
    }
}
