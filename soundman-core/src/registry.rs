use std::collections::HashMap;

use crate::graph::node::DspNode;
use crate::ir::types::NodeTypeDecl;

pub trait NodeFactory: Send + Sync {
    fn create(&self, sample_rate: u32, block_size: usize) -> Box<dyn DspNode>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RegistryError {
    TypeNotFound(String),
    DuplicateType(String),
}

impl std::fmt::Display for RegistryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::TypeNotFound(id) => write!(f, "node type not found: {id}"),
            Self::DuplicateType(id) => write!(f, "node type already registered: {id}"),
        }
    }
}

impl std::error::Error for RegistryError {}

pub struct NodeRegistry {
    types: HashMap<String, NodeTypeDecl>,
    factories: HashMap<String, Box<dyn NodeFactory>>,
}

impl NodeRegistry {
    #[must_use]
    pub fn new() -> Self {
        Self {
            types: HashMap::new(),
            factories: HashMap::new(),
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
        self.factories.insert(type_id, Box::new(factory));
        Ok(())
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
        Ok(factory.create(sample_rate, block_size))
    }

    #[must_use]
    pub fn get_type(&self, type_id: &str) -> Option<&NodeTypeDecl> {
        self.types.get(type_id)
    }

    #[must_use]
    pub fn type_ids(&self) -> Vec<&str> {
        self.types.keys().map(String::as_str).collect()
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
        fn num_inputs(&self) -> usize { 0 }
        fn num_outputs(&self) -> usize { 1 }
        fn set_param(&mut self, name: &str, _value: f32) -> Result<(), ParamError> {
            Err(ParamError::NotFound(name.into()))
        }
        fn reset(&mut self, sample_rate: u32) { self.sample_rate = sample_rate; }
    }

    struct StubFactory;

    impl NodeFactory for StubFactory {
        fn create(&self, sample_rate: u32, _block_size: usize) -> Box<dyn DspNode> {
            Box::new(StubNode { sample_rate })
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
        assert_eq!(result.unwrap_err(), RegistryError::DuplicateType("oscillator".into()));
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
}
