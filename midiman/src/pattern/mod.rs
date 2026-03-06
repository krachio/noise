mod query;

use smallvec::SmallVec;

use crate::event::Value;
use crate::time::Time;

/// A compiled pattern stored as a flat arena of nodes.
/// Query walks by index — no heap allocation, no pointer chasing.
#[derive(Clone, Debug)]
pub struct CompiledPattern {
    pub nodes: Vec<PatternNode>,
    pub root: usize,
}

/// A single node in the pattern arena.
#[derive(Clone, Debug)]
pub enum PatternNode {
    Atom { value: Value },
    Silence,
    Fast { factor: Time, child: usize },
    Slow { factor: Time, child: usize },
    Early { offset: Time, child: usize },
    Late { offset: Time, child: usize },
    Rev { child: usize },
    Cat { children: SmallVec<[usize; 8]> },
    Stack { children: SmallVec<[usize; 8]> },
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
