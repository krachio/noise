//! Intermediate representation received from the frontend.
//!
//! [`IrNode`] is a serde-tagged enum matching the JSON wire format.
//! [`validate()`] checks structural invariants (no zero denominators,
//! no empty children) and [`compile()`] transforms an `IrNode` tree into
//! an arena-indexed [`CompiledPattern`](crate::pattern::CompiledPattern).
//!
//! # JSON wire format
//!
//! Nodes are tagged by `"op"`. The frontend sends these as JSON:
//!
//! ```json
//! {"op": "Fast", "factor": [2, 1], "child":
//!   {"op": "Cat", "children": [
//!     {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 60, "velocity": 100, "dur": 0.5}},
//!     {"op": "Atom", "value": {"type": "Note", "channel": 0, "note": 64, "velocity": 100, "dur": 0.5}}
//!   ]}
//! }
//! ```
//!
//! # Examples
//!
//! ```
//! use pattern_engine::ir::{IrNode, compile};
//! use pattern_engine::event::Value;
//! use pattern_engine::pattern::query;
//! use pattern_engine::time::Arc;
//!
//! // Build an IR tree: two notes alternating
//! let ir = IrNode::Cat {
//!     children: vec![
//!         IrNode::Atom { value: Value::Note { channel: 0, note: 60, velocity: 100, dur: 0.5 } },
//!         IrNode::Atom { value: Value::Note { channel: 0, note: 64, velocity: 100, dur: 0.5 } },
//!     ],
//! };
//!
//! // Compile and query cycle 0
//! let pattern = compile(&ir).unwrap();
//! let events = query(&pattern, pattern.root, Arc::cycle(0));
//! assert_eq!(events.len(), 2);
//! ```

mod compile;
mod validate;

use serde::{Deserialize, Serialize};

use crate::event::Value;

pub use compile::compile;
pub use validate::validate;

/// IR node sent from the Python frontend.
/// Tagged by "op" field in JSON for readable wire format.
#[allow(missing_docs)]
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "op")]
pub enum IrNode {
    /// A leaf node holding a concrete value (note, CC, or OSC).
    Atom { value: Value },
    /// Produces no events for its time span.
    Silence,
    /// Marks a sub-pattern as an indivisible unit. Transparent in query
    /// (delegates to child), but signals to transforms that this compound
    /// should be treated as a single atomic event.
    Freeze { child: Box<IrNode> },
    /// Sequential concatenation: children share the cycle equally.
    Cat { children: Vec<IrNode> },
    /// Parallel layering: all children occupy the full cycle.
    Stack { children: Vec<IrNode> },
    /// Speed up the child pattern by a rational factor `[num, den]`.
    Fast {
        factor: [i64; 2],
        child: Box<IrNode>,
    },
    /// Slow down the child pattern by a rational factor `[num, den]`.
    Slow {
        factor: [i64; 2],
        child: Box<IrNode>,
    },
    /// Shift the child pattern earlier by a rational offset `[num, den]`.
    Early {
        offset: [i64; 2],
        child: Box<IrNode>,
    },
    /// Shift the child pattern later by a rational offset `[num, den]`.
    Late {
        offset: [i64; 2],
        child: Box<IrNode>,
    },
    /// Reverse the child pattern within each cycle.
    Rev { child: Box<IrNode> },
    /// Apply a transform to the child every `n` cycles.
    Every {
        n: u32,
        transform: Box<IrNode>,
        child: Box<IrNode>,
    },
    /// Euclidean rhythm: distribute `pulses` across `steps` with optional rotation.
    Euclid {
        pulses: u32,
        steps: u32,
        rotation: u32,
        child: Box<IrNode>,
    },
    /// Randomly drop events with the given probability (0.0 = keep all, 1.0 = drop all).
    Degrade {
        prob: f64,
        seed: u64,
        child: Box<IrNode>,
    },
    /// Time warp: remap event onset times within each grid pair.
    /// `kind` selects the warp function ("swing"), `amount` parameterizes it,
    /// `grid` is subdivisions per cycle (must be even).
    Warp {
        kind: String,
        amount: f64,
        grid: u32,
        child: Box<IrNode>,
    },
}

/// Error from IR validation or compilation.
#[allow(missing_docs)]
#[derive(Clone, Debug, PartialEq)]
pub enum IrError {
    /// A rational time value has a zero denominator.
    ZeroDenominator,
    /// A `Fast` or `Slow` factor is not strictly positive.
    NonPositiveFactor,
    /// A `Cat` or `Stack` node has an empty children list.
    EmptyChildren { op: &'static str },
    /// Invalid Euclidean rhythm parameters.
    InvalidEuclid { msg: String },
    /// Invalid degrade probability or seed.
    InvalidDegrade { msg: String },
    /// Invalid `Every` combinator parameters.
    InvalidEvery { msg: String },
    /// Invalid `Warp` parameters.
    InvalidWarp { msg: String },
}

impl std::fmt::Display for IrError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ZeroDenominator => write!(f, "time value has zero denominator"),
            Self::NonPositiveFactor => write!(f, "fast/slow factor must be positive"),
            Self::EmptyChildren { op } => write!(f, "{op} requires at least one child"),
            Self::InvalidEuclid { msg } => write!(f, "euclid: {msg}"),
            Self::InvalidDegrade { msg } => write!(f, "degrade: {msg}"),
            Self::InvalidEvery { msg } => write!(f, "every: {msg}"),
            Self::InvalidWarp { msg } => write!(f, "warp: {msg}"),
        }
    }
}

impl std::error::Error for IrError {}
