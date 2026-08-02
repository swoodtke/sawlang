# Design 89-c — Cooperative op-count budget (deferred from 89-b) (queued Aug 1)

The design-89 item 6 fairness refinement, deferred by the 89-b agent
with analysis (correctly — the core executor unification landed green;
the budget is an adversarial-case fairness knob, not correctness).
Bounds how long an always-ready-io task runs between yields so it can't
starve siblings on the single ambient scheduler.

## Why 89-b deferred it (the analysis to solve)
The budget needs a per-ROOT-TASK counter threaded through every
embedded io sub-frame + forced yields inside the design-90-stabilized
io primitives. Each `read()`/`write()`/`accept()` is a SEPARATE
embedded sub-frame, so cross-call counting can't live in the sub-frame
(it resets per call). The counter must live in the ROOT task frame (or
the ambient scheduler, keyed by the running root) and be reachable
from a deep io sub-frame — the same "reachable from any frame"
problem the ambient scheduler solved with the `static __saw_exec`
singleton. Likely realization: the budget lives in the scheduler's
per-running-task record (the run-queue entry), NOT the sub-frame; a
suspending io primitive that completes without parking decrements the
CURRENT-TASK budget via the scheduler singleton, and forces a yield at
0. This sidesteps the per-sub-frame reset.

## Scope
- Per-running-task budget in the ambient scheduler's task record
  (design 89-b), seeded 128 at (re)schedule.
- Each io primitive completing WITHOUT parking decrements the current
  task's budget (via the scheduler singleton); at 0 the next
  suspending call force-yields (park-and-immediately-reschedule) and
  resets. A call that actually parks resets (already yielded).
- Op-count, NOT wall-clock (kernel-friendly, deterministic).
- Purely at existing suspension points — colorless, no language
  surface.
- Test (deterministic): a task doing a long run of ALWAYS-READY reads
  (pre-filled socketpair) with no `yield_now` cannot starve a counting
  sibling — the sibling makes progress bounded by the budget; budget-
  resets-on-park; the design-89-b core tests + net_* stay green.
- Docs: saw-lang skill (remove the design-89-b "budget deferred"
  caveat once landed); spec fairness note; tracker (89-c landed).

Bars: full suite (baseline = post-89b, 891+) + blade/libs + bootstrap
green per commit; zero xfails. Standing policy; interruption-safe;
saw-lang skill self-review.
