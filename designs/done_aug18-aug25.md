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
