# Design 188 — the safety-audit batch

**Status: LANDED (Aug 9), all eight units — see the landing report at the
bottom. The record below is the brief as ratified.**

**Status when written: APPROVED + QUEUED, held (Aug 9). Source: the Aug-8 external
review (`review.md`) + audit (`safety_audit.md`, 247 rows — the probes
live in gitignored scratch, which is why every landed finding here
carries an examples/ pin). Findings filed as DF-188a-i in the tracker.
All four rulings RATIFIED in the Aug-9 one-by-one review (units 2-5
record each, including the alternatives explored and declined: NoMove's
two-axis model, interior-heap pinning, join-at-the-brace). DO NOT
DISPATCH until the user resumes the queue. DF-188e (audit D5) is NOT
here — it joined design 187 (same transform surface). Queue position
when the user resumes: after 187, ahead of 186 — unit 2 is the only
known silent-wrong-answer-in-safe-code bug in the tree.**

## Units

1. **The no-escape holes — DF-188a + DF-188b (mechanical, no ruling).**
   Run design 163d's NAMES walk over ENUM CASE PAYLOAD types with the field
   position's diagnostic (closes the `case Held(r: &Int)` route into
   `Vector` storage and the two read-back ICEs behind it), and RESOLVE TYPE
   ALIASES to their underlying type before the walk everywhere it runs
   (closes `type R = &Int` laundering into fields and generic arguments;
   the return position currently fails only by accident, on a type
   mismatch — after this it fails by rule). Flips
   `enum_ref_payload_escape.saw` and `typealias_ref_launder.saw`; add the
   audit's other alias positions (R41, R50) as plain error tests.
2. **DF-188f — place windows join the Law of Exclusivity (RATIFIED, user
   Aug 9: "yes to D6").** PIN: `examples/place_window_exclusivity.saw`
   (the two-window lost-write shape; the fixing commit adds the Data
   corruption twin and the window-beside-`&var root` case as plain error
   tests). The trigger, from the audit's boundary table: two
   by-reference accesses to one ROOT in one call, at least one a `borrows`
   place — two windows, or a window beside a `&var root` argument — compile
   and silently lose writes (`Data` corrupts: audit X40). What refuses the
   ExplicitCopy/NoCopy shapes today is the COPY POLICY (the compiler copies
   the receiver to open the second access and reports that copy), which is
   the masking: free-copy receivers sail through. The fix the spec already
   promises ("a place borrow charges its ROOT"): fold place-window roots
   into the existing path-disjointness check that already handles
   `f(&var x, &x)` / field / tuple / constant-index paths, and make the
   refusal an EXCLUSIVITY diagnostic on every tier, so the copy-policy
   error stops being load-bearing. Everything outside the trigger stays
   legal (single window, windows in separate statements, window + shared
   read of a disjoint path, plain fixed-array indexing) — the audit's
   correct-shapes table becomes the accept-side test set. Related family:
   DF-151j, DF-176b, DF-175a; DF-176c's held item is the WRITE-path half of
   the same lowering and should be re-examined in this unit's light.
