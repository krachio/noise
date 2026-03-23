use std::fmt;

/// Index of a node within a compiled [`DspGraph`](super::DspGraph).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct NodeId(pub usize);

/// Identifies a specific port on a specific node within a compiled graph.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct PortId {
    pub node: NodeId,
    pub port: usize,
}

/// Error returned by [`DspNode::set_param`] when a parameter update fails.
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Debug, Clone, PartialEq)]
pub enum ParamError {
    /// No parameter with this name exists on the node.
    NotFound(String),
    /// The value is outside the parameter's valid range.
    OutOfRange {
        name: String,
        value: f32,
        min: f32,
        max: f32,
    },
}

impl fmt::Display for ParamError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotFound(name) => write!(f, "parameter not found: {name}"),
            Self::OutOfRange {
                name,
                value,
                min,
                max,
            } => {
                write!(
                    f,
                    "parameter '{name}' value {value} out of range [{min}, {max}]"
                )
            }
        }
    }
}

impl std::error::Error for ParamError {}

/// A single processing node in the audio graph.
///
/// Each node reads from its input buffers, writes to its output buffers,
/// and exposes named parameters that can be changed at control rate.
/// Nodes must be `Send` so compiled graphs can be transferred across threads.
///
/// Implement this trait to add custom DSP to audio-engine — then wrap it in a
/// [`NodeFactory`](crate::registry::NodeFactory) and register it with the
/// [`NodeRegistry`](crate::registry::NodeRegistry).
pub trait DspNode: Send {
    /// Process one block of audio. `inputs[i]` is the i-th input channel,
    /// `outputs[i]` is the i-th output channel. All slices have the same length.
    fn process(&mut self, inputs: &[&[f32]], outputs: &mut [&mut [f32]]);

    /// Number of audio input channels (0 for generators).
    fn num_inputs(&self) -> usize;

    /// Number of audio output channels.
    fn num_outputs(&self) -> usize;

    /// Set a named parameter to a new value.
    ///
    /// # Errors
    /// Returns `ParamError::NotFound` if the parameter doesn't exist,
    /// or `ParamError::OutOfRange` if the value is outside the valid range.
    fn set_param(&mut self, name: &str, value: f32) -> Result<(), ParamError>;

    /// Re-initialize internal state for a new sample rate.
    fn reset(&mut self, sample_rate: u32);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn node_id_equality_and_hashing() {
        use std::collections::HashSet;

        let a = NodeId(0);
        let b = NodeId(0);
        let c = NodeId(1);

        assert_eq!(a, b);
        assert_ne!(a, c);

        let mut set = HashSet::new();
        set.insert(a);
        assert!(set.contains(&b));
        assert!(!set.contains(&c));
    }

    #[test]
    fn port_id_references_node() {
        let port = PortId {
            node: NodeId(3),
            port: 0,
        };
        assert_eq!(port.node, NodeId(3));
        assert_eq!(port.port, 0);
    }

    #[test]
    fn param_error_display() {
        let not_found = ParamError::NotFound("freq".into());
        assert_eq!(not_found.to_string(), "parameter not found: freq");

        let out_of_range = ParamError::OutOfRange {
            name: "cutoff".into(),
            value: -1.0,
            min: 20.0,
            max: 20_000.0,
        };
        assert!(out_of_range.to_string().contains("cutoff"));
        assert!(out_of_range.to_string().contains("-1"));
    }

    struct TestNode {
        sample_rate: u32,
    }

    impl DspNode for TestNode {
        fn process(&mut self, inputs: &[&[f32]], outputs: &mut [&mut [f32]]) {
            for (out, inp) in outputs.iter_mut().zip(inputs.iter()) {
                out.copy_from_slice(inp);
            }
        }

        fn num_inputs(&self) -> usize {
            1
        }
        fn num_outputs(&self) -> usize {
            1
        }

        fn set_param(&mut self, name: &str, _value: f32) -> Result<(), ParamError> {
            Err(ParamError::NotFound(name.into()))
        }

        fn reset(&mut self, sample_rate: u32) {
            self.sample_rate = sample_rate;
        }
    }

    #[test]
    fn dsp_node_trait_passthrough() {
        let mut node = TestNode { sample_rate: 44100 };
        let input = [1.0_f32, 2.0, 3.0];
        let mut output = [0.0_f32; 3];

        node.process(&[&input], &mut [&mut output]);
        // Exact comparison valid: passthrough copies input bits directly
        #[allow(clippy::float_cmp)]
        let matches = output == [1.0, 2.0, 3.0];
        assert!(matches);
    }

    #[test]
    fn dsp_node_trait_reset() {
        let mut node = TestNode { sample_rate: 44100 };
        node.reset(48000);
        assert_eq!(node.sample_rate, 48000);
    }

    #[test]
    fn dsp_node_trait_param_error() {
        let mut node = TestNode { sample_rate: 44100 };
        let result = node.set_param("nonexistent", 0.0);
        assert_eq!(result, Err(ParamError::NotFound("nonexistent".into())));
    }
}
