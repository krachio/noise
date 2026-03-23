//! Python bindings for pattern-engine via PyO3.
//!
//! Exposes pattern compilation and query as Python functions.
//! Used by the WASM REPL (JupyterLite/Pyodide) and can also be used
//! natively for testing.

use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;

use pattern_engine::event::Value;
use pattern_engine::ir;
use pattern_engine::pattern::query;
use pattern_engine::pattern::curve::compile_wavetable;
use pattern_engine::time::Arc;

/// Compile a pattern from JSON IR and query it for one cycle.
/// Returns a list of event dicts: [{"onset": f64, "label": str, "value": f64}, ...]
#[pyfunction]
fn query_cycle(ir_json: &str, cycle: i64, table_len: usize) -> PyResult<Vec<(String, Vec<f32>)>> {
    let ir_node: ir::IrNode = serde_json::from_str(ir_json)
        .map_err(|e| PyValueError::new_err(format!("invalid IR JSON: {e}")))?;

    let compiled = ir::compile(&ir_node)
        .map_err(|e| PyValueError::new_err(format!("compilation error: {e}")))?;

    let arc = Arc::cycle(cycle);
    let events = query(&compiled, compiled.root, arc);
    let tables = compile_wavetable(&events, table_len);

    Ok(tables.into_iter().collect())
}

/// Compile a pattern from JSON IR and return raw events for one cycle.
/// Returns [(onset_frac, label, value), ...] sorted by onset.
#[pyfunction]
fn query_events(ir_json: &str, cycle: i64) -> PyResult<Vec<(f64, String, f32)>> {
    let ir_node: ir::IrNode = serde_json::from_str(ir_json)
        .map_err(|e| PyValueError::new_err(format!("invalid IR JSON: {e}")))?;

    let compiled = ir::compile(&ir_node)
        .map_err(|e| PyValueError::new_err(format!("compilation error: {e}")))?;

    let arc = Arc::cycle(cycle);
    let events = query(&compiled, compiled.root, arc);

    let mut result = Vec::new();
    for event in &events {
        if let Value::Control { label, value } = &event.value {
            if let Some(whole) = event.whole {
                let frac = whole.start.fract();
                let onset = frac.num as f64 / frac.den as f64;
                result.push((onset, label.clone(), *value));
            }
        }
    }
    result.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    Ok(result)
}

/// Validate and compile a pattern IR from JSON. Returns true if valid.
#[pyfunction]
fn validate_ir(ir_json: &str) -> PyResult<bool> {
    let ir_node: ir::IrNode = serde_json::from_str(ir_json)
        .map_err(|e| PyValueError::new_err(format!("invalid JSON: {e}")))?;
    match ir::compile(&ir_node) {
        Ok(_) => Ok(true),
        Err(e) => Err(PyValueError::new_err(format!("{e}"))),
    }
}

/// Python module definition.
#[pymodule]
fn pattern_engine_py(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(query_cycle, m)?)?;
    m.add_function(wrap_pyfunction!(query_events, m)?)?;
    m.add_function(wrap_pyfunction!(validate_ir, m)?)?;
    Ok(())
}
