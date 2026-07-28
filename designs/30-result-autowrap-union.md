# Design 30 — Result auto-wrap tie-break and error-union semantics

**Status: DECIDED (Jul 28, user).** Source: critique design concern 3
(`todo_jul26.md`), tracker item D3. Two rulings:

## Ruling 1 — auto-wrap ambiguity is a compile error

In a function returning concrete `Result<T, E>`:
- `T != E`: auto-wrap as today (expr : T → `Ok`, expr : E → `Err`,
  expr : Result → no wrap).
- **`T == E` (same concrete type): bare `return expr` of that type is a
  compile error** naming the ambiguity and demanding the explicit
  variant: `Result<Int, Int>.Ok(value: x)` / `.Err(error: x)`.
  `return` of an explicit Result value is unaffected.

Generic bodies are already principled (brief 24): the wrap decision is
made abstractly against the declared parameters (`x: T` → Ok, `x: E` →
Err) and monomorphizes consistently even when an instantiation makes
`T == E`. No change there; add a test locking that behavior in
(generic `Result<T, E>` returning T, instantiated at `<Int, Int>`,
must produce Ok).

## Ruling 2 — the multi-error union is a closed, unnameable enum

For `try { } catch { }` blocks whose try-body propagates more than one
error type:
- `error`'s type is a compiler-synthesized **closed enum over exactly
  the error types propagated in that try block** (deduplicated).
- The type is **unnameable in surface syntax**. Consequence (and the
  reason this needs no new checks): it cannot appear in any written
  signature, field, return type, or annotation — escape is prevented
  structurally, as a theorem rather than a rule. Local inferred
  bindings (`let e = error`) are permitted and harmless.
- `match error { ... }` exhaustiveness is enforced over exactly the
  propagated set (no catch-all required; adding one is allowed).
- Single-error-type try blocks keep `error` as that concrete, nameable
  type (unchanged).
- Future `Error`-trait / dyn-object story, if ever built, layers on top;
  the union stays the default. (Explicitly considered and not chosen
  now: dyn Error objects — needs trait objects + RTTI; single-error-type
  restriction — ergonomic regression.)

## Implementation items

1. **The T == E diagnostic.** Probe current behavior first (likely
   silent Ok-wins or order-dependent). Implement the ambiguity error in
   the auto-wrap path (typechecker return reconciliation, the brief-24
   `_reconcile_return_type` machinery). Error test with the exact
   message; acceptance test for explicit-variant returns on
   `Result<Int, Int>`.
2. **Generic lock-in test** per Ruling 1.
3. **Union conformance audit.** Verify implemented behavior against
   Ruling 2: exhaustiveness over the exact propagated set; local
   binding allowed; confirm no path lets the union type reach a written
   signature (try to construct one; if any exists, close it and add the
   error test). Dedup of repeated error types probed and tested.
4. **Spec.** LANGUAGE_SPEC.md error-handling section gains both rulings
   (the auto-wrap table gets the T == E row; a new "The error union"
   subsection). Keep it to observable semantics.

## Report back
Probe verdicts (current T == E behavior; any union-escape path found),
mechanism + tests per item, suite tally. Deviations; non-allowlisted
commands.
