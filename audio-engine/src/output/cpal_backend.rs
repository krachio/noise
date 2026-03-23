use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use log::info;

use super::{AudioCallback, AudioOutput};
use crate::engine::config::EngineConfig;

/// Native device capabilities, queried before engine setup.
#[derive(Debug, Clone)]
pub struct DeviceConfig {
    pub sample_rate: u32,
    pub channels: usize,
}

/// Audio output via [cpal](https://docs.rs/cpal).
///
/// Opens the default output device and drives the audio callback from cpal's
/// audio thread. Use [`query_device`](Self::query_device) to discover the
/// native sample rate before constructing an [`EngineConfig`](crate::engine::config::EngineConfig).
pub struct CpalBackend {
    stream: Option<cpal::Stream>,
    input_stream: Option<cpal::Stream>,
}

impl CpalBackend {
    #[must_use]
    pub const fn new() -> Self {
        Self {
            stream: None,
            input_stream: None,
        }
    }

    /// Query the default output device for its native sample rate and channel count.
    ///
    /// # Errors
    /// Returns an error if no output device is available.
    pub fn query_device() -> Result<DeviceConfig, String> {
        let host = cpal::default_host();
        let device = host
            .default_output_device()
            .ok_or("no output device available")?;
        let config = device.default_output_config().map_err(|e| e.to_string())?;
        Ok(DeviceConfig {
            sample_rate: config.sample_rate().0,
            channels: config.channels() as usize,
        })
    }
}

impl CpalBackend {
    /// Open the default input device and start capturing audio into an rtrb
    /// ring buffer. Returns the `Consumer<f32>` for the `AdcNode`.
    ///
    /// # Errors
    /// Returns an error if no input device is available or the stream fails.
    pub fn start_input(
        &mut self,
        sample_rate: u32,
        channel: usize,
    ) -> Result<rtrb::Consumer<f32>, String> {
        use rtrb::RingBuffer;

        let host = cpal::default_host();
        let device = host
            .default_input_device()
            .ok_or("no input device available")?;
        let default_config = device.default_input_config().map_err(|e| e.to_string())?;

        let channels = default_config.channels() as usize;
        if channel >= channels {
            return Err(format!(
                "channel {channel} out of range (device has {channels} channels)"
            ));
        }

        // ~200ms buffer at the given sample rate
        let capacity = (sample_rate as usize) / 5;
        let (mut producer, consumer) = RingBuffer::new(capacity);

        let stream_config = cpal::StreamConfig {
            channels: default_config.channels(),
            sample_rate: cpal::SampleRate(sample_rate),
            buffer_size: cpal::BufferSize::Default,
        };

        info!(
            "input device: {channels} ch, {sample_rate}Hz, capturing ch {channel}"
        );

        let stream = device
            .build_input_stream(
                &stream_config,
                move |data: &[f32], _: &cpal::InputCallbackInfo| {
                    for frame in data.chunks(channels) {
                        if let Some(&sample) = frame.get(channel) {
                            let _ = producer.push(sample);
                        }
                    }
                },
                |err| eprintln!("audio input stream error: {err}"),
                None,
            )
            .map_err(|e| e.to_string())?;

        stream.play().map_err(|e| e.to_string())?;
        self.input_stream = Some(stream);
        Ok(consumer)
    }
}

impl AudioOutput for CpalBackend {
    fn start(&mut self, config: &EngineConfig, mut callback: AudioCallback) -> Result<(), String> {
        let host = cpal::default_host();
        let device = host
            .default_output_device()
            .ok_or("no output device available")?;

        if let Ok(default_config) = device.default_output_config() {
            info!(
                "device default: {}Hz, {} ch, {:?}",
                default_config.sample_rate().0,
                default_config.channels(),
                default_config.buffer_size()
            );
        }

        let stream_config = cpal::StreamConfig {
            channels: u16::try_from(config.channels).map_err(|e| e.to_string())?,
            sample_rate: cpal::SampleRate(config.sample_rate),
            buffer_size: cpal::BufferSize::Fixed(
                u32::try_from(config.block_size).map_err(|e| e.to_string())?,
            ),
        };
        info!(
            "requesting: {}Hz, {} ch, block={}",
            config.sample_rate, config.channels, config.block_size
        );

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
            .field("output_active", &self.stream.is_some())
            .field("input_active", &self.input_stream.is_some())
            .finish()
    }
}
