# Design Brief 22 — `sync` effect system prototype (the flip, investigated early)

**Source:** `designs/18-async-await.md` Axis B′ (DECIDED: colorless calls,
checked `sync` effect). **Purpose: discover the gotchas while the language
is small** — the effect system is pure typechecker machinery, so it can be
built and stressed NOW against synthetic suspension sources, before any
executor exists. The deliverable is as much the REPORT (what was awkward,
what surprised) as the code.
**Prereq/sequencing:** land AFTER brief 21 (concurrency stage 1) — both
touch the typechecker.

## Synthetic suspension sources (no runtime behavior)

1. `__test_suspend()` — compiler-known intrinsic: typechecked as A
   SUSPENSION POINT; codegen = no-op (programs still run). Exists to give
   the effect system something to propagate.
2. `extern blocking func ...` — parse and record the `blocking` marker
   (real feature from paper 18: unbounded FFI). For this prototype it is
   simply a suspension source; the offload machinery is future work.

## The effect system

1. **Inference:** every function/method/closure gets a transitive
   `suspends` bit: true iff its body reaches a suspension source — a
   synthetic source above, a call to a suspending function, or a call
   through a NON-`sync` function-typed value (conservative). Whole-program
   fixpoint (SCC or iterate-to-fixpoint; mutual recursion must work).
   Generic functions: infer on the abstract body; where the answer
   depends on a function-typed parameter, see "known hard case" below.
2. **`sync` in function types:** `sync (Int) -> Int` (pick the concrete
   grammar; keyword before the signature is the working proposal). A
   closure literal or function reference assigned/passed to a sync
   function type is CHECKED suspension-free. Calls through sync-typed
   values do NOT mark the caller suspending.
3. **`sync func` declarations** (ISR/callback style): body checked
   suspension-free at definition.
4. **Implicit sync contexts:** every `deinit` body (paper 18: suspension
   in deinit is a compile error). Add the check.
5. **Diagnostics — a primary investigation target:** the error for a sync
   violation must carry the SUSPENSION PATH:
   `cannot suspend in sync context: lock closure calls `f` → `g` →
   `__test_suspend` (g suspends at line N)`. Path quality through
   monomorphized generics and closures is exactly where effect systems
   get miserable — make it good, and report what it took.

## Known hard case — surface it, don't solve it

**Effect polymorphism:** `func apply(f: (Int) -> Int, x: Int) -> Int`
takes a non-sync function type, so `apply` is conservatively suspending —
even when the caller passes a provably-sync closure. That makes every
higher-order utility unusable in sync contexts unless duplicated with a
`sync` signature. Swift solved the analogous problem with `rethrows`;
effect-generic signatures (`func apply(f: (Int) -[e]-> Int) -[e]-> Int`)
are the general answer. The prototype should: implement the conservative
rule, construct the failing case as a test (EXPECT: error, documenting
current behavior — NOT xfail, it is the designed conservative behavior),
and REPORT on which resolution fits Saw (effect-generic params vs
per-bound duplication vs monomorphization-time effect specialization —
the last is intriguing since Saw monomorphizes everything anyway:
effects could be re-inferred per instantiation. Analyze, recommend,
do not implement).

## Tests

Errors: sync context calling a directly-suspending fn; transitively (3
deep — assert the path appears in the message); via a non-sync
function-typed value; `deinit` calling `__test_suspend`; `extern
blocking` called from a `sync func`; the effect-polymorphism
conservative case.
Acceptances: pure-compute call chains usable in sync contexts with zero
annotations (inference does the work); sync-typed closure params
accepting sync closures; a suspending main-line program that also has
sync regions (`__test_suspend` outside, sync helper inside).

## Scope guard

NO executor, NO state machines, NO `await`/`async` keywords (none exist
in the flip), NO changes to how anything codegens except `__test_suspend`
as a no-op. Do not modify concurrency stage-1 machinery (Mutex etc.) —
if stage 1 has landed, adding the `sync` check to `Mutex.lock`'s closure
param is IN scope (it is the marquee consumer); if the wiring is
awkward, report rather than force.

## Report back

The gotcha list is the deliverable: inference fixpoint surprises;
grammar friction for `sync` types; diagnostic-path implementation cost;
the effect-polymorphism analysis + recommendation; how many existing
stdlib/example functions inferred suspending once `extern blocking` was
honored (should be zero today — verify); interface implications noted
for future separate compilation; deviations; non-allowlisted commands.
