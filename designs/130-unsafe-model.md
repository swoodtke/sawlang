# Design 130 — DRAFT: the unsafe model, rebuilt (DO NOT DISPATCH)

STATUS: DRAFT for user review (Aug 4 evening). Supersedes design 81's marking
rules if accepted. Decisions below marked **[user]** were made in conversation;
items under "Open questions" still need a call.

## Why
The Aug 4 review sweep found five probe-proven memory bugs in safe-facing std
code (`designs/reviews/2026-08-04-stdlib-review.md`, C1/C2/C4/C5/H1 + RS-6
below). Classifying them showed the marking model — not just the individual
sites — is implicated:

- `vector.saw` carries **2** `unsafe` markers in ~530 lines; `data.saw` carries
  **0** in ~450. Design 81's rule "a `self`-method of a pointer-field struct is
  already the marked domain" blanket-marks the whole type, so nothing
  distinguishes `pop` (sound) from `push` (overflows on alloc failure), or
  `with_ref` (unchecked index) from `get` (checked).
- `string.saw` carries **21** markers, because `String` is not a pointer-field
  struct — so the marker fired correctly on `byte_at`'s `unsafe ptr[index]`,
  and the bug happened anyway: the unsafety was laundered out through a
  `public func byte_at(&self, index: Int) -> Int8` carrying no obligation.

So: the marker is too coarse inside pointer-holding types, and there is no
rule stopping an unsafe operation from being re-exported through a safe
signature.

## Proposed model

1. **Type marking is declared, not inferred.** A type may be declared
   `unsafe struct Foo`. **[user]** Any `Unsafe`-prefixed type (including
   user-defined `UnsafeXxx`) is unsafe.
   *Synthesis to decide (open q1):* make the semantics come from the
   declaration and have the compiler **enforce** the `Unsafe*` name — so
   `unsafe struct MmioReg` errors with "an unsafe type must be named
   `UnsafeMmioReg`". Keeps the always-visible-at-use-site property of the
   prefix without deriving semantics from an identifier.

2. **Function/closure marking uses the `unsafe` keyword in the EFFECT
   position, beside `sync` — no `@decorator` syntax. [user]**
   ```saw
   public unsafe func push(&var self, value: T) { ... }
   func with_raw<R>(&self, body: (UnsafePointer<T>) unsafe sync -> R) -> R
   ```
   Reads in Saw's existing declaration order (visibility, effects, `func`), and
   design 121's `--emit-docs` picks it up for free from the effect position.

3. **Trigger rule: a function is `unsafe` if its body or signature NAMES,
   BINDS, RECEIVES or RETURNS a value of an unsafe type.**
   Deliberately broader than "performs a deref/index/arithmetic": the narrow
   form MISSES `Vector.iter()`, which merely reads `self.buffer` and passes it
   into the iterator struct — and that is bugs C2 and C5. Marking trivia like
   `self.buffer != None` is accepted; the marker is simply true there.

4. **Unsafety is NOT transitive for types. [user]** A `Vector` holding an
   `UnsafePointer<T>` field is a safe type — safe to name, hold, pass, store.
   Only the *functions* that touch the pointer are unsafe. This is the fix for
   the granularity hole.

5. **The line-level `unsafe` expression marker is removed. [user]**
   Load-bearing assumption to state as std policy: an `unsafe` function must be
   short enough to review as a unit. (Note `Vector.push` becomes wholly marked,
   including the `if length >= capacity { grow() }` logic where C1's bug
   actually lived — function granularity is coarser there than line was.)

6. **Calling an unsafe function from a safe function needs no ceremony.
   [user]** The unsafe function is the reviewed wrapper; its callers are safe.

7. **The soundness rule (what makes 6 safe).** A function whose parameters are
   ALL safe types must be sound for EVERY input. Preconditions are expressed by
   taking an unsafe-typed parameter.
   - `with_ref(index: Int)` takes only safe types → must be sound for all
     indices → must bounds-check.
   - `dealloc(ptr: UnsafePointer<Int8>, size: Int, align: Int)` names an unsafe
     type → any caller must name it too → the obligation propagates through
     rule 3 automatically.
   This gives Rust's two-category behavior (`unsafe fn` with preconditions vs a
   safe fn wrapping `unsafe {}`) with ONE marker and no `unsafe(caller)`
   spelling. It is what makes rule 6 sound rather than merely convenient.

8. **The accessor rule (corollary, user-argued).** On a safe type, every
   indexed accessor is checked. Unchecked access exists only through
   `UnsafePointer`. An out-of-range index PANICS for direct accessors, or
   returns `None`/`Err` for `get`-shaped ones — never a silent no-op, never a
   clamp. This kills RS-6's unchecked indices, M5's silent no-ops, and M3's
   clamping in one rule.

## Migration cost (measured, `.build/scratch/probe_unsafe_surface.py`)

| area | functions needing `unsafe` | existing line markers |
|---|---|---|
| `sawc/std` | 73 / 411 (18%) | 135 |
| `sawc/rt` | 40 / 106 (38%) | 50 |
| `blade/src` | 2 / 96 (2%) | 0 |
| `libs`, `selfhost`, `sos/kernel` | 0 | 0 |

Net: delete ~185 line markers, add ~115 function keywords, moved from buried
lines into signatures. Application-level Saw is ~0% — the model carves at the
right joint.

## Open questions
- **q1** Declaration-marked with enforced `Unsafe*` naming, or pure name-prefix
  semantics as originally proposed? (Prefix-only cannot mark `PhysAddr`/`RawFd`
  without renaming, gives a benign `UnsafeDefaults` unwanted semantics, and has
  no opt-out.)
- **q2** Does rule 3 fire on a `&`/`&var` reference to an unsafe-typed field,
  or only on the value? (Affects how many rt/ functions get marked.)
- **q3** Closure literals passed INTO an unsafe function: judged by rule 3 on
  their own body (so a closure receiving a safe `&T` stays safe). Confirm —
  this is what keeps `with_ref`/`with_var_ref` callable from safe user code.
- **q4** Migration mechanics: one sweeping commit per area, or incremental with
  both models accepted during transition?

## Exit criteria (once approved)
Typechecker enforces rules 1-3 and 7; line-level marker removed from the
grammar; std + rt migrated; the accessor rule (8) applied across `Vector`,
`Data`, `String`; spec's unsafe chapter + saw-lang skill rewritten; design 81's
superseded rules marked as such. Tests: a safe function that names an unsafe
type is an error naming the fix; a safe-parameter function exposing unchecked
access is caught by the accessor tests; `--emit-docs` shows `unsafe` in the
effect field.
