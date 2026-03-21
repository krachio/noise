use crate::graph::DspGraph;

/// Instructions sent from the control thread to the audio thread via the
/// lock-free SPSC channel. Processed by [`GraphSwapper::drain_commands`](super::GraphSwapper::drain_commands).
pub enum Command {
    /// Replace the active graph (triggers crossfade).
    SwapGraph(Box<DspGraph>),
    /// Set a parameter on a node in the active graph.
    SetParam { node_id: String, name: String, value: f32 },
    /// Set the master output gain.
    SetMasterGain(f32),
    /// Update the crossfade duration (in samples) for subsequent graph swaps.
    SetCrossfade(usize),
    /// Signal engine shutdown.
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
            Self::SetCrossfade(samples) => write!(f, "Command::SetCrossfade({samples})"),
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
