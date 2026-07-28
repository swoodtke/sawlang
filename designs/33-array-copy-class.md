# Design Brief 33 — Fixed arrays inherit the element copy class

**Status: DECIDED (Jul 28, user) — implementation brief.** Source:
design 06 open question, tracker D9a. Ruling: `[T; N]` has T's copy
class — trivial elements → trivial array (unchanged); ExplicitCopy
elements → ExplicitCopy array (move by default, `.copy()` = per-element
copy); NoCopy elements → NoCopy array (move-only). D9b also decided: no
size-threshold warning on large trivial copies (no work).

## Item 0 — soundness probe FIRST (suspected live hole)
Briefs 09/14/17 wired containment, transfer checking, and drop glue for
structs, Vector, and Map — fixed arrays were likely never covered. Probe
in `.build/scratch/`:
1. `var a: [Vector<Int>; 2] = ...; let b = a` — does the checkpoint
   demand move/copy, or bitwise-copy (double-free on scope exit)?
2. Does a fixed array of Deinit elements run element deinit at scope
   exit at all, or leak?
3. Struct containing `[File; 2]` — do the containment rules fire?
Report the verdicts; every hole found becomes a red-proven test before
its fix (verify-twice).

## Items
1. **Copy-class computation** for ARRAY types: derive from element type
   in the shared classification helper (wherever auto-Copy/containment
   classification lives — one place, used by checkpoint + containment +
   deinit detection).
2. **Value-transfer checkpoint**: array-typed transfers follow the
   derived class (move required / `.copy()` allowed / trivial silent).
   `.copy()` on an ExplicitCopy array lowers to per-element copy in
   index order (memberwise-`.copy()` derivation extended to arrays).
3. **Drop glue**: fixed arrays of Deinit elements release elements in
   REVERSE index order at scope death; compose with `__deinit_in_place`
   for arrays nested in structs/enums. Array literals of owning values
   are transfer sites per element (move semantics into the literal).
4. **Containment**: structs/enums holding owning-element arrays inherit
   the class (extend the existing containment checks to look through
   ARRAY fields).
5. **Tests**: per class (trivial unchanged; ExplicitCopy array move +
   copy + double-free-free; NoCopy array move-only error on copy
   attempt); element deinit order printed; struct-containing-array
   containment error; array literal move-in; -O0 spot check on the
   deinit tests.
6. **Docs**: LANGUAGE_SPEC.md arrays + copy sections; design 06 already
   annotated.

## Hazards
Double-free family — deinit_*/implicit_copy_*/string_* ordering suites
at every checkpoint. Don't disturb Vector/Map (heap collections) — this
brief is stack fixed-arrays only.

## Report back
Item-0 verdicts (each hole + its red test), then per item mechanism +
verification. Deviations; non-allowlisted commands.
