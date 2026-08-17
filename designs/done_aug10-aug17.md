# Saw Tracker — Archived Recaps (Aug 10 – Aug 17, 2026)

Landed / closed / decided entries moved VERBATIM out of designs/todo.md
as of Aug 17, 2026. Section order and text are as found there; every
open item stayed in todo.md. Most entries date from Aug 10-17; the
older ones are here because their last open item closed inside that
window. ONE line was edited in the move: design 230's header still read
"awaiting integration" after it was integrated Aug 16. Append-only
history.

## Design 230 — channel waits become real parks (BUILT + INTEGRATED Aug 16)

Brief: `designs/230-channel-parks.md` (fully ruled), which carries the built
shape. Units landed A (the park), then C (explicit `close()` +
`receive`/`send` -> `Result<T, ChannelError>`), then B (the quiescent
deadlock report, transferred from design 225 D-e) — C ahead of B on purpose,
since B's report has to name the cooperative path it is the backstop for.
Conformance rows K63-K68. Channel SELECT is the named successor and was NOT
built. Two findings filed rather than decided: DF-230a and DQ-230b, below.

**Obligation-2 consumer sweep (run Aug 16, before any contract change).**
`receive`/`send` -> `Result` and the new `close()` are behavioral-contract
flips, so every holder of the old contract was enumerated first:

- **Where channels are used at all:** `examples/` (~45 files) and
  `devtools/dogfood/programs/` (3 files). `blade/`, `libs/`, `sos/`,
  `sawc/rt/` and `tools/` have ZERO `std.Channel` use. (SOS's
  `sos.Event.receive()` is a different type on the kernel's own wait/wake
  ABI and already returns a `Result` — prior art, not a consumer.)
- **`receive()` — ~50 call sites**, every one adapting to `try!`/`try`/
  `match`. Two shapes are NOT a drop-in wrap and were re-authored rather
  than sprinkled with `try!`: `K47_channel_receive_binding_and_try_heads`
  receives from a `Channel<Int?>` into an `if let`/`guard let` head and from
  a `Channel<Result<Int, Boom>>` into `try!` heads, so after the flip both
  face a doubled wrapper (`Result<Int?, ChannelError>`,
  `Result<Result<Int, Boom>, ChannelError>`) and need BOTH layers peeled.
- **`send()` — ~45 call sites**, every one a bare statement today. Design
  151 makes a discarded `Result` a compile error, so every one of them
  becomes an error at the flip; adapted to `try!` where the failure is a
  bug and `let _ =` only where the test is deliberately best-effort.
- **Untouched surfaces:** `try_receive() -> T?` (9 sites),
  `try_send() -> Result<Void, AllocError>` (1), `recv()` (1 site,
  `examples/channel_pipeline.saw`) and `try_make()`. `recv()` is the
  thread-blocking twin and out of the brief's scope; it gains only close
  awareness (a closed, drained channel must not block its thread forever).
- **Compiler side:** exactly ONE Channel-specific hook —
  `typechecker/expressions.py` stamps `MethodCall.is_chan_recv`, consumed at
  8 sites in `coro_transform.py` (the design-62 G3 inline lowering). That
  is the funnel unit A's wake reason and unit C's `Result` both travel
  through; nothing else in `sawc/` knows what a Channel is.
- **Docs stating the old contract:** LANGUAGE_SPEC.md (two worked examples
  plus the design-123 infallible-tier table), README.md (one worked
  example), the saw-lang skill (the `recv`-vs-`receive` entry and the
  narrow-hoist section). `TESTING.md` and `rt/ABI.md` say nothing about the
  contract. All updated; the new examples were compiled and run as written.

**One soundness hole found and closed during unit B, worth recording because
the walk looks complete without it.** The quiescent report enumerates every
way code could still run, and the frame walk accounts for two of the three
kinds of thread there are: WORKER threads (a mid-resume worker sets its
slot's `active`, an idle one has nothing to run) and THREAD-ENGINE tasks (a
counter, since no run queue knows about one). The third is the OWNER thread —
the one that creates the groups and runs ordinary program code between its
calls into the executor — and nothing about a run queue reveals whether it is
computing or waiting. An MT worker holding a channel-parked task would have
reported a deadlock while the owner was mid-computation on its way to the
send. `__saw_exec_in_executor` is the fix: a depth counter entered by the
ambient sweep, the single-frame park, an MT `join` and an MT `Deinit`, and
the report requires it nonzero. K68's fourth round is the regression.

## DF-229a — CLOSED (Aug 16): the silent selective-import miss

Fixed in f9b020e4 — the no-else bind loop became std's name-set-first
funnel, covering all three predicted gaps (missing name, PRIVATE name,
and the unchecked `type`-alias category); 2591d385 closes the DF-229b
sibling it exposed, the design-144 alias back-conversion that built its
type from the spelling.

## DQ-225n — RULING OWED: the deadlock report (design 225 D-e / unit 4) cannot
## be built as specified, because a cooperative CHANNEL WAIT IS NOT A PARK
## (filed Aug 16 by the design-225 dispatch, with measurement; unit 4 NOT built)

Design 225 unit 4 asked for a report at "the ambient scheduler's
nothing-runnable / nothing-parked / no-wake-source state". **That state is
unreachable, and the states that are the real deadlocks are not decidable.**

**Why unreachable.** `Channel.receive` is a `try_receive` + `yield_now` loop
(std/channel.saw:203), so a task waiting on a channel suspends with wake reason
0 — READY — and the scheduler requeues it at once. A wait that will never be
satisfied is therefore INDISTINGUISHABLE, at the scheduler, from a task making
progress: `__saw_exec_any_ready()` is true forever. Every other live state is
accounted for (`remaining < 0` is an io park with a registration, `> 0` is a
timer with a deadline), so `anylive && not io && deadline <= 0` cannot happen
and a report placed there would be dead code.

**Measured (`.build/scratch/d{1,2,3,4}_*.saw`, gitignored, 3 s bound each):**

| shape | outcome | CPU |
|-------|---------|-----|
| main receives from a channel nobody feeds | hangs | 100% of a core |
| an ST-group task does the same | hangs | 100% |
| an MT-group task does the same | hangs | 143% (two workers) |
| control: a task that only sleeps | exits 0 | 1% |

**Why a heuristic is not a substitute.** "Resumed N times with no state change"
would abort correct programs: design 127's op budget force-yields a pure-compute
loop exactly the same way, so a long computation and a permanent channel wait
present identically. An abort that fires on correct programs is worse than the
hang.

