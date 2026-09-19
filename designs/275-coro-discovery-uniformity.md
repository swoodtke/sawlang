# Design 275 — Coroutine transform discovery uniformity

**Status: RULED Sep 18 2026** (user, all four units as the lead recommended;
tracker epic SL-318). The Sep-18 ruling also settles sequencing: SL-215 and
SL-317 are units of THIS epic, not point fixes ahead of it, and the
sawtracker build waits for the finished foundation — "doing a point fix vs
the correct fix is a waste of time".

## 0. Why this is an epic and not another funnel

Every coroutine-transform finding of the week of Sep 14 was a DISCOVERY
seam, none was a lowering bug:

| finding | seam | the fix that was made |
|---|---|---|
| SL-280 | six sites keyed a callee's frame independently (name vs mangled symbol) | `callee_frame_key` funnel, 16 named entries |
| SL-274 (r1 review) | two MORE keying sites the funnel had not reached | routed |
| SL-306 | classifier, closure walk and generic promotion disagreed on WHICH suspension question to ask (conservative closure-call bit vs real) | `suspends_ignoring_closure_calls` funnel |
| SL-306 (r1 review) | a fourth reader of the broad bit the sweep missed | routed |
| SL-304 | Blade's resolver recursion compiled only because its edge was silently declined | de-recursed Blade |
| SL-287, SL-316 | a callee/closure the walk declines is silently lowered as a plain call — the park blocks the executor thread | open |
| SL-215, SL-317 | the inline `try…catch` and the collection `for` cannot be split; refused (or, pre-280, silently declined) | open |
| K33–K37 (design 223) | enum / generic-struct / generic-method / conformance / existential embeds keyed three different ways | XFAIL |

Each fix routed the found site through a funnel and named its entries
(obligation 1), and each following unit found a sibling the enumeration
missed — twice in one day by review, not by gate. That is the signature
of a problem the ownership epic (SL-209, designs 267/269/270/273) already
diagnosed one module over: a DECISION re-derived at every consumer,
policed by reading. The remedy there was a recorded decision with a gate
(the producer taxonomy lane). The same remedy applies here.

Census, Sep 18 (`sawc/coro_transform.py`): 12,224 lines; `_FrameBuilder`
has 212 methods; `transform_program` is 1,032 lines with nine nested
closures; ~20 distinct predicates answer some form of "does this suspend /
what key names its frame / can I build it"; SEVEN split shapes (`if`,
`if let`, `guard let`, `while`, RANGE `for`, `match`, BLOCK `try…catch`);
21 scattered refusal messages; 17 governing briefs (44 → 224). The seven
split routines and the state-machine lowering have been stable for weeks
and are NOT in scope.

## 1. The four units (ruled)

### U1 — ONE DISCOVERY LEDGER (structural; goes first)

One pass, run once per program before any body is lowered, computes the
CLOSED frame table:

    FrameDecision(key, decl, kind ∈ {free, method, static, mono-instance},
                  suspends ∈ {really, closure-only, no},
                  buildable ∈ {yes, no(reason)},
                  home_module, splice_origin?)

keyed by `callee_frame_key` / `_method_frame_key`, populated from the
effect graph's three-valued answer (U4), the body tables (entry +
imported), the generic instantiation registry, and the method tables.
Every consumer READS it and derives nothing: `_classify_call`,
`_classify_method_call`, `_suspending_method_target`, `_is_suspending_expr`,
`_spans_suspension`, `_reject_buried_suspend_call`, `_default_expr_suspends`,
`_module_free_call_suspends`, the closure-walk edge-follow,
`_promote_nested_generic_calls` / `_promote_nested_generic_methods`,
`_structurally_suspends`, `_scan_method_callees`, `_rewrite_drive_sites`,
`_callee_fb`, the consumption sweep. `callee_frame_key` and
`suspends_ignoring_closure_calls` survive as the ledger's own composers.

THE GATE: a battery lane (`corodiscovery`, modelled on
`tools/test_producer_taxonomy.py` / `test_ast_graft.py`) that FAILS when
any site in `coro_transform.py` outside the ledger builder reads
`.suspends`, `.mangled_symbol`, `.resolved_symbol`, `.module_free_call`,
`.name` of a callee node, or the typechecker's `_suspending_methods_set` /
`_really_suspending_methods_set` — the raw inputs the ledger owns. That is
what turns "a missed sibling" from likely into impossible.

