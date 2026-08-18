# Saw Tracker — Archived Recaps (Aug 18 – Aug 25, 2026)

Landed / closed / decided entries moved VERBATIM out of designs/todo.md
as of Aug 18, 2026. Section order and text are as found there; every
open item stayed in todo.md. These entries closed between the Aug-17
split and the end of Aug 18, so they are this week's first. Nothing was
rewritten, stale lines included: design 233's header still reads
"awaiting integration", which it was when the entry was written and is
no longer (integrated on main as d84b0269 / 174b235b / bc484c87, all
ancestors of the Aug-17 split commit a89ffef8). Append-only history.

## ~~DF-232c — a raw-backed enum's case value takes an INTEGER LITERAL only~~
## — **FIXED Aug 17** (filed Aug 17, SOS M3 unit 1 review-pass rider)

The position now takes a const EXPRESSION. The parser keeps its literal fast
path (a bare or negated INT that ENDS the variant — the common `case A = 0`,
which costs no fold and behaves exactly as before) and otherwise parses an
expression into a new declared `EnumVariant.raw_value_expr`;
`_fold_enum_raw_values` folds it into `raw_value` through design 186's
`const_eval`, at platform width.
WHERE, and why it is the only workable seam: `raw_value` has TWELVE consumers
across four phases, and the earliest is `_ast_enum_raw_values`, called by
`_collect_const_statics` BEFORE registration so a flag-enum static
(`static RW: UInt8 = Perm.Read | Perm.Write`) can see the numbers. Folding
immediately ahead of that means every consumer still reads a plain int and
none of them changed — including the range check against the backing, which
is unchanged code running on the folded value.
BOUNDARY, refused by name rather than half-supported: the expression may not
name a `static` or another enum's case. Those resolve by stamping leaves
against a table built in DECLARATION order, and all enums are read BEFORE any
static precisely so the flag-static case works — so naming one from a case
value is a forward reference into a table that does not exist yet. Its
refusal is also the ONLY error for that case: registration's "needs an
explicit value" check now skips a case that WROTE an expression, since
telling the author a value is missing would contradict the line they are
looking at.
Design 145's no-auto-increment rule is untouched — a folded `1 << 8` states
its value as exactly as `256` does.
Tests: `examples/enum_raw_value_takes_const_expression.saw` (XFAIL flipped —
shifts, `2 * 4`, hex, binary with separators, parenthesized, two operators,
a signed backing with `-1` and `0 - 2`, plus design 185's other reading, the
case value as a const OPERAND in a static),
`examples/enum_raw_value_const_expression_out_of_range.saw` (`1 << 9` at
`UInt8`) and `examples/enum_raw_value_const_expression_needs_constant.saw`.
DEFERRED, deliberately: the sos/ enums are NOT flipped from decimals to
shifts here — same reason as DF-232b, a concurrent agent is restructuring
sos/kernel, and the flip is scheduled for after both branches land. Values
are unchanged meanwhile.
NEIGHBOURING AND NOT A DEFECT (unchanged by this): a parenthesized shift in a
COMPARISON stays platform `Int` (design 195 promotes bare literals only, and
a subexpression reaches no expected type), so `>= (1 << 8)` against a
`UInt32` is refused and `(1u32 << 8)` is its spelling — which is why the abi
`static_assert`s keep their decimals. [232]

## DF-232i — CLOSED (Aug 17): a GENERIC raw-backed enum keeps its declared
## tag values through monomorphization (RENUMBERED from the finder branch's
## DF-232e — the kcore split claimed d-g first; RULED: FIX PROPER, values
## survive, not the refuse-the-combination fallback; landed as item 6 of
## the Aug-17 small-fix batch)

**Landed, the ruling as stated.** `Code<Int>.Warn as UInt8` gave 1 where the
source said 20 — silent wire-format corruption with no diagnostic, and
precisely what a declared backing exists to prevent (design 145 unit B2 pins
the representation so reordering cases cannot renumber them; a generic enum
was renumbering them by construction).

TWO faults, both in `_ensure_monomorphized_enum` (codegen/generics.py) and
both needed:
1. the rebuilt `EnumVariant`s carried only `name` + `associated_types`, so
   `raw_value` was dropped; and
2. `_register_concrete_enum` was called with no `raw_type`, so it took its
   ordinal path however good the variants were. Only the PAYLOAD types depend
   on the instantiation — the tags and the backing are the enum's own and are
   identical in every instantiation, so both pass through unsubstituted.

