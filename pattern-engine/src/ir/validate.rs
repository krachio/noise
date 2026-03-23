use super::{IrError, IrNode};

/// Validate an IR tree before compilation.
/// Checks: no zero denominators, positive factors, non-empty children.
pub fn validate(node: &IrNode) -> Result<(), IrError> {
    match node {
        IrNode::Atom { .. } | IrNode::Silence => Ok(()),
        IrNode::Freeze { child } => validate(child),
        IrNode::Cat { children } => {
            if children.is_empty() {
                return Err(IrError::EmptyChildren { op: "Cat" });
            }
            for child in children {
                validate(child)?;
            }
            Ok(())
        }
        IrNode::Stack { children } => {
            if children.is_empty() {
                return Err(IrError::EmptyChildren { op: "Stack" });
            }
            for child in children {
                validate(child)?;
            }
            Ok(())
        }
        IrNode::Fast { factor, child } => {
            validate_time_pair(*factor)?;
            validate_positive_factor(*factor)?;
            validate(child)
        }
        IrNode::Slow { factor, child } => {
            validate_time_pair(*factor)?;
            validate_positive_factor(*factor)?;
            validate(child)
        }
        IrNode::Early { offset, child } => {
            validate_time_pair(*offset)?;
            validate(child)
        }
        IrNode::Late { offset, child } => {
            validate_time_pair(*offset)?;
            validate(child)
        }
        IrNode::Rev { child } => validate(child),
        IrNode::Every { n, transform, child } => {
            if *n == 0 {
                return Err(IrError::InvalidEvery {
                    msg: "n must be > 0".into(),
                });
            }
            validate(transform)?;
            validate(child)
        }
        IrNode::Euclid {
            pulses,
            steps,
            child,
            ..
        } => {
            if *steps == 0 {
                return Err(IrError::InvalidEuclid {
                    msg: "steps must be > 0".into(),
                });
            }
            if *pulses > *steps {
                return Err(IrError::InvalidEuclid {
                    msg: "pulses must be <= steps".into(),
                });
            }
            validate(child)
        }
        IrNode::Degrade { prob, child, .. } => {
            if !(*prob >= 0.0 && *prob <= 1.0) {
                return Err(IrError::InvalidDegrade {
                    msg: "prob must be in [0, 1]".into(),
                });
            }
            validate(child)
        }
        IrNode::Warp { kind, amount, grid, child } => {
            if kind != "swing" {
                return Err(IrError::InvalidWarp {
                    msg: format!("unknown warp kind: {kind}"),
                });
            }
            if *grid == 0 || *grid % 2 != 0 {
                return Err(IrError::InvalidWarp {
                    msg: "grid must be even and > 0".into(),
                });
            }
            if !(*amount > 0.0 && *amount < 1.0) {
                return Err(IrError::InvalidWarp {
                    msg: "amount must be in (0, 1)".into(),
                });
            }
            validate(child)
        }
    }
}

fn validate_time_pair(pair: [i64; 2]) -> Result<(), IrError> {
    if pair[1] <= 0 {
        return Err(IrError::ZeroDenominator);
    }
    Ok(())
}

