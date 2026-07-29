# Design 43 — LLVM coroutine viability probe: findings

Investigation-only. Feeds the async **stage-2** scheduling decision (paper
`designs/18-async-await.md`, Axis A1: stackless coroutines / state-machine
transform). Paper 18 flags: *"Probe required before the brief: whether llvmlite
0.48 exposes the coro intrinsics + passes usably; if not, the transform is
hand-rolled at AST level."* This document answers that probe.

No compiler or stdlib source changed. Evidence lives in `.build/scratch/`
(probe scripts + emitted IR); the full suite is green (**448 passed**) confirming
no product code moved.

## Environment (one surprise up front)

- llvmlite **0.48.0**, bundling **LLVM 22.1.0** — *not* the "LLVM 20-era" the
  brief assumed. This matters: intrinsic signatures are version-sensitive (see
  §Q1), so any brief must pin behaviour to the LLVM the shipped llvmlite carries,
  not to docs for an older release.
- Host linker: Apple clang 21 (the project's existing `clang obj -o exe` path).
- Project codegen path probed against verbatim: `parse_assembly` → `verify` →
  `create_pipeline_tuning_options(speed_level=1)` → `create_pass_builder` →
  `getModulePassManager().run(mod, pb)` → `target_machine.emit_object`
  (`sawc/codegen/core.py:1608-1669`).

---

## Q1 — Can llvmlite declare/call the `llvm.coro.*` intrinsics + `presplitcoroutine`?

**VERDICT: YES, with two small, well-understood shims on the *builder* path.**

Two sub-questions: (a) does the bundled LLVM accept coroutine IR, and (b) can
`llvmlite.ir` (what `codegen.py` builds with) *emit* it.

### (a) Raw IR acceptance — clean

`binding.parse_assembly` + `verify()` accept a full presplit coroutine
(`coro.id/size/begin/suspend/free/end`, `presplitcoroutine` fn attribute) and
the caller-side subfn intrinsics (`coro.resume/destroy/done`). The attribute
survives the parser round-trip. Evidence:
`probe_coro_1_lowering.py` → `PARSE+VERIFY: OK` and
`probe_coro_sig_one.py` (per-intrinsic isolation).

**Signature gotcha (LLVM 22, opaque pointers):**
`llvm.coro.end` is **`void (ptr, i1, token)`** — *not* `i1 (...)`. The `i1`
form (correct in older LLVM) fails verify: `Intrinsic has incorrect return
type!`. Confirmed-good signatures for LLVM 22:

```
declare token @llvm.coro.id(i32, ptr, ptr, ptr)
declare i64   @llvm.coro.size.i64()
declare ptr   @llvm.coro.begin(token, ptr)
declare i8    @llvm.coro.suspend(token, i1)
declare ptr   @llvm.coro.free(token, ptr)
declare void  @llvm.coro.end(ptr, i1, token)     ; void, not i1
declare void  @llvm.coro.resume(ptr)
declare void  @llvm.coro.destroy(ptr)
declare i1    @llvm.coro.done(ptr)
```

**Sharp edge worth a brief-level warning:** a *wrong-arity* or *wrong-return*
coro intrinsic declaration does not raise a Python exception — it **hard-aborts
the process** (`Assertion failed: ... doRAUW ... Value.cpp` / SIGABRT) inside
LLVM's intrinsic auto-upgrader (`run_sig_cases.py`, cases `end_i1_ptr_i1` and
`end_i1_ptr_i1_bundle`, `rc=-6`). Codegen must therefore emit *exactly* the
right signatures; a typo is a crash, not a diagnostic.

### (b) Builder emission — two shims, then it just works

`llvmlite.ir` has two gaps against coroutines, both demonstrated in
`probe_coro_4_builder.py`:

1. **`presplitcoroutine` is not in the attribute allowlist** —
   `func.attributes.add("presplitcoroutine")` raises
   `ValueError: unknown attr 'presplitcoroutine'` (the `_known` frozenset in
   `llvmlite/ir/values.py:FunctionAttributes` omits it).
2. **There is no `token` type** — `hasattr(ir, "TokenType") == False`. The coro
   intrinsics traffic in `token`, and the builder cannot express it.

Both are ~10 lines to fix, no LLVM patch, no fork:

```python
# (1) widen the allowlist
ir.values.FunctionAttributes._known = frozenset(
    ir.values.FunctionAttributes._known | {"presplitcoroutine"})

# (2) a minimal token type + a 'token none' operand
class TokenType(ir.Type):
    def _to_string(self): return "token"
    def __eq__(self, o):  return isinstance(o, TokenType)
    def __hash__(self):   return hash("token")
def token_none():   # renders as the operand `token none`
    return ir.values.FormattedConstant(TokenType(), "none")
```

