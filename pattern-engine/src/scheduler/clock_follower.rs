//! MIDI clock follower — derives BPM from incoming 24-ppqn clock ticks.
//!
//! Pure state machine with no I/O dependencies. Feed it `Instant` timestamps
//! from the midir callback; it returns a BPM estimate when enough ticks have
//! arrived. Uses an exponential moving average with a jitter gate to reject
//! outlier ticks (dropped tick, USB latency spike).

use std::time::{Duration, Instant};

/// EMA smoothing factor. Lower = smoother, slower to react.
/// 0.05 tracks tempo ramps within ~1 beat while rejecting jitter.
const ALPHA: f64 = 0.05;

/// Reject ticks where the interval deviates more than 30% from the current
/// estimate. Catches dropped ticks and USB latency spikes.
const OUTLIER_RATIO: f64 = 1.3;

/// Standard MIDI clock: 24 ticks per quarter note.
const TICKS_PER_BEAT: f64 = 24.0;

/// Derives BPM from a stream of MIDI clock ticks (24 ppqn).
///
/// Feed ticks via [`on_tick`], signal transport via [`on_start`]/[`on_stop`].
/// The follower needs at least 2 ticks to produce a BPM estimate.
pub struct ClockFollower {
    ema_interval: f64,
    last_tick: Option<Instant>,
    running: bool,
}

impl Default for ClockFollower {
    fn default() -> Self {
        Self::new()
    }
}

impl ClockFollower {
    /// Create a new follower in stopped state.
    #[must_use]
    pub fn new() -> Self {
        Self {
            ema_interval: 0.0,
            last_tick: None,
            running: false,
        }
    }

    /// Process an incoming clock tick. Returns the current BPM estimate
    /// if the tick was accepted (not an outlier) and enough data exists.
    pub fn on_tick(&mut self, now: Instant) -> Option<f64> {
        let prev = self.last_tick.replace(now);
        let prev = prev?;
        let interval = now.duration_since(prev).as_secs_f64();
        if interval <= 0.0 {
            return None;
        }

        if self.ema_interval == 0.0 {
            // First interval — seed the EMA.
            self.ema_interval = interval;
        } else {
            // Jitter gate: reject outliers.
            let ratio = interval / self.ema_interval;
            if !(1.0 / OUTLIER_RATIO..=OUTLIER_RATIO).contains(&ratio) {
                // Outlier — don't update EMA, don't update last_tick to the
                // outlier time (keep previous good tick for next interval).
                self.last_tick = Some(prev);
                return None;
            }
            // EMA update.
            self.ema_interval = ALPHA.mul_add(interval, (1.0 - ALPHA) * self.ema_interval);
        }

        Some(interval_to_bpm(self.ema_interval))
    }

    /// Handle MIDI Start (0xFA). Resets the follower for a new transport cycle.
    pub fn on_start(&mut self, now: Instant) {
        self.last_tick = Some(now);
        self.running = true;
        // Don't reset ema_interval — preserve tempo estimate across start/stop.
    }

    /// Handle MIDI Stop (0xFC).
    pub fn on_stop(&mut self) {
        self.running = false;
    }

    /// Whether the follower is in running state (after Start, before Stop).
    #[must_use]
    pub fn running(&self) -> bool {
        self.running
    }

    /// True if no tick has arrived within `timeout` of `now`.
    #[must_use]
    pub fn is_timed_out(&self, now: Instant, timeout: Duration) -> bool {
        self.last_tick
            .is_some_and(|last| now.duration_since(last) > timeout)
    }

    /// Current EMA tick interval in seconds, or None if no intervals yet.
    #[must_use]
    pub fn expected_interval(&self) -> Option<f64> {
        if self.ema_interval > 0.0 {
            Some(self.ema_interval)
        } else {
            None
        }
    }

    /// Current BPM estimate, or None if no ticks received yet.
    #[must_use]
    pub fn bpm(&self) -> Option<f64> {
        if self.ema_interval > 0.0 {
            Some(interval_to_bpm(self.ema_interval))
        } else {
            None
        }
    }
}

