pub mod dsp;
pub mod factory;
mod ffi;
pub mod node;

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
