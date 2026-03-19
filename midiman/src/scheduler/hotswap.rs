//! Lock-free pattern hot-swap via `arc-swap`.

use std::sync::Arc;

use arc_swap::ArcSwap;

use crate::pattern::CompiledPattern;

/// A lock-free hot-swappable slot for a compiled pattern.
/// The scheduler reads via `load()` (wait-free on most platforms).
/// The IPC thread writes via `swap()`.
pub struct SwapSlot {
    inner: ArcSwap<CompiledPattern>,
}

impl SwapSlot {
    /// Create a new slot with an initial pattern.
    #[must_use]
    pub fn new(pattern: CompiledPattern) -> Self {
        Self {
            inner: ArcSwap::from_pointee(pattern),
        }
    }

    /// Load the current pattern. Lock-free.
    #[must_use]
    pub fn load(&self) -> arc_swap::Guard<Arc<CompiledPattern>> {
        self.inner.load()
    }

    /// Atomically swap in a new pattern.
    pub fn swap(&self, pattern: CompiledPattern) {
        self.inner.store(Arc::new(pattern));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::Value;
    use crate::pattern::query;
    use crate::time::Arc as TimeArc;

    fn note(n: u8) -> Value {
        Value::Note {
            channel: 0,
            note: n,
            velocity: 100,
            dur: 0.5,
        }
    }

    #[test]
    fn load_returns_initial_pattern() {
        let slot = SwapSlot::new(CompiledPattern::atom(note(60)));
        let pat = slot.load();
        let events = query(&pat, pat.root, TimeArc::cycle(0));
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].value, note(60));
    }

    #[test]
    fn swap_replaces_pattern() {
        let slot = SwapSlot::new(CompiledPattern::atom(note(60)));
        slot.swap(CompiledPattern::atom(note(72)));
        let pat = slot.load();
        let events = query(&pat, pat.root, TimeArc::cycle(0));
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].value, note(72));
    }

    #[test]
    fn swap_is_safe_across_threads() {
        use std::sync::Arc as StdArc;
        use std::thread;

        let slot = StdArc::new(SwapSlot::new(CompiledPattern::atom(note(60))));
        let slot2 = StdArc::clone(&slot);

        let writer = thread::spawn(move || {
            for i in 0..100 {
                slot2.swap(CompiledPattern::atom(note(i)));
            }
        });

        // Reader should always see a valid pattern
        for _ in 0..100 {
            let pat = slot.load();
            let events = query(&pat, pat.root, TimeArc::cycle(0));
            assert_eq!(events.len(), 1);
        }

        writer.join().unwrap();
    }
}