`from(raw:)` on a generic instantiation did not merely invert wrongly, it did
not COMPILE: `_check_enum_from_raw` stamped the base name and dropped the
receiver's type arguments, so the result typed as a bare `Code` and codegen
looked it up in a table that only ever holds `Code$1$Int` —
`internal compiler error: 'Code'`. The checker now carries the resolved
arguments onto the returned `E<...>?`, and `_generate_enum_from_raw` resolves
the instantiation from them through `_ensure_monomorphized_enum` (idempotent,
and the same call that carries the raw values onto the copy).

Test: `examples/generic_enum_raw_backing_keeps_values.saw` — the declared
value out of TWO instantiations plus an equality row proving they agree, the
round trip back through `from(raw:)`, an ORDINAL rejected by the inverse, the
width the backing pins, and a non-generic control. The XFAIL pin at the same
path retired via the add/add resolution at integration. MERGED-TREE CHECK
DONE (lead, Aug 17): const-EXPRESSION raw values (DF-232c's
`raw_value_expr`, folded before monomorphization) survive by the same route —
probed with `1 << n` values on two instantiations, round-trip included
(.build/scratch/probe_232i_constexpr.saw). [145, 232]

## ~~DF-232a — INTERNAL COMPILER ERROR: a bare integer literal does not
## adopt the expected fixed-width type in PLAIN ASSIGNMENT position~~
## — **FIXED Aug 17** (filed Aug 17, SOS M3 unit 1)

`TIMERS[slot].deadline_ns = 0` on a `UInt64` field died with
`cannot store i32 to i64*` on riscv32; three lines reproduced it on the
host at any two widths. TWO DEFECTS, both fixed: the literal now adopts
(an assignment target names an expected type exactly as an annotation
does), and an unreconcilable value gets a CLEAN REFUSAL.
MECHANISM, as landed: the same shape in BOTH halves of the compiler, so
the fix is two funnels. The obligation-4 sweep widened the filed three
ICE rows to SIX — the tracker's `v = 4`, `w.b = 2`, `rows[0].b = 7`,
plus `t.0 = 5` (tuple index), `nt.p = 6` (named-tuple element) and
`r = 11` through a `&var` referent.
`_check_assign_rhs` (typechecker) is now THE reconciliation of an
assignment's RHS against its target's type — push the expectation down,
check, reconcile a bare `None`, refuse by name, take the value-transfer
checkpoint. Its docstring names all NINE entry points; only three took
the propagation before (array element, place lend, `unsafe static var`),
and the other six ICE'd. `_store_assigned_value` (codegen) is THE store
an assignment makes — integer-width fit, then optional layers; its
docstring names all FIVE store sites, of which only the array-element
arm coerced the width. Two rows the finding never named fell out of the
codegen half: `v = k` for a plain `Int` k (LEGAL — a platform `Int`
converts to and from any integer type — and it ICE'd, since adoption
cannot reach a non-literal) and a folded `v = 2 + 3`.
Tests: `examples/assignment_target_adopts_fixed_width.saw` is the
matrix (XFAIL flipped, all eleven target-kind rows plus the platform-Int
and negative-literal negatives), and
`examples/assignment_target_literal_out_of_range.saw` pins the second
defect — `v = 999` at `UInt8` is now
``integer literal 999 does not fit in `UInt8` (range 0..=255)`` at the
LITERAL's column. LANGUAGE_SPEC's adoption-position list and the
saw-lang digest name the assignment target kinds. The sos/ `timer_disarm`
suffix workaround (`0u64`, with a comment pointing here) can drop
whenever that branch next moves — not touched from here. [232]

## DF-233a — SILENT HANG: an `if let`/`guard let` carrying a `break` for a
## suspension-spanning loop is not CFG-split (filed + FIXED Aug 16 by the
## design-233 dispatch; pre-existing, found probing the interim drain idiom)

**Symptom.** In a suspending body, `while true { if let x = f() { … } else
{ break } }` HANGS — the else branch runs, the `break` is taken, and the loop
re-enters the same state forever. A variant drops everything after the loop
instead. Sync code is unaffected, so the shape reads as working until it is
driven. The `guard let`-`break` drain idiom this tracker blessed as the interim
spelling for `while let` shares it: it works where the guard's own block spans a
suspension (the probe that blessed it) and hangs where it does not.

