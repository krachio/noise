use std::f32::consts::TAU;

use crate::graph::node::{DspNode, ParamError};
use crate::ir::types::{ChannelLayout, ControlDecl, NodeTypeDecl, PortDecl, Rate};
use crate::registry::NodeFactory;

/// Oscillator waveform shape. Selected via the `waveform` parameter
/// (0 = sine, 1 = saw, 2 = square).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Waveform {
    Sine,
    Saw,
    Square,
}

impl Waveform {
    fn from_index(v: f32) -> Self {
        #[allow(clippy::float_cmp)]
        if v == 1.0 {
            Self::Saw
        } else if v == 2.0 {
            Self::Square
        } else {
            Self::Sine
        }
    }
}

/// Mono oscillator with selectable waveform.
///
/// Parameters: `freq` (20–20000 Hz), `waveform` (0/1/2).
/// Zero inputs, one mono output.
#[derive(Debug)]
pub struct Oscillator {
    phase: f32,
    freq: f32,
    waveform: Waveform,
    sample_rate: f32,
}

impl Oscillator {
    #[must_use]
    #[allow(clippy::cast_precision_loss)]
    pub const fn new(sample_rate: u32) -> Self {
        Self {
            phase: 0.0,
            freq: 440.0,
            waveform: Waveform::Sine,
            sample_rate: sample_rate as f32,
        }
    }

    fn generate_sample(&self) -> f32 {
        match self.waveform {
            Waveform::Sine => (self.phase * TAU).sin(),
            Waveform::Saw => 2.0_f32.mul_add(self.phase, -1.0),
            Waveform::Square => {
                if self.phase < 0.5 { 1.0 } else { -1.0 }
            }
        }
    }

    fn advance_phase(&mut self) {
        self.phase += self.freq / self.sample_rate;
        self.phase -= self.phase.floor();
    }
}

impl DspNode for Oscillator {
    fn process(&mut self, _inputs: &[&[f32]], outputs: &mut [&mut [f32]]) {
        if let Some(out) = outputs.first_mut() {
            for sample in out.iter_mut() {
                *sample = self.generate_sample();
                self.advance_phase();
            }
        }
    }

    fn num_inputs(&self) -> usize { 0 }
    fn num_outputs(&self) -> usize { 1 }

    fn set_param(&mut self, name: &str, value: f32) -> Result<(), ParamError> {
        match name {
            "freq" => {
                if !(20.0..=20_000.0).contains(&value) {
                    return Err(ParamError::OutOfRange {
                        name: name.into(),
                        value,
                        min: 20.0,
                        max: 20_000.0,
                    });
                }
                self.freq = value;
                Ok(())
            }
            "waveform" => {
                self.waveform = Waveform::from_index(value);
                Ok(())
            }
            _ => Err(ParamError::NotFound(name.into())),
        }
    }

    #[allow(clippy::cast_precision_loss)]
    fn reset(&mut self, sample_rate: u32) {
        self.phase = 0.0;
        self.sample_rate = sample_rate as f32;
    }
}

#[derive(Debug)]
pub struct OscillatorFactory;

impl NodeFactory for OscillatorFactory {
    fn create(&self, sample_rate: u32, _block_size: usize) -> Box<dyn DspNode> {
        Box::new(Oscillator::new(sample_rate))
    }
}

