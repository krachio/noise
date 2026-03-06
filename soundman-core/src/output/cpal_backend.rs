use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};

use super::{AudioCallback, AudioOutput};
use crate::engine::config::EngineConfig;

pub struct CpalBackend {
    stream: Option<cpal::Stream>,
}

impl CpalBackend {
    #[must_use]
    pub const fn new() -> Self {
        Self { stream: None }
    }
}

impl AudioOutput for CpalBackend {
    fn start(
        &mut self,
        config: &EngineConfig,
        mut callback: AudioCallback,
    ) -> Result<(), String> {
        let host = cpal::default_host();
        let device = host
            .default_output_device()
            .ok_or("no output device available")?;

        let stream_config = cpal::StreamConfig {
            channels: u16::try_from(config.channels).map_err(|e| e.to_string())?,
            sample_rate: cpal::SampleRate(config.sample_rate),
            buffer_size: cpal::BufferSize::Fixed(
                u32::try_from(config.block_size).map_err(|e| e.to_string())?,
            ),
        };

        let stream = device
            .build_output_stream(
                &stream_config,
                move |data: &mut [f32], _: &cpal::OutputCallbackInfo| {
                    callback(data);
                },
                |err| eprintln!("audio stream error: {err}"),
                None,
            )
            .map_err(|e| e.to_string())?;

        stream.play().map_err(|e| e.to_string())?;
        self.stream = Some(stream);
        Ok(())
    }

    fn stop(&mut self) {
        self.stream = None;
    }
}

impl Default for CpalBackend {
    fn default() -> Self {
        Self::new()
    }
}

impl std::fmt::Debug for CpalBackend {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("CpalBackend")
            .field("active", &self.stream.is_some())
            .finish()
    }
}