With those, a coroutine built entirely through `ir.IRBuilder`
(`define ptr @saw_start(i32 %n) presplitcoroutine`, phi/switch/suspend CFG)
**parses, verifies, and splits** through the O1 pipeline. So `codegen.py` can
emit coroutine IR directly — no text-splicing hack needed.

---

## Q2 — Do the coroutine LOWERING passes (CoroSplit/CoroCleanup) run?

**VERDICT: YES via the default O-level pipeline — and *only* that way. There is
no isolated-coro-pass path in the 0.48 wrapper.**

`probe_coro_1_lowering.py` runs the coroutine through
`getModulePassManager()` (= LLVM `buildPerModuleDefaultPipeline`) at every speed
level:

```
speed_level=0: split=True  leftover_presplit_intrinsics=none  resume_clone_present=True
speed_level=1: split=True  leftover_presplit_intrinsics=none  resume_clone_present=True
speed_level=2: split=True  leftover_presplit_intrinsics=none  resume_clone_present=True
speed_level=3: split=True  leftover_presplit_intrinsics=none  resume_clone_present=True
```

The default pipelines carry `CoroSplit`/`CoroCleanup` (gated at runtime on the
`presplitcoroutine` attribute), at O0 through O3. The **project's exact
pipeline (`speed_level=1`)** splits the function into a ramp + `.resume` +
`.destroy` clones — no leftover presplit intrinsics.

**Two hard limits of the llvmlite 0.48 new-PM wrapper (both confirmed):**

- **No string-pipeline API.** `dir(binding)` exposes only
  `PipelineTuningOptions` / `create_pipeline_tuning_options` — there is **no
  `parse_pass_pipeline`**, so you cannot run a `"coro-split,coro-cleanup"`
  pipeline string.
- **No coro-named `add_*` pass** on `ModulePassManager`/`FunctionPassManager`
  (the hand-pick list has ~80 passes; zero contain "coro").

Consequently the *only* way to reach CoroSplit is to run a whole default
O-pipeline.

**Load-bearing consequence for `sawc -O0`:** the project's `-O0`
(`optimize=False`) **skips the pipeline entirely** (`core.py:1664`). An object
emitted from an *unlowered* coroutine hard-aborts the backend:
`probe_coro_5_o0.py` → `LLVM ERROR: Cannot select: intrinsic %llvm.coro.begin`.
So on the LLVM path, **coroutine programs cannot be compiled at `-O0`** unless
`-O0` is changed to still run at least the default pipeline (or a future
llvmlite exposes CoroSplit standalone). This coupling — lowering welded to
optimization — is a real constraint the brief must design around.

---

## Q3 — End-to-end native binary: suspend → return → resume → complete?

**VERDICT: YES. Fully working native executable through the project's own
emit-object + clang-link path.**

`probe_coro_3_native.py` parses the canonical coroutine, runs the project O1
pipeline, `target_machine.emit_object(...)` to `.o`, and `clang`-links it with a
tiny C driver (`coro_driver.c`) that calls the IR-exposed
`saw_start/saw_resume/saw_done/saw_destroy` wrappers. Program output:

```
driver: starting coroutine
1
driver: resuming
2
driver: resuming
3
driver: resuming
driver: coroutine done after 3 resume(s); destroying frame
driver: done
```
exit code 0.

That exercises **frame allocation** (heap `malloc`), **suspension** (control
returns to the C driver after each value), **resumption** (driver re-enters and
the coroutine restores its live `i` counter), and **completion** (final suspend
→ `coro.done` true → `coro.destroy` runs cleanup/free). This is the whole
stage-2 mechanism, proven on the shipped toolchain.

**Frame size (measured):** CoroSplit constant-folds `@llvm.coro.size` — the ramp
allocates a **compile-time-constant 24-byte frame** for this trivial coroutine
(`coro_split_O1.ll:18` → `malloc(i64 24)`). Layout LLVM chose:

```
offset 0  : ptr   resume-fn        (store @saw_start.resume)
offset 8  : ptr   destroy-fn       (store @saw_start.destroy)
offset 16 : i32   spilled `n`
offset 20 : i2    suspend-index    (LLVM packed the state index to 2 bits)
```

`saw_resume` is just `load fn-ptr; tailcall`; `saw_done` is
`load resume-ptr; icmp eq null`. LLVM produces exactly the state machine we'd
hand-write, and packs it tighter (a 2-bit index) than a naive transform would.

---

## Q4 — Where it fails, and the source-level fallback

No step *failed* outright — the LLVM path is viable end-to-end. What surfaced is
a set of **structural frictions**, not blockers:

1. Lowering is welded to the optimization pipeline (`-O0` impossible; §Q2).
2. No isolated CoroSplit → no way to lower without also running the full O1
   pipeline's other transforms (§Q2).
