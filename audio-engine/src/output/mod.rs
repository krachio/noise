pub mod cpal_backend;

use crate::engine::config::EngineConfig;

/// Audio callback invoked by the output backend each block.
/// Receives a mutable buffer of interleaved samples to fill.
pub type AudioCallback = Box<dyn FnMut(&mut [f32]) + Send>;

/// Delivers audio to a hardware device or test harness.
///
/// The callback runs on the audio thread — it must not block or allocate.
pub trait AudioOutput {
    /// Open the output device and begin calling `callback` each block.
    ///
    /// # Errors
    /// Returns an error string if the output device cannot be opened.
    fn start(
        &mut self,
        config: &EngineConfig,
        callback: AudioCallback,
    ) -> Result<(), String>;

    /// Stop playback and release the device.
    fn stop(&mut self);
}

/// Mock audio output for testing — captures blocks for inspection.
#[derive(Debug)]
pub struct MockAudioOutput {
    captured: Vec<Vec<f32>>,
}

impl MockAudioOutput {
    #[must_use]
    pub const fn new() -> Self {
        Self {
            captured: Vec::new(),
        }
    }

    /// Run the callback for a given number of blocks, capturing output.
    pub fn run_blocks(
        &mut self,
        config: &EngineConfig,
        callback: &mut dyn FnMut(&mut [f32]),
        num_blocks: usize,
    ) {
        for _ in 0..num_blocks {
            let mut buf = vec![0.0_f32; config.block_size * config.channels];
            callback(&mut buf);
            self.captured.push(buf);
        }
    }

    #[must_use]
    pub fn captured_blocks(&self) -> &[Vec<f32>] {
        &self.captured
    }

    pub const fn captured_blocks_mut(&mut self) -> &mut Vec<Vec<f32>> {
        &mut self.captured
    }
}

impl Default for MockAudioOutput {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mock_output_captures_blocks() {
        let config = EngineConfig::default();
        let mut mock = MockAudioOutput::new();

        let mut counter = 0_u32;
        #[allow(clippy::cast_precision_loss)]
        mock.run_blocks(&config, &mut |buf: &mut [f32]| {
            buf[0] = counter as f32;
            counter += 1;
        }, 3);

        assert_eq!(mock.captured_blocks().len(), 3);
        assert!((mock.captured_blocks()[0][0]).abs() < f32::EPSILON);
        assert!((mock.captured_blocks()[1][0] - 1.0).abs() < f32::EPSILON);
        assert!((mock.captured_blocks()[2][0] - 2.0).abs() < f32::EPSILON);
    }
}
