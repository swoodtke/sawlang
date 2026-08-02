# Design 101 — DF7: suspending method under nested `if` in a driven loop silently blocks (queued Aug 2)

Found by the design-89-c agent (tracker DF7, with repro). A suspending
METHOD call buried under a nested `if` inside a `while` in a
driven/spawned body is SILENTLY compiled as a plain blocking call —
not embedded as a driven sub-frame — so its cooperative suspension is
a no-op (IR shows `call @TcpStream_read` instead of the
`__Frame_..._resume` drive). No error, wrong behavior: the worst
diagnostic class (the documented "buried suspending method" case
ERRORS cleanly; this shape does NOT).

Same FAMILY as design 96's root cause (structural-suspension
detection missing a shape — there: nested free-fn edges; here: a
method call under nested control flow inside a loop), so start from
design 96's `structurally_susp_fns` / `_scan_method_callees` work in
coro_transform.py.

## Scope
1. Root-cause: why does the driven-body scan see a top-level method
   call and one under a single `if`, but MISS one under `if` nested in
   `while` (or whatever the precise boundary is — map it exactly:
   if-in-while, if-in-if, match arms, else branches, guard bodies).
2. Fix so the scan is structural over ALL statement/expression nesting
   (the design-96 pattern: one canonical walker, not per-shape
   special cases). Every suspending method call in a driven/spawned
   body must either EMBED correctly or ERROR cleanly (the design-74
   unsupported-shape error) — never silently block.
3. Sweep for remaining silent-blocking shapes: an exhaustive
   shape-matrix probe (top-level / if / else / if-in-while /
   match-arm / nested-block / closure body) asserting each either
   round-trips cooperatively or errors — no silent third outcome.
   This closes the CLASS, not just the instance.
4. Tests: the DF7 repro (nested-if read/write in a driven loop)
   round-trips; the shape matrix; coro_*/taskgroup_*/net_* stay
   green. Re-simplify the design-89-c `net_budget_fairness` workaround
   (it moved calls to the loop top-level to dodge DF7) back to the
   natural nested form as the acceptance.
5. Docs: tracker (DF7 closed); skill only if the supported-shape
   story changes.

Bars: full suite (baseline 929) + bootstrap (incl. libs) green per
commit; zero xfails. Standing policy; foreground suites; watchdog
hangs; interruption-safe; saw-lang skill self-review.
