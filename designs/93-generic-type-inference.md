# Design 93 — generic type-argument inference (landed Aug 2; brief backfilled)

NOTE: this brief was written AFTER landing (the file was never checked
in pre-dispatch; the implementing agent worked from the dispatch
prompt, which matched this content). Recorded here as-landed so the
designs/ ledger stays complete. Commits: `cce6966` (feature + tests),
`e6ea22f` (docs), `cab83a4` (optional auto-wrap inference). Suite
910 → 915, zero xfails; bootstrap green.

## What was decided
Infer generic type arguments at call sites — free functions AND
methods — so `v.map({ $0.to_string() })` works without `map<String>`.
Explicit `<...>` stays always-legal and always wins. Inference NEVER
silently picks under ambiguity — it errors, naming the un-inferable
parameter (never-hide-errors / expected-not-easy).

## As-landed boundary
INFERS: from argument types (single + multi param); from a closure's
inferred RETURN type (`map`'s U, `fold`'s accumulator from the initial
arg); through optional auto-wrap (`5` into `T?` solves `T = Int`);
mixed explicit prefix + inferred rest; unconstrained trailing param
falls back to its declared default; driven/spawned generic calls
(`__drive`/`group.spawn`) — inference stamps `type_args` before the
effect/coro mono rewrite, so instantiation is byte-identical to
explicit.

STILL EXPLICIT: a generic OVERLOAD set (inference not run across
overloads — would create new cross-overload ambiguity; design-55
exact-match model untouched); a param solvable only by a LATER
argument than one it gates (single left-to-right pass, non-closure
args then closures); labeled out-of-order args are mapped
positionally for inference.

## Mechanism (for future maintainers)
`_unify_infer` structurally matches abstract param types against
actual arg types. A sandboxed pre-pass (`_infer_snapshot`/`_infer_
restore` — rolls back moves, mono queues, poly-call edges) discovers
arg types; solved args are stamped onto `expr.type_args` so the
EXPLICIT path (bounds, effect-poly, codegen mono, coro rewrite) runs
unchanged. Args are checked twice (sandboxed + real); bootstrap
timing unchanged.

## Diagnostics
- underdetermined: ``cannot infer type argument `T` for function
  `make``` + explicit-args hint
- conflict: ``it is required to be both `Int` and `String```
- bounds: ``type `Int` does not satisfy the `Tagged` bound`` on the
  inferred type. Fix-on-discovery bonus: generic-METHOD calls did no
  bound checking at all before; `_check_type_param_bounds` now runs on
  explicit and inferred method calls.

## Process note
The missing-brief slip is the lesson: a design number in the tracker
MUST have its `designs/NN-*.md` checked in BEFORE dispatch.
