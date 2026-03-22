//! BPM-based clock mapping between wall time and cycle time.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Instant;

use crate::time::Time;

/// Converts between wall-clock time and cycle-time using a fixed BPM.
/// One cycle = one "bar" in Tidal terms. At 120 BPM with 4 beats/cycle,
/// one cycle = 2 seconds.
pub struct Clock {
    bpm: f64,
    beats_per_cycle: f64,
    start: Instant,
}

impl Clock {
    /// Create a clock starting from now.
    #[must_use]
    pub fn new(bpm: f64, beats_per_cycle: f64) -> Self {
        Self {
            bpm,
            beats_per_cycle,
            start: Instant::now(),
        }
    }

    /// Create a clock with an explicit start instant (useful for tests).
    #[must_use]
    pub fn with_start(bpm: f64, beats_per_cycle: f64, start: Instant) -> Self {
        Self {
            bpm,
            beats_per_cycle,
            start,
        }
    }

    /// Seconds per cycle.
    #[must_use]
    pub fn cycle_duration_secs(&self) -> f64 {
        self.beats_per_cycle * 60.0 / self.bpm
    }

    /// Convert a cycle-time to wall-clock seconds from start.
    #[must_use]
    pub fn cycle_to_secs(&self, cycle: Time) -> f64 {
        let cycle_f = cycle.num as f64 / cycle.den as f64;
        cycle_f * self.cycle_duration_secs()
    }

    /// Returns the current BPM.
    #[must_use]
    pub fn bpm(&self) -> f64 {
        self.bpm
    }

    /// Returns the beats per cycle.
    #[must_use]
    pub fn beats_per_cycle(&self) -> f64 {
        self.beats_per_cycle
    }

    /// Update the BPM (takes effect on the next tick).
    pub fn set_bpm(&mut self, bpm: f64) {
        self.bpm = bpm;
    }

    /// Wall-clock instant when the given whole cycle number starts.
    /// Pure f64 arithmetic — no `Time` involved.
    #[must_use]
    pub fn cycle_start_instant(&self, cycle: i64) -> Instant {
        let secs = cycle as f64 * self.cycle_duration_secs();
        self.start + std::time::Duration::from_secs_f64(secs)
    }

    /// Convert a cycle-time onset to a wall-clock instant.
    #[must_use]
    pub fn onset_to_instant(&self, cycle: Time) -> Instant {
        let secs = self.cycle_to_secs(cycle);
        self.start + std::time::Duration::from_secs_f64(secs)
    }
}

/// Lock-free shared BPM value, readable from the scheduler thread
/// and writable from the IPC thread.
#[derive(Clone)]
pub struct SharedBpm(Arc<AtomicU64>);

impl SharedBpm {
    /// Create a new shared BPM with the given initial value.
    #[must_use]
    pub fn new(bpm: f64) -> Self {
        Self(Arc::new(AtomicU64::new(bpm.to_bits())))
    }

    /// Read the current BPM.
    #[must_use]
    pub fn get(&self) -> f64 {
        f64::from_bits(self.0.load(Ordering::Relaxed))
    }

    /// Set a new BPM value.
    pub fn set(&self, bpm: f64) {
        self.0.store(bpm.to_bits(), Ordering::Relaxed);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn shared_bpm_roundtrips() {
        let bpm = SharedBpm::new(140.0);
        assert!((bpm.get() - 140.0).abs() < f64::EPSILON);
        bpm.set(95.5);
        assert!((bpm.get() - 95.5).abs() < f64::EPSILON);
    }

    #[test]
    fn shared_bpm_special_values() {
        let bpm = SharedBpm::new(0.0);
        assert!((bpm.get()).abs() < f64::EPSILON);
        bpm.set(999_999.999);
        assert!((bpm.get() - 999_999.999).abs() < f64::EPSILON);
    }

    #[test]
    fn cycle_duration_at_120_bpm() {
        let clock = Clock::new(120.0, 4.0);
        // 4 beats at 120 BPM = 2 seconds per cycle
        assert!((clock.cycle_duration_secs() - 2.0).abs() < 1e-10);
    }

    #[test]
    fn cycle_duration_at_60_bpm() {
        let clock = Clock::new(60.0, 4.0);
        // 4 beats at 60 BPM = 4 seconds per cycle
        assert!((clock.cycle_duration_secs() - 4.0).abs() < 1e-10);
    }

    #[test]
    fn cycle_start_instant_at_cycle_zero() {
        let start = Instant::now();
        let clock = Clock::with_start(120.0, 4.0, start);
        assert_eq!(clock.cycle_start_instant(0), start);
    }

    #[test]
    fn cycle_start_instant_at_cycle_one() {
        let start = Instant::now();
        let clock = Clock::with_start(120.0, 4.0, start);
        // Cycle 1 starts at 2 seconds (120 BPM, 4 beats/cycle)
        let expected = start + Duration::from_secs(2);
        assert_eq!(clock.cycle_start_instant(1), expected);
    }

    #[test]
    fn cycle_start_instant_at_high_cycle() {
        let start = Instant::now();
        let clock = Clock::with_start(120.0, 4.0, start);
        // Cycle 1000 starts at 2000 seconds
        let expected = start + Duration::from_secs(2000);
        assert_eq!(clock.cycle_start_instant(1000), expected);
    }

    #[test]
    fn cycle_to_secs_roundtrip() {
        let clock = Clock::new(120.0, 4.0);
        let cycle = Time::new(3, 2); // 1.5 cycles
        let secs = clock.cycle_to_secs(cycle);
        // 1.5 cycles * 2 seconds/cycle = 3.0 seconds
        assert!((secs - 3.0).abs() < 1e-10);
    }
}
