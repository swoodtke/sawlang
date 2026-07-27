# Option Paper 06 — Copy semantics

**Status: DECISION NEEDED (user).** Gates: the String redesign (paper 07), all
future stdlib collections, and the honesty of design principle #4 ("no hidden
allocations"). Source: `todo_jul26.md` design concern 1 and priority item 4.

## The problem, restated

Saw today has **three copy semantics coexisting**, and which one you get at
`let b = a` is invisible at the assignment site:

| Type kind | `let b = a` does | Declared via |
|---|---|---|
| POD (Int, Bool, struct of PODs) | bitwise copy | nothing |
| Refcounted / hooked | `copy()` call | `CustomCopy` |
| Resource-owning (Vector, Map, File) | **compile error without `move`** | `NoCopy` |

The spec meanwhile promises a fourth: implicit *deep copy* for collections
(`LANGUAGE_SPEC.md:437`) — which the implementation doesn't do, and which
would make an innocent `=` cost O(n) heap work, contradicting principle #4.

The stdlib made the real decision for us: `Vector` and `Map` are `NoCopy`
because bitwise-copying a heap buffer double-frees. So **the most-used types
are already move-only** — users face Rust's move discipline without Rust's
borrow checker. Wave 2's value-transfer checkpoint made this sound (no more
silent double-frees), but it also made the ergonomic cost real: `move`
everywhere, or compile errors.

## Options

### A. Status quo, documented honestly
Keep the three-way split; fix the spec to match; accept that `NoCopy` is the
de-facto default for anything owning memory.
- **Pro:** zero work; checkpoint already enforces it; explicit at declaration.
- **Con:** the split is invisible at use sites; "copy by default" remains the
  marketing while move-only is the reality; every new stdlib type must pick a
  trait and users must memorize the choice per type.

### B. Hylo/Val position — implicit copy only when trivial, explicit `.copy()` otherwise  ⭐ recommended
One rule: a type is implicitly copyable iff it is trivially copyable (POD,
recursively). Every type that owns a resource (`Deinit` conformers and
anything containing one) moves on transfer by default; duplicating one is
always a visible call: `let b = a.copy()`.
- `NoCopy` disappears as a user-facing concept — owning types just *are*
  move-by-default. `CustomCopy` becomes `Copyable` (provides `.copy()`);
  the compiler auto-derives `.copy()` memberwise where possible.
- `move` keyword stays for the cases where you want to hand off the *last*
  use explicitly; the checkpoint already knows how to demand it.
- **Pro:** one teachable rule; `=` is always O(1); allocation is always
  spelled `.copy()`; keeps the no-lifetimes story intact; matches what the
  stdlib already needs; the wave-2 checkpoint is 90% of the implementation.
- **Con:** it *is* move discipline for big types — but that's option A's
  reality too, minus the pretense. Requires the use-after-move dataflow gap
  (noted in brief 03) to be closed for good diagnostics.

### C. Spec-as-written — implicit deep copy for collections
`let b = a` deep-copies a Vector.
- **Pro:** value-semantics ergonomics; no move discipline anywhere.
- **Con:** violates principle #4 in the worst way (O(n) + allocation hidden
  behind `=`); every accidental copy is a silent perf bug; `CustomCopy`
  machinery must run element-wise; nobody who chose "systems language" wants
  this without at least CoW.

### D. Swift-style copy-on-write
Implicit copies are refcount bumps; real copy happens on first mutation of a
shared value.
- **Pro:** value semantics AND cheap `=`; proven model (Swift).
- **Con:** by far the most machinery: every owning type needs a refcounted
  buffer + uniqueness check on every mutating access; interacts badly with
  the existing `Deinit` determinism story (when does the buffer die?);
  hides *when* the O(n) copy happens rather than whether; a large runtime
  commitment this early.

## Recommendation

**B.** It's the position the critique endorsed, it matches what the stdlib
already forced, the value-transfer checkpoint built in wave 2 is precisely
its enforcement mechanism, and it's the only option where the cost model is
readable at every use site. Follow-ups it implies, in order:
1. Close the use-after-move gap (per-scope moved-set — a contained
   typechecker brief).
2. Rename/merge traits: `CustomCopy` → `Copyable` with auto-derive;
   retire user-facing `NoCopy` (internally it becomes "not Copyable").
3. Update spec §copying + LANGUAGE_SPEC.md:437, and the README claims.
4. Then paper 07's String lands as an ordinary move-by-default `Copyable`
   type — no special cases.

## Open questions to settle at decision time
- Are fixed-size arrays of POD implicitly copyable (recommend yes — trivial)?
  Arrays of owning types (recommend: move-only, `.copy()` derives per-element)?
- Function-call args of trivially-copyable structs: any size threshold where
  implicit copy should warn (recommend: no threshold now; revisit with data)?
- Does `.copy()` on a generic `T` require a `Copyable` bound (recommend yes —
  it becomes the idiomatic constraint name)?
