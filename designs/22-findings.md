# Design 22 — `sync` effect prototype: findings

Investigation addendum to `designs/22-sync-effect-prototype.md`. The prototype
landed (parsing, whole-program suspendability inference, `sync`-context
checking with suspension-path diagnostics, `Mutex.lock` wired as the marquee
consumer). This file is the deliverable half of the brief: what was awkward,
what surprised, and the effect-polymorphism analysis + recommendation.

## 1. What landed

- `__test_suspend()` — a compiler-known intrinsic. Typechecked as a suspension
  SOURCE; codegen lowers it to a no-op (`codegen/calls.py`). Programs using it
  still compile and run.
- `extern blocking func` — parsed (`blocking` is a soft keyword valid only in
  extern blocks), recorded on `ExternFunction.is_blocking` / `FunctionSymbol.
  is_blocking`, and treated as a suspension source.
- `sync func` declarations and `sync (T) -> U` function types — `sync` is a
  hard keyword. `sync` precedes both the `func` in a declaration and the `(` in
  a function type.
- Whole-program transitive suspendability inference — iterate-to-fixpoint over
  a call graph built during type checking (`typechecker/effects.py`). SCC- and
  mutual-recursion-correct: flips are monotone, so the sweep terminates.
- `sync` contexts checked: `sync func`, every `deinit` body, and any closure
  whose target type is a `sync (...)` function type. Violations carry the full
  suspension PATH.
- `Mutex.lock`'s `body` parameter retyped `sync (&var T) -> Bool`
  (`std/mutex.saw`) — holding a lock across a suspension is now a compile error,
  and because `body` is `sync`, invoking it does not make `lock` itself
  suspend.

Diagnostic quality bar (met verbatim from the brief):

```
cannot suspend in a `sync` closure context: closure calls `f` → __test_suspend (`f` suspends at line 2)
cannot suspend in `sync func` declaration: `sync func handler` calls `f` → `g` → __test_suspend (`g` suspends at line 8)
```

## 2. Gotchas

### 2.1 Inference is trivial; the plumbing is the cost
The fixpoint itself is ~15 lines and never surprised. The real work was
*collecting the call graph*. The clean choice was to piggy-back on the
typechecker's existing name/type resolution — record an edge exactly where the
checker has already resolved a `FunctionCall`/`MethodCall` to a symbol — rather
than re-resolving in a standalone AST pass. That reuse is what makes method
dispatch, generics, and closure argument typing "just work" for the analysis.
Consequence: the analysis is a *phase*, not a *pass*. Edges are gathered during
body checking; the fixpoint + sync checks run once at the very end
(`finalize_effects`, called from `check()` and from the entry module's
`check_module`).

### 2.2 Node keying is subtle
Free functions are keyed by name (`("fn", name)`); duplicate free-function
names are already a hard error, so names are unique within a single-file
program. Methods are keyed by `id(Method)` (the AST node stored on the method's
`FunctionSymbol.ast_node` — the same object at declaration and call site).
Closures by `id(ClosureExpr)`. A mixed int/tuple-key dict is fine. The trap
avoided: non-generic free functions register `ast_node=None`
(`registration.py`), so keying free-function nodes by symbol identity would
have silently dropped every non-generic function from the graph. Name-keying
sidesteps it.

### 2.3 Closures need their own stack frame in the analysis
A closure body's suspendability must attach to the *closure*, not its enclosing
function — otherwise `apply({ __test_suspend() }, ...)` would wrongly taint the
caller through the wrong node, and a `sync` closure argument could never be
checked in isolation. A small explicit node stack (`_suspend_stack`, push on
entering function/method/closure bodies) solves this and mirrors how the
checker already tracks `current_function`/`current_method`.

### 2.4 Grammar friction: `sync` as a keyword
`sync` had to be reserved to parse `sync (Int) -> Int` unambiguously in type
position (a soft keyword there needs LPAREN lookahead against a hypothetical
type literally named `sync`). Reserving it is low-risk today (no lowercase
`sync` identifier exists anywhere in stdlib/examples/tests) but IS a
reservation — a wart worth noting before it appears in user code. `blocking`,
by contrast, only ever precedes `func` inside an `extern` block, so it stayed a
soft keyword with zero reservation cost. Recommendation: keep `sync` reserved;
keep `blocking` contextual.