**Mechanism.** Design 96 (DF6) established the rule: a construct carrying a
`break`/`continue` for an ENCLOSING suspension-spanning loop must be CFG-SPLIT
even when it does not itself span, or the jump lowers in place as a raw `break`
and escapes the resume method's `while true` DISPATCH loop instead of the
logical loop. `_lower_stmt` applies that rule on the spot (`needs_ctrl_split`)
to `if`, `match` and `try`/`catch`. It CANNOT apply it to an `if let`/`guard
let`: their split needs the binding renamed to a frame field first, which only
`_mark_optional_binding_splits` does — and that pass only ever asked whether the
BODY spans. So the two optional-binding forms were the two the design-96 rule
never reached.

**Obligation-4 sweep — three positions, one pass.** The mechanism is
"`_mark_optional_binding_splits` decides less than the lowering needs", and it
reaches every position that pass walks:

1. **The split predicate** — `if let` (miscompiles: hang or dropped loop tail)
   and `guard let` whose own block does not span (same). Fixed by adding the
   design-96 clause, with a `in_spanning_loop` flag a `while`/`for` re-decides
   for its own body and every other container passes through.
2. **The container descent** — hand-rolled over six kinds, missing
   `try`/`catch`: the entry every hand-rolled spine walk misses (DF-193a), which
   is why `ast_walk.control_blocks` exists. An `if let` whose body spanned a
   suspension inside a `try` block was never marked, so the CFG walk refused to
   descend and the suspension was REJECTED as a "nested/expression position" — a
   legal program refused rather than miscompiled. Fixed by taking the tracked
   enumeration.
3. **The block TAIL** — the walk read `block.statements` and not `final_expr`,
   where the parser parks a block's last bare expression. A drain loop's `if let`
   usually IS the loop body's tail. `_normalize_suspending_tails` hid how often
   this matters (it statementizes every SPANNING tail, so only a non-spanning
   one is left) — and a non-spanning construct in a spanning loop is exactly
   what clause 1 is about. Fixed with `_stmt_positions`, a named funnel the
   frame-field census takes too (it owes a field to every binding the marking
   splits).

**Not reached, recorded per the obligation:** a value-position `if let` holding
a `break` (`let y = if let x = o { 1 } else { break }`) sits in a `LetStatement`
value, not a statement position, so no spine walk reaches it at all — a separate
mechanism (the value-conditional lowering), not a sibling of this one.

Fix + regression matrix: `examples/coro_optbind_loop_control.saw` (seven
positions, driven), `..._spawned.saw` (spawned root + suspending scrutinee),
`coro_optbind_split_in_try.saw` (position 2).

## Design 233 — `while let` (BUILT Aug 16, awaiting integration)

Brief: `designs/233-while-let.md` (fully ruled). Landed in four commits: the
DF-233a prerequisite above, then parser + sync semantics, then the suspension
matrix, then docs.

**Shape.** The parser LOWERS the header into the two constructs it means —
`while { if let x = SCRUT { BODY } else { break } }` — so obligation 1's funnel
is satisfied by identity rather than by discipline: the binding IS an `if let`,
so design 100's derived-shadow rule, design 63's tuple pattern, design 131's
payload-read tier, design 62 G2's scrutinee hoist and design 104's CFG split all
reach it through their own existing entry points, with no second position to keep
in sync. `parser/statements.py _parse_while_let` is the new entry point named in
`_check_if_let_expr`'s docstring. Two marker fields carry what the desugared tree
can no longer say for itself (`IfLetExpr.while_let`, `WhileExpr.is_while_let`):
diagnostics name `while let`, the synthesized `else { break }` is not reported as
a branch the author can retype, and value position is refusable.

**Every ruling built as written.** Scrutinee re-evaluates per iteration
(`continue` re-runs it); `None` ends the loop; no `else` clause (clean parse
error); value position refused with its own message and a hint; `try?` composes
for Result sources; a tuple pattern is allowed sync and refused over a suspension
with the inherited diagnostic, now naming `while let`.

**Verification.** 10 tests (5 sync/error, 5 suspension), every matrix row run in
DRIVEN and SPAWNED bodies, plus MT (`threads: 4`), a suspending `try`/`catch`
inside the loop, and `Channel.try_receive` as the drain family's concurrency
member. No new TOKENS, and there is no second parser (`selfhost/` is a lexer
only), so lexdiff/astdiff/selfhostlex were untouched by construction — verified,
not assumed.

