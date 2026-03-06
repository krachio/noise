use std::cmp::Ordering;
use std::fmt;
use std::ops::{Add, Div, Mul, Neg, Sub};

fn gcd(mut a: u64, mut b: u64) -> u64 {
    while b != 0 {
        let t = b;
        b = a % b;
        a = t;
    }
    a
}

/// Rational number representing a point or duration in cycle-time.
/// Numerator is signed, denominator is always positive and nonzero.
#[derive(Clone, Copy)]
pub struct Time {
    pub num: i64,
    pub den: u64,
}

impl Time {
    #[must_use]
    pub fn new(num: i64, den: u64) -> Self {
        assert!(den != 0, "Time denominator must be nonzero");
        let g = gcd(num.unsigned_abs(), den);
        let sign = num.signum();
        Self {
            num: sign * (num.unsigned_abs() / g) as i64,
            den: den / g,
        }
    }

    #[must_use]
    pub fn whole(n: i64) -> Self {
        Self { num: n, den: 1 }
    }

    #[must_use]
    pub fn zero() -> Self {
        Self { num: 0, den: 1 }
    }

    #[must_use]
    pub fn one() -> Self {
        Self { num: 1, den: 1 }
    }

    /// Integer part (floor division towards negative infinity).
    #[must_use]
    pub fn floor(self) -> i64 {
        if self.num >= 0 {
            self.num / self.den as i64
        } else {
            // For negative: -((-num + den - 1) / den)
            let abs_num = self.num.unsigned_abs();
            -(((abs_num + self.den - 1) / self.den) as i64)
        }
    }

    /// Fractional part in [0, 1). Always non-negative.
    #[must_use]
    pub fn fract(self) -> Self {
        let floor = self.floor();
        self - Self::whole(floor)
    }

    #[must_use]
    pub fn is_zero(self) -> bool {
        self.num == 0
    }

    #[must_use]
    pub fn is_positive(self) -> bool {
        self.num > 0
    }
}

// -- Arithmetic impls --

impl Add for Time {
    type Output = Self;
    fn add(self, rhs: Self) -> Self {
        Self::new(
            self.num * rhs.den as i64 + rhs.num * self.den as i64,
            self.den * rhs.den,
        )
    }
}

// Allow `&time + &time` for ergonomics
impl Add for &Time {
    type Output = Time;
    fn add(self, rhs: Self) -> Time {
        *self + *rhs
    }
}

impl Sub for Time {
    type Output = Self;
    fn sub(self, rhs: Self) -> Self {
        Self::new(
            self.num * rhs.den as i64 - rhs.num * self.den as i64,
            self.den * rhs.den,
        )
    }
}

impl Mul for Time {
    type Output = Self;
    fn mul(self, rhs: Self) -> Self {
        Self::new(self.num * rhs.num, self.den * rhs.den)
    }
}

impl Div for Time {
    type Output = Self;
    fn div(self, rhs: Self) -> Self {
        assert!(!rhs.is_zero(), "division by zero");
        let sign = if rhs.num < 0 { -1 } else { 1 };
        Self::new(
            sign * self.num * rhs.den as i64,
            self.den * rhs.num.unsigned_abs(),
        )
    }
}

impl Neg for Time {
    type Output = Self;
    fn neg(self) -> Self {
        Self {
            num: -self.num,
            den: self.den,
        }
    }
}

impl PartialEq for Time {
    fn eq(&self, other: &Self) -> bool {
        // Cross-multiply to avoid overflow from normalization
        self.num * other.den as i64 == other.num * self.den as i64
    }
}

impl Eq for Time {}

impl PartialOrd for Time {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Time {
    fn cmp(&self, other: &Self) -> Ordering {
        let lhs = self.num * other.den as i64;
        let rhs = other.num * self.den as i64;
        lhs.cmp(&rhs)
    }
}

impl fmt::Debug for Time {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.den == 1 {
            write!(f, "{}", self.num)
        } else {
            write!(f, "{}/{}", self.num, self.den)
        }
    }
}

impl fmt::Display for Time {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Debug::fmt(self, f)
    }
}

/// A half-open time interval `[start, end)` representing a span in cycle-time.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Arc {
    pub start: Time,
    pub end: Time,
}

impl Arc {
    #[must_use]
    pub fn new(start: Time, end: Time) -> Self {
        Self { start, end }
    }

    /// The whole-number cycle span, e.g. cycle 0 = Arc(0, 1).
    #[must_use]
    pub fn cycle(n: i64) -> Self {
        Self {
            start: Time::whole(n),
            end: Time::whole(n + 1),
        }
    }

    #[must_use]
    pub fn duration(self) -> Time {
        self.end - self.start
    }