**What it needs first, and the ruling that is owed.** A channel wait must become
a PARK WITH AN IDENTIFIABLE WAKE SOURCE — a distinct wake reason carrying the
channel's identity, so the scheduler can ask "is there any live sender for this
channel, in either engine, on any thread". That is a change to the wake
vocabulary (`Resumable.wake_reason`, the transform's channel-receive lowering,
and both engines' scan), and it buys more than the report: a channel wait would
then cost 0% CPU instead of 100%, which is a bigger win than the diagnostic that
motivated it. It also has a real design question inside it — the "no live
sender" test needs a channel to know its sender count, which `Channel.copy()`
already tracks, but a sender that has not been created yet is not a
contradiction, so the predicate is "no live sender AND no task that could make
one", which may not be decidable either.

Sequenced AFTER design 225's remaining units; unit 4 is recorded in the brief as
blocked rather than skipped.

**RESOLVED (user, Aug 16): option (a) ruled — `designs/230-channel-parks.md`,
fully ruled (park + quiescent report + explicit close() with
`receive() -> Result<T, ChannelError>`); D-e's deliverable transferred
there; the sender-count worry dissolved in the quiescent state and was
CORRECTED for the per-channel case (unified Copy handles make roles
uncountable — close() is the mechanism). Dispatches after 225 integrates.
IN PROGRESS Aug 16 — see the design 230 entry at the top of this file.**

## DF-225m — SILENT WRONG ANSWER: an INCLUSIVE-range `for` in a suspending
## body drops its last iteration (filed Aug 16, found by design 225 unit 3's
## soak case; mechanism located, obligation-4 sweep run, NOT fixed here)

**FIXED Aug 16 (`9d3ca7d8` the lowering + the nine rows, `48aac3a2` corodiff's
`..=` axis).** Both halves as ruled below: the design-53 guarded step, not the
naive `<=` (verified — the naive spelling panics `integer overflow` on
`examples/coro_for_inclusive_range_int_max.saw`), and three range-`for`
contexts on corodiff's loop axis. The pin lost its XFAIL and carries all nine
rows beside their plain twins; the axis found four cells of DF-217n/DF-217p
the ledger had never recorded, each replayed as pre-existing.

**One line, and it is not a scheduler bug — `coro_transform.py:5562`
(`_split_for`) builds the loop header condition as a hard-coded `<`:**

```python
cond = BinaryOp(op="<", left=_self_field(var), right=_self_field(end_name))
```

`s.iterable.is_inclusive` is never read, so every `for i in a..=b` inside a
function the transform drives runs `b - a` times instead of `b - a + 1`. The
sync twin of the same loop is correct, so this is a TWIN DIVERGENCE of exactly
the kind corodiff exists to catch — and corodiff never caught it because the
harness emits no `..=` at all (`grep '\.\.=' tools/corodiff.py` is empty). That
coverage gap is half the finding: an inclusive range is not an exotic spelling.

**Obligation-4 sweep (`.build/scratch/p_incl_sweep.saw`, 9 rows, all one
mechanism — every row is wrong except the genuinely empty range):**

| row | shape | got | want |
|-----|-------|-----|------|
| 1 | literal bounds, spawned root | 10 | 15 |
| 2 | variable bound `1..=hi` | 10 | 15 |
| 3 | module-`static` bound | 10 | 15 |
| 4 | loop in an EMBEDDED suspending callee | 10 | 15 |
| 5 | **loop body does not suspend; the FUNCTION does** | 10 | 15 |
| 6 | single-iteration `3..=3` | 0 | 3 |
| 7 | empty `3..=2` | 0 | 0 |
| 8 | nested `1..=2` x `1..=2` | 1 | 4 |
| 9 | MT spawned root | 10 | 15 |

Row 5 is the sharp one: the body contains no suspension, and merely being
inside a driven function is enough — the transform rewrites every range `for` in
a driven body. Row 6 is the loudest: a single-iteration inclusive loop does not
run AT ALL. Both engines, entry-module, embedded and MT alike; a `while` loop is
unaffected and the exclusive `a..b` form is correct everywhere.

**What the fix owes beyond the one-line `<=`.** Design 53 lowers an inclusive
range through a `RangeInclusive` that is `Int.max`-SAFE, and a naive `i <= end`
header reintroduces exactly the hazard that type exists to avoid: with Saw's
always-on overflow checks, `for i in 0..=Int.max` in a driven body would trap on
the increment where its sync twin terminates — trading a silent wrong answer for
a twin divergence at the boundary. So the fix mirrors design 53's shape (run the
body, then `if i == end break else i = i + 1`) rather than flipping the
operator, and it lands with (a) `..=` added to corodiff's loop axis, so the
harness can see this class at all, and (b) the sweep's nine rows as its test
plan. Pinned by `examples/coro_for_inclusive_range_last_iteration.saw`.

Deliberately NOT fixed inside design 225: it is a coroutine-transform bug found
by an executor brief, and the `Int.max` question above is a real decision rather
than a typo repair.

## DF-225g — SAFETY: `self.field[i] += v` inside a `&self` method writes
## the CALLER's storage silently, no diagnostic (filed Aug 15, doc-sync
## correctness scan round 2, LEAD-VERIFIED)

**Highest-priority finding of the scan — a real, silent Law-of-Exclusivity
hole, not a doc bug.** LANGUAGE_SPEC.md's own "A `&self` method may not
write its receiver" section (§4 Memory Management, `Status: implemented`)
documents FOUR spellings of the rule and shows each one refused: a direct
field write (`self.hits = self.hits + 1`), a `&var self.<field>`
projection, a `&var self` method call reached through a field
(`self.cells.push(9)`), and a **place-window compound assignment**
(`self.grid[0] += 100`, captioned `// error: cannot write through a place
window on storage reached through a &self receiver`). The first three are
genuinely enforced (verified). The fourth is NOT — it compiles clean and
the write lands, visibly, in the caller's storage:

```saw
struct Board { grid: Vector<Int> }

@synthesize
extension Board: ExplicitCopy {}

extension Board {
    func bump(&self) {
        self.grid[0] += 100
    }
}

func main() {
    let b = Board(grid: [1, 2, 3])
    b.bump()
    print(b.grid.get(0)!)   // prints 101 — mutated through a `&self` (shared) receiver
}
```

Lead-reproduced independently (`.build/scratch/docsync2/verify_spec_a_safety.saw`):
compiles with no error, runs, prints `101`. A `let`-bound `b` (no `var`
needed to observe it) had its storage mutated through a call that only
borrowed it `&self` — the exact hazard the surrounding prose warns about
for the sibling `self.cells.push(9)` case, which IS caught.

MECHANISM (obligation 4): the place-window write-through-receiver check
apparently covers `&var self` METHOD CALLS reached through a field
(`self.cells.push(9)`) but not COMPOUND ASSIGNMENT through a place-window
ACCESSOR reached through a field (`self.grid[0] += v`, where `Vector.[]`
is a `borrows` accessor) — i.e. the check that classifies "does this
expression open an exclusive place-window on receiver-owned storage" does
not fire for an index-assignment target the way it fires for a method-call
receiver. Likely siblings, UNPROBED: `self.map[k] = v` / `self.map[k]!.x
+= 1` (Map's `[]` is the same `borrows` shape per LANGUAGE_SPEC's Map
section), and any other stdlib `borrows` accessor reached through a
`&self`-receiver field with a compound-assignment or whole-value-write use
site.

This needs a compiler brief, not a doc edit — the doc's claim is the
INTENDED behavior (and matches the three enforced sibling spellings); the
compiler has the gap. Left the LANGUAGE_SPEC.md example exactly as
written (it correctly states intent) per doc-sync doctrine: code is buggy,
not the doc.

**SWEEP VERDICT (Aug 15, obligation-4 mechanism sweep,
`.build/scratch/sweep225g/RESULTS.md` + probes p01-p61, GITIGNORED):
FALSIFIED — DF-225g is CLOSED as not-a-bug.** The plain-assign twin
compiles identically (p01); the axis is design 200's ruled indirection
carve-out, spec-documented (the "heap buffer" paragraph immediately
below the snippet) and conformance-pinned (M32): a `Vector` field's
elements live in its heap buffer, so writes through it at `&self` are
ALLOWED; the refusal is for INLINE `[T; N]` storage — and the inline
twin IS refused, both spellings (p04/p61). The scan's reading was
induced by the spec snippet omitting `Board`'s field declaration —
FIXED (the snippet now shows the inline field and points at the
heap-case paragraph). All three checks fire on compound paths for this
rule (statements.py:2785, place_uses.py:235 handles both classes).

**The sweep's census found FOUR NEW findings — two SOUNDNESS — the
hypothesized class operating on OTHER rules: DF-225i (compound assign
skipped design 193's write-path RHS exclusivity, losing the callee's
write), DF-225j (`let`-immutability of INLINE array storage was
shape-dependent, incl. two cells writing the caller's array through a
SHARED `&` parameter), DF-225k (`self.c?.n = 99` at `&self` was a silent
no-op) and DF-225l (`o?.n += 5` was a parse error).**

**ALL FOUR FIXED — `designs/227-write-target-funnel.md` (BUILT Aug 15,
branch awaiting cherry-pick).** One `_check_write_target` funnel with
four named entry points, one ArrayIndex-transparent root walk keeping
design 200's indirection carve-out, and the parser hoist that makes
`x?.y += v` a chain assignment. Unit 0's consumer census: ZERO in-tree
writes relied on the DF-225j hole (96 chained-index writes, 26 with a
non-mutable root, every one of them stopping at a pointer, a heap
container or a static). Merging the walks turned up two siblings the
sweep had not probed, both verified writing a `let` before the fix: a
`let` optional's payload (`o!.n = 5`) and a `&var self` call through an
inline array element (`h.cells[0].bump()`). Rows M37-M44; the carve-out
accept/refuse table is pinned by M41/M42.

## Design 188 — safety-audit batch (ALL EIGHT UNITS LANDED, Aug 9)

