# Option Paper 06 — Copy semantics

**Status: DECIDED (Jul 27, 2026).** See the decision record below; options
kept for history. Implementation brief: `designs/09-copy-trait-family.md`.
Source: `todo_jul26.md` design concern 1 and priority item 4.

## DECISION — the `Copy` trait family

Keep existing default semantics (trivial types bitwise-copy; owning types
move) and add an explicit copy path. One umbrella trait, two policy subtraits:

```
                Copy                    "this type can be duplicated"
               /    \                   requires: func copy(self) -> Self
     ImplicitCopy    ExplicitCopy       policy: WHEN the compiler may call copy()
```

- **`Copy`** — umbrella: the type can be duplicated via `copy()`. Trivial
  types (POD, recursively) **auto-conform** with a synthesized bitwise
  `copy()` — unless they have `Deinit` or declare `NoCopy`.
- **`ImplicitCopy`** (rename of today's `CustomCopy`) — the compiler invokes
  `copy()` automatically at every transfer site. **Documented contract:
  cheap, O(1)-ish** (e.g. `Rc` refcount bump).
- **`ExplicitCopy`** — the compiler NEVER invokes `copy()`; transfer sites
  demand `move`; duplication is always a visible `v1.copy()`. **Documented
  contract: may be expensive/deep** (e.g. `Vector`, `Map`, `String`).
  Enforcement = the existing NoCopy move-required checkpoint.
- **`NoCopy`** — "not `Copy`, on purpose": never duplicable (`File`, `Mutex`).
- `ImplicitCopy` and `ExplicitCopy` are mutually exclusive on one type.
- Generic bound **`T: Copy`** (positive bound — `~NoCopy` spelling rejected:
  negative bounds make adding a conformance a breaking change) grants
  `.copy()` in the body; monomorphization synthesizes the right tier per
  instantiation. Narrower `T: ImplicitCopy` / `T: ExplicitCopy` also legal.
- Memberwise `copy()` derivation for declared conformers; a `NoCopy` field
  makes derivation impossible. Containment stays explicit: a struct with an
  `ExplicitCopy` field must itself declare `ExplicitCopy` (or `NoCopy`) —
  error with hint, no silent inference.
- Spec's implicit-deep-copy-for-collections line (`LANGUAGE_SPEC.md:437`) is
  deleted; principle #4 ("no hidden allocations") holds: the only implicit
  copies are cheap by contract.

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
- ~~Arrays~~ **DECIDED (Jul 28, user): arrays inherit the element's copy
  class** — `[POD; N]` trivial; `[ExplicitCopy; N]` is ExplicitCopy
  (move by default, `.copy()` derives per-element); `[NoCopy; N]` is
  NoCopy. The struct containment rule extended to arrays (an array is an
  anonymous struct with uniform fields). Implementation + soundness
  audit → `designs/33-array-copy-class.md`.
- ~~Size threshold~~ **DECIDED (Jul 28, user): no threshold** — trivial
  types copy silently at any size; revisit only with profiling evidence.
- ~~`.copy()` bound~~ Settled by brief 09: unbounded `T` gets no
  `.copy()`; `T: Copy` grants it.
