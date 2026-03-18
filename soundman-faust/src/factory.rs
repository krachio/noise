//! `FaustFactory` — compiles FAUST code and creates `FaustNode` instances.

use soundman::graph::node::DspNode;
use soundman::ir::types::{ChannelLayout, ControlDecl, NodeTypeDecl, PortDecl, Rate};
use soundman::registry::NodeFactory;

use crate::dsp::FaustDsp;
use crate::node::FaustNode;

/// A node factory that compiles FAUST DSP code via LLVM JIT on first
/// instantiation, then clones from the compiled factory for each node.
///
/// The FAUST code is compiled once when the first node is created.
/// Subsequent calls to `create` compile fresh instances from the same source.
pub struct FaustFactory {
    name: String,
    code: String,
}

impl FaustFactory {
    /// Create a factory from FAUST source code.
    ///
    /// The code is not compiled until `create()` is called — this keeps
    /// factory registration lightweight.
    #[must_use]
    pub fn new(name: &str, code: &str) -> Self {
        Self {
            name: name.to_string(),
            code: code.to_string(),
        }
    }

    /// Probe the DSP to build a `NodeTypeDecl` for registry registration.
    ///
    /// This compiles a temporary instance at 48000 Hz to discover the
    /// port layout and parameters.
    ///
    /// # Errors
    /// Returns the FAUST compilation error if the code is invalid.
    pub fn probe_type_decl(&self, type_id: &str) -> Result<NodeTypeDecl, String> {
        let dsp = FaustDsp::from_code(&self.name, &self.code, 48000, 64)?;

        let audio_inputs = if dsp.num_inputs() == 0 {
            vec![]
        } else {
            // FAUST inputs are individual mono channels
            (0..dsp.num_inputs())
                .map(|i| PortDecl {
                    name: if dsp.num_inputs() == 1 {
                        "in".into()
                    } else {
                        format!("in{i}")
                    },
                    channels: ChannelLayout::Mono,
                })
                .collect()
        };

        let audio_outputs = if dsp.num_outputs() == 0 {
            vec![]
        } else {
            (0..dsp.num_outputs())
                .map(|i| PortDecl {
                    name: if dsp.num_outputs() == 1 {
                        "out".into()
                    } else {
                        format!("out{i}")
                    },
                    channels: ChannelLayout::Mono,
                })
                .collect()
        };

        let controls = dsp
            .params()
            .values()
            .map(|p| ControlDecl {
                name: p.label.clone(),
                range: (p.min, p.max),
                default: p.init,
                rate: Rate::Control,
                unit: None,
            })
            .collect();

        Ok(NodeTypeDecl {
            type_id: type_id.to_string(),
            audio_inputs,
            audio_outputs,
            controls,
        })
    }
}

impl NodeFactory for FaustFactory {
    fn create(&self, sample_rate: u32, block_size: usize) -> Result<Box<dyn DspNode>, String> {
        let dsp = FaustDsp::from_code(&self.name, &self.code, sample_rate, block_size)?;
        Ok(Box::new(FaustNode::new(dsp)))
    }
}

impl std::fmt::Debug for FaustFactory {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("FaustFactory")
            .field("name", &self.name)
            .finish_non_exhaustive()
    }
}