fn validate_positive_factor(pair: [i64; 2]) -> Result<(), IrError> {
    // Factor must be positive (num and den same sign, both nonzero)
    if pair[0] <= 0 || pair[1] <= 0 {
        return Err(IrError::NonPositiveFactor);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::Value;

    fn atom() -> IrNode {
        IrNode::Atom {
            value: Value::Note {
                channel: 0,
                note: 60,
                velocity: 100,
                dur: 0.5,
            },
        }
    }

    #[test]
    fn valid_atom() {
        assert!(validate(&atom()).is_ok());
    }

    #[test]
    fn valid_silence() {
        assert!(validate(&IrNode::Silence).is_ok());
    }

    #[test]
    fn valid_cat() {
        let node = IrNode::Cat {
            children: vec![atom(), atom()],
        };
        assert!(validate(&node).is_ok());
    }

    #[test]
    fn empty_cat_fails() {
        let node = IrNode::Cat {
            children: vec![],
        };
        assert_eq!(
            validate(&node),
            Err(IrError::EmptyChildren { op: "Cat" })
        );
    }

    #[test]
    fn empty_stack_fails() {
        let node = IrNode::Stack {
            children: vec![],
        };
        assert_eq!(
            validate(&node),
            Err(IrError::EmptyChildren { op: "Stack" })
        );
    }

    #[test]
    fn zero_denominator_in_fast_fails() {
        let node = IrNode::Fast {
            factor: [2, 0],
            child: Box::new(atom()),
        };
        assert_eq!(validate(&node), Err(IrError::ZeroDenominator));
    }

    #[test]
    fn negative_factor_fails() {
        let node = IrNode::Fast {
            factor: [-1, 2],
            child: Box::new(atom()),
        };
        assert_eq!(validate(&node), Err(IrError::NonPositiveFactor));
    }

    #[test]
    fn zero_factor_fails() {
        let node = IrNode::Slow {
            factor: [0, 1],
            child: Box::new(atom()),
        };
        assert_eq!(validate(&node), Err(IrError::NonPositiveFactor));
    }

    #[test]
    fn zero_den_in_early_fails() {
        let node = IrNode::Early {
            offset: [1, 0],
            child: Box::new(atom()),
        };
        assert_eq!(validate(&node), Err(IrError::ZeroDenominator));
    }

    #[test]
    fn nested_validation_catches_deep_error() {
        let node = IrNode::Rev {
            child: Box::new(IrNode::Cat {
                children: vec![IrNode::Fast {
                    factor: [1, 0],
                    child: Box::new(atom()),
                }],
            }),
        };
        assert_eq!(validate(&node), Err(IrError::ZeroDenominator));
    }

    #[test]
    fn negative_denominator_in_early_fails() {
        // Negative denominators wrap to huge u64 in time_from_pair,
        // producing wrong Time values. Must be rejected by validation.
        let node = IrNode::Early {
            offset: [1, -3],
            child: Box::new(atom()),
        };
        assert_eq!(validate(&node), Err(IrError::ZeroDenominator));
    }

    #[test]
    fn negative_denominator_in_late_fails() {
        let node = IrNode::Late {
            offset: [-1, -4],
            child: Box::new(atom()),
        };
        assert_eq!(validate(&node), Err(IrError::ZeroDenominator));
    }

    #[test]
    fn negative_denominator_in_fast_fails() {
        let node = IrNode::Fast {
            factor: [2, -1],
            child: Box::new(atom()),
        };
        // validate_time_pair runs first, catches negative den
        assert_eq!(validate(&node), Err(IrError::ZeroDenominator));
    }

    // ── Warp validation ────────────────────────────────────────────────

    fn swing(amount: f64, grid: u32) -> IrNode {
        IrNode::Warp {
            kind: "swing".into(),
            amount,
            grid,
            child: Box::new(atom()),
        }
    }

    #[test]
    fn valid_swing() {
        assert!(validate(&swing(0.67, 8)).is_ok());
    }

    #[test]
    fn warp_unknown_kind_fails() {
        let node = IrNode::Warp {
            kind: "groove".into(),
            amount: 0.5,
            grid: 8,
            child: Box::new(atom()),
        };
        assert!(matches!(validate(&node), Err(IrError::InvalidWarp { .. })));
    }

    #[test]
    fn warp_grid_zero_fails() {
        assert!(matches!(validate(&swing(0.67, 0)), Err(IrError::InvalidWarp { .. })));
    }

    #[test]
    fn warp_grid_odd_fails() {
        assert!(matches!(validate(&swing(0.67, 7)), Err(IrError::InvalidWarp { .. })));
    }

    #[test]
    fn warp_amount_zero_fails() {
        assert!(matches!(validate(&swing(0.0, 8)), Err(IrError::InvalidWarp { .. })));
    }

    #[test]
    fn warp_amount_one_fails() {
        assert!(matches!(validate(&swing(1.0, 8)), Err(IrError::InvalidWarp { .. })));
    }

    #[test]
    fn warp_amount_nan_fails() {
        assert!(matches!(validate(&swing(f64::NAN, 8)), Err(IrError::InvalidWarp { .. })));
    }
}
