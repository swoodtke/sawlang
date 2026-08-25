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


## DF-232j — a `public import` RE-EXPORT WIDENS a `public(package)` symbol to
## the world: design 229's facade bypasses design 80's package tier (filed
## Aug 20, writing the pin the re-narrowing rider owed — the pin DISPROVED the
## property it was written to protect)
## — FIXED Aug 20 (branch df-232j, unit 1)

A facade module of a mapped package re-exports a sibling's package-private
symbol and PUBLISHES it. `pkgvis.secret` declares `public(package) func
pkg_secret`; `pkgvis`'s lib.saw says `public import pkgvis.secret.{pkg_secret}`;
an entry file OUTSIDE the package then calls `pkgvis.pkg_secret()` and it
compiles and runs, printing 7. Reaching the same symbol DIRECTLY
(`import pkgvis.secret.{pkg_secret}`) is correctly refused — so the tier works
everywhere except through the one construct designed to republish names.
SEVERITY: this is the tier's soundness, not a diagnostic wart. `public(package)`
means "siblings only"; one `public import` line anywhere in a package silently
converts that to "everyone", with no error, no warning and no test failing —
the failure mode is invisible by construction.
NOT EXPLOITED TODAY, by accident not design: kcore's facade names eleven
symbols and all eleven were promoted back to genuinely `public` by the Aug-20
re-narrowing, so none of its 108 `public(package)` names is re-exported. The
narrowing therefore STANDS. But the protection is one careless facade line from
gone, and nothing would catch it.
PIN: `examples/module_path_reexport_no_widen_error.saw`, XFAIL citing this DF,
EXPECT stating the intent (refusal naming the tier and the defining module).
Its fixture's `public import` is the widening attempt, deliberately.
NEIGHBOUR ALREADY PINNED: `export229_scoped_import_error.saw` covers
`public(package) import` being refused outright. That one HAS a diagnostic;
this one has none, which is why it went unnoticed.
MECHANISM (read Aug 20, lead sweep; both obligation-4 hypotheses were wrong —
the tier RIDES the symbol and dies at the DECISION): a re-exported symbol
keeps its `visibility` and `def_module` (symbols are shared by reference).
The defect is that design 80's relation has two callers of the one
implementation (`Namespace.check_visibility`) and only one is honest: the
typechecker's `_visibility_relation_allows` (core.py:1033) computes the
package root (std arm + DF-232f's mapped arm) before delegating, while the
qualified-reach path — `_resolve_parts.is_visible`, namespace.py:564-576 —
calls it raw, with `symbol_module=self.module_path` (the FOUND-IN module,
not `def_module`) and `package_root=self.package_root`, which is `()` for
every user namespace (nothing ever sets it), and an empty root means "assume
same package" (namespace.py:2727). So EVERY namespace-side visibility
decision lets `public(package)` through; the facade of the filing is
incidental — the DIRECT qualified reach widens too, no re-export needed.
Third wrongness, currently masked by the empty root: the module-member-access
sites hardcode `accessor_module=()` (expressions.py:6138), so a root fix
alone would REFUSE legitimate sibling qualified reach — the true accessor
must be threaded.
SWEEP (Aug 20; all shapes entry-OUTSIDE the mapped package; every row now a
committed pin, the fix's oracle):
- WIDENS direct qualified, no facade (`import pkgvis.secret`;
  `secret.pkg_secret()` printed 7) — pin `module_path_qualified_no_widen_error.saw`
- WIDENS selective facade, qualified reach — the filed symptom, pin
  `module_path_reexport_no_widen_error.saw`
- WIDENS two stacked selective facades — pin
  `module_path_reexport_twohop_no_widen_error.saw`
- WIDENS kind-general: static printed 9, struct constructed — pin
  `module_path_reexport_kinds_no_widen_error.saw`
- REFUSED entry selective through facade — the typechecker funnel runs;
  control pin `module_path_facade_selection_error.saw` (not XFAIL; wart: the
  diagnostic names the FACADE, not the defining module)
- REFUSED entry glob of facade — accidental (the glob-copy PUBLIC-only filter)
- REFUSED glob facade — accidental, same filter refuses the SIBLING → DF-232k
  (entry below); widen pin `module_path_glob_facade_no_widen_error.saw` stays
  XFAIL until BOTH land
- REFUSED whole-module facade chain — accidental: the re-exported qualifier is
  bound `Visibility.PRIVATE` (core.py:1484), value-position chain reach fails
  everywhere, public included → DF-232l (entry below); widen pin
  `module_path_whole_facade_no_widen_error.saw` stays XFAIL until BOTH land
- sibling direction keeps working (lib_answer 42, existing tests)
FIX SHAPE (dispatched Aug 20, branch df-232j): ONE funnel —
`Namespace.check_visibility` is already the shared implementation; make its
callers honest. Root computation (std + mapped arms) moves into the namespace
layer, `is_visible` judges `sym.def_module or self.module_path`, member-access
sites pass the real accessor, refusal diagnostic names the tier and the
defining module (the pins' EXPECT). W-rows flip to refusals, R-rows stay
refused, sibling + std cross-file + kcore/sos + bootstrap reaches stay green.
LANDED Aug 20 as dispatched, no deviation. `Namespace.visibility_relation_
allows` is the funnel (namespace.py) and carries BOTH package-root arms; the
typechecker's `_visibility_relation_allows` delegates and keeps only the
entry-point list, which now names the namespace-side qualified reach.
`Namespace.mapped_packages` is stamped on every module namespace by
`check_module` and inherited by `register_module_from_ast`;
`_resolve_parts.is_visible` judges `sym.def_module` (the tier RIDES the shared
symbol, so hop count cannot matter) and the chain recursion stops reading an
accessor of `()` — the ENTRY module — as "unknown, use my own path", which had
made every chain hop a same-module access. Every `resolve(..., check_
visibility=True)` site now passes `_accessor_vis_module()`. Refusals are
reported, not swallowed: `Namespace.resolve` takes an out-list of
`VisibilityRefusal`, and `TypeChecker._report_visibility_refusal` turns it into
the tier diagnostic at the four module member-access/call sites — a design-229
surface hint still WINS over it, since "the module merely imports this name" is
the more specific story. FLIPPED (XFAIL removed): the four W-row pins.
DIAGNOSTIC IMPROVEMENTS the fix pulled in, four existing tests re-pinned to the
better wording (refusal unchanged in every one): visibility_private_access_
error, visibility_parent_access_error, visibility_private_struct_error (which
had been calling a STRUCT a function) and reexport_private_module_error now
name the tier and the defining module instead of "has no symbol". CONSUMER
SWEEP: clean — full suite 2023 pass / 20 xfail and sos_runner 80 pass across
riscv32 + arm64 (kcore/imgformat/sosrt are the corpus's mapped packages). NOT
ONE in-tree site was newly refused, which is the re-narrowing's claim holding
up under a now-real gate. [232f, 229, design 80/82]

## DF-232k — a sibling GLOB import drops `public(package)` names: the
## glob-copy arm filters PUBLIC-only (filed Aug 20, the DF-232j sweep)
## — FIXED Aug 20 (branch df-232j, unit 2)

`import pkgvis.secret.*` written INSIDE the package does not bind the
sibling's `public(package)` names: the glob arm of `check_module`
(typechecker/core.py:2729-2759) tests `visibility == PUBLIC` where the
selective arm asks `_selection_visible` with the importer as accessor —
DF-229c fixed exactly this for the selective form; the glob arm kept the
pre-229c shape. Symptom: the aggregating facade itself fails to compile
(`undefined function pkg_secret`). Usability, not soundness — it REFUSES
valid reach. Fix: the glob arm asks the same relation; the outside-facing
direction (an outside glob keeps excluding package-tier names) falls out of
the accessor-aware predicate. PIN: `module_path_glob_facade_sibling.saw`
(XFAIL, EXPECT success 42). SCHEDULED (user, Aug 20): rides branch df-232j
as unit 2.
LANDED Aug 20 as filed: all five glob-copy loops now test `_selection_visible`
with the importer as accessor instead of `visibility == PUBLIC`, and the
`_glob_takes` closure carries both that and the design-229 surface test, so no
loop can drift from another. Both directions fell out of the one predicate with
no special case, as predicted. FLIPPED: `module_path_glob_facade_sibling.saw`
(42) and — with unit 1 — `module_path_glob_facade_no_widen_error.saw`, the
widen pin that had been masked by this defect. Nothing in-tree was newly
admitted or refused: suite 2025 pass / 18 xfail, sos_runner 80 pass both
arches. [232j sweep, 229c, design 80]

## DF-232l — whole-module `public import` re-exports NOTHING in value
## position: the qualifier is bound PRIVATE (filed Aug 20, the DF-232j sweep)
## — FIXED Aug 20 (branch df-232j, unit 3, after unit 1 as the ordering required)

Design 229's whole-module form re-exports its QUALIFIER — but
`_bind_module_qualifier` (typechecker/core.py:1482-1485) stamps every bound
qualifier `Visibility.PRIVATE` ("an import is never re-exported", a comment
design 229 superseded for the `public import` form). A chain reach in a VALUE
position (`facade.dep.leaf_make(...)`) fails with "module `facade` has no
symbol `dep`" for ordinary and mapped modules alike, public symbols included.
The suite never noticed: `export229_facade.saw` exercises the chain only in a
TYPE annotation (a path that checks no module visibility) plus the facade's
own public function. ORDERING: fix AFTER (or with) DF-232j — flipping the
qualifier re-exported while `_resolve_parts` still decides package visibility
with an empty root would open DF-232j's hole through the whole-module shape,
the one form the sweep could not exercise end to end. PIN:
`export229_whole_chain_call.saw` (XFAIL, EXPECT success 2). SCHEDULED (user,
Aug 20): rides branch df-232j as unit 3, strictly after unit 1.
LANDED Aug 20 as filed, and in the required order. `_bind_module_qualifier`
stamps the qualifier PUBLIC exactly when `_qualifier_is_reexported(imp)` — the
new per-FORM predicate: `public import` AND no selection list. The whole-module
form binds no bare name, so the qualifier IS its product; the selective form's
qualifier stays PRIVATE even under `public import` (design 229's ruling —
re-exporting it beside the named symbols would hand on the whole module), and
the glob form binds none. The std whole-module arm now reads the same predicate
for its `note_private_import` half, so the export gate and the qualifier's
visibility cannot drift apart. FLIPPED: `export229_whole_chain_call.saw` (2)
and — with unit 1 — `module_path_whole_facade_no_widen_error.saw`; a probe of
the direction the fix ADMITS (`pkgvis.secret.secret_is_reachable()` through a
mapped package's `public import` chain) prints 1 while the `public(package)`
sibling beside it is refused on the tier, which is the pairing the ordering
existed to guarantee. Suite 2027 pass / 16 xfail, sos_runner 80 pass both
arches. [232j sweep, 229]

## DF-232m — the battery's `irdet` lane VERIFIED NOTHING from a worktree: it
## builds irdetbin with $PY and then invokes it with no `--python` (filed
## Aug 20, hit by the DF-232j terminal battery) — FIXED Aug 20 (branch df-232j)

MECHANISM (`tools/battery.sh:129-137`): `run_irdet` compiles
`devtools/irdet/src/main.saw` with `"$PY"` — correct — and then runs
`./.build/irdetbin --plan --all` and `./.build/irdetbin --all --jsonl` with no
interpreter argument. Building irdetbin says nothing about the interpreter it
DRIVES: irdetbin shells out to sawc, and its `--python` default is bare
`python3`. On a machine whose `python3` cannot import llvmlite that compiles
nothing. `SAW_PYTHON` does not rescue it — the variable reaches `$PY`, which is
never passed on — and from a WORKTREE there is no `./.venv` for the fallback to
find either, which is precisely the configuration CLAUDE.md prescribes for
agent work.
BLAST RADIUS: every worktree-run battery's irdet lane has verified NOTHING
since the lane existed. That is the exact silent-lane failure design 192 unit 5
tracked the battery to prevent — a lane quietly going missing — reappearing
INSIDE the tracked battery rather than around it. It is visible at all only
because design 220/221 made irdet self-report: the lane prints
`NOTHING WAS CHECKED -- every candidate failed to compile` and `irdet_verdict`
fails on a run that verified nothing rather than reading zero mismatches as
green. Without that self-report this would have been a clean pass forever.
FIX: `--python "$PY"` on BOTH invocations, nothing else.
EVIDENCE: the DF-232j terminal battery failed this lane with
`1359 record(s) — 0 ok, 1359 skipped, 0 MISMATCH, 0 VIOLATED INVARIANT`; the
lane re-run verbatim with `--python` gave `1266 ok, 93 skipped, 0 MISMATCH,
0 VIOLATED INVARIANT` (1255 of 1266 reusing the suite manifest), GATE=0 — so
the oracle itself was green over the whole corpus and only the plumbing was
broken. Re-proved after the fix by
`SAW_PYTHON=<main>/.venv/bin/python tools/battery.sh irdet` from the worktree.
[232j, design 192 u5, 220, 221 D]


## Pipe rename — SOS `Channel` -> `Pipe`, and the request/reply handle names
## (RATIFIED by user, Aug 20; LANDED same day, lead-direct, in parallel with
## the design-236 dispatch — the entry authorized "its own small unit any
## time before M4")

The IPC object of sos/spec.md §2.1 collides by name with std's `Channel`
while sharing none of its semantics (std: buffered in-process queue,
any-holder close, fire-and-forget; sos: synchronous rendezvous, one staged
message, request/reply primitive, fire-and-forget excluded). Ruled renames:

- `Channel` -> `Pipe`; `ChannelRight` -> `PipeRight`; `ChannelHandle` ->
  `PipeHandle` (abi reservations only — nothing is built, M4).
- `RequestHandle` -> `PipeRequestHandle`; `ReplyHandle` -> `PipeReplyHandle`.
  The user kept the request/reply pair over role names (Requester/Responder
  were considered); the Pipe prefix follows the abi's object-kind convention
  (`SystemHandle`, `PipeHandle`) and reserves bare Request/Reply for a future
  protocol layer's own message types.

Rationale for Pipe over Endpoint/Queue: the planned Plan 9-like namespace
(paths like /dev/uart0 resolve to a server-owned object speaking a protocol)
is the named-pipe model nearly verbatim — server registers at a path, client
opens by path, framed messages, request/reply as a transaction
(TransactNamedPipe lineage). Queue was REJECTED: it names the one property
the design deliberately lacks (there is no queue — one message, synchronous).

Record in the spec when the rename lands:
- `Pipe` names the PER-CLIENT connection object (today's §2.1 object); the
  path-attached acceptor the namespace will need is a separate later object,
  named in the namespace design — do not spend `Pipe` on it.
- The client send API (RATIFIED Aug 20, superseding the earlier `transact`
  idea — name rejected by user): ONE `send` name, overloaded by the
  presence of `timeout:` — a runtime flag cannot change a return type, so
  blocking-ness is an overload distinction, never a `Bool` parameter.
  `pipe.send(msg) -> Result<PipeReply, PipeError>` suspends (cooperatively)
  until the reply; `pipe.send(msg, timeout: Duration) ->
  Result<PipeReply, PipeSendError>` where `case TimedOut(pending:
  PipeReplyHandle)` carries the still-live claim in the error payload — the
  pending state is representable exactly and only in the outcome where it
  exists (three-tier error doctrine). `PipeReply` is the RESOLVED reply
  object (data + transferred handles); `PipeReplyHandle` resolves to one.
  A two-state maybe-pending return was REJECTED: it hands every blocking
  caller an impossible state to match on and reimports the poll-a-future
  shape colorless concurrency removes.
- The split-phase form (send now, wait later; returns the bare
  `PipeReplyHandle`) is NOT redundant with the timeout overload — it is
  what a client attaches to a Waiter (§2.2) to multiplex outstanding
  requests. Its method name is M4-brief business.
- ABANDONED-REQUEST semantics (RATIFIED Aug 20; a client drop and a client
  crash are the same event to the kernel): `reply()` to an abandoned
  request returns `Err(PeerClosed)`, never a silent success (std Channel's
  close precedent — ignorable with `let _ =`); the obligation is
  discharged and attached handles closed either way; the
  `PipeRequestHandle` is waitable for "abandoned" (opt-in early notice —
  the user specifically wants this for long-running requests; state on the
  kernel object, so it travels with a delegated handle);
  drop-of-`PipeReplyHandle` is the cancellation primitive (timeout
  overload -> drop pending = cancel, no cancel() verb, deterministic
  timing via deterministic destruction).
- The TELL idiom (RATIFIED Aug 20, amending the earlier anti-pattern
  framing): send-then-drop is the sanctioned "tell the server something an
  Event cannot carry" pattern — client drops the reply handle at once, the
  server discharges with `let _ = request.reply()`. It composes entirely
  from the ruled pieces; no new mechanism. Two clarifications recorded
  with it: (1) the idiom is SPELLED on the split-phase form (`send`
  suspends until the reply, so `let _ = pipe.send(msg)` waits-and-ignores;
  tell-without-waiting drops the handle the split-phase form returns —
  which promotes that method's name to user-facing idiom; leading
  candidate `post`, M4 brief decides); (2) ABANDONMENT IS INFORMATION,
  NOT AN IMPERATIVE — whether it cancels is the protocol's per-request-
  type decision (a tell-style message ignores the signal; a cancellable
  read honors it), which sits naturally with server-owned protocols in
  the Plan 9-style namespace plan. Event remains the payload-free
  notification mechanism.

Scope: sos/spec.md (14 Channel mentions + the handle names), the
RequestHandle/ReplyHandle mentions across sos/ + designs/232-sos-m3-sketch.md
(17 lines), the M4-seeds backlog line (updated with this filing). No code
anywhere names these yet (verified Aug 20: zero hits in kernel/abi +
sysapi sources).
LANDED Aug 20 (lead-direct, prose only): the mechanical rename ran
compounds-first across spec/sketch plus the NINE comment-only .saw mentions
(dispatch.saw, process.saw, abi/lib.saw), then a second pass caught the
lowercase prose uses — protecting Saw's own task-level channels, the
"Zircon channel-call" lineage citation, std.channel, and diag.saw's generic
"failure channel". Hand-written on top: §2.1's AMENDED Aug 20 block
transcribing the whole ratified record (rename rationale + per-client
note, the overloaded send API with TimedOut(pending:), abandoned-request
semantics, drop-as-cancellation, abandonment-is-information, the tell
idiom); the fire-and-forget bullet amended to point at it; the §2.2
waitables row gains PipeRequestHandle (abandoned); the Jul-31 `call` verb
bullet amended (superseded by the suspending `send` overload); the object
table row notes the rename. Gate: sos_runner 80/80 both arches (sos-only
change). Handed to the M4 brief: the split-phase method name (leading
candidate `post`).


## DF-239a — a call on a trait-BOUNDED type parameter never checked its
## arguments (filed Aug 20; CLOSED Aug 20, design 239 unit 1a)

**Status: FIXED**, and the filing's diagnosis was wrong in a way worth
keeping. Substitution never dropped the `&`: both faces were probed to WORK
under the spelling Saw actually has, and `Bag_doubled` really does take
`%Bag*`. What the pins hit was the MISSING BORROW SIGIL — Saw has no implicit
re-borrow at any type, so `a.merge(b)` against `func merge(&self, other:
&Self)` is a plain missing `&`, and the DEFAULT-BODY face reproduces
identically for a plain `&Bag` parameter with no `Self` anywhere.

The real mechanism: `_check_type_param_method_call`
(typechecker/expressions.py) is the ONE call form in the language with no
argument-compatibility loop — it checks argument COUNT and defers deep typing
on purpose (a trait signature may name associated types, abstract in the
generic body). Anything it defers reaches codegen, where a mismatch is an ICE
and not a diagnostic. Probed class, all three ICEing before the fix: a
missing borrow at a `&Self` parameter (`%"Bag"* != %"Bag"`), a surplus borrow
at a by-value one (`%"Bag" != %"Bag"*`), and a `String` handed to a fully
concrete `Int` parameter (`i64 != i8*`). Sibling call form CLEAN: the
existential path (`_check_existential_method_call`) checks argument types
outright, because `Self` cannot appear in an object-safe trait.

FIXED for the reference-spelling axis, which is a SPELLING question rather
than a typing one and therefore decidable whatever `Self` denotes — the
declared type's own kind answers it, with no substitution, no resolution and
no prelude gate. `_check_bound_arg_reference_spelling` carries the four-row
matrix; the other two rows were already `_check_reference_sigils`', reached
through `_check_call_exclusivity`. The DEEP-typing axis stays open as
**DF-239b** below. The erasure diagnostic's wording wart went with it: a
`&Self` parameter is refused as `takes parameter `other` of type `&Self` — a
`Self`-typed parameter is not object-safe, by reference or by value`, which
is both what was written and why.

PINS, all passing: `trait_self_ref_param_generic_call.saw` and
`_default_body.saw` (the capability, correctly spelled — XFAIL markers
removed), `errors/generic_bound_call_borrow_spelling.saw` (both new
diagnostic rows), and the four controls `_direct_call.saw`,
`trait_self_optional_bound_call.saw`, `trait_self_byval_param_faces.saw`,
`_not_erasable_error.saw`. [239, 216b, 106]


## Design 235 — the position-matrix ledgers (RATIFIED Aug 17; BUILT Aug 20,
## branch `design-235`; INTEGRATED Aug 20 — fast-forward, the exact tree the
## terminal gate blessed, so no re-gate owed)

designs/235-position-matrices.md is the plan of record: two standing corpus
ledgers on the conformance/ template — examples/coercion/ (adoption grid +
qualified-name-as-target grid) and examples/modules/ (import-forms×positions,
visibility, graph shapes) — with INDEX.md per ledger, cite-don't-duplicate,
N/A reasons in place, and every red cell filed as a DF + cited XFAIL pin, so
the family's xfail set becomes an ENUMERATION's red cells, not the trail of
what we stepped on. No-guessing rule: undetermined cells are OPEN rows for
ruling, never invented EXPECTs. Sonnet-class dispatch (user ruling — the
brief fixes the grids and authorities; the agent transcribes). Seeds: the
DF-232a/226d/e/232c pins + the kcore unit-0 probes. [235]

LANDING NOTE (Aug 20). Unit 1 (`examples/coercion/`) is two commits, one per
grid, both suite-gated. Unit 2 landed as `examples/module_matrix/`, NOT
`examples/modules/` as the brief's own prose says — `test_runner.py`'s
`discover_tests` hard-codes `skip_dirs = {'modules'}` and excludes ANY path
component named `modules` at any depth, corpus-wide, so a literal
`examples/modules/` ledger's own test files would never have run (the name
was already taken as the corpus-wide cross-module fixture directory every
OTHER test's `import modules.X` reaches). Flagged rather than silently
substituted: this is a structural/tooling correction, not a judgment call
under the no-guessing rule, and doesn't change what the grids test. Unit 2
is three commits, one per grid, each suite-gated.

Every cell in every grid was determined by DIRECT COMPILE/RUN EVIDENCE —
zero invented EXPECTs, zero OPEN rows in either ledger. Probing surfaced
findings well beyond the seeded ones:

- **DF-235a/b** (new, filed by unit 1) — the array-literal/coercion probing
  found `_apply_literal_expected_type` has no case for a general constant
  EXPRESSION (a folded shift/arithmetic `BinaryOp`, as opposed to a bare
  `IntLiteral`), so a const-expression source silently skips design 87's
  adoption+range-check funnel almost everywhere it's used — an
  `insert_value` codegen ICE where a downstream path assumed the width was
  reached (DF-235a: a mixed array literal, a Result payload slot), or a
  silent narrow truncation / silent wide mis-storage / spurious refusal
  with NO error at all otherwise (DF-235b: most of the rest of grid 1's
  position list). Only the enum raw value (its own dedicated fold+check
  pipeline) and the Result ambiguous-refusal row are unaffected — confirmed
  correct, not assumed.
- **DF-232d, corrected** (grid 2, unit 1) — the finding's original matrix
  claimed the "writes"/"refs" rows for `mod.STATIC` work; direct compile
  evidence (plain relative import AND `--module-path` alike) found only a
  plain READ actually does — every write/reference shape through a
  qualifier ICEs at codegen. Corrected in place per obligation 4, not
  re-filed.
- **DF-232e, DF-232n** (unit 2) — both already filed, neither previously
  pinned in `examples/`; this brief gave each its first fixture (DF-232e's
  3-cycle confirmed as the same mechanism at a longer length, not assumed;
  DF-232n's minimal two-file repro alongside the audit's larger
  `libs/toml/` evidence).

Two structural findings, confirmed by direct compile rather than assumed
from the grammar prose: an extension receiver and a match pattern BOTH
require a bare name at the parser level, so they are grammar-level N/A for
the qualified and `as`-renamed import forms specifically (not a gap either
form's probing could close).

Cell counts and every red-cell pin are recorded in
`examples/coercion/INDEX.md` and `examples/module_matrix/INDEX.md`, not
restated here. Terminal gate (`suite lexdiff astdiff irdet`) run before
close-out; see the commit log on `design-235` for the per-grid suite gates.

## Design 236 — `static` is REQUIRED on static methods (BUILT Aug 20, branch
## `design-236`; ratified Aug 18, user: "no inference")

designs/236-static-keyword.md is the plan of record: a self-less non-init
extension `func` is a declaration-site error with the two-way fixit (add a
receiver / write `static func`); `static` with a receiver is the mirror
error; init exempt; trait requirements spell it and conformance kinds must
agree. Earned by V39 (forgot-`&self` silently became a static). Migration
is compiler-driven across std/blade/libs/sos/devtools/examples — each
V39-alike the sweep surfaces is a bug the migration fixes. Runs BEFORE 235
so the matrices enumerate the ruled grammar. [236]

LANDING NOTE (Aug 20). Six units, each gated before its commit; the brief's
unit order was inverted at the front because it could not be green as
written — enforcing the keyword before migrating std means nothing in the
tree compiles, so unit 1 lands the grammar PERMISSIVELY, units 2-4 migrate
region by region, and unit 5 turns the errors on with the matrix.

1. Grammar. `_parse_static_modifier` on two entry points (`parse_method`,
   `parse_trait_method`) — the only two places a method-shaped declaration
   is parsed. `public static func` is the order. `Method.declared_static` is
   what the author wrote; `is_static` stays the derived fact downstream
   reads. Gate: suite + sos GREEN.
2. Migration, sawc/std + builtin.saw — 50 declarations, plus
   `Deserialize.deserialize`, the tree's one static trait requirement.
   No V39-alike. Gate: suite + sos GREEN.
3. Migration, blade/ + libs/ — 5 declarations, AND THE ONE V39-ALIKE:
   `blade/src/builder.saw:565` called `self.layout.clean_all()`, an instance
   spelling of a receiver-less method, one line below the genuine
   `self.layout.clean()`. `clean_all` removes the whole `.build/` root
   through a free `build_root()` and never touches the receiver, so it is
   static and the call is now `BuildLayout.clean_all()`. Same behaviour
   either way, which is why nothing caught it. Gate: suite + bootstrap + sos
   GREEN (bootstrap is the only lane that runs blade/tests + libs/*/tests).
4. Migration, examples/ — 63 declarations, plus a comment sweep (several
   tests described staticness as "no `self` parameter", which is now the
   refused shape). `generic_static_type_arg_inference.saw` gains the keyword
   and STAYS XFAIL on DF-216c, its comment saying why. Gate: suite + sos
   GREEN. That closes the corpus: sos/, devtools/ and selfhost/ carried NO
   self-less extension methods, established by a parser census rather than a
   grep.
5. Enforcement. The three refusals through `_check_static_declaration`
   (docstring names its entries, obligation 1); conformance kind agreement
   in `_check_trait_conformance`, both directions; `--emit-docs` gains a
   `static` field and spells the keyword in `signature`, schema 2 -> 3 on
   design 144's precedent. Two synthesis sites corrected to carry the
   requirement's own kind — `_synthesize_trait_defaults` hardcoded
   `is_static=False`, which would have made a static requirement's default
   body claim a receiver it has no parameter for. Tests: nine
   `examples/errors/static236_*` (matrix error rows) + two positive pins
   (`static236_declared_static`, `static236_module_level_funcs_untouched` —
   the negative half, `@export`ed C-ABI seam included) + a docs golden.
   Gate: suite + sos GREEN.
6. Docs (design 125): LANGUAGE_SPEC's Type Extensions gains a "Static
   methods" section, Traits gains the static-requirement + kind-agreement
   rule, the serde trait block and the enum example spell the keyword;
   README's quick example and a fourth "smaller rule"; the saw-lang skill's
   cheat sheet and its DF-217q gotcha.

NOT DONE, deliberately: no `examples/conformance/` rows. The suite's
families are runtime soundness guarantees (mutability, exclusivity, moves,
divergence, …) and this rule is a declaration-shape rule that adds no
family; the position matrix lives in `examples/errors/static236_*` where
the brief put it.

Terminal gate (compiler branch): the FULL battery, 20 of 20 stages GREEN in
2899s — suite, icebreadcrumb, lexdiff, astdiff, astgraft, forgetgate,
ircontract, preludegate, stdtypes, abidoc, bttable, fuzz, corodiff, bench,
selfhostlex, reemit, irdet (`--all`), gmgate, bootstrap, sos.

- **DF-236a (CLOSED Aug 20, `df-batch-232n` unit 2; filed by 236's migration,
  the filing text kept below as the record) — a static method
  reached through a FIELD-ACCESS receiver is not refused; DF-217q's
  call-site check has a position gap.** MECHANISM (obligation 4):
  `_check_method_call`'s `isinstance(expr.object, MemberAccess)` branch
  (`typechecker/expressions.py`, the `module.Struct.method()` route) decides on
  the member access's TYPE — "this resolves to a struct that has a static of
  this name" — which is equally true of a member access that NAMES the type
  and one that evaluates to a VALUE of it. So `h.inner.solo(3)` is routed as
  though `h.inner` were the type: the receiver is dropped and the arguments
  shift by one. Nullary → the call silently succeeds; arity ≥ 1 → codegen ICE
  (`Type of #1 arg mismatch: i64 != %"Inner"`). SWEEP (compile evidence, all
  six probed): a plain local, `self`, a call result, a tuple element, a
  `Vector` element and a field at ENUM type all reach the DF-217q refusal
  cleanly — the gap is the field access at STRUCT type and nothing else, since
  it is the only spelling that enters that branch. Found in the wild exactly
  once: blade's `self.layout.clean_all()`, fixed at the call site by 236's
  region-2 commit; a corpus-wide AST hunt for the shape turned up no other.
  PIN: `examples/static_method_through_field_receiver.saw` (XFAIL). The fix is
  DF-217q's mechanism, not 236's rule — it needs the checker to distinguish a
  member access that names a TYPE from one that yields a VALUE, which is a
  ruling about that branch. [236, 217q]
  CLOSED Aug 20 (branch `df-batch-232n`, unit 2). The distinction is now a
  DECLARED stamp: `MemberAccess.names_type`, set by `_check_member_access` at
  every point it resolves a member access to a type SYMBOL (struct and enum, in
  both the chained-module and the qualifier arm), read by the branches that need
  a type rather than a value. Codegen had been asking the same question all
  along through `resolved_struct_name`, which is why the arity-1 face surfaced
  there. THE SWEEP FOUND TWO SIBLINGS, both the same mechanism and both SILENT
  wrong answers rather than errors: `_check_method_call`'s ENUM arm
  (module-qualified variant construction) took `h.c.Custom(r: 3)` and BUILT a
  fresh `Color`, discarding the receiver — probed, compiled and ran, printing
  `custom 3`; `_check_member_access`'s ENUM arm did the same for the
  payload-less read `h.c.Red`. All three arms are gated on the one stamp now.
  Two diagnostics came with them, on DF-217q's model: a variant named through a
  value reports ``is a variant of enum `Color` and cannot be constructed /
  reached through a value`` with the type spelling, instead of "has no method"
  / "cannot access member of non-struct type". PINS:
  `examples/static_method_through_field_receiver.saw` (XFAIL REMOVED, and the
  arity-1 face added beside the nullary one — they failed differently) +
  `examples/enum_variant_through_field_receiver_error.saw` (both enum faces).
  Docs: LANGUAGE_SPEC's static-method section and the saw-lang skill's DF-217q
  gotcha. Gate: full suite 2055 passed / 16 xfailed, sos_runner 80/80 across
  riscv32 + arm64.

## Design 237 — the ANF-hoist funnel (LANDED Aug 21, branch `design-237`;
## ratified Aug 18. USER INSTRUCTION Aug 21, carried over from its QUEUE line:
## the session STOPS after integrating this one)

designs/237-anf-hoist-funnel.md is the plan of record and carries the landing
section: the census, the four real gaps, the units as built, the tests and the
consumer sweep. Summary: the hoist's statement entries are one TABLE
(`_ANF_STMT_ENTRIES`), the child-position funnel gained the Result wrap family
and a docstring naming its entries, and every substitution the transform makes
into a position an earlier pass answered goes through `_substitute`, which
moves the call-site auto-wrap marks exactly once.

CLOSED by it: DF-217g (DestructuringLet — the one missing leaf statement
class), the return-under-Result-auto-wrap refusal (the missing NODE classes),
DF-224c and a `Result` twin found beside it (the dropped position mark, an ICE
in a driven body), DF-218n (drive site in a suspending body — the user's Aug-15
CLEAN REFUSAL ruling, with the teaching diagnostic). Ledger: the DF-217g row
and the STALE DF-217f row both retired from `tools/corodiff_known.txt`.

The census RE-DATED the brief's own list: design 224 (Aug 15) had already
closed the whole ICE family (if/while conditions, `&&`/`||` LHS, for-range
bounds, ctor-argument scrutinees) and three of the five bogus refusals (`??`
LHS, `?.` head, compound-assign RHS), and DF-217h's double-free had been closed
by design 218 stage 2. DF-218e EXITED the brief on its unit-1 mechanism check
(entry below, under design 218). OUT as written: DF-217p / DF-217m-coro deinit
TIMING. [237, 217, 218, 224]

## DF-235a — a constant EXPRESSION element/payload ICEs at codegen: a plain
## array literal (mixed with an adopted sibling) and a `Result` payload slot
## both `insert_value`-crash (filed Aug 20, design 235's coercion grid)
## — CLOSED Aug 21, design 240 items 1-2 (branch `design-240`)

Found probing grid 1's "const expression" column (design 185's folded
shift/arithmetic/bitwise family — `(1 << 3) | (1 << 4)`) against the
adoption position matrix.

MECHANISM (obligation 4): `_apply_literal_expected_type`
(sawc/typechecker/expressions.py:5174), the ONE funnel that pushes a
resolved expected type onto a literal-shaped value BEFORE it is checked and
range-checks an integer literal there, dispatches on the value's AST NODE
SHAPE — `IntLiteral`, unary-minus-of-literal, the if/match/block
"transparent" wrappers, a nested Tuple/Array/Map/Set literal, `None`, a
FuncPointer-shaped closure/name. A general `BinaryOp` (what a folded const
expression like a shift or an `|` actually is, at the AST level before
folding) matches NONE of these cases, so it is never stamped with an
expected type and is checked as an ordinary expression with no context —
which resolves it to platform `Int`, same as a bare `1 << 8` written with no
annotation in sight at all.

TWO CRASH-SHAPED SYMPTOMS, downstream of positions whose codegen assumes
the checked/declared width was actually reached:

1. A PLAIN (non-repeat) array literal: `_generate_array_literal`
   (sawc/codegen/collections.py:159-161) derives the array's LLVM element
   type from ELEMENT 0's own codegen'd type (`elem_type =
   element_values[0].type`) rather than from the array's declared Saw type,
   then `insert_value`s every element into that type. An element that DID
   adopt (a bare literal, stamped by the funnel's `IntLiteral` case) and one
   that did NOT (a const expression, left at platform width) disagree, and
   `insert_value` throws in EITHER order:
   ```
   let a: [UInt32; 2] = [0, (1 << 3) | (1 << 4)]
   // internal compiler error (ArrayLiteral): Can only insert i64 at [1] in
   // [2 x i64]: got i32
   let a: [UInt32; 2] = [(1 << 3) | (1 << 4), 0]
   // internal compiler error (ArrayLiteral): Can only insert i32 at [1] in
   // [2 x i32]: got i64
   ```
2. A `Result` payload slot: `return 1 << 20` at `-> Result<UInt16, Bad>`
   throws the same `insert_value`-shaped crash in `ResultOkWrap` codegen
   (`Can only insert i16 at [0] in {i16}: got i64`) — the wrap assumes the
   payload was adopted to `UInt16` and instead receives platform `Int`.

SWEEP (obligation 4, compile evidence — see DF-235b for the full position
census): `Vector<UInt32>` and `(UInt32, UInt32)` tuple literals, given the
SAME mixed elements, both compile and print correctly — Vector builds via
per-element `push`, Tuple addresses each slot by its own declared type,
neither deriving from element 0's codegen'd type. `_check_repeat_literal`'s
`[v; N]` does not ICE either (it silently mis-stores instead — DF-235b).
This finding is the ICE-shaped half of the funnel gap; the silent half
(no ICE, but no range check and the wrong effective width) is DF-235b,
same root cause, most of the rest of the position matrix.

PINS: `examples/coercion/array_literal_const_element_ice.saw`,
`examples/coercion/result_slot_const_expression_ice.saw` (both XFAIL).
[235, 87, 195]

LANDED Aug 21 (design 240 items 1-2, one commit — the two findings are one
funnel gap and one arm closes both). `_apply_literal_expected_type` gained
case (2b): a `BinaryOp` (or a `~`/negated `UnaryOp`, through case (2)) at a
FIXED-WIDTH expectation is folded by the one `const_eval` and range-checked
against the slot with the same words case (1) gives a bare literal, then
stamped `const_folded_value` + the slot's type; `_check_binary_op` /
`_check_unary_op` answer from the stamp and codegen emits the constant AT
that width. Every position the funnel serves was fixed by the one arm — no
per-position patch — and the two ICEs went with it (the array's LLVM element
type now agrees because both elements adopt; the Result wrap receives the
payload width it assumed). Pins renamed for the behaviour they now pin and
un-XFAIL'd: `array_literal_const_element_mixed.saw`,
`array_literal_const_element_range_check.saw`,
`result_slot_const_expression.saw`. Ledger rows in
`examples/coercion/INDEX.md` flipped (20 S3 cells).
TWO NOTES for the record. (1) The stamp pair, not `resolved_type`, is what
the checker reads: the place lowering UNCHECKS the tree between the two
front-half passes, so `resolved_type` is gone by the second one — reading it
made an already-folded `-(1 << 7)` re-descend into its operand and refuse
`128` on pass two. (2) The fold is design 185's SIGNED platform-`Int`
domain, so `1 << 63` at a `UInt64` slot is now a REFUSAL where it used to
reinterpret the bit pattern silently — consistent with the refusal
`(1 << 63) as UInt64` already gave and with a bare
`-9223372036854775808` there. Corpus swept for the shape before landing
(`~0`, `1 << 63`, `1 << 31`): every occurrence is a `static_assert`, an array
length or a platform-`Int` slot, none at a fixed-width unsigned one, and the
full suite is green. Pinned by `const_expression_signed_domain_error.saw`
beside `const_expression_unary_adopts.saw`.
ONE BOUNDARY, deliberately not widened: the arm folds what `const_eval`
answers from the AST it is handed, so a const expression naming a module
`static` or a raw-backed enum case (`1 << PAGE_SHIFT`, `Perm.Read |
Perm.Write`) still reaches the slot un-adopted. Stamping those names here
would need `_stamp_const_names`, which also stamps enum raw values — and
design 185 unit 4 rules that a flag-enum read is a constant only IN a const
position. Widening it is a RULING, not a fix; filed as DF-240a below.

## DF-235b — a constant EXPRESSION source is never range-checked at MOST
## fixed-width positions — silent truncation, silent over-width storage, or
## (one position) a spurious refusal of an otherwise-legal value (filed
## Aug 20, design 235's coercion grid; same funnel gap as DF-235a)
## — CLOSED Aug 21, design 240 items 1-2 (branch `design-240`)

The SILENT half of DF-235a's mechanism: everywhere DF-235a's missing
`BinaryOp` case in `_apply_literal_expected_type` does NOT reach codegen as
an outright `insert_value` crash, it instead reaches it as a value nobody
range-checked, and — depending on what that position's OWN codegen does
with an un-adopted platform-`Int` value — the program either keeps running
at the WRONG effective width or refuses a value it should accept.

MATRIX (obligation 4, compile evidence — `1 << 20` against a `UInt16`
target throughout, which is 1048576, out of `UInt16`'s 0..=65535 range):

  SILENTLY TRUNCATES to the declared narrower width, no range check, no
  error — the position's codegen narrows an un-adopted platform-`Int` value
  at the store/pass/return site (same shape DF-232a's own "folded" row
  named in passing for assignment, without flagging the missing check —
  extended here rather than re-filed): annotated `let`, `static`
  initializer, struct-literal field, positional argument, `return`, default
  parameter value, value `if` arm, `match` arm, plain assignment target
  (DF-232a's `v = 2 + 3` row). Every one of these prints `0` for `1 << 20`
  at `UInt16` — an out-of-range value silently becomes a DIFFERENT
  in-range one instead of a compile error.

  SILENTLY WIDENS the actual storage past the declared type instead —
  prints the untruncated `1048576`, meaning the value (and, for the
  container cases, its backing storage) is carried at platform width
  throughout despite the DECLARED Saw type claiming `UInt16`: the repeat
  literal's value (`[1 << 20; 2]`), an Optional payload slot
  (`let o: UInt16? = 1 << 20`), the `??` operand
  (`absent ?? (1 << 20)`), and a UNIFORM plain array literal whose elements
  are ALL const expressions (`[1 << 3, 1 << 4]` — no `insert_value`
  conflict since every element agrees on the SAME wrong width, but
  `sizeof`/layout downstream would disagree with the declared `[UInt32; N]`
  wherever this array's storage crosses an ABI boundary).

  REFUSES a value it should accept — the one position with no leniency
  fallback: compound-assign's RHS (`acc += (1 << 2) + 4` for `acc: Int16`)
  is rejected outright by design 195's operand-agreement check (`Int16` vs
  the un-adopted `Int`), where the SAME position accepts a bare literal RHS
  fine. Safe (no silent corruption), but inconsistent with every other
  position in this matrix and with a literal in the same slot.

  CORRECT (control): the enum raw value (DF-232c) properly range-checks a
  folded const expression against its declared backing
  (`case A = 1 << 20` on a `UInt8` backing refuses by name, "raw value
  1048576 ... is out of range"), because `_fold_enum_raw_values` is a
  SEPARATE, dedicated fold-and-range-check pipeline that never routes
  through `_apply_literal_expected_type` at all — the one place in the
  matrix the funnel gap does not reach.

Not independently probed (same funnel, not yet exercised with an
out-of-range value): a struct-literal field via a field-through-element
target, a Result payload slot's OWN range check (its symptom is DF-235a's
ICE, so a range question does not apply the same way), `&var` reference
targets. Presumed the same family by the shared funnel per obligation 4,
not asserted without evidence.

PINS: `examples/coercion/const_expression_range_unchecked_narrow.saw`,
`examples/coercion/const_expression_range_unchecked_wide.saw`,
`examples/coercion/compound_assign_const_expression_refused.saw` (all
XFAIL). [235, 87, 195, 232a, 232c]

LANDED Aug 21 with DF-235a — one commit, one funnel arm; the mechanism and
the two notes worth keeping are in DF-235a's landing paragraph above. Pins
renamed for the behaviour they now pin and un-XFAIL'd:
`const_expression_range_checked_narrow.saw`,
`const_expression_range_checked_wide.saw`,
`compound_assign_const_expression.saw`. Two new files cover the shapes the
fix newly determines: `const_expression_unary_adopts.saw` (a negated const
expression and a `~` mask) and `const_expression_signed_domain_error.saw`.
The named-`static` leaf is the one shape left un-adopted — DF-240a.

## DF-232n — `public(package)` is NOT enforced across a RELATIVE-PATH import:
## the empty-root fail-open arm survives where no mapped identity exists
## (filed Aug 20, the re-narrowing audit's oracle check) — CLOSED Aug 20

`libs/toml/tests/*.saw` reach the package via `import src.lib.*` — no
`--module-path`, so the modules carry no mapped-package identity and
`check_visibility`'s `if not package_root: return True` arm answers ALLOW.
Proven live both ways: `TomlDoc` narrowed to `public(package)` is REFUSED by
blade (mapped consumer) while all four toml tests compile CLEAN against the
same source; same for `semver.Version`. This is the DF-232j family's
remaining arm — 232j rooted mapped and std packages; a package reached by
RELATIVE path still fails open, so the tier is only real for consumers that
arrive through `--module-path`. Fix direction: a relative-path package needs
a root identity too (the filesystem package root the module_resolver already
computes), or the fail-open default flips to fail-closed with an explicit
carve-out for the no-package case. Obligation-4 sweep owed at fix time: any
OTHER reach that constructs namespaces without a package root (single-file
compiles, `module` decls, the entry file itself). [232j, 232f, audit report]

CLOSED Aug 20 (branch `df-batch-232n`, unit 1). Fixed by IDENTITY, not by a
blanket fail-closed: the two behaviors riding the fail-open arm are CORRECT and
had to survive (the `examples/` manifest-less fixtures, where DF-229c ruled a
same-package importer binds package names, and a package's own tests under its
`Saw.toml` root). Every module a compile loads now carries a PACKAGE IDENTITY —
an opaque token compared for equality — in this precedence: (1) std,
`("<std>", …)`; (2) a `--module-path` name, `(name, …)`; (3) the nearest
`Saw.toml` root of the module's FILE (`ModuleResolver._find_package_root`,
reused); (4) the ENTRY file's directory tree, the ad-hoc-package rule. 1 and 2
are facts about the module PATH and stay where they were (the funnel's prefix
arms, plus `Namespace.package_identity` so the ACCESSOR side is placed too);
3 and 4 are facts about the FILE, computed once by the driver
(`_prepare_codegen`) into `package_identities` and stamped on every namespace
beside `mapped_packages`. `Namespace.visibility_relation_allows` — still THE
funnel, docstring updated — answers the rootless `public(package)` question by
comparing identities, and `check_visibility`'s `if not package_root: return
True` arm is now `return False`.

OBLIGATION-4 ROWS — which loading path each shape takes, all probed: a
single-file compile (def_module == accessor, decided before any root question);
an entry plus a relative SIBLING (`examples/` — arm 4, one tree, one package);
an entry inside a `Saw.toml` root reaching a sibling under it (`libs/toml`'s
tests — arm 3, same manifest); a `--module-path` package (arm 2, unchanged);
an INLINE `module foo { }` (path is `parent + (name,)`, so the identity lookup's
nearest-ancestor walk gives it its parent's — an inline module is part of the
file that declares it); an external `module foo` decl (its own module_map entry,
so its own file's identity); std (arm 1); the entry file itself (`()`, always in
the map). CONSUMER SWEEP (obligation 2): the fail-open arm's in-tree
beneficiaries were exactly the `examples/` relative fixtures and `libs/toml`'s
tests — both preserved by construction; corpus-wide, `public(package)` appears
in only three trees (`examples/`, `sos/kernel/core/` which is mapped as `kcore`
and unaffected, and `libs/toml/src`), and kcore's siblings import each other as
`kcore.X` rather than relatively, so no site was newly refused. PINS:
`examples/package_tier_foreign_relative_reach_error.saw` +
`…_selection_error.saw` (the refusal, at both funnel entry points) and
`examples/module_tests/pkg232n/tests/package_tier_same_package_reach.saw` (the
`libs/toml/tests` shape, kept working), over the new fixture package
`examples/module_tests/pkg232n/`. Conformance rows B18 (refusal) + B19
(control) added FIRST. Gate: full suite 2053 passed / 17 xfailed, sos_runner
80/80 across riscv32 + arm64.

## DF-232o — a visibility-refused TYPE re-resolves as a distinct same-named
## type: "expects `SosStatus` but got `SosStatus`" cascades, and a private
## type surfaces as place/optional errors with NO visibility line (filed
## Aug 20, the re-narrowing audit) — FACE 1 CLOSED Aug 20, FACE 2 CLOSED
## Aug 21 (the private-in-public ruling landed)

One mechanism, two faces. When a type name is refused by tier, the checker
does not stop at the refusal — the name re-resolves to a
distinct-but-same-named type and every downstream comparison fails
STRUCTURALLY, so the printer renders both sides identically ("field `status`
expects type `SosStatus` but got `SosStatus`", 100+ cascade lines burying
the one true refusal). Reached through the design-141 place lowering the
cascade loses the visibility line entirely: a `private TomlTable` fails as
``argument `__window` expects `(&var TomlTable) sync -> TomlTable` but got
`(&var TomlTable) -> Void`` and "left side of `??` must be optional" —
nothing says visibility. Fix shape: a tier-refused type resolution should
poison downstream uses (design-63-style distinct-type printing would also
stop the X-but-got-X rendering: name the module in at least one side).
[audit report, 141, 80]

FACE 1 (the cascade) CLOSED Aug 20 (branch `df-batch-232n`, unit 3). A refused
type reference is now POISONED: `_types_compatible` — the one place two types
are judged, and therefore the funnel under all fifteen mismatch diagnostics —
answers compatible for a poisoned name, so the cascade never starts and the one
reported refusal stands as the story. Poison is recorded at the two places a
type reference is refused BY TIER: the selective import (`check_module`, which
already reported it) and the qualified spelling
(`_resolve_qualified_symbol` -> `_note_type_refusal`). The qualified spelling
also gained the right diagnostic: `_resolve_qualified_symbol` answered None for
both "the name is absent" and "the name is refused", so the message could only
guess ("type `lib.PkgBox` ... does not resolve", hint "check the import and that
`PkgBox` is `public`"); it now names the TIER in the standard wording. Two
"body has no value" verdicts consult the poison too — a signature naming a
refused type cannot type its own body, and that is the refusal's shadow. LIVE
ON THE AUDIT'S OWN CASE: `SosStatus` narrowed to `public(package)` and the
kernel rebuilt gives exactly ONE error, the tier refusal, where the audit
recorded 100+ self-contradicting lines. Poison is per-COMPILE and keyed on the
simple name, which is deliberate over-suppression on an already-failing
compile. PINS: `examples/package_tier_refused_type_no_cascade_error.saw` and
`…_qualified_error.saw`, over a new test_runner directive
`// EXPECT-ERROR-ABSENT:` (TESTING.md) — a fix that is about lines NO LONGER
PRINTED cannot be pinned by `EXPECT-ERROR-CONTAINS` alone.

FACE 2 (the place path) WAS OPEN — STOPPED AND REPORTED rather than patched,
because what it needed was a RULING. THE MECHANISM, probed (`--module-path` fixture, a
module-private `Hidden` behind a public `Carrier`):
  * a module-private type's VALUE flows out today and its `public` methods are
    callable: `c.get().doubled()`, `c.get().n` and a `public` field of that type
    both COMPILE AND RUN from a module that cannot name `Hidden`. Private-in-
    public is permitted as the language stands.
  * the PLACE path over the same type does not: `c.at(0).n` /
    `c.maybe(0)!.doubled()` fail with ``argument `__window` expects
    `(&var Hidden) sync -> Hidden` but got `(&var Hidden) -> Void``, exactly the
    toml shape. Traced: the synthesized window closure's BODY (a member access
    on the lent element) types as NOTHING, silently, so the closure comes out
    `-> Void`. `place_transform` records `decl.place_type` at PARSE time as the
    NAME the author wrote and the `__window` parameter's function type carries
    that same raw name; neither is canonicalized to a design-144 IDENTITY, so
    the use site re-resolves the name in the CALLING module. A `public` element
    type resolves there and everything works — which is why this only ever shows
    on a type the caller may not name.
  * the same probe with the caller declaring its OWN `Hidden` (design 144 says a
    dep's private name reserves nothing) does NOT type-confuse — it fails the
    same way — so this is a broken path and a bad diagnostic, not a soundness
    hole.
THE RULING OWED: may a value of a type this module cannot NAME be reached at
all? If YES (today's answer on the value path), the fix is design 144's own rule
— carry the element type's IDENTITY through `place_type` and the `__window`
type — and the place case then COMPILES, so nothing says "visibility" and the
brief's success criterion for this face is the wrong target. If NO, the refusal
belongs on the VALUE path too, which is a new rule owing a corpus sweep (std and
blade both return module-private types today). Deliberately not decided here.

RULED Aug 21 (user): **"a public API needs public types."** NO — a declaration
may not name a type LESS VISIBLE than its own effective reach, refused at the
DECLARATION (Rust's E0446 shape, on design 219's precedent that a `public`
declaration hard-requires what an internal one may infer). So the refusal moves
onto the VALUE path too, and the place case never arises.

FACE 2 CLOSED Aug 21 (branch `private-in-public`). THE FUNNEL is
`sawc/typechecker/sigvis.py` — one decision procedure over one position matrix
(16 rows, each naming its covering test), entered from `check` and
`check_module` at the same seam; the reach comparison REUSES design 80's
relation (tier ranks for "at least as wide", `visibility_relation_allows` for
"and the same scope") rather than restating it. A member's reach is CAPPED by
its type, so design 80's "legal but inert" stays true and the rule asks nothing
extra of a public member of a private struct. A `borrows` accessor is judged on
`place_type`, so no diagnostic names the synthesized `__window`. Three
compiler-registered prelude symbols (`String`, the primitive pseudo-structs,
`Result`) now say `public`: they had no declaration to read a tier off, and the
PRIVATE default refused every signature naming a `Result`.

THE CORPUS SWEEP (obligation 2 — a contract flip) found EIGHT sites across
suite + sos + bootstrap + a forced `sawc/rt/` rebuild. Five WIDEN THE TYPE:
std's `StringBytes`/`StringChars`/`VectorIterator`/`EnumeratedIterator` (the
iterators `for x in v.iter()` consumes — `std.data`'s `DataIterator` was
already `public`, fields stay private), `libs/toml`'s `TomlTable` (its own
init/get/add and both `TomlSection` accessors are `public`; it WAS `public`
until 718a9784, the DF-232f rider's file-local narrowing that DF-232q found
inverted), sos `WaitAnswer` and `ProcessSlot` + the fields their sibling
modules read. One NARROWS THE DECLARATION: `pkg232n`'s `make_box`, a fixture
written to exhibit the leak. Side-finding, recorded not filed: the two sos
widenings turned the FIELD gate on where it had been bypassed — while those
structs were private a sibling module read their private fields with no
diagnostic, and the only route to that was a private-in-public leak, which the
type-level rule now refuses.

THE RESIDUE, probed rather than assumed: the `__window` failure cannot be
produced by legal code (pinned by `EXPECT-ERROR-ABSENT: __window` in
conformance B22), and the parse-time `place_type` identity gap does NOT
misbehave for LEGAL same-named cross-module types — a `public Cell` lent across
a boundary keeps its identity through a read, a write in place, a conditional
lend and a forced one, beside the caller's own unrelated `Cell`
(`examples/place_cross_module_same_name_type.saw`). Nothing to fix there.

PINS: conformance rows B20 (refusal) + B21 (control: the cap and the private
declaration) + B22 (the cross-module face) added FIRST, over the new fixture
`examples/conformance/modules/hidden232o/`; the position matrix at
`examples/private_in_public_positions_error.saw` and
`…_extension_surface_error.saw`; a declaration-side row family added to
`examples/module_matrix/INDEX.md` grid 2. Gate: full suite 2087 passed /
29 xfailed, sos_runner 80/80 across riscv32 + arm64, blade bootstrap green.

## DF-232p — a refused CALL swallows a refusal in its own ARGUMENT (filed
## Aug 20, the re-narrowing audit; diagnostic completeness — filed "minor",
## ELEVATED Aug 20 by DF-232q to a real census hazard) — CLOSED Aug 20

`uart.write_str(hal.arch_name())` with BOTH refused reports only
`write_str`; isolating `arch_name` produces its refusal cleanly. An error
census from one batch compile under-counts — recorded in the audit report
as an implementing-agent warning. Fix rides whatever touches the
member-access refusal path next (likely DF-232o's). [audit report]

Aug 20: DF-232q measured the under-count at 72 sites across three waves, which
is not a diagnostic nicety — it is what made the audit's headline verdict
wrong. Treat this as a census hazard, not a minor wart.

CLOSED Aug 20 (branch `df-batch-232n`, unit 3). A call that cannot resolve now
type-checks its own ARGUMENTS before it bails, for their diagnostics alone —
`_check_arguments_anyway`, one funnel whose docstring names its five entry
points (the chained and the qualifier module arms of `_check_method_call`, on
every exit each: refusal/absence, the enum-spelling error, not-callable). The
member-visibility gate is deliberately NOT one: it REPORTS and lets the call go
on, so its arguments are already checked by the ordinary path. PIN:
`examples/package_tier_refused_argument_reported_error.saw` — both refusals of
`lib.pkg_scale(lib.pkg_secret())` reported, where before only the outer was.

## DF-232q — the re-narrowing audit's file-local verdict was INVERTED: 72 of
## 78 sites have kcore sibling consumers (filed Aug 20, the narrowing unit)
## — CLOSED on filing: the finding is about the audit, and the unit's
## convergence already carries the correct answer

`designs/renarrow-audit-aug20.md` called 78 of its 84 sites file-local and six
package-tier. Applying that grid, the compiler refused 72 of the 78: they are
read or constructed by kcore SIBLING files — `process.saw` (33 sites),
`irq.saw` (2: `TimerSlot.is_due`, `.fire`), `dispatch.saw` and siblings (37).
Not drift: `process.saw` was created by the kcore split (873c22a4), two commits
BEFORE the re-narrowing, and `git show ee4d2ffa:sos/kernel/core/process.saw`
already contains the offending `ThreadSlot(state:…)` / `TimerSlot(state:…)`
constructions. The audit was wrong when written.

MECHANISM: the audit ran ONE error census over a single narrow-all pass. Per
DF-232p a refused call swallows the refusals inside it, and more sharply, a
module that fails to compile is never reached by the modules downstream of it —
so each wave of refusals hides the next entirely. The audit saw
`waitables.saw`'s six and concluded the rest were file-local. Converging (widen
the wave, recompile, repeat) took three rounds to reach a clean build.

The wave-masking at this scale — 72 sites hidden across three waves — elevates
DF-232p from a minor diagnostic wart to a real census hazard: ANY batch
visibility census is sound only when iterated to a clean build, and a
single-pass count must never be reported as a verdict.

Landed with the narrowing unit (branch `renarrow-232f`, commit `0cac7deb`);
see the re-narrowing rider section for counts and gates. The lead corrects the
audit document at integration. [232f, 232p, 80, audit report]

## Extension-head visibility — RULED Aug 20 (user): BANNED. "Visibility
## belongs on members" — a tier marker on an extension head becomes a
## declaration-site error
## — CLOSED Aug 21, design 240 item 3 (branch `design-240`)

THE FACTS, corrected from the filing: `Extension.visibility` is parsed and
stored with exactly ONE consumer — the docs emitter's signature string
(cosmetic). It is not a member default (probed: an unmarked member inside a
`public(package) extension` is PRIVATE, not package), not a clamp (the
audit: a `public` member inside one is world-callable), not a scoping input
(design 142 is import-based). And the filing's "only such site" was the
package-tier marker only — plain `public extension` is a corpus-wide HABIT:
~105 sites across std/blade/libs/sos/examples, plus 4 spec examples and 2
skill mentions it was likely cargo-culted from.
THE RULING: ban the position. An extension is not a nameable entity — it
has nothing to be visible; only its members do. The habit's prevalence
STRENGTHENS the ban: adopting Swift default-setter semantics instead would
make ~105 decorative markers suddenly meaningful, silently flipping every
unmarked member inside a `public extension` from private to public.
THE UNIT (scheduled: the small-fix batch after design 239 lands, with the
Float64-name removal and the DF-225e search-path fix): parser refuses a
visibility on `extension` with a teaching fixit ("visibility belongs on
members — mark each member"); the dead `Extension.visibility` field and its
plumbing go; the docs emitter's signature drops the prefix (goldens
regenerate, schema note); the ~107-site corpus marker removal
(compiler-driven, 236-style); spec's 4 examples + the saw-lang skill's 2
lose the marker and the member-visibility section states the rule;
`visibility_package.saw`/`visibility_public.saw`/`visibility_parent.saw`
drop their extension lines and a new error pin covers the refusal.
diag.saw:63's marker (left alone by the narrowing branch pending this
ruling) goes with the batch. [audit report, design 80, 142]

LANDED Aug 21 (design 240 item 3). The parser refuses at the MODIFIER —
`_error_extension_visibility` (parser/core.py), reached from both positions a
visibility can precede an extension (the plain declaration dispatch and the
`@synthesize`-attributed one), anchored on the token to delete;
`parse_extension` takes no visibility and `Extension.visibility` is gone from
the AST, with the class docstring recording WHY there is no field. The docs
emitter drops the modifier from an extension's `signature` AND the item's
`visibility` key — that is a schema change, so `SCHEMA_VERSION` is 4 with its
changelog entry, and the header now says an extension is the one item kind
without the key (a consumer decides whether to show one by whether any of its
`methods` survived the gate). The seven `--emit-docs` goldens regenerated to a
FIXPOINT: each golden lives inside the file it describes, so dropping the
`visibility` line shifted every `"line"` it records by one.
MIGRATION: 104 heads across sawc/std, blade, libs, sos, devtools and examples,
compiler-driven (236-style) — the count matches the audit's ~105 including
`diag.saw:63`'s `public(package)`. Spec: the member-visibility section states
the rule with the real diagnostic, and its own `public extension Account`
example plus the two orphan-rule examples lose the marker; the design-142
paragraph now says `public` on an extension METHOD. Skill: the two example
sites, plus a new bullet under member visibility. PINS:
`examples/extension_head_visibility_error.saw` (plain `public`) and
`examples/extension_head_visibility_package_error.saw` (`public(package)` on an
attributed head).
NO V39-ALIKE. The sweep looked for the thing the ruling was afraid of — a
member that was reachable only because its extension head said `public` — and
there is none, which the FACTS above predict: the marker was never a member
default, so an unmarked member inside a `public extension` was already private
and stayed private. Cross-module consumers (blade, libs, sos/sysapi,
examples/modules) are green with no member re-marking anywhere, and the full
suite plus sos on both arches confirm it.

## DF-232e — an IMPORT CYCLE is not diagnosed: the symbols silently vanish and
## the error lands on an innocent third module (filed Aug 17, the kcore split's
## unit-0 probe)
## — CLOSED Aug 21, design 240 item 7 (branch `design-240`)

Two modules of one package importing each other (`a` imports `b.{beta}`, `b`
imports `a.{alpha}`) compiles to `error: undefined function `alpha`` — reported
in `lib.saw`, a THIRD module that merely imports `a` and did nothing wrong. The
cycle itself is never named, neither participant is pointed at, and the reader is
sent to look for a typo in a file that has none.
MECHANISM (read, not guessed): `_topological_sort` (sawc.py:324) detects the
cycle and then RETURNS THE MODULES IN ARBITRARY ORDER with the comment "the type
checker will handle any errors" — so a module is type-checked before the
dependency that defines its names, its own checking fails, and its export table
comes out empty for everybody downstream.
THE FIX IS THE DIAGNOSTIC, not the ordering: `import cycle: a -> b -> a`, naming
the import lines. Whether Saw should SUPPORT cycles is a separate question the
kernel does not need answered — the kcore split is a DAG by construction — but
silently degrading is not an answer to either.
Pinned by nothing yet: a cycle needs two module files, which `examples/` has no
harness shape for (a `// COMPILE-FLAGS: --module-path` test dir would be the
first). [232, design 82/150]

LANDED Aug 21 (design 240 item 7) — the DIAGNOSTIC, as ruled; whether Saw
should SUPPORT cycles stays un-asked. `module_dependency_graph` is the shared
half (the edge set PLUS the `import` node behind each edge, so a message can
point at a LINE), read by both `topological_sort_modules` and the new
`find_import_cycle`; `report_import_cycle` prints the loop as the headline
(`import cycle: a -> b -> a`) and every edge's import line in the hint, with
the caret on the first participating import in ITS OWN file. New
`ErrorKind.IMPORT_CYCLE`. The check runs at the call site, before the sort,
because that is where the reporter and every module's source are in hand.
ONE BOUNDARY, kept green rather than tightened: a module importing ITSELF is
not a cycle — it asks for names it already has and has always compiled — so a
module is never its own dependency, dropped where the graph is built rather
than left for two consumers each to recognize as not-a-cycle. Design 235's
own `graph_self_import.saw` row is the pin, and its comment now records why.
PINS flipped and renamed: `examples/module_matrix/graph_2cycle_error.saw`,
`graph_3cycle_error.saw`. Both carry an `EXPECT-ERROR-ABSENT: undefined
function` — the innocent third module the error used to land on is exactly
what has to be GONE, and no CONTAINS line can say that. Grid 3 of
`examples/module_matrix/INDEX.md` is green. Spec gained an "Import cycles"
section; the skill a bullet.

## DF-232d — ASSIGNMENT THROUGH A MODULE QUALIFIER is the one member-access
## position that does not resolve (filed Aug 17, the kcore split's unit-0 probe)
## — CLOSED Aug 21, design 240 item 6 (branch `design-240`)

`mod.STATIC = v` from another module is `error: undefined variable `mod``,
pointed at the assignment. READING the same static works, and so does every other
write shape — this is one position, not a missing feature.
MECHANISM (read in `_check_assign_statement`, statements.py:2406): a bare
`Identifier` target is asked `_mutable_static_symbol` first (design 149's
whole-value static write), and a `MemberAccess` target instead type-checks its
OBJECT as an expression (`obj_type = self._check_expression(stmt.target.object)`,
:2483). That is right for `a.b.c = v`, whose object is a value — and wrong for
`<qualifier>.<static>`, whose object is a MODULE NAME and so reaches
expressions.py's "undefined variable". Nothing routes a qualified static to the
static-write path the bare form has.
MATRIX (obligation 4 — 10 positions probed, ONE fails): reads `mod.X`,
`mod.CELL.v`, `mod.ARR[0]`, `mod.CELLS[1].v` ✓; writes `mod.CELL.v = v`,
`mod.ARR[0] = v`, `mod.CELLS[1].v = v` ✓; refs `&var mod.X`, `&var mod.CELL.v`,
`&var mod.ARR[2]` ✓; `mod.X = v` ✗. Every passing row reaches the qualifier
through the general EXPRESSION path (which knows qualifiers); the one failure is
the only target whose base IS the qualifier and nothing else.
THE KCORE SPLIT DOES NOT WORK AROUND IT: the bare-import spelling
(`import kcore.threads.{THREADS}`, then `THREADS[i].state = ...`) is a
first-class design-150 form, is what a shared kernel slab wants to read like, and
writes correctly — proven cross-module, single-instance, in the unit-0 probe.
[232, design 149/150]

CORRECTION (Aug 20, design 235's grid 2 sweep): the "writes" and "refs" rows
above do NOT hold on today's tree — re-probed directly, three ways, all ICE:
`mod.ARR[1] = 41` (an element WRITE through the qualifier — the exact
`mod.ARR[0] = v` shape the matrix marked ✓), `bump(&var mod.X)` and the same
shape through `mod.ARR[2]` (the "refs" rows) all crash
(`internal compiler error ... (Identifier): Undefined variable: mod`), not
the clean typecheck refusal the bare `mod.X = v` assignment gets. Reproduced
both via a plain relative import AND via `--module-path` (so this is not
DF-232n's relative-path/package-root distinction) — identical failure
either way. Only the PLAIN READ (`mod.X`, `mod.ARR[i]`) and the plain
by-VALUE argument (`f(mod.X)`) actually work; every write-shaped or
reference-shaped consumer of a qualifier-rooted place ICEs. Since the
typecheck phase does not error before the crash (reads through the same
qualifier succeed earlier in the same compile unit), this is a CODEGEN
gap, not the typechecker gap the entry above names: whatever generates the
LVALUE/address for a qualifier-rooted `ArrayIndex`/`ReferenceExpr` write
target tries to codegen the qualifier `Identifier` as an ordinary runtime
value (which has none — a qualifier is compile-time-only), where the READ
path apparently special-cases it. Not re-numbered — same disease (a
qualifier-rooted `MemberAccess` whose consumer does not recognize the
qualifier), one layer down from the typechecker gap above, filed under
DF-232d per obligation 4 (a finding is a class until a sweep says
otherwise, and this sweep found the class is WIDER than first drawn: every
write/reference position through a qualifier is red, not three of four).
SO THE CORRECTED MATRIX IS: reads `mod.X`, `mod.ARR[0]` ✓; a plain by-value
argument `f(mod.X)` ✓; `mod.X = v` ✗ (clean refusal, typecheck); every
OTHER write/reference shape through a qualifier — `mod.ARR[i] = v`,
`mod.CELL.v = v`, `&var mod.X`, `&var mod.ARR[i]`, and (design 235's own
probe) `mod.X += v` — ✗ (ICE, codegen). PINS:
`examples/coercion/qualname_mod_static_refarg_ice.saw`,
`examples/coercion/qualname_mod_static_compound_assign_ice.saw` (XFAIL,
design 235's grid 2; the array/field-write ICE is the SAME
`qualname_mod_static.saw` neighborhood — see that ledger's INDEX.md for the
full cell list rather than restating it here).

LANDED Aug 21 (design 240 item 6). TWO layers, as the corrected matrix said.
TYPECHECK: `_qualified_static_symbol` is the one place that asks "does this
member access name a module static", and two callers use it — the
static-root walk (`_assign_target_static_root`, where a qualified static is
now the ROOT rather than something to peel past, which is what keeps the
IMMUTABLE refusal honest) and `_check_assign_statement`, which routes a
mutable one to `_check_static_var_assign` beside the bare spelling. Design
150 pin 4 rides along free: the helper asks `_module_qualifier`, so a local
named after the qualifier still wins (probed — `let qdep = 7` then
`qdep.X = 5` is "cannot assign to field of immutable variable `qdep`").
CODEGEN: `_static_global` answers for the qualified stamp
(`resolved_static_name`) as well as the bare one, and the three address
paths that bypassed the lvalue funnel now ask it — `_get_lvalue_pointer`'s
MemberAccess arm, `_generate_reference_expr`'s, and
`_get_array_element_pointer`'s — plus a `mod.NAME = v` arm in
`_generate_assign_statement` and a compound-assign arm that goes through
`_get_lvalue_pointer` instead of straight to `_get_member_pointer`.
MATRIX (probed, all green): `mod.X = v`, `+=`, `&var`, `&`, `mod.ARR[i] = v`,
`mod.ARR[i] += v`, `&var mod.ARR[i]`, `mod.CELL.v = v`, `+=`, `&var
mod.CELL.v`, the plain read, the by-value argument, and the immutable
refusal. ONE SIBLING the sweep found and fixed with it:
`&STATIC_ARR[i]` on a BARE static raised "Undefined variable" too —
`_get_array_element_pointer`'s Identifier arm was the only address path that
never learned about statics at all.
PINS (renamed for the behaviour they now pin, un-XFAIL'd):
`qualname_mod_static_assign.saw`, `_compound_assign.saw`, `_refarg.saw`,
`_elem_write.saw`, plus the new `_immutable_error.saw`; the fixture gained a
`Cell` and an immutable `K`. Grid 2's row is green in
`examples/coercion/INDEX.md`, and grid 1's module-qualified-static-assign row
with it.

## DF-240a — a const expression whose LEAF is a module `static` still does
## not adopt its fixed-width slot, so it is not range-checked (filed Aug 21,
## design 240 items 1-2's own sweep) — WANTS A RULING

`static PAGE_SHIFT: Int = 20` then `let e: UInt16 = 1 << PAGE_SHIFT` compiles
clean and prints `0`; spelled `1 << 20` it is the clean "does not fit in
`UInt16`" error the same file's sibling pins. The size-in-one-place idiom
(DF-172j) is exactly the spelling that loses the check.
MECHANISM: design 240's funnel arm folds through `const_eval` over the AST it
is handed, and a static's value reaches that AST only where an earlier pass
stamped `const_static_value` — which is a CONST-REQUIRED position, not an
ordinary expression. The walk that would supply it, `_stamp_const_names`,
also stamps a raw-backed enum CASE, and design 185 unit 4 rules a flag-enum
read (`Perm.Read | Perm.Write`) a constant only IN a const position. So the
fix is not "call the stamper here": it decides whether an ADOPTION position
is a const position for naming purposes, which widens 185 unit 4 as a side
effect or needs a narrower stamper that deliberately excludes enum cases.
RULED Aug 21 (user): **FULL CONST POSITION** — a fixed-width adoption slot
is a const position for name resolution, statics AND raw-backed enum cases
both fold there. This DELIBERATELY widens design 185 unit 4 (an amendment,
not an accident): `let mask: UInt8 = Perm.Read | Perm.Write` becomes legal,
with the result the backing integer exactly as 185 rules in every const
position; the enum-typed-VALUE operator refusal outside const/adoption
positions is unchanged. The fix + the 185 spec amendment ride design 241
unit 2 (first on resume). PIN:
`examples/coercion/const_expression_named_static_operand.saw` (XFAIL, flips
with the fix). [240, 235, 185, 172j]

**CLOSED Aug 21, design 241 unit 2** (branch `design-241`). One line at design
240's own funnel arm: `_fold_const_expression_into` runs `_stamp_const_names`
over the expression before `const_eval`, so an adoption slot has the names
every other const position has. 185 unit 4's refusal is untouched —
`_check_binary_op` answers from the `const_folded_value`/`expected_type` stamp
pair and never descends into the operands once the funnel folded, and outside
an adoption or const position the arm never runs. Pin un-XFAIL'd; the
enum-case row is `examples/coercion/const_expression_named_enum_case_operand.saw`;
`examples/coercion/INDEX.md` rows flipped. Spec + saw-lang skill carry the
dated amendment. Boundary and evidence: designs/241-undefined-type-names.md.

## Design 205 — the platform pair converts by the book at transfers too
## (LANDED Aug 21 — designs/205-transfer-conversion-closes.md, with its
## landing section + the unit-3 migration list)

Closes DF-195b and DF-195c (entries above) — the last two SILENT integer
conversions in the language. `_types_compatible`'s integer arm is same-kind
only; the one implicit integer conversion a transfer admits (a lossless
widening through the platform pair) is admitted POSITIONALLY by
`_transfer_compatible`, and every refusal site carries design 170's three
spellings as a hint. The transfer-position matrix is conformance rows W20-W24.
The consumer sweep's 53 corpus failures were 46 ADOPTION-ENTRY GAPS fixed at
six paths (the plain instance-method argument, both enum-payload arms, the
`borrows` accessor argument, `UnsafeMemory.write`, `UnsafeMutableInterior`, the
overload candidate filter — each a position design 87's stamp never reached and
the closed permission had been absorbing) and THREE true migrations, all `as`:
two in `examples/`, one the real std bug (`net.saw`'s `close(fd as Int32)`).
One finding filed and fixed in the same brief.

- **DF-205a (SOUNDNESS — WRONG ANSWER + an ICE, filed Aug 21 by 205 u1's
  probes): an implicit LOSSLESS widening extends by the TARGET's signedness
  at FOUR MORE transfer positions.** DF-195a's mechanism — "a widening site
  with no source type" — at the positions neither its fix nor DF-195e's
  census reached: the implicit TAIL return (`func f(u: UInt32) -> Int { u }`
  prints -294967296 where the explicit `return u` beside it prints
  4000000000 — the tail path calls `_coerce_ret_value(result)` with no
  expression, the `return` path passes `stmt.value`), a fixed-array LITERAL
  element, a tuple element, and an optional payload (`let o: Int? = u`). The
  array face is worse than a wrong answer: an annotated literal whose FIRST
  element is narrower than the annotation takes its LLVM element type off
  that element instead of the annotation, so `let a: [Int; 2] = [u, 0]` is
  an internal compiler error (`Can only insert i32 at [1] in [2 x i32]: got
  i64`). Load-bearing for design 205: closing the narrowing and sign-flip
  axes makes the widening admission POSITIONAL, so every position has to
  extend correctly before the rule can rest on it. PIN:
  `examples/conformance/W22_lossless_widening_transfer_positions.saw`.
  **FIXED by design 205 unit 2.** The six fall-through `ret` sites each pass
  their own `body.final_expr` to `_coerce_ret_value` now, and one new codegen
  funnel — `_coerce_element_int`, whose docstring names its three entry points —
  coerces an aggregate element to its DECLARED type at the array literal, the
  tuple literal and the `OptionalWrap`, which is what retires the ICE with the
  wrong answers. PIN flipped to a passing test.

## ~~DF-244a — a propagating `try` inside a `return` (or a block TAIL) in a
## SUSPENDING body never reaches the frame's error edge~~ — **FIXED Aug 22**
## on branch `design-234`, found while probing design 234 unit 1's position
## matrix

MECHANISM (obligation 4, and it is one site, not a family of positions):
`_lower_stmt` dispatches a propagating `try` to design 196 unit 3's error
landing BELOW the control-flow ladder — and the `ReturnStatement` branch sits
ABOVE it. So a `return` carrying a propagating `try` was lowered IN PLACE with
the `try` still inside `resume() -> Poll`, and the exact failure the landing
exists to prevent came back: the typechecker's second pass read the propagation
target off `Poll` (``cannot propagate errors from a function returning `Poll` ``)
or codegen reached `_create_result_err_for_return` inside `resume`
(``Cannot create Result.Err outside Result-returning function``, an ICE).
SWEEP: 26 rows × {sync, suspending}, compiled AND run. Five expression shapes
failed under `return` — bare, argument, receiver, binary operand, `match`
scrutinee, `??` RHS (two of them the ICE) — and every one of them PASSED when
bound to a `let` first, which is what made it look like a rule about expression
positions rather than the one statement kind it is. A block TAIL is the same
site (tail normalization turns it into a return), and it needed the second half
of the fix: `_norm_block` left a NON-spanning tail in `final_expr`, where
`_done` lowers it with the `try` inside. The landing dispatch stays BELOW the
ladder — a `while` whose body holds a propagating `try` is a loop to split, not
a statement to wrap — so the `return` branch DEFERS to it rather than the
dispatch moving up. Regression test
`examples/suspending_return_propagates_a_try.saw` (9 rows, Ok and Err path
each). Matters to design 234 because the flip multiplies `return try f()`.
[196, 234]

## DF-243c — `SegFlag.Device`'s docstring says "Bit 8 rather than 3" and the
## value IS bit 3 (filed Aug 21, same session; surfaced by the shift
## respelling — NOT introduced by it)

`sos/imgformat/src/lib.saw`'s `SegFlag` docstring closes with: "Bit 8 rather
than 3, because 1/2/4 are a RISC-V PMP config's low three bits … a fourth bit
in that field would be the PMP `A` field's low bit." The case is `Device = 8`,
which IS the fourth bit — bit index 3 — and riscv32's `PMP_A_TOR` is `0x8`, the
very value the sentence warns about. The prose describes a collision it says
was avoided and the value walks straight into it. The decimal `8` hid this;
`1 << 3` puts the bit index in the reader's eye, which is the respelling
earning its keep.

NOT LIVE, and that is why it is a finding rather than a fix: riscv32's
`prot_region` masks with `PMP_PERM_MASK = 0x7` before staging a cfg byte, so
the Device bit never reaches the A field; arm64 names `SegFlag.Write`/`Execute`
explicitly and never installs the mask raw; Blade emits through named cases on
the other side. Every consumer is correct today.

WHAT IT NEEDS IS A RULING, not an edit — which half was meant. Either the value
should move (a WIRE-FORMAT change: `SosimgSeg.flags` is `UInt8`, so "bit 8" is
not even representable, and any move is a version bump touching both emitters
and both loaders), or the sentence should say what the code actually does and
why it is safe (the mask is the real reason, and it is not mentioned where the
flag is declared). Left exactly as found; the value is unchanged and
probe-verified. [140, 178]

## DF-238a — a module-QUALIFIED free-function call does not carry its
## parameter's fixed-width type into a literal argument (filed Aug 21, design
## 238 unit 1; found writing the freestanding suite's cross-target rows)

`m.f(300)` at a `func f(b: UInt8)` COMPILES and the callee receives 44. The
bare twin `f(300)` under `import m.{f}` is the clean ``integer literal 300 does
not fit in `UInt8` `` it should be, so the literal is not adopting the
parameter's width through the qualifier — it stays at platform `Int` and is
truncated at the call with nothing said. Hosted, running evidence: a program
printing `qualified: 44`.

SECOND FACE, 32-bit targets only: a literal WIDER than the platform word has no
platform-`Int` reading at all, so instead of truncating it falls out as an
INTERNAL COMPILER ERROR — ``internal compiler error … (IntLiteral): integer
literal 40029095242992 does not fit in the 32-bit platform Int of target
'riscv32-unknown-none-elf'`` for `m.take_wide(0x2468_0000_ACF0)` at an `Int64`
parameter. Same missing expectation, different fallout per target, which is why
this surfaced in the freestanding suite and not in the compiler suite.

MECHANISM (obligation 4): the qualified free-function call path resolves the
callee but does not thread its signature into argument checking, so the
expected-type propagation every other call shape performs simply does not run.

WHY IT IS SILENT RATHER THAN AN ERROR, and this is a COMPOSITION with a finding
already on this tracker: the literal that never adopted stays a platform `Int`,
and `_types_compatible` admits a platform `Int`/`UInt` into any integer type —
which is DF-195b, filed and pinned separately. 238a is why the literal is still
an `Int` at the call; 195b is why an `Int` may land in a `UInt8` with nothing
said. Fixing EITHER turns the 44 into a diagnostic; fixing 238a is the one that
makes it the RIGHT diagnostic, at the literal and naming the range. Whoever
takes one should read the other first.
POSITION MATRIX, probed with compile/run evidence on both targets:

| spelling | literal adopts + range-checks? |
|---|---|
| `import m` + `m.f(lit)` | **NO — silent truncation / ICE** |
| `import m as mm` + `mm.f(lit)` | **NO — silent truncation** |
| `import m.{f}` + `f(lit)` | yes |
| `import m.*` + `f(lit)` | yes |
| `m.T.s(lit)` qualified STATIC method | yes |
| `m.T(field: lit)` qualified CONSTRUCTOR | yes |
| same-module call, annotation, return, field, `static`, suffixed literal | yes |

THIRD FACE, same path, found in the same session: GENERIC TYPE-ARGUMENT
INFERENCE does not run there either. `m.over<T: Named>(&r)` at a conforming
`Rec` is ``argument `value` expects `&T` but got `&Rec` `` — `T` was never
solved — where the bare twin infers it and the same call with an EXPLICIT
`<Rec>` fails identically. Inference reads the callee's signature, so this is
one more thing the qualified path does not thread rather than a second
mechanism, and it is why the freestanding suite's `module_compose` case reaches
its generic bare and its non-generic calls through the qualifier.

So the hole is the qualified FREE-FUNCTION path alone; the two qualified MEMBER
paths beside it are correct, which is where a fix should look for the
propagation it is missing. Pinned XFAIL:
`examples/qualified_call_literal_adopts_parameter_width.saw` (+
`examples/modules/qualcall238a/`), whose two controls are the qualified static
method and the qualified constructor — so a fix cannot pass by breaking them.
The freestanding suite's cases reach `fscore` through `import fscore.*` rather
than the qualifier for this reason, stated at the runner's case table. [238,
185, 235, 150]

ELEVATED at the 205 integration (Aug 21, lead): design 205 closed the DF-195b
permission that had been silently absorbing this gap, so the un-adopted `Int`
at a fixed-width qualified call is now a REFUSAL of a perfectly ordinary bare
literal — `fsrt.stop(0)` broke every freestanding case at the merge (the 205
sweep could not see code that landed in parallel). Migrated at integration:
`tests/freestanding/core/src/lib.saw` spells `0u32` with a comment naming this
finding; the fix un-suffixes it. A bare literal at ANY qualified free-function
call with a fixed-width parameter now refuses, so this gap is user-visible on
the ordinary path and should be scheduled accordingly.

**STATUS: CLOSED Aug 21 (small-fix batch).** `_check_module_function_call` now
threads the RESOLVED callee's signature exactly as the bare path does, in the
bare path's own order: solve/verify the type arguments (design 93/105
inference, `_check_type_param_bounds` for the bounds and design 219's
discharge, `_effect_record_poly_call` for the deferred effect edge), substitute
into the parameter and return types, admit the design-53 arity RANGE, check
design 108's omitted generic defaults, then per argument
`_apply_literal_expected_type` before `_check_expression`, plus the existential
coercion arm. Codegen's `_generate_module_function_call` gained the two things
that follow: `_instantiate_generic_function` for a generic callee (the template
is registered under the same key the bare path uses) and `_fill_func_defaults`
for an omitted trailing default.
A FOURTH FACE, found by this fix's own probe and the same mechanism rather than
a new one: a DEFAULTED parameter could not be omitted at all through a
qualifier (``function `with_default` takes 2 argument(s), but 1 were given``) —
the arity test compared against the full parameter list and codegen filled no
default. Recorded here rather than filed separately, per the entry's own
mechanism statement.
PIN FLIPPED: `examples/qualified_call_literal_adopts_parameter_width.saw`, with
its two controls intact. COMPANION:
`examples/qualified_call_threads_the_callee_signature.saw` (eight rows — width
adoption, a defaulted parameter omitted and supplied, inference at a bounded
parameter, at a plain one and across two, an explicit type-argument list, and
optional auto-wrap), over an extended `examples/modules/qualcall238a/`.
The SECOND face is 32-bit-only and cannot live in `examples/`, so it is
asserted in the freestanding suite: `module_compose` passes a wide literal
through the qualifier at `check_wide`'s `Int64` (the exact ICE shape) and a
bare literal through it at a new `fscore.widen_byte`'s `UInt8`. MIGRATION
REVERSED: `tests/freestanding/core/src/lib.saw` spells `fsrt.stop(0)` again and
the runner's case-table note now records the qualifier as a free choice.
DF-239b was explicitly out of scope and is untouched. Gated suite + freestanding
both arches.

## Queue records — the Aug 21-22 overnight/morning group (moved verbatim from [QUEUE] at the Aug-22 tracker pass)

- ~~DF-218s remainder + DF-218w~~ — LANDED Aug 21 on branch `df-218s-218w`, two commits. DF-218s CLOSED (forced frame residency, pin flipped with its block-kind matrix); DF-218w NARROWED to the mixed `case Both(v, _)` shape, both ledger rows retired, three pins now (one flipped, two XFAIL). Two findings filed: DF-218x (sync `if let` leak on a `return`/`break` out of the then-branch) and DF-218y (a multi-field all-`_` payload's field order, and sync is the suspect half). Entries below
- ~~Small-fix batch~~ — LANDED Aug 21-22 (branch `small-fix-batch`, five fixes + a docs commit): DF-216c (+DF-217d), DF-216h, DF-219c, DF-238a (a fourth face found and fixed with it), DF-218v all CLOSED in place. Three findings filed: DF-242a (driven try/catch teardown timing), DF-242b (cross-module overload set bound bare as one overload), DF-242c (suffixed literal does not disambiguate an Int-vs-narrow overload set). Conformance K74/K75 (renumbered from K72/K73 at integration). xfails 13 -> 10
- sos riders batch — LANDED Aug 21 (branch sos-riders): the remainder both flipped — `clock_get` takes `type:` at its two declarations, the kernel decode and the three labeled call sites, and all 46 rights-enum cases in `sos/kernel/abi/` read as shifts with the values probe-verified byte-identical before and after (ordinals left decimal; the `>= 256` static_assert threshold is not a case and stayed, reported). The kcore re-narrowing LANDED Aug 20; the member audit RAN Aug 20 and its narrowing unit LANDED Aug 20 (84 sites: 78 `public(package)`, 6 private, 2 consumed; the audit's file-local split was inverted — DF-232q); see the re-narrowing rider section

## ~~DF-239b — a fully CONCRETE parameter type is unchecked on the
## generic-bound call path~~ (filed Aug 20, DF-239a's sweep) — **FIXED Aug 24**
## on branch `resolution-wording`, commit 2, by DECLARATION-TIME RESOLUTION

The residue of DF-239a's mechanism. `_check_type_param_method_call` defers
deep argument typing because a trait signature MAY name an associated type;
it never asks whether THIS one does. So `a.concrete("hi")` against a
requirement `func concrete(&self, n: Int)` — no `Self`, no associated type,
nothing abstract — type-checks in the generic body and dies at codegen with
`Type of #2 arg mismatch: i64 != i8*`. Traits carry no type parameters of
their own (`TraitSymbol` has `associated_types` and nothing else), so the
decidability test is small: substitute `Self` to the receiver's type
parameter and check every parameter whose result names no associated type.
What stopped the fix riding DF-239a was RESOLUTION — a trait's declared
parameter types are stored raw, and resolving one at a foreign call site runs
the design-194 prelude gate against the wrong module. Wants a resolution
strategy, hence its own entry. PIN:
`examples/generic_bound_call_concrete_param_type.saw` (XFAIL). [239]

**FIXED Aug 24** (branch `resolution-wording`, commit 2). `_register_trait` —
design 241 unit 1's fifth funnel entry, which already GATED the requirement's
written types and threw the answer away — now RESOLVES them and keeps the
result: `TraitMethodSymbol.resolved_param_types` / `resolved_return_type`
(design-144 identities) plus `abstract_type_names`, the set that stays abstract
at every call site. `_check_type_param_method_call` then substitutes `Self` to
the receiver's own type parameter and, for every parameter whose result names
nothing in that set, runs the ORDINARY argument check — `_apply_literal_
expected_type`, `_try_existential_arg_coercion`, `_arg_type_ok`, the same
message and the same `_int_conversion_hint` the instance-method path uses.
WHY DECLARATION TIME IS THE WHOLE FIX: resolving the spelling at the CALL runs
the prelude gate against the caller's module, so a trait declaring
`take(&self, bytes: &data.Data)` would be uncallable from any module that never
wrote `import std.data` — the error naming a type the author never mentioned.
Registration runs in the declaring module (and fourth of four passes, so
same-module names are registered); the gate's per-position dedup means passing
through `_resolve_type` there reports nothing twice.
MECHANISM (obligation 4): "a call form with no argument-compatibility loop".
The MATRIX, all probed: a CONCRETE parameter (the pin), a `Self` parameter
(decidable — becomes `&T`, and the message says `&T` not `&Self`), an
ASSOCIATED-TYPE parameter (deferred, and must stay so), a MIXED signature with
all three plus out-of-order LABELS, and the cross-module gated pair in both
directions. Two abstract sources the matrix does NOT need rows for, because the
parser refuses both spellings: a trait cannot declare type parameters
(`trait Holder<E>` is a parse error) and neither can a requirement
(`func pick<R>(...)`). `abstract_type_names` collects them anyway, so the day
either lands the decidability test is already right.
TWO SECOND FACES the sweep turned up, both ICEs and both fixed by running the
real machinery rather than by new rules: an auto-WRAP at an `Int?` parameter
(`Type of #2 arg mismatch: {i1, i64} != i64`, verified against the branch point
by stash) and design 87/205's literal ADOPTION at a `UInt8` parameter.
FUNNEL (obligation 1): `_bound_call_param_slots` is now the ONE
argument -> parameter mapping on this path, shared by the new type check and
DF-239a's reference-spelling check — two rules judging per-parameter properties
of the same argument had grown two copies of the label mapping. The type check
also DEFERS to the spelling check where the two would both fire (a missing or
surplus `&`), so one mistake still draws one diagnostic.
ADJACENT, NOT CLOSED: a `static` requirement is still not callable on a type
parameter (`T.make(...)` is `undefined variable \`T\``) — DF-169e, recorded in
`std/cbor.saw` beside the `decode<T: Deserialize>` it blocks. That is why
`_bound_call_param_slots`' `off == 0` branch is unreachable from this call form
today; it is kept because the helper's contract covers both receiver shapes.
PIN FLIPPED: `examples/generic_bound_call_concrete_param_type.saw` (XPASS).
FIVE tests added: `generic_bound_call_self_param_type.saw`,
`generic_bound_call_associated_param_defers.saw`,
`generic_bound_call_mixed_signature_error.saw`,
`generic_bound_call_decidable_param_conversions.saw`, and the cross-module pair
`generic_bound_call_cross_module_gated_param{,_mismatch}.saw` over the new
fixture `examples/modules/traitgate239b/`.
CONFORMANCE: no row owed, the same disposition DF-239a took — this completes a
TYPE CHECK (an ICE becomes a diagnostic) and changes no safety guarantee the
ledger states.

## ~~DF-247b — under a GLOB import the QUALIFIED spelling of a type is a
## DIFFERENT type from the bare one~~ (filed Aug 22 by design 242 unit 1's
## identity probes) — **FIXED Aug 24** on branch `resolution-wording`, commit 3,
## as the ruled DESIGN 150 AMENDMENT

```saw
import std.data.*

func main() {
    var a: Data = Data()          // fine
    var b: data.Data = Data()     // error: cannot assign `Data` to variable
    print(a.len() + b.len())      //        of type `data.Data`
}
```

Neither answer is the right one. Design 150 says a qualifier works "in EVERY
position a name appears", so `data.Data` should BE `Data`; and if a glob
import is not meant to bind the qualifier at all, the line should be a clean
"undefined type", not a type mismatch against a phantom. Today it resolves to
something that is not std's type and nothing says so.

Reproduced at three types on two axes, which is what makes it general rather
than a corner of design 242's new carve-out: `std.data.*` + `data.Data` (an
ordinary gated std type), `std.compiler.frame.*` + `frame.Slot<Int>` (a
compiler-emitted one), and `std.task.*` + `task.Thread<Int>`. CONTROLS, both
green: the plain `import std.data` + `data.Data`, and the selective `import
std.compiler.frame.{Slot}` + `frame.Slot<Int>` — so it is the GLOB form
specifically.

MECHANISM (obligation 4, unswept): the glob path binds the qualifier without
mapping it to the module's real type identities, so `data.Data` resolves to a
name-only type that compares unequal to `Data`. The mechanism reaches every
position a qualified type name may be WRITTEN under a glob — design 194's
annotation matrix is the ready-made grid (parameter, return, `let`, field,
enum payload, alias RHS, `static`, generic argument, tuple/array element,
function-type part, `any Trait`) — and only the `let` cell is probed. Whether
the fix is "make it work" or "make the glob refuse a qualifier" is a RULING,
not an implementation choice.

Not pinned: the pin belongs with the ruling. [150, 194, 242]

**FIXED Aug 24** (branch `resolution-wording`, commit 3), both ruled halves.
HALF 1 — a QUALIFIER is bound ONLY by the whole-module form. The decision is one
predicate, `_import_binds_qualifier`, applied INSIDE `_bind_module_qualifier`
rather than at its callers, so no binding site can bypass it (obligation 1; the
docstring names its two entries, and the selective arms that used to be a third
and fourth are gone). The former bonus reach is a refusal naming the line that
would bind it, at the two positions a qualifier is written: the TYPE funnel's
qualified arm (`` `data` is not a module qualifier here ``, after design 229's
export wall has had its say) and the expression ladder's undefined-variable
verdict, both through one `_nonbinding_qualifier_hint`. The phantom's downstream
shadows are suppressed on DF-232o's rule, keyed on the WHOLE dotted spelling so
the bare `Data` beside it stays judged, plus the file-scoped "body has no value"
verdict a local of an unresolved type produces.
HALF 2 — the same-module pair is legal and complementary. It falls out rather
than being added: with only one form binding, `import std.data` +
`import std.data.{Data}` cannot collide, and the duplicate-qualifier error still
fires on two DIFFERENT modules (both collision pins use whole-module imports and
are untouched). ONE IDENTITY pinned position by position, since a fresh identity
there would be silent — annotation (both directions), construction, generic
argument (bare element into a qualified container and back), `&any` existential,
generic bound, extension lookup, struct field, enum payload, `type` alias, and
an `as` target: `examples/import247b_pair_one_identity.saw` over the new fixture
`examples/modules/pair247b/`, plus `import247b_glob_pair_one_identity.saw` for
the GLOB pair at the filing's own two axes (a gated std type and the
compiler-emitted `frame.Slot<Int>`).
CONSUMER SWEEP (obligation 2) — what read the selective form's `ns.modules`
entry, and what each of them was really asking:
  * COHERENCE (`coherence_search_namespaces`): would have LOST a conformance,
    which is DF-238c's finding one form over. The source moved to a new
    `selective_sources` list the same funnel walks beside `glob_sources`.
  * design 229's bare-name hint (`_import_hiding`): same list, same reason.
  * NAME lookups that fall through to imports — SIX walks, and the last two the
    first gate found rather than the sweep: `_lookup_struct_deep` and its type
    alias and enum twins, `trait_refines`' parent walk, `_cross_module_lookup`
    (the bare-name fallback; sos's `ATTACHMENTS[a].kind` reads a field off an
    element whose TYPE the import list never named, and 80 kernel builds failed
    on it), and the "not directly accessible" diagnostic that says WHICH module
    has a name. These were never qualifier questions — `import m.{Child}` has to
    keep finding `Child`'s unselected PARENT — so they read a new
    `imported_search_sources` that is `modules` plus the selective sources. A
    GLOB source is deliberately still excluded there: a glob COPIES what it is
    entitled to, so a name it did not copy is one this module may not see.
  * `-W shadowed-qualifier` and the member-lookup shadow hint: scoped to the one
    binding form automatically, since both read `ns.modules`.
  * design 229's private-import NOTE is still recorded by every form — it says
    what this module IMPORTS, not what it binds — which is what keeps B13's
    chain hop (`wall229.wire229.Header`) and the facade refusal reporting the
    surface wall rather than a missing qualifier.
CENSUS (obligation 2, the migration): a token-level walk of every tracked `.saw`
file over the compiler's own front end, filtering member accesses and local
bindings, then hand-verified. FIVE files, FOURTEEN sites, each given its
explicit whole-module line: `examples/import150_std_forms.saw` (1 — the design
150 forms pin itself, rewritten to document the amended rule),
`examples/module_matrix/import_form_selective_positions.saw` (1 — design 235's
selective-form row, same rewrite),
`examples/conformance/B13_import_is_not_reexport.saw` (2 — which makes it a
bonus test of half 2, all three forms of one module in one file),
`tests/freestanding/cases/module_compose.saw` (9), and
`sos/kernel/sysapi/src/lib.saw` (1 — `sosabi.ENTRY_IMAGE`; an ordinary import,
so the vDSO wall is unchanged). Nothing in blade, libs, devtools or selfhost
used one: every apparent hit there was a local named after a std leaf, which is
design 150 pin 4 working as designed.
The token walk had ONE BLIND SPOT, found by the gate and then closed in the
probe: a STRING INTERPOLATION is one token, so `"{lib.other_widget(9).n}"` was
invisible to it — which is the position a qualifier is most likely to be
PRINTED from. The corrected sweep scans interpolations as text beside the token
stream, and that is what the fifth file is.
CONFORMANCE: row B24 added (the amended binding + the one-identity matrix), and
B23's note gained the sentence that keeps its claim true through the amendment.
Spec's Imports section, README's import block and the saw-lang skill's import
table all carry the amended cells.

## ~~DF-244b — a bare `None` TAIL at a `Result<T?, E>` cannot type itself, in a
## NAMED body as much as a closure~~ (filed Aug 22, DF-232h's residue) —
## **FIXED Aug 22** on branch `transform-typing`, commit 3

`func f() -> Result<Int32?, Bad> { None }` is ``cannot tell what this `None` is
a `None` OF``, while `{ return None }` compiles and prints `ok -1`. Both
spellings were probed, in a named body and in a closure, and they agree — so
this is NOT the closure-vs-named disagreement DF-232h was, and DF-232h's fix
neither caused nor was owed it. MECHANISM: the wrap ladder runs AFTER the body
is checked, and a bare `None` fails in the body check itself, before any
expectation reaches it. `_check_return_statement` gets past that because
`_stamp_return_literal_types` / its own DF-140d branch push the expected type
onto the value FIRST; the tail path has no equivalent push for a Result whose
Ok payload is an optional. A fix propagates the peeled Ok payload into the
tail ahead of the body check, at both tail sites. Low value on its own —
`return None` is the one-keyword workaround, and the shape (an absent value
that is also fallible) is rare. [232, 234]

**FIXED Aug 22** (branch `transform-typing`, commit 3), and the mechanism as
FOUND corrects the guess above. The wrap ladder does not run after the body
check for this value at all — it never runs, because the ENTRY CONDITION at all
four sites is "does the body's type fail to transfer into the declared one?",
and the none-literal rule makes a bare `None` transfer into EVERYTHING. So the
tail was left exactly as written and codegen met a raw `NoneLiteral`. Nothing
about the body check refused it. `_check_return_statement` escaped only because
DF-140d had hand-written the decision at that ONE site — which is what made
`return None` work and the tail that means the same thing die.
FIX, extending design 234 unit 1's funnel rather than adding a rule beside it:
the bare-`None` decision MOVED into `_autowrap_into_result` (a new arm, ahead of
the ambiguity check — a `None` fits both payloads by the none-literal rule, so
asking the ambiguity question of one would reject an unambiguous program), the
hand-written copy at entry point 3 is GONE, and one predicate
`_reaches_result_autowrap` answers "does this value reach the ladder?" at all
four entry points so the answer cannot drift between them. The generic tail
needed one more clause, on DF-174a's argument: `_wrap_optional_tail` routes a
bare `None` at a declared `Result<T?, E>` through the same ladder, because the
Ok payload is an optional at every instantiation and so exactly one wrap is
right for all of them.
SWEEP (obligation 4), compiled AND run: 20 rows — the four entry points x the
tail shapes (bare, a value `if`'s arms, a value `match`'s arms) x {sync,
suspending}, plus a generic body, a generic STRUCT's method, an erased
`Result<T?, Box<any Error>>`, a closure whose tail is a value `if`, and the
`return` control. 8 failed before, 0 after. TWO faces, not one: the sync rows
were the codegen refusal, and the SUSPENDING tail rows COMPILED and then panicked
`force unwrap of None` inside `Task.join` — the tail normalization turns a tail
into a `return`, so the transform hid the refusal and left a task that stores no
result. CONTROL rows: a `None` at a Result whose Ok type is not an optional now
gives the same clean refusal at all four sites (the tail's used to be the codegen
message about a payload type, for a program whose real problem is the declared Ok
type).
Pins: `examples/result_optional_none_tail_types_itself.saw` (10 rows) and
`examples/errors/result_none_tail_needs_an_optional_ok.saw` (the refusal).
Docs: LANGUAGE_SPEC's four-return-targets section and the saw-lang skill's two
Result-tail paragraphs.
CONFORMANCE: none owed — a typing over-rejection plus one ICE, no guarantee
moves.

## DF-245a — an `init`'s DECLARED return type is never checked against the
## receiver, so a wrong one is an ICE (found while probing design 234 unit 3's
## constructor question)
## — CLOSED Aug 24 (branch `df-245a-fallible-init`, commit 2)

An `init` may be declared with ANY return type. The declaration is accepted, the
CALL is typed as the receiver regardless, and codegen then emits IR that does
not verify:

```saw
struct Other { m: Int }
extension Other {
    init(seed: Int) -> Int { return seed }        // accepted at the declaration
}
func main() { let o = Other(seed: 7)  print("{o.m}") }
// internal compiler error: LLVM IR parsing error
//   value doesn't match function result type '%Other = type { i64 }'
//     ret i64 %"seed.2"
```

MECHANISM (obligation 4): the two consumers of an `init`'s signature disagree
and nothing reconciles them. The CALL side derives the constructed type from the
RECEIVER and ignores the written return type; the BODY side checks `return`
against the WRITTEN one. Every other member kind has a declaration check that
ties the two together; `init` has none, so any return type that is not the
receiver is silently two different types. SIBLINGS the mechanism reaches, all
one funnel (the `init` declaration): a plain struct extension and a generic one,
`public` and private, and any wrong type — `-> Int` is the IR-verifier failure
above, `-> Result<Self, E>` is a `ResultErrWrap` ICE at the `return <error>`
inside the body, and the call site of the latter types as the bare receiver
(``cannot assign `Holder` to variable of type `Result<Holder, AllocError>` ``,
reported at the CALLER, about a signature the caller cannot see). Enums have no
`init`, so there is no second declaration site.

FIX SHAPE: refuse at the declaration — an `init`'s written return type must BE
the receiver (`Self` or the spelled receiver type, generic arguments included),
with the ordinary two-way fixit. Zero in-tree violations, so it costs nothing to
adopt. NOT fixed here: it is a new refusal with its own conformance row and is
outside design 234's units.

WHAT IT SETTLES FOR DESIGN 234: a constructor cannot be made fallible by
declaring `init(...) -> Result<T, E>`. So unit 3's allocating constructors —
`Vector(capacity:)`, `Data(capacity:)`, `Arc(value:)`, `Mutex(value:)`,
`Channel()` — must become STATIC factories returning `Result`, which is the same
shape their `try_` twins already have and turns "retire the prefix" into
"delete the `init`, rename the twin". That is a public-API change at 194 call
sites (counted below), not a signature tweak. [234]

RULED Aug 24 (user) and LANDED the same day, WIDER than the fix shape above: an
`init` may declare `Self`/the receiver (today's meaning) OR `Result<Self, E>`,
and nothing else. No `Self?` — an optional creation encodes as Result, since a
`None` names no cause — refused at the declaration with a fixit naming the
Result form. So a constructor CAN be made fallible after all, and unit 3 keeps
its `init`s instead of migrating 194 call sites to static factories; the two
paragraphs above are superseded on that point and kept as the record of why the
question was asked.

WHAT LANDED. ONE funnel, `_init_declared_return`
(sawc/typechecker/registration.py), whose docstring names its two entry points —
the DECLARATION side (`register_extension`, which reports) and the BODY side
(`_check_method`, silent). It answers `('receiver', None)` /
`('result', <type>)` / `('refused', <what the author wrote>)`; the receiver's
SPELLING stays each caller's own, because the two disagree on purpose (DF-216r).
A refused declaration is judged against the author's own type so the body is not
reported a second time for the same mistake. Argument comparison is by rendered
spelling and only where BOTH sides spell their arguments — `_ext_written_self_type`
bails out to the argument-free form for a CONST parameter, and std's
`extension FixedBuf<N>` writes `init() -> FixedBuf<N>` by hand.
The CALL SITE reads the matched init's registered return through
`_init_call_type`, at both construction positions (`_check_struct_init` and
`_check_module_struct_init`). CODEGEN lowers the declared return through
`_init_llvm_return_type`, at both prototype sites (`_declare_extension_methods`
and `_declare_monomorphized_method`), and both init body generators size their
undefined-fallback from the signature rather than the struct layout.
The SIGVIS hole the sweep found is closed with it: design 193's position matrix
SKIPPED an init's return (it could only name the receiver, so judging it only
restated the cap), and the fallible form names an `E` beside it — a
`public init(...) -> Result<Exposed, Hidden>` published a private error type
with no diagnostic. New row in `SIGNATURE_VISIBILITY_POSITIONS` + a row in
`examples/private_in_public_positions_error.saw`.
END TO END, probe-verified: `try!`, `try?`, a propagating `try`, `match
Ok/Err`, the `try(as ...)` routing clause, design 151's discard error, a NoCopy
receiver, a generic receiver, a const-generic receiver, default parameters, and
label-distinguished overloads. Conformance row A02. Tests:
`examples/init_fallible_result.saw`, `init_fallible_result_shapes.saw`,
`init_fallible_result_module_qualified.saw` (the second construction position),
`init_receiver_return_spellings.saw` (the control — every receiver spelling,
including the no-clause form nothing in the corpus writes), and three refusals
under `examples/errors/`. Zero in-tree migrations: all 118 `init` declarations
already name their receiver.

FOR UNIT 3, two things the sweep turned up that a flip will meet.
`codegen/collections.py` SYNTHESIZES a no-argument init CALL for a collection
literal (`resolved_init_params = []`) and takes the returned value as the
container, so flipping a container's nullary `init` needs that site taught
first. And the two construction checkers select an init differently —
`_check_struct_init` accepts a subset plus defaults (design 53),
`_check_module_struct_init` demands an exact set — so a fallible init with
defaults resolves at the bare spelling and not the qualified one.
Four findings filed: DF-251a (FIXED here, commit 1), DF-251b, DF-251c, DF-251d
(the suspending-`init` boundary this brief was asked to record). [234]

## DF-251a — a GENERIC extension's `init` body inherited the PREVIOUS
## function's cleanup state, so an unrelated `String_deinit` landed in it
## — CLOSED Aug 24 (branch `df-245a-fallible-init`, commit 1); PRE-EXISTING,
## verified by stash against the branch point 13f85716

`_generate_init_method_generic` was the one body generator that reset neither
the cleanup stack nor the drop flags nor `moved_variables`, and set no
`current_return_type`. Every explicit `return` in a body runs
`_cleanup_all_scopes()`, so a generic init containing one emitted whatever the
LAST-generated function had registered:

```saw
extension Label { init(text: String) -> Label {
    if text.len() == 0 { return Label(v: 0) }
    return Label(v: text.len()) } }
extension Wrap<T> { init(payload: T, mark: Int) -> Wrap<T> {
    if mark < 0 { return Wrap<T>(item: payload, tag: 0) }
    return Wrap<T>(item: payload, tag: mark) } }
// internal compiler error: LLVM IR parsing error
//   use of undefined value '%text.1'
//   call void @"String_deinit"(i8** %"text.1")
```
in `Wrap$1$Int_init_payload_mark`, which has no `text`. Needs THREE things at
once, which is why it sat unnoticed: an earlier init with an OWNING param, a
generic init after it, and an explicit `return` in that generic body (a bare
tail asks for no cleanup). Found landing DF-245a, whose fallible generic init
returns twice by construction; nothing about the fallible form is required.
LANDED: the state is saved, cleared and restored exactly as
`_generate_method_generic` does it. Regression test
`examples/init_generic_body_isolates_cleanup_state.saw`. [234, 245]

## DF-245b — `try!` PANICS WITHOUT THE ERROR IT WAS HANDED, and design 234
## makes it the corpus's mass-migration spelling
## — CLOSED Aug 22 (branch `diag-batch`, commit 1)

```saw
func fails() -> Result<Void, AllocError> { return AllocError(size: 64, align: 8) }
func main() { try! fails() }
// panic at trybang.saw:8: try! failed
```

`AllocError` is `Printable` (every `Error` is), the value is right there, and
none of it reaches the message: `sawc/codegen/results.py:102` emits the fixed
string `"try! failed"` and drops the payload.

WHY IT MATTERS NOW rather than as a papercut. Design 234 retires the panic tier
by making the infallible ops return `Result`, and the behavior-PRESERVING
migration for a call site that does not want to handle OOM is `try!`. Today
`v.push(x)` panics `Vector.push: allocation failed`; after the flip
`try! v.push(x)` panics `try! failed`. That is the same failure reported worse,
at every one of the 1434 sites counted below — the flip would trade a precise
cause for none, which is the opposite of what it is for.

MECHANISM (obligation 4): `_emit_panic` is called with a literal, so nothing
about the error VALUE is consulted — it is one site, and the sibling forms are
already better. `main`'s `Err` exit prints the error through its vtable (design
221) and `try? `/`try`/`catch` all hand the value on; `try!` is the only
consumer of a `Result` that throws the payload away. So this is a single
missing rendering, not a family.

FIX SHAPE: render the error after the fixed prefix when `E` is `Printable`
(`panic at F:L: try! failed: allocation of 64 bytes (align 8) failed`), through
the stack-scratch builder design 137 already uses for panic assembly, so the
alloc-free and denied-allocator paths keep working. `E` is not bounded
`Printable` at the `try!` site, so a non-Printable `E` keeps today's text.
NEEDS A RULING on the exact wording, and it CHANGES A PIN
(`examples/try_force_panic.saw` expects `try! failed` verbatim). [234, 19]

LANDED Aug 22, in the fix shape above and at that wording:
`panic at F:L: try! failed: <error>`. `_generate_try_force`'s literal
`_emit_panic` became `_emit_try_force_panic`, which renders the extracted Err
through `_render_argument` — design 137's ONE format walk, the same one
`print("{}", e)` and the checked-cast panic (`cast to UInt8 out of range: 1000`)
already use, which is why the message is alloc-free by construction rather than
by a second copy of the rule. `_render_argument`/`_render_via_format` gained the
`in_entry` knob `_render_int_value` already had, and the `try!` path passes
False: a panic block ends in `unreachable`, so a function that merely CONTAINS a
`try!` pays no frame bytes for the 512-byte Printable scratch.
MATRIX (probed, `.build/scratch/df245b_matrix.saw` + `_suspend.saw`): a
`Printable` struct, a `Printable` enum at a `Result<Void, E>`, an erased
`Box<any Error>` (renders through its vtable), a `String` error, an `Int32`
error, and a NON-Printable struct (keeps the bare text) — plus a `try!` in a
suspending body over a suspending subject, and the whole file under
`--no-hidden-alloc`.
SWEEP (obligation 4): the mechanism is "a compiler-emitted panic that HOLDS the
offending value and reports fixed text". Census of `_emit_panic`'s callers — the
force-unwrap of `None` has no value (that IS the failure), and division by zero
/ integer overflow / shift range report a CONDITION, not a payload; the checked
CAST already renders its value and is the precedent this follows. One position
remains and is filed rather than invented: the fixed-array bounds panic
(DF-249a below) holds the index and the length and prints neither.
PINS: `examples/try_force_panic_names_the_error.saw` (the rendering row) beside
`examples/try_force_panic.saw`, whose non-`Printable` `ParseError` is now the
FALLBACK row and says so. Spec's Runtime-Semantics list, README's error section
and the saw-lang skill all carry the new message.
CONFORMANCE: no row owed — this is diagnostic quality on an already-trapping
path, not a safety guarantee (what `try!` DOES on an `Err` is unchanged).

## ~~DF-249a — the FIXED-ARRAY bounds panic holds the index and the length and
## prints neither~~ (filed Aug 22, DF-245b's sweep) — **FIXED Aug 24** on branch
## `resolution-wording`, commit 1, as the whole WORDING FAMILY the ruling asked
## for

`a[i]` out of range on a `[Int; 4]` is `panic at f.saw:9: index out of range`,
and the two numbers that would make it actionable are both in hand at the trap:
the index is the value just compared, and the length is the compile-time
constant it was compared against (`_emit_array_bounds_check`,
`codegen/operators.py:283`). The checked CAST next door already renders its
operand (`cast to UInt8 out of range: 1000`, design 170) through the alloc-free
format path, and DF-245b just put `try!` on the same footing, so the machinery
and the precedent both exist — `index 7 out of range: length 4` is one
`_render_int_value(..., in_entry=False)` plus a constant.
NOT the same finding as DF-245b (that one dropped a value it was HANDED; this
one declines to report a value it COMPUTED), which is why it is filed rather
than ridden. Wants a wording decision before it is written: whether the length
belongs in the message at all, and whether std's own hand-written accessor
panics (`Vector.[]: index out of range`, authored in Saw) should follow. [122,
170, 63]

**FIXED Aug 24** (branch `resolution-wording`, commit 1). ONE WORDING FAMILY,
`<what>: index out of range: <i> (len <n>)`, spelled by every bounds panic in
the language; a range/slice accessor spells both bounds
(`String.substring: range out of range: 5..2 (len 5)`). The compiler trap is
`array: index out of range: 7 (len 4)` — `array` is the only name a fixed array
has, and the `<what>:` slot stays uniform rather than growing a second shape for
the one non-method site.
MECHANISM (obligation 4): "a bounds check that HAS both numbers and reports
neither", which is exactly DF-245b's mechanism one position over. The census is
the funnel plus the prologues, and it is closed: ONE compiler funnel,
`_emit_array_bounds_check` (8 call sites — read, write, compound write, `swap`'s
two indices, the pointee-region arms), and THIRTEEN std prologues —
`Vector.[]`/`with_ref`/`with_var_ref`/`set`/`swap`(×2)/`swap_out`,
`Data.[]`/`set`/`try_set`, `String.byte_at`/`substring`, `FixedBuf.get`/`set`.
`Vector.swap` was the one shape the wording did not fit: a joint `i or j` check
has two candidates and no way to name the guilty one, so the two indices are
checked separately now. `get`-shaped accessors are untouched by construction —
they return `None`/`Err` and raise nothing.
The index is rendered at its OWN signedness, not the unsigned reading the
compare folds it to, so `a[-1]` says `-1` rather than 18446744073709551615.
ALLOC-FREE by construction, not by a second copy of the rule: the compiler side
goes through `_emit_runtime_panic` + `_render_int_value(in_entry=False)` — the
same three lines the checked cast and DF-245b's `try!` use — and the std side
through design 137's `{}` panic arguments, never interpolation.
ARITHMETIC TRAPS EXCLUDED (ruled): overflow, shift range and division by zero
report a CONDITION rather than an index into something with a length, and keep
their fixed text. Recorded in `_emit_array_bounds_check`'s docstring and in the
spec's accessor-rule section, which is where the family is documented.
PINS: 18 updated to assert the full new message (they were `-CONTAINS` prefixes
that would have passed unchanged — updating them is what makes the payload
tested), plus one new file `examples/fixedbuf_get_oob_panic.saw`: the const
generic `N` as the length, under `--no-hidden-alloc`, which pins the alloc-free
claim where it matters. Spec's accessor-rule section gained the family (with the
arithmetic exclusion), the runtime-semantics array bullet and the `#lend_var`
example follow it, and the saw-lang skill teaches the house wording for a
hand-written accessor.
CONFORMANCE: no row owed — diagnostic quality on an already-trapping path, the
same disposition DF-245b recorded. Rows T10/T11/T25 keep their guarantee and
had their expected text updated in place.

## ~~DF-245c — ONE SPAWNED TASK ANYWHERE stops every `return None` at a
## `-> Result<T?, E>` from typing, in functions that task never calls~~ —
## **FIXED Aug 22** on branch `transform-typing`, commit 1

```saw
func poll(n: Int) -> Result<Int?, Stop> {
    if n == 0 { return None }        // fine on its own
    return n
}
func worker() -> Int { yield_now()  return 7 }   // never calls `poll`
func main() {
    var group = TaskGroup()
    let h = group.spawn(worker())                // <- adding this breaks `poll`
    print("worker {h.join()}")
    match poll(0) { case Ok(o) -> print("{o ?? -1}"), case Err(e) -> print("{e}") }
}
// error: cannot tell what this `None` is a `None` OF — no annotation, parameter,
//        field, return type or element type in scope fixes its payload type
//   --> line 2, a line the transform never touched
```

MECHANISM (obligation 4): sawc typechecks TWICE, and the SECOND pass — over the
post-transform AST — does not push the peeled `Ok` payload onto a `return`'s
`None` the way the first does. Anything that makes the coroutine transform RUN
turns the second pass on for the whole module, so the trigger is global while
the symptom is local. Probed four ways: `poll` alone compiles; `poll` plus a
suspending function that is never spawned compiles; `poll` plus a spawned task
that CALLS it fails; `poll` plus a spawned task that does NOT call it fails. So
it is the transform running, not the call graph.

SIBLINGS the mechanism reaches: every position where the first pass pushes an
expected type that the second does not re-derive. `return None` at
`Result<T?, E>` is the one design 234 hits; the family to sweep is the rest of
`_stamp_return_literal_types`'s work (bare literals at fixed widths, optional
payload adoption) under a spawned task. NOT probed here — that sweep belongs to
the fix brief.

RELATED, and NOT the same: DF-244b is the sync-only residue (a bare `None` TAIL
that cannot type itself where `return None` works). This one breaks `return
None` too, and only with a spawn present.

Pin: `examples/result_optional_none_survives_the_transform.saw` (XFAIL).
Workaround, which std.channel now uses: an annotated local
(`let absent: T? = None  return absent`). Design 234 §4 makes `Result<T?, E>`
the shape of every non-blocking poll, so the flip meets this immediately.
[234, 244]

**FIXED Aug 22** (branch `transform-typing`, commit 1). The mechanism as FOUND
is narrower and more mechanical than "the second pass does not re-derive": the
contextual annotation was written to `resolved_type`, which is the very field
`_check_expression` stamps generically on every node it visits, so the design-146
second pass ERASED it — and the branch that had written it (the DF-140d `return`
route into `_prepare_ok_payload`) could not re-run, because its own first-pass
rewrite into a `ResultOkWrap` is what it keys on. `_apply_literal_expected_type`
case (0) had already met this and chosen the durable field, `expected_type`; the
OTHER contextual-`None` funnel, `_propagate_optional_type`, had not. It now
stamps both, and its docstring names its nine entry points.
SWEEP (obligation 4): 18 return-position rows x {no spawn, spawn}, compiled AND
run — the rest of `_stamp_return_literal_types`'s work, as the entry asked.
Exactly five cells failed, all one shape (a `None` inside a synthesized
`ResultOkWrap`): a free function, a method, a suspending body (which failed with
or without a spawn — a suspending body IS the transform running), the arms of a
value `if`, and a generic body. Everything else in the family survives already,
and for one reason: a fixed-width literal, a collection literal, a struct field
`None`, a Vector-element `None` and a plain `-> T?` `None` are all stamped
through `_apply_literal_expected_type`'s durable field, or sit in a position
whose annotating path re-runs unchanged on the second pass. Pin FLIPPED to a
passing test carrying all five rows. Two unrelated findings fell out of the
sweep and are filed separately: DF-250a, DF-250b.

## ~~DF-245d — a PROPAGATING `try` in an optional-binding SCRUTINEE inside a
## SUSPENDING body is refused~~ — **FIXED Aug 22** on branch `transform-typing`,
## commit 2; the rule is about CONTAINER HEADS, not the binding forms

```saw
while let v = try step(i) { ... }    // inside a spawned/driven body
// error: `try` cannot propagate errors from a function returning `Poll`
//        (must return Result)
```

MECHANISM (obligation 4): the same one DF-244a named, at the positions its
sweep did not reach. `_lower_stmt` dispatches a propagating `try` to design
196's error landing BELOW the control-flow ladder; DF-244a moved the `return`
branch (and block tails) to defer to it, and the optional-BINDING branches —
`while let`, `if let`, `guard let` — still lower in place with the `try` inside
`resume() -> Poll`, where the propagation target is read off `Poll`. Probed:
all three are fine in a SYNC body and all three are refused in a suspending
one; a plain `let v = try f()` in a suspending body is fine, which is what
makes it a rule about the binding forms rather than about expressions.

Design 234 §4 makes this the natural drain loop — `try` peels the error
channel and `while let` peels the optional — so the flip meets it on its first
consumer. Pin: `examples/suspending_binding_scrutinee_propagates_a_try.saw`
(XFAIL, both the `while let` and `if let` rows).
`examples/while_let_channel_drain.saw` spells `try!` and cites this entry.
[196, 234, 244]

**FIXED Aug 22** (branch `transform-typing`, commit 2). The sweep WIDENED the
rule and CORRECTED the entry's claim above: it is not about the binding forms,
it is about CONTAINER HEADS — the one place an expression sits outside every
block its construct owns — so the fix is one clause on design 224's head lift
(`_hoist_container_heads`, via the new `_head_must_move`), which already moves a
head that SPANS a suspension and now moves one that carries a propagating `try`
for the same reason. That is DF-244a's second half at the other position:
`_norm_block` had to call a try-carrying TAIL "spanning" because the lowering
keys on STATEMENTS and the landing dispatch wraps one.
SWEEP (obligation 4), all compiled AND run:
  * 3 binding forms x 6 expression shapes (plain, argument, receiver, binary
    operand, `match` subject, `??` RHS) x {sync, suspending, suspending with a
    spanning body} = 54 cells. ALL 18 sync cells passed and 30 of the 36
    suspending cells FAILED, in the two faces DF-244a named: the `Poll` refusal
    and ``Cannot create Result.Err outside Result-returning function`` (an ICE,
    a face this entry had not recorded). The 6 that passed are the one cell the
    entry mis-generalised — `if let` whose branch does NOT span, which is not
    CFG-split and so reached the landing dispatch already. That is also why
    `while let` fails even with a body that suspends nowhere: design 127's op
    budget makes every loop in a task body span.
  * the OTHER 4 head kinds `control_heads` enumerates — an `if` condition, a
    `while` condition, a `for` range endpoint, a `match` scrutinee — x {sync,
    suspending, suspending-spanning} = 12 cells. Two failed the same way, and
    they are siblings the entry never named.
  * a SECOND clause was needed and is its own finding-shaped thing: the lifted
    temp must be a frame FIELD. `_collect_frame_locals` already forces residency
    inside a SPLIT try/catch, for the stated reason that a `let` lowered behind
    a landing pad is scoped to the pad's synthesized `try { }` and invisible to
    the statement after it — and the PROPAGATE landing (no enclosing catch) has
    no such marker. A `let` carrying a propagating `try` now asks for itself.
    Without it the two head shapes whose container is lowered IN PLACE (an `if`
    condition, a `match` scrutinee, in a body with no other suspension) failed
    with `undefined variable __head0`; with it every cell above is green and
    every answer matches its sync twin.
All 66 cells green after the fix. Pin FLIPPED and rebuilt as 7 rows x {Ok, Err}
covering the three binding forms, a `try` NESTED inside a larger head, and the
other three head kinds. `examples/while_let_channel_drain.saw` got its honest
spelling back — `consumer` returns `Result<Int, ChannelError>` and drains with a
plain `try`. Docs: LANGUAGE_SPEC's design-196 propagating-`try` bullet and the
saw-lang skill's container-head + channel-drain paragraphs.
CONFORMANCE: none owed — a typing/lowering over-rejection, no guarantee moves.

## ~~DF-257e — conformance K90 pinned a THREAD RACE, through directives its own
## header said must not pin one~~ (filed + FIXED Aug 25 by design 234 unit 3;
## PRE-EXISTING, from design 242 unit 3b)

`examples/conformance/K90_thread_detach_is_a_fate.saw` asserts five lines with
`EXPECT-OUTPUT-CONTAINS`, two of which are printed by DETACHED OS THREADS. Its
header says so out loud — "their order against `detached`/`chained` is not a
property of the language and must not be pinned as one" — but design 158 made
`EXPECT-OUTPUT-CONTAINS` ORDER-CHECKED, each match starting where the last one
ended, because order is half of what a structured dump asserts. So the file
pinned exactly the order it declared unpinnable, and passed only while the
spawner happened to win both races. It lost one here, on an unrelated branch,
with a 35-second suite run:

```
detached / chained / ticket 2 released / ticket 1 released / main is finished
```

MECHANISM (obligation 4): an order-checked directive over output whose order is
a race. The siblings are every other MT test that reaches for CONTAINS — the
class DF-246a already ruled on, whose three rules this file breaks two of (a
fixed 150ms `sleep` as the synchronizer, and no polling of the observation).

FIXED to that doctrine: both threads park on a `GO` gate the test controls
(a SPIN, not a sleep — a spawned thread runs no executor, so a suspension there
is a compile error), main opens it after its own printing, and then POLLS a
`RELEASED` counter with a 5-second ceiling that bounds genuine breakage only.
The two releases print the same text, so which thread finishes first cannot
decide anything; two identical directives still require two occurrences, because
the cursor moves past each match. Verified green on five consecutive runs.

WORTH KEEPING AS A RULE: a CONTAINS directive is an ORDER assertion. A test that
wants an unordered set of lines has to make the ORDER deterministic — there is
no unordered spelling, and adding one would weaken every structured-dump pin
that depends on the ordering. [158, 242, 246]

## Design 242 — the Thread/Task split (AUTHORED + fully RULED Aug 22; IN
## FLIGHT on branch `design-242`)

designs/242-thread-task-split.md is the plan of record and its nine rulings
are law. Status by unit:

- **Unit 0 (census) — DONE.** 43 real `Thread.spawn`-form sites (42 in
  `examples/` across 22 files, 1 in `sawc/std/taskgroup.saw`); zero in
  `blade/`, `libs/`, `sos/`, `devtools/`. 14 `TaskHandle` + 5 `VoidTaskHandle`
  mentions in `.saw` (8 of them real annotations, all `Vector<...>` element
  types). `Channel.recv` has ONE call site in the whole tree
  (`examples/channel_pipeline.saw`) against 82 `receive()`s. PROBE ON RECORD
  for unit 4: a suspending body handed to today's spawn form is neither
  refused nor driven — it compiles as ORDINARY SYNC CODE (no frame in the
  emitted IR), so a `yield_now()` inside it is a silent no-op; and a
  `blocking` extern called there already emits a DIRECT call inside the
  trampoline (no offload thunk), which is ruling 9's behaviour arrived at by
  accident rather than by a rule. One finding: DF-247a.
- **Unit 1 (the renames) — LANDED.** `spawn {}` -> `Thread.spawn {}`,
  `Task<T>` -> `Thread<T>` (+ the new `VoidThread`), `TaskHandle<T>` ->
  `Task<T>`, `VoidTaskHandle` -> `VoidTask`; std's internal `trait Thread` is
  `NativeThread`. Compiler-driven per 236: the bare `spawn { }` and both old
  type names are ERRORS carrying the new spelling (pins
  `examples/errors/spawn_names_its_engine.saw`,
  `examples/errors/retired_task_handle_names.saw`), no deprecation alias.
  `Thread`/`VoidThread` joined `COMPILER_EMITTED_STD_TYPES` (`Slot`'s
  carve-out, DF-218g), so the SPELLING stays the user's — which is what keeps
  SOS's own `struct Thread` compiling; pin
  `examples/thread_name_belongs_to_the_user.saw`. Two findings: DF-247a,
  DF-247b.
- **Unit 2 (the consumption rules) — LANDED.** Rulings 5/6/9a/9b. ONE funnel
  (`typechecker/types.py`, entries named in its header) in two halves: a
  singleton spawn form's handle is BOUND to a local or CONSUMED where it is
  made (`Thread.spawn { }.join()`), and a bound handle reaches `join()`/
  `detach()`/`cancel()` on every path — per-path exactly as design 189's
  borrows are, with a nested-block consume undone on the way out. Both
  discard spellings refused, `let _ =` included (the one place design 151's
  blessed explicit discard does not apply); `return` is an exit and refuses
  the escape, which is ruling 5's function-local fence. 9a's storage
  discharge keys on the ROOT of the destination path declaring a hand-written
  `deinit`, which is what makes std's crew compile unchanged. 9b: `Thread<T>`
  and `VoidThread` deinits PANIC instead of joining. Conformance rows K78-K82
  (written first). CONSUMER SWEEP (obligation 2) found THREE corpus users of
  drop-join and no more: `task_join_on_deinit.saw` (the whole test WAS the
  retired contract — renamed `thread_fate_is_written_not_dropped.saw` and
  rewritten around the explicit join plus the chained spelling),
  `spawn_void_body.saw`'s `drop_path`, and `conformance/D11`, which is refused
  earlier and needed nothing. Suite 2181 pass / 4 xfail (unchanged),
  freestanding 31, corodiff clean.
- **Unit 4 (`Thread.spawn` semantics) — LANDED IN PART, rulings 8 and 9.** The
  body is a `sync` context (ruling 8) that PERMITS a `blocking` extern (ruling
  9), which is one decision about one context and is set in one place
  (`_effect_mark_thread_spawn_body`). Ruling 9 is a second fixpoint over the
  same graph — `suspends_ignoring_blocking`, `really_suspending`'s shape with
  blocking sources struck out — computed only when a blocking-permitted
  context exists, and the violation path skips blocking sources so it names
  the cooperative suspension that actually broke the rule. Both directions
  tested (conformance K83, K84 + its ordinary-sync control), and K84 pins
  "runs DIRECTLY" on the IR: design 103's offload machinery is absent.
  Ruling 8 turned unit 0's probe finding into a refusal, and the refusal
  immediately caught a corpus test that was passing VACUOUSLY —
  `funcpointer226_composites.saw`'s across-a-suspend section spawned onto a
  thread, so no frame was ever built and its `yield_now()`s were no-ops. Its
  claim does not hold on the cooperative engine either: DF-252a, filed with a
  seven-cell matrix and pinned XFAIL. Suite 2183 + the new rows, freestanding
  31, corodiff clean.
- **Unit 5 (docs) — LANDED for what units 2 and 4 shipped.** LANGUAGE_SPEC §6:
  the two-engines paragraph became the NAMESPACE rule (with the
  `Channel.recv`-from-a-task warning it always implied), plus two new
  subsections under Tasks and Channels — "No implicit fates" (the refusals,
  the 9a storage discharge with a compiling `Pool` example, the group control,
  the 9b panic quoted from a real run) and "The thread body" (rulings 8 and 9,
  both with their real diagnostics). README gained the second-engine example
  and the recommendation gradient; the saw-lang skill gained the two rules and
  the gradient in its concurrency section. The spec says in one sentence that
  `detach()` is named by the diagnostics and not implemented yet, which is the
  honest state until unit 4c lands.
- **Unit 3 — LANDED (branch `design-242-c`, three commits), except the
  cooperative BRACE sugar.** Rulings 3, 4, 5/6/9b on the cooperative side, 7
  and 10's capture-list half. The brief's landing section is the record of
  every mechanism; the summary is that `Task.spawn(work(n))` is the call form
  ruling 10 named, the background group is an all-zero heap `TaskGroup`
  published by CAS and closed by a synthesized `main` wrapper, the 9b fault
  keys on a PROVENANCE bit rather than on the handle type, `detach()` landed on
  both engines (the thread side on one additive seam,
  `__saw_rt_thread_detach`), and a spawned brace now captures nothing
  implicitly. Conformance rows K85-K91. Suite 2206 / 5 xfail (unchanged),
  freestanding 31, sos 80, corodiff + abidoc + citations clean.
  - **STILL OPEN, ruling 10's other half:** the brace sugar for the two
    cooperative forms (`Task.spawn { [x] in ... }`,
    `group.spawn { [x] in ... }`). The blocker is the lifted function's RETURN
    TYPE — a Saw function with no declared return type is `Void`, so the lift
    cannot defer the question to the ordinary function checker, and the answer
    is not known until the body is checked. The two ways out (a sandboxed
    deepcopy check on design 70's pristine-template model, or a
    deferred-return-type mechanism for a synthesized declaration) are a shape
    to decide rather than to pick; the brief's landing section has the analysis
    and the probe. Ruling 10's enclosing-TYPE-parameter refusal belongs with
    the lift and not before it.
  - Two findings: DF-256a (a generic struct's fields invisible to codegen's
    type-order sort — FIXED here, it blocked the unit) and DF-256b (the thread
    control block's deallocation SIZE, pre-existing, open; entry below).
- **The widest edge of 9a's approximation, recorded for a possible tightening.**
  The discharge asks whether the destination path's ROOT type declares a
  hand-written `deinit`. std's `Vector` declares one, so `v.push(move t)` into
  a BARE LOCAL `Vector<VoidThread>` is discharged too — a local vector the
  author drains and joins is legal code that must keep compiling, and the
  checker cannot tell it from one that is forgotten. The forgotten one meets
  ruling 9b's panic at the element drop. The alternative reading (require at
  least one field hop from the root, so a bare container is refused and ruling
  5's "`Vector<Task<T>>` stays a group idiom" sentence holds literally) is a
  ruling, not a fix, and is left to the user.

## Design 234 — the fallibility flip (RATIFIED Aug 17; QUEUED behind the
## three in-flight Aug-17 branches)

designs/234-fallibility-flip.md is the plan of record: every failable op
returns Result (design 123's panic tier retired, the ~16 alloc try_ twins
with it), three-tier error doctrine (narrowest leaf type / payload-carrying
compounds / Box<any Error> as the app-only tier), the prefix routing clause
`try(as LocalError.Alloc) f(...)`, `try_` reserved for non-blocking, the
fault-line and hidden-alloc boundaries. Resolves DQ-230b (try_send retires,
ChannelError gains Alloc). DISPATCH ORDER: after the kcore split, the
literal/const family and the small-fix batch all integrate — corpus-wide
touches conflict with everything; M3 unit 1.5+ may interleave with units 1-2
only. [234]

IN FLIGHT on branch `design-234`. Landed so far:
- **unit 0 — the consumer sweep**: the migration matrix is in the brief's
  landing section. Three corrections to the brief's own census, all recorded
  there: 19 alloc twins across 10 std files (not "~16 across nine"), FOUR of
  them with NO infallible twin at all (a rename, not a merge), and
  `try_receive`'s §4 shape is a CHANGE rather than a preservation.
- **unit 1 — the routing clause** `try(as ErrorType.Case) f()`: parser,
  typechecker (one chokepoint, `_check_try_routing`), codegen, the coroutine
  fence, 13-row position matrix + 10 refusals. RIDER **DF-232h CLOSED** by
  the funnel extraction the entry asked for (`_autowrap_into_result`, four
  named entry points), which also closes **DF-213b** — the same defect filed
  from another angle. Two findings filed: DF-244a (FIXED, its own commit —
  a propagating `try` in a `return` inside a suspending body) and DF-244b
  (open, the bare-`None` tail residue).

- **unit 2 — the error-type reshapes** (branch `design-234-b`, RULED Aug 22 =
  option 1, the additive seam): `__saw_rt_last_raw_code() -> word`, stamped by
  `__saw_rt_last_syserror` in both host bodies, PER-THREAD (pthread TSD, the
  op_budget idiom — errno is per-thread and MT groups classify on several at
  once). Recorded in ABI.md as an AMENDMENT to design 117's pin deviation with
  both of its grounds shown to survive. SOS: nothing to stamp (four seams, no
  OS-op family, no `last_syserror`), the ruled answer documented in ABI.md and
  `sos/rt/common/src/lib.saw` for when one lands. `IoError` is now
  `{syscall, kind: IoErrorKind, code: Int32}` — 21 kinds off the frozen tag
  table with `Other`→`Unknown` as the escape hatch, two factories
  (`of(syscall:tag:)` reads the seam, `of(syscall:kind:)` is the std-raised
  form whose code is 0), and only `kind()` reaches the rendered text so `"{e}"`
  stays platform-identical. `ChannelError` gained `Alloc(e: AllocError)`,
  rendering through the leaf. Pin `examples/io_error_kind_and_raw_code.saw`.

- **unit 3, CHANNEL sub-unit only** (the rest is blocked — see the two DF
  entries above this section): `send`'s allocator arm is `Err(Alloc(e))` and
  `try_send` retired. **DQ-230b is now EXECUTED**, not just resolved on paper —
  its entry sits in `done_aug18-aug25.md` saying "Executes with 234's Channel
  sub-unit", and this is that. Conformance row **A01** opens the alloc-tier
  section, which had zero rows.
- **unit 4 — the non-blocking family**: `try_receive` is
  `Result<T?, ChannelError>` (`Ok(None)` nothing yet, `Err(Closed)` closed and
  drained), over a new private `_take_one`; the transform's
  `__try_receive_result` seam is untouched by construction. 16 call sites
  migrated. §4's discipline audit finds the other two `try_` keepers already
  conforming — `SpinLock.try_lock -> R?` and `Once.try_get -> T?` are the
  no-error-path short form §4 blesses. `selfhost`'s `try_read_int_suffix` is the
  third in-tree meaning and stays out of scope (not std), as unit 0 recorded.

- **unit 5 — docs closeout, PARTIAL** (the half that is true after units 1/2/4).
  LANGUAGE_SPEC §5 gained "Error-type doctrine" (the three tiers, the
  no-stdlib-wide-enum rule, a pointer to the routing clause) and "`try_` means
  non-blocking" (§4's shape + the `T?` short form + the `try`/`while let` drain);
  the saw-lang skill and README carry the user-facing subset. THE TWO RULED
  BOUNDARY SENTENCES landed with it — the erased-error box panics because an
  error path cannot report an allocation failure without allocating, and
  `Data.[]`'s copy-on-write separation stays under the accessor rule with
  `try_detached()` named as the fallible spelling. NOT landable yet, because
  they describe unit 3's end state: marking design 123's sections superseded,
  and removing the `try_` twin table (18 of the 20 twins still exist).

**CENSUS CORRECTIONS to unit 0's own numbers**, both found by re-counting
against the tree, both recorded in the brief's landing section:
- the alloc twin family is **20**, not 19 — unit 0's own table lists 20 rows
  (4+7+3+1+1+1+1+2) under a heading that says 19;
- **FIVE** twins have no infallible partner method, not four — unit 0's own
  paragraph names five (`Vector.try_with_capacity`, `Vector.try_reserve`,
  `Data.try_with_capacity`, `Data.try_reserve`, `StringBuilder.try_with_capacity`)
  under a heading that says four. And each `try_with_capacity` DOES have a
  panicking partner, just not a method one: `Vector(capacity:)` / `Data(capacity:)`
  are INITS, which is the constructor question DF-245a below now answers — and
  since Aug 24 the answer is that an `init` MAY return `Result<Self, E>`, so
  those two flip in place instead of becoming static factories.

**THE COUNT UNIT 0's MATRIX NEVER TOOK, and unit 3's real size**: the matrix
counts the 56 twin CALL sites and the 24 std alloc-panic sites, but not the
callers of the INFALLIBLE ops those panics belong to — and design 151 makes
every one of them a compile error the moment `push`/`append`/`insert` return a
`Result`. Counted Aug 22: **1434** `.push(`/`.append(`/`.insert(`/
`.append_char(`/`.append_bytes(` sites (examples 902, sawc/std 115, the rest
417 across blade/libs/devtools/selfhost/sos), plus **194** constructor sites
(`Arc(value:)` 67, `Channel<T>()` 72, `Mutex<T>(value:)` 22,
`Vector<T>(capacity:)`/`Data(capacity:)` 33). Each needs a SPELLED disposition
(`try!` / `try` / `let _ =`), and which one is a decision the brief does not
make — `try!` reproduces today's behavior visibly, `let _ =` would hide the
failure the flip exists to surface. [234]

- **unit 3 — THE FLIP, COMPLETE** (branch `design-234-c`, four commits, Aug 25).
  Design 123's panic tier is retired; every allocating std op returns
  `Result<_, AllocError>`; 18 of the 20 twins retired into the operation they
  doubled, two renamed (`Vector.reserve`, `Data.reserve`), and the constructors
  flipped IN PLACE over DF-245a rather than becoming factories. The brief's
  landing section carries the 20-row twin table, the two hazards' resolutions,
  and the per-tree list of every non-mechanical site with its chosen spelling
  (the 205 precedent). Conformance A03-A17 plus Z01's re-read. ONE
  silent-unsoundness save: the Send-on-frames gate keys on the SHAPE of a
  group's initializer and could not see through the `try!` every
  `TaskGroup(threads:)` now needs, so it turned itself off everywhere — a
  `_unwrap_try` funnel fixes it and the five pinned Send refusals are back.
  Findings: DF-257a (recorded, not reached), DF-257b (owes a naming ruling),
  DF-257c and DF-257d (both PRE-EXISTING, both pinned XFAIL). Gates: suite
  2220/6 xfailed, freestanding both arches, citations, bootstrap, selfhostlex,
  bench, irdet --all, sos both arches.
- **unit 5 — docs closeout, COMPLETE** with unit 3: LANGUAGE_SPEC's "Allocation
  failure" rewritten around the one tier with a "Where a refusal still panics"
  subsection, the twin table deleted, the `Data`/`StringBuilder`/`Box`/slab
  sections de-twinned; the saw-lang skill's allocation section rewritten;
  README's allocation bullet and error-doctrine section carry the one-tier
  sentence.

**DESIGN 234 IS COMPLETE** — units 0-5 all landed. [234]

## DF-225a-f — six compiler findings surfaced by the doc-sync correctness
## scan round 2 (filed Aug 15; reconstructing LANGUAGE_SPEC.md examples
## against the real compiler, not grep — every example is a free fuzz
## input the sweep never asked for)

None of these are doc bugs — each is the compiler doing something the
doc-sync scan's reconstruction probes did not expect while verifying an
otherwise-correct LANGUAGE_SPEC.md example. Two (a, b) are ICEs (an
unhandled exception surfacing as `internal compiler error: ...` instead
of a clean diagnostic — the sawfuzz oracle's exact bar), which per
obligation 4 are PRESUMED a class until swept properly; the corroborating
positions below are from three independent probes (two different
sub-agents, one lead), not one lucky repro.

- **DF-225a — declaring a user `extern "C"` function under a name the
  compiler ALSO declares internally in codegen (`printf`, `abort`,
  `snprintf`, `strcpy`, `strcat` — `sawc/codegen/core.py` lines
  459/463/471/478/485) crashes codegen with `internal compiler error:
  <name>`, no location, even when the function is never called.**
  Reproduces in a bare one-declaration file, no import needed:
  `extern "C" { func printf(format: UnsafeConstPointer<Int8>, ...) -> Int }`
  alone ICEs; renaming to any non-colliding name (`myprintf`) compiles
  clean. Contrast: colliding with a std-declared extern (`malloc`, which
  `sawc/std/{file,directory,env,process}.saw` all declare with a
  DIFFERENT signature) gives a clean `function 'malloc' is defined
  multiple times with different signatures` — so the ordinary
  multi-declaration check works fine; only the codegen-internal names
  bypass it entirely and reach llvmlite's redeclaration path unguarded.
  Motivating case: LANGUAGE_SPEC.md's "C FFI" section (`Status:
  implemented`) used exactly `printf` in its worked example, which
  therefore ICE'd regardless of the (separately real, separately fixed)
  `malloc(size: UInt)` signature bug beside it — the doc-sync fix
  swapped the example to `puts`, sidestepping the collision rather than
  masking it.
  **CLOSED Aug 22 (branch `diag-batch`, commit 6).** SWEPT FIRST (obligation 4),
  and the sweep is what sized the fix: EVERY LLVM symbol codegen declares was
  probed with a user `extern "C"` of the same name — the five above, the two
  `_libc_func` declares lazily (`memcpy`, `strlen`), a runtime seam
  (`__saw_rt_write`), a String helper (`__saw_string_len`) and a
  non-colliding control. Only the five ICE, and the reason is exact: every
  other compiler-declared symbol is ALSO declared as an `extern` in a std
  source, so the typechecker knows it and the ordinary multi-declaration check
  answers; the five exist only as LLVM declarations, so there was nothing to
  compare against and the second `ir.Function` reached llvmlite unguarded.
  FIX at the mechanism: `_declare_external_functions` registers the five in
  `self.functions` like every other compiler-declared symbol (so the extern
  pass's existing skip covers them) and records the TYPE each was declared with
  in `compiler_declared_c_symbols`; `_declare_extern_function` then applies the
  ordinary rule in the terms that decide correctness — the same LLVM signature
  UNIFIES, a different one is a clean, located refusal whose hint prints the
  compiler's own signature. LLVM types rather than Saw ones on purpose: an
  `UnsafePointer<Int8>` and an `UnsafeConstPointer<Int8>` are two Saw types and
  one C parameter, and refusing an author for choosing the other spelling would
  be arbitrary. `_extern_llvm_type` is the one construction both readers use.
  RIDER: `ExternFunction` gained the `source_file` every other declaration node
  carries (stamped by the parser), because two diagnostics anchor on it — this
  one and DF-181f's `blocking` disagreement — and both read it defensively, so
  a refusal raised while checking a DEPENDENCY named no file at all. Same family
  as DF-243b, one commit later.
  PINS: `examples/extern_c_compiler_declared_symbol.saw` (all five declared,
  `printf` actually CALLED through the shared symbol — LANGUAGE_SPEC's C-FFI
  example is writable again) and
  `examples/errors/extern_c_compiler_symbol_mismatch_error.saw`, whose
  `EXPECT-ERROR-ABSENT: internal compiler error` is what pins the ICE as gone.
  Spec's C FFI section documents both arms.
- **DF-225b — referencing an undefined struct name ICEs
  (`internal compiler error: Undefined struct: <Name>`, no location)
  in at least two independent positions, never a clean "undefined type"
  diagnostic:** an enum case's payload field type
  (`enum Reel { case Loaded(t: Tape), case Empty }` with `Tape` never
  declared — found independently reconstructing LANGUAGE_SPEC.md block
  72, L2594), and a `sizeof<>` type argument
  (`static_assert(sizeof<UartRegs>() == 0x1C, ...)` with `UartRegs`
  declared only much later in a different section — LANGUAGE_SPEC.md
  L7480). Every OTHER undefined-name context hit during the same sweep
  (undefined module, undefined trait, unknown attribute, undefined
  function/variable) gives sawc's normal located `error: ...` — these
  two are the exceptions, which is exactly the "two positions, presumed
  a class" shape obligation 4 asks a fix brief to sweep before
  dispatch (other likely positions, unswept: a trait method's
  parameter/return type, a `type` alias RHS, a generic bound).
  **SWEPT Aug 21 (design 240 item 4) — the class is WIDER and has a second,
  SILENT face.** An undefined type name in an annotation is never diagnosed as
  one at all: it becomes an opaque type the checker carries, so an annotated
  `let` and a struct FIELD give a downstream mismatch about a type that does
  not exist (``cannot assign `Float` to variable of type `Float64` ``, plus a
  "not `Printable`" cascade), and a free FUNCTION SIGNATURE that reaches
  codegen gives the ICE — a THIRD ICE position beside the filed two.
  `Float64` and a nonsense `Nonesuch` behave IDENTICALLY, which is how item 4
  found this: the ruling asked for the `Float64` type-name registration to be
  removed and there is none to remove (see DF-225c below). The fix is one
  diagnostic, at the point a type NAME resolves, and its hard part is
  deciding when to fire: a GENERIC PARAMETER is also "a name the parser left
  as STRUCT" (`_is_abstract_type_param`), so telling a typo from a type
  parameter is a scope question rather than a table lookup. Wants its own
  brief.
  PIN: `examples/unknown_type_name_diagnostic.saw` (XFAIL; asserts a located
  diagnostic naming the type and NO internal compiler error, rather than a
  wording nobody has ruled on).
  **CLOSED Aug 21, design 241 unit 1** (branch `design-241`). One rule at the
  design-194 written-type funnel: ``error: undefined type `X` ``, located at the
  name. `_gate_resolved_type` asks the hidden-std question, then design 229's,
  then this one as the residue, so the specific answer wins wherever there is
  one. The scope question is answered by the type parameters in force (the
  declaration's own at the registration entries), the names the unit declares
  (registration is ordered and Saw is not), the namespace, and three fences —
  a const generic ARGUMENT written as a bare name, `Optional`, and the file
  being checked (a foreign generic's `R` resolves in the CALLER's body).
  `_register_trait` became the funnel's fifth entry, `_register_extension` now
  states its type parameters while it resolves signatures, and DF-174d's
  duplicate `_check_type_name_resolves` retired. Pin un-XFAIL'd and grown into
  the nine-row position matrix. Cascade suppression was NOT attempted — see
  the boundary in designs/241-undefined-type-names.md.
- **DF-225c (RULED Aug 20, user: FLOAT ONLY — reading 2, sharpened: `Float`
  is THE float type, the `Float64` name is dropped/removed rather than
  wired; `Float32` stays a planned future narrower type; there is no
  `Double` and never was, probed same day. Spec doc half DONE Aug 20 —
  the alias claim, the primitive table, and every worked example now say
  `Float`; the CBOR wire-width sentence untouched. Compiler half PENDING,
  small-fix batch: remove the `Float64` type-name registration so the
  spelling errors cleanly.
  **CLOSED-AS-NO-OP Aug 21, design 240 item 4 — THE PREMISE WAS WRONG.**
  There is no `Float64` type-name registration: the name appears nowhere in
  `sawc/` outside a `std/cbor.saw` comment about CBOR's own float items, and
  `BUILTIN_TYPES` (parser/types.py) lists `Float` and no other float. The
  ruling's compiler half is therefore already in force — `Float64` names
  nothing — and what is left of the filing is not about `Float64` at all: an
  UNDEFINED TYPE NAME is not diagnosed as one, which is DF-225b's class and
  is filed there with the sweep, the third ICE position and the pin. Probe of
  record: `Float64` and a nonsense `Nonesuch` produce byte-identical
  diagnostics in every position tried. No compiler change landed here, and
  none is owed under this number. DOC RESIDUE swept Aug 21 by design 241:
  the Aug-20 doc half missed ELEVEN worked-example occurrences of `Float64`
  in LANGUAGE_SPEC — unit 1's new diagnostic turns each into a hard error
  rather than a cascade, so they now read `Float`; the two occurrences left
  are prose about the name and are correct.) — original filing:** `Float64` cannot be produced
  by any literal, cast, or arithmetic, contradicting LANGUAGE_SPEC.md's own
  "`Float` // Alias for `Float64`" claim (lines 669-670, 690-692, stated as
  `implemented`).** `let x: Float64 = 1.0` fails with `cannot assign
  'Float' to variable of type 'Float64'`; `(1.0) as Float64` fails with
  `cannot cast 'Float' to 'Float64'`; two `Float64` operands refuse `+=`;
  `Float64` has no `Printable` conformance. `Float` and `Float64`
  type-check as two distinct, non-interconvertible types today — either the
  alias direction regressed, or it was never wired up on the
  literal/cast/arithmetic/Printable paths. CORROBORATED at scale, two
  independent probes: falsifies LANGUAGE_SPEC.md's Type System `Point`
  example (line 146, block 4) AND, at wider scope, the identical `Point`
  example reused in "Type Extensions" (line ~2158, block 58) — substituting
  `Float64` throughout either produces double-digit cascading errors;
  substituting `Float` compiles and runs clean both times. Two readings:
  (1) `Float64` should be wired as a true alias and the compiler has the
  gap (the doc's own design intent, matching its own primitive-types
  table); (2) the doc is describing an aspiration that was never built and
  every `Float64` mention should read `Float`. Left every LANGUAGE_SPEC.md
  `Float64` occurrence UNCHANGED pending this ruling — this is exactly the
  "spec promises X, compiler does Y, X is plausibly the design" case the
  doc-sync doctrine says not to decide alone.
- **DF-225d — an extension method on a PRIMITIVE that returns bare
  `self` fails type-check against its own declared return type with a
  message naming the identical type on both sides**:
  `extension UInt8 { func encoded(&self) -> UInt8 { self } }` →
  `error: method 'encoded' should return 'UInt8' but returns 'UInt8'`.
  Substituting a literal (`5u8`) for `self` compiles clean, isolating it
  to `self`'s inferred type inside a primitive extension not unifying
  with the primitive type it visibly is. Falsifies LANGUAGE_SPEC.md's
  "Conformances on primitives" worked example (block 153, L5051).
  **CLOSED Aug 22 (branch `diag-batch`, commit 7).** MECHANISM: three maps held
  one fact — "which written names are primitives, and which `TypeKind` each IS"
  — and design 176 (DF-169d) widened TWO of them from {Int, Float, String} to
  all thirteen. The typechecker's `PRIMITIVE_EXT_SELF_KINDS` stayed at three, so
  inside `extension UInt8` the receiver was a STRUCT named "UInt8" while the
  return annotation was `TypeKind.UINT8` — the same type spelled two ways, which
  is why both sides printed identically.
  THE CLASS IS WIDER THAN THE FILING, probed
  (`.build/scratch/df225d_matrix.saw`): `self` was unusable as a value of its
  own type AT ALL on those ten. Beside the return, `self * 2` was ``operator `*`
  cannot be applied to `UInt8` and `Int` `` and `self == other` was ``cannot
  compare `UInt8` with `UInt8` ``; `not self` on a `Bool` and `self as UInt64`
  on a `UInt` failed too, so `Bool` and `UInt` — both in the OTHER two maps —
  were affected as much as the fixed-width integers. Int, Float and String were
  clean throughout, which is what made it look like a `UInt8` problem.
  FIX at the mechanism (obligation 1): ONE table,
  `ast_nodes.PRIMITIVE_EXT_KINDS`, whose docstring names its three readers —
  the typechecker's `_primitive_ext_self_type`, codegen's
  `_primitive_self_llvm_type`/`_primitive_ext_name`, and
  `Namespace._PRIMITIVE_CONFORMANCE_KEYS`, which is it inverted. The other two
  copies are now assignments to it, so a fourth primitive cannot be added to one
  and missed by another.
  PIN: `examples/primitive_extension_self_is_its_own_type.saw` — thirteen rows,
  four positions each (bare return, arithmetic, comparison, a bound reached
  through a conformance on the primitive), with Int/Float/String as the
  controls. The SPEC needed no change: its worked example is the repro, and it
  was right — the compiler was wrong. The skill's primitive-conformance bullet
  carries the note.
- **DF-225e (RULED Aug 20, user: reading 1 — `std/` comes OFF the bare
  import's search path; only `std.`-prefixed imports reach std sources, per
  design 150's uniform model, and the spec's documented collision
  diagnostic becomes reachable. Compiler fix PENDING, small-fix batch:
  module_resolver.py search-path split + a pin for the user-module-named-
  `data` case.
  **CLOSED Aug 21, design 240 item 5 (branch `design-240`).** The split is
  literal: `ModuleResolver` keeps `std_paths` beside `search_paths`, the
  `std.`-prefixed arm searches `std_paths + search_paths` and the bare arm
  searches `rel_dirs + search_paths` — one list became two, and the class
  docstring now states the order. Nothing else reads `search_paths`.
  PINS: `examples/import225e_bare_std_leaf_not_found.saw` (the bare `import
  data` with no user module of that name is one "module `data` not found",
  with an `EXPECT-ERROR-ABSENT: defined multiple times` — the cascade is what
  had to go: four errors about std's own `DataBuf` internals, pointing INTO
  std, about a collision the program never wrote) and
  `examples/module_tests/test_bare_import_user_module_named_after_std.saw`
  plus its sibling `data.saw` (a user module named after a std leaf resolves
  to itself, with `import std.data as sdata` reaching std beside it). Spec's
  Qualifier-collisions section says the second import names YOUR module.)
  — original filing:** a bare `import <name>`
  with no `std.` prefix silently resolves into `sawc/std/<name>.saw`
  when the name happens to collide with a real std leaf module.**
  `sawc/module_resolver.py`'s search-path list always includes `std/`,
  even for a non-`std.`-prefixed import, so `import data` (intending an
  unrelated user module) double-compiles `sawc/std/data.saw` alongside
  any real `import std.data`, producing a pile of "defined multiple
  times" errors rather than the clean "two imports bind the qualifier
  `data`" diagnostic LANGUAGE_SPEC.md documents for exactly this
  scenario (L7986-7990). Two readings, no evidence either way of
  original intent: (1) the doc is right and `std/` should never be on a
  bare import's search path, only `std.`-prefixed ones; (2) the
  fallback is deliberate (some blessed same-name-as-std-leaf
  configuration) and the doc's example is an accidental collision with
  a broader mechanism it didn't anticipate.
- **DF-225f (minor, compiler-robustness) — `@section(".vector_table")`
  on a mach-O target aborts the PROCESS via a raw LLVM fatal error
  (`LLVM ERROR: ... invalid section specifier ...`, exit -6), not a
  sawc-formatted diagnostic.** LANGUAGE_SPEC.md (L8412-8418) documents
  mach-O needing the `SEG,sect` section-name form instead of ELF's bare
  name but doesn't claim what happens if you get it wrong; a reader on
  macOS who copies the ELF-shaped form as written hits an LLVM crash
  instead of a compiler error naming the fix.
  **CLOSED Aug 22 (branch `diag-batch`, commit 7), ridden with DF-225d because
  the interception is twelve lines.** `_checked_section` is the one place a
  section name is validated, with its two entry points named in its docstring —
  the `@section` stamp on a `static` and on a function, which are the only two
  positions the attribute is legal in. On a mach-O triple a specifier with no
  comma is a clean `CodegenUserError` naming the declaration and BOTH two-part
  spellings; ELF is untouched, where a bare `.name` is right and a comma'd one
  is legal too. Checking before LLVM is the whole point: `report_fatal_error`
  kills the process, so there is no error for a front end to catch afterwards.
  PIN: `examples/errors/section_macho_specifier_error.saw`, which PINS the
  triple (`--target arm64-apple-darwin`) rather than inheriting the host's — the
  rule is a property of the object format, and an inherited triple would make
  the test pass on Linux by not applying. `EXPECT-ERROR-ABSENT: LLVM ERROR` is
  what pins the abort as gone. Spec's `@section` paragraph states the refusal.
- **DF-225h (RULED Aug 20, user, and CLOSED — no compiler work): `()` and
  `Void` stay DISTINCT; design 122/132's visible-Void rejection is
  ABSOLUTE (a `case _ -> Void` spelling was proposed and REJECTED — it
  would carve a position-specific exception into a deliberately absolute
  rule); `{}` is the do-nothing arm spelling and the spec's three `()`
  arms now use it. Doc fix landed Aug 20.) — original filing:** a bare `()` does not unify with `Void` as a
  match arm's "do nothing" value, though LANGUAGE_SPEC.md uses exactly that
  spelling three times** (`case Empty -> ()` / `case Nothing -> ()` twice,
  §4 Memory Management's NoCopy-enum and Copy-enum match examples, each
  beside a sibling arm calling a Void function). Lead-reproduced:
  `case _ -> ()` beside `case 1 -> use()` (`use` returning `Void`) gives
  `match arms have incompatible types: 'Void' and 'TUPLE'`
  (`.build/scratch/docsync2/verify_spec_a_voidtuple.saw`) — `()` type-checks
  as a genuine, distinct empty-tuple value, not a `Void` spelling, in this
  compiler. `case _ -> {}` (empty block) compiles clean in the identical
  position (`verify_spec_a_voidtuple2.saw`), so a working spelling exists;
  the question is which one LANGUAGE_SPEC.md's three occurrences should
  use, or whether `()`/`Void` unification is the intended design and the
  compiler has the gap.

## Queue records — the Aug 22-25 group (moved verbatim from [QUEUE] and [BACKLOG] at the Aug-25 tracker pass)

- ~~Design 234 — the fallibility flip~~ — **COMPLETE Aug 25**, units 0-5 all landed (unit 3 on branch `design-234-c`, four gated commits: conformance rows first, the two hazards, the flip, the edge rows + docs). Every allocating std op returns `Result<_, AllocError>`; 18 of the 20 twins retired into the operation they doubled and two renamed; the constructors flipped IN PLACE over DF-245a. The flip's own consumer sweep caught the Send-on-frames gate turning itself OFF at every `TaskGroup(threads:)` because its shape test could not see through the new `try!`. Findings DF-257a-d. Entry below. Original ruling and protocol kept here: (designs/234-fallibility-flip.md) — units 0-2, 4, 5 + channel sub-unit LANDED Aug 22; UNIT 3 RULED Aug 24 (user): PATH 1 — ~~fix DF-245a FIRST~~ **DF-245a LANDED Aug 24** (branch `df-245a-fallible-init`: fallible `init` is expressible; an `init` may declare ONLY `Self`/the receiver or `Result<Self, E>`, nothing else — no `Self?`, refused at the declaration; entry below), so unit 3 may now flip the constructors in place and is UNBLOCKED, THEN the flip as ratified (no factory migration). Migration protocol RATIFIED: examples/tests take `try!` mechanically (failure-path tests get real matches, flagged by name); sawc/std per-site with a propagate bias (`try!` inside std re-creates the panic tier); blade/devtools/tools/selfhost per-site, propagate bias, irdet+bench their own careful commit; every non-mechanical site listed in the landing section (the 205 precedent). Execution: DF-245a brief-let, then unit 3 as one dispatch
- ~~Place-window xfail family~~ — LANDED Aug 22 (branch `place-window-fixes`): DF-169h/DF-218i(+248d)/DF-218j closed, DF-232n pin resolved as superseded-by-ruling. ~~DF-218h~~ and ~~DF-248a~~ — CLOSED Aug 24 (branch `deferred-move`, one commit each) to their rulings: a non-escaping closure's `move` capture transfers WHEN THE BODY RUNS, and an assignment's RHS may read the target's own root while every other in-window naming keeps its refusal behind teaching text. One finding filed: DF-255a (the ESCAPING half of the capture double free, pinned XFAIL). Entries below
- ~~Diagnostics/codegen small batch~~ — LANDED Aug 22-23 (branch `diag-batch`, seven commits, nothing stopped): DF-245b, DF-238b (+ the checked-cast twin), DF-238c (+ a second face at the thread-assertion funnel, conformance B23), DF-243a (four operator families + the sos abi un-suffixing, byte-identical), DF-243b+DF-232g residue, DF-225a, DF-225d (self usable as its own type on all ten primitives), DF-225f ridden. One finding filed: DF-249a (bounds panic omits index+length — wording decision held). xfails -2, none added
- ~~Transform typing batch~~ — ALL THREE LANDED Aug 22 (branch `transform-typing`, one commit each, after 242 units 0-1 integrated): DF-245c (a bare `None`'s payload type now outlives the second typecheck pass), DF-245d (a propagating `try` in a container HEAD — the sweep widened the rule from the binding forms), DF-244b (the bare `None` tail, through design 234's ladder). Two XFAIL pins flipped (suite xfails 7 -> 5), two new passing tests added (DF-244b had no pin: `result_optional_none_tail_types_itself.saw` plus the refusal `errors/result_none_tail_needs_an_optional_ok.saw`). Two findings filed: DF-250a, DF-250b. Entries below
(User-reserved list RELEASED by user, Aug 21: DF-232h rides design 234 unit 1 as an implemented task — the auto-wrap ladder extraction is exactly unit 1's machinery; DF-217m's sync half is design 240's item 9, LANDED Aug 21. Neither is a hand fix anymore.)
- ~~DF-243a~~ — CLOSED Aug 22 (branch `diag-batch`, commit 4): the adoption ladder covers the mixed binop now, at all four operator families the sweep found (not just the comparison the filing named), so the Aug-17 bit-flag ruling costs no suffix anywhere. The sos rider un-suffixed 40 assert operands, proved byte-identical. Entry below
- ~~DF-243b~~ — CLOSED Aug 22 (branch `diag-batch`, commit 5), with the DF-232g residue in the same commit: one family, two layers. A module-level diagnostic falls back to the MODULE's source now, and a declared array length carries its own file into codegen. Entry below
- DF-243c — RULED Aug 22 (user): the DOC was wrong ("bit 8" is unrepresentable in a `UInt8`); doc-fix landed same day, lead-direct — the sentence now states the value AND the masking invariant it rests on (`PMP_PERM_MASK = 0x7` before staging). Wire format unchanged. CLOSED; entry below is the record
- (DF-238a CLOSED Aug 21 by the small-fix batch — entry below; DF-239b, its adjacent, is still open at the line above)
- ~~DF-238b~~ — CLOSED Aug 22 (branch `diag-batch`, commit 2): an integer renders at its own width now, through the new `_fmt_int_fn` funnel; the freestanding pin lost its XFAIL and grew to four rows. The sweep also fixed the checked-CAST panic, which truncated the same way. Entry below
- ~~DF-238c~~ — CLOSED Aug 22 (branch `diag-batch`, commit 3): a conformance query now walks the GLOB sources beside the qualifier bindings, through the new `coherence_search_namespaces` funnel. The sweep found a SECOND FACE at the same funnel — a declared `UnsafeSend`/`UnsafeSync` was lost the same way. Both pins flipped; conformance row B23. Entry below
- DF-239b — RULED Aug 24 (user): DECLARATION-TIME RESOLUTION — a trait requirement's parameter types resolve at registration IN THE DECLARING MODULE'S context (design 194's provenance rule; design 241's `_register_trait` funnel entry already resolves them for the undefined check — the fix STORES the result as design-144 identities on `TraitMethodSymbol`), and the deep check then covers every parameter whose stored type names no `Self`/associated type. This is the ruled "migrate rules into abstract bound vocabulary" direction from 218 unit 1.5 — the abstract error at the generic's own line stays the better error post-1.5. DISPATCHED Aug 24 (branch `resolution-wording`). Entry below, beside DF-239a
- ~~DF-239b~~ — CLOSED Aug 24 (branch `resolution-wording`, commit 2): a requirement's signature is resolved at `_register_trait` in the declaring module and stored on `TraitMethodSymbol`; the generic-bound call path checks every parameter that names nothing abstract once `Self` is substituted. Pin flipped, five tests added, the cross-module gated case verified in both directions, two auto-wrap/literal-adoption ICEs closed along the way. DF-169e (a static requirement on a type parameter) stays open and is named in the entry. Original ruling: DECLARATION-TIME RESOLUTION — a trait requirement's parameter types resolve at registration IN THE DECLARING MODULE'S context (design 194's provenance rule; design 241's `_register_trait` funnel entry already resolves them for the undefined check — the fix STORES the result as design-144 identities on `TraitMethodSymbol`), and the deep check then covers every parameter whose stored type names no `Self`/associated type. This is the ruled "migrate rules into abstract bound vocabulary" direction from 218 unit 1.5 — the abstract error at the generic's own line stays the better error post-1.5. Joins the pending dispatch group. Entry below, beside DF-239a
- ~~DF-232g RESIDUE~~ — CLOSED Aug 22 (branch `diag-batch`, commit 5): `Expression` declares a `source_file` annotation, stamped by a walk beside the length fold's, so a codegen-raised length refusal names its file. Entry below
- ~~DF-218x~~ — CLOSED Aug 22 (branch `df-218xy`, commit 1): the branch got a cleanup scope of its own, so `_cleanup_to_depth` reaches the binding with no fourth entry point. The sweep found FIVE leaking spellings, not two, and corrected two entry claims (the driven twin was already right; the tuple pattern was mis-scoped rather than leaked). Entry below; conformance K76
- ~~DF-218y~~ — CLOSED Aug 22 (branch `df-218xy`, commit 2) on the SYNC side, as the Aug-22 ruling directs: discard order is REVERSE-DECLARATION everywhere. The sweep found a SECOND forward loop — the destructuring `let`'s wildcard leaves — which was forward on both twins and moved with it. Pin flipped and extended to 11 rows; entry below; conformance K77
- ~~DF-244b~~ — CLOSED Aug 22 (branch `transform-typing`, commit 3): the ladder's ENTRY CONDITION was the defect, not its ordering — a bare `None` transfers into everything, so no tail site ever reached it. The decision moved INTO `_autowrap_into_result` and one predicate now answers for all four entry points. Entry below
- DF-247b — RULED Aug 24 (user), as a DESIGN 150 AMENDMENT with two halves: (1) a QUALIFIER is bound ONLY by the whole-module form (`import std.data`, renamed by `as`); the selective and glob forms bind exactly their named/bare surface and NO qualifier — the former bonus-qualifier reach becomes a refusal with the fixit naming the whole-module line (an undocumented dependency was exactly what 150's own braces idiom exists to prevent); (2) same-module combinations (`import std.data` + `.{Data}` or `.*`) become LEGAL and complementary, and with both imported the bare and qualified spellings are ONE TYPE in EVERY position (annotation, construction, generic arg, `&any` bound, extension lookup, conformance coherence) — pinned by a position matrix, since the pair is newly legal and DF-247b's fresh-identity mechanism could lurk on it. Obligation-2 census owed (any in-tree qualifier use whose only import is selective/glob gets its explicit whole-module line). DISPATCHED Aug 24 (branch `resolution-wording`, with DF-239b + DF-249a). Entry below
- DF-249a — RULED Aug 24 (user): YES to both, ONE wording family — every bounds/range panic (compiler traps AND std's hand-written accessor prologues) spells `<what>: index out of range: <i> (len <n>)` (range/slice variants spell both bounds); free via the design-137 format machinery, alloc-free everywhere. Arithmetic traps (overflow/shift/div-zero) deliberately EXCLUDED from v1 (operand-format questions, marginal value) — recorded, not forgotten. Mechanical sweep + pinned-string updates; DISPATCHED Aug 24 (branch `resolution-wording`). Entry below
- ~~DF-246a~~ — CLOSED Aug 24 (branch `harness-doctrine`, commit 1): the three ruled rules are TESTING.md's "Waiting in a multi-threaded test", with the park-on-controlled-gate idiom as its worked example, and BOTH members of the class are rewritten to it — each 10/10 byte-identical in isolation AND at loadavg 34, where the backtrace one also dropped from 3.9s per run to 0.01s. Entry below
- ~~DF-248a~~ — CLOSED Aug 24 (branch `deferred-move`, commit 2) to the ruling: the hoist widened from a window-opening RHS to any read of the root, and every other in-window naming keeps its refusal behind the teaching text. Entry below
- ~~DF-247b~~ — CLOSED Aug 24 (branch `resolution-wording`, commit 3): the design 150 amendment, both halves. One predicate (`_import_binds_qualifier`) inside the one binding site decides which form binds a qualifier; an unbound one is a refusal naming the whole-module line, in a type position and an expression position. The same-module pair is legal by construction and pinned position by position (conformance B24). Census: 5 files, 14 sites migrated — one of them in sos/, so the commit gated on sos_runner too. Consumer sweep moved the selective source into two new search lists rather than losing it; the first gate found two more walks the sweep had missed (the bare-name cross-module fallback, which is what 80 kernel builds died on, and the "not directly accessible" diagnostic), and the census probe had a string-interpolation blind spot it closed. Original ruling: (1) a QUALIFIER is bound ONLY by the whole-module form (`import std.data`, renamed by `as`); the selective and glob forms bind exactly their named/bare surface and NO qualifier — the former bonus-qualifier reach becomes a refusal with the fixit naming the whole-module line (an undocumented dependency was exactly what 150's own braces idiom exists to prevent); (2) same-module combinations (`import std.data` + `.{Data}` or `.*`) become LEGAL and complementary, and with both imported the bare and qualified spellings are ONE TYPE in EVERY position (annotation, construction, generic arg, `&any` bound, extension lookup, conformance coherence) — pinned by a position matrix, since the pair is newly legal and DF-247b's fresh-identity mechanism could lurk on it. Obligation-2 census owed (any in-tree qualifier use whose only import is selective/glob gets its explicit whole-module line). QUEUED for dispatch with DF-218h at the next free slot. Entry below
- ~~DF-249a~~ — CLOSED Aug 24 (branch `resolution-wording`, commit 1): one funnel (`_emit_array_bounds_check`, 8 call sites) plus 13 std prologues all spell `<what>: index out of range: <i> (len <n>)`; the range variant spells both bounds; `Vector.swap` split its joint check so the message can name the guilty index; the negative index reports at its own signedness. 18 pins updated, one added (`fixedbuf_get_oob_panic.saw`, const-generic length under `--no-hidden-alloc`). Arithmetic traps excluded per the ruling, recorded in the spec. Entry below
- DF-246a — RULED Aug 24 (user), the MT-TEST DOCTRINE, three rules: (1) a fixed sleep is NEVER a synchronizer (it may pace a poll loop, never establish state); (2) the awaited state must be STABLE once reached (workers park on gates the TEST controls — a channel nobody sends on, an Atomic the observer flips); (3) observe by POLLING the observation itself until the stable state appears, a generous deadline bounding only genuine breakage. No synchronized `dump_tasks` twin — its unsync character is a recorded feature. Execution: TESTING.md section (the three rules + the park-on-controlled-gate idiom), both flaky tests rewritten, DF-246a closes. Rides the DF-218h/247b/248a dispatch or the next harness batch. Entry below
- DF-248a — RULED Aug 24 (user): NO carve-out to the Law. The ASSIGNMENT-RHS face (`v[0].n = v.len()`) LEGALIZES via the design-193/DF-218j hoist (RHS-first is the documented order, so hoisting the read ahead of the target's window is semantics-preserving by rule); every OTHER in-window naming of the root (arguments, body reads) keeps its refusal, because the hoist there would run the read ahead of the accessor's PROLOGUE — an observable reorder of documented sequence. USER REQUIREMENT: the refusal carries TEACHING TEXT explaining the asymmetry (the two shapes look identical to an uninformed reader — the error must say WHY the assignment form works and this one doesn't, and give the one-line `let` hoist as the fix). QUEUED for dispatch with DF-218h + DF-247b. Entry below
- ~~DF-257e~~ — CLOSED Aug 25 (branch `design-234-c`, commit 4): conformance K90 pinned a THREAD RACE through order-checked `EXPECT-OUTPUT-CONTAINS` directives, against its own header. Rewritten to DF-246a's doctrine (a gate the test controls, then poll the observation); entry below
- ~~DF-225a~~ — CLOSED Aug 22 (branch `diag-batch`, commit 6): the five join the ordinary duplicate-declaration rule — same LLVM signature unifies (so `printf` is callable), a different one is a clean refusal. The sweep probed every compiler-declared symbol and found the five are exactly the ones std does not also declare. Entry below, under DF-225a-f
- ~~DF-225d~~ — CLOSED Aug 22 (branch `diag-batch`, commit 7): the three copies of "which names are primitives" became ONE table, so `self` inside a primitive extension is that primitive again. The sweep found the class is wider than the filing — arithmetic, comparison and `Bool`/`UInt` too, all ten design 176 added. Entry below, under DF-225a-f
- ~~DF-225f~~ — CLOSED Aug 22 (branch `diag-batch`, commit 7, ridden with DF-225d): a mach-O specifier with no comma is refused before LLVM sees it, at one funnel with both `@section` positions as its entries. Entry below, under DF-225a-f
(DF-225b closed Aug 21 by design 241 unit 1, 225c/225e by design 240's
batch, 225h Aug 20; 225a, 225d and 225f closed Aug 22 by `diag-batch` — their
closure notes live in the DF-225a-f entry below, which has nothing open left
inside it now and travels whole.)

## DF-256a — a GENERIC struct's own fields are invisible to codegen's
## type-registration order (filed + FIXED Aug 25 by design 242 unit 3a)

```saw
func work(n: Int) -> Int { yield_now()  n * 2 }
func main() -> Int {
    let a = Task.spawn(work(3))   // `a` lives across the suspension below,
    yield_now()                   //   so `__Frame_main` holds a `Task<Int>`
    a.join()
}
// internal compiler error: Undefined struct: TaskGroup
```

MECHANISM. `_register_types_in_order` (`codegen/core.py`) topologically sorts
the program's types before registering them, and builds the graph over
NON-GENERIC declarations only — a template has no layout, so `if
struct.type_params: continue`. A field of type `Task<Int>` therefore
contributed the name `Task` and stopped. But registering the CONTAINER asks
`_ensure_monomorphized_struct` to build the instantiation right there, and
`Task<T>`'s `group_ptr: UnsafePointer<TaskGroup>` needs `TaskGroup` registered
first. The edge exists and the graph could not see it.

Pre-existing, and invisible until now for a mundane reason: every program that
put a `Task<T>` in a frame also had a `TaskGroup` of its own, which ordered
`TaskGroup` for it. `Task.spawn` is the first spawn form with no group in
sight. It is the same class of failure design 33's array-element arm fixed (its
comment records the identical symptom, "Undefined struct", nondeterministic
under hash order) — a dependency edge the walk did not follow.

FIXED here: `get_deps` reaches THROUGH a generic name into the template's own
fields, guarded against a self-referential template. Substitution is not
needed — a field typed by a type PARAMETER names no registered type, and one
typed by a concrete struct names the same struct at every instantiation.
SIBLINGS the mechanism reaches, now covered by the same widening: any
non-generic struct whose field instantiates a generic that holds a concrete
struct, in either direction of declaration order. [33, 242]
- Design 242 — the Thread/Task split (designs/242-thread-task-split.md) — units 0-1 LANDED Aug 22; UNITS 2 + 4(part) + 5 LANDED Aug 24 (branch `design-242-b`: the consumption funnel per-path, 9a's storage discharge keyed on a hand-written-deinit root, 9b's panic on the two THREAD handles, the blocking-permitted sync context via a second fixpoint, docs; conformance K78-K84; the 9b probe corrected the census — three corpus sites migrated). UNIT 3 RULED Aug 24 (user, ruling 10 in the brief): the CALL form is the Task engine's primitive; the brace form is SUGAR with an EXPLICIT-CAPTURE-LIST requirement UNIFORM across Thread.spawn/Task.spawn/group.spawn braces (the list IS the parameter list; implicit captures = teaching error; ~42-site Thread-brace migration rides). Trailing-brace syntax briefed as design 243, BACKLOGGED. UNIT 3 LANDED Aug 25 (branch `design-242-c`, three commits): `Task.spawn` + the background singleton + the exit cancel-then-join, the cooperative must-consume with its PROVENANCE-keyed 9b fault, `detach()` on both engines (one additive seam `__saw_rt_thread_detach`), and the spawn brace's capture list with the 27-site migration; conformance K85-K91. ONE PART OPEN — the cooperative BRACE sugar (`Task.spawn { }` / `group.spawn { }`), blocked on the lifted function's return type; the brief's landing section has the analysis. Findings: DF-252a (FuncPointer called by name in a driven body, pinned XFAIL), DF-256a (fixed), DF-256b (open)

## ~~DF-232h — a closure's TAIL expression does not auto-wrap into a declared
## `Result` return type, though its `return` does and though the OPTIONAL
## analogue works~~ — **FIXED Aug 22** as design 234 unit 1's rider (found
## Aug 17 by DF-226e's fix, probed; RENUMBERED from the branch's DF-232d at
## integration — the kcore split claimed d-g first; SCHEDULED Aug 17 as a
## rider on design 234 unit 1, user)

LANDED as the extraction the entry asked for, not a second copy: the
Ok-vs-Err ladder is now `_autowrap_into_result` in
`sawc/typechecker/statements.py`, ONE funnel whose docstring names its four
entry points — a function tail, a method tail, a `return`, and the closure
tail that had no copy at all. The three hand-written copies are gone; each
caller keeps only its own wording for the outcomes that are errors at ITS
site, which is what lets a method, a function, a `return` and a closure each
name themselves. The if/match per-ARM reconciliation is deliberately NOT an
entry point, and the docstring says why (a different question, with no
ambiguity refusal, no erasure and no optional-payload peel). Matrix covered
row by row in the flipped pin `examples/closure_tail_autowraps_result.saw`
(Ok literal, Ok non-literal, Err, erased `Box<any Error>`, optional Ok
payload, the two controls, a value-`if` tail) plus
`examples/closure_tail_result_ambiguous_payloads.saw` for the refusal.
DF-213b above is the same defect filed from another angle and closes with it.
Residue filed as DF-244b (a bare `None` TAIL, which a NAMED body has too).
Original filing:

`run(f: { x in 12 })` against `(Int) sync -> Result<Int32, Bad>` is
``argument `f` expects `(Int) sync -> Result<Int32, Bad>` but got
`(Int) -> Int32` ``. NOT a literal-width problem and not DF-226e: a
non-literal `{ x in k }` for an `Int32` k fails identically, and the explicit
`{ x in Result<Int32, Bad>.Ok(value: 12i32) }` compiles. The closure return
path (`_check_closure`, sawc/typechecker/expressions.py ~11085) has an
`expected_ret.kind == OPTIONAL` branch that auto-wraps the tail in an
`OptionalWrap` and no `Result` counterpart, while a closure's `return`
statement goes through `_check_return_statement`, which shares the named
body's auto-wrap chain — so the two spellings of the same intent disagree.
MECHANISM/SHAPE OF A FIX (obligation 1): the Ok-vs-Err selection lives inline
in `_check_return_statement` (the `_result_autowrap_ambiguous` /
`_types_compatible(ok)` / `_types_compatible(err)` / erased-Err ladder). A fix
should EXTRACT that ladder into one funnel and call it from both the return
path and the closure tail, rather than growing a second copy — the matrix is
Ok side, Err side, the ambiguity refusal, the erased `Box<any Error>` target,
and an optional Ok payload needing `_prepare_ok_payload`. Workaround
meanwhile: write `return` instead of a bare tail. [226, DF-226e]

- ~~**DF-226f — a `static` of OPTIONAL type never auto-wraps its
  initializer**~~ — **FIXED Aug 17**, to the Aug-17 ruling: a deliberate
  refusal at the declaration, auto-wrap NOT added. `_register_static` asks it
  on the TYPE right after `_resolve_type`, before the initializer is looked at,
  so the bare (`= 7`), wrapped, `None` and NO-INITIALIZER spellings all meet
  one rule instead of four incidental outcomes. An ALIAS to an optional is
  refused too (it resolves to the static's own top-level type); an optional
  nested in a field, element or generic argument is untouched, and `unsafe
  static var` is not reopened.
  The refusal does NOT bail out of registration — it suppresses only the
  initializer checks and falls through, because returning early orphaned the
  symbol and made every later USE of the name draw a second, misleading
  ``static `SLOT` is declared after this point``. One error per declaration now.
  Tests: `examples/static_optional_type_refused.saw` (the bare-payload form),
  `examples/static_optional_type_refused_none.saw` (the `None` form — the row
  that shows this is not a repackaged type mismatch, since `None` IS assignable
  to `Int?`), and `examples/static_non_optional_types_unaffected.saw` for the
  negative rows.

- **DF-226c (v1 gap, deliberately not built) — construction form 2 accepts a
  BARE name, not a module-QUALIFIED one.** `import fpmod.{tripled}` then
  `let p: FuncPointer<(Int) sync -> Int> = tripled` works; under a whole-module
  `import fpmod`, the only spelling design 150 leaves is `fpmod.tripled`, and
  that is a clean but wrong refusal (``cannot assign `(Int) -> Int` to variable
  of type `FuncPointer<(Int) sync -> Int>` `` — note the missing `sync`: a
  qualified function reference is already typed as a FUNCTION so that calls
  work, and it drops the effect slot doing it). Not built because a qualified
  name is a THIRD construction site, not a third position of the existing one:
  `_check_member_access` types it at TWO places (the single-qualifier arm and
  the nested-module-chain arm), so form 2's checks — signature match, the
  `sync` context, the generic and overload refusals — would need routing
  through both, and a codegen path of its own for the address. That is a matrix
  to write, not a line to add. Workaround today is one word at the import
  (`import fpmod.{tripled}`). Worth doing when the kernel adopts the type in
  M3, where `sos` sysapi callbacks are cross-module by nature.

- **DF-226b (minor, cosmetic) — a `borrows` function type inside a GENERIC
  ARGUMENT is a bare parse error, not design 141's named refusal.**
  `func f(g: (Int) borrows -> Int)` says ``a function TYPE may not be
  `borrows` ``; `FuncPointer<(Int) borrows -> Int>` says `Parse error at
  1:33: Expected '>' after type arguments`. The committed-generic type parse
  does not accept the effect slot's `borrows`, so it never reaches the rule
  that has words for it. Both are clean errors and both reject the same
  program — this is a diagnostic-quality gap, not a hole. Pre-dates design
  226 (any generic taking a function type has it); noticed there because a
  `FuncPointer`'s argument is ALWAYS a function type in a generic argument.
