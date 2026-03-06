//! BPM-based clock mapping between wall time and cycle time.

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

    /// Convert a wall-clock instant to cycle-time as a rational.
    /// Uses high-precision: microsecond numerator, cycle-duration denominator.
    #[must_use]
    pub fn instant_to_cycle(&self, now: Instant) -> Time {
        let elapsed_secs = now.duration_since(self.start).as_secs_f64();
        let cycles = elapsed_secs / self.cycle_duration_secs();
        // Convert to rational with microsecond precision
        let micros = (cycles * 1_000_000.0) as i64;
        Time::new(micros, 1_000_000)
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

    /// Update the BPM (takes effect on the next tick).
    pub fn set_bpm(&mut self, bpm: f64) {
        self.bpm = bpm;
    }

    /// Convert a cycle-time onset to a wall-clock instant.
    #[must_use]
    pub fn onset_to_instant(&self, cycle: Time) -> Instant {
        let secs = self.cycle_to_secs(cycle);
        self.start + std::time::Duration::from_secs_f64(secs)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

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
    fn instant_to_cycle_at_start_is_zero() {
        let start = Instant::now();
        let clock = Clock::with_start(120.0, 4.0, start);
        let cycle = clock.instant_to_cycle(start);
        assert_eq!(cycle, Time::zero());
    }

    #[test]
    fn instant_to_cycle_after_one_cycle() {
        let start = Instant::now();
        let clock = Clock::with_start(120.0, 4.0, start);
        // One cycle = 2 seconds at 120 BPM, 4 beats/cycle
        let later = start + Duration::from_secs(2);
        let cycle = clock.instant_to_cycle(later);
        // Should be approximately 1.0 (within microsecond precision)
        let cycle_f = cycle.num as f64 / cycle.den as f64;
        assert!((cycle_f - 1.0).abs() < 1e-6);
    }

    #[test]
    fn instant_to_cycle_half_cycle() {
        let start = Instant::now();
        let clock = Clock::with_start(120.0, 4.0, start);
        let later = start + Duration::from_secs(1);
        let cycle = clock.instant_to_cycle(later);
        let cycle_f = cycle.num as f64 / cycle.den as f64;
        assert!((cycle_f - 0.5).abs() < 1e-6);
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
