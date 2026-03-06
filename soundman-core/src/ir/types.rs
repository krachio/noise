use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChannelLayout {
    Mono,
    Stereo,
}

impl ChannelLayout {
    #[must_use]
    pub const fn channel_count(self) -> usize {
        match self {
            Self::Mono => 1,
            Self::Stereo => 2,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Rate {
    Control,
    Audio,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PortDecl {
    pub name: String,
    pub channels: ChannelLayout,
}

#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ControlDecl {
    pub name: String,
    pub range: (f32, f32),
    pub default: f32,
    pub rate: Rate,
    pub unit: Option<String>,
}

#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct NodeTypeDecl {
    pub type_id: String,
    pub audio_inputs: Vec<PortDecl>,
    pub audio_outputs: Vec<PortDecl>,
    pub controls: Vec<ControlDecl>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn channel_layout_count() {
        assert_eq!(ChannelLayout::Mono.channel_count(), 1);
        assert_eq!(ChannelLayout::Stereo.channel_count(), 2);
    }

    #[test]
    fn node_type_decl_serde_roundtrip() {
        let decl = NodeTypeDecl {
            type_id: "oscillator".into(),
            audio_inputs: vec![],
            audio_outputs: vec![PortDecl {
                name: "out".into(),
                channels: ChannelLayout::Mono,
            }],
            controls: vec![
                ControlDecl {
                    name: "freq".into(),
                    range: (20.0, 20_000.0),
                    default: 440.0,
                    rate: Rate::Control,
                    unit: Some("Hz".into()),
                },
                ControlDecl {
                    name: "waveform".into(),
                    range: (0.0, 2.0),
                    default: 0.0,
                    rate: Rate::Control,
                    unit: None,
                },
            ],
        };

        let json = serde_json::to_string(&decl).unwrap();
        let roundtripped: NodeTypeDecl = serde_json::from_str(&json).unwrap();
        assert_eq!(decl, roundtripped);
    }

    #[test]
    fn node_type_decl_deserializes_from_json() {
        let json = r#"{
            "type_id": "faust:lowpass2",
            "audio_inputs": [{"name": "in", "channels": "mono"}],
            "audio_outputs": [{"name": "out", "channels": "stereo"}],
            "controls": [{
                "name": "cutoff",
                "range": [20.0, 20000.0],
                "default": 1000.0,
                "rate": "control",
                "unit": "Hz"
            }]
        }"#;

        let decl: NodeTypeDecl = serde_json::from_str(json).unwrap();
        assert_eq!(decl.type_id, "faust:lowpass2");
        assert_eq!(decl.audio_inputs.len(), 1);
        assert_eq!(decl.audio_inputs[0].channels, ChannelLayout::Mono);
        assert_eq!(decl.audio_outputs[0].channels, ChannelLayout::Stereo);
        assert_eq!(decl.controls[0].name, "cutoff");
        assert_eq!(decl.controls[0].range, (20.0, 20_000.0));
        assert!((decl.controls[0].default - 1000.0).abs() < f32::EPSILON);
        assert_eq!(decl.controls[0].unit, Some("Hz".into()));
    }

    #[test]
    fn rate_serde_roundtrip() {
        let control_json = serde_json::to_string(&Rate::Control).unwrap();
        assert_eq!(control_json, "\"control\"");

        let audio_json = serde_json::to_string(&Rate::Audio).unwrap();
        assert_eq!(audio_json, "\"audio\"");

        let roundtripped: Rate = serde_json::from_str(&control_json).unwrap();
        assert_eq!(roundtripped, Rate::Control);
    }
}
