use rtrb::Consumer;

use crate::graph::node::{DspNode, ParamError};
use crate::ir::types::{ChannelLayout, NodeTypeDecl, PortDecl};

/// Audio input node — reads from a lock-free ring buffer fed by the system
/// audio input callback. Outputs silence on underrun (no samples available).
pub struct AdcNode {
    consumer: Consumer<f32>,
}

impl AdcNode {
    #[must_use]
    pub const fn new(consumer: Consumer<f32>) -> Self {
        Self { consumer }
    }
}

impl DspNode for AdcNode {
    fn process(&mut self, _inputs: &[&[f32]], outputs: &mut [&mut [f32]]) {
        if let Some(out) = outputs.first_mut() {
            for s in out.iter_mut() {
                *s = self.consumer.pop().unwrap_or(0.0);
            }
        }
    }

    fn num_inputs(&self) -> usize {
        0
    }
    fn num_outputs(&self) -> usize {
        1
    }

    fn set_param(&mut self, name: &str, _value: f32) -> Result<(), ParamError> {
        Err(ParamError::NotFound(name.into()))
    }

    fn reset(&mut self, _sample_rate: u32) {}
}

impl std::fmt::Debug for AdcNode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AdcNode").finish_non_exhaustive()
    }
}

/// Returns the [`NodeTypeDecl`] for the `"adc_input"` type.
#[must_use]
pub fn adc_type_decl() -> NodeTypeDecl {
    NodeTypeDecl {
        type_id: "adc_input".into(),
        audio_inputs: vec![],
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
    use rtrb::RingBuffer;

    #[test]
    fn adc_outputs_silence_on_empty_consumer() {
        let (_producer, consumer) = RingBuffer::new(64);
        let mut adc = AdcNode::new(consumer);

        let mut output = [0.0_f32; 16];
        adc.process(&[], &mut [&mut output]);

        for &s in &output {
            assert!(
                s.abs() < f32::EPSILON,
                "empty consumer should output silence, got {s}",
            );
        }
    }

    #[test]
    fn adc_reads_from_consumer() {
        let (mut producer, consumer) = RingBuffer::new(64);
        let mut adc = AdcNode::new(consumer);

        // Push known samples
        for i in 0..8 {
            #[allow(clippy::cast_precision_loss)]
            producer.push(i as f32 * 0.1).unwrap();
        }

        let mut output = [0.0_f32; 8];
        adc.process(&[], &mut [&mut output]);

        for (i, &s) in output.iter().enumerate() {
            #[allow(clippy::cast_precision_loss)]
            let expected = i as f32 * 0.1;
            assert!(
                (s - expected).abs() < f32::EPSILON,
                "sample {i}: expected {expected}, got {s}",
            );
        }
    }

    #[test]
    fn adc_partial_underrun_fills_remainder_with_silence() {
        let (mut producer, consumer) = RingBuffer::new(64);
        let mut adc = AdcNode::new(consumer);

        // Push only 4 samples, request 8
        for i in 0..4 {
            #[allow(clippy::cast_precision_loss)]
            producer.push(i as f32 * 0.25).unwrap();
        }

        let mut output = [999.0_f32; 8];
        adc.process(&[], &mut [&mut output]);

        // First 4 should have data
        assert!((output[0]).abs() < f32::EPSILON);
        assert!((output[3] - 0.75).abs() < f32::EPSILON);
        // Last 4 should be silence
        for &s in &output[4..] {
            assert!(
                s.abs() < f32::EPSILON,
                "underrun should output silence, got {s}"
            );
        }
    }

    #[test]
    fn adc_io_counts() {
        let (_producer, consumer) = RingBuffer::new(4);
        let adc = AdcNode::new(consumer);
        assert_eq!(adc.num_inputs(), 0);
        assert_eq!(adc.num_outputs(), 1);
    }

    #[test]
    fn adc_rejects_all_params() {
        let (_producer, consumer) = RingBuffer::new(4);
        let mut adc = AdcNode::new(consumer);
        assert!(matches!(
            adc.set_param("gain", 0.5),
            Err(ParamError::NotFound(_))
        ));
    }

    #[test]
    fn type_decl_matches_implementation() {
        let decl = adc_type_decl();
        let (_producer, consumer) = RingBuffer::new(4);
        let adc = AdcNode::new(consumer);

        assert_eq!(decl.type_id, "adc_input");
        assert_eq!(decl.audio_inputs.len(), adc.num_inputs());
        assert_eq!(decl.audio_outputs.len(), adc.num_outputs());
        assert!(decl.controls.is_empty());
    }
}
