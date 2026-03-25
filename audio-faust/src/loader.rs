//! Load FAUST `.dsp` files from disk and register them in an audio-engine registry.

use std::fs;
use std::path::Path;

use audio_engine::registry::NodeRegistry;

use crate::factory::FaustFactory;

/// Load a `.dsp` file, deriving `type_id` from path relative to `base_dir`.
///
/// `base_dir/drums/kick.dsp` → `("faust:drums/kick", code)`.
///
/// # Errors
/// Returns an IO error if the file cannot be read.
pub fn load_dsp_file(
    path: impl AsRef<Path>,
    base_dir: impl AsRef<Path>,
) -> Result<(String, String), std::io::Error> {
    let path = path.as_ref();
    let rel = path.strip_prefix(base_dir.as_ref()).unwrap_or(path);
    let stem = rel
        .with_extension("")
        .to_str()
        .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::InvalidInput, "invalid path"))?
        .to_string();
    let type_id = format!("faust:{stem}");
    let code = fs::read_to_string(path)?;
    Ok((type_id, code))
}

/// Recursively scan a directory for `.dsp` files and register each in the registry.
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
    let mut dsp_files = Vec::new();
    collect_dsp_files(dir, &mut dsp_files)
        .map_err(|e| format!("failed to scan {}: {e}", dir.display()))?;
    dsp_files.sort();

    let mut registered = Vec::new();
    for path in dsp_files {
        let (type_id, code) = load_dsp_file(&path, dir)
            .map_err(|e| format!("failed to read {}: {e}", path.display()))?;
        let name = path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("unknown");
        let factory = FaustFactory::new(name, &code);
        let decl = factory.probe_type_decl(&type_id)?;
        registry
            .register(decl, factory)
            .map_err(|e| e.to_string())?;
        registered.push(type_id);
    }

    Ok(registered)
}

fn collect_dsp_files(dir: &Path, out: &mut Vec<std::path::PathBuf>) -> std::io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            collect_dsp_files(&path, out)?;
        } else if path.extension().is_some_and(|ext| ext == "dsp") {
            out.push(path);
        }
    }
    Ok(())
}