fn interval_to_bpm(tick_interval_secs: f64) -> f64 {
    60.0 / (tick_interval_secs * TICKS_PER_BEAT)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Generate tick instants at a steady tempo.
    fn steady_ticks(start: Instant, bpm: f64, count: usize) -> Vec<Instant> {
        let interval = Duration::from_secs_f64(60.0 / (bpm * TICKS_PER_BEAT));
        (0..count).map(|i| start + interval * i as u32).collect()
    }

    #[test]
    fn steady_120_bpm_converges() {
        let mut follower = ClockFollower::new();
        let start = Instant::now();
        let ticks = steady_ticks(start, 120.0, 96); // 4 beats

        let mut last_bpm = None;
        for t in &ticks {
            if let Some(bpm) = follower.on_tick(*t) {
                last_bpm = Some(bpm);
            }
        }

        let bpm = last_bpm.expect("should have BPM after 96 ticks");
        assert!(
            (bpm - 120.0).abs() < 0.5,
            "expected ~120 BPM, got {bpm}"
        );
    }

    #[test]
    fn steady_120_bpm_within_half_bpm_after_48_ticks() {
        let mut follower = ClockFollower::new();
        let start = Instant::now();
        let ticks = steady_ticks(start, 120.0, 48); // 2 beats

        let mut last_bpm = None;
        for t in &ticks {
            if let Some(bpm) = follower.on_tick(*t) {
                last_bpm = Some(bpm);
            }
        }

        let bpm = last_bpm.expect("should have BPM after 48 ticks");
        assert!(
            (bpm - 120.0).abs() < 0.5,
            "expected within ±0.5 of 120 BPM after 48 ticks, got {bpm}"
        );
    }

    #[test]
    fn tempo_ramp_120_to_140() {
        let mut follower = ClockFollower::new();
        let start = Instant::now();

        // 48 ticks at 120 BPM to establish baseline.
        let ticks_120 = steady_ticks(start, 120.0, 48);
        for t in &ticks_120 {
            follower.on_tick(*t);
        }

        // 96 ticks at 140 BPM (ramp).
        let ramp_start = *ticks_120.last().unwrap();
        let ticks_140 = steady_ticks(ramp_start, 140.0, 96);
        let mut last_bpm = None;
        for t in &ticks_140[1..] {
            // skip first (same as last of 120)
            if let Some(bpm) = follower.on_tick(*t) {
                last_bpm = Some(bpm);
            }
        }

        let bpm = last_bpm.expect("should have BPM");
        // After 96 ticks (~4 beats at 140), should track within 2 BPM.
        assert!(
            (bpm - 140.0).abs() < 2.0,
            "expected ~140 BPM after ramp, got {bpm}"
        );
    }

    #[test]
    fn dropped_tick_rejected() {
        let mut follower = ClockFollower::new();
        let start = Instant::now();
        let interval = Duration::from_secs_f64(60.0 / (120.0 * TICKS_PER_BEAT));

        // Establish baseline: 10 ticks at 120 BPM.
        for i in 0..10 {
            follower.on_tick(start + interval * i);
        }
        let bpm_before = follower.bpm().unwrap();

        // Drop a tick (next tick arrives at 2x the expected interval).
        let late_tick = start + interval * 11; // skipped tick 10
        let result = follower.on_tick(late_tick);
        assert!(result.is_none(), "outlier tick should be rejected");

        // BPM estimate should be unchanged.
        let bpm_after = follower.bpm().unwrap();
        assert!(
            (bpm_before - bpm_after).abs() < 0.01,
            "BPM should not change after rejected outlier"
        );
    }

    #[test]
    fn jitter_within_30_pct_accepted() {
        let mut follower = ClockFollower::new();
        let start = Instant::now();
        let base_interval = Duration::from_secs_f64(60.0 / (120.0 * TICKS_PER_BEAT));

        // Establish baseline: 10 ticks at 120 BPM.
        for i in 0..10 {
            follower.on_tick(start + base_interval * i);
        }

        // Tick with +20% jitter (within 30% threshold).
        let jittery = start + base_interval * 10 + base_interval / 5;
        let result = follower.on_tick(jittery);
        assert!(result.is_some(), "±20% jitter should be accepted");
    }

    #[test]
    fn jitter_beyond_30_pct_rejected() {
        let mut follower = ClockFollower::new();
        let start = Instant::now();
        let base_interval = Duration::from_secs_f64(60.0 / (120.0 * TICKS_PER_BEAT));

        // Establish baseline.
        for i in 0..10 {
            follower.on_tick(start + base_interval * i);
        }

        // Tick with +40% jitter (beyond 30% threshold).
        let jittery = start + base_interval * 10 + base_interval * 2 / 5;
        let result = follower.on_tick(jittery);
        assert!(result.is_none(), ">30% jitter should be rejected");
    }

    #[test]
    fn start_resets_last_tick() {
        let mut follower = ClockFollower::new();
        let start = Instant::now();
        let interval = Duration::from_secs_f64(60.0 / (120.0 * TICKS_PER_BEAT));

        // Feed some ticks.
        for i in 0..10 {
            follower.on_tick(start + interval * i);
        }

        // Long gap, then start.
        let new_start = start + Duration::from_secs(10);
        follower.on_start(new_start);
        assert!(follower.running());

        // First tick after start should not produce outlier.
        let first_after = new_start + interval;
        let result = follower.on_tick(first_after);
        assert!(result.is_some(), "first tick after start should be accepted");
    }

    #[test]
    fn stop_clears_running() {
        let mut follower = ClockFollower::new();
        follower.on_start(Instant::now());
        assert!(follower.running());
        follower.on_stop();
        assert!(!follower.running());
    }

    #[test]
    fn timeout_detection() {
        let mut follower = ClockFollower::new();
        let start = Instant::now();
        let timeout = Duration::from_secs(2);

        // No ticks yet — not timed out (no last_tick).
        assert!(!follower.is_timed_out(start, timeout));

        // One tick, check immediately — not timed out.
        follower.on_tick(start);
        assert!(!follower.is_timed_out(start, timeout));

        // 3 seconds later — timed out.
        let later = start + Duration::from_secs(3);
        assert!(follower.is_timed_out(later, timeout));
    }

    #[test]
    fn bpm_returns_none_before_any_ticks() {
        let follower = ClockFollower::new();
        assert!(follower.bpm().is_none());
    }

    #[test]
    fn bpm_returns_some_after_two_ticks() {
        let mut follower = ClockFollower::new();
        let start = Instant::now();
        let interval = Duration::from_secs_f64(60.0 / (120.0 * TICKS_PER_BEAT));
        follower.on_tick(start);
        follower.on_tick(start + interval);
        assert!(follower.bpm().is_some());
    }
}
