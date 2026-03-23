use crate::graph::node::{DspNode, ParamError};
use crate::ir::types::{ChannelLayout, ControlDecl, NodeTypeDecl, PortDecl, Rate};
use crate::registry::NodeFactory;

/// Scales its mono input by a `gain` parameter with audio-rate smoothing.
/// Eliminates clicks on gain changes by exponentially ramping to the target.
#[derive(Debug)]
pub struct GainNode {
    current: f32,
    target: f32,
    /// Smoothing coefficient per sample. ~0.02 gives ~5ms ramp at 44100Hz.
    coeff: f32,
    /// True until the first process() call. set_param snaps current=target
    /// before audio starts, so initial controls don't cause a ramp from 1.0.
    virgin: bool,
}

/// Smoothing coefficient: controls how fast gain ramps to target.
/// Higher = faster (less smooth). 0.02 ≈ 5ms settling at 44100Hz.
const SMOOTH_COEFF: f32 = 0.02;

impl GainNode {
    #[must_use]
    pub fn new() -> Self {
        Self {
            current: 1.0,
            target: 1.0,
            coeff: SMOOTH_COEFF,
            virgin: true,
        }
    }
}

impl Default for GainNode {
    fn default() -> Self {
        Self::new()
    }
}

impl DspNode for GainNode {
    fn process(&mut self, inputs: &[&[f32]], outputs: &mut [&mut [f32]]) {
        self.virgin = false;
        if let (Some(inp), Some(out)) = (inputs.first(), outputs.first_mut()) {
            let len = inp.len().min(out.len());
            for (o, i) in out[..len].iter_mut().zip(&inp[..len]) {
                self.current += (self.target - self.current) * self.coeff;
                *o = i * self.current;
            }
        }
    }

    fn num_inputs(&self) -> usize {
        1
    }
    fn num_outputs(&self) -> usize {
        1
    }

    fn set_param(&mut self, name: &str, value: f32) -> Result<(), ParamError> {
        match name {
            "gain" => {
                self.target = value;
                if self.virgin {
                    self.current = value;
                }
                Ok(())
            }
            _ => Err(ParamError::NotFound(name.into())),
        }
    }

    fn reset(&mut self, _sample_rate: u32) {}
}

#[derive(Debug)]
pub struct GainFactory;

impl NodeFactory for GainFactory {
    fn create(&self, _sample_rate: u32, _block_size: usize) -> Result<Box<dyn DspNode>, String> {
        Ok(Box::new(GainNode::new()))
    }
}

