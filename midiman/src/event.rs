//! Events produced by pattern evaluation.
//!
//! An [`Event`] carries a value (MIDI note, CC, or OSC message) along with
//! two time arcs: `whole` (the event's natural span) and `part` (the portion
//! that falls within the queried range). This whole/part model enables correct
//! behavior under time-shifting combinators like `Fast` and `Slow`.

use serde::{Deserialize, Serialize};

use crate::time::Arc;

/// A control signal value produced by pattern evaluation.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum Value {
    Note {
        channel: u8,
        note: u8,
        velocity: u8,
        dur: f64,
    },
    Cc {
        channel: u8,
        controller: u8,
        value: u8,
    },
    Osc {
        address: String,
        args: Vec<OscArg>,
    },
}

/// An argument in an OSC message.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum OscArg {
    Float(f64),
    Int(i32),
    Str(String),
}

/// An event produced by querying a pattern over a time arc.
///
/// `whole` is the arc of the "whole" event (its natural span in the pattern).
/// `part` is the portion of the event that falls within the queried arc.
/// When a pattern is time-shifted (fast/slow), `part` may be a subset of `whole`.
#[derive(Clone, Debug, PartialEq)]
pub struct Event<V> {
    pub whole: Option<Arc>,
    pub part: Arc,
    pub value: V,
}

impl<V> Event<V> {
    #[must_use]
    pub fn new(whole: Option<Arc>, part: Arc, value: V) -> Self {
        Self { whole, part, value }
    }

    /// Does the event onset (start of whole) fall within the queried part?
    /// Used for deduplication: only fire events whose onset is in the query window.
    #[must_use]
    pub fn has_onset(&self) -> bool {
        match self.whole {
            Some(w) => w.start >= self.part.start && w.start < self.part.end,
            None => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::time::Time;

    #[test]
    fn event_has_onset_when_whole_starts_in_part() {
        let event = Event::new(
            Some(Arc::new(Time::new(1, 4), Time::new(1, 2))),
            Arc::new(Time::zero(), Time::one()),
            Value::Note {
                channel: 0,
                note: 60,
                velocity: 100,
                dur: 0.5,
            },
        );
        assert!(event.has_onset());
    }

    #[test]
    fn event_no_onset_when_whole_starts_before_part() {
        let event = Event::new(
            Some(Arc::new(Time::zero(), Time::new(1, 2))),
            Arc::new(Time::new(1, 4), Time::new(1, 2)),
            Value::Cc {
                channel: 0,
                controller: 1,
                value: 127,
            },
        );
        assert!(!event.has_onset());
    }

    #[test]
    fn event_no_onset_when_whole_is_none() {
        let event: Event<Value> = Event::new(
            None,
            Arc::new(Time::zero(), Time::one()),
            Value::Osc {
                address: "/test".into(),
                args: vec![OscArg::Float(1.0)],
            },
        );
        assert!(!event.has_onset());
    }

    #[test]
    fn event_onset_at_part_boundary_start() {
        let event = Event::new(
            Some(Arc::new(Time::new(1, 2), Time::one())),
            Arc::new(Time::new(1, 2), Time::one()),
            Value::Note {
                channel: 0,
                note: 64,
                velocity: 80,
                dur: 0.25,
            },
        );
        assert!(event.has_onset());
    }

    #[test]
    fn event_onset_at_part_boundary_end_excluded() {
        // whole starts exactly at part.end — half-open, so no onset
        let event = Event::new(
            Some(Arc::new(Time::one(), Time::new(3, 2))),
            Arc::new(Time::new(1, 2), Time::one()),
            Value::Note {
                channel: 0,
                note: 64,
                velocity: 80,
                dur: 0.25,
            },
        );
        assert!(!event.has_onset());
    }
}
