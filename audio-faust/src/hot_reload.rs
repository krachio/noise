//! `HotReloadEngine` — wraps an audio-engine with FAUST file watching and hot reload.

use std::path::Path;
use std::sync::mpsc;

use log::info;
use audio_engine::engine::config::EngineConfig;
use audio_engine::engine::{self, AudioProcessor, EngineController};
use audio_engine::ir::GraphIr;
use audio_engine::protocol::ClientMessage;
use audio_engine::registry::NodeRegistry;

use crate::loader;
use crate::watcher::{self, DspWatcher, WatchEvent};

/// An audio-engine with FAUST hot reload.
///
/// Watches a directory of `.dsp` files. On file changes, recompiles the FAUST
/// code, updates the registry, and reloads the current graph.
pub struct HotReloadEngine {
    ctrl: EngineController,
    _watcher: DspWatcher,
    rx: mpsc::Receiver<WatchEvent>,
    current_graph: Option<GraphIr>,
}

impl HotReloadEngine {
    /// Create a new engine watching `dsp_dir` for `.dsp` files.
    ///
    /// Registers all existing `.dsp` files in the directory on startup.
    ///
    /// # Errors
    /// Returns an error if the watcher cannot start or initial registration fails.
    pub fn new(
        config: &EngineConfig,
        dsp_dir: impl AsRef<Path>,
    ) -> Result<(Self, AudioProcessor), String> {
        let (mut ctrl, proc) = engine::engine(config);
        let (tx, rx) = mpsc::channel();

        loader::register_dsp_dir(ctrl.registry_mut(), &dsp_dir)?;

        let watcher = DspWatcher::new(&dsp_dir, tx)?;

        let engine = Self {
            ctrl,
            _watcher: watcher,
            rx,
            current_graph: None,
        };

        Ok((engine, proc))
    }

    /// Load a graph and remember it for hot reload.
    ///
    /// # Errors
    /// Returns an error if graph compilation fails.
    pub fn load_graph(&mut self, graph: GraphIr) -> Result<(), String> {
        self.ctrl
            .handle_message(ClientMessage::LoadGraph(graph.clone()))
            .map_err(|e| e.to_string())?;
        self.current_graph = Some(graph);
        Ok(())
    }

    /// Poll for file change events and apply reloads.
    ///
    /// Returns the list of `type_id`s that were reloaded. If the current graph
    /// uses any reloaded type, it is automatically recompiled and swapped.
    ///
    /// # Errors
    /// Returns an error if recompilation or graph reload fails.
    pub fn poll_reload(&mut self) -> Result<Vec<String>, String> {
        let mut reloaded = Vec::new();

        while let Ok(event) = self.rx.try_recv() {
            let type_id = match &event {
                WatchEvent::Changed { type_id, .. } | WatchEvent::Removed { type_id } => {
                    type_id.clone()
                }
            };
            watcher::apply_reload(self.ctrl.registry_mut(), &event)?;
            info!("hot-reloaded FAUST node: {type_id}");
            reloaded.push(type_id);
        }

        if let (false, Some(graph)) = (reloaded.is_empty(), &self.current_graph) {
            let graph_uses_reloaded = graph
                .nodes
                .iter()
                .any(|n| reloaded.contains(&n.type_id));

            if graph_uses_reloaded {
                info!("reloading graph after FAUST hot-reload");
                self.ctrl
                    .handle_message(ClientMessage::LoadGraph(graph.clone()))
                    .map_err(|e| e.to_string())?;
            }
        }

        Ok(reloaded)
    }

    /// Access the underlying registry.
    pub fn registry(&mut self) -> &NodeRegistry {
        self.ctrl.registry_mut()
    }

    /// Mutable access to the engine controller.
    pub const fn controller_mut(&mut self) -> &mut EngineController {
        &mut self.ctrl
    }
}

impl std::fmt::Debug for HotReloadEngine {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("HotReloadEngine")
            .field("has_graph", &self.current_graph.is_some())
            .finish_non_exhaustive()
    }
}
