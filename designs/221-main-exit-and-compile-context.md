# Design 221 — main's exit status, the `main` rule, and the per-compile LLVM context

**Status: RULED (user, Aug 14), queued behind 218 stage 4. Landing this
unblocks the design 220 re-gate** (the parked branch
`worktree-agent-a347ef517d8ff1a2e` integrates only after this brief and a
re-gate — see the 220 tracker entry). Three DFs, one brief, because their
fixes share gates and one funnel: DF-220a (compile self-reproducibility),
DF-220b (exit-status propagation), DF-220c (the `main` rule). Every decision
below is ruled; the units execute.

Factual foundation: two Aug-14 sweeps, both probe-backed —
`.build/scratch/sweep220a/RESULTS.md` and `sweep220b/RESULTS.md` (GITIGNORED;
their key facts are in the tracker's DF-220a/b/c entries and restated here;
the sweep matrices become this brief's conformance rows). The obligation-2
consumer sweep for Part B is DONE — it is the 220b sweep's §4: blade test and
test_runner.py judge by rc==0 and are inert today (all 43 test mains across
blade/libs/selfhost/bench are Void + panic-based, verified by compile); the
only live exit-code consumers of driven programs are irdet itself and
`irdet_remote.py:59`'s `--plan` guard.

## Part A — DF-220a: per-compile LLVM binding context (fix A, measured)

Mechanism (pinned by the sweep): every `binding.parse_assembly` at
`codegen/core.py:3132`/`:3148` omits `context=` and lands in LLVM's
process-global `LLVMContext`; llvmlite's ABI-size queries
(`core.py:2091-2096` → `_get_ll_global_value_type`) parse a throwaway module
carrying the compile's whole identified-type table into that same context
(~92 parses × ~45 types per compile), so from the second in-process compile
on, struct names acquire `.NNNN` uniquing suffixes in optimized IR text.
Text-only: objects and the unoptimized sidecar are byte-identical; nothing
is miscompiled today.

**A1 — route every parse through a per-compile `binding.create_context()`.**
The sweep's `probe_fix.py` measured this working: three compiles in one
process, unopt/opt/obj all identical AND equal to today's fresh-process
output — zero corpus churn expected, and irdet --all is the proof. Two known
snags the unit must handle, not discover: llvmlite's `Type.get_abi_size`
hard-codes the global context, so sawc must own that query (its own
throwaway module parsed with the compile's context, or layout computed from
the data-layout string — implementer's choice, both sketched in RESULTS.md);
and the created context must outlive every `ModuleRef`/target-machine use of
the compile. Rider benefit worth stating in the commit: each compile
currently leaks ~45 named types / ~4200 uniquings into a design-115 worker's
global context permanently.

**A2 — the gate lane that would have caught this.** `tools/reemitdiff.py` is
the tool for this exact question but compares only the two artifacts that do
NOT diverge (unoptimized sidecar + object) — green and blind — and it is not
in `battery.sh`'s STAGES. Extend it (or add a sibling check) to compile one
file TWICE IN ONE PROCESS and byte-compare the OPTIMIZED IR, and add the
lane to STAGES. Re-run design 115's bit-identity audit (full suite diffed
against `--subprocess`) as part of this unit's gate.

## Part B — DF-220b: the entry executors return main's result

Mechanism (pinned): the value reaches the frame's `__result` slot and both
synthesized entry executors declare themselves Void and drop it.
`_make_driver` — every non-main driven root — already does the correct
`take`/`move __res` read; the fix gives the two executors the driver's
plumbing. Panics are unaffected (exit 134 everywhere, verified incl. MT);
suspending `-> Void` is clean; `--freestanding` shares the bug, so the fix
lands in the target-independent entry synthesis.

**B1 — conformance rows FIRST (obligation 3).** Exit-status propagation is a
user-visible contract with zero rows today. Promote the 220b sweep's matrix:
sync `-> Int`; suspending `-> Int`; suspending `-> Int` + spawn (ambient);
suspending `-> Int` + `TaskGroup(threads: N)`; suspending `-> Void`; panic in
suspending main; panic in a spawned task under MT — each asserting the real
process exit code. Plus Part C's rows. Written failing (or XFAIL-pinned)
before B2/B3 land.

**B2 — the single-frame executor.** `_make_entry_executor`
(coro_transform.py:6275-6278, line numbers pre-stage-3): declare `fb.ret`,
read `__result` exactly as `_make_driver` does. Local change.

**B3 — the ambient root gets a real cell (RULED: root cell +
executor-side conversion).** Today `_make_ambient_entry_executor` boxes
main's frame as `Box<any Resumable>` and `__saw_exec_run_root`
(std/taskgroup.saw:1487) enqueues it with a `__VoidCell` — after erasure the
typed `__result` is unreachable, and cells are the executor's existing
result channel (a spawned task's value travels out through its typed cell).
The ruled shape: the SYNTHESIZED EXECUTOR converts main's result to the exit
Int ITSELF (Part C's mapping) before it reaches the cell, so the root's cell
always carries plain Int and std needs exactly one non-void root entry — a
`__saw_exec_run_root` variant that attaches an Int-carrying cell and returns
its value after quiescence. Void mains keep the void path unchanged. This is
the compiler↔std executor contract (`__saw_exec_*`, versioned together
in-tree) — NOT the frozen `__saw_rt_*` seam; rt/ABI.md is not reopened.

**B4 — one exit funnel in codegen (obligation 1).** One place maps the
executor/driver result to the C `i32` for EVERY main shape, sync and driven
alike — replacing today's Void-only override at `codegen/core.py:2396-2400`.
Mapping (DF-220c ruling): Void → 0; Int → the value (POSIX truncation
`& 0xff` is the platform's, not ours — document it); Ok(Void) → 0; Ok(n) →
n; Err(e) → print the error, exit 1, rendering through the SAME path the
erased-error `try!` panic already uses (no new rendering machinery). The
funnel's docstring names its entry points: sync main epilogue, the
single-frame executor, the ambient executor's conversion.

## Part C — DF-220c: the `main` rule (RULED)

`main` may return exactly `Void`, `Int`, `Result<Void, E>`, or
`Result<Int, E>`; every other return type is a compile error naming the
four. E's only obligation is what the Err path needs: the erased-error
rendering `try!` already performs (so `Box<any Error>` and concrete `Error`
conformers both work; a non-Error E follows whatever `try!`'s rendering
demands — reuse, don't invent). The check lands in the typechecker where
main is looked up today (`typechecker/core.py:1680/2461` — currently
existence-only). Sync `main -> Result` goes through the same B4 funnel (it
is today's silent ABI-garbage case: struct-return `@main`, exit 138).

Docs per design 125: LANGUAGE_SPEC.md gains the `main` rule (it has none),
README and the saw-lang skill get the user-facing summary; saw-docs skill
governs the prose. Conformance rows: each legal shape's exit behavior
(folded into B1's rows), plus refusal rows for `-> String` and one other
illegal type asserting the four-type error text.

## Part D — honest gates (with, not after, B)

- `battery.sh run_irdet` (tools/battery.sh:103-106) parses irdet's
  structured output (`--jsonl` records, the same source
  `irdet_remote.check_here` already trusts) — never `$?`. After B lands the
  exit code ALSO works, but the structured read is the contract; a gate
  should not depend on the bug it gates being fixed.
- `tools/irdet_remote.py:59` — the `--plan` returncode guard becomes a
  structured/output check (it can never fire today).
- Makefile irdet targets (Makefile:72-77): same review, same pass.

## Units and sequencing

A is codegen-only; B/C/D share the transform + std + typechecker surface.
Dispatch as ONE implementer, order: B1 rows → A (with its lane, so the new
lane gates everything after) → B2 → B3 → C → B4 → D. Per-unit full suite;
terminal gate the full tracked battery — in which the irdet lane must
demonstrate BOTH directions: green on the landed tree, and (as a one-off
proof in the report, not a committed state) red when fed a deliberate
mismatch, now that its exit code and the battery's read are both real.

## Non-goals

No change to what irdet checks; no design-220 integration (separate
re-gate); no touching the six deferred 218 families; DF-218k/l/m
(suspending-method trio) are a separate family sweep + brief; the
`main() -> Result` Err exit code is 1, not the error's discriminant —
richer mappings are future work if ever asked for.
