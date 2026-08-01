# Design 87 — Consolidate fixed-width literal coercion + stable type-ids (DECIDED Aug 1)

Two correctness consolidations the session's history argued for.

## Item 1 — ONE literal-coercion pass (stop the whack-a-mole)
An integer literal defaults to platform `Int` (i64 hosted). When it
flows into a FIXED-WIDTH expected type it must adopt that type +
range-check AT the literal. This has been patched PER POSITION,
reactively, ~8 times (struct field, let, comparison, arithmetic,
unary minus, param, return, enum payload) — each found by an ICE.
Fix it ONCE:
- Route integer-literal typing through the existing EXPECTED-TYPE
  propagation (designs 29/40 — the channel already used for
  closure-param inference and literal-into-Vector). A literal (or a
  bare-literal-typed subexpression) flowing into a slot with a known
  fixed-width expected type coerces + range-checks there, uniformly.
- AUDIT + cover the still-unpatched positions with tests: array-
  literal elements into `[IntN; M]`/`Vector<IntN>`; Map/Set literal
  keys+values; DEFAULT parameter values; `if`/`match` arm results
  merging to a fixed-width type; COMPOUND-ASSIGN RHS (`x += 1`,
  x: Int8); tuple elements; any others the audit finds.
- DELETE the scattered per-position coercion code the central pass
  subsumes (leave only what genuinely can't route through expected-
  type; report what stays and why).
- INVARIANT (the hazard): NO change to platform-`Int` behavior where
  there is no fixed-width expected type — a bare `let x = 5` stays
  platform Int; `Int`/`Int` arithmetic unchanged. The full suite is
  the oracle; run attentively (this touches every integer literal).
- Range errors stay clean compile errors (e.g. `256` into `UInt8`).

## Item 2 — stable erased-error type-ids (future separate-compilation)
Design 72's downcasting type-id is a per-compilation MONOTONIC COUNTER
memoized by mangled name — correct today (whole-program), but two
separately-compiled units would assign DIFFERENT ids to the same
type, breaking `is<T>()`/`take<T>()` across the boundary. Replace with
a STABLE scheme: a deterministic hash of the mangled type name (reuse
the FNV/Hasher machinery; pick a width that makes collisions
negligible and DOCUMENT the collision posture — a 64-bit hash is
fine). Keep is<T>/take<T> behavior identical; existing downcasting
tests stay green; add a test asserting the id is stable across two
compiles of the same type (same emitted constant). No separate
compilation exists yet — this is future-proofing a cheap seam now.

## Docs / tracker
Spec (literal-coercion: "a literal adopts a fixed-width expected type
everywhere"); saw-lang skill (the fixed-width gotcha simplifies —
update it); tracker (both items closed; note the audit result).

Bars: full suite (baseline = post-86) + blade/libs + bootstrap green
per commit (one commit per item); zero xfails. Standing policy;
interruption-safe; saw-lang skill self-review.