Source: the Aug-8 external review (`review.md`) + systematic audit
(`safety_audit.md`, 247 rows, probes in `.build/scratch/safety/` —
GITIGNORED, which is why the load-bearing repros are promoted to example
pins below). Nine findings, all closed. All four rulings were ratified in the
Aug-9 one-by-one review — the brief's units 2-5 record each decision and the
alternatives explored and declined. D-numbers cite the audit's sections. Eight
per-unit commits, the full suite green at each; eight pins flipped
(`enum_ref_payload_escape`, `typealias_ref_launder`, `place_window_exclusivity`,
`lend_accessor_local`, `taskgroup_move_live`, `spawn_capture_after_group`,
`unsafe_trait_requirement_effect`, `spinlock_import_gate`). Two follow-on
findings filed below (DF-188j, DF-188k).

- **DF-188a — CLOSED (unit 1).** An enum case payload could be a reference.
  Design 163d enumerated the positions that carry a reference past its call and
  enum payloads were not among them, so a one-case enum was a general bypass:
  `case Held(r: &Int)` accepted, `Slot.Held(r: &x)` filled from an ordinary `&`
  parameter, the value into `Vector` storage outliving the call. Cause: the
  NAMES walk simply had no call at the payload position — `parse_enum` never
  invoked it. Fixed with the field position's own walk and diagnostic. Pin
  flipped: `examples/enum_ref_payload_escape.saw`.
- **DF-188b — CLOSED (unit 1).** A `type` alias laundered a reference into every
  guarded position. Cause: all four written-form checks live in the PARSER,
  which is where the position is known and where no alias can be resolved yet,
  so `type R = &Int` read as a plain named type. Fixed by re-running the walk in
  the typechecker with aliases RESOLVED at every step, over the same declared
  positions plus binding annotations, and by refusing the back-conversion
  `R(&x)` that inhabits them. A PARAMETER stays legal — the walk never ran
  there. Pin flipped: `examples/typealias_ref_launder.saw`; the audit's other
  two alias positions are `examples/errors/typealias_ref_{generic_argument,
  construction}.saw` and the boundary is `examples/ref_no_escape_alias_boundary.saw`.
- **DF-188c — CLOSED (unit 5).** Case (i), the probe-confirmed silent UAF: a
  reference capture of a binding declared AFTER its group. Cause: nothing
  related a capture to its group's declaration order, and the soundness argument
  for captures is entirely that order — LIFO runs the later binding's deinit
  before the group joins. Now an error naming the binding, the group, both
  lines, the LIFO order and the fix. Case (ii) probed ALREADY REFUSED (a closure
  is not `Send`), pinned as `examples/errors/spawn_capture_mt_send.saw`. Case
  (iii) untouched and pinned as legal:
  `examples/spawn_capture_declared_before.saw`. Join-at-the-brace was declined
  (it deadlocks the drop-to-terminate idioms). Pin flipped:
  `examples/spawn_capture_after_group.saw`. Design 189 owns the extent rule.
- **DF-188d — CLOSED (unit 4).** `move group` with a live task was accepted and
  the runtime aborted. Cause: design 124 defines a group as a scope and the type
  system had no way to say so — every relocation rule the language had was about
  DUPLICATION. `NoMove` is the missing axis: a declarable empty marker that
  REQUIRES a declared `NoCopy` (never implies it), permits exactly one move
  (constructor into binding), leaves whole-referent replacement through `&var`
  legal, cascades by DECLARATION into containing types, and is not a generic
  bound. `TaskGroup` conforms and the refused-move diagnostic cites design 124.
  `NoMove + ExplicitCopy` opens later by relaxing one check. Pin flipped:
  `examples/taskgroup_move_live.saw`.
- **DF-188e — CLOSED (design 187 unit 6).** `n += 1` on a `&var` param after
  a suspension ICEd with "Unsupported container expression in compound
  assignment" while `n = n + 1` worked. Not the transform: it makes a
  reference param a frame-resident POINTER, so the target arrives as
  `self.n[0]` — an ArrayIndex over a MemberAccess — and CODEGEN's compound
  path had no case for a non-Identifier container, which the plain assignment
  path had handled for a long while. The two are mirrored now, minus the
  ownership bookkeeping a numeric target does not need. Pin flipped:
  `examples/coro_ref_param_compound_assign.saw`, grown to the whole integer
  operator family, a Float, and a field of a `&var` referent.
- **DF-188f — CLOSED (unit 2), the headline.** Two by-reference accesses to one
  root in one call, at least one a place, silently lost writes; std `Data`
  corrupted. Cause: `_build_access_path` treated a place use as an ordinary
  projection or as nothing at all, so window roots never entered the
  path-disjointness check — and what refused the shape on ExplicitCopy/NoCopy
  receivers was the COPY POLICY (the compiler copied the receiver to open the
  second access and reported that copy), which is why a free-copy receiver sailed
  through. Fixed by charging a place use's RECEIVER whole, giving the exclusivity
  diagnostic on every tier, and — since a window's extent is the whole call —
  collecting references created by NESTED calls in the same argument list when a
  window is open (audit X31). Pin flipped: `examples/place_window_exclusivity.saw`;
  twins at `examples/errors/place_window_{data_corruption,beside_var_root}.saw`;
  the audit's correct-shapes table is `examples/place_window_exclusivity_boundary.saw`.
