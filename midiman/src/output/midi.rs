//! MIDI output sink via midir.

use midir::{MidiOutput, MidiOutputConnection};

use crate::event::Value;
use crate::scheduler::TimedEvent;

use super::{OutputError, OutputSink};

/// MIDI output sink using midir.
pub struct MidiSink {
    conn: MidiOutputConnection,
    port_name: String,
}

impl MidiSink {
    /// Connect to the first available MIDI output port.
    pub fn connect_first(client_name: &str) -> Result<Self, OutputError> {
        let output = MidiOutput::new(client_name)
            .map_err(|e| OutputError::Midi(format!("init: {e}")))?;
        let ports = output.ports();
        let port = ports
            .first()
            .ok_or_else(|| OutputError::Midi("no MIDI output ports available".into()))?;
        let port_name = output
            .port_name(port)
            .unwrap_or_else(|_| "unknown".into());
        let conn = output
            .connect(port, "midiman")
            .map_err(|e| OutputError::Midi(format!("connect: {e}")))?;
        Ok(Self { conn, port_name })
    }

    /// Connect to a specific MIDI output port by name.
    pub fn connect_by_name(client_name: &str, target: &str) -> Result<Self, OutputError> {
        let output = MidiOutput::new(client_name)
            .map_err(|e| OutputError::Midi(format!("init: {e}")))?;
        let ports = output.ports();
        let port = ports
            .iter()
            .find(|p| {
                output
                    .port_name(p)
                    .map(|n| n.contains(target))
                    .unwrap_or(false)
            })
            .ok_or_else(|| {
                OutputError::Midi(format!("no port matching '{target}'"))
            })?
            .clone();
        let port_name = output
            .port_name(&port)
            .unwrap_or_else(|_| "unknown".into());
        let conn = output
            .connect(&port, "midiman")
            .map_err(|e| OutputError::Midi(format!("connect: {e}")))?;
        Ok(Self { conn, port_name })
    }

    /// Send raw MIDI bytes.
    fn send_bytes(&mut self, bytes: &[u8]) -> Result<(), OutputError> {
        self.conn
            .send(bytes)
            .map_err(|e| OutputError::Midi(format!("send: {e}")))
    }
}

impl OutputSink for MidiSink {
    fn send_note_off(&mut self, channel: u8, note: u8) -> Result<(), OutputError> {
        let status = 0x80 | (channel & 0x0F);
        self.send_bytes(&[status, note & 0x7F, 0])
    }

    fn send_clock_tick(&mut self) -> Result<(), OutputError> {
        self.send_bytes(&[0xF8])
    }

    fn send_clock_start(&mut self) -> Result<(), OutputError> {
        self.send_bytes(&[0xFA])
    }

    fn send_clock_stop(&mut self) -> Result<(), OutputError> {
        self.send_bytes(&[0xFC])
    }

    fn send(&mut self, event: &TimedEvent) -> Result<(), OutputError> {
        match &event.event.value {
            Value::Note {
                channel,
                note,
                velocity,
                ..
            } => {
                // Note On: 0x90 | channel, note, velocity
                let status = 0x90 | (channel & 0x0F);
                self.send_bytes(&[status, *note & 0x7F, *velocity & 0x7F])
            }
            Value::Cc {
                channel,
                controller,
                value,
            } => {
                // CC: 0xB0 | channel, controller, value
                let status = 0xB0 | (channel & 0x0F);
                self.send_bytes(&[status, *controller & 0x7F, *value & 0x7F])
            }
            Value::Osc { .. } => Ok(()), // Not handled by MIDI sink
        }
    }

    fn name(&self) -> &str {
        &self.port_name
    }
}
