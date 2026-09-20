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
  source and String's an immutable one). Ruled Sep 18: the iterator
  becomes a TRACKED borrow of the collection for the loop's window, so a
  body mutation is the clean exclusivity error `v.push` already gets
  inside a `with_ref` window (designs 141/146), and that window SPANS a
  suspension. The alternative — refuse a borrowed-place iterator across
  a split in v1 — was withdrawn: it would have refused the very loop
  this unit exists to compile (sawtracker `store.saw:285`). Ruled Sep
  20 (superseding the Sep-18 phrasing "design 88's rule extended to the
  lent place" and the `let it = v.iter()` matrix cell, which is now a
  REFUSAL): the tracked borrow is a BORROWING STRUCT whose only window
  is the `for` statement — the subsection below, "U3 borrow-lifetime
  contract", is the whole ruling, its matrix and codex's completion
  requirements (c41); it supersedes this bullet wherever they differ.
  Obligation 3 row: "no use-after-free in safe code".

#### U3 borrow-lifetime contract (RULED Sep 20 — the borrowing-struct model; tightened per codex c41)

The contract codex asked for (SL-318.p1 review point 4), written against
the compiler as it is after U1, then tightened to codex's six completion
requirements (SL-318 c41); every claim names the mechanism it rests on,
and the U3 agent turns each into a test, never a re-derivation. Parts:
the MODEL and its ORIGIN, the for-head FENCE, EXTENT and DESTRUCTION
(codex i), ADDRESS STABILITY of frame AND referent (codex ii), EXTERNAL
STORAGE (codex iii), CANCELLATION as a safety guarantee, the MATRIX, the
fences.

**0. The model (RULED): the iterator is a BORROWING STRUCT — a type that
holds a lent place — and the `for` statement is its window.** Two
models were weighed and one refused. A HANDLE that carries a borrow past
the call that made it (design 201's `TaskCaptureBorrow` extent,
generalized to any value) is a lifetime in disguise: design 201 gets
away with it because a task handle is fenced on every side (written
fate, `join` releases, never stored), and a general iterator handle
would owe that fence at every position a value can go — obligation 1's
position-quantified rule. REFUSED (user, Sep 20): `let it = v.iter()`
is against the borrows rules; the pattern is the `for` head, the one
place the extent is already lexical. The borrow is carried BY THE TYPE,
in four spellings, each a Saw word or a design-141 word one position
over:

```saw
public borrows struct VectorIterator<T> {      // (1) the type declares its nature
    private vector: &Vector<T>                  // (2) the field is a plain reference
    private index: Int
}
extension Vector<T: Copy> {
    public func iter(&self) borrows -> VectorIterator<T> {   // (3) the signature echoes it
        VectorIterator<T>(vector: lends self, index: 0)      // (4) the body proves it
    }
}
```

(1) `borrows struct` is design 130's `unsafe struct` shape: the type
declares its nature at its declaration, every signature that carries the
type echoes it, `--emit-docs` carries it as a type attribute. No name
convention (`Unsafe*` exists because unsafety must read at every use
site by name alone; a borrowing struct appears only as a `for` head
result, where the loop syntax and the producing `borrows` already say
it). (2) The field keeps the ordinary reference spelling — `&Vector<T>`
IS the sigil; a second modifier on the field would be a second spelling
of one fact. The two levels police each other: a reference-typed field
outside a `borrows struct` is an error with a fixit naming the keyword;
a `borrows struct` with no reference field is design 130's rule-7
teaching error. THE PERMISSION A FIELD CARRIES MATCHES THE WINDOW MODE
(codex p5-r1 P1): U3 is a SHARED-window feature, so a borrowing struct's
reference fields are SHARED `&T` ONLY — a `&var T` field, and an
exclusive `lends` that would feed one, are REFUSED in U3 with a message
naming the rule (user-defined negative fixtures owed), because a user
iterator carrying `&var Collection` could reallocate the very
collection an outer shared iterator is reading through its own field;
recording the root alone would not catch it. This is DISTINCT from
`next(&var self)`: the cursor is the iterator's OWN state and mutating
it is not mutable access to the borrowed collection. The generic
window record still reserves shared/exclusive MODES for later clients;
U3 exercises shared only, and an exclusive-window derivation (with its
writer-versus-reader and nested-window rows) is the follow-up's to
specify. (3) `borrows` in the effect slot on a VALUE-returning
function: readers and `--emit-docs` see at the declaration that the
result borrows the receiver. A `borrows` function either `lend`s exactly
once (design 141) or RETURNS a borrowing struct, never both. (4) `lends
<place>` at the init site is the body's proof. LEND THE ROOT, NOT THE
BUFFER: `next` reads `self.vector.length` and `self.vector.buffer`
through the reference on every call, nothing is snapshotted, the struct
owns no raw pointer, and the only `unsafe` left is the index through the
buffer inside `next`. `EnumeratedIterator` is the same four lines.
RETURN, NOT SUSPEND: a design-141 accessor stops at its `lend` with its
frame alive and resumes for an epilogue at window close; this form
RETURNS — the accessor finishes, the borrow travels in the object, no
accessor frame lives across the loop.