3. **DF-188g — a lend must be rooted in the receiver (RATIFIED, user
   Aug 9: "yes with the narrow receiver rule").** The NARROW form: the
   lent place must be storage reached through the receiver — an
   accessor's local AND its parameter are both refused, even where the
   storage would outlive the window (an outlives-based widening stays
   available later; the reverse migration would not). PIN:
   `examples/lend_accessor_local.saw`; the fixing commit adds the
   parameter-lend twin as a plain error test. A `borrows` accessor lending its own local or
   parameter is accepted; reads are sound (the frame is alive for the
   window), writes land in storage that dies at resume — `c.slot() = 99`
   is a silent no-op. The match-arm rule ("a payload of a value the body
   just built dies with the accessor") states the principle; apply it to
   plain `lend <local>` / `lend <param>`: the lent place must be storage
   reached through the receiver. Error names the binding and the rule.
4. **DF-188d — `NoMove`, a declared relocation tier; `TaskGroup` is its
   first conformer (RATIFIED, user Aug 9, refined in review).** `move
   group` with a spawned task is accepted today and the runtime aborts;
   design 124 defines a group as a SCOPE, so the type system honors it.
   The mechanism, as ratified:
   - **Duplication and relocation are SEPARATE AXES.** `NoMove` is a new
     declarable empty marker conformance governing relocation only. It
     does NOT imply `NoCopy` — it REQUIRES it: declaring `NoMove` on a
     type whose copy tier is anything but a declared `NoCopy` is a
     compile error, so both properties are always explicitly stated
     (`extension TaskGroup: NoCopy {}` + `extension TaskGroup: NoMove {}`).
     Relaxing that check is how `NoMove + ExplicitCopy` (the C++
     re-register-on-copy shape, hand-written `copy()` only) opens later
     with zero migration; v1 ships the strict point.
   - **Semantics**: a `NoMove` value moves exactly once — from its
     constructor into its binding — and never again. `move x`,
     `Optional.take` of a `NoMove` payload, and every transfer position
     are refused (the NoCopy machinery already funnels them through
     `move`; `NoMove` refuses the funnel). Whole-referent replacement
     through `&var` stays legal — destruction then construction at the
     same address, not a move (the old group's Deinit joins first, which
     IS design 124).
   - **The contagion, documented**: a struct/enum with a `NoMove` member
     does not compile until it declares `NoMove` (+ `NoCopy`) itself —
     the design-139 declared-cascade style, never silent inheritance.
     The spec states this cost plainly; the escape for a type that wants
     a movable handle over pinned state is composition (heap
     indirection), which needs no language mechanism.
   - **Fences**: not a generic bound (`T: NoMove` refused, hint at the
     conformance position); no Pin/projection machinery; no
     self-referential blessing. Error message on a refused move cites
     design 124's scope rule for TaskGroup.
   - Considered and declined: pinning only the group's INTERIOR behind a
     heap handle (already expressible by composition; buys returnable
     groups, which 124 rejects, reopens DF-188c as a real dangle, and
     taxes the scheduler hot path).
   PIN: `examples/taskgroup_move_live.saw`.
5. **DF-188c — spawn captures, ruled by soundness lines, not symmetry
   (RATIFIED, user Aug 9, after a three-round design conversation).** The
   blanket refusal was considered and REJECTED — a task borrowing from its
   spawner is structured concurrency's core promise, not a hazard. Three
   cases:
   - **(i) A reference capture of a binding declared AFTER its group is an
     ERROR.** PROBE RESULT (Aug 9, instrumented): CONFIRMED silent UAF —
     the task's pushes print after "scope ends", into a Vector whose
     deinit already freed the buffer, exit 0. This case is a HOLE, filed
     as such. The diagnostic teaches the model: name the binding, the
     group, the LIFO order, and the fix ("declare `buf` before `group`").
     PIN: `examples/spawn_capture_after_group.saw`.
   - **(ii) Reference captures into a `threads: N` group — PROBED:
     ALREADY REFUSED.** A closure is not `Send`, so the frame-param Send
     check rejects every closure-carrying MT spawn with a good message.
     This unit owes only a pinned regression test of the existing
     rejection (design 189 unit 3 carries it).
   - **(iii) Single-threaded, declared-before-the-group captures STAY
     LEGAL — with the soundness caveat the probes exposed.** The
     scope-exit argument holds (group joins before anything declared
     ahead of it dies, NoMove closing the move-the-group route), but a
     `move` OF THE CAPTURED ROOT before the join escapes it: probe 5
     (`consume(move buf)` between spawn and join) reads-and-reallocs
     from freed memory, silently, in the ordering this ruling calls
     legal. That is DESIGN 189's charter (the borrow-extent rule, brief
     authored Aug 9 from these probes); (iii) stands as ruled here, and
     189 is the brief that makes it sound rather than
     sound-in-the-common-shape.
   Considered and DECLINED: hoisting the group's join ahead of scope
   teardown ("the join belongs to the closing brace") — it blesses every
   ordering but INVERTS the dependency the drop-to-terminate idioms rely
   on (a CancelGuard/closing-sender declared after the group, whose
   DEINIT is what lets the tasks finish, deadlocks a join that now runs
   first — an undiagnosable runtime hang traded for a compile-time
   error), makes destruction order type-dependent against the
   deterministic-LIFO contract, and re-creates the hazard one level up
   for group-into-group captures. Rule (i) is the same invariant
   expressed in SOURCE: the group opens the scope it governs, so it is
   declared at the top of it. FOLLOW-UP BRIEF (filed in the tracker, not
   this unit): scoped task borrows — extend the Law of Exclusivity with
   a borrow-extent rule (a `&var` capture into a spawn holds its root
   exclusively until the group's death, closing the two-tasks-alias-one-
   root gap case (iii) leaves), and evaluate RELAXING design 88's param
   refusal under the same declared-before rule — restoring param/capture
   symmetry in the permissive direction.
