# Ralph Review Sprint 1

- [ ] DEAD_REUSE_INFRA — soundman-core/src/engine/mod.rs — remove cached_graph field, simplify recompile_and_send drain, remove is_additive_change; soundman-core/src/graph/compiler.rs — remove CompileResult/fresh_ids, revert to returning DspGraph
- [ ] STALE_COMMENT — soundman-core/src/engine/mod.rs:36-38 — control_values docstring mentions gate but gate is skipped
- [ ] DEAD_RETURN_CHANNEL — soundman-core/src/engine/mod.rs — return_consumer/return_producer still allocated but retired graphs are never used; AudioProcessor still pushes to return channel for no reason
