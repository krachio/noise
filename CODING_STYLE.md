# Coding Style Guide

You are writing code for an experienced systems programmer. Follow these principles strictly. When in doubt, choose the simpler, flatter, more obvious option. Every abstraction must earn its place.

## Core philosophy

Write code that solves the problem in front of you. Do not write code that solves the family of problems you imagine. Premature abstraction is worse than premature optimisation — it's harder to undo and it obscures the data flow.

The test for any file: can a competent reader understand the full data flow without jumping to any other file? If yes, you're done. If no, you've over-abstracted.

## Data and types

- **Flat data, obvious flow.** Structs are bags of data. Functions transform them. The caller owns the sequencing. This is the default. Only deviate when you can name the specific invariant an encapsulation boundary protects.
- **Types exist because the domain demands them.** If a struct doesn't map to a noun in the problem, delete it. Wrapper types, tag types, marker types — each one needs a concrete justification beyond "it's the proper way."
- **Prefer value types and contiguous storage.** `Vec`, arrays, slabs. Not linked lists, not `Box<dyn Trait>` chains, not pointer graphs. Think about what memory the CPU actually touches on the hot path.
- **POD where possible.** Keep data structures simple, copyable, inspectable. You should be able to `printf` / `dbg!` any piece of state trivially.

## Abstraction budget

- **Start with free functions operating on plain structs.** If you find a real multi-field invariant that callers can silently violate, *then* wrap it in a type with a private interior — not before.
- **No inheritance hierarchies.** No virtual dispatch unless the problem is genuinely polymorphic at runtime (plugin systems, not "different kinds of X").
- **No trait/concept/template metaprogramming** unless it removes duplication across >2 concrete instantiations that actually exist today, not ones you anticipate.
- **No design patterns by name.** No visitors, no abstract factories, no builders for 3-field structs. If you catch yourself naming a Gang-of-Four pattern, stop and ask whether a function would do.

## STL / standard library

- **Use `std::vector` / `Vec` freely.** This is the one data structure that earns its keep universally. Growable contiguous storage, reserve up front for hot paths, done.
- **Use standard algorithms when they communicate intent** (`sort`, `min_element`, `partition`, `drain`). Do not use them as a flex — a 4-line for loop that anyone can read beats a ranges pipeline that requires C++20 literacy, if the generated code is identical.
- **`std::unordered_map` / `HashMap` is not free.** For small n (< ~100 elements), a linear scan over a flat array is faster. Measure before reaching for hash maps.
- **Templates / generics for callback inlining** (avoid function pointer overhead in hot loops). This is a genuine and important use. `template<typename Fn>` / `impl FnMut(...)` — use it.
- **Do not cargo-cult STL for "compiler optimisation."** Modern compilers (GCC 12+, Clang 15+, LLVM) recognise loop patterns regardless of whether you spelled them as `std::ranges::min` or a for loop. The generated assembly is identical. Write whichever reads clearer in context.

## Memory and allocation

- **No heap allocation on the hot path.** Pre-allocate at init, reserve vectors, use slab pools if needed. `malloc` in an audio callback or inner simulation loop is a bug.
- **Prefer `vector::reserve` / `Vec::with_capacity` over custom allocators.** The custom pool/slab is a last resort for when profiling shows allocation is the bottleneck, not a starting point.
- **Free lists and intrusive linked lists are almost never worth it.** They trade move cost for scan cost and kill the prefetcher. Profile first.

## Error handling

- **Result types for recoverable errors.** `Result<T, E>` in Rust, `std::optional` or error codes in C++. Not exceptions on hot paths.
- **`assert` / `debug_assert!` for invariants** that indicate programmer error, not runtime conditions. These document the contract.
- **Fail loudly and early.** Do not silently swallow errors. Log and propagate.

## File and module structure

- **Single-file modules are fine and often preferable.** A 200-line header that contains a complete, self-contained component is better than 6 files with 40 lines each spread across a directory tree.
- **No premature decomposition.** Don't split into files until you have a reason (separate compilation, independent testability, genuinely orthogonal concerns). "It's getting long" is not a reason until ~500 lines.
- **Headers / modules should be readable top-to-bottom.** Types first, then helpers, then public operations. A usage comment at the top (3-5 lines showing the API in action) is worth more than a page of doc comments on individual methods.

## Naming

- **Short, specific names.** `count`, `key`, `bucket`, `scratch` — not `eventCounter`, `schedulingKey`, `bucketContainer`, `temporaryScratchBuffer`.
- **Namespace / module prefixing over long names.** `radix::push` not `radix_heap_push_event`.
- **No Hungarian notation, no `m_` prefixes.** Trailing underscore for private members in C++ if you must distinguish, otherwise just use clear names.

## Performance thinking

- **Think about what memory you're touching and in what order.** This matters more than algorithmic complexity for n < 10,000. Cache locality dominates.
- **Profile before optimising.** The first version should be the boring, obvious one. SoA layout, SIMD intrinsics, lock-free queues — all legitimate, but only after the profiler says so.
- **Amortised O(1) is not worst-case O(1).** Know which one your system requires. Real-time audio needs bounded worst-case. Batch processing doesn't care.
- **Don't optimise the control path.** If something runs at 1ms poll rate with 100 elements, a linear scan is fine. Save your complexity budget for the hot path.

## Language-specific notes

### C++

- **Rule of zero.** If `std::vector` and value semantics handle your lifetime, write no destructor, no copy/move constructors. Let the compiler do it.
- **`auto` for type deduction is fine** when the type is obvious from the RHS. Not fine when it obscures what you're working with.
- **Avoid `std::function` on hot paths.** It heap-allocates and type-erases. Use a template parameter for callables.
- **`constexpr` and `static constexpr` for compile-time constants.** Not `#define`, not `const int`.

### Rust

- **Don't fight the borrow checker with clever types.** If you need two mutable references to different parts of a struct, use `split_at_mut`, restructure the data, or accept a temporary `Vec` and rebuild. Don't reach for `RefCell` / `Rc` / `unsafe` until you've exhausted the simple options.
- **`drain(..)` and `split_at_mut` are your friends** for the "move data between containers" pattern.
- **Avoid trait boilerplate for ordering.** If you need a sorted collection with custom ordering, a `Vec` with `sort_unstable_by` and `pop` from the end is simpler than implementing `Ord` on a wrapper type — especially for small n.
- **No async unless you have actual I/O concurrency.** `async` infects everything it touches. A synchronous event loop with `sleep` is simpler and sufficient for most real-time systems.

### C

- **Use C when the ecosystem demands it** (kernel modules, embedded, FFI boundaries). Otherwise prefer C++ for `std::vector` and templates alone — they eliminate the two biggest sources of boilerplate.
- **If writing C: one growable-array implementation per project, then stop.** Don't reinvent it per module.

## The decision checklist

Before writing any abstraction, ask:

1. **Can I name the specific bug this prevents?** Not a category of bug — a specific scenario in this code.
2. **Does the reader need to understand the abstraction to understand the data flow?** If yes, you've added a concept they must learn.
3. **Will this exist in the final version, or am I building scaffolding?** Scaffolding rots.
4. **Can I delete this and replace it with a function?** If yes, do that.

If you cannot answer (1) with a concrete scenario, do not add the abstraction.
