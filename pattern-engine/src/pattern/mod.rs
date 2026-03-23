//! Compiled pattern representation and query evaluator.
//!
//! Patterns are stored as a flat arena of [`PatternNode`]s indexed by `usize`.
//! This avoids heap allocation and pointer chasing during evaluation.
//! [`query()`] walks the arena recursively to produce events for a given
//! time arc.
//!
//! # Examples
//!
//! ```
//! use pattern_engine::pattern::{CompiledPattern, query};
//! use pattern_engine::event::Value;
//! use pattern_engine::time::Arc;
//!
//! // Create a single-note pattern and query one cycle
//! let pat = CompiledPattern::atom(
//!     Value::Note { channel: 0, note: 60, velocity: 100, dur: 0.5 },
//! );
//! let events = query(&pat, pat.root, Arc::cycle(0));
//! assert_eq!(events.len(), 1);
//! assert_eq!(events[0].value, Value::Note { channel: 0, note: 60, velocity: 100, dur: 0.5 });
//! ```

mod query;

use smallvec::SmallVec;

use crate::event::Value;
use crate::time::Time;

/// A compiled pattern stored as a flat arena of nodes.
/// Query walks by index — no heap allocation, no pointer chasing.
#[derive(Clone, Debug)]
pub struct CompiledPattern {
    /// Arena of all pattern nodes.
    pub nodes: Vec<PatternNode>,
    /// Index of the root node in `nodes`.
    pub root: usize,
    /// True if every Atom in the pattern is `Value::Control`.
    /// Control-voice patterns are compiled to block-rate wavetables
    /// instead of discrete events.
    pub is_control: bool,
}

/// A single node in the pattern arena.
#[allow(missing_docs)]
#[derive(Clone, Debug)]
pub enum PatternNode {
    /// A leaf node that produces a single event.
    Atom { value: Value },
    /// Produces no events.
    Silence,
    /// Transparent wrapper — delegates to child. Marks a compound as indivisible.
    Freeze { child: usize },
    /// Speed up a child pattern by `factor`.
    Fast { factor: Time, child: usize },
    /// Slow down a child pattern by `factor`.
    Slow { factor: Time, child: usize },
    /// Shift events earlier in time by `offset`.
    Early { offset: Time, child: usize },
    /// Shift events later in time by `offset`.
    Late { offset: Time, child: usize },
    /// Reverse the child pattern within each cycle.
    Rev { child: usize },
    /// Concatenate children sequentially across the cycle.
    Cat { children: SmallVec<[usize; 8]> },
    /// Layer children on top of each other (polyphonic).
    Stack { children: SmallVec<[usize; 8]> },
    /// Apply transform every Nth cycle, otherwise pass through child.
    Every { n: u32, transform: usize, child: usize },
    /// Euclidean rhythm: distribute `pulses` hits across `steps` slots.
    Euclid { pulses: u32, steps: u32, rotation: u32, child: usize },
    /// Randomly drop events with probability `prob`, seeded for reproducibility.
    Degrade { prob: f64, seed: u64, child: usize },
}

impl CompiledPattern {
    /// Create a pattern with a single atom.
    #[must_use]
    pub fn atom(value: Value) -> Self {
        let is_control = matches!(value, Value::Control { .. });
        Self {
            nodes: vec![PatternNode::Atom { value }],
            root: 0,
            is_control,
        }
    }

    /// Create a silence pattern.
    #[must_use]
    pub fn silence() -> Self {
        Self {
            nodes: vec![PatternNode::Silence],
            root: 0,
            is_control: false,
        }
    }

    /// Create an empty pattern for manual arena construction (tests).
    #[must_use]
    pub fn empty() -> Self {
        Self {
            nodes: Vec::new(),
            root: 0,
            is_control: false,
        }
    }

    /// Push a node into the arena, returning its index.
    pub fn push(&mut self, node: PatternNode) -> usize {
        let idx = self.nodes.len();
        self.nodes.push(node);
        idx
    }

    /// True if every Atom in the arena is `Value::Control` and at least one Atom exists.
    pub(crate) fn detect_control(nodes: &[PatternNode]) -> bool {
        let mut has_atom = false;
        for node in nodes {
            if let PatternNode::Atom { value } = node {
                has_atom = true;
                if !matches!(value, Value::Control { .. }) {
                    return false;
                }
            }
        }
        has_atom
    }
}

pub use query::query;