#[must_use]
pub fn gain_type_decl() -> NodeTypeDecl {
    NodeTypeDecl {
        type_id: "gain".into(),
        audio_inputs: vec![PortDecl {
            name: "in".into(),
            channels: ChannelLayout::Mono,
        }],
        audio_outputs: vec![PortDecl {
            name: "out".into(),
            channels: ChannelLayout::Mono,
        }],
        controls: vec![ControlDecl {
            name: "gain".into(),
            range: (0.0, 4.0),
            default: 1.0,
            rate: Rate::Control,
            unit: None,
        }],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gain_converges_to_target() {
        let mut node = GainNode::new();
        node.set_param("gain", 0.5).unwrap();

        // Process enough samples for smoothing to converge
        let input = [1.0_f32; 512];
        let mut output = [0.0_f32; 512];
        node.process(&[&input], &mut [&mut output]);

        // After 512 samples, should be very close to 0.5
        assert!(
            (output[511] - 0.5).abs() < 0.01,
            "should converge to 0.5, got {}",
            output[511]
        );
    }

    #[test]
    fn gain_one_is_passthrough() {
        // Default gain=1, target=1 → current starts at 1 → exact passthrough
        let mut node = GainNode::new();
        let input = [0.3_f32, -0.7, 1.0, 0.0];
        let mut output = [0.0_f32; 4];
        node.process(&[&input], &mut [&mut output]);
        for (i, o) in input.iter().zip(output.iter()) {
            assert!((i - o).abs() < 0.01);
        }
    }

    #[test]
    fn gain_zero_converges_to_silence() {
        let mut node = GainNode::new();
        node.set_param("gain", 0.0).unwrap();

        let input = [1.0_f32; 512];
        let mut output = [0.0_f32; 512];
        node.process(&[&input], &mut [&mut output]);

        // Last sample should be very close to 0
        assert!(
            output[511].abs() < 0.001,
            "should converge to 0, got {}",
            output[511]
        );
    }

    #[test]
    fn gain_rejects_unknown_param() {
        let mut node = GainNode::new();
        assert!(matches!(
            node.set_param("freq", 440.0),
            Err(ParamError::NotFound(_))
        ));
    }

    #[test]
    fn type_decl_matches_implementation() {
        let decl = gain_type_decl();
        let factory = GainFactory;
        let node = factory.create(48000, 512).unwrap();
        assert_eq!(decl.type_id, "gain");
        assert_eq!(decl.audio_inputs.len(), node.num_inputs());
        assert_eq!(decl.audio_outputs.len(), node.num_outputs());
        assert_eq!(decl.controls.len(), 1);
        assert_eq!(decl.controls[0].name, "gain");
    }

    #[test]
    fn gain_change_ramps_smoothly() {
        // Set gain=1 → process → set gain=0 → process.
        // The output should NOT drop to 0 instantly — it should ramp.
        let mut node = GainNode::new();
        node.set_param("gain", 1.0).unwrap();

        let input = [1.0_f32; 256];
        let mut output = [0.0_f32; 256];
        node.process(&[&input], &mut [&mut output]);

        // Now jump to gain=0
        node.set_param("gain", 0.0).unwrap();
        let mut output2 = [0.0_f32; 256];
        node.process(&[&input], &mut [&mut output2]);

        // First sample should NOT be 0 — it should be close to 1 (smoothed)
        assert!(
            output2[0] > 0.5,
            "first sample should still be near 1.0, got {}",
            output2[0]
        );
        // Last sample should be near 0 (converged)
        assert!(
            output2[255] < 0.01,
            "last sample should be near 0, got {}",
            output2[255]
        );

        // No large sample-to-sample jump
        let max_jump = output2
            .windows(2)
            .map(|w| (w[1] - w[0]).abs())
            .fold(0.0_f32, f32::max);
        assert!(
            max_jump < 0.05,
            "max sample-to-sample jump {max_jump} should be small"
        );
    }

    #[test]
    fn fresh_gain_snaps_to_initial_value() {
        // A fresh GainNode with set_param("gain", 0.5) before any process()
        // should start at 0.5 immediately — no ramp from 1.0.
        let mut node = GainNode::new();
        node.set_param("gain", 0.5).unwrap();

        let input = [1.0_f32; 4];
        let mut output = [0.0_f32; 4];
        node.process(&[&input], &mut [&mut output]);

        // First sample should be at (or very near) 0.5, not ramping from 1.0
        assert!(
            (output[0] - 0.5).abs() < 0.02,
            "fresh gain node should snap to initial value, got {}",
            output[0]
        );
    }

    #[test]
    fn gain_still_ramps_after_first_process() {
        // After processing at least one block, set_param should ramp (not snap).
        let mut node = GainNode::new();
        let input = [1.0_f32; 64];
        let mut output = [0.0_f32; 64];
        node.process(&[&input], &mut [&mut output]);

        // Now change gain — should ramp, not snap
        node.set_param("gain", 0.0).unwrap();
        let mut output2 = [0.0_f32; 4];
        node.process(&[&input[..4]], &mut [&mut output2]);

        // First sample should still be near 1.0 (ramping), not snapped to 0
        assert!(
            output2[0] > 0.5,
            "after first process, gain should ramp not snap, got {}",
            output2[0]
        );
    }
}