- **DF-188g — CLOSED (unit 3).** A `borrows` accessor could lend its own local or
  parameter; reads were sound (the frame is alive for the window) and writes
  vanished. Cause: the rule existed for a match-arm payload ("a value the body
  just BUILT dies with the accessor") and was never applied to a plain `lend`.
  Fixed in the NARROW ruled form — an accessor's parameter is refused too, `&var`
  included. Two things stay rooted without being written `self.…`: a match-arm
  payload of a receiver-rooted scrutinee, and an INDIRECTION out of the receiver
  (`lend buf[i]` for a `buf` bound from `self.buffer`), which is how std
  Vector/Data are written. Pin flipped: `examples/lend_accessor_local.saw`;
  parameter twin at `examples/errors/lend_accessor_param.saw`; accept side at
  `examples/lend_rooted_in_receiver.saw`.
- **DF-188h — CLOSED (unit 6).** The documented direction is enforced: a
  conformer of an `unsafe` trait requirement must declare the effect. Cause: the
  conformance check compared receiver mutability, return type and parameter
  count, and had never been given the effect. The reverse direction stays legal
  as rule 7's redundant declaration. Pin flipped:
  `examples/unsafe_trait_requirement_effect.saw`; accept side at
  `examples/unsafe_conformance_effects.saw` (audit row U26 is deliberately
  superseded — it was an accept row only because the rule was unenforced).
- **DF-188i — CLOSED (unit 7).** `spinlock` and `slab` joined
  `IMPORT_REQUIRED_STD_MODULES`. Cause: the allowlist and the spec's module table
  were two independent lists, so a module documented as gated and never added
  stayed bare. `tools/test_prelude_gate_doc.py` (`make preludegate`) walks the
  table and asserts the two agree in both directions. Flipping the pin surfaced a
  second half: a gated module is not compiled in at all, so `static LOCK:
  SpinLock<Int>` — which never names the type in an expression — reached codegen
  and ICEd there; the gate now runs at a static's declaration too. Pin flipped:
  `examples/spinlock_import_gate.saw`. DF-138c closed with it.
- **DF-188j (SOUNDNESS-CONTRACT, filed Aug 9 by unit 2): the Law of Exclusivity
  does not see a reference created by a NESTED call.** `sink(&var p.a,
  reset(&var p))` compiles with no place involved anywhere, and the answer
  depends on argument evaluation order (probed: `a=107 b=200`). Unit 2 closed the
  half where a window is open, because a window's extent is provably the whole
  call; the general case is a question about when an argument's borrow starts,
  which the Law has never had to answer and which no current spelling forces.
  Widening it would reject `f(&var x, g(&y))` shapes that are legal today, so it
  wants a ruling rather than a patch. Repro: `.build/scratch/p_nested_ref.saw`
  (three statements; the shape is in this entry).
  **RULED Aug 10, owned by design 199:** a nested call's by-ref
  arguments JOIN the outer call's access set — OVERLAPPING roots error
  on every tier (mirroring the landed place rule), disjoint roots stay
  legal (`f(&var x, g(&y))` compiles; the earlier "would reject" framing
  conflated the two). Consumer sweep before the flip, per rule 2.
  **CLOSED Aug 10 by design 199 unit 3.** The nested-reference collection
  design 188 unit 2 had gated on a place being present is unconditional
  now: every `&`/`&var` written strictly below an argument joins the
  access set with its own path root and meets the SAME overlap test, so
  disjoint paths are untouched and the widening is to the set alone. The
  brief's units 1-2 answered the two open questions ahead of the change —
  the receiver-position variant is NOT already caught (`p.total(reset(&var
  p))` compiled and read the receiver at its pre-reset value), and the
  consumer sweep over all 1890 tracked `.saw` files found ZERO offenders,
  so the rule landed with no grandfathering and no existing program
  changed. Pins: `examples/conformance/X41_nested_call_ref_overlaps_
  sibling.saw` (the repro in this entry), `X44_…_receiver.saw`,
  `X45_two_nested_calls_one_root.saw`; accept sides at
  `X42_…_disjoint_roots.saw` and `X43_…_from_every_sibling.saw`.
- **DF-188k (SPEC/IMPL, filed Aug 9 by unit 7): the prelude gate does not run on
  type ANNOTATIONS.** `func take(d: &Data) -> Int { d.len() }` compiles with no
  `import std.data` — the gate fires in EXPRESSION positions (a call, a struct
  literal, a static-method head), and a parameter annotation is none of those. In
  practice a value of a gated type usually has to be built or called somewhere,
  which is why this has held up; a function that only RECEIVES one and calls
  methods on it never trips the gate. Unit 7 fixed the one position where the
  consequence was an ICE (a `static`'s annotation). The general fix is to run the
  gate wherever a written type name is resolved in user source, which needs care
  about the many internal callers that resolve std-derived types while checking a
  user body — an over-rejection hazard, hence a finding rather than a change.
  **Design 193 unit 7 built it and BACKED IT OUT** — the hazard is real and its
  cause is now known: see DF-193d above (the written spelling is destroyed
  before any check can read it, so a legal qualified annotation is refused).
  **CLOSED Aug 10 by design 194 unit 4**, through the written-form provenance
  bit DF-193d specified. Eleven annotation positions are gated; see DF-193d for
  the mechanism, the exemptions and the consumer sweep.

Also from the audit, for the record: DF-174h's failure mode CHANGED — the
too-deep `??` default no longer emits invalid IR; it silently takes the
absent path (audit row O10). The type error is still owed (187 unit 7,
note updated there). Audit rows confirming fixed items: V17 (DF-146j),
O10/O11 controls, the 26/26 trap table.

## Design 201 — spawn reference parameters (LANDED Aug 10)

`designs/201-spawn-reference-parameters.md` — design 189's unbuilt unit 4,
ratified as its own brief. `group.spawn(f(&var buf))` is legal in a
SINGLE-THREADED group on exactly the extent machinery 189 built for captures:
the argument borrows its ROOT for the task's life, the handle carries the
borrow, `join()` releases it, a discarded handle holds to group death, and the
loop-body liveness refusal applies. An MT group refuses on `Send`. All four
units landed, tracked battery green; design 88's blanket refusal and its pin
`examples/coro_spawn_ref_rejected.saw` are retired, and conformance rows R25 and
K04 are re-authored to the ruling. Two answers the units produced are in the
brief: the declared-after-group question (it does NOT fall out of 188's rule)
and the dual-role trampoline regression the probes caught.

- ~~**DF-201a — the ratified relaxation is not built, and the two holes it must
  close are only invisible because the shape cannot be written.**~~ **CLOSED by
  units 2-3** (Aug 10). The four refusals are the typechecker's (unit 2: the
  extent intake takes a reference ARGUMENT through one funnel beside the
  capture, and design 188's LIFO check reads the same list); the two accepts and
  the MT refusal are the lowering's (unit 3: design 88's blanket refusal
  retired, the spawn site casting `&var x` to a pointer exactly as a drive site
  does, and the Send gate left to refuse the multi-threaded case on its own
  terms). All seven pins flipped. Original text:

  **DF-201a — the ratified relaxation is not built, and the two holes it must
  close are only invisible because the shape cannot be written.** Probed Aug 10
  (unit 1, `.build/scratch/probe201_*.saw`) by lifting design 88's blanket
  refusal and running the shapes the extent model is supposed to cover. Two of
  them are silent use-after-frees in safe code — the SAME two design 189's
  probes found through a capture, reached through an ARGUMENT instead:
  - **declared-after-group (probe H).** A root declared after its group, handle
    discarded: LIFO tears the root down first and the task's pushes print AFTER
    "scope ends", exit 0. This does NOT fall out of design 188's rule — that
    check walks a spawn's capture LISTS and never looks at its arguments — so
    the brief's "verify, row either way" question is answered: it owes an
    implementation, not just a row. Row K18.
  - **`move` of a borrowed root between spawn and join (probe I).**
    `consume(move buf)` compiled, printed `consumed 0`, dropped the buffer, and
    the task then pushed three elements into freed storage. Design 189 probe
    5's shape, one position over. Row K20.
  Two more shapes compile today with no diagnostic: a caller read/write of the
  root inside the spawn-join window (probe B — the caller read `1`, the task
  then wrote through the same root), and one textual spawn in a loop body
  opening N live exclusive borrows (probe E). Rows K15 and K17.
  Cited by the seven XFAILs `examples/conformance/K14`-`K20`; K15/K17/K18/K20
  flip with unit 2, K14/K16/K19 with unit 3.

## Design 189 — scoped task borrows (UNITS 1-3 LANDED, Aug 9; unit 4 NOT built)

`designs/189-scoped-task-borrows.md`, authored from the five-probe
investigation the user directed ("first probe it and then write a brief
depending on the probe outcome"). Probes CONFIRMED TWO SILENT UAFs in
safe code: (a) a deinit-bearing root declared after its group is freed
before the task's write (188's DF-188c(i), now labeled HOLE); (b) `move`
of a captured root between spawn and join hands the task freed memory —
in the ordering 188 calls legal, so extent tracking is REQUIRED for
soundness, not hygiene. Also probed: two `&var` captures of one root
co-live silently (Law violated); MT captures are ALREADY refused via
Send on the closure param (nothing owed there but a regression pin).
The rule: a capture borrows its root for the task's life, the HANDLE
carries the borrow, join releases it (group death is the fallback for a
discarded handle); an exclusive capture excludes caller reads too —
standard XOR over a task-length window. Design-88 param relaxation rides
as an optional unit, ratified separately — **RATIFIED Aug 10, now its
own brief: design 201** (spawn reference parameters on the extent
model; unit 4 here is superseded by it). RATIFIED Aug 9; queue slot:
immediately after 188, before 186. Queue RESUMED same day:
184 ∥ 187 dispatched, then 188 → 189 → 186 serial.

Standing after design 188 landed (Aug 9): (a) is CLOSED — DF-188c(i) is a
compile error naming the LIFO order, and its pin flipped. The `move`-the-group
route (b) depended on is closed too, by DF-188d's `NoMove`.

Units 1-3 LANDED Aug 9 in three commits, full suite green at each. A reference
capture into `group.spawn(...)` now borrows its ROOT for the task's life, the
HANDLE carries the borrow, `join()` releases it, and a discarded or unjoined
handle releases at the group's death. Not a new checker — a new EXTENT: the
records live beside the move state and five existing access sites consult them.
Diagnostics are the existing exclusivity/move errors plus one sentence naming
the task and its release point. All three pins flipped; two error pins and one
accept pin were added for the edges (see the brief). Unit 4 (the design-88
reference-PARAM relaxation) is NOT built and still needs its own ratification —
its precondition, the extent model proved in the capture position, is now met.

- **DF-189a — CLOSED (unit 1).** Two `[&var]` captures of one root co-lived
  silently: both tasks mutated the one root, two exclusive borrows across
  suspensions, no diagnostic. Cause: a capture's borrow ended with the spawning
  call, so nothing was live at the second spawn to collide with. Fixed by the
  extent — and with no new site, because a capture list is already part of a
  call's access set, so the second capture collides with the first task's
  borrow exactly the way two captures in ONE call collide. Pin flipped:
  `examples/spawn_capture_alias.saw`.
- **DF-189b — CLOSED (unit 1).** The caller wrote and read a root while a task
  held `[&var]` of it. Both are refused now: an exclusive capture excludes
  readers as well as writers, which is the ratified one-writer-XOR-many-readers
  table over a task-length window. Pin flipped:
  `examples/spawn_capture_caller_alias.saw`.
- **DF-189c — CLOSED (unit 1), the headline.** `move` of a captured root
  between spawn and join handed the task freed memory: the moved-to value
  dropped, the join then drove the task, which read the dead slot and realloc'd
  from the freed buffer, silently, exit 0 — in the declared-before ordering
  DF-188c rules legal. The move-while-borrowed refusal already existed; what it
  lacked was a visible borrow. Pin flipped:
  `examples/spawn_capture_move_root.saw`.
- **DF-189d (filed and CLOSED in the same landing, unit 1): a capture still
  live when a LOOP BODY ends.** One textual spawn, N live borrows — the Law
  violated by iteration rather than by a second line, and outside the letter of
  the brief's probe record. Refused at the spawn, beside the cross-iteration
  MOVE rule already in `_check_loop_body`. Spawn-and-join-inside-the-body stays
  legal. Pin: `examples/errors/spawn_capture_across_iterations.saw`; accept side
  in `examples/spawn_capture_join_releases.saw`.

## DF-182f — irdet's fan-out lost its accidental throttle (FOUND + FIXED Aug 9, live incident)

Design 182's cooperative `Command.run()` removed a throttle nobody knew
existed: irdet spawned check_one for EVERY corpus file into
`TaskGroup(threads: jobs)` and relied on `run()` BLOCKING its worker
thread to cap children at the worker count. Post-182 `run()` parks, the
workers pick up the next task and launch its child too, and `--all`
put ~1000 concurrent sawc processes on the machine — loadavg >700,
observed live with two agent batteries running. Fixed in
`devtools/irdet/src/main.saw`: the fan-out is now WAVES of at most
`opts.jobs`, joined in input order before the next wave spawns — the
bound the flag always promised, made explicit instead of accidental.
LESSON for every driver of subprocess fleets (the test runner is safe —
it has its own worker pool — but future Saw tools are not): a spawned
task that runs a child process must be bounded by STRUCTURE, not by the
hope that some call blocks. Both in-flight agents were stopped mid-run
for the fix; their worktrees predate it, so their batteries must not run
`--all` until rebased.

## Design 187 — coro fix batch + 182 completion (LANDED, Aug 9)

`designs/187-coro-fix-batch.md`. All eleven units landed, each its own commit
with the full suite green: DF-158e, DF-158c, DF-158a, DF-158b, DF-158d, DF-188e,
DF-174g, DF-174h, DF-182e, DF-182c, and unit 11's cooperative
`Command.output()`. Five pins flipped and were renamed
(`coro_panic_value_position`, `coro_tail_suspend_void`,
`coro_ref_param_compound_assign`, `coro_move_scrutinee_span`,
`process_output_concurrent`); three findings were filed along the way
(DF-187a, still open; DF-187b and DF-187c, both closed).

**Unit 11: `Command.output()` is cooperative, and DF-181a CLOSES WHOLE.** The
drain is a `blocking` extern, so design 183 runs the pipe read on a worker
thread and the task parks — the seam still blocks, just never on the executor
thread. The reap is a shared `Command.reap` METHOD, the same park loop `run()`
has used since design 182. `__saw_rt_proc_wait` drained to zero callers and was
REMOVED from `RUNTIME_ABI_SYMBOLS`, rt/ABI.md and `rt/common/proc.saw`: a seam
with no callers is one a new runtime should not be asked to write.

Three things the first attempt measured, and the landing confirms:
- **`reap` must be a METHOD.** As a std FREE function the transform cannot embed
  it (design 84 embeds std METHODS; the closure walk over free functions is
  entry-module only), so its `io_wait` ran outside a frame, the wait became a
  busy poll, and `process_run_concurrent` / `process_cancel_during_child` both
  regressed. Measured, not reasoned.
- **`output()`'s own buffers had to stop being raw pointers.** A frame holding
  an `UnsafePointer` across the offload park is not `Send`, so `output()` itself
  would have been unspawnable into a multi-threaded group — the very thing unit
  9 unblocked for its callers. The chunk is a frame-resident `[Int8; N]` (design
  183's documented offload idiom) and the accumulator a `Data` (Send since unit
  9, and it grows itself), which deleted the hand-rolled realloc loop and its
  manual NUL terminator from std. Pinned:
  `examples/process_output_multithreaded.saw`.
- **Then irdet stopped compiling** — DF-187b, which is fixed above, and DF-187c
  one layer under it, which the fix then exposed. Both were pre-existing
  transform bugs in shapes irdet happens to be written in.

The brief's "two lines on run()'s park loop" underestimated it: the two callers'
shapes differ enough that the reap has to be shared as a method and the drain
has to give up its raw buffers.

- **DF-187c (COMPILER, CLOSED Aug 9 in unit 11's landing; PRE-EXISTING): a
  `return` inside a control-flow block reached through an EXPRESSION lowered
  raw, emitting invalid IR.** The transform turned a `return` into the frame's
  done sequence only where the construct holding it WAS the statement
  (`_lower_inplace`'s if/while/match branches). Reached through an expression —
  a `match` that is a `let`'s value, a value `if`'s branch, an assignment's RHS
  — only the identifiers inside were rewritten, and the `return` stayed a
  `return` out of a resume method whose result type is `__Poll`: llvmlite
  rejected the module with ``value doesn't match function result type 'i32'``,
  which is the only thing in the pipeline that noticed. `_rewrite_expr` now
  treats a `Block` as a lowering boundary, which covers every expression
  position at once; `ClosureExpr` returns before it, so a closure's own `return`
  is untouched. PIN: `examples/coro_return_in_expression_block.saw`.

## Design 185 — const bitwise + flag enums (LANDED, Aug 8)

Closed items: see todo_aug1-aug9.md.

- **DF-185b — CLOSED (design 186 unit 7).** A `static` initializer was
  literals-only, so a constant EXPRESSION could not initialize one:
  `static SIZE: Int = 4 * 1024` and this brief's own `static RW: UInt8 =
  Perm.Read | Perm.Write` were both refused even though the same
  expressions folded in every position that CONSUMES a constant. Design
  41's `_is_const_init` was a hand-written list kept apart from the
  evaluator; it ASKS the evaluator now (by trying it, not by re-listing
  its grammar), codegen emits the folded value, and a static initializer
  is a const position so the flag-enum half reads its operands as tags.
  All three of the filed ordering questions were answered as the finding
  predicted: `_collect_const_statics` evaluates in DECLARATION ORDER —
  which is also the cycle rule, since a forward reference has nothing to
  fold against — and reads raw-backed enum case values straight off the
  AST, and the answer is decided once, on the symbol, so an importer sees
  what the declaring module decided. Pin flipped and renamed:
  `examples/static_const_expr_init.saw`.

## Design 158 — logical task backtraces (LANDED, Aug 8)

Three units landed: the per-monomorphized-frame state tables as one
read-only in-binary blob (`__saw_bt_table`, always on), `tools/lldb_saw.py`
(`saw tasks` / `saw bt` / `saw table`), and the alloc-free in-process dump
(`dump_tasks()` from std.task, plus the automatic post-panic one) hosted and
freestanding.

**SIZE (the reserved veto point).** 246-517 bytes per hosted program across
the nine-program gate corpus — 0.23% to 0.83% of the binary. 287 bytes for the
SOS kernel image that runs tasks. 138 bytes for a program with NO coroutine
frames at all (header + the debugger's executor descriptor + the string table)
— the SOS kernel that spawns nothing, and Blade, both land there. A frame
record is 24 bytes, a state entry 12, and names are shared in one string
table, so the cost tracks frames rather than program size.
`tools/test_bt_table.py --sizes` reprints it any time. The debugger's vtable
map (unit 2) adds one pointer per frame on top.

Five findings, ALL PRE-EXISTING (each reproduced on `main` before 158
touched anything). Two carry XFAIL pins; three are recorded here because
they have no user-facing spelling to pin.

**DF-158a — CLOSED (design 187 unit 3).** A diverging `panic` in RESULT
position of a suspending body was a codegen ICE: the transform stored the
panic's (nonexistent) value into the frame's `__result` and codegen stored a
Python `None` (`'NoneType' object has no attribute 'type'`). The done
sequence now asks whether the result expression is `Never` — which covers
the tail `panic`, the explicit `return panic(...)`, a `-> Never` callee and
a value `if` whose arm diverges — and emits the expression instead of a
store, exactly as it already did for a `Void` body. Pin flipped and renamed:
`examples/coro_panic_value_position.saw`, now covering all four spellings.

**DF-158b — CLOSED (design 187 unit 4).** A suspending call in a `Void`
body's TAIL position was rejected: the tail normalization turned
`func f() { yield_now() }` into `return yield_now()`, and a suspending call
as a RETURN VALUE is a nested/expression position the state split cannot
express — so the author got a message about a shape they did not write, and
any statement after the call made it compile. A `Void` body HAS no result,
so nothing in it is ever in tail position in that sense: the normalization
now treats a Void body's tail as the discard it is and lowers it exactly as
a statement. That also closes the audit's X23 (a bare `yield_now()` as a
block's final statement read as expression position) and lets
`sos/tests/taskdump.saw` drop the `return` it was carrying as a workaround.
Pin flipped and renamed: `examples/coro_tail_suspend_void.saw`, grown to
cover the bare intrinsic, a nested suspending call, and trailing
`if`/`match` tails.

**DF-158c — CLOSED (design 187 unit 2).** An `@export`ed seam's return WIDTH
was wrong on a 32-bit target: `-> Int64` emitted `define i32` for riscv32 and
`-> Int` emitted `i64`, the two swapped. The cause was the compiler's OWN
declarations, which an `@export` of the same symbol unifies with and inherits
its type from — `_declare_io_runtime` hardcoded i64 for a family of seams
rt/ABI.md calls `word`, and `_declare_seams` used the platform word for the
two clock seams the document calls `Int64`. `--runtime-provider` could not
see it: it compares the SAW-declared types, which were correct all along.
Both directions now read their width off rt/ABI.md's vocabulary. Regression:
`tools/test_ir_contract.py` checks EVERY declared and defined `__saw_rt_*`
against `runtime_abi.abi_signatures()` at 64 and 32 bits — the same parse
`--runtime-provider` uses, so one document governs both sides. The SOS
`taskdump` case is no longer arm64-only.

**DF-158e — CLOSED (design 187 unit 1).** A `-c` / freestanding compile did
not EMBED a nested suspending callee. `object_only` decided `is_entry`, and
`is_entry` gates the whole-program effect fixpoint, so under `-c` every
callee's `suspends` bit stayed False and the closure walk never reached a
spawn root's suspending callees: `fmiddle` got a frame, `fleaf` did not, and
the call lowered as a direct BLOCKING call — in a kernel the nested park ran
inline. The fix SPLITS the flag: `is_entry` now means "the last module of
the compilation unit" (it always was, for an object too) and the new
`require_main` carries the entry-point requirement. `sos/tests/taskdump.saw`
is two frames deep as a result, which is the honest proof. Regression:
`tools/test_ir_contract.py` (`make ircontract`) requires the frame set to be
IDENTICAL with and without `-c` over four coroutine shapes — an examples test
cannot spawn under `-c`, so the check is at the IR level.

**DF-158d — CLOSED (design 187 unit 5), and the culprit is the SPELLING.**
`yield_now()` in a nested callee did not make its caller suspend — the
callee got no frame, the yield ran outside one, and the task never ceded,
silently killing the one documented escape hatch a compute loop in a helper
has. Narrowing it found the bare spellings (`import std.task.*`,
`import std.task.{yield_now}`) were always fine: they put the name in scope
BARE, which lands in the intrinsic branch. Design 150's QUALIFIER spelling
`task.yield_now()` arrived after design 114 and resolved to the std WRAPPER
as an ordinary cross-module free function, which the transform cannot
embed. The wrapper is transparent by design, so the qualified call now
routes to the intrinsic too (marked at resolution, canonicalized to the bare
`FunctionCall` by a transform pre-pass, so every downstream pass sees the
one spelling it already handles). Test:
`examples/coro_nested_yield_wrapper.saw` — the witness COUNTS its own turns
taken while the worker is still running, no ordering asserted; zero before
the fix, nonzero after.

- **DF-187a — CLOSED (Aug 17).** A function's namespace KEY doubles as its
  codegen name unless `mangled_name` overrides it, so `_expose`'s
  re-registration of the already-merged std symbol under a second spelling left
  codegen looking up `dt`. It now carries the original across as
  `mangled_name` — which is exactly what the USER-module selective-import path
  (`core.py`, design 53's aliased-function branch) had always done, and the
  whole reason only std broke. On a COPY (`dataclasses.replace`): `_expose`
  hands out the SHARED merged symbol, and renaming it in place would rename the
  definition out from under std itself. Obligation 4 — the mechanism is "a
  namespace key that is also a codegen name", so it reaches functions and
  nothing else in that table list: a struct/enum/trait/alias carries its
  identity on the SYMBOL, which is why a renamed std TYPE always worked, and a
  static resolves through its symbol too. Matrix:
  `examples/import_rename_function_positions.saw` (two renames from one std
  module, a user-module rename, a renamed generic, a renamed type, and a rename
  called twice). PIN flipped: `examples/import_std_function_rename.saw`. Gated
  on suite + `sos_runner` both arches.
  As filed (COMPILER, Aug 9 by design 187 unit 5; PRE-EXISTING): a
  RENAMED selective import of a std FUNCTION is a codegen ICE.
  `import std.task.{dump_tasks as dt}` type-checks (the rename registers the
  symbol under `dt`), then codegen looks the call up by the name at the call
  site: `internal compiler error: Undefined function: dt`. The same rename
  over a USER module (`import helper.{greet as hello}`) works, and so does a
  renamed std TYPE (`import std.data.{Data as Bytes}`) — so it is the std
  FUNCTION path, not the rename machinery. Found while narrowing DF-158d,
  whose `{yield_now as cede}` spelling hits it; every std function does.
  PIN: `examples/import_std_function_rename.saw`.
**DF-187b — CLOSED (Aug 9), and the cause was a TUPLE the walk could not see.**
A suspension-spanning `if let` renames its binding to a unique frame field and
rewrites the body's uses; the rename walk descended through lists and
`Argument`s but not through TUPLES, and `StructInit.field_inits` is a list of
`(name, value)` pairs — so it walked straight past every struct literal, the
outer name survived unrenamed, and the re-check reported ``undefined variable
`a` ``. Nothing to do with nesting, tails or interpolation: those shapes all
worked because none of them puts a name inside a tuple-shaped field.

  A dozen walks in `coro_transform.py` hand-rolled that same recursion and the
  copies did not agree, so the fix is ONE `_child_nodes(node)` generator — every
  AST child through any nesting of lists, tuples and `Argument`s — and the five
  walks that were missing tuples now share it. Three of them had the same hole
  in a position that MATTERS and nobody had hit yet: `_iter_method_calls` and
  `_iter_function_calls` (a suspending method call written in a struct-literal
  field would not have been discovered, so no frame, so a silent blocking call)
  and `_reject_buried_suspend_call` (which would not have caught it either).
  Order is unchanged for the shapes that already worked.

  Pin flipped and widened: `examples/coro_nested_iflet_struct_init.saw` — the
  original struct-literal tail, a `MapLiteral` tail (the other tuple-shaped
  field), and nested struct literals two levels deep.

  Original finding follows.

- **DF-187b (COMPILER, filed Aug 9 by design 187 unit 11; PRE-EXISTING): a
  STRUCT INIT in the tail of a nested suspension-spanning `if let` loses the
  OUTER binding's frame rewrite.** Two nested split `if let`s, and a struct
  literal in the inner branch's tail naming the outer binding: the transform
  leaves the name a plain local, and the re-check reports ``undefined variable
  `a` ``. The struct literal is the whole of it — the bare tail `a + b`, the
  bare tail `"{a} vs {b}"`, a struct init one level down, and reading the outer
  binding into a `let` before the literal all work, so it is not the nesting,
  the tail position or interpolation. Reproduces with NO `move` anywhere, so it
  is not DF-182c's surface. PIN:
  `examples/coro_nested_iflet_struct_init.saw`.

  **This is what blocked design 187 unit 11.** `devtools/irdet`'s `check_one` is
  exactly this shape, and a suspending `Command.output()` turns it into a
  coroutine — so the devtool stops compiling, and irdet is a gate. Everything
  else unit 11 needs is built and measured; see the design-187 section above.

## Design 184 — hostname resolution (LANDED, Aug 9)

Brief: `designs/184-hostname-resolution.md`. All four units landed; **DF-181d is
CLOSED WHOLE**. `TcpStream.connect` dials the host it is given, and a NAME is
resolved on a worker thread while siblings run.

Unit 3's resolver half landed on top of DF-184a's fix, and it is three methods
where it was one:

- `connect` chooses. A dotted quad is dialled directly (no libc, no thread hop,
  no way for a literal caller to pay for the resolver's existence); anything
  else is resolved and the first IPv4 answer dialled. A resolution failure, and
  a resolver that succeeds with no IPv4 address, are both an `Err(IoError)`
  naming the host: `io error: resolve "db.internal" failed (not found)`.
- `TcpStream.resolve_first` is a static METHOD, and that is the load-bearing
  part: the transform embeds a suspending std method as a sub-frame and cannot
  reach a std FREE function, so the same code written as a free helper would run
  its `blocking` seam outside a frame — a naked call holding the executor thread
  for the whole lookup, which is exactly what design 184 exists to prevent. It
  is `unsafe` so the pointer work is confined (design 130) and `connect` keeps a
  safe signature. Its `found` buffer is a frame local, satisfying design 183's
  pointer rule.
- `TcpStream.dial` is the shared tail, so a name and a literal reach their peer
  through identical code.

Pins: `examples/net_connect_by_name.saw` (XPASS flipped — the dialer is spawned
FIRST and the sibling still prints first, which is the offload proof) and
`examples/net_connect_unresolvable_host.saw`, rewritten because its old
expectation WAS the refusal. Its unresolvable hosts are now the two the resolver
rejects out of its own input validation — an empty host and a name past the
255-octet limit — so it stays network-free; a name that merely does not exist is
deliberately not tested, since whether and how fast it fails is a property of
the machine's DNS.

**DF-184b — CLOSED, verified on the IR.** With `connect` embedded, its park is
in-frame: at `-O0` the reactor arm sits in `__Frame_TcpStream_dial_resume` with
a real wake token, and the offload start in
`__Frame_TcpStream_resolve_first_resume`. The out-of-frame form (`io_register(…,
0)` + `__saw_exec_park(-1)`) survives only in the untransformed std bodies the
transform leaves behind as dead code, which is how every embedded std method
already looked. A call from a NON-suspending `main` still reaches those bodies
and still blocks that thread — but `main` is not a task, nothing is scheduled
behind it, and that is the general rule for a suspending method called from
non-suspending code rather than anything specific to `connect`.

What landed earlier:

- **The literal fast path** (`parse_ipv4_literal`, std.net). A dotted quad is an
  address, so it is parsed in Saw — no libc, no thread hop — and dialled
  directly. Strict: four octets, 1-3 digits, no leading zero, nothing else in
  the string; a near-miss like `127.00.0.1` answers `None` rather than picking a
  side in the "is a leading zero octal?" ambiguity. Test:
  `examples/net_ipv4_literal_parse.saw`.
- **The seam.** `__saw_rt_resolve_ipv4(host, out, max) -> count | -tag` is in
  the frozen ABI, and its ABI.md entry is the FIRST to state a blocking contract
  explicitly (the 181 audit's documentation standard). Body in Saw
  (rt/common/os_ops.saw): AF_INET/SOCK_STREAM hints as a typed struct pinned by
  `static_assert`, `getaddrinfo`, the walk, `freeaddrinfo`, the EAI mapping.
  Three projections are C in `shim.c` beside `__saw_open_flags`, for the same
  reason: glibc declares `ai_addr` before `ai_canonname` and macOS the other way
  round (a hardcoded offset cannot be right on both — the design-122 `d_name`
  bug, which shipped), and the `EAI_*` codes disagree in value AND sign.
- **The design law is ENFORCED, not just written down.** Because `blocking` is
  part of an extern's contract (design 183 unit 1), a program that redeclares
  `__saw_rt_resolve_ipv4` without the annotation is refused at its own
  declaration: there is no way to spell a naked resolve.
  `examples/errors/resolve_seam_must_be_blocking.saw`.
- **The seam offloads**, proven by INTERLEAVE rather than by stopwatch — one
  cooperative thread, the resolver spawned first, the sibling's line printed
  first anyway (`examples/resolve_seam_offloads.saw`). Network-free throughout:
  `localhost` comes out of /etc/hosts and no test in the suite leaves the
  machine.
- **The address travels the whole way down.** `__saw_rt_tcp_connect_start` takes
  `(addr_be, port)` and `_connect_check` takes `(fd, addr_be, port)` — it must
  re-issue against the same peer or it is asking a different question —
  `loopback_sockaddr` is gone. Pin:
  `examples/net_connect_dials_the_host_it_was_given.saw`, which keeps a live
  listener on 127.0.0.1:port and watches the all-ones broadcast address be
  refused beside it. The old code answered Ok to both.

**DF-184a — CLOSED (Aug 9). A suspending STATIC method is now embedded exactly
as an instance one is.** The transform asked the RECEIVER what type owned a
method callee, and a static call has no receiver; a static call now carries the
owner on the CALL instead (`is_static_method_call` / `static_receiver`, stamped
by both static-call checkers), and one shared `_method_call_owner` answers for
both shapes at the five places that used to read `mc.object.resolved_type`. The
frame itself splits `is_method` (this frame belongs to a type — key, display
name, embedding) from a new `has_recv` (this frame reaches a receiver through a
pointer), and a static frame simply has neither the `__recv` field, the driver's
receiver parameter, nor a `self` to rewrite. `__saw_drive(T.m(...))` follows the
same split. Pin flipped: `examples/coro_static_method_suspends.saw`, both bodies
identical but for the receiver.

  Finding the fix cost one more bug, filed and fixed beside it (below): the pin's
  own INSTANCE half was returning zero, and had been all along.

- **DF-184c (COMPILER, CLOSED Aug 9 in DF-184a's landing; PRE-EXISTING): a
  suspending METHOD call in TAIL position silently discarded its result.**
  `_classify_call` sets `is_ret` in its `return <FunctionCall>` branch and then
  hands a MethodCall to `_classify_method_call` with `is_ret` still False — so a
  tail `recv.m()`, and the design-83-normalized bare tail that becomes one, was
  classified as a bare DISCARD. The callee ran, the caller frame's `__result` was
  never written, and the caller handed back a zeroed value: a spawned task joined
  to 0 (or, for an opt-encoded result, panicked in `TaskHandle.join` on a force
  unwrap of None), a driven one returned 0. At every copy tier, with no
  diagnostic. The `let x = recv.m(); x` spelling was always fine, which is why
  nothing in the corpus caught it. Pin:
  `examples/coro_tail_method_call_result.saw` — the three tail spellings, the
  static twin, and an owning `String` result.

  Original DF-184a finding follows.

- **DF-184a (COMPILER, filed Aug 9): a suspending STATIC extension method
  is unreachable from a task body, and in std it silently loses its offload.**
  The coroutine transform embeds a suspending METHOD callee by its RECEIVER's
  type (`_scan_method_callees` reads `mc.object.resolved_type.struct_name`), and
  a static call has no receiver, so the method is never embedded. Two faces:
  - In the ENTRY module the call does not even resolve. A static method with a
    `yield_now` in it, called from a spawned task, reports ``undefined variable
    `Napper` `` — it names the TYPE as though it were a value. An instance
    method with the identical body works. Pin:
    `examples/coro_static_method_suspends.saw`.
  - In std the call resolves and the body is then compiled UNTRANSFORMED, so
    every suspension in it runs out of frame and a `blocking` extern in it
    lowers to a NAKED direct call — no offload, no diagnostic, the executor
    thread stopped for the duration. Verified on the IR: with the resolve inside
    `TcpStream.connect` the module contains zero `__saw_rt_offload_start` and one
    direct `call @__saw_rt_resolve_ipv4`; moved into `TcpListener.accept` (an
    instance method) the same call offloads. That is why unit 3 stopped: design
    184's whole point is that resolution never blocks the executor, and shipping
    it inside `connect` today would do exactly that, invisibly.

  `TcpStream.connect` is std's only suspending static method, so it is the only
  place this bites in the tree. The fix is coro-transform work (resolve a static
  call's owning struct and build a receiver-less frame) and is left to whoever
  owns that surface. Unit 3's finished contract is written out as an xfail:
  `examples/net_connect_by_name.saw`, interleave included, so the fix validates
  itself. Until then `connect` REFUSES a name — `io error: resolve "example.com"
  (hostname resolution is not available yet — pass an IPv4 address) failed
  (invalid argument)` — which is the honest middle between blocking the executor
  and dialling 127.0.0.1 and calling it success.

- **DF-184b (filed Aug 9, found by 184's investigation): `TcpStream.connect`
  parks OUT OF FRAME, so a slow connect starves every sibling.** Same root cause
  as DF-184a and worth stating on its own because it is live TODAY, with no
  resolution involved: `connect` is not a coroutine frame, so its `io_wait` is
  the outside-frame blocking kind — the one `taskgroup.saw` documents as "a sync
  connect wait" that polls the reactor inline. The scheduler is not pumped and
  no sibling runs while it waits. Loopback hides it (a local connect completes in
  microseconds); a real peer that does not answer does not. The design-181 audit
  did not catch this one because it inventoried EXTERNS, and this is a park.
  DF-184a's fix closes it.

- **Future work (out of scope by the brief, recorded so it is not re-derived):**
  IPv6 and happy-eyeballs, which need the dual-stack design first — the seam is
  named `_ipv4` and returns a `u32` array precisely so a v6 seam is an ADDITION
  rather than a reinterpretation; resolver CACHING (a TTL-aware cache is a
  policy question — whose TTL, whose eviction, and does a long-lived server want
  its own?); and `Command`-env-style HOSTS INJECTION for tests, which is what
  would let a starvation test drive a deliberately slow lookup instead of
  relying on the interleave proof this brief used. A connect TIMEOUT is a
  separate net design over design 180's `Duration`.

## Design 183 — the offload story, made real (LANDED, Aug 8)

DF-181e and DF-181f are both closed above; the offload now works on the seams
and the signatures the design-181 audit needed. Four things worth a look at
review, each a decision the brief left to the implementation.
**The two open ones — the blocking-conflict ERROR and Float in the
offload set — were RATIFIED as-is by the user Aug 10** (error is
relaxable later, the upgrade would not be; Float rides the governing
"whatever @export admits" rule at zero cost). Nothing further owed:

- **A contradicting `blocking` redeclaration is an ERROR, not an upgrade.**
  DF-181f could have been fixed either way. Making the annotation win would give
  a user the whole-program escape hatch of annotating a std seam — and would let
  a downstream declaration turn a function another module calls into a suspension
  source, landing errors inside code its author never wrote. The audit's escape
  hatch does not need it: a user offloads their own distinctly-named wrapper, and
  DF-181e is what makes that wrapper spellable. Relaxing this later is possible;
  the reverse would not be.
- **The thunk is COMPILER-synthesized, so the C shim never casts a function
  pointer.** The alternative was an arity switch in `shim.c` casting `job->fn` to
  `long(*)(long, long, ...)`, which is the usual trick and is undefined behavior
  that happens to work on both integer-register ABIs. Emitting
  `__saw_blk_thunk$<extern>` in IR instead means the real call is made with the
  extern's real LLVM signature by the same lowering every other extern call uses.
  `shim.c` lost a line rather than gaining a switch.
- **Float is in the offloadable set**, because the brief's rule is "whatever
  `@export` admits" and `@export` admits it. It costs nothing: the thunk moves a
  `Float` through the job's integer word as bits, exactly. The brief's
  parenthetical list omitted it; the governing sentence did not.
- **The argument slots are copied into the JOB, not borrowed from the caller.**
  The worker reads them at a time `start` cannot bound, so the alternative was to
  make the call site's slot array outlive the park, which would have put it in
  the coroutine frame and coupled the thunk to frame layout. `start` copies,
  `take` frees after the join. The call site's array is an entry-block slot, so
  an offload inside a driven loop does not grow the resume frame's stack.

## Design 186 — UnsafeMutableInterior (APPROVED + QUEUED, Aug 8)

Brief in `designs/186-unsafe-mutable-interior.md`, fully ratified: interior
mutability as ONE unsafe primitive + a computed cell-carrying property,
replacing the three compiler-known names; `UnsafeSync`/`UnsafeSend` declared
markers (Sync/Send stay derivation-only); Mutex rebuilt inline (futex /
os_unfair_lock, zero = unlocked, static-eligible); `Once<T>` promoted in as
the set-once static (splitting `unsafe static var` back to genuinely-mutated
state); three-tier statics fence (zero / memberwise-const / never-runtime).
Queue position: after the current wave and the net track — typechecker +
codegen + builtin.saw + std surface, shares with everything, runs alone.

## Design 174 — the T = U? sweep (Aug 7, probe-only investigation)

Closed items: see todo_aug1-aug9.md.

- **DF-174a — FIXED (design 176 unit 7).** Design 24's decidability rule decides
  whether a return-type MISMATCH can be judged in an abstract generic body, and
  rightly defers that to monomorphization; the OPTIONAL wrap was riding the same
  gate and should not have been. It is decidable abstractly: `-> T?` is an
  optional at every instantiation and a non-optional tail is its payload at
  every instantiation, so exactly one wrap is correct for all of them — `T =
  Int?` included, where `Int?` wraps once into `Int??`. The non-decidable branch
  now performs the wrap (and stamps a bare `None` tail) and nothing else, so
  mismatches stay deferred. The `return x` spelling and the generic METHOD path
  never consulted decidability and were always right; the free-function tail was
  the one path that did. Tests: `examples/optional_generic_return_tail.saw`
  (the pin, flipped) and `examples/generic_optional_tail_return.saw` (the shapes
  that share the path — already-optional tail, `None` tail, diverging tail, value
  `if` arms, generic method, and the `T = Int?` instantiation).
  Original finding follows.
- **DF-174a (COMPILER, P0-severity, filed Aug 7 by the 174 sweep): a generic
  function returning `T?` skips the return auto-wrap for a TAIL EXPRESSION and
  emits MALFORMED LLVM IR.** `func wrap<T>(x: T) -> T? { x }` compiles to
  `ret i64 %x` against a `{ i1, i64 }` result type; the LLVM verifier is the
  only thing catching it, and what it is catching is a skipped optional wrap
  that would otherwise be a type-confused read. **NOT Optional-specific** — it
  reproduces at `T = Int` exactly as at `T = Int?`, so it is a generic-return
  bug the sweep happened to walk into. The `return x` spelling of the same
  function is correct, and so is the non-generic `func w(x: Int) -> Int? { x }`;
  it is specifically `-> T?` plus a tail expression. Severity is the highest of
  this batch: a crash today, a soundness hole if the verifier ever stops
  looking. Test: `examples/optional_generic_return_tail.saw`.
- **DF-174g — CLOSED (design 187 unit 7).** A value needing MORE THAN ONE wrap
  into a nested optional slot was mis-lowered: `let a: Optional<Int?> = 5` left
  the outer layer present with a garbage inner, so the first peel worked and the
  second crashed (exit 133); three layers ICEd. Why the earlier one-line
  recursive fit did not take: the `let` path never CALLED the fit. It leant
  instead on a None-literal placeholder retag whose shape test ("payload is i64,
  target is not") reads a genuine `Int?` exactly as it reads a placeholder — so
  the value was rebuilt from its inner TAG alone, payload dropped, before any
  fit could have run. Both halves landed: the retag now asks whether the value
  IS a `None` literal, and the `let` path fits its value to the annotation like
  every other slot does. `_fit_optional_slot` recurses into the slot's payload,
  so a value any number of layers down gets a real `Some` at each. Boundary
  observed, NOT a bug: a struct LITERAL still refuses a two-layer auto-wrap
  (``field `slot` expects type `Int??` but got `Int```) — a clean error, not a
  miscompile. Promoted from the probes: `examples/optional_nested_wrap_depth.saw`.
- **DF-174h — CLOSED (design 187 unit 8).** `a ?? b` whose DEFAULT is one layer
  too deep was accepted. `v.get(9) ?? v.get(0)` on a `Vector<Int?>` — both
  operands `Int??` — is now the clean type error it always owed, naming both
  types. Why it slipped: the compatibility check reads "could the payload flow
  into the DEFAULT", and `Int?` flowing into `Int??` is exactly the auto-wrap
  rule, so depth was the one thing it could not see. A depth comparison runs
  ahead of it and refuses only a default DEEPER than the payload, leaving every
  ordinary one-layer coalesce untouched. (Symptom history, for the record: an
  invalid-IR crash when filed; by the Aug-9 audit a silent absent path; in the
  peeled-twice spelling an `Can't index at [0] in i64` ICE. All three were the
  same accepted mis-type.) Tests:
  `examples/errors/optional_coalesce_default_too_deep.saw` and
  `examples/optional_coalesce_peel_depth.saw` (the accept side).

## DECIDED — Aug 8 morning round (user, the 181 policy)

Closed items: see todo_aug1-aug9.md.

- **RULED and BUILT:** the DF-181d connect fix scope (IPv4-literals-now vs full
  resolution) became design 184, which shipped both — a literal is parsed in Saw
  and dialled directly, a name is resolved through an offloaded seam.
