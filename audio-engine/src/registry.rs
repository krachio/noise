use std::collections::HashMap;

use crate::graph::node::DspNode;
use crate::ir::types::NodeTypeDecl;

/// Creates [`DspNode`] instances for a given node type.
///
/// Each registered node type has one factory. The factory is `Send + Sync`
/// because the registry lives on the control thread and may be shared.
pub trait NodeFactory: Send + Sync {
    /// Instantiate a new node configured for the given sample rate and block size.
    ///
    /// # Errors
    /// Returns an error string if instantiation fails (e.g. compilation, resource loading).
    fn create(&self, sample_rate: u32, block_size: usize) -> Result<Box<dyn DspNode>, String>;
}

/// Errors from node type registration and lookup.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RegistryError {
    /// No factory registered for this `type_id`.
    TypeNotFound(String),
    /// A factory with this `type_id` already exists.
    DuplicateType(String),
    /// Factory failed to create a node instance.
    CreateFailed(String),
}

impl std::fmt::Display for RegistryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::TypeNotFound(id) => write!(f, "node type not found: {id}"),
            Self::DuplicateType(id) => write!(f, "node type already registered: {id}"),
            Self::CreateFailed(msg) => write!(f, "node creation failed: {msg}"),
        }
    }
}

impl std::error::Error for RegistryError {}

/// Maps `type_id` strings to [`NodeTypeDecl`]s and [`NodeFactory`] instances.
///
/// Built-in types (`"oscillator"`, `"dac"`) are registered at engine creation.
/// External types (e.g. FAUST nodes) can be added via
/// [`EngineController::registry_mut`](crate::engine::EngineController::registry_mut).
pub struct NodeRegistry {
    types: HashMap<String, NodeTypeDecl>,
    factories: HashMap<String, Box<dyn NodeFactory>>,
    versions: HashMap<String, u64>,
}

impl NodeRegistry {
    #[must_use]
    pub fn new() -> Self {
        Self {
            types: HashMap::new(),
            factories: HashMap::new(),
            versions: HashMap::new(),
        }
    }

    /// # Errors
    /// Returns `RegistryError::DuplicateType` if a type with this `type_id` is already registered.
    pub fn register(
        &mut self,
        decl: NodeTypeDecl,
        factory: impl NodeFactory + 'static,
    ) -> Result<(), RegistryError> {
        if self.types.contains_key(&decl.type_id) {
            return Err(RegistryError::DuplicateType(decl.type_id));
        }
        let type_id = decl.type_id.clone();
        self.types.insert(type_id.clone(), decl);
        self.factories.insert(type_id.clone(), Box::new(factory));
        *self.versions.entry(type_id).or_insert(0) += 1;
        Ok(())
    }

    /// Replace the declaration and factory for an already-registered type.
    ///
    /// Useful for hot-reload: recompile a DSP and swap the factory without
    /// tearing down the whole registry.
    ///
    /// # Errors
    /// Returns `RegistryError::TypeNotFound` if this `type_id` has not been registered.
    pub fn reregister(
        &mut self,
        decl: NodeTypeDecl,
        factory: impl NodeFactory + 'static,
    ) -> Result<(), RegistryError> {
        if !self.types.contains_key(&decl.type_id) {
            return Err(RegistryError::TypeNotFound(decl.type_id));
        }
        let type_id = decl.type_id.clone();
        self.types.insert(type_id.clone(), decl);
        self.factories.insert(type_id.clone(), Box::new(factory));
        *self.versions.entry(type_id).or_insert(0) += 1;
        Ok(())
    }

    /// Register only the type declaration (no factory). Used for node types
    /// that are created externally and injected into the compiler (e.g. `AdcNode`).
    /// The type decl is needed so the compiler can resolve port names.
    pub fn register_type_only(&mut self, decl: NodeTypeDecl) {
        let type_id = decl.type_id.clone();
        self.types.insert(type_id.clone(), decl);
        *self.versions.entry(type_id).or_insert(0) += 1;
    }

    /// # Errors
    /// Returns `RegistryError::TypeNotFound` if no factory exists for this `type_id`.
    pub fn create_node(
        &self,
        type_id: &str,
        sample_rate: u32,
        block_size: usize,
    ) -> Result<Box<dyn DspNode>, RegistryError> {
        let factory = self
            .factories
            .get(type_id)
            .ok_or_else(|| RegistryError::TypeNotFound(type_id.into()))?;
        factory
            .create(sample_rate, block_size)
            .map_err(RegistryError::CreateFailed)
    }

