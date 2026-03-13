use std::net::UdpSocket;

use log::{debug, trace, warn};
use rosc::{OscMessage, OscPacket, OscType};

use super::ControlInput;
use crate::protocol::ClientMessage;

pub struct OscControlInput {
    socket: Option<UdpSocket>,
    addr: String,
    buf: Vec<u8>,
}

impl OscControlInput {
    #[must_use]
    pub fn new(addr: &str) -> Self {
        Self {
            socket: None,
            addr: addr.to_string(),
            buf: vec![0u8; 4096],
        }
    }

    #[allow(clippy::cast_possible_truncation)]
    const fn osc_as_f32(arg: &OscType) -> Option<f32> {
        match arg {
            OscType::Float(f) => Some(*f),
            OscType::Double(d) => Some(*d as f32),
            _ => None,
        }
    }

    fn parse_osc_message(msg: &OscMessage) -> Option<ClientMessage> {
        let parts: Vec<&str> = msg.addr.split('/').collect();
        if parts.len() < 3 || parts[1] != "soundman" {
            trace!("ignoring non-soundman OSC: {}", msg.addr);
            return None;
        }

        match parts[2] {
            "set" => {
                // /soundman/set <label> <value>
                let label = msg.args.first().and_then(|a| {
                    if let OscType::String(s) = a { Some(s.clone()) } else { None }
                })?;
                let value = msg.args.get(1).and_then(Self::osc_as_f32)?;
                Some(ClientMessage::SetControl { label, value })
            }
            "load_graph" => {
                // /soundman/load_graph <json_string>
                let json = msg.args.first().and_then(|a| {
                    if let OscType::String(s) = a { Some(s.as_str()) } else { None }
                })?;
                let ir = serde_json::from_str(json).ok()?;
                Some(ClientMessage::LoadGraph(ir))
            }
            "gain" => {
                // /soundman/gain <float>
                let gain = msg.args.first().and_then(Self::osc_as_f32)?;
                Some(ClientMessage::SetMasterGain { gain })
            }
            "ping" => Some(ClientMessage::Ping),
            "shutdown" => Some(ClientMessage::Shutdown),
            unknown => {
                warn!("unknown OSC command: /soundman/{unknown}");
                None
            }
        }
    }

    fn decode_packet(packet: &OscPacket) -> Vec<ClientMessage> {
        match packet {
            OscPacket::Message(msg) => {
                Self::parse_osc_message(msg).into_iter().collect()
            }
            OscPacket::Bundle(bundle) => bundle
                .content
                .iter()
                .flat_map(Self::decode_packet)
                .collect(),
        }
    }
}

impl ControlInput for OscControlInput {
    fn start(&mut self) -> Result<(), String> {
        let socket = UdpSocket::bind(&self.addr).map_err(|e| e.to_string())?;
        socket
            .set_nonblocking(true)
            .map_err(|e| e.to_string())?;
        self.socket = Some(socket);
        Ok(())
    }

    fn poll(&mut self) -> Vec<ClientMessage> {
        let Some(socket) = &self.socket else {
            return vec![];
        };

        let mut messages = Vec::new();

        loop {
            match socket.recv_from(&mut self.buf) {
                Ok((size, addr)) => {
                    if let Ok((_remaining, packet)) = rosc::decoder::decode_udp(&self.buf[..size])
                    {
                        let decoded = Self::decode_packet(&packet);
                        for msg in &decoded {
                            debug!("OSC from {addr}: {msg:?}");
                        }
                        messages.extend(decoded);
                    }
                }
                Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => break,
                Err(_) => break,
            }
        }

        messages
    }

    fn stop(&mut self) {
        self.socket = None;
    }
}

impl std::fmt::Debug for OscControlInput {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("OscControlInput")
            .field("addr", &self.addr)
            .field("active", &self.socket.is_some())
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_set_control() {
        let msg = OscMessage {
            addr: "/soundman/set".into(),
            args: vec![
                OscType::String("pitch".into()),
                OscType::Float(880.0),
            ],
        };
        let result = OscControlInput::parse_osc_message(&msg).unwrap();
        assert!(matches!(
            result,
            ClientMessage::SetControl { ref label, value }
            if label == "pitch" && (value - 880.0).abs() < f32::EPSILON
        ));
    }