**Not built, and why.** No native Result form (the sugar is for drains; a caller
wanting error inspection writes the `match`). No `break <value>` story: value
position is refused, so the conditional-loop value question stays where design
177 left it.

## DQ-230b — `Channel.try_send` has two failure modes and one error type
## (filed Aug 16 by the design-230 dispatch, unit C; RESOLVED Aug 17 by
## design 234)

**RESOLVED — design 234 retires `try_send`**: `send` returns
`Result<Void, ChannelError>` with `ChannelError { Closed, Cancelled,
Alloc(e: AllocError) }`, and the `try_` prefix is reserved for non-blocking
variants. The asymmetry this entry records dies with the twin. Executes with
234's Channel sub-unit; kept below for the record. [234]

(original) **OPEN — surface decision, not a bug.** Design 230 gave `send` a second failure
(`Err(ChannelError.Closed)`) beside the allocator one design 123 gave it
(`panic`, with `try_send` as the reporting twin returning
`Result<Void, AllocError>`). The two error sets are disjoint and `try_send` has
one slot, so unit C left it PANICKING on a closed channel, with a message naming
`send` as the spelling that reports one:

```
panic at channel.saw:NN: Channel.try_send: channel is closed (use `send` to
handle a closed channel)
```

That is loud rather than silent, which is the part that mattered, and it invents
no public type — but it is asymmetric: the same program state is a value through
one door and fatal through the other. The brief ruled `ChannelError`'s cases
(`Closed` now, `TimedOut` reserved) and did not reach `try_send`.

The three readings worth weighing, none picked here: widen `try_send` to one
error type covering both (an `AllocFailed` case on `ChannelError`, which puts an
allocator concern in a channel-protocol enum); keep two types and let `try_send`
return `Result<Void, Box<any Error>>` (erased, allocating, wrong for the
denied-allocator case it exists for); or retire `try_send` on the grounds that a
caller who cares about allocator refusal on a channel should say so once at
`try_make`. One call site in tree (`examples/alloc_no_inert_objects.saw`).

## DF-230a — CLOSED (Aug 17): cancellation reaches a task parked inside
## `Channel.receive()`, and it reports `Err(Cancelled)`

**Rider ruling (user, Aug 17): CANCEL-BEATS-BUFFERED is the contract** — a
task cancelled while a value is already buffered gets `Err(Cancelled)`, not
the value: cancellation is the receiver explicitly asking for no more data,
so delivering one more would contradict the request. The value is not lost
(it stays in the channel for other receivers / teardown). This RESOLVES the
implementation's flagged judgement call below: the loop-TOP position is the
ruled behavior, and `examples/channel_recv_cancel.saw`'s updated expectation
is the contract, not a regression.

**Landed, the ruling as stated.** Three pieces, and the first two are only
correct together:

1. **The check.** `ChannelError` gains `case Cancelled` (`sawc/std/channel.saw`),
   and the receive loop observes cancellation at its TOP, ahead of the queue
   read — the std.net park-loop position (design 102), which is also design 180
   unit 5's for the timer half. Ahead of the dequeue on purpose: a cancelled
   consumer stops instead of taking one more message, which K69 pins with a
   value left in the queue.
2. **The wake.** `__saw_exec_wake_flags` and the MT worker's under-the-lock
   promote scan both gained the io side's cancel clause. Design 230 refused it
   for a reason that was right at the time and is now the reason it is required:
   with no check in the loop, a woken cancelled waiter re-parked (a
   promote/resume/re-park spin); with the check, the wake TERMINATES the receive,
   and without the wake the check would never be reached. The comment at
   `__saw_exec_wake_flags` records the flip rather than deleting the reasoning.
   The quiescent deadlock walk reads the cancel word too, so a cancel landing
   during its double-check is never reported as a deadlock.
3. **The lowering.** The semantics live in `coro_transform.py`'s
   `_emit_recv_call`, not in the reference body — every call site is rewritten
   inline, and a `cancelled()` outside a coroutine frame is constant false. The
   loop top is now a cancel block that stores `Channel.__cancelled_result()`
   through the same store funnel as the received value, so the holder, the
   `return ch.receive()` tail and the frame teardown need no second shape: the
   two answers have one type. The reference body in `std/channel.saw` carries the
   matching check, as it carries the matching park.

**No parked-SENDER twin exists.** `Channel` is UNBOUNDED — `_enqueue` locks,
allocates a node, links and unlocks; there is no capacity to wait on and `send`
never suspends. `try_send` untouched (DQ-230b is still open and unchanged).