    #[must_use]
    pub fn get_type(&self, type_id: &str) -> Option<&NodeTypeDecl> {
        self.types.get(type_id)
    }

    #[must_use]
    pub fn type_ids(&self) -> Vec<&str> {
        self.types.keys().map(String::as_str).collect()
    }

    /// Returns the version counter for a type. Starts at 1 on first register,
    /// increments on each reregister. Returns 0 for unregistered types.
    #[must_use]
    pub fn version(&self, type_id: &str) -> u64 {
        self.versions.get(type_id).copied().unwrap_or(0)
    }
}

impl Default for NodeRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl std::fmt::Debug for NodeRegistry {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("NodeRegistry")
            .field("types", &self.types.keys().collect::<Vec<_>>())
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph::node::ParamError;
    use crate::ir::types::{ChannelLayout, ControlDecl, PortDecl, Rate};

    struct StubNode {
        sample_rate: u32,
    }

    impl DspNode for StubNode {
        fn process(&mut self, _inputs: &[&[f32]], _outputs: &mut [&mut [f32]]) {}
        fn num_inputs(&self) -> usize {
            0
        }
        fn num_outputs(&self) -> usize {
            1
        }
        fn set_param(&mut self, name: &str, _value: f32) -> Result<(), ParamError> {
            Err(ParamError::NotFound(name.into()))
        }
        fn reset(&mut self, sample_rate: u32) {
            self.sample_rate = sample_rate;
        }
    }

    struct StubFactory;

    impl NodeFactory for StubFactory {
        fn create(&self, sample_rate: u32, _block_size: usize) -> Result<Box<dyn DspNode>, String> {
            Ok(Box::new(StubNode { sample_rate }))
        }
    }

    fn oscillator_decl() -> NodeTypeDecl {
        NodeTypeDecl {
            type_id: "oscillator".into(),
            audio_inputs: vec![],
            audio_outputs: vec![PortDecl {
                name: "out".into(),
                channels: ChannelLayout::Mono,
            }],
            controls: vec![ControlDecl {
                name: "freq".into(),
                range: (20.0, 20_000.0),
                default: 440.0,
                rate: Rate::Control,
                unit: Some("Hz".into()),
            }],
        }
    }

    #[test]
    fn register_and_resolve() {
        let mut registry = NodeRegistry::new();
        registry.register(oscillator_decl(), StubFactory).unwrap();

        let decl = registry.get_type("oscillator");
        assert!(decl.is_some());
        assert_eq!(decl.unwrap().type_id, "oscillator");
    }

    #[test]
    fn create_node_from_registry() {
        let mut registry = NodeRegistry::new();
        registry.register(oscillator_decl(), StubFactory).unwrap();

        let node = registry.create_node("oscillator", 48000, 512).unwrap();
        assert_eq!(node.num_outputs(), 1);
        assert_eq!(node.num_inputs(), 0);
    }

    #[test]
    fn create_node_unknown_type_fails() {
        let registry = NodeRegistry::new();
        let result = registry.create_node("nonexistent", 48000, 512);
        assert!(matches!(result, Err(RegistryError::TypeNotFound(ref id)) if id == "nonexistent"));
    }

    #[test]
    fn duplicate_registration_fails() {
        let mut registry = NodeRegistry::new();
        registry.register(oscillator_decl(), StubFactory).unwrap();

        let result = registry.register(oscillator_decl(), StubFactory);
        assert_eq!(
            result.unwrap_err(),
            RegistryError::DuplicateType("oscillator".into())
        );
    }

    #[test]
    fn type_ids_lists_registered_types() {
        let mut registry = NodeRegistry::new();
        assert!(registry.type_ids().is_empty());

        registry.register(oscillator_decl(), StubFactory).unwrap();
        let ids = registry.type_ids();
        assert_eq!(ids, vec!["oscillator"]);
    }

    #[test]
    fn get_type_returns_none_for_unknown() {
        let registry = NodeRegistry::new();
        assert!(registry.get_type("missing").is_none());
    }

    // -- reregister tests --

