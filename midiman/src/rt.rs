//! Real-time thread priority helpers.
//!
//! Uses the `thread-priority` crate for a safe, cross-platform API.
//! Failure is non-fatal — the thread continues at default priority.

/// Attempt to raise the current thread to the highest available priority.
/// Logs a warning on failure but does not panic.
pub fn set_realtime_priority() {
    use thread_priority::{set_current_thread_priority, ThreadPriority};

    if let Err(e) = set_current_thread_priority(ThreadPriority::Max) {
        eprintln!("warning: could not set realtime thread priority: {e:?}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn set_realtime_priority_does_not_panic() {
        // May fail silently on CI/unprivileged environments — that's fine
        set_realtime_priority();
    }
}