**Consumer sweep (obligation 2), and it caught a REAL flip the grep did not.**
The new enum case can only break an exhaustive `match` over `ChannelError`, and
the tree has none outside `std/channel.saw` — every in-tree reader uses
`case Err(_)` or `try!`. What the grep could not see is the ORDERING change:
`examples/channel_recv_cancel.saw` cancelled its worker BEFORE the group was
driven and then asserted that the worker still received the buffered value,
observing the cancel through a hand-written `cancelled()` check beside it. Under
the ruled loop-TOP position that first `receive()` answers `Err(Cancelled)` and
takes nothing, so the file's `try!` aborted — the suite was the census. Updated
to the new contract (the buffered 100 stays in the channel, `join()` returns 0),
keeping the thing it exists for: normal control flow out of a cancelled worker
and the `Res` deinit oracle firing exactly once before `join()` returns.

**FLAGGED for the user, since it is the one judgement call in the fix —
RESOLVED by the rider ruling above (cancel-beats-buffered stands).** The
ruling said "at its top", citing std.net, where the check genuinely precedes the
operation — a cancelled `accept()` refuses a connection that is already pending.
Implemented that way, so cancellation WINS over a queued message. The other
reading is check-before-PARK (drain what is queued, then report `Cancelled`),
which is what `examples/taskgroup_cancel_receive.saw`'s hand-rolled idiom does
and what the old `channel_recv_cancel.saw` asserted. Moving the check below the
`__try_receive_result` call in `_emit_recv_call` (and in the reference body) is
the whole of the change if drain-then-stop was meant; K69's `send(5)` row and
`channel_recv_cancel`'s expectation are the two that would flip back.

