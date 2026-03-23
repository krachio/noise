//! Tidal Cycles-inspired live coding pattern engine.
//!
//! Evaluates composable patterns over rational time and outputs
//! control signals (MIDI notes, CC, OSC messages) in real time. A separate
//! frontend sends pattern IR as JSON over a Unix socket; the engine compiles,
//! schedules, and dispatches events.
//!
//! # Core pipeline
//!
//! ```text
//! IR JSON → compile → CompiledPattern → scheduler query → output dispatch
//! ```
//!
//! # Modules
//!
//! - [`time`] — Rational time and half-open arc intervals
//! - [`event`] — Events with whole/part time model and value types
//! - [`pattern`] — Arena-indexed compiled patterns and query evaluator
//! - [`ir`] — Frontend IR (serde JSON), validation, compilation
//! - [`scheduler`] — Real-time loop, clock, lock-free pattern hot-swap
//! - [`output`] — MIDI and OSC output sinks
//! - [`ipc`] — Unix socket server for frontend communication

#![warn(missing_docs)]

pub mod engine;
pub mod event;
#[cfg(feature = "native")]
pub mod ipc;
pub mod ir;
#[cfg(feature = "native")]
pub mod output;
pub mod pattern;
#[cfg(feature = "native")]
pub mod rt;
pub mod scheduler;
pub mod time;
