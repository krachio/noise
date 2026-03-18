//! Load FAUST `.dsp` files from disk and register them in a soundman registry.

use std::fs;
use std::path::Path;

use soundman::registry::NodeRegistry;

use crate::factory::FaustFactory;

/// Load a `.dsp` file, returning `(type_id, code)`.
///
/// The `type_id` is derived from the filename: `lowpass.dsp` → `"faust:lowpass"`.
///
/// # Errors
/// Returns an IO error if the file cannot be read.
pub fn load_dsp_file(path: impl AsRef<Path>) -> Result<(String, String), std::io::Error> {
    let path = path.as_ref();
    let stem = path
        .file_stem()
        .and_then(|s| s.to_str())
        .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::InvalidInput, "invalid filename"))?;
    let type_id = format!("faust:{stem}");
    let code = fs::read_to_string(path)?;
    Ok((type_id, code))
}

/// Scan a directory for `.dsp` files and register each in the registry.
///
/// Returns the list of registered `type_id`s.
///
/// # Errors
/// Returns an error if any `.dsp` file fails to compile or register.
pub fn register_dsp_dir(
    registry: &mut NodeRegistry,
    dir: impl AsRef<Path>,
) -> Result<Vec<String>, String> {
    let dir = dir.as_ref();
    let mut entries: Vec<_> = fs::read_dir(dir)
        .map_err(|e| format!("failed to read directory {}: {e}", dir.display()))?
        .filter_map(Result::ok)
        .filter(|e| e.path().extension().is_some_and(|ext| ext == "dsp"))
        .collect();

    // Sort for deterministic registration order
    entries.sort_by_key(std::fs::DirEntry::path);

    let mut registered = Vec::new();
    for entry in entries {
        let path = entry.path();
        let (type_id, code) =
            load_dsp_file(&path).map_err(|e| format!("failed to read {}: {e}", path.display()))?;
        let name = path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("unknown");
        let factory = FaustFactory::new(name, &code);
        let decl = factory.probe_type_decl(&type_id)?;
        registry.register(decl, factory).map_err(|e| e.to_string())?;
        registered.push(type_id);
    }

    Ok(registered)
}