Tests: conformance row **K69**
(`examples/conformance/K69_cancel_reaches_a_parked_channel_receive.saw`, the
single-threaded cooperative engine plus the no-further-message ordering) and
`examples/channel_receive_cancel_mt.saw` (`threads: 2`, the worker's own promote
scan — the half that would have shown up only as a hang).
`examples/taskgroup_cancel_receive.saw` (the hand-rolled `try_receive` idiom,
which still works and is no longer the only cancellable spelling) and K63/K64/
K66/K67/K68/K47 all stay green. Docs: LANGUAGE_SPEC.md (the receive bullet and
the `close()` section's enum), README's "Channels Close Explicitly" and the
stdlib list, the saw-lang skill's channel gotcha. Original filing follows.

(original) `h.cancel()` on a task whose current suspension is a `receive()` never
reaches the task: the receive loop is `try_receive` + park and has no
`cancelled()` check, so the task waits for a value that will never arrive and
the group's `Deinit` waits for the task. Pre-230 the same program spun at 100%
of a core instead of parking, so nothing about the reachability changed — only
the CPU it costs.

Every other parking primitive in std observes cancellation: `std.net`'s
accept/read/write re-check `cancelled()` at their park-loop top and return
`Err(IoError)` (design 102), and design 180 unit 5 gave the timer half the same
promptness. The channel is the one park with no such path, and the sanctioned
workaround is to write the loop yourself with `try_receive`
(`examples/taskgroup_cancel_receive.saw` is the idiom).

Design 230 deliberately does NOT wake a cancelled channel waiter: with no
`cancelled()` check in the loop, the resume finds nothing and parks again, which
converts a quiet park into a promote/resume/re-park spin (`__saw_exec_wake_flags`
records the reasoning). The task is unreachable either way; this way it costs
nothing while it is.

WHAT IT NEEDS, and why it is a RULING rather than a fix: `receive()` returns
`Result<T, ChannelError>` since design 230, and the natural shape is a
`Cancelled` case beside `Closed` — but the brief ruled the enum's contents
(`Closed` now, `TimedOut` reserved) and a third case is a surface decision, not
an implementation one. The alternative reading is that cancellation is not an
error at all and the answer is a separate `receive_or_cancelled()`. Not decided
here.

## ~~DF-232b — `type` should be usable as an argument LABEL, a VARIABLE
## name and a FIELD name~~ — **FIXED Aug 17** (RULED Aug 17, user)

Found by M3 unit 1: the ruled `clock_get(type:)` label was unwritable
because `type` was a lexer keyword, so the unit shipped `kind:`.
`type` is now CONTEXTUAL, built the way this compiler already builds
contextual words rather than by a second mechanism: it is out of BOTH
keyword tables (`sawc/lexer.py` and `selfhost/lexer/src/lib.saw`, one
commit — the lexdiff/astdiff lanes compare them token for token), lexes
as IDENT, and the parser recognizes it through `at_type_alias_start()`
over `match_ident`, the same door `import`/`export`/`module`/`sync`/
`any`/`const` use. The read is `type` FOLLOWED BY AN IDENT; its
docstring names the three entry points (module-level dispatch, a trait
body, an extension body), and `_at_toplevel_start`/`_synchronize`
consult it so error recovery still sees an alias as a boundary.
Unambiguous because that two-token shape occurs nowhere else and `type`
never opens a statement — the hazard that keeps `lend` reserved.
CENSUS (the reason this was free): all 2240 tracked `.saw` files hold 84
`type` tokens, every one at an alias or associated-type head, so no
existing code changed meaning and nothing had to be renamed.
CORRECTION to the filing: it listed "statement head in a module and in a
block still parse as the alias declaration" as negative rows. Only the
MODULE one existed — a local `type X = Y` has never parsed, since no
statement form consumes it. It stays an error and now says so by name
instead of falling through to ``undefined variable `type` ``.
Tests: `examples/type_is_a_contextual_keyword.saw` (the matrix — four
negative alias rows, then field, parameter, argument label, struct
literal, `e.type`, `self.type`, `let`/`var` binding + assignment,
for-loop variable, `if let` binding, named-tuple label, closure
parameter, interpolation) and
`examples/type_alias_in_function_body_refused.saw`.
Also updated: LANGUAGE_SPEC's reserved-vs-contextual lists,
`tools/sawfuzz.py`'s KEYWORDS/CONTEXTUAL split, and the nvim syntax file
(which highlighted `type` unconditionally and so mis-coloured `e.type`).
DEFERRED, deliberately: the sos/ `clock_get(kind:)` API is NOT flipped to
the ruled `type:` here. A concurrent agent is restructuring sos/kernel,
and the flip is scheduled for after both branches land. The label is
declared at `sos/kernel/sysapi/src/lib.saw:540` (its docstring already
points here), with the kernel side at `sos/kernel/core/lib.saw:2079`,
labeled call sites in `sos/tests/{clock-basics,timer-deadlock,
timer-oneshot}/src/main.saw`, and prose in `sos/spec.md:1191` +
`designs/232-sos-m3-sketch.md:470`. [232, DF-232b]

## DF-229c — CLOSED (Aug 17): a `public(package)` name selected from
## INSIDE its own package now BINDS

**Landed.** The visibility relation is ONE predicate now,
`_visibility_relation_allows` (typechecker/core.py), whose docstring names its
two entry points (obligation 1): `_member_gate_allows`, which asks with the
module of the code being checked, and `check_module`'s selective-import arm,
which passes the IMPORTING module explicitly — the import list is processed
before `self.namespace` becomes this module's, so the ambient accessor would
have named the previous module. The arm's test is `_selection_visible` over
that predicate instead of `visibility == PUBLIC`, and `_module_selectable_names`
was moved onto the SAME predicate so the `available:` hint can never omit a
name the import would bind. Tests:
`examples/df229c_package_selection_binds.saw` (every category the funnel walks
— struct, enum, function, static, type alias — selected from a same-package
module and run) and `examples/df229c_parent_selection_error.saw` (the control:
`public(parent)` from a non-parent is still refused, `_vis_word` still prints
the visibility it found, and the hint's list is the predicate's own answer),
over the fixture `examples/modules/df229c_pkg.saw`;
`examples/df229a_private_selection_error.saw` (private refusal, unchanged) and
`examples/visibility_package_access.saw` (the qualified reach this makes the
selective form agree with) stay green. Spec: the Visibility section states that
a scoped name answers to every spelling its scope allows.

Noted while fixing, NOT fixed here (pre-existing, and outside the ruling): a
USER cross-package refusal is not constructible in-tree, because
`Namespace.package_root` is `()` for every sawc compile — nothing populates it
from the Blade manifest — so `check_visibility` takes its "no package root
defined, assume same package" branch and `public(package)` is effectively
`public` between user modules. The one rooted package is std (`("<std>",)`,
design 82), which declares no top-level `public(package)` name, so the
cross-package arm has no in-tree exercise on either side of this fix; it is
preserved by construction, since both gates now share one predicate and the
std rooting lives inside it. Worth a ruling if package walls are meant to be
real for user packages. [229, DF-229a]

