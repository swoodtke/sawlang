# Design 222 — the safe async rewrite: retiring E2 into a named verified-unsafe core

**Status: AUTHORED Aug 14 (user-directed), PROTOTYPE brief. Dispatches
immediately after 218 stage 4 integrates** — stage 4 rewrites the exact
target surface (teardown/cancel/panic paths, `__release` bodies) and
ratifies the R8/P3/P4 trusted list, which is this brief's unit-0 work
inventory. Cutting a branch earlier would redo the cancel-path half.

## The goal

The coroutine transform's output becomes ORDINARY CHECKED SAW — every rule
the typechecker applies to user code applies to generated code — with the
E2 exemption DELETED, not narrowed. Whatever genuinely cannot be expressed
safely lands in a NAMED verified-unsafe core: a per-item list in the 218
enforcement brief, each entry carrying an impossibility argument in the
218a §7 style, ratified the way stage 4 ratifies the trusted list. "Trust
the transform" ends; "trust these N named constructs, for these written
reasons" replaces it.

This is a PROTOTYPE: build the mechanism on the branch, measure everything,
and report — the landing decision happens at review, not inside the
dispatch. A unit that works cleanly is still committed per-unit with green
suites so the branch is integrable if review says land.

## Where E2 stands after stage 3 (unit 0 re-verifies on post-stage-4 main)

Stage 3 split E2's coverage: declarations the transform AUTHORS are now
CHECKED (`unsafe_decl_checked` — the transform computes `is_unsafe` from
what each declaration touches and design 130's rule verifies it; a wrong
answer is a compile error). What E2 still exempts:

1. **The drive-site cast in REWRITTEN USER BODIES** — a plain `func main()`
   calling a suspending method gets
   `__saw_drive_C_slow((&c) as UnsafeConstPointer<C>)` spliced into its own
   body, and deleting E2 would demand `unsafe` on a function whose author
   wrote no pointer (the provenance error, E1's class).
2. **The cell plumbing** — `__cellp` derefs in `_result_place` /
   `_cancel_place` (stage 4 may have moved these; unit 0 re-inventories).
3. **The wake latch** — the `__io_tok` / `&self.__wake` cast that makes
   `resume`'s unsafety unconditional (design 91/102 reactor wakeup).

Known context worth reading before any unit: the stage-3 commit d13ba3c3
(the written-down `is_unsafe` predicate per declaration kind), 218a §6 (the
exemption inventory), designs/218-enforcement-architecture.md (the
verified-unsafe core concept this brief instantiates), and stage 4's final
trusted list once it lands.

## Units

**Unit 0 — inventory on real main.** Re-derive E2's surviving coverage on
post-stage-4 main by MEASUREMENT: flip E2 off, compile the corpus, and
categorize every resulting error by construct (the error list IS the work
list — no grep-derived inventory). Take stage 4's ratified trusted list
alongside. Output: the definitive item list for units 1-3, recorded in this
brief.

**Unit 1 — the safe cell.** A typed cell abstraction in
`std.compiler.frame` (the DF-218g identity mechanism already makes this
module's types compile into every driven program without claiming bare
names — Slot/UnsafeRef/Poll precedent) that gives result and cancel access
a safe, checked spelling, replacing the raw `__cellp` derefs. Design
constraint: the executor side (`__TaskCell`, `__VoidCell`,
design 221's Int root cell if landed by then) keeps working unchanged —
this wraps the frame side, it does not redesign task result delivery.
Conformance rows for the cell's contract land first (obligation 3 applies:
this is a safety surface).

**Unit 2 — the drive-site spelling.** Remove the caller-body cast: the
drive wrapper takes a spelling that is SAFE at the call site (candidates,
in preference order: the driver declaring a reference parameter — design
201 already made a spawned frame's reference parameter a pointer under the
hood; a `borrows`-style lend; a safe constructor on the frame type that
does the cast INSIDE checked-generated code). The acceptance test: E2's
rewritten-bodies coverage EMPTIES — a user body after rewrite names no
unsafe type — and the design-130 rule runs on rewritten bodies with zero
exemption. This is the unit that makes "rewrite async functions safely"
literally true for user code.

**Unit 3 — the wake latch.** Expected hardest; the reactor wakeup cast may
be genuinely unsafe (a pointer that outlives the frame's checked scope,
handed to the reactor). Permitted outcomes, in order of preference: a safe
wrapper (same treatment as unit 1); OR a verified-unsafe-core entry with a
written impossibility argument tied to the reactor contract (design 91/102)
— NOT a shrug. If it enters the core, `resume`'s unsafety stays
unconditional and the core list says exactly why.

**Unit 4 — E2 deletes.** The flag's read site goes; the design-130 rule
runs everywhere; the verified-unsafe core list (possibly empty, possibly
unit 3's one entry) is recorded in the 218 enforcement brief and cross-cited
from 218a §6. The corpus compiles with zero E2 reads. Gate: full suite,
corodiff --quick + the generic axis, irdet --all, then the full tracked
battery.

## Constraints

- The six deferred 218 census families and the two scrutinee-temp rows keep
  their legacy encodings — OUT OF SCOPE; if a unit's change brushes one,
  defer that construct with the citation, exactly as stages 1-4 did.
- DF-218k/l/m (the suspending-method trio) are a separate family sweep —
  out of scope.
- DF-219c, DF-220a/b/c: out of scope (221 owns the DF-220 family).
- Standard process rules: stop-don't-workaround with DF notes; per-unit
  commits, suite green each; the suite lock; foreground gates.

## What review decides afterward

Whether the prototype lands as-is, lands with changes, or feeds a redesign;
and the ratification of whatever the verified-unsafe core contains. Items
expected to need rulings: unit 2's spelling choice if the preference order
fails, and unit 3's core entry if the latch resists wrapping.