/// Returns the [`NodeTypeDecl`] for the built-in `"oscillator"` type.
#[must_use]
pub fn oscillator_type_decl() -> NodeTypeDecl {
    NodeTypeDecl {
        type_id: "oscillator".into(),
        audio_inputs: vec![],
        audio_outputs: vec![PortDecl {
            name: "out".into(),
            channels: ChannelLayout::Mono,
        }],
        controls: vec![
            ControlDecl {
                name: "freq".into(),
                range: (20.0, 20_000.0),
                default: 440.0,
                rate: Rate::Control,
                unit: Some("Hz".into()),
            },
            ControlDecl {
                name: "waveform".into(),
                range: (0.0, 2.0),
                default: 0.0,
                rate: Rate::Control,
                unit: None,
            },
        ],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE_RATE: u32 = 48000;

    #[test]
    fn sine_output_starts_at_zero() {
        let mut osc = Oscillator::new(SAMPLE_RATE);
        let mut output = [0.0_f32; 1];
        osc.process(&[], &mut [&mut output]);
        assert!(output[0].abs() < 1e-6, "sine should start near zero, got {}", output[0]);
    }

    #[test]
    fn sine_output_bounded() {
        let mut osc = Oscillator::new(SAMPLE_RATE);
        let mut output = [0.0_f32; 1024];
        osc.process(&[], &mut [&mut output]);
        for &s in &output {
            assert!((-1.0..=1.0).contains(&s), "sample out of [-1, 1]: {s}");
        }
    }

    #[test]
    fn sine_frequency_matches_expected_period() {
        let mut osc = Oscillator::new(SAMPLE_RATE);
        osc.set_param("freq", 1000.0).unwrap();

        let period_samples = SAMPLE_RATE / 1000; // 48 samples per period
        let mut output = vec![0.0_f32; period_samples as usize * 4];
        osc.process(&[], &mut [&mut output]);

        // Find zero crossings (positive-going)
        let mut crossings = 0;
        for w in output.windows(2) {
            if w[0] <= 0.0 && w[1] > 0.0 {
                crossings += 1;
            }
        }
        // 4 periods should give approximately 4 positive zero crossings
        assert!((3..=5).contains(&crossings), "expected ~4 zero crossings, got {crossings}");
    }

    #[test]
    fn saw_output_ramps() {
        let mut osc = Oscillator::new(SAMPLE_RATE);
        osc.set_param("waveform", 1.0).unwrap();
        let mut output = [0.0_f32; 10];
        osc.process(&[], &mut [&mut output]);
        assert!(output[0] < output[5], "saw should ramp up");
    }

    #[test]
    fn square_output_is_bipolar() {
        let mut osc = Oscillator::new(SAMPLE_RATE);
        osc.set_param("waveform", 2.0).unwrap();
        let mut output = [0.0_f32; 1024];
        osc.process(&[], &mut [&mut output]);

        let has_positive = output.iter().any(|&s| s > 0.5);
        let has_negative = output.iter().any(|&s| s < -0.5);
        assert!(has_positive, "square should have positive samples");
        assert!(has_negative, "square should have negative samples");

        for &s in &output {
            assert!(
                (s - 1.0).abs() < f32::EPSILON || (s + 1.0).abs() < f32::EPSILON,
                "square sample should be +/-1, got {s}"
            );
        }
    }

    #[test]
    fn set_freq_out_of_range() {
        let mut osc = Oscillator::new(SAMPLE_RATE);
        let result = osc.set_param("freq", 10.0);
        assert!(matches!(result, Err(ParamError::OutOfRange { .. })));
    }

    #[test]
    fn set_unknown_param() {
        let mut osc = Oscillator::new(SAMPLE_RATE);
        let result = osc.set_param("volume", 0.5);
        assert!(matches!(result, Err(ParamError::NotFound(_))));
    }

    #[test]
    fn reset_clears_phase() {
        let mut osc = Oscillator::new(SAMPLE_RATE);
        let mut buf = [0.0_f32; 100];
        osc.process(&[], &mut [&mut buf]);

        osc.reset(SAMPLE_RATE);
        let mut output = [0.0_f32; 1];
        osc.process(&[], &mut [&mut output]);
        assert!(output[0].abs() < 1e-6, "after reset, sine should start near zero");
    }

    #[test]
    fn factory_creates_working_oscillator() {
        let factory = OscillatorFactory;
        let mut node = factory.create(SAMPLE_RATE, 512);
        assert_eq!(node.num_inputs(), 0);
        assert_eq!(node.num_outputs(), 1);

        let mut output = [0.0_f32; 64];
        node.process(&[], &mut [&mut output]);
        let energy: f32 = output.iter().map(|s| s * s).sum();
        assert!(energy > 0.0, "oscillator should produce non-silent output");
    }

    #[test]
    fn type_decl_matches_implementation() {
        let decl = oscillator_type_decl();
        let factory = OscillatorFactory;
        let node = factory.create(SAMPLE_RATE, 512);

        assert_eq!(decl.type_id, "oscillator");
        assert_eq!(decl.audio_inputs.len(), node.num_inputs());
        assert_eq!(decl.audio_outputs.len(), node.num_outputs());
    }
}
