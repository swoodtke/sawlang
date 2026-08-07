# Design 177 — an infinite `while {}` with no exit types `Never`

**Status: PRE-DECIDED (user, Aug 7 morning — decision 9, tracker commit
3134cf7: "while{} types Never, true-literal excluded"). This brief just
schedules the decided rule. QUEUE: immediately after 176 integrates
(typechecker surface); it UNBLOCKS "172 part 2" (DF-172e — the arena and
the last `__saw_rt_panic` seam body in Saw need a Saw spelling for a
diverging `noreturn` function).**

## The rule (as decided)

- The conditionless infinite loop `while { ... }` whose body contains NO
  `break` (any `break`, valued or not, keeps today's typing: `break v`
  yields `T`) is a DIVERGING expression: it types `Never`, exactly like
  `panic(...)`. A function whose body ends in one satisfies `-> Never`
  (and any `-> T`, since Never flows to everything, matching panic).
- **The true-literal spelling is EXCLUDED** (the decision's carve-out):
  `while true { ... }` keeps its current typing and does NOT become Never —
  the conditionless form is the deliberate "this diverges" spelling; a
  literal-`true` condition stays an ordinary loop a later edit may falsify.
- `cancelled()`/budget instrumentation interplay: inside a TASK body the
  op-budget backedge charge (127) makes the loop suspending — a `Never`
  loop in a `sync` context must still be sync-legal (no charge inserted
  outside task bodies; verify, don't assume).

## Units

1. Typechecker: the divergence rule + `-> Never` satisfaction; the
   reachability consequence (code after the loop is unreachable — reuse
   panic's handling).
2. Tests: `-> Never` with `while {}` (freestanding + hosted), the
   true-literal exclusion pinned, break-forms unchanged, unreachable-after
   diagnostics, a `sync` body case.
3. Docs: spec (beside `panic`/Never), skill digest line.
4. Tracker: close decision 9 + DF-172e; note 172-part-2 is dispatchable.

## Gates

Full battery. Small unit — one agent, short.
