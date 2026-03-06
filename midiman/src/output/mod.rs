//! Output sinks for MIDI and OSC.
//!
//! Each sink implements [`OutputSink`]. The [`dispatch()`] function routes
//! events by value type: `Note`/`Cc` to MIDI, `Osc` to OSC.

pub mod midi;
pub mod osc;

use crate::event::Value;
use crate::scheduler::TimedEvent;

/// Trait for dispatching timed events to an output backend.
pub trait OutputSink: Send {
    /// Send a single timed event to this output.
    fn send(&mut self, event: &TimedEvent) -> Result<(), OutputError>;
    /// Send a MIDI note-off for the given channel and note.
    fn send_note_off(&mut self, _channel: u8, _note: u8) -> Result<(), OutputError> {
        Ok(())
    }
    /// Human-readable identifier for this sink (e.g. port name or address).
    fn name(&self) -> &str;
}

/// Error from an output sink.
#[derive(Debug)]
pub enum OutputError {
    /// A MIDI backend error.
    Midi(String),
    /// An OSC backend error.
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
pub fn dispatch(
    event: &TimedEvent,
    midi_sink: &mut Option<Box<dyn OutputSink>>,
    osc_sink: &mut Option<Box<dyn OutputSink>>,
) -> Result<(), OutputError> {
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