    /// Split an arc that may span multiple cycles into per-cycle sub-arcs.
    /// Each sub-arc is clamped to `[floor, floor+1)`.
    /// This is essential for querying patterns that repeat each cycle.
    #[must_use]
    pub fn split_cycles(self) -> Vec<Self> {
        let start_cycle = self.start.floor();
        let end_cycle = self.end.floor();

        // If end is exactly on a cycle boundary, don't include that cycle
        // (half-open interval)
        let last_cycle = if self.end.fract().is_zero() && self.end > self.start {
            end_cycle - 1
        } else {
            end_cycle
        };

        (start_cycle..=last_cycle)
            .map(|c| {
                let cycle_start = Time::whole(c);
                let cycle_end = Time::whole(c + 1);
                Self {
                    start: if self.start > cycle_start {
                        self.start
                    } else {
                        cycle_start
                    },
                    end: if self.end < cycle_end {
                        self.end
                    } else {
                        cycle_end
                    },
                }
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // -- Time construction & normalization --

    #[test]
    fn time_normalizes_on_construction() {
        let t = Time::new(4, 6);
        assert_eq!(t.num, 2);
        assert_eq!(t.den, 3);
    }

    #[test]
    fn time_normalizes_negative() {
        let t = Time::new(-6, 9);
        assert_eq!(t.num, -2);
        assert_eq!(t.den, 3);
    }

    #[test]
    fn time_zero_numerator() {
        let t = Time::new(0, 5);
        assert_eq!(t.num, 0);
        assert_eq!(t.den, 1);
    }

    #[test]
    #[should_panic(expected = "denominator must be nonzero")]
    fn time_zero_denominator_panics() {
        let _ = Time::new(1, 0);
    }

    // -- Arithmetic --

    #[test]
    fn time_addition() {
        let a = Time::new(1, 3);
        let b = Time::new(1, 6);
        let sum = a + b;
        assert_eq!(sum, Time::new(1, 2));
    }

    #[test]
    fn time_subtraction() {
        let a = Time::new(1, 2);
        let b = Time::new(1, 3);
        let diff = a - b;
        assert_eq!(diff, Time::new(1, 6));
    }

    #[test]
    fn time_multiplication() {
        let a = Time::new(2, 3);
        let b = Time::new(3, 4);
        assert_eq!(a * b, Time::new(1, 2));
    }

    #[test]
    fn time_division() {
        let a = Time::new(1, 2);
        let b = Time::new(3, 4);
        assert_eq!(a / b, Time::new(2, 3));
    }

    #[test]
    #[should_panic(expected = "division by zero")]
    fn time_division_by_zero_panics() {
        let _ = Time::one() / Time::zero();
    }

    #[test]
    fn time_negation() {
        let t = Time::new(3, 7);
        assert_eq!((-t).num, -3);
        assert_eq!((-t).den, 7);
    }

    // -- Comparison --

    #[test]
    fn time_ordering() {
        let a = Time::new(1, 3);
        let b = Time::new(1, 2);
        assert!(a < b);
        assert!(b > a);
        assert_eq!(Time::new(2, 4), Time::new(1, 2));
    }

    // -- Floor / Fract --

    #[test]
    fn time_floor_positive() {
        assert_eq!(Time::new(7, 3).floor(), 2);
        assert_eq!(Time::new(6, 3).floor(), 2);
    }

    #[test]
    fn time_floor_negative() {
        assert_eq!(Time::new(-1, 3).floor(), -1);
        assert_eq!(Time::new(-3, 3).floor(), -1);
        assert_eq!(Time::new(-4, 3).floor(), -2);
    }

    #[test]
    fn time_fract_positive() {
        let t = Time::new(7, 3); // 2 + 1/3
        assert_eq!(t.fract(), Time::new(1, 3));
    }

    #[test]
    fn time_fract_negative() {
        let t = Time::new(-1, 3); // floor = -1, fract = 2/3
        assert_eq!(t.fract(), Time::new(2, 3));
    }

    #[test]
    fn time_fract_exact() {
        let t = Time::whole(3);
        assert_eq!(t.fract(), Time::zero());
    }

    // -- Arc --

    #[test]
    fn arc_duration() {
        let a = Arc::new(Time::new(1, 4), Time::new(3, 4));
        assert_eq!(a.duration(), Time::new(1, 2));
    }

    #[test]
    fn arc_cycle() {
        let c = Arc::cycle(2);
        assert_eq!(c.start, Time::whole(2));
        assert_eq!(c.end, Time::whole(3));
    }

    // -- split_cycles --

    #[test]
    fn split_cycles_within_single_cycle() {
        let a = Arc::new(Time::new(1, 4), Time::new(3, 4));
        let splits = a.split_cycles();
        assert_eq!(splits.len(), 1);
        assert_eq!(splits[0], a);
    }

    #[test]
    fn split_cycles_exact_one_cycle() {
        let a = Arc::cycle(0);
        let splits = a.split_cycles();
        assert_eq!(splits.len(), 1);
        assert_eq!(splits[0], Arc::new(Time::zero(), Time::one()));
    }

    #[test]
    fn split_cycles_spans_two_cycles() {
        let a = Arc::new(Time::new(1, 2), Time::new(3, 2));
        let splits = a.split_cycles();
        assert_eq!(splits.len(), 2);
        assert_eq!(
            splits[0],
            Arc::new(Time::new(1, 2), Time::one())
        );
        assert_eq!(
            splits[1],
            Arc::new(Time::one(), Time::new(3, 2))
        );
    }

    #[test]
    fn split_cycles_end_on_boundary() {
        // [0.5, 2.0) should split into [0.5, 1.0) and [1.0, 2.0)
        let a = Arc::new(Time::new(1, 2), Time::whole(2));
        let splits = a.split_cycles();
        assert_eq!(splits.len(), 2);
        assert_eq!(splits[0].start, Time::new(1, 2));
        assert_eq!(splits[0].end, Time::one());
        assert_eq!(splits[1].start, Time::one());
        assert_eq!(splits[1].end, Time::whole(2));
    }

    #[test]
    fn split_cycles_three_cycles() {
        let a = Arc::new(Time::new(1, 4), Time::new(9, 4));
        let splits = a.split_cycles();
        assert_eq!(splits.len(), 3);
        assert_eq!(splits[0].start, Time::new(1, 4));
        assert_eq!(splits[0].end, Time::one());
        assert_eq!(splits[1], Arc::cycle(1));
        assert_eq!(splits[2].start, Time::whole(2));
        assert_eq!(splits[2].end, Time::new(9, 4));
    }
}
