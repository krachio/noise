use super::{IrError, IrNode};

/// Validate an IR tree before compilation.
/// Checks: no zero denominators, positive factors, non-empty children.
pub fn validate(node: &IrNode) -> Result<(), IrError> {
    match node {
        IrNode::Atom { .. } | IrNode::AtomGroup { .. } | IrNode::Silence => Ok(()),
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
    }
}

fn validate_time_pair(pair: [i64; 2]) -> Result<(), IrError> {
    if pair[1] == 0 {
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
}
