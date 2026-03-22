use crate::graph::node::{DspNode, ParamError};
use crate::ir::types::{ChannelLayout, NodeTypeDecl, PortDecl};
use crate::registry::NodeFactory;

/// Terminal output node — copies its input to the graph's output buffer.
///
/// One mono input, one mono output, no parameters. Every graph that
/// produces audible output needs a `"dac"` node as the final sink.
#[derive(Debug)]
pub struct DacNode;

impl DspNode for DacNode {
    fn process(&mut self, inputs: &[&[f32]], outputs: &mut [&mut [f32]]) {
        if let (Some(inp), Some(out)) = (inputs.first(), outputs.first_mut()) {
            let len = inp.len().min(out.len());
            out[..len].copy_from_slice(&inp[..len]);
        }
    }

    fn num_inputs(&self) -> usize { 1 }
    fn num_outputs(&self) -> usize { 1 }

    fn set_param(&mut self, name: &str, _value: f32) -> Result<(), ParamError> {
        Err(ParamError::NotFound(name.into()))
    }

    fn reset(&mut self, _sample_rate: u32) {}
}

#[derive(Debug)]
pub struct DacFactory;

impl NodeFactory for DacFactory {
    fn create(&self, _sample_rate: u32, _block_size: usize) -> Result<Box<dyn DspNode>, String> {
        Ok(Box::new(DacNode))
    }
}

/// Returns the [`NodeTypeDecl`] for the built-in `"dac"` type.
#[must_use]
pub fn dac_type_decl() -> NodeTypeDecl {
    NodeTypeDecl {
        type_id: "dac".into(),
        audio_inputs: vec![PortDecl {
            name: "in".into(),
            channels: ChannelLayout::Mono,
        }],
        audio_outputs: vec![PortDecl {
            name: "out".into(),
            channels: ChannelLayout::Mono,
        }],
        controls: vec![],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dac_passes_input_to_output() {
        let mut dac = DacNode;
        let input = [0.5_f32, -0.3, 1.0, 0.0];
        let mut output = [0.0_f32; 4];

        dac.process(&[&input], &mut [&mut output]);

        #[allow(clippy::float_cmp)]
        let matches = output == input;
        assert!(matches, "DAC should pass input to output unchanged");
    }

    #[test]
    fn dac_handles_empty_io() {
        let mut dac = DacNode;
        // No inputs, no outputs — should not panic
        dac.process(&[], &mut []);
    }

    #[test]
    fn dac_handles_mismatched_lengths() {
        let mut dac = DacNode;
        let input = [1.0_f32, 2.0];
        let mut output = [0.0_f32; 4];

        dac.process(&[&input], &mut [&mut output]);
        // Only first 2 samples should be copied
        #[allow(clippy::float_cmp)]
        let first_two_match = output[0] == 1.0 && output[1] == 2.0;
        assert!(first_two_match);
    }

    #[test]
    fn dac_rejects_all_params() {
        let mut dac = DacNode;
        assert!(matches!(dac.set_param("gain", 0.5), Err(ParamError::NotFound(_))));
    }

    #[test]
    fn dac_io_counts() {
        let dac = DacNode;
        assert_eq!(dac.num_inputs(), 1);
        assert_eq!(dac.num_outputs(), 1);
    }

    #[test]
    fn factory_creates_dac() {
        let factory = DacFactory;
        let node = factory.create(48000, 512).unwrap();
        assert_eq!(node.num_inputs(), 1);
        assert_eq!(node.num_outputs(), 1);
    }

    #[test]
    fn type_decl_matches_implementation() {
        let decl = dac_type_decl();
        let factory = DacFactory;
        let node = factory.create(48000, 512).unwrap();

        assert_eq!(decl.type_id, "dac");
        assert_eq!(decl.audio_inputs.len(), node.num_inputs());
        assert_eq!(decl.audio_outputs.len(), node.num_outputs());
        assert!(decl.controls.is_empty());
    }
}
