mod compile;
mod validate;

use serde::{Deserialize, Serialize};

use crate::event::Value;

pub use compile::compile;
pub use validate::validate;

/// IR node sent from the Python frontend.
/// Tagged by "op" field in JSON for readable wire format.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "op")]
pub enum IrNode {
    Atom { value: Value },
    Silence,
    Cat { children: Vec<IrNode> },
    Stack { children: Vec<IrNode> },
    Fast { factor: [i64; 2], child: Box<IrNode> },
    Slow { factor: [i64; 2], child: Box<IrNode> },
    Early { offset: [i64; 2], child: Box<IrNode> },
    Late { offset: [i64; 2], child: Box<IrNode> },
    Rev { child: Box<IrNode> },
    Every { n: u32, transform: Box<IrNode>, child: Box<IrNode> },
    Euclid { pulses: u32, steps: u32, rotation: u32, child: Box<IrNode> },
    Degrade { prob: f64, seed: u64, child: Box<IrNode> },
}

/// Error from IR validation or compilation.
#[derive(Clone, Debug, PartialEq)]
pub enum IrError {
    ZeroDenominator,
    NonPositiveFactor,
    EmptyChildren { op: &'static str },
    InvalidEuclid { msg: String },
    InvalidDegrade { msg: String },
    InvalidEvery { msg: String },
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
        }
    }
}

impl std::error::Error for IrError {}
