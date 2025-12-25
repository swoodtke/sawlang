# Saw Language Project

A modern systems programming language combining Rust's safety with Swift's elegance.

## Project Status

Currently in design phase. See `LANGUAGE_SPEC.md` for the full specification.

## Key Design Decisions

### Memory Management
- Rust-style ownership and borrowing
- No garbage collector
- Deterministic destruction
- Lifetimes for reference validity

### Mutability
- Immutable by default (`let`)
- Explicit `var` for mutable bindings
- `&` for immutable refs, `&mut` for mutable refs

### Type System
- Algebraic data types (enums with data)
- Traits for polymorphism
- Generics with trait bounds
- No null - `?T` optionals instead
- `Result<T, E>` for error handling

### Syntax Philosophy
- Expression-oriented (everything returns a value)
- `guard let` for early exits (from Swift)
- String interpolation: `"Hello, {name}!"`
- Trailing closure syntax
- Pattern matching as core feature

### Key Differences from Rust
1. `var` instead of `let mut`
2. `?T` for optionals (Swift-style)
3. `guard let` for early unwrapping
4. Simpler closure syntax: `{ x in x * 2 }` or `{ $0 * 2 }`
5. Named tuple fields

### Concurrency
- Async/await
- Channels for message passing
- `Send`/`Sync` traits for thread safety

## Open Questions

- Final language name (Saw is placeholder)
- Semicolons: required, optional, or forbidden?
- Compilation target: LLVM, VM, or transpilation?
- Reference counting as alternative to pure ownership?

## File Structure

```
LANGUAGE_SPEC.md   # Full language specification
CLAUDE.md          # This file - project context
```