### 2.5 Path reconstruction is cheap once the graph exists
The suspension-PATH diagnostic — the part the brief warned "is exactly where
effect systems get miserable" — was a ~20-line DFS over the same graph
(`_effect_path`): from the sync node, follow the first suspending edge until a
direct source, accumulating callee short-names. Because edges already carry the
call-site line and a display short-name, the message needs no extra
bookkeeping. Through monomorphized generics the path stays readable *because we
infer on the abstract body* (§4) — the chain names the generic function once,
not per instantiation.

### 2.6 Where suspension is reported vs. where it happens
The error is anchored at the `sync` context's declaration (the `sync func` /
`deinit` / closure), with the leaf `__test_suspend` line quoted inline
("suspends at line N"). That reads well for the sync-context-owner (they see
which of their obligations broke) but the caret points at the signature, not
the offending call. A future refinement could anchor at the first hop's call
site instead. Recorded, not changed.

## 3. Verification: zero existing functions inferred suspending

With `extern blocking` honored, the only suspension sources in the tree are the
new test files — no `__test_suspend` or `blocking func` exists in `builtin.saw`
or any `std/*.saw`. Every stdlib `deinit` body (Mutex, Vector, Map, …) is a
`sync` context and all pass, so the inference reports zero pre-existing
suspending functions. The full suite is green (289 passed / 7 xfailed; +10 new
tests, no xfail movement).

## 4. The known hard case: effect polymorphism

`func apply(f: (Int) -> Int, x: Int) -> Int { f(x) }` takes a non-`sync`
function type. The conservative rule (calls through a non-`sync` function value
mark the caller suspending) therefore makes `apply` unconditionally suspending
— even when the caller passes a provably-pure `{ $0 * 2 }`. So *no* higher-order
utility (map/filter/fold, retry wrappers, `Mutex.lock`-alikes) is usable from a
`sync` context unless hand-duplicated with a `sync` signature. This is the
designed behavior for the prototype (test `errors/sync_effect_polymorphism.saw`
is EXPECT: error, deliberately, not xfail).

Three resolutions were considered:

1. **Per-bound duplication** (`lock` + `lock_sync`, `map` + `map_sync`). Zero
   new type theory, but O(2^effects) API surface and it splits the ecosystem
   exactly the way Rust's sync/async split did — the outcome the flip exists to
   avoid. Reject as the general answer (fine as a one-off, which is how
   `Mutex.lock` gets its `sync` signature today).

2. **Effect-generic signatures** (`func apply(f: (Int) -[e]-> Int) -[e]-> Int`),
   the Koka/Swift-`rethrows` answer: `apply` is polymorphic in the effect of
   `f` and forwards it. General and principled, but it introduces effect
   variables into the surface type system — new syntax, inference, and a second
   axis of generic parameter. Heavy for a language whose whole premise is
   "mark the rare thing, infer the rest."

