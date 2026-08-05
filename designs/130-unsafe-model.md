# Design 130 — the unsafe model, rebuilt (LANDED Aug 5)

STATUS: LANDED. Supersedes design 81's marking rules. Decisions marked
**[user]** were made in conversation.

Shipped in the six staged commits of q4's plan, suite green at each. Measured
migration, against the estimates in the table below:

| area | functions marked | line markers deleted |
|---|---|---|
| `sawc/std` (18 files) | 133 | 152 |
| `sawc/rt` (13 files) | 47 | 56 |
| `examples` (35 files) | 60 | 79 |
| `blade/src` + `blade/tests` | 5 | 0 |
| `sos/kernel` + `sos/tests` | 5 | 0 |
| `libs`, `selfhost` | 0 | 0 |
| **total** | **250** | **287** |

Two estimates were low. The marker count was 287, not ~185 — the brief's table
omitted `examples/` entirely, and `taskgroup.saw` alone held 72. The function
count was 250, not ~115, because the brief measured std and rt only.

The shape of the result held exactly: application-level Saw needed 5 marks in
blade and 5 in SOS, all of them on code that casts to a raw pointer for a libc
call or drives an MMIO register block. `libs/` and `selfhost/` needed none.

Three things the implementation had to decide that the brief did not name:

1. **The trigger rule must judge the SOURCE program.** The coroutine transform
   rewrites user bodies in place (a held `&var` param becomes a frame-resident
   `UnsafePointer<T>`; a spawned task reaches its group through an
   `UnsafeConstPointer<TaskGroup>`), so the post-transform AST attributes
   compiler-minted pointers to the user's own `main`. The check runs on the
   first type-check only; 37 net/coro examples were falsely flagged before that.
2. **A redundant `unsafe` is allowed.** Design 81 made a marker over nothing
   unsafe an error. Per-declaration that would break a conformer of an `unsafe`
   trait requirement whose own body happens not to touch anything, so the
   marker is treated as a promise about the contract rather than a claim about
   the body.
3. **Rule 7 needs no separate machinery.** A precondition expressed as an
   unsafe-typed parameter forces every caller to produce an unsafe-typed
   argument, which the trigger rule already marks. Rule 7 is rule 3 applied to
   arguments; what the implementation adds is the policy statement in the spec.

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

1. **Type marking is DECLARED, and the name is ENFORCED. [user, q1]**
   Semantics come from the declaration keyword; the compiler then requires the
   type's name to start with `Unsafe`:
   ```saw
   unsafe struct UnsafeMmioReg { addr: Int }     // ok
   unsafe struct MmioReg { addr: Int }
   // error: an unsafe type must be named `Unsafe*`
   //   help: rename to `UnsafeMmioReg`
   struct UnsafeDefaults { .. }                  // plain struct, no semantics
   ```
   Explicit opt-in (no identifier magic, no accidental capture of a benign
   `UnsafeDefaults`), while keeping the always-visible-at-use-site property of
   the prefix. Accepted cost: kernel-domain types must be named
   `UnsafePhysAddr`/`UnsafeRawFd`/`UnsafeMmioReg` rather than their bare names.
   The built-ins (`UnsafePointer`, `UnsafeMemory`) already comply.

2. **Function/closure marking uses the `unsafe` keyword in the EFFECT
   position, beside `sync` — no `@decorator` syntax. [user]**
   ```saw
   public unsafe func push(&var self, value: T) { ... }
   func with_raw<R>(&self, body: (UnsafePointer<T>) unsafe sync -> R) -> R
   ```
   Reads in Saw's existing declaration order (visibility, effects, `func`), and
   design 121's `--emit-docs` picks it up for free from the effect position.

3. **Trigger rule: a function is `unsafe` if its body or signature NAMES,
   BINDS, RECEIVES or RETURNS a value of an unsafe type — including a
   REFERENCE to one (`&UnsafePointer<T>` counts). [user, q2]**
   Deliberately broader than "performs a deref/index/arithmetic": the narrow
   form MISSES `Vector.iter()`, which merely reads `self.buffer` and passes it
   into the iterator struct — and that is bugs C2 and C5. Marking trivia like
   `self.buffer != None` is accepted; the marker is simply true there.

   **Derivation does NOT propagate. [user, q2]** A value or reference of a
   SAFE type produced inside an unsafe function (`&T` obtained from `buf[i]`)
   is safe onward — performing that derivation soundly is exactly what the
   reviewed wrapper exists for. This is what keeps `with_ref`/`with_var_ref`
   usable from safe code.

   **Closures are judged by rule 3 on their OWN body. [user, q3 — follows from
   q2]** A closure that never names an unsafe type is safe even when passed
   into an unsafe function:
   ```saw
   unsafe func with_ref<R>(&self, i: Int, body: (&T) sync -> R) -> R
   v.with_ref(0) { e in e + 1 }        // closure sees only &T -> SAFE
   ```
   Where an unsafe value genuinely IS handed to a closure, the closure's
   parameter type names it, so rule 3 marks the closure — and the closure-type
   effect slot from rule 2 carries it: `(UnsafePointer<T>) unsafe sync -> R`.

4. **Unsafety is NOT transitive for types. [user]** A `Vector` holding an
   `UnsafePointer<T>` field is a safe type — safe to name, hold, pass, store.
   Only the *functions* that touch the pointer are unsafe. This is the fix for
   the granularity hole.

5. **The line-level `unsafe` expression marker is removed. [user]**
   Load-bearing assumption, stated as std policy: an `unsafe` function must be
   short enough to review as a unit. (Note `Vector.push` becomes wholly marked,
   including the `if length >= capacity { grow() }` logic where C1's bug
   actually lived — function granularity is coarser there than line was.)

   **Oversized unsafe functions are migrated as-is here and decomposed in a
   FOLLOW-UP brief. [user]** `__saw_exec_worker` (~150 lines), the reactor
   bodies, and `rt/common/os_ops.saw` would each become wholly `unsafe`,
   violating the policy on the day it ships. Keeping the mechanical migration
   separate from judgment-heavy refactoring of the executor's hot paths is the
   deliberate tradeoff; the decomposition is filed as a tracker item.

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

## Migration plan [user, q4] — staged, NO dual-model period

No transition window where both markers are valid; there are no consumers
outside this repo. Full suite green at every step, one commit each:

1. Grammar + typechecker ACCEPT `unsafe` in the effect position on functions
   and closure types, and `unsafe struct` with the name check. No enforcement
   of the trigger rule yet — zero behavior change, everything still compiles.
2. Migrate `sawc/std` (73 functions).
3. Migrate `sawc/rt` (40 functions), plus the 2 in `blade/src`.
4. Flip the trigger rule (3) and the soundness rule (7) to hard errors.
5. Delete the line-level `unsafe` expression marker from the grammar and the
   ~185 remaining sites (mechanical).
6. Apply the accessor rule (8) across `Vector`, `Data`, `String` — this is a
   std change, not a language change, and closes RS-6 / M5 / M3.

## Exit criteria
Typechecker enforces rules 1-3 and 7; line-level marker removed from the
grammar; std + rt migrated; the accessor rule (8) applied across `Vector`,
`Data`, `String`; spec's unsafe chapter + saw-lang skill rewritten; design 81's
superseded rules marked as such. Tests: a safe function that names an unsafe
type is an error naming the fix; a safe-parameter function exposing unchecked
access is caught by the accessor tests; `--emit-docs` shows `unsafe` in the
effect field.
