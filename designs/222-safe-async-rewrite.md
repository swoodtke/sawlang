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

### UNIT 0 LANDED (Aug 14) — the measured inventory, and it corrects the brief

Method: `self.exempt_unsafe_trigger = False`, then compile all 1547 corpus
programs (`examples/` + `examples/conformance/`, each with its own
`COMPILE-FLAGS`) and collect every design-130 trigger diagnostic; then the SAME
file set with E2 restored, and subtract. Probes:
`.build/scratch/probe_e2_corpus.py` + `probe_e2_categorize.py` (gitignored).

- E2 off: **172** files diagnose. E2 on: **6** (`U04`/`U05`/`U06`/`U27`/`U30` +
  `generic_instantiation_unsafe_signature` — the design-130 rows that MEAN to
  fail, all first-pass). **Net E2 coverage: 166 files.**

| # | construct | emission site | files | the type the user body names |
|---|-----------|---------------|-------|------------------------------|
| A | spawn-site group cast | `_spawn_site_rule`, coro_transform.py:7578 | 158 | `UnsafeConstPointer<TaskGroup>` |
| B | drive-site receiver cast | `_rewrite_drive_sites`, :7646 | 10 | `UnsafeConstPointer<Recv>` |
| C | reference-argument cast | `_ref_arg_to_ptr`, :7613 (called from BOTH A and B) | 2 | `UnsafePointer<T>` |

**Three corrections to the brief's predicted list, all in the same direction —
E2 is smaller than the brief thought, and unit 2 is bigger.**

