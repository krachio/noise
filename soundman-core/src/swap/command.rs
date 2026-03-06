use crate::graph::DspGraph;

pub enum Command {
    SwapGraph(Box<DspGraph>),
    SetParam { node_id: String, name: String, value: f32 },
    SetMasterGain(f32),
    Shutdown,
}

impl std::fmt::Debug for Command {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::SwapGraph(_) => write!(f, "Command::SwapGraph(...)"),
            Self::SetParam { node_id, name, value } => {
                write!(f, "Command::SetParam({node_id}/{name} = {value})")
            }
            Self::SetMasterGain(gain) => write!(f, "Command::SetMasterGain({gain})"),
            Self::Shutdown => write!(f, "Command::Shutdown"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn command_debug_formatting() {
        let cmd = Command::SetParam {
            node_id: "osc1".into(),
            name: "freq".into(),
            value: 440.0,
        };
        let debug = format!("{cmd:?}");
        assert!(debug.contains("osc1"));
        assert!(debug.contains("freq"));

        let shutdown = Command::Shutdown;
        assert!(format!("{shutdown:?}").contains("Shutdown"));

        let gain = Command::SetMasterGain(0.5);
        assert!(format!("{gain:?}").contains("0.5"));
    }
}