6. **DF-188h — enforce the `unsafe` effect across a conformance
   (mechanical).** The documented direction: a conformer of an `unsafe`
   trait requirement must declare `unsafe`. Enforce it; the reverse
   direction (an `unsafe`-declared impl of a safe requirement) stays legal
   under rule 7 but gets the redundancy treatment the spec gives a
   redundant declaration `unsafe` — allowed, meaningful only about the
   body. Flips `unsafe_trait_requirement_effect.saw`.
7. **DF-188i — close the std gate list (mechanical).** Add `spinlock` and
   `slab` to `IMPORT_REQUIRED_STD_MODULES`, flip
   `spinlock_import_gate.saw`, and add the drift-proof test: walk
   LANGUAGE_SPEC's own gated-module table and assert each listed module is
   actually gated — the list can never silently diverge from the spec
   again. Sweep std/examples for any code that leaned on the bare names.
8. **Docs + tracker.** Spec: the exclusivity section gains the place-window
   sentence unit 2 implements; the `borrows` section gains unit 3's
   rooting rule; the TaskGroup section gains unit 4's non-movability; the
   trait section gains unit 6's conformance rule. Skill: same four, one
   line each. Tracker: DF-188a-i closed with causes; re-examine DF-176c
   against unit 2's landing and either close it or narrow it to what
   remains.

## Gates

Per-unit commits, full suite green each, zero uncited xfails; the four
pins flip in their fixing commits (plus the two ruling-gated pins added
once rulings land). Final battery: suite, lexdiff, astdiff, Saw-irdet
--all, bootstrap, gmgate, sos_runner both arches. The audit's
correct-shapes tables (X-series accepts, P11/P13/P15) become accept-side
regression tests wherever a unit touches their machinery — over-rejection
is a failure mode here, not a safety win. DF-188x follow-on findings as
usual.

## Explicitly out

The codegen ICE-vs-diagnostic cleanup and the two silent typechecker
fallthroughs (the review's item 2 — a real unit, but a diagnostics-quality
brief, not a safety one; candidate design 189); `visitor.py` dead code and
the review's hygiene list; D9/DF-174g (design 187 owns it); any change to
the interior-mutability exemption (design 186 owns that surface); the
scoped-task-borrows design (unit 5's follow-up: borrow-extent exclusivity
for captures + the design-88 param relaxation — its own brief);
`NoMove + ExplicitCopy` (unit 4 records the opening; no conformer yet).

## Landing report (Aug 9)

Eight units, eight commits, the full suite green at each. Suite went
1542 passed / 19 xfailed to 1565 passed / 11 xfailed: eight pins flipped and
fifteen tests added, of which six are accept-side boundary tests — the audit's
correct-shapes tables, landed wherever a unit touched their machinery, because
over-rejection was the stated failure mode here. Nothing in the corpus was
over-rejected by any unit.

What each unit's cause turned out to be is recorded per-finding in the tracker
(DF-188a-i, all closed). Three notes worth keeping with the brief:

- **Unit 1's alias half could not go where the rest of the walk lives.** Every
  written-form no-escape check runs in the PARSER, which is the pass that knows
  the position and cannot resolve a name. So the walk runs a second time in the
  typechecker with aliases resolved, over the same declared positions plus
  binding annotations, and the alias's back-conversion `R(&x)` is refused where
  it is written — that construction is what inhabits every position the walk
  guards, so refusing it is what makes the other refusals total.
- **Unit 2 needed one thing the brief did not name.** A window's extent is the
  whole call, which the use-site lowering makes literal by nesting the call
  inside the window closure. Audit row X31 (`sink(&var p.at(0), reset(&var p))`)
  puts the second reference inside a NESTED call, so folding window roots into
  the per-call check was not enough on its own; with a window open, references
  from nested calls in the same argument list join the access set. Deliberately
  conditional on a window: the same shape with no place in it is a question
  about when an argument's borrow starts, which is filed as DF-188j rather than
  answered here.
- **Unit 7 found a second half behind its own pin.** A gated module is not
  compiled in at all, so `static LOCK: SpinLock<Int>` — the pin's exact shape,
  and a declaration that never names the type in an expression — reached codegen
  and ICEd instead of being told to import it. The gate now runs at a static's
  declaration, on the argument design 149 already makes two lines away for the
  atomics check. Type ANNOTATIONS in general are still ungated (DF-188k).

DF-176c was re-examined against unit 2 as the brief asked and NARROWED rather
than closed: it is the receiver-COPY half, which a rule about how many accesses
one call makes does not touch.
