pub mod midi;
pub mod osc;

use crate::event::Value;
use crate::scheduler::TimedEvent;

/// Trait for dispatching timed events to an output backend.
pub trait OutputSink: Send {
    fn send(&mut self, event: &TimedEvent) -> Result<(), OutputError>;
    fn name(&self) -> &str;
}

#[derive(Debug)]
pub enum OutputError {
    Midi(String),
    Osc(String),
}

impl std::fmt::Display for OutputError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Midi(msg) => write!(f, "MIDI error: {msg}"),
            Self::Osc(msg) => write!(f, "OSC error: {msg}"),
        }
    }
}

impl std::error::Error for OutputError {}

/// Dispatch a timed event to the appropriate sink based on its value type.
pub fn dispatch(event: &TimedEvent, midi_sink: Option<&mut dyn OutputSink>, osc_sink: Option<&mut dyn OutputSink>) -> Result<(), OutputError> {
    match &event.event.value {
        Value::Note { .. } | Value::Cc { .. } => {
            if let Some(sink) = midi_sink {
                sink.send(event)?;
            }
        }
        Value::Osc { .. } => {
            if let Some(sink) = osc_sink {
                sink.send(event)?;
            }
        }
    }
    Ok(())
}
