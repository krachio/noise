use crate::graph::node::{DspNode, ParamError};
use crate::ir::types::{ChannelLayout, ControlDecl, NodeTypeDecl, PortDecl, Rate};
use crate::registry::NodeFactory;

/// Scales its mono input by a `gain` parameter. Use this to set per-voice
/// levels before mixing into the DAC, avoiding clipping from loud fan-in sums.
#[derive(Debug)]
pub struct GainNode {
    gain: f32,
}

impl GainNode {
    #[must_use]
    pub fn new() -> Self {
        Self { gain: 1.0 }
    }
}

impl Default for GainNode {
    fn default() -> Self {
        Self::new()
    }
}

impl DspNode for GainNode {
    fn process(&mut self, inputs: &[&[f32]], outputs: &mut [&mut [f32]]) {
        if let (Some(inp), Some(out)) = (inputs.first(), outputs.first_mut()) {
            let len = inp.len().min(out.len());
            for (o, i) in out[..len].iter_mut().zip(&inp[..len]) {
                *o = i * self.gain;
            }
        }
    }

    fn num_inputs(&self) -> usize { 1 }
    fn num_outputs(&self) -> usize { 1 }

    fn set_param(&mut self, name: &str, value: f32) -> Result<(), ParamError> {
        match name {
            "gain" => { self.gain = value; Ok(()) }
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
        audio_inputs: vec![PortDecl { name: "in".into(), channels: ChannelLayout::Mono }],
        audio_outputs: vec![PortDecl { name: "out".into(), channels: ChannelLayout::Mono }],
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
    fn gain_scales_input() {
        let mut node = GainNode::new();
        node.set_param("gain", 0.5).unwrap();

        let input = [1.0_f32, -1.0, 0.5, -0.5];
        let mut output = [0.0_f32; 4];
        node.process(&[&input], &mut [&mut output]);

        assert!((output[0] - 0.5).abs() < f32::EPSILON);
        assert!((output[1] + 0.5).abs() < f32::EPSILON);
    }

    #[test]
    fn gain_one_is_passthrough() {
        let mut node = GainNode::new();
        let input = [0.3_f32, -0.7, 1.0, 0.0];
        let mut output = [0.0_f32; 4];
        node.process(&[&input], &mut [&mut output]);
        for (i, o) in input.iter().zip(output.iter()) {
            assert!((i - o).abs() < f32::EPSILON);
        }
    }

    #[test]
    fn gain_zero_silences() {
        let mut node = GainNode::new();
        node.set_param("gain", 0.0).unwrap();
        let input = [1.0_f32, -1.0, 0.5];
        let mut output = [0.0_f32; 3];
        node.process(&[&input], &mut [&mut output]);
        assert!(output.iter().all(|&s| s == 0.0));
    }

    #[test]
    fn gain_rejects_unknown_param() {
        let mut node = GainNode::new();
        assert!(matches!(node.set_param("freq", 440.0), Err(ParamError::NotFound(_))));
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
}
