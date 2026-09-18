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

Behaviour-preserving by construction: U1 lands with the suite, the SL-280
rows, SL-306's matrix and the K rows byte-identical in outcome; `irdet`
and `reemit` prove the IR unchanged where no decision changed.

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
  iterator types qualify (`Iterator<T>` conformers; a `borrows` iterator
  over a place is a Law-of-Exclusivity question — a borrow window may not
  span a suspension unless the referent is frame-owned, ruled by design 88's
  rule for references), what `break`-with-value does across the split
  (SL-222's discarded-body rule stays), and the op-budget instrumentation
  (which currently SKIPS collection loops at `:494`) now charges them.
  Matrix: {Vector.iter, Map keys/values, Set, a user Iterator} × {suspension
  in the body, in the head} × {driven root, spawned, nested in while/for}.

### U4 — a THREE-VALUED answer at the effect source

`typechecker/effects.py` answers ONCE per node — `really` (reaches a
cooperative primitive, io park, blocking-extern offload or `__saw_suspend`),
`closure-only` (only through a call via a non-`sync` function value), or
`no` — instead of one bit meaning "might" plus design 206's
`really_suspending` and SL-306's `suspends_ignoring_closure_calls` beside
it. The `sync` checker keeps refusing on `closure-only` (a `sync` body
that maps a vector with an unknown closure is still not provably sync);
the transform's ledger reads `really` for framing and `closure-only` for
nothing. The trap SL-306's agent hit — `really_suspending` strikes the
test-only `__saw_suspend`, which IS a frame boundary — is a row.

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

## 3. Rulings owed (none block U4/U1)

1. U3/SL-317: may a `borrows` iterator over a place span a suspension when
   the referent is frame-owned (design 88's reference rule extended to
   places), or is a borrowed-place iterator always refused across a split?
   Lead recommends: refused in v1, frame-owned iterators only; revisit
   with evidence.
2. U2: K37 (existential dispatch of a suspending conformance body) — the
   design-223 recommendation was "work where the mechanism exists, refuse
   where it does not"; the table needs the refusal ruled as PERMANENT or
   as pending a dynamic-frame design. Lead recommends permanent refusal.

## 4. What this brief deliberately does NOT do

No change to the state machine, the seven split routines, the drive
loop, the executor, or design 44's by-value frame embedding (SL-304's
option 2 stays unruled and unneeded). No port to Saw — but what U1
consolidates is what the design-259 endgame ports once instead of twice.
