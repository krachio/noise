Code is for humans. Readability is the primary design constraint. Names, structure, and types should make intent obvious. Code that is clever but opaque is wrong.

- Use the strictest type checking available. No escape hatches. Types serve as documentation
- Idiomatic, mostly functional, mostly pure. Small reusable functions
- DTOs over god-classes. Collocate related logic
- No redundancy. No verbose comments where code is clear
- Small, incremental commits with clear messages; no monolithic dumps
- Any user correction or preference gets added to CLAUDE.md immediately
