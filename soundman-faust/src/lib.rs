//! FAUST LLVM JIT plugin for the [soundman] audio engine.
//!
//! Compiles [FAUST](https://faust.grame.fr) DSP code at runtime via LLVM JIT
//! and registers the resulting nodes in soundman's [`NodeRegistry`].
//!
//! # Quick start
//!
//! Register a FAUST program as a node type, then use it in a graph:
//!
//! ```no_run
//! use soundman::engine::{self, config::EngineConfig};
//! use soundman_faust::register_faust_node;
//!
//! let (mut ctrl, mut proc) = engine::engine(&EngineConfig::default());
//!
//! register_faust_node(
//!     ctrl.registry_mut(),
//!     "faust:sine",
//!     "sine",
//!     r#"
//!         import("stdfaust.lib");
//!         freq = hslider("freq", 440, 20, 20000, 1);
//!         process = os.osc(freq);
//!     "#,
//! ).unwrap();
//! ```
//!
//! # Hot reload
//!
//! For live-reloading `.dsp` files from a directory, use [`hot_reload::HotReloadEngine`]:
//!
//! ```no_run
//! use soundman::engine::config::EngineConfig;
//! use soundman_faust::hot_reload::HotReloadEngine;
//!
//! let (mut engine, mut proc) = HotReloadEngine::new(
//!     &EngineConfig::default(),
//!     "./dsp",  // directory of .dsp files
//! ).unwrap();
//!
//! // In your control loop:
//! engine.poll_reload().unwrap();
//! ```
//!
//! # Modules
//!
//! | Module | Purpose |
//! |--------|---------|
//! | [`dsp`] | Safe wrapper around compiled FAUST DSP instances |
//! | [`factory`] | [`FaustFactory`] — soundman [`NodeFactory`] implementation |
//! | [`node`] | [`FaustNode`](node::FaustNode) — soundman [`DspNode`](soundman::graph::node::DspNode) adapter |
//! | [`loader`] | Load `.dsp` files from disk, register directories |
//! | [`watcher`] | File watcher for `.dsp` changes |
//! | [`hot_reload`] | All-in-one engine with live reload |
//!
//! [soundman]: https://docs.rs/soundman
//! [`NodeRegistry`]: soundman::registry::NodeRegistry
//! [`NodeFactory`]: soundman::registry::NodeFactory

pub mod dsp;
pub mod factory;
mod ffi;
pub mod hot_reload;
pub mod loader;
pub mod node;
pub mod watcher;

use log::info;
use soundman::registry::NodeRegistry;

use crate::factory::FaustFactory;

/// Register a FAUST DSP program as a node type in the soundman registry.
///
/// The `type_id` is the string used to reference this node in graph IR
/// (e.g. `"faust:lowpass2"`). The `name` is an internal label for FAUST
/// diagnostics.
///
/// This probes the code to discover ports and parameters, then registers
/// both the type declaration and factory.
///
/// # Errors
/// Returns the FAUST compilation error if the code is invalid, or a
/// registry error (as string) if the type is already registered.
pub fn register_faust_node(
    registry: &mut NodeRegistry,
    type_id: &str,
    name: &str,
    code: &str,
) -> Result<(), String> {
    let factory = FaustFactory::new(name, code);
    let decl = factory.probe_type_decl(type_id)?;

    info!(
        "registering FAUST node '{type_id}': {} in, {} out, {} controls",
        decl.audio_inputs.len(),
        decl.audio_outputs.len(),
        decl.controls.len()
    );

    registry
        .register(decl, factory)
        .map_err(|e| e.to_string())?;

    Ok(())
}

/// Return the FAUST library version string.
///
/// # Panics
/// Panics if the version string from libfaust is not valid UTF-8.
#[must_use]
pub fn faust_version() -> String {
    let ptr = unsafe { ffi::getCLibFaustVersion() };
    let cstr = unsafe { std::ffi::CStr::from_ptr(ptr) };
    cstr.to_str().expect("faust version not utf8").to_string()
}
