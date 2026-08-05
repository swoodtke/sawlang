# Design 126 — Pre-port trio: declared AST contract, stable NodeIds, astdiff

Source: `designs/reviews/2026-08-04-compiler-preport.md` (R1, R2, R11 +
hazard 1's live bug). User decision Aug 4: land the three port-order
prerequisites now, in Python. Everything here is compiler-internal — zero
language-visible behavior change is the acceptance frame: the full suite,
bootstrap, lexdiff, sos, and `--emit-ir` output for a fixed corpus sample
must be byte-stable except where R2 deliberately fixes nondeterminism.

## R1 — Declare the cross-pass AST contract (the 59 grafts)
- `Expression` base becomes a real dataclass base (`kw_only`) carrying
  `line`, `column`, `node_id`, `resolved_type` — killing the ~80 duplicate
  per-class declarations and the stamp-on-6-declare-on-44 mismatch.
- Promote every runtime-grafted annotation the report inventories to a
  declared, typed, defaulted field; group the clumped ones into plan
  dataclasses (`CallPlan`, `MatchPlan`, `UnsafeMemPlan`) rather than loose
  scalars; DELETE the 4 dead grafts the report lists.
- Move codegen's llvmlite value/type caches OFF the AST (side tables keyed
  by node_id) — LLVM objects must never ride the tree the effect/mono
  passes walk.
- **This fixes the live bug**: `substitute_ast_types` walks
  `dataclasses.fields()`, so grafted `SawType`s currently survive
  monomorphization un-substituted (RC-2). Add the regression test the report
  sketches (a generic whose grafted type must be substituted — assert via
  behavior, not internals).

## R2 — Stable NodeId; eliminate `id()` as identity
- Parser assigns a monotonic `node_id` at construction (synthesized nodes
  get ids from the same counter via one factory).
- Rekey: the effect graph's heterogeneous `Dict[Any, ...]` (behind a typed
  `EffectKey`), move-checking's `id(VariableInfo)` keys, coro_transform's
  `*_by_id` maps.
- The two `id()`-derived GENERATED NAMES (`_CatchError_{id(expr)}`-style)
  become node_id-based → compiler output is deterministic run-to-run.
  Verify: two clean-cache compiles of the same corpus sample produce
  identical IR; add that as a test (this is the one sanctioned output
  change).

## R11 — `ast_dump.py` complete + frozen + `make astdiff`
- Extend the dump to ALL AST node types (report says ~45 of 80 covered);
  deterministic field order; node_id excluded from the dump (ids are stable
  but not meaningful cross-implementation) unless a --ids flag asks.
- `tools/astdiff.py` + `make astdiff`: dump the whole tracked .saw corpus,
  assert (a) every file dumps without falling back to a generic repr,
  (b) dump is byte-identical across two runs. This is the acceptance oracle
  for the future Saw parser port, mirroring lexdiff exactly.
- CI wiring same as lexdiff's.

## Constraints
Pyright noise rules still apply, but R1 should DELETE most of the mixin
`self.X` false-positive surface it touches — don't chase the rest. No
behavioral refactors beyond the three Rs (R3/R4/R5... are later briefs).

## Exit criteria
Zero grafted (`object.__setattr__`/plain setattr outside __init__) AST
writes remain in typechecker/codegen/coro_transform (grep-clean plus the
report's inventory checked off); no `id()` used as a persistent key or name
anywhere in sawc/; `make astdiff` green over the corpus; determinism test
green; RC-2 regression green; full suite + bootstrap + lexdiff + sos green.
