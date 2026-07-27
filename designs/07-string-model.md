# Option Paper 07 — The String model

**Status: DECISION NEEDED (user), after paper 06.** String is the first stdlib
type designed under the new copy semantics, and it stresses every part of the
memory model — that's why it's the right forcing function. Source:
`todo_jul26.md` design concern 5 and priority item 4.

## Where strings stand today

`String` is a raw NUL-terminated `char*`: `std/string.saw` casts it to
`UnsafePointer<Int8>` and calls `strlen`. Consequences:
- `len()` is O(n); interior NUL bytes silently truncate; "UTF-8 string" in
  the spec is aspiration, not fact.
- **No ownership**: literals point at static data, `+`/interpolation results
  point at heap allocations (since brief 05) that nothing ever frees, and
  nothing distinguishes the two. The interpolation fix deliberately leaks,
  with a comment pointing here.

## Options

### A. Owned `String { ptr, len, capacity }` with `Deinit`  ⭐ recommended
The systems-language standard (Rust `String`, C++ `std::string` minus SSO to
start). Byte buffer, UTF-8 by convention, O(1) len, interior NULs fine,
`Deinit` frees — so interpolation/concat results stop leaking the moment the
type lands. Under paper 06-B it's move-by-default with explicit `.copy()`.
- **Pro:** deterministic, no runtime beyond malloc/free, model users expect,
  exercises Deinit/Copyable/checkpoint machinery end-to-end (that's the
  point), FFI story is explicit (`toCString()` allocates/borrows at the
  boundary).
- **Con:** move discipline applies to strings — the most-passed-around type.
  `print(s)` etc. must take `&s`-style non-consuming params (they already
  conceptually do — receivers/params that don't store can borrow); real
  ergonomic pressure lands on the use-after-move diagnostics from 06's
  follow-up #1.

**The literal problem** (must solve inside A): `let s = "hi"` — static data
must not be freed, and must not require an allocation per literal mention.
  - A1. **`capacity == 0` sentinel means borrowed/static** — one word, no
    branch cost on reads, `deinit` checks capacity, mutation promotes to
    owned. Cheap, invisible, recommended.
  - A2. Distinct `StaticString` type + implicit widening — more honest types,
    but infects every API signature; overkill now.

### B. Immutable refcounted string (`Rc`-style buffer)
Copies are refcount bumps; mutation goes through a builder.
- **Pro:** cheap to pass everywhere; no move discipline for strings; no CoW
  uniqueness machinery (immutable).
- **Con:** refcount traffic on every transfer; needs `Arc` variant story for
  `Send`; a *second* memory-management regime existing only for String —
  undermines "one rule" from 06-B; builder-based mutation is clunky for a
  systems language's workhorse type.

### C. Status quo plus length (`{ ptr, len }` unowned view)
Fixes O(n)/NUL issues, ignores ownership.
- **Pro:** small step.
- **Con:** leaks stay; the "who frees this" question remains unanswered and
  gets harder as the stdlib grows on top. Punt, not a plan.

## Sub-decisions (apply to A; recommendations inline)

- **UTF-8 guarantee:** validate at literal-compile-time (free) and at
  explicit `String.fromBytes()` (checked, returns `Result`); raw byte access
  via `bytes()` view. Don't validate on every operation.
- **Indexing:** NO `s[i]` integer indexing (it's bytes-vs-scalars confusion
  incarnate). Provide `bytes()` (O(1) random access) and `chars()` (scalar
  iterator) — decide `s[i]` never, not "later".
- **Interpolation/concat:** build directly into an owned `String`; the brief-
  05 leak comment gets deleted; sizing pass already exists.
- **FFI:** `withCString { ptr in ... }` scoped borrow (NUL-terminated copy
  only when the buffer isn't already terminated) — keeps the no-escape
  property.
- **SSO (small-string optimization):** explicitly deferred; changes ABI of
  the struct, do it before separate compilation or never.

## Recommendation

**A with A1**, sequenced strictly after the 06 decision (its transfer
semantics ARE 06's semantics). Implementation shape: one brief for the type +
literals + deinit + interpolation handoff; a second for the API surface
(`+`, `len`, `bytes`, `fromBytes`, FFI) migrating `std/string.saw` off
`strlen`. `process_simple`'s pre-existing xfail (Command.output capture)
likely gets fixed for free once real ownership exists — verify then.