THE ORIGIN IS A CHECKED COMPILER FACT (codex c41 point 1). A `borrows`
signature says a borrow exists; the call site must know WHICH root to
charge. U3 admits ONE origin: the RECEIVER — `lends self` is the only
`lends` spelling accepted, it REQUIRES a REFERENCE receiver (`&self`;
a by-value receiver's `self` is the callee's own local, not the
caller's persistent storage, so `lends self` in a by-value or `&var
self` producer is refused — the first because there is no live
borrowed origin, the second because U3 admits shared fields only), and
every returning path of a `borrows`
function returning a borrowing struct must initialize EVERY reference
field with `lends self` (a path that constructs the struct any other way,
lends a non-receiver place, a projection of `self` (`lends self.buffer`),
another reference parameter, or a local, is refused: "U3 admits the
receiver as the only borrow origin"). The origin summary — "receiver
root" — is recorded on the function declaration as a DECLARED annotation
field (design 126's AST contract, gated by the `astgraft` lane), so it
rides `substitute_ast_types` through monomorphization and travels with
an imported declaration exactly as `is_reference` does; at the call site
the checker substitutes it onto the RECEIVER PLACE's root through design
141's root attribution (`&v[i]` charges `v`; `v.iter()` charges `v`;
`st.patches.iter()` charges the path `st.patches`, an enclosing-owner
path per design 8/10) — THAT is the handoff, named here so the agent
reuses the attribution rather than re-deriving a root walk. The
borrowing-struct-ness is a property of the TYPE IDENTITY (defining
module, name — design 144), never of a std visibility: a user `borrows
struct` in another module is refused and admitted by the same rules.
NOTHING ERASES IT: a borrowing struct may not instantiate ANY type
parameter — not `Optional<It>`, `Result<It, E>`, `Vector<It>`, `Box<It>`,
a generic `T`, or a closure's return — and may not be erased into an
existential (`any Iterator`); it may CONFORM to `Iterator` (that is how
`for` reaches `next`), but only static dispatch reaches the conformance.
Each is a refusal row; together they are what makes "a generic identity
wrapper launders the value" unwritable rather than caught.

**The for-head FENCE, semantically (codex point 2).** A `borrows` call
returning a borrowing struct is legal in exactly ONE position: as the
DIRECT head of a `for`, where the RECEIVER is a PLACE rooted in a named
binding — a local, a parameter (`&`, `&var`, or by value), `self`, or a
field path of one (`st.patches`). Everything else is refused through ONE
rejector with one message naming the rule, each a matrix row: a
TEMPORARY receiver (`for x in make_vec().iter()` — "bind the collection
first": a temporary has no persistent storage to point into, codex point
4); an `if`/`match`/block/`try` EXPRESSION in the head that yields the
call; a `let`/`var` init; an argument; a `return` outside a `borrows`
function; a struct/enum/tuple/collection-literal element; a closure
capture or return; a spawn argument or capture; a `move` operand; an
assignment RHS; a `?.`/`??` operand. A helper forwarding the result and a
generic identity are not refusal rows but IMPOSSIBLE spellings: a
borrowing struct cannot be a plain function's parameter or return type,
nor a type argument, so no helper can name it (the refusal is at the
helper's declaration). NARROW EXCEPTIONS, stated so they license no user
storage: (e1) construction and `return` inside the producing `borrows`
function — its ONLY legal return; (e2) the compiler's hidden `__iter`
binding — a frame field in a driven body, an alloca in a sync one, never
nameable; (e3) the receiver position `&self`/`&var self` of the struct's
OWN extension methods (`next`); (e4) INSIDE those methods the reference
field is readable only as a non-escaping RE-BORROW — design 106's
forwarding rules: `self.vector.length`, `self.vector.buffer[idx]`, `&self.
vector` as an argument — never bound, stored, returned or captured;
field extraction anywhere else is refused as a language rule (std's
`private` is convenience, not the safety boundary). NO SECOND ITEM
LIFETIME: a borrowing struct's `Iterator.Item` may not be a reference or
a borrowing struct in U3 — the yielded value is OWNED by the loop
variable (Vector's `T: Copy` elements satisfy this; a user iterator
yielding `&T` is refused with the message naming the rule). NEGATIVE
USER-DEFINED FIXTURES are owed even though std is the only positive
consumer migrated: a user `borrows struct` over a user collection
exercising every refusal position above, plus the accept cell.

**(i) Extent and destruction — two events, ordered (codex point 3).**
The window opens at the head's evaluation and closes when the `for`
statement ends; the extent is LEXICAL, so every route out leaves it.
Two things happen at the close, in THIS order: first the iterator is
DESTROYED — its owned fields drop through the ordinary machinery (design
131's deinit prefix + synthesized field drops; the reference field is
exempt, design 88), exactly once — and THEN the root charge ends. The
order matters because a hand-written `deinit` on a borrowing struct may
still read through the reference. Owned fields and a `deinit` body on a
borrowing struct are SUPPORTED in U3 (lead call: the drop machinery is
the existing one, and refusing them would make the std iterators the
only writable shape); the fixture is a user borrowing iterator holding a
COUNTED resource beside a COUNTED Vector owner, because an iterator of
reference-plus-Int cannot test destruction. Routes, each owed a test
proving the root is writable again at the first reachable point after
the exit AND the value is the sync twin's: (1) exhaustion; (2) `break`
with and without a value (SL-222's discarded-body rule unchanged); (3)
`continue` TARGETING THIS LOOP — NOT an exit: iterator and charge stay
live across the back-edge, which the op budget now charges (the `:494`
skip goes); a `break`/`continue` targeting an INNER loop closes nothing
here, and one targeting an OUTER loop closes this window first (the
reuse obligation's B2 states the general rule); (4)
`return` from the body — the writable-again proof sits in the CALLER
after the call, since the code after the loop is unreachable; (5) an
error propagated by `try`/`?` — proof in the `catch` (block and inline
forms — SL-215 lands beside this) or the caller; (6) an error or a
cancellation CAUGHT inside the body that CONTINUES the loop — the window
stays live, the iterator is not destroyed; (7) exit under cancellation
(below). An EMPTY loop opens and closes the window with zero iterations
(the head still evaluates, the iterator still drops once); a `break` on
the first iteration followed IMMEDIATELY by a mutation of the root is the
release-timing cell. Checker-side, no route may leave the root charge
live past the statement, gated like design 189's loop rule (K17).

**(ii) Address stability — the frame never moves after its first
`resume`, and the REFERENT is pinned for the window (codex point 4).**
The three places a frame lives: a DRIVEN-in-place frame is `var __f` on
the driver's own stack for the whole drive (`_make_driver`), never
moved; a SPAWNED frame is constructed INSIDE `Box<any Resumable>.make`
in the spawn helper (`_make_spawn_helper`) at state 0, before any
resume, and design 134's cell/frame split promises "the fat pointer's
data word never moves" — including across the `threads: N` worker
hand-off, which passes the box; an EMBEDDED callee frame is a by-value
FIELD of its caller's (design 44) and inherits its stability. The one
move a frame undergoes — the spawn box — precedes state 0, and every
window opens inside a state body. U3 PINS this: a transform-side
invariant that a spawn helper boxes only a state-0 frame (ICE breadcrumb
otherwise). THE REFERENT: the direct-call-on-a-place rule guarantees the
receiver is persistent storage — a frame FIELD (a frame-local `var v`
under design 44's encoding), a design-88 frame-resident POINTER's
referent (a `&`/`&var` parameter), or `&self.<field>` into an enclosing
frame — never a resume-stack temporary; and the SHARED root charge
forbids, for the window, every operation that would relocate or replace
the referent: `move v`, `v = other`, `swap`, `take`, a `swap_out` of an
enclosing owner, and reassignment of any enclosing-owner path (K20's
precedent: `move` of a borrowed root is refused) — each a row.
STRUCTURAL ASSERTION: the transform asserts that the `__iter` field's
reference targets a persistent owner slot — a frame field address, a
frame-resident pointer's referent, or a parent-frame field — and never a
state-body local; a lane check reads the frame layout (`--emit-frame-
layout` shape) for the matrix files. RUNTIME CELLS: a window across a
suspension in the driven context; in a spawned root; through an EMBEDDED
callee inside a spawned parent with REPEATED `Pending`s (the frame is
resumed many times while the window is live); and `threads: 2`, which
stays REFUSED on the existing Send-on-frames rule (K19) — frame address
stability is no argument to relax Send. The synthesized frame gains a
reference-typed field (design 88's frame-resident pointer, exempt from
drop flags); the generated methods already say `unsafe` (design 222 unit
2), and no user-written signature is asked to.

**(iii) External storage — proof by tracked origin, extent and
exclusivity; confinement is the background (codex point 6).** A
collection reached through a `&`/`&var` PARAMETER is a design-88
frame-resident pointer into the DRIVER's caller's storage (in-place: the
caller is parked on the drive) or into the SPAWNER's storage held by a
design-201 extent (spawned: the argument borrow keeps the root alive and
excluded for the task's life). A collection that is an ENCLOSING FRAME's
field is `&self.<field>` into the parent frame, which does not move by
(ii). Address stability is inherited; what remains is NON-MUTATION across
the suspension. LANGUAGE_SPEC §"Suspension and the coroutine transform"
currently says a container borrow "may not span [a suspension]" because
"a concurrent task could reallocate" the storage — too broad for THIS
window, and rewritten NARROWLY: the tracked `for` window is allowed
because its ORIGIN is recorded, its EXTENT is the statement, and the Law
of Exclusivity sees every competing safe writer — a `&var v` design-189/
201 extent live at the head, or STARTED inside the body, is the
writer-beside-reader error; a `&v` extent composes; a `threads: N` group
refuses the reference on Send before the question arises; inside this
task nothing runs while the frame is parked. `with_ref`/`with_var_ref`
bodies and accessor `lend` windows RETAIN their `sync` restriction
pending their follow-up; the spec says so in the same paragraph. The
`Mutex` row is CLOSED, not OPEN: `Mutex.lock<R>(&self, body: (&var T)
sync -> R)` runs a `sync` body, so a `for` over the guarded collection
INSIDE `lock` is a sync window and works, and a suspension inside it is
refused by the sync-body rule — a PAIRED test, without extending guard
lifetimes.

**Cancellation is a SAFETY guarantee, not a termination claim (codex
point 5).** A cancel request does not close a window: the borrow stays
live while cancellation is delivered, while an error or the cancellation
is caught and handled inside the body, and until the statement has
actually exited; an external task extent is released by `join`, never by
`cancel`. What IS guaranteed: a live window is never destroyed by
dropping a still-running frame — teardown DRIVES the frame (cancel wakes
a parked task, design 102) and JOINS it (design 124 item 5, K87) before
its box is released, and the frame reaches the statement's exit or Done
by ordinary control flow, so iterator and owner cleanup run exactly once
on the route actually taken. A parent never completes while a sub-frame
is mid-flight (`_owned_frame_fields`). If the agent finds a
FRAME-ABANDONMENT path — a box dropped without being driven to Done — it
is a FINDING (SL issue) whose fix runs the window's cleanup, not an
"impossible" assertion; panic and process exit stay explicitly outside
ordinary unwinding. Cells: cancellation while parked in a NESTED callee
inside the body; a caught cancellation that CONTINUES the loop; a cancel
delivered BEFORE the head is initialized — a cancel is a REQUEST, it
does not stop the head from running; the cell is a cancellation
PROPAGATED out of the head's own evaluation (a caught-and-rethrown
park in a suspending argument, B3's A3), so no iterator is ever
constructed: ZERO iterator constructions and ZERO iterator drops, and
the OWNER's deinit count is whatever its initialization state was
(one if the vector was initialized before the head, none otherwise);
cancel at the park then exhaustion; every OTHER cancellation cell
counts the vector's and the iterator's deinits and expects one each.

**The matrix (obligation 1), rows the agent covers one by one.**
SL-317's original axes stay: {Vector.iter, enumerated, a user borrowing
iterator, a record-less user Iterator, Map keys/values (owned copies —
control)} × {suspension in the BODY, in the HEAD (the receiver
expression itself suspends: `for x in (try slow_load()).iter()` is
REFUSED as a non-direct head; a suspending call bound before the loop is
the accept twin), NESTED loops (inner over the same root composes; inner
mutating the outer's root refused)} × {driven root, spawned, embedded in
a spawned parent, nested in while/for}. Root axis for (ii)/(iii): {frame-
local, `&` param, `&var` param of a driven callee, `&var` param of a
spawned root (design 201), enclosing frame's field, field of a `&var
self` receiver, imported collection type, generic collection
instantiation (`Vector<Wrapper<T>>` via a generic driven callee),
imported producer module}. Conflict axis: {body pushes; `with_var_ref` on
the root in the body; `&var` extent live at the head; `&var` extent
STARTED in the body; `&` extent (composes); move/reassign/swap of the
root or an enclosing owner; second `for` over the same root nested
(composes)}. Release axis: the seven routes of (i), the empty loop, break-
then-mutate, the cancellation cells. Fence axis: every refusal position
of the fence paragraph, the origin refusals, the type-argument/existential
refusals, the Item-lifetime refusal — each with a user-defined borrowing
struct. Obligation 3 row: "no use-after-free in safe code" (SL-321's
repro flips from `seen = 1025` to a compile error at the push), beside
the design-96/101/104 rows U2 rewrote.

**REUSE OBLIGATION (user, Sep 20): build the STATEMENT-SCOPED WINDOW,
with `for` as its first client — not a for-loop feature.** The user
intends a generic scoped-borrow statement later (a keyword-introduced
block that binds a lent PLACE for the statement's extent — the
non-closure form of `with_ref`, able to suspend, `return`, `break` and
propagate errors; with an `else` arm for a `borrows -> T?` head; the
follow-up brief carries its spelling). U3's implementation must let
that brief add its syntax, its typechecking client and its
acquisition/result binding — and NO second implementation of root
accounting, pinning, suspension persistence or exit cleanup (codex c44:
the guarantee is "no duplicated lifetime machinery", not a literal
node-plus-one-entry count, since an accessor window's acquisition and
epilogue differ from an iterator's). So, by construction (obligation 1,
a funnel with named entries): (1) the
typechecker owns ONE record, a statement window — root path, mode
(shared/exclusive), origin, the statement node that is its extent —
opened and closed through ONE chokepoint whose docstring names its
clients (`for` is the only one in U3) and which performs the root
charge, the exclusivity conflicts, the move/reassign/take refusals, and
the close-on-every-route accounting; the `ForLoop` adapter is a thin
caller that supplies the head and the body and reads back nothing
for-specific; (2) the coroutine transform keys "a window is live across
this suspension" on the window RECORD, not on `ForLoop` — the frame
field for the window's binding, the design-88 pointer encoding, the
referent-pinning assertion of (ii), and the exit-route closing are
properties of the window; the for-split (`_split_for`'s collection arm)
asks the window machinery for its field and its close points and adds
only the `next()` re-entry; (3) codegen's sync lowering of the window
(the hidden binding's alloca + the drop-before-charge-end order of (i))
is the same one routine for any client; (4) the diagnostics name "the
window" and its introducer generically, with the `for` wording supplied
by the client, so the generic form does not fork the messages; (5) the
`borrowing struct` rules (origin, fence, no-erasure) are keyed on the
TYPE and on "the head of a window", never on `for` — the generic
statement would bind a borrowing struct through the same head rule if
ever ruled. FOUR BOUNDARIES the seam is policed against (codex c44):
(B1) ITERATION stays in the `for` client — iterator construction,
`next()`, element/pattern binding, exhaustion, the back-edge and its
op-budget charge; WINDOW LIFETIME is the common layer — root charge,
persistent referent slot, suspension state, ordered cleanup. The record
holds a GENERIC resource/owner slot, not a field named `__iter` or an
`Iterator`-shaped payload; and not every `ForLoop` is a window — a range
loop or an OWNED-iterator loop opens none and uses the ordinary split —
nor is every future window a loop. (B2) A window closes by CONTROL-FLOW
TARGET, not by the spelling of the exit: an edge closes exactly the
windows whose lexical extent it leaves, inside-out — `continue`
targeting THIS `for` keeps its window, `break` targeting it closes it,
`break`/`continue` targeting an INNER loop closes nothing of the outer,
a window nested inside an outer loop closes when control continues that
outer loop, and `return`/error/cancellation propagation close every
scope crossed. The cleanup funnel receives RESOLVED scope/target
information; an implementation that special-cases every `Continue` node
as "keep open" leaks the first client's shape and fails review.
Nested-window and inner-loop cells are pinned NOW. (B3) The record has
a LIFECYCLE — ACQUIRE, ACTIVE, RELEASE. ACQUIRE is ONE sequence (codex
p5-r1 P2; it is LANGUAGE_SPEC's "Argument Evaluation Order" — receiver
before arguments, arguments left to right — plus design 141's rule that
a reference argument's window is the whole CALL EXPRESSION, applied to
the head unchanged; nothing here changes evaluation order): (A1) the
receiver PLACE is resolved — it must be a persistent slot (a frame
field, a design-88 pointer's referent, `&self.field`), which is what the
direct-head rule guarantees, so it is never re-resolved to a different
address; (A2) the head's SHARED borrow of that root opens — and it
spans the ENTIRE head call expression, ARGUMENTS INCLUDED, exactly as
`f(&v, g(&var v))` is already a conflict today: an explicit or default
argument that writes, moves or reallocates the root (`v.iter(slow(&var
v))`) is REFUSED, a suspending argument is ACCEPTED (the U2 shape
table's HOIST lifts it before the call; the checker still treats the
argument as inside the head's window, so the static conflict rule does
not depend on the lowering, and the root's address is stable across the
hoisted suspension because A1 made it a persistent slot); (A3)
arguments evaluate left to right; a FAILING argument (an error
propagated out of it, or a cancellation caught there) exits before the
producer runs — no statement charge exists yet, no iterator was
constructed, the head window closes with the expression, nothing to
clean; (A4) the producer runs and RETURNS the borrowing struct; (A5)
the head window hands off to the STATEMENT charge with no gap — the
same root, the same shared mode, one continuous extent — and the
resource is initialized into its persistent slot; only then is the
window ACTIVE (the resource is initialized before it is treated as
live). RELEASE is exactly once on exit, never on an uninitialized
resource. Three cells pin the sequence: an argument mutating/moving
the root (refused at the argument), a suspending argument (accepted,
order preserved, value equal to the sync twin's), a failing argument
(no charge, no iterator drop, the root writable in the `catch`). The
whole thing is done with a CLIENT-PROVIDED
cleanup operation: for this client, release destroys the borrowing
iterator before ending the root charge; a future accessor window's
release would run an accessor epilogue, and an optional head may take
an `else` branch without ever activating a body window, so the shared
API assumes neither that release is an iterator drop nor that every
evaluated head opens a window. (B4) The DIRECT-head / temporary-receiver
refusals apply to BORROWING results only. The original U3 requirement
stands: ANY `Iterator` conformer, with a suspension in the head or the
body — an OWNED iterator produced by a suspending head is evaluated
once, preserved in frame state, then iterated (its own matrix cell,
beside the borrowed-from-a-temporary REFUSAL cell); a BORROWED head
whose ARGUMENTS or defaults suspend follows B3's ACQUIRE sequence
(A1-A5: receiver place first, the head's shared borrow spanning the
whole call expression, arguments left to right and hoisted when they
suspend) rather than falling under the temporary-receiver refusal by
accident. The lead reviews the seam at
validation (a grep for `ForLoop` in the window chokepoint and the
transform's window handling must find only the adapter), and the
agent's report includes a paragraph "what the generic window statement
would add": its syntax and typechecking client, its acquisition/result
binding, and a demonstration that root accounting, pinning, suspension
persistence and exit cleanup need no second implementation.

**Fences (U3 scope).** The `for` head is the ONLY window that spans a
suspension in U3. `Vector.with_ref`/`with_var_ref` bodies and `borrows`/
`lend` windows keep their `sync` rule — same argument, same mechanism,
but a second consumer sweep and their own rows, so they are a filed
follow-up (SL issue at dispatch), not a rider (RULED (c)). Receiver is
the only origin; no `let`-bound borrowing struct; no borrowing struct as
a parameter, field of another struct, or type argument; `Item` owned.
The `for` split (SL-317) admits ANY `Iterator` conformer — a record-less
user iterator splits and stores as a frame field exactly like the std
one; the borrowing struct is what the std iterators ADD, not what the
split requires. CONSUMER SWEEP (obligation 2, Sep 20, grep over
examples, blade, libs, devtools, sawc/std and the read-only sawtracker
sources): 51 `for` heads over `iter()`/`enumerated()`, all direct calls
on named places, untouched; the ONLY iterator held outside a `for` head
is Data's (`examples/data_iter_outlives_source.saw`), whose iterator owns
its source and is not a borrowing struct. `VectorIterator`'s `public`
was added so a holder could name it; with holding refused the agent may
drop it or keep it, and says which. The design-141 sentence "a place is
never a value and never escapes" becomes: a place is never a value
outside a borrowing struct, and a borrowing struct is never a value
outside its window.
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
3. U3 borrow-lifetime contract — RULED Sep 20 (the subsection under
   U3): (a) the borrow is carried BY THE TYPE — `borrows struct
   VectorIterator<T>` holding a plain `&Vector<T>` field, produced by
   `func iter(&self) borrows -> VectorIterator<T>` whose body says
   `lends self`; a borrowing struct is a window value, never a stored
   one; (b) the pattern is the `for` HEAD only — `let it = v.iter()` is
   against the borrows rules and is refused, which is what keeps the
   extent lexical (the handle-extent model was weighed and refused as a
   lifetime in disguise); (c) `with_ref`/`lend` windows across a
   suspension stay a follow-up, not a rider. Codex review of the
   contract requested on SL-318 before U3 dispatches.

## 4. What this brief deliberately does NOT do

No change to the state machine, the seven split routines, the drive
loop, the executor, or design 44's by-value frame embedding (SL-304's
option 2 is SL-322's, the heap-frame design that ruling 2 pairs with
K37; this epic only records the refusal). No port to Saw — but what U1
consolidates is what the design-259 endgame ports once instead of twice.