CONSTRUCTION AND FREEZE CONTRACT (codex review point 2). "One pass" means
ONE AUTHORITATIVE ANALYSIS, not one traversal: discovery runs a WORKLIST
until it stabilizes, because an imported body or a generic instance can
reveal further callees (a monomorphized clone of an imported generic is
keyed only once its instantiation is known). Discovery FINISHES before any
body is lowered, and the ledger is then FROZEN — a write after the freeze
is an invariant failure. A ledger MISS at a consumer is likewise an
invariant failure (an ICE breadcrumb naming the key), never permission to
emit a plain call — the silent decline this epic exists to end. Callee
FACTS and call-site DECISIONS are separate tables: `FrameDecision` is the
callee's (key, suspends set, buildable), and a `SiteDecision` (site, callee
key, context ∈ {driven root, embedded, spawned, closure body, sync body,
Thread body}, outcome) is what a consumer reads — the same callee can be
EMBED as a direct call and REFUSE inside a closure, and that difference
lives in the site table, not in two readings of the callee row.

VALIDATION (codex review point 5 — the first draft's claim was wrong):
`irdet` and `reemit` check REPEATABILITY of one compiler; they cannot prove
equivalence with the compiler before U1. Behaviour preservation is proven
by an explicit OLD-versus-NEW comparison: (a) a `--emit-frame-ledger` dump
(the decision table in deterministic order) is generated by a pre-U1
compiler at a pinned commit and by the branch, over the whole corpus +
Blade + the read-only sawtracker sources, and diffed — every difference
is a finding, either a pre-U1 silent decline the ledger now records
(expected, listed) or a regression; (b) the optimized-IR artifacts of a
main-checkout `test_runner` run are byte-compared against the branch's
(the design-220 manifest makes both sides available); (c) the suite, the
SL-280 rows, SL-306's matrix and the K rows are identical in outcome. The
adversarial cases from the SL-274 and SL-306 reviews (two-module
same-name, flat-vs-nested, generic-via-helper, closure-caller) become
PERMANENT gates — examples with EXPECT directives, not lead probes.

### U2 — TOTALITY: no silent decline, ever

A SHAPE TABLE (extending design 224's expression-position matrix to every
STATEMENT shape) says, for each shape a suspension can sit in: SPLIT (which
`_split_*`), HOIST (design 120's ANF), or REFUSE (one rejector, one
message, anchored at the shape's introducer). The transform consults the
table; there is no fourth outcome. In particular:

- a callee in the ledger with `buildable = no(reason)` reached from a
  driven closure is a COMPILE ERROR naming the reason and the callee
  (SL-287 closes; the message names the recursive function for a cycle,
  the anchor note SL-280's landing asked for);
- a closure body that really suspends is refused at the closure whether it
  lives in the entry module or an imported one (SL-316 closes);
- K33–K37's five embed shapes each get a ledger row (EMBED with its key, or
  REFUSE with its reason) so the XFAILs flip or become documented refusals
  by ruling, never by silence.

TOTALITY IS CHECKED AFTER LOWERING TOO (codex review point 3). The
source-level gate lane (U1's `corodiscovery`) bans the raw reads, which
makes a bypass unlikely; it cannot prove every suspension was HANDLED.
Two further checks make the promise mechanical: (a) every reachable
suspension SITE (a node whose cause set is non-empty, at each of its
call sites) has a recorded `SiteDecision` — a site without one fails the
compile as an invariant, and a NEW AST shape fails that coverage check
until the shape table classifies it; (b) a post-lowering walk over every
generated resume body asserts that no `frame_boundary` call survives as a
plain call — the same question `closure_calls_permitted` asks today for
synthesized frame methods, made total and run for every frame. (b) is the
runtime-facing half: a suspension that slipped every static check still
cannot reach the executor as a blocking call.

Obligation 3 first: the conformance rows for the guarantee "a suspending
call embeds or errors; it never silently blocks" (designs 96/101/104) are
rewritten as the shape table's rows, one per shape × {entry, imported,
spawned}. Obligation 2: programs that compile today ONLY because an edge
was declined stop compiling — Blade did, sawtracker did; the sweep is
`corodiff` + the bootstrap lane + a read-only sawtracker build, and every
newly-refused site is a finding to record, never a tolerance.

### U3 — COVERAGE: the two shapes the table has no SPLIT for

- **SL-215** — the INLINE `try EXPR catch { … }` (a `TryExpr` with a
  `catch_block`) routes through design 196's `TryCatchExpr` split, or
  normalizes to the equivalent `match` before the split walk. Cover the
  error binding, `try`/`try!`/`try?`, the `route_path` clause, DF-196b's
  multi-error refusal; the XFAIL pin `coro_suspending_call_in_inline_catch.saw`
  flips XPASS.
- **SL-317** — the COLLECTION `for` (`for x in v.iter()`): the iterator
  value becomes frame state across a suspension and the loop head
  re-enters through `next()`; ONE split funnel serves the range and the
  iterator `for`. Design questions the brief settles, not the agent: which
  iterator types qualify (`Iterator<T>` conformers), what `break`-with-value
  does across the split (SL-222's discarded-body rule stays), and the
  op-budget instrumentation (which currently SKIPS collection loops at
  `:494`) now charges them. Matrix: {Vector.iter, Map keys/values, Set, a
  user Iterator} × {suspension in the body, in the head} × {driven root,
  spawned, nested in while/for}.
- **SL-321 — INSIDE this unit (user ruling, Sep 18).** The std Vector
  iterator IS a borrow of the vector that nothing tracks: `iter(&self)`
  returns an owned `VectorIterator` holding the raw buffer pointer, the
  `&self` borrow ends at the return, and a `for x in v.iter()` body may
  `v.push` — the iterator then reads FREED memory in safe sync code
  (`seen = 1025` for a sum of 10; SL-321 has the repro and the sweep: the
  class is Vector's two iterators, Data's holds an owned copy-on-write
  source and String's an immutable one). Ruled: the iterator becomes a
  TRACKED borrow of the collection for the loop's window, so a body
  mutation is the clean exclusivity error `v.push` already gets inside a
  `with_ref` window (designs 141/146), and that window SPANS a suspension
  under design 88's driven-in-place rule (held references are sound by
  task confinement; spawned frames keep stripping them) extended to the
  lent place. The alternative — refuse a borrowed-place iterator across a
  split in v1 — was withdrawn: once the iterator is a tracked borrow it
  would have refused the very loop this unit exists to compile
  (sawtracker `store.saw:285`). Matrix cells added: mutation of the
  iterated collection {in the sync body, across the suspension, via
  `let it = v.iter()` held across a push} × {Vector.iter, enumerated};
  obligation 3 row: "no use-after-free in safe code".
  BORROW-LIFETIME CONTRACT, owed by the U3 brief BEFORE dispatch (codex
  review point 4 — "frame-owned" alone does not settle address
  stability): (i) the collection borrow BEGINS at the evaluation of the
  `for` head and ENDS at loop exit by every route — normal exhaustion,
  `break`, `return`, an error propagated by `try` out of the body, task
  cancellation resuming into the frame's `__release`, and frame
  destruction without resumption — each route named and tested; (ii) the
  borrow is a REFERENCE stored in the frame (design 88's mechanism), so
  the referent's ADDRESS must be stable for the window: a collection
  owned by the frame itself is stable only if the frame is never moved
  after the window opens — design 44 embeds callee frames BY VALUE in the
  caller's, and a `Task.spawn`/group spawn MOVES a frame into the
  scheduler, so the contract states at which points a frame may still
  move and forbids a window across them (or pins the frame); (iii) a
  collection reached through a `&var` PARAMETER or an enclosing frame's
  field is external storage the task does not own — task confinement
  (D6) is the argument that no other task mutates it, and the Law of
  Exclusivity inside this task is what the window enforces; the brief
  distinguishes the two cases in its matrix rather than treating
  "frame-owned" as one thing.

### U4 — ONE set of suspension CAUSES at the effect source (amended Sep 18)

`typechecker/effects.py` computes ONCE per node the SET of causes a
suspension reaches it by — `cooperative` (a `REAL_SUSPEND_LABELS`
primitive: `yield_now`/`sleep`/io park/channel park, or a seeded std leaf
that reaches one), `blocking` (an `extern blocking` call, design 103),
`test_suspend` (the test-only `__saw_suspend`, design 44's synthetic state
boundary), `closure_call` (the conservative "a call through a non-`sync`
function value MIGHT suspend") — propagated over the call graph as a set
union to a fixpoint, SCC-safe, in one analysis. Every existing predicate
becomes a DERIVED READ of that set and is deleted as a walker: today's
FOUR walkers (`suspends`, design 206's `really_suspending`, design 242's
`suspends_ignoring_blocking`, SL-306's `suspends_ignoring_closure_calls`)
each exist because a consumer needs a different subset, and a three-valued
answer (the brief's first draft) would have re-created them at the
consumers — codex's review point 1. The context decisions are NAMED
derivations beside the set, each with its consumers in its docstring:

| decision | reads | consumers |
|---|---|---|
| `might_suspend` | any cause | the `sync` checker (a `sync` body that maps a vector with an unknown closure is still not provably sync) |
| `wraps_main` | cooperative ∪ blocking | design 45's entry-executor gate — NOT `test_suspend`, which must never wrap `main` |
| `refused_in_thread_body` | cooperative ∪ test_suspend ∪ closure_call | design 242 ruling 9: a `Thread.spawn { }` body permits `blocking` and nothing else |
| `frame_boundary` | cooperative ∪ blocking ∪ test_suspend | the transform's framing (U1's `suspends` column) — `test_suspend` IS a boundary (the SL-306 trap); `closure_call` is read for NOTHING here |
| `closure_only` | closure_call and nothing else | diagnostics: "suspends only through a closure parameter" |

A consumer that needs a subset no row names adds a ROW, never a private
combination. The std seed table (`_effect_seed_std_methods`) carries the
SET per std method, not a bit.

## 2. Sequencing and ownership

U4 → U1 → U2 → U3 (SL-215 then SL-317). U4 is small and makes U1's
`suspends` column trustworthy; U1 is behaviour-preserving and gated; U2
flips the contract and owes the sweep; U3 adds shapes on the finished
table. Dispatches as soon as SL-274.p1 lands (SL-306.p1 r2 is in; user
re-sequenced Sep 18: the epic goes AHEAD of the small-fixes batch
SL-264/270/271/276, which does not touch the transform and follows it).
One Opus agent per unit, serially, each in its own worktree,
per-commit gate + terminal battery; the lead validates each with an
ADVERSARIAL two-module / same-name / generic-via-helper probe set on top
of the agent's tests (the Sep-18 lesson: the suite and battery passed
both patches codex bounced).

Acceptance for the epic: the discovery gate lane green; the shape table's
conformance rows all covered; SL-287, SL-316, SL-215, SL-317 closed;
K33–K37 each flipped or ruled; Blade and the whole corpus green; AND a
read-only build of `/Users/shawn/Projects/sawtracker/src/main.saw` that
compiles and whose IR shows no out-of-frame park in any driven path.

## 3. Rulings (RULED Sep 18, user)

1. U3/SL-317 + SL-321: a borrowed-place iterator SPANS a suspension when
   the referent is frame-owned — design 88's driven-in-place rule extended
   to lent places — and SL-321 lands inside U3 (the U3 bullet above has the
   full ruling). The lead's refuse-in-v1 recommendation was withdrawn on
   the user's observation that the std iterator already IS an untracked
   borrow of its collection, which SL-321's probe then proved unsound.
2. U2/K37: the refusal is PENDING A DYNAMIC-FRAME DESIGN, not permanent.
   Existential dispatch of a suspending conformance body and suspending
   RECURSION (SL-287's refusal; SL-304's option 2) both need a
   heap-allocated frame with an indirect resume, so they land together in
   one design — carrier **SL-322**. U2's shape table records both as
   REFUSE pending SL-322, with the refusal message naming it (the cycle
   message names the recursive function). The lead's permanent-refusal
   recommendation rested on the hidden allocation; SL-322 lists the
   questions that answer it (an explicit reader-visible surface,
   `--no-hidden-alloc` rejecting it, `AllocError` vs a panic boundary, an
   allocator type parameter for freestanding, `__release` on cancel, Send).

## 4. What this brief deliberately does NOT do

No change to the state machine, the seven split routines, the drive
loop, the executor, or design 44's by-value frame embedding (SL-304's
option 2 is SL-322's, the heap-frame design that ruling 2 pairs with
K37; this epic only records the refusal). No port to Saw — but what U1
consolidates is what the design-259 endgame ports once instead of twice.
