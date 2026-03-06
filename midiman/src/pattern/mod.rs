//! Compiled pattern representation and query evaluator.
//!
//! Patterns are stored as a flat arena of [`PatternNode`]s indexed by `usize`.
//! This avoids heap allocation and pointer chasing during evaluation.
//! [`query()`] walks the arena recursively to produce events for a given
//! time arc.

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
}

/// A single node in the pattern arena.
#[derive(Clone, Debug)]
pub enum PatternNode {
    /// A leaf node that produces a single event.
    Atom { value: Value },
    /// Produces no events.
    Silence,
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
        Self {
            nodes: vec![PatternNode::Atom { value }],
            root: 0,
        }
    }

    /// Create a silence pattern.
    #[must_use]
    pub fn silence() -> Self {
        Self {
            nodes: vec![PatternNode::Silence],
            root: 0,
        }
    }

    /// Push a node into the arena, returning its index.
    pub fn push(&mut self, node: PatternNode) -> usize {
        let idx = self.nodes.len();
        self.nodes.push(node);
        idx
    }
}

pub use query::query;
