#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EngineConfig {
    pub sample_rate: u32,
    pub block_size: usize,
    pub channels: usize,
    pub crossfade_ms: u32,
}

impl EngineConfig {
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
            block_size: 512,
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
        assert_eq!(config.block_size, 512);
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
