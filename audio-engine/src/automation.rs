//! Automation shapes and parameter modulation.
//!
//! An [`Automation`] drives a single node parameter through a repeating
//! (or one-shot) waveform at block rate. [`AutoShape`] defines the
//! waveform — sine, triangle, ramp, etc. — evaluated at normalised time.

use std::f32::consts::PI;

/// Waveform shape for parameter automation, evaluated at normalised time t in [0, 1).
#[derive(Debug, Clone)]
pub enum AutoShape {
    Sine,
    Tri,
    Ramp,
    RampDown,
    Square,
    Exp,
    Pulse { duty: f32 },
    Custom { table: Vec<f32> },
}

impl AutoShape {
    /// Evaluate shape at normalized time `t` in [0, 1) producing a value in [0, 1].
    #[must_use] pub fn eval(&self, t: f32) -> f32 {
        match self {
            Self::Sine => 0.5f32.mul_add((t * 2.0 * PI).sin(), 0.5),
            Self::Tri => 1.0 - 2.0f32.mul_add(t, -1.0).abs(),
            Self::Ramp => t,
            Self::RampDown => 1.0 - t,
            Self::Square => {
                if t < 0.5 {
                    1.0
                } else {
                    0.0
                }
            }
            Self::Exp => t * t,
            Self::Pulse { duty } => {
                if t < *duty {
                    1.0
                } else {
                    0.0
                }
            }
            Self::Custom { table } => {
                if table.is_empty() {
                    return 0.0;
                }
                let idx = (t * table.len() as f32) as usize;
                table[idx.min(table.len() - 1)]
            }
        }
    }
}

/// Block-rate parameter automation targeting a single node parameter.
#[derive(Debug, Clone)]
pub struct Automation {
    pub node_id: String,
    pub param: String,
    pub shape: AutoShape,
    pub lo: f32,
    pub hi: f32,
    pub period_samples: usize,
    pub phase: usize,
    pub active: bool,
    pub one_shot: bool,
}

impl Automation {
    /// Current output value mapped to [lo, hi].
    #[must_use] pub fn eval(&self) -> f32 {
        if self.period_samples == 0 {
            return self.lo;
        }
        let t = self.phase as f32 / self.period_samples as f32;
        let normalized = self.shape.eval(t);
        (self.hi - self.lo).mul_add(normalized, self.lo)
    }

    /// Advance phase by `samples`. Wraps for looping, clamps for one-shot.
    pub const fn advance(&mut self, samples: usize) {
        if self.period_samples == 0 {
            self.active = false;
            return;
        }
        self.phase += samples;
        if self.phase >= self.period_samples {
            if self.one_shot {
                self.phase = self.period_samples - 1;
                self.active = false;
            } else {
                self.phase %= self.period_samples;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sine_midpoint() {
        let shape = AutoShape::Sine;
        let val = shape.eval(0.5);
        assert!((val - 0.5).abs() < 1e-5, "Sine(0.5) = {val}, expected ~0.5");
    }

    #[test]
    fn test_sine_peak() {
        let shape = AutoShape::Sine;
        let val = shape.eval(0.25);
        assert!(
            (val - 1.0).abs() < 1e-5,
            "Sine(0.25) = {val}, expected ~1.0"
        );
    }

    #[test]
    fn test_tri_endpoints() {
        let shape = AutoShape::Tri;
        let at_zero = shape.eval(0.0);
        let at_half = shape.eval(0.5);
        assert!(at_zero.abs() < 1e-5, "Tri(0.0) = {at_zero}, expected ~0.0");
        assert!(
            (at_half - 1.0).abs() < 1e-5,
            "Tri(0.5) = {at_half}, expected ~1.0"
        );
    }

    #[test]
    fn test_ramp() {
        let shape = AutoShape::Ramp;
        assert!((shape.eval(0.0)).abs() < 1e-5);
        assert!((shape.eval(1.0) - 1.0).abs() < 1e-5);
    }

    #[test]
    fn test_pulse() {
        let shape = AutoShape::Pulse { duty: 0.5 };
        assert!((shape.eval(0.25) - 1.0).abs() < 1e-5);
        assert!(shape.eval(0.75).abs() < 1e-5);
    }

    #[test]
    fn test_custom_wavetable() {
        let table = vec![0.0, 0.25, 0.5, 1.0];
        let shape = AutoShape::Custom { table };
        // t=0.0 -> idx 0 -> 0.0
        assert!((shape.eval(0.0)).abs() < 1e-5);
        // t=0.5 -> idx 2 -> 0.5
        assert!((shape.eval(0.5) - 0.5).abs() < 1e-5);
        // t=0.75 -> idx 3 -> 1.0
        assert!((shape.eval(0.75) - 1.0).abs() < 1e-5);
        // empty table returns 0
        let empty = AutoShape::Custom { table: vec![] };
        assert!(empty.eval(0.5).abs() < 1e-5);
    }

    #[test]
    fn test_automation_eval() {
        let auto = Automation {
            node_id: "osc1".into(),
            param: "freq".into(),
            shape: AutoShape::Sine,
            lo: 100.0,
            hi: 200.0,
            period_samples: 1000,
            phase: 250, // t=0.25 -> sine peak -> normalized=1.0 -> value=200
            active: true,
            one_shot: false,
        };
        let val = auto.eval();
        assert!((val - 200.0).abs() < 0.1, "expected ~200.0, got {val}");
    }

    #[test]
    fn test_automation_advance_loops() {
        let mut auto = Automation {
            node_id: "n".into(),
            param: "p".into(),
            shape: AutoShape::Ramp,
            lo: 0.0,
            hi: 1.0,
            period_samples: 1000,
            phase: 900,
            active: true,
            one_shot: false,
        };
        auto.advance(200); // 900 + 200 = 1100 -> wraps to 100
        assert_eq!(auto.phase, 100);
        assert!(auto.active);
    }

    #[test]
    fn test_automation_one_shot_holds() {
        let mut auto = Automation {
            node_id: "n".into(),
            param: "p".into(),
            shape: AutoShape::Ramp,
            lo: 0.0,
            hi: 1.0,
            period_samples: 1000,
            phase: 900,
            active: true,
            one_shot: true,
        };
        auto.advance(200); // exceeds period
        assert_eq!(auto.phase, 999);
        assert!(!auto.active);
    }

    #[test]
    fn test_automation_zero_period_eval_returns_lo() {
        let auto = Automation {
            node_id: "n".into(),
            param: "p".into(),
            shape: AutoShape::Sine,
            lo: 42.0,
            hi: 100.0,
            period_samples: 0,
            phase: 0,
            active: true,
            one_shot: false,
        };
        assert!((auto.eval() - 42.0).abs() < 1e-5);
    }

    #[test]
    fn test_automation_zero_period_advance_deactivates() {
        let mut auto = Automation {
            node_id: "n".into(),
            param: "p".into(),
            shape: AutoShape::Sine,
            lo: 0.0,
            hi: 1.0,
            period_samples: 0,
            phase: 0,
            active: true,
            one_shot: false,
        };
        auto.advance(256); // must not panic
        assert!(!auto.active, "zero-period automation should deactivate");
    }
}