    #[test]
    fn parse_set_control_double() {
        let msg = OscMessage {
            addr: "/soundman/set".into(),
            args: vec![
                OscType::String("pitch".into()),
                OscType::Double(440.0),
            ],
        };
        let result = OscControlInput::parse_osc_message(&msg).unwrap();
        assert!(matches!(
            result,
            ClientMessage::SetControl { ref label, value }
            if label == "pitch" && (value - 440.0).abs() < f32::EPSILON
        ));
    }

    #[test]
    fn parse_gain_double() {
        let msg = OscMessage {
            addr: "/soundman/gain".into(),
            args: vec![OscType::Double(0.75)],
        };
        let result = OscControlInput::parse_osc_message(&msg).unwrap();
        assert!(matches!(result, ClientMessage::SetMasterGain { gain } if (gain - 0.75).abs() < f32::EPSILON));
    }

    #[test]
    fn parse_gain() {
        let msg = OscMessage {
            addr: "/soundman/gain".into(),
            args: vec![OscType::Float(0.5)],
        };
        let result = OscControlInput::parse_osc_message(&msg).unwrap();
        assert!(matches!(result, ClientMessage::SetMasterGain { gain } if (gain - 0.5).abs() < f32::EPSILON));
    }

    #[test]
    fn parse_ping() {
        let msg = OscMessage {
            addr: "/soundman/ping".into(),
            args: vec![],
        };
        let result = OscControlInput::parse_osc_message(&msg).unwrap();
        assert!(matches!(result, ClientMessage::Ping));
    }

    #[test]
    fn parse_shutdown() {
        let msg = OscMessage {
            addr: "/soundman/shutdown".into(),
            args: vec![],
        };
        let result = OscControlInput::parse_osc_message(&msg).unwrap();
        assert!(matches!(result, ClientMessage::Shutdown));
    }

    #[test]
    fn parse_unknown_command_returns_none() {
        let msg = OscMessage {
            addr: "/soundman/unknown".into(),
            args: vec![],
        };
        assert!(OscControlInput::parse_osc_message(&msg).is_none());
    }

    #[test]
    fn parse_wrong_namespace_returns_none() {
        let msg = OscMessage {
            addr: "/other/set".into(),
            args: vec![
                OscType::String("pitch".into()),
                OscType::Float(440.0),
            ],
        };
        assert!(OscControlInput::parse_osc_message(&msg).is_none());
    }

    #[test]
    fn parse_load_graph_from_osc() {
        let json = r#"{"nodes":[{"id":"osc1","type_id":"oscillator","controls":{"freq":440.0}},{"id":"out","type_id":"dac","controls":{}}],"connections":[{"from_node":"osc1","from_port":"out","to_node":"out","to_port":"in"}],"exposed_controls":{}}"#;

        let msg = OscMessage {
            addr: "/soundman/load_graph".into(),
            args: vec![OscType::String(json.into())],
        };
        let result = OscControlInput::parse_osc_message(&msg).unwrap();
        assert!(matches!(result, ClientMessage::LoadGraph(_)));
    }

    #[test]
    fn osc_control_input_roundtrip_via_udp() {
        // Start receiver
        let mut osc_input = OscControlInput::new("127.0.0.1:0");
        osc_input.start().unwrap();

        let local_addr = osc_input.socket.as_ref().unwrap().local_addr().unwrap();

        // Send an OSC message via UDP
        let sender = UdpSocket::bind("127.0.0.1:0").unwrap();
        let msg = rosc::encoder::encode(&OscPacket::Message(OscMessage {
            addr: "/soundman/set".into(),
            args: vec![
                OscType::String("pitch".into()),
                OscType::Float(880.0),
            ],
        }))
        .unwrap();
        sender.send_to(&msg, local_addr).unwrap();

        // Small delay for UDP delivery
        std::thread::sleep(std::time::Duration::from_millis(10));

        let messages = osc_input.poll();
        assert_eq!(messages.len(), 1);
        assert!(matches!(
            &messages[0],
            ClientMessage::SetControl { label, .. } if label == "pitch"
        ));
    }
}
