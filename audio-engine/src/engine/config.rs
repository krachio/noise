/// Audio engine configuration.
///
/// Defaults: 48 kHz, 256-sample blocks, stereo, 10 ms crossfade.
/// 256 samples @ 44100 Hz ≈ 5.8 ms per block — half the quantization of
/// 512-sample blocks, measurably tighter for percussion-driven patterns.
/// Use [`CpalBackend::query_device`](crate::output::cpal_backend::CpalBackend::query_device)
/// to match the hardware sample rate.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EngineConfig {
    /// Sample rate in Hz (e.g. 44100, 48000).
    pub sample_rate: u32,
    /// Samples per processing block.
    pub block_size: usize,
    /// Number of output channels (1 = mono, 2 = stereo).
    pub channels: usize,
    /// Duration of graph-swap crossfade in milliseconds.
    pub crossfade_ms: u32,
}

impl EngineConfig {
    /// Crossfade duration converted to samples.
    #[must_use]
    #[allow(clippy::cast_precision_loss, clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    pub const fn crossfade_samples(&self) -> usize {
        (self.sample_rate as u64 * self.crossfade_ms as u64 / 1000) as usize
    }
}

impl Default for EngineConfig {
    fn default() -> Self {
        Self {
            sample_rate: 48000,
            block_size: 256,
            channels: 2,
            crossfade_ms: 10,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_config() {
        let config = EngineConfig::default();
        assert_eq!(config.sample_rate, 48000);
        assert_eq!(config.block_size, 256);
        assert_eq!(config.channels, 2);
        assert_eq!(config.crossfade_ms, 10);
    }

    #[test]
    fn crossfade_samples_calculation() {
        let config = EngineConfig {
            sample_rate: 48000,
            crossfade_ms: 10,
            ..Default::default()
        };
        assert_eq!(config.crossfade_samples(), 480);

        let config_44k = EngineConfig {
            sample_rate: 44100,
            crossfade_ms: 20,
            ..Default::default()
        };
        assert_eq!(config_44k.crossfade_samples(), 882);
    }
}
