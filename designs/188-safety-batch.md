# Design 188 — the safety-audit batch

**Status: DRAFT (Aug 9). Source: the Aug-8 external review (`review.md`) +
audit (`safety_audit.md`, 247 rows — the probes live in gitignored scratch,
which is why every landed finding here carries an examples/ pin). Findings
filed as DF-188a-i in the tracker. FOUR units await user rulings, being
reviewed one-by-one — the recommendation is stated inline and the unit is
marked PENDING until ratified. DO NOT DISPATCH: the queue is stopped, and
the rulings must land in this brief first. DF-188e (audit D5) is NOT here —
it joined design 187 (same transform surface). Queue recommendation when
the user resumes: after 187, ahead of 186 — unit 2 is the only known
silent-wrong-answer-in-safe-code bug in the tree.**

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
2. **DF-188f — place windows join the Law of Exclusivity (PENDING RULING;
   recommendation YES).** The trigger, from the audit's boundary table: two
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
3. **DF-188g — a lend must be rooted in the receiver (PENDING RULING;
   recommendation YES).** A `borrows` accessor lending its own local or
   parameter is accepted; reads are sound (the frame is alive for the
   window), writes land in storage that dies at resume — `c.slot() = 99`
   is a silent no-op. The match-arm rule ("a payload of a value the body
   just built dies with the accessor") states the principle; apply it to
   plain `lend <local>` / `lend <param>`: the lent place must be storage
   reached through the receiver. Error names the binding and the rule.
4. **DF-188d — moving a live `TaskGroup` (PENDING RULING; recommendation:
   REJECT the move).** `move group` with a spawned task is accepted and
   the runtime aborts (`Vector.get: no place to lend`, SIGABRT). Design
   124 defines a group as a SCOPE whose Deinit structured-joins where it
   was born; honor that in the type system — a `TaskGroup` is not movable
   (v1: reject `move` outright; a group has no reason to relocate). The
   alternative (runtime survives relocation) buys nothing and costs a
   redesign.
5. **DF-188c — spawn-capture symmetry (PENDING RULING; recommendation:
   REFUSE, after a usage grep).** A `[&var x]` borrow-capture in a closure
   argument to a spawned call carries the same pointer into the same frame
   that a reference PARAM at a spawn root carries — and design 88 refuses
   the param with a considered diagnostic while the capture compiles. The
   audit could not prove the capture unsound in the ordinary shape (the
   group's Deinit joins before the spawner frame dies — and unit 4's
   ruling, if it lands as reject-the-move, closes the one route around
   that argument). Symmetry says one rule for one pointer: refuse the
   borrow-capture at a spawn root with design 88's own diagnostic. Grep
   the tree first; if real code depends on the capture spelling, bring the
   count back to the user before landing.
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
the interior-mutability exemption (design 186 owns that surface).