3. Intrinsic signatures are LLVM-version-fragile and mis-declaration *aborts the
   process* rather than erroring (§Q1).
4. **Frame size is computed by LLVM's CoroSplit, invisible to the Saw
   front-end** until after codegen (§Q5) — the sharpest friction, because it
   collides with the freestanding static-allocation requirement.

### The fallback: a source-level state-machine transform

The alternative paper 18 names: split suspending functions in the Saw
typechecker/codegen into a resumable state struct + a `resume(state) -> Poll`
dispatch function, front-end-owned. What it would require, given what already
exists:

- **Suspension points: already known.** The `sync`-effect machinery
  (`typechecker/effects.py`, per `designs/22-findings.md`) already runs a
  whole-program fixpoint that identifies every suspending function and every
  suspension *edge*. The transform's "where do I split" question is answered by
  machinery that shipped. This is the single biggest reason the source-level
  path is *less* daunting for Saw than for a language starting cold.
- **New work the effect graph does *not* give you:**
  - **Live-across-suspend analysis** — for each suspension point, the set of
    locals live afterward, to become state-struct fields. This is a
    dataflow pass the compiler does not have yet.
  - **CFG → resumable state machine rewrite** over the typed AST/IR: a
    `switch(state)` re-entry, storing/reloading live locals, handling
    suspension inside loops, `match`, and nested expressions.
  - **`Deinit` interaction** — deterministic LIFO destruction must run for
    live locals when a coroutine is cancelled/dropped mid-suspension (LLVM's
    `.destroy` clone does this automatically; a hand-rolled transform must
    emit it). This is the fiddliest correctness surface.
  - **Frame layout** — the front-end computes it, so **frame size is known at
    compile time in the front-end** (the Q5 payoff).
- **Cost:** genuinely large — paper 18 calls A1 "the biggest compiler work item
  to date," and the live-set + Deinit-across-suspend pieces are where that cost
  concentrates. But it is *incremental* on top of the effect graph, not
  greenfield.

**Cost/benefit vs the LLVM path:**

| | LLVM coro intrinsics | Source-level transform |
|---|---|---|
| Works today | ✅ proven (Q3) | ✗ must be built |
| Front-end code | ~10-line shim + IR emission | large (live sets, CFG rewrite, Deinit) |
| Frame size to front-end | ✗ post-split only (Q5) | ✅ compile-time in front-end |
| Static `.bss` frames | awkward (Q5) | natural |
| `-O0` support | ✗ (Q2) | ✅ (front-end lowered) |
| LLVM-version stability | fragile (Q1) | stable (plain IR) |
| Frame packing quality | excellent (2-bit index) | as good as we make it |
| Send-check on frame (stage 3) | inspect LLVM frame (opaque) | front-end owns struct → structural check trivial |

---

## Q5 — Freestanding / static-frame allocation

**VERDICT: frame size IS a compile-time constant — but on the LLVM path it is
LLVM's constant, materialized only *after* CoroSplit, i.e. it is not available
to the Saw front-end at the point Saw source would need it to declare static
`.bss` task arrays.**

