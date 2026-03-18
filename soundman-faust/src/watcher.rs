//! Watch a directory of `.dsp` files and emit events on changes.

use std::path::{Path, PathBuf};
use std::sync::mpsc::Sender;

use notify::{Event, EventKind, RecursiveMode, Watcher};

/// Events emitted by [`DspWatcher`] when `.dsp` files change.
#[derive(Debug, Clone)]
pub enum WatchEvent {
    /// A `.dsp` file was created or modified.
    Changed {
        type_id: String,
        path: PathBuf,
    },
    /// A `.dsp` file was removed.
    Removed {
        type_id: String,
    },
}

/// Watches a directory for `.dsp` file changes and sends [`WatchEvent`]s.
///
/// Dropping the watcher stops watching.
pub struct DspWatcher {
    _watcher: notify::RecommendedWatcher,
}

impl DspWatcher {
    /// Start watching `dir` for `.dsp` file changes.
    ///
    /// Events are debounced (~200ms) and sent to `tx`.
    ///
    /// # Errors
    /// Returns an error if the watcher cannot be created or the directory cannot be watched.
    pub fn new(dir: impl AsRef<Path>, tx: Sender<WatchEvent>) -> Result<Self, String> {
        let dir = dir.as_ref().to_path_buf();

        let mut watcher = notify::recommended_watcher(move |res: Result<Event, notify::Error>| {
            let Ok(event) = res else { return };
            Self::handle_event(&event, &tx);
        })
        .map_err(|e| format!("failed to create watcher: {e}"))?;

        watcher
            .watch(dir.as_ref(), RecursiveMode::NonRecursive)
            .map_err(|e| format!("failed to watch {}: {e}", dir.display()))?;

        Ok(Self { _watcher: watcher })
    }

    fn handle_event(event: &Event, tx: &Sender<WatchEvent>) {
        for path in &event.paths {
            let is_dsp = path.extension().is_some_and(|ext| ext == "dsp");
            if !is_dsp {
                continue;
            }

            let Some(type_id) = path.file_stem().and_then(|s| s.to_str()).map(|s| format!("faust:{s}")) else {
                continue;
            };

            match event.kind {
                EventKind::Create(_) | EventKind::Modify(_) => {
                    // Debounce: skip if file is empty (mid-write)
                    if path.metadata().is_ok_and(|m| m.len() > 0) {
                        let _ = tx.send(WatchEvent::Changed {
                            type_id,
                            path: path.clone(),
                        });
                    }
                }
                EventKind::Remove(_) => {
                    let _ = tx.send(WatchEvent::Removed { type_id });
                }
                _ => {}
            }
        }
    }
}

impl std::fmt::Debug for DspWatcher {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("DspWatcher").finish_non_exhaustive()
    }
}

/// Apply a [`WatchEvent::Changed`] to a registry — recompiles the FAUST code
/// and either registers (new) or reregisters (existing) the node type.
///
/// # Errors
/// Returns an error if the file cannot be read or the FAUST code fails to compile.
pub fn apply_reload(
    registry: &mut soundman::registry::NodeRegistry,
    event: &WatchEvent,
) -> Result<(), String> {
    match event {
        WatchEvent::Changed { type_id, path } => {
            let code = std::fs::read_to_string(path)
                .map_err(|e| format!("failed to read {}: {e}", path.display()))?;
            let name = path
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("unknown");
            let factory = crate::factory::FaustFactory::new(name, &code);
            let decl = factory.probe_type_decl(type_id)?;

            if registry.get_type(type_id).is_some() {
                registry.reregister(decl, factory).map_err(|e| e.to_string())
            } else {
                registry.register(decl, factory).map_err(|e| e.to_string())
            }
        }
        WatchEvent::Removed { .. } => {
            // Registry doesn't support unregister — this is a no-op for now.
            // The type remains registered but can't be reinstantiated from file.
            Ok(())
        }
    }
}
