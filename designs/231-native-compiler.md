# Design 231 — the native compiler: readiness ledger + the VM staging sketch

**Status: SKETCH + LEDGER (Aug 16, user-directed). Not a dispatchable
brief — the ruling session happens when the start line below is crossed.
This document is the standing answer to "when do we start, and with
what architecture."**

## The readiness ledger (what gates the start — xfails are the SMALLEST gate)

The ~25 cited xfails split three ways: (1) quick-fixable bugs with fix
shapes written (DF-225m, DF-224c, 218o/p/q, 221a, 229a, the diagnostics
warts) — mech/small-brief burn-down; (2) riders on queued briefs (218n
via the ICE brief, the 178d family via 228); (3) DESIGN DEBT — the six
deferred 218 census families, which keep the M1/M3 legacy encodings
alive. Bucket 3 needs a DECISION (fix vs document) before the transform
port, so nobody ports dead encodings; it does not need to hit zero.

**Gate 1 — surface stability.** Remaining known churn, finite and
listed: 226 (FuncPointer grammar + coercion), 230 (receive/send
signatures + close()), 228 (the Never rules), and the `&Self` trait
change (the big one — core trait signatures, every conformer). The
heavy semantic stabilization is ALREADY DONE (Slot migration, E2
deletion, live pool, export control — exactly the changes not to absorb
mid-rewrite).

**Gate 2 — the pipeline contract: 218 UNIT 1.5 IS RULED BUT NOT BUILT.**
Monomorphization is still codegen-side lazy discovery; the ruled
architecture (typecheck abstract → mono as a transform → instances
re-enter the checker with REAL errors → place/coro transforms on
concrete ASTs → codegen) is the self-hosting midpoint contract by name.
THE single biggest prerequisite; closes DF-217i/j/k with it.

**Gate 3 — reference hygiene.** DF-225o (load-exposed emission
nondeterminism) fixed before the rewrite: the differential lane is the
rewrite's safety net and its oracle needs the reference emitter
deterministic under all conditions.

**THE START LINES (queue terms, not calendar):**
- The PARSER PORT starts after 226 + 230 land (the two grammar/signature
  changes), in lockstep via a NEW two-parser diff lane (the lexdiff
  precedent; today's astdiff is a self-determinism oracle, not a
  two-parser diff — the lane must be built).
- The TYPECHECKER/TRANSFORM PORT (the real mass, ~10k+ lines of
  judgment) starts after the `&Self` change + UNIT 1.5 + the
  deferred-families decision.

## The VM staging sketch (ruled framing from the Aug-16 conversation)

**Feasibility is unusually high because the architecture pre-built the
boundary:** post-elaboration AST is plain imperative code (the coro
transform is source-level — a VM needs NO coroutine machinery; places
are lowered; mono will be a transform per unit 1.5), and the frozen
`__saw_rt_*` seam set IS the intrinsic list — the VM implements the
seams natively (~a dozen: alloc, write, tcp/fs, thread spawn, atomics)
and interprets everything above them INCLUDING std, exactly the hosted
runtime's own layering.

**The staging (VM as first backend and permanent reference, NEVER a
replacement):**
1. Front-end port (lexer done; parser; typechecker) — executable early
   via
2. THE VM BACKEND: tree-walk or simple bytecode over elaborated AST;
   self-hosting begins here WITHOUT LLVM bindings in Saw. MANDATORY
   unit 0: the differential lane (whole corpus, VM vs LLVM, outputs
   diffed — the suite becomes the semantics oracle; the corodiff/irdet
   harness culture applied to the rewrite's twin-divergence hazard).
3. The LLVM-C-FFI backend — the shipping backend; freestanding/SOS can
   ONLY ever be served here (a VM cannot target the mission's core).

**The VM's permanent roles after stage 3 (the rustc/Miri analogy):**
reference semantics + UB checking; const-eval/comptime when the
language wants it; the design-214 deterministic-simulation host (virtual
clock + virtual scheduler live naturally in an interpreter); the fast
dev loop (interpreted suite runs skip codegen+link).

**Performance note:** interpretation at 10-100x off native still
plausibly BEATS CPython running today's sawc for the
compiler-on-itself workload — self-hosting on the VM is not a
regression even transiently.