    struct StubNode2;

    impl DspNode for StubNode2 {
        fn process(&mut self, _inputs: &[&[f32]], _outputs: &mut [&mut [f32]]) {}
        fn num_inputs(&self) -> usize {
            0
        }
        fn num_outputs(&self) -> usize {
            2
        }
        fn set_param(&mut self, name: &str, _value: f32) -> Result<(), ParamError> {
            Err(ParamError::NotFound(name.into()))
        }
        fn reset(&mut self, _sample_rate: u32) {}
    }

    struct StubFactory2;

    impl NodeFactory for StubFactory2 {
        fn create(
            &self,
            _sample_rate: u32,
            _block_size: usize,
        ) -> Result<Box<dyn DspNode>, String> {
            Ok(Box::new(StubNode2))
        }
    }

    fn oscillator_decl_stereo() -> NodeTypeDecl {
        NodeTypeDecl {
            type_id: "oscillator".into(),
            audio_inputs: vec![],
            audio_outputs: vec![
                PortDecl {
                    name: "left".into(),
                    channels: ChannelLayout::Mono,
                },
                PortDecl {
                    name: "right".into(),
                    channels: ChannelLayout::Mono,
                },
            ],
            controls: vec![],
        }
    }

    #[test]
    fn reregister_overwrites_factory_and_decl() {
        let mut registry = NodeRegistry::new();
        registry.register(oscillator_decl(), StubFactory).unwrap();

        // Original: 1 output, has "freq" control
        let node = registry.create_node("oscillator", 48000, 512).unwrap();
        assert_eq!(node.num_outputs(), 1);
        assert_eq!(registry.get_type("oscillator").unwrap().controls.len(), 1);

        // Reregister with stereo factory
        registry
            .reregister(oscillator_decl_stereo(), StubFactory2)
            .unwrap();

        // Now: 2 outputs, no controls
        let node = registry.create_node("oscillator", 48000, 512).unwrap();
        assert_eq!(node.num_outputs(), 2);
        let decl = registry.get_type("oscillator").unwrap();
        assert_eq!(decl.audio_outputs.len(), 2);
        assert!(decl.controls.is_empty());
    }

    #[test]
    fn reregister_unknown_type_fails() {
        let mut registry = NodeRegistry::new();
        let result = registry.reregister(oscillator_decl(), StubFactory);
        assert!(matches!(result, Err(RegistryError::TypeNotFound(ref id)) if id == "oscillator"));
    }

    // -- version tracking tests --

    #[test]
    fn initial_version_is_one_after_register() {
        let mut registry = NodeRegistry::new();
        registry.register(oscillator_decl(), StubFactory).unwrap();
        assert_eq!(registry.version("oscillator"), 1);
    }

    #[test]
    fn version_increments_on_reregister() {
        let mut registry = NodeRegistry::new();
        registry.register(oscillator_decl(), StubFactory).unwrap();
        assert_eq!(registry.version("oscillator"), 1);

        registry
            .reregister(oscillator_decl_stereo(), StubFactory2)
            .unwrap();
        assert_eq!(registry.version("oscillator"), 2);

        registry
            .reregister(oscillator_decl_stereo(), StubFactory2)
            .unwrap();
        assert_eq!(registry.version("oscillator"), 3);
    }

    #[test]
    fn versions_are_independent_per_type() {
        let mut registry = NodeRegistry::new();
        registry.register(oscillator_decl(), StubFactory).unwrap();

        let dac_decl = NodeTypeDecl {
            type_id: "dac".into(),
            audio_inputs: vec![PortDecl {
                name: "in".into(),
                channels: ChannelLayout::Mono,
            }],
            audio_outputs: vec![],
            controls: vec![],
        };
        registry.register(dac_decl, StubFactory).unwrap();

        assert_eq!(registry.version("oscillator"), 1);
        assert_eq!(registry.version("dac"), 1);

        registry
            .reregister(oscillator_decl_stereo(), StubFactory2)
            .unwrap();
        assert_eq!(registry.version("oscillator"), 2);
        assert_eq!(registry.version("dac"), 1); // unchanged
    }

    #[test]
    fn version_of_unknown_type_is_zero() {
        let registry = NodeRegistry::new();
        assert_eq!(registry.version("nonexistent"), 0);
    }
}