3. **Monomorphization-time effect re-inference** ⭐ **recommended.** Saw already
   monomorphizes every generic and every closure call site is statically known
   at the point a higher-order function is specialized. So the effect need not
   be a *type-system* variable at all — it can be **re-inferred per
   instantiation**, exactly like a `T: Copy` bound is re-checked per concrete
   `T`. When `apply` is instantiated with the concrete closure argument
   `{ $0 * 2 }`, re-run the suspend fixpoint on *that* instantiation: the
   indirect call now resolves to a known-pure closure, so this `apply` instance
   is non-suspending and usable in a `sync` context; an `apply` instance handed
   a suspending closure is suspending. No effect variables, no duplicated
   source, no new surface syntax — the polymorphism falls out of the
   monomorphizer that already exists.

   Why it fits Saw specifically: the flip's entire bet is "whole-program
   inference does the work; annotations are rare." Effect variables re-introduce
   annotations on every higher-order signature — the thing the flip removed.
   Per-instantiation re-inference keeps the signature bare and pushes the cost
   into the compiler, which is where the flip already put suspendability
   inference. The `sync`-context check then runs against the *instantiated*
   effect, so `sync`-passing a pure closure into `apply` and calling it Just
   Works.

   Cost / caveats to design out before adopting:
   - The suspend graph becomes **per-instantiation** for effect-polymorphic
     functions, not per-abstract-body. That means keying nodes by
     (function, type-args, closure-argument-identity) for those functions and
     running the fixpoint after monomorphization rather than during initial
     checking. The two-phase structure already built here (collect edges →
     fixpoint) accommodates that; the collection point moves later.
   - Recursion through an effect-polymorphic parameter needs the fixpoint to
     reach a conservative fallback (assume suspending) if an instantiation
     cycle can't be resolved — same monotone-flip safety as today.
   - Diagnostics must name the instantiation ("`apply` instantiated with the
     closure at line N suspends"), which is strictly more information than
     today, not less.
   - Separate compilation (below) is the real tension: re-inference wants the
     callee's body, which cross-module means the body or a summarized effect
     signature must be available. For a whole-program compiler (today) this is
     free.

## 5. Interface implications for separate compilation

Today's inference is whole-program by construction. Two structural facts matter
for the eventual module-interface story:

- In the single-file path (`check()`), builtins + std + user are one graph, so
  inference is genuinely whole-program and fully correct — this is the path all
  the required tests and `Mutex` usage take.
- In the multi-module path (`compile_with_modules`), user modules share one
  `TypeChecker` instance (one graph), but builtins/std are checked by a
  *separate* `TypeChecker`. Cross-module edges into std therefore resolve to a
  missing node and are treated as non-suspending leaves. That is safe today
  (no std function suspends) but is exactly the seam where a real module
  interface must eventually **record each public function's inferred
  suspendability** (and, per §4, its effect-polymorphism shape). The brief's
  "auto-written into module interfaces when separate compilation lands" is the
  right framing: the `suspends` bit is a computed part of a function's exported
  signature. Until then, cross-module suspendability is conservatively
  non-suspending for imported symbols, which the analysis already does.

Recommendation for the interface format when it lands: export, per public
function, (a) a `suspends` bit for non-effect-polymorphic functions, and (b)
for functions with function-typed parameters, an effect-shape descriptor ("this
result suspends iff parameter `f` does") so re-inference (§4.3) can run without
the callee's body.

## 6. Deviations and gaps (scoped, documented)

- Edge recording covers free-function calls, the main method-dispatch path
  (incl. `Mutex.lock`), calls through function-typed local/param values, and
  the two suspension sources. NOT yet wired: module-qualified function calls
  (`mod.fn()`), static/`init` method calls, and calls through a function-typed
  *struct field*. These are conservative-unsound only in the narrow sense that
  a suspending callee reached exclusively through those forms would be missed;
  none are exercised by the required cases, and adding them is mechanical
  (same `_effect_call_*` helpers). Flagged for follow-up.
- `sync` methods (`sync func` inside an `extension`) parse only at top level
  today; the node/checking machinery already handles a `Method.is_sync` flag,
  so wiring the parser is a small follow-up (ISR/callback-as-method).
- Type compatibility ignores the `sync` flag: a closure LITERAL passed to a
  `sync` param is accepted structurally and then *effect-checked*. A non-literal
  function VALUE passed to a `sync` param is not yet rejected at the boundary
  (it would need a "this value's type must be `sync`" assignability rule). Not
  required by the brief; noted.

## 7. Bottom line

The flip is cheap to prototype and the diagnostics are good — the feared
"miserable path reconstruction" was easy once the graph was collected by
reusing the checker's resolution. The one genuinely hard thing, effect
polymorphism, has an unusually clean answer *for Saw specifically*: because Saw
monomorphizes everything, effects can be re-inferred per instantiation instead
of being lifted into the surface type system. That keeps signatures bare, which
is the whole point of the flip. Recommend adopting per-instantiation effect
re-inference (§4.3) when higher-order utilities need to be `sync`-usable, and
treating each public function's `suspends` bit as computed signature data when
separate compilation lands (§5).