Concretely: the 24-byte size (Q3) is a folded constant in the *emitted object*,
but the Saw front-end emitting `@llvm.coro.size.i64()` sees an opaque call, not
`24`, until LLVM runs. The Embassy model paper 18 wants — *"tasks are
compile-time-sized frames in `.bss`, allocation-free"* — needs the size **at the
front-end** to lay out `static [N x TaskFrame]`. The LLVM path can do static
frames (pass a static buffer to `coro.begin` instead of `malloc`, and
`CoroElide` already promotes non-escaping frames to caller `alloca` — the ramp
in Q3 would put the frame on the stack if the caller didn't let it escape), but
sizing a *named static array in Saw source* requires either:

- a **two-pass compile** (compile once, read the split frame size back from the
  object/IR, then materialize `.bss` buffers), or
- ceding frame placement entirely to LLVM (stack via elision / linker-provided
  buffers), giving up the explicit `static` task-table shape.

The **source-level transform sidesteps this cleanly**: the front-end computes
the frame struct, so its size is a compile-time constant *in the compiler*, and
`static` task frames in `.bss` fall out directly — exactly the Embassy shape.
**This is the strongest single argument for the source-level path, and it is
specifically the freestanding requirement (a first-class Saw target per
`designs/18` and MEMORY) that drives it.**

---

## Recommendation for stage 2

**Primary: build the stage-2 executor on the LLVM coro-intrinsic path *first*,
as the hosted, dynamic-frame prototype — but architect the codegen seam so the
front-end effect graph drives a swappable lowering backend, because the
freestanding profile will most likely force a source-level transform later.**

Reasoning, weighted by the evidence:

1. **Stage 2 is explicitly hosted + single-threaded** (paper 18: "async/await on
   a single-threaded executor … frames never cross threads"), and the
   freestanding profile is deferred to *its own option paper before stage-2
   work*. For hosted, dynamic `malloc`'d frames, the LLVM path's one real
   liability (front-end-invisible frame size, Q5) **does not bite** — nothing
   needs `.bss` sizing. The LLVM path is proven (Q3), needs only a ~10-line shim
   (Q1), and produces better-packed frames than we'd hand-write. It de-risks the
   *executor/scheduler/structured-concurrency* work — the genuinely novel part —
   without also paying for a CFG-rewrite transform up front.
2. **Use the LLVM path as a correctness oracle** even if the source-level
   transform ultimately wins: it gives a working reference (frame layout, resume
   dispatch, Deinit-on-destroy semantics) to diff a hand-rolled transform
   against.
3. **The source-level transform is the likely destination for freestanding**
   (Q5), and Saw is unusually well-positioned for it because the effect graph
   already computes the split points (Q4). The decision of *when* to switch is a
   function of when the freestanding static-allocation profile is scheduled — it
   is not a stage-2-hosted blocker.
4. **Do not let coro-intrinsic assumptions leak into the front-end.** The
   stage-2 brief must keep suspension-point identification and live-set analysis
   in front-end terms, with the LLVM intrinsics as one *backend* of a lowering
   interface. That keeps the source-level transform a backend swap, not a
   rewrite.

**Honest uncertainty:** if the freestanding static-frame profile lands *close
to* stage 2 (MEMORY says kernels/embedded are the *initial* targets, which
pushes it earlier than paper 18's sequencing implies), the calculus flips toward
doing the source-level transform first and skipping the LLVM detour — because
maintaining two lowering backends has a cost, and the LLVM path's frame-size
opacity is fatal to the headline freestanding requirement. This is the one
scheduling question the user should resolve before committing: **how soon must
`.bss` static task frames work?** If "stage 2 or right after," go source-level
first; if "later, hosted first," the LLVM path is the faster, proven start.

## What the stage-2 implementation brief should contain

1. **A lowering-backend interface** in codegen: input = a suspending function +
   its suspension points (from the effect graph) + live-across-suspend sets;
   output = a ramp/resume/destroy triple. Two implementations planned
   (LLVM-intrinsic first, source-level later); front-end stays backend-agnostic.
2. **The coro-intrinsic shim** (Q1): widen `FunctionAttributes._known`, add a
   `TokenType`, `token none` via `FormattedConstant`; a signature table pinned to
   the bundled LLVM version, with a startup assertion that the LLVM version
   matches (mis-declared intrinsics *abort*, Q1) — treat an LLVM-version bump as
   a coro-signature review item.
3. **Pipeline coupling fix** (Q2): coroutine-bearing modules must run the default
   pipeline even under `-O0` (or document `-O0` as unsupported for async
   programs). Note the absence of an isolated CoroSplit in llvmlite 0.48 — a
   minimal `add_coro_split_pass` binding is a possible upstream/patch item if
   `-O0` async becomes important.
4. **Live-across-suspend analysis** — the new dataflow pass, shared by both
   backends (the source-level backend consumes it to build the state struct; a
   validation harness can diff its live sets against LLVM's chosen frame fields).
5. **Deinit-across-suspend semantics** — specify LIFO destruction of live locals
   on cancel/drop mid-suspension; on the LLVM path this is the `.destroy` clone,
   on the source path it is explicit emission. This is the highest-risk
   correctness surface; write tests against the LLVM oracle.
6. **Frame-size story for freestanding** (Q5): decide two-pass vs
   LLVM-elision vs "source-level transform owns it" for `.bss` static task
   tables; this decision selects the destination backend.
7. **Executor/reactor scope** (from paper 18): single-threaded run queue + waker,
   poller-only reactor over unbounded sources, structured `spawn`/join,
   explicit-only cancellation — orthogonal to the coroutine lowering and the bulk
   of stage-2 *product* value; the lowering choice above should not gate it.

## Probe artifacts (`.build/scratch/`)

- `coro_canonical.ll` — canonical presplit coroutine (LLVM 22 signatures).
- `probe_coro_sig_one.py` / `run_sig_cases.py` — per-intrinsic signature probe
  (found `coro.end` is `void`; found mis-declaration aborts).
- `probe_coro_1_lowering.py` → `coro_split_O1.ll` — parse/verify + split at all
  O-levels; no string-pipeline / coro `add_*` API.
- `probe_coro_3_native.py` + `coro_driver.c` → `coro_native` — end-to-end native
  binary; frame-size measurement.
- `probe_coro_4_builder.py` → `coro_builder_emitted.ll` — `ir` builder blockers
  + shim; builder-emitted coroutine splits.
- `probe_coro_5_o0.py` — unlowered coroutine fails object emission (the `-O0`
  coupling).
