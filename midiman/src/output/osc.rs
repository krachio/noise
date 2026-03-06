//! OSC output sink via rosc + UDP.

use std::net::UdpSocket;

use rosc::{OscMessage, OscPacket, OscType, encoder};

use crate::event::{OscArg, Value};
use crate::scheduler::TimedEvent;

use super::{OutputError, OutputSink};

/// OSC output sink using rosc + UdpSocket.
pub struct OscSink {
    socket: UdpSocket,
    target: String,
}

impl OscSink {
    /// Create a new OSC sink that sends packets to `target_addr` (e.g. `"127.0.0.1:57120"`).
    pub fn new(target_addr: &str) -> Result<Self, OutputError> {
        let socket = UdpSocket::bind("0.0.0.0:0")
            .map_err(|e| OutputError::Osc(format!("bind: {e}")))?;
        Ok(Self {
            socket,
            target: target_addr.to_owned(),
        })
    }

    fn send_osc(&self, address: &str, args: &[OscArg]) -> Result<(), OutputError> {
        let osc_args: Vec<OscType> = args
            .iter()
            .map(|a| match a {
                OscArg::Float(f) => OscType::Double(*f),
                OscArg::Int(i) => OscType::Int(*i),
                OscArg::Str(s) => OscType::String(s.clone()),
            })
            .collect();

        let packet = OscPacket::Message(OscMessage {
            addr: address.to_owned(),
            args: osc_args,
        });

        let bytes = encoder::encode(&packet)
            .map_err(|e| OutputError::Osc(format!("encode: {e}")))?;

        self.socket
            .send_to(&bytes, &self.target)
            .map_err(|e| OutputError::Osc(format!("send: {e}")))?;

        Ok(())
    }
}

impl OutputSink for OscSink {
    fn send(&mut self, event: &TimedEvent) -> Result<(), OutputError> {
        match &event.event.value {
            Value::Osc { address, args } => self.send_osc(address, args),
            _ => Ok(()), // Not handled by OSC sink
        }
    }

    fn name(&self) -> &str {
        &self.target
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::{Event, OscArg, Value};
    use crate::time::Arc;
    use std::time::Instant;

    #[test]
    fn osc_sink_sends_and_receives_loopback() {
        // Bind a listener
        let listener = UdpSocket::bind("127.0.0.1:0").unwrap();
        let listener_addr = listener.local_addr().unwrap();
        listener.set_read_timeout(Some(std::time::Duration::from_millis(500))).unwrap();

        // Create sink pointing at listener
        let mut sink = OscSink::new(&listener_addr.to_string()).unwrap();

        let event = TimedEvent {
            fire_at: Instant::now(),
            event: Event::new(
                Some(Arc::cycle(0)),
                Arc::cycle(0),
                Value::Osc {
                    address: "/test/hello".into(),
                    args: vec![OscArg::Float(42.0), OscArg::Str("world".into())],
                },
            ),
            slot_name: "d1".into(),
        };

        sink.send(&event).unwrap();

        // Receive and decode
        let mut buf = [0u8; 1024];
        let (len, _) = listener.recv_from(&mut buf).unwrap();
        let (_, packet) = rosc::decoder::decode_udp(&buf[..len]).unwrap();

        match packet {
            OscPacket::Message(msg) => {
                assert_eq!(msg.addr, "/test/hello");
                assert_eq!(msg.args.len(), 2);
                assert_eq!(msg.args[0], OscType::Double(42.0));
                assert_eq!(msg.args[1], OscType::String("world".into()));
            }
            OscPacket::Bundle(_) => panic!("expected message, got bundle"),
        }
    }

    #[test]
    fn osc_sink_ignores_non_osc_values() {
        let listener = UdpSocket::bind("127.0.0.1:0").unwrap();
        let listener_addr = listener.local_addr().unwrap();

        let mut sink = OscSink::new(&listener_addr.to_string()).unwrap();

        let event = TimedEvent {
            fire_at: Instant::now(),
            event: Event::new(
                Some(Arc::cycle(0)),
                Arc::cycle(0),
                Value::Note {
                    channel: 0,
                    note: 60,
                    velocity: 100,
                    dur: 0.5,
                },
            ),
            slot_name: "d1".into(),
        };

        // Should succeed but not send anything
        sink.send(&event).unwrap();

        // Verify nothing was sent
        listener.set_read_timeout(Some(std::time::Duration::from_millis(50))).unwrap();
        let mut buf = [0u8; 1024];
        assert!(listener.recv_from(&mut buf).is_err());
    }
}
