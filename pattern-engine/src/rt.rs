//! Real-time thread priority helpers.
//!
//! Uses the `thread-priority` crate for a safe, cross-platform API.
//! Failure is non-fatal — the thread continues at default priority.

/// Attempt to raise the current thread to the highest available priority.
/// Returns `true` if priority was raised, `false` if it failed (non-fatal).
/// Logs a warning on failure.
pub fn set_realtime_priority() -> bool {
    use thread_priority::{ThreadPriority, set_current_thread_priority};

    match set_current_thread_priority(ThreadPriority::Max) {
        Ok(()) => true,
        Err(e) => {
            eprintln!("warning: could not set realtime thread priority: {e:?}");
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn set_realtime_priority_is_deterministic() {
        let first = set_realtime_priority();
        let second = set_realtime_priority();
        assert_eq!(
            first, second,
            "repeated calls should return the same result"
        );
    }

    #[test]
    fn set_realtime_priority_changes_thread_priority() {
        use thread_priority::get_current_thread_priority;

        let before = get_current_thread_priority().expect("should read priority");
        let succeeded = set_realtime_priority();
        let after = get_current_thread_priority().expect("should read priority");

        if succeeded {
            assert!(
                after >= before,
                "priority should not decrease after successful set"
            );
        } else {
            assert_eq!(
                before, after,
                "priority should be unchanged after failed set"
            );
        }
    }
}