1. **The brief's item 1 is a FAMILY of three, not one cast.** The drive-site
   receiver cast is the shape the stage-3 commit named, but it is 10 of 166
   files. The dominant construct is the SPAWN site's `(&group) as
   UnsafeConstPointer<TaskGroup>` — 158 files, and every one of them a program
   whose author wrote `group.spawn(worker(n))` and nothing else. Both funnel
   reference ARGUMENTS through `_ref_arg_to_ptr`, which is the third.
2. **The brief's item 2 (the cell plumbing) is NOT E2 coverage.** Zero files
   diagnose `__cellp`. `_result_place` / `_cancel_place` are read only from
   `resume` / `is_cancelled` / `release` / the spawn helper — declarations the
   transform AUTHORS, which since stage 3 carry `unsafe_decl_checked` and
   declare `unsafe` honestly. The cell is trusted-list item 2; it does not
   block E2's deletion.
3. **The brief's item 3 (the wake latch) is NOT E2 coverage either**, for the
   same reason: `__io_tok`'s `(&self.__wake) as UnsafePointer<Int>` lives in
   `resume`, which declares `unsafe`.

**Consequence for the unit order.** Unit 2 alone is E2's blocker; units 1 and 3
are trusted-LIST work (they shrink what stage 4 ratified), not E2 work. They are
built in the brief's order anyway, and each reports its own acceptance
measurement.

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

### UNIT 1 LANDED (Aug 14) — the cell gets a named handle, and "safe" is refused honestly

**The safe cell the brief asked for does not exist under design 130, and the
reason is design 130's own soundness argument.** A cell handle's accessors are
not sound for every input — the referent is storage the GROUP owns, and a handle
outliving it dereferences a corpse — so by the rule "a function with all-safe
parameters must be sound for every input; a precondition is spelled as an
unsafe-typed parameter", the receiver must BE unsafe-typed. The tempting shape is
`Vector`'s (a safe struct with an `UnsafePointer` field and `unsafe` methods),
and it does not transfer: `Vector` OWNS its buffer, so its invariant is its own
to keep, while a cell handle's invariant is a fact about somebody else's
lifetime. Writing it that way would launder the unsafety into a type whose
holders owe nothing — exactly what unit 3's instruction forbids, applied one unit
early. A genuinely safe cell needs SHARED OWNERSHIP (the cell behind an `Arc`),
which is a redesign of task result delivery and out of this unit's scope by its
own constraint.

**What landed instead: the cell joins `UnsafeRef`.** `__cellp` is
`UnsafeRef<__ResultCell<T>>` / `UnsafeRef<__VoidCell>` where it was a bare
`UnsafePointer`, minted through the existing `_unsaferef_init` funnel at
`_build_frame_init` (one more entry point on a docstring that already names
them), and every cell READ — `is_cancelled`, the cooperative-cancel branch, the
copy-down to a sub-frame, a rewritten `cancelled()` — is `deref()`, an ordinary
`borrows` accessor the place system judges. Trusted-list item 2 stops being
bespoke plumbing with its argument in a comment and becomes an instance of item
1, whose argument is written on the type.

**One half did NOT migrate, and it is a deferred family, not a new problem.** The
result WRITE keeps the raw index, forwarded through the handle's own `p`.
Measured: routing it through `deref()` broke three corpus programs
(`coro_iflet_suspending_deinit`, `coro_nested_iflet_struct_init`,
`taskgroup_nested_ambient`) with ``cannot copy value of type `Res` which
implements NoCopy`` at context `closure capture`. The mechanism is
`FAM_WINDOW_MOVE` / DF-218h exactly: a place window is lowered as a CLOSURE, so
every enclosing local the assignment's RHS names becomes a by-value capture — and
the stored value is precisely what a frame's locals feed, so the write meets it
every time rather than occasionally. Forwarding `<handle>.p` is stage 3's own
answer to the same shape (its finding (a)). The write migrates with the
window-move family, in that family's landing.

Conformance: K32 (rows first) pins the observable half — result moved to the
joiner and dropped once at NoCopy and Arc tiers, an unjoined result released once
at group teardown, and the cancel word read through the handle at both cell
shapes. Green before the rewrite and after it. Suite 1854 / 25 xfailed at both
commits. **E2 is unchanged by this unit, as unit 0 predicted.**

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

### UNIT 2 LANDED (Aug 14) — the reference-parameter driver, and E2's coverage measures ZERO

The brief's first-preference candidate, and it took no fallback. All three of
unit 0's constructs stop casting at the CALL and start declaring a REFERENCE at
the callee — the same move design 201 already made for a spawned frame's
reference parameter, applied to the other two positions:

| construct | before (in the author's body) | after |
|---|---|---|
| A spawn site | `__spawn_f((&group) as UnsafeConstPointer<TaskGroup>, …)` | `__spawn_f(&group, …)`; `__spawn_f(__group: &TaskGroup, …)` derives `__gp` in its own body |
| B drive site | `__saw_drive_C_m((&c) as UnsafeConstPointer<C>, …)` | `__saw_drive_C_m(&c, …)`; the driver takes `__recv: &C` (`recv_ref_type`) and casts at `_build_frame_init` |
| C reference argument | `f((&var x) as UnsafePointer<T>)` | `f(&var x)`; the driver/helper parameter keeps `&var T` and `_frame_param_arg` casts |

Nothing about the ADDRESS moved — the same pointer is taken over the same
storage, at the same moment. What moved is WHOSE DECLARATION owns it: out of a
body the transform rewrote, into the one it authored, which since stage 3 says
`unsafe` honestly and is held to it (`unsafe_decl_checked`). That is the whole
architecture in one edit — the crossing is not hidden, it is attributed.

**Acceptance, measured the same way unit 0 was.** E2 off, whole corpus (1548
files): **6 diagnose, and they are exactly unit 0's 6 pre-existing first-pass
rows.** E2's coverage of rewritten bodies is 166 → **0**. The full suite is green
WITH THE FLAG OFF (1854 / 25 xfailed), which is the flip's real gate — the flag
is now dead code, and deleting it in unit 4 changes no behaviour.

Two things a reviewer should look at, both deliberate:

- **The receiver reference is SHARED (`&c`), not `&var c`, and that mirrors what
  the cast did** (`ReferenceExpr(mutable=False)` in both the drive-site and
  spawn-site constructions before this unit). Keeping it shared is what makes
  this a zero-delta change for a `let` receiver, which the corpus has. The frame
  still mutates through the handle — legal, because the driver is the
  `unsafe`-declared declaration that owns the crossing, and design 88's D6
  confinement says the caller executes nothing while parked on the drive. The
  honest alternative is to mirror the method's own `self_mutable`, which would
  make the call site's borrow say what the callee does; it needs a receiver-
  mutability lookup at the rewrite and would demand `var` receivers the corpus
  does not currently write. Flagged rather than done.
- **The spawn helper takes `&TaskGroup` and re-derives the pointer** rather than
  taking `&var TaskGroup` and calling `__enqueue` (a `&var self` method) through
  the reference. Same reason and the same zero-delta property.

**Unit 3 — the wake latch.** Expected hardest; the reactor wakeup cast may
be genuinely unsafe (a pointer that outlives the frame's checked scope,
handed to the reactor). Permitted outcomes, in order of preference: a safe
wrapper (same treatment as unit 1); OR a verified-unsafe-core entry with a
written impossibility argument tied to the reactor contract (design 91/102)
— NOT a shrug. If it enters the core, `resume`'s unsafety stays
unconditional and the core list says exactly why.

### UNIT 3 LANDED (Aug 14) — the latch is a CORE ENTRY, and the wrapper was built before it was refused

**Outcome: verified-unsafe core entry, not a wrapper.** The instruction was not
to force one that launders, so the wrapper was written and RUN first, and it
launders measurably.

**The probe** (`.build/scratch/u3_latch_probe.saw`, compiled and run): the
candidate is `func wake_token(word: &var Int) unsafe -> Int` — all-safe
signature, unsafe body, exactly the shape a `std.compiler.frame.wake_token`
would take. Its caller compiles with **no `unsafe` declaration**. That is the
whole objection: the address still escapes, and the obligation has disappeared
from every signature between the escape and the reader. It also violates design
130's own soundness premise from the inside — a function with all-safe
parameters must be sound for every input, and this one is sound only for a
word whose owner outlives a registration the caller knows nothing about.

**The other candidate, `UnsafeRef<Int>`, is refused for a different reason.** It
does not launder (a `resume` binding one still declares `unsafe`), but the
contract it states — "the referent outlives every `deref()`" — is not the
obligation that has to hold here, and nobody ever derefs it. Attaching it would
make a reviewed-looking type carry the wrong theorem. There is a mechanical
blocker beside the principled one: `__io_tok` must stay an `Int` to be copied
down the frame chain at every drive and to reach `__saw_rt_reactor_register(r,
fd, w, token: Int)`, which rt/ABI.md freezes — the handle would project back to
an integer one line later.

**The argument, traced rather than asserted** (now also at the emission site, the
single `io_tok_init` in `_FrameBuilder.build`):

1. The address **leaves the type system as an integer** and is stored in KERNEL
   memory — a kqueue `udata`, an epoll `data.u64`.
2. The **write side is the runtime's poll**, in another module and on another
   thread, rebuilding a pointer from that integer with no provenance:
   `rt_reactor_poll` does `let tokptr = ud as UnsafePointer<Int>; tokptr[0] = 0`.
3. Validity extends over the **registration**, which is not a lexical extent: the
   frame's box holds the address stable (design 134), one-shot rearm stops a
   fired event re-firing, and DF-134a's `release` unregisters what an exiting
   frame left armed.
4. In an MT group the store is **unsynchronized** against the executor's reads —
   the poll runs outside the queue lock by design, with a bounded timeout and a
   persistent latch word so a fire racing a park is caught on the next scan.

No Saw type states (2), (3) or (4). `resume`'s unsafety therefore stays
unconditional, and the core list says why.

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
