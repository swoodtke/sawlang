# Design 189 — scoped task borrows: the capture's extent is the task's life

**Status: APPROVED + QUEUED (user, Aug 9: "it is a legit hole that we
need to fix … they seem consistent and understandable — let's brief it
as discussed"). Probe-driven: the probes CONFIRMED two silent
use-after-frees reachable from safe code, so this is a SOUNDNESS brief.
Ratified clarifications from the review conversation: the borrow
releases at the HANDLE's consuming join (or group death for a
discarded/unjoined handle — the fallback, not the norm); an exclusive
`[&var]` capture excludes caller READS too, the standard
one-writer-XOR-many-readers table over a task-length window — a caller
that wants to observe mid-task state uses `Arc<Mutex>`/`Channel`, where
the synchronization is visible in the types. The user notes the refused
patterns may be rare in practice; the rule is enforced for consistency
and the hole, not for ergonomics. Queue slot: after 188, before 186.
Probes: `.build/scratch/probe_borrow_extent_*.saw`,
`probe_capture_after_group_uaf.saw`, `probe_capture_mt_group.saw`
(gitignored scratch — outcomes recorded here and pinned at landing).**

## The probe record (Aug 9, all on main at 3f392ec)

1. **Two `[&var n]` captures of one root, ST group**: COMPILES; both tasks
   mutate the one root (`n is 11`). Two exclusive borrows co-live across
   suspensions — the Law of Exclusivity is violated with no diagnostic
   (benign for `Int` single-threaded; the contract is broken regardless).
2. **Caller writes and reads the root while a task holds `[&var n]`**:
   COMPILES (`caller wrote 5, read 5`, task later saw it). Writer aliases
   writer across the spawn/join window.
3. **Deinit-bearing root declared AFTER its group** (188's DF-188c(i)
   probe obligation): CONFIRMED silent UAF — the task's instrumented
   pushes print AFTER "scope ends", into a `Vector` whose deinit already
   freed the buffer. Exit 0. DF-188c(i) is a HOLE, not an asymmetry.
4. **`[&var n]` capture into `threads: 2`** (DF-188c(ii)): ALREADY
   REFUSED — a closure is not `Send`, so the frame-param Send check
   rejects every closure-carrying MT spawn with a good message. Case (ii)
   owes only a pinned regression test of the existing rejection.
5. **`move buf` while a task's `[&var buf]` is live, root declared
   BEFORE the group** (the ordering 188 rules LEGAL): COMPILES; main
   never suspends before the move, so `consume(move buf)` sees len 3 and
   DROPS the buffer; the join then drives the task, which reads the dead
   slot and reallocs FROM FREED MEMORY. Silent, exit 0. **This route is
   untouched by DF-188c(i)'s declared-after rule — extent tracking is
   required for soundness.**

## The rule

**A reference capture into a spawned task borrows its ROOT for the
task's lifetime, and the task's HANDLE carries that borrow.**

- `[&var x]` at a spawn opens an EXCLUSIVE borrow of `x`'s root; `[&x]`
  opens a SHARED one. The borrow is registered in the existing
  exclusivity machinery — not a new checker, a new EXTENT.
- **Release**: joining the handle (`h.join()` — already a consuming,
  move-out operation, so the release point is statically known) ends the
  borrow; after the join the caller touches the root freely, which keeps
  the natural spawn-join-use pattern legal. A handle that is DISCARDED
  or never joined releases at the GROUP's death (its Deinit joins the
  task), which is in-scope by DF-188c(i)'s ordering rule.
- **Consequences, mapped to the probes**: probe 1's second `&var`
  capture of a borrowed root = exclusivity error at the second spawn;
  probe 2's caller write/read while borrowed = the ordinary
  one-writer-XOR-many-readers error; probe 5's `move` of a borrowed
  binding = the existing move-while-borrowed refusal, now firing because
  the borrow is finally VISIBLE. Probe 3's shape is subsumed: a root
  whose deinit (LIFO) would run while a task's borrow is live is the
  same error 188's DF-188c(i) lands — at landing, de-duplicate so ONE
  diagnostic (the LIFO-teaching one) covers it.
- **Conservative edges (v1)**: a handle that ESCAPES the group's scope
  or is stored extends its borrow to group death; `cancel` does not
  release (the cancelled task still runs its cancel path); shared `[&x]`
  captures compose with other readers as everywhere else.

## Units

1. **The extent machinery**: register capture borrows at spawn sites,
   release at handle-join / group death; wire into the existing
   path-disjointness and move checkers. Flips the three new pins (below).
2. **Diagnostics**: the errors are the EXISTING exclusivity/move errors
   with one added sentence naming the task and the release point ("the
   task spawned at LINE holds `&var buf` until its join at LINE / its
   group's death"). No new error vocabulary.
3. **Pins + accepts**: probes 1, 2 and 5 are PRE-PINNED on main (user,
   Aug 9) as `examples/spawn_capture_alias.saw` (DF-189a),
   `examples/spawn_capture_caller_alias.saw` (DF-189b) and
   `examples/spawn_capture_move_root.saw` (DF-189c) — unit 1 flips all
   three XPASS. Add accept-side tests for the patterns that must
   SURVIVE: single capture + touch-after-join, disjoint roots into two
   tasks, shared captures beside reads, the spawn-join-use idiom.
   Regression-pin probe 4's existing MT rejection.
4. **Design-88 relaxation (OPTIONAL — separate ratification):** the same
   machinery blesses reference PARAMS at spawn roots (`group.spawn(f(&x))`)
   under the same declared-before + handle-extent rules, restoring
   param/capture symmetry in the permissive direction and retiring the
   Arc/Mutex tax on scoped sharing. Recommend ratifying only after unit
   1 proves the extent model in the capture position.

## Sequencing

Elevated by the probes to a soundness brief: recommend queue position
IMMEDIATELY AFTER design 188 (they share the exclusivity surface and the
DF-188c(i) diagnostic; 188's unit 5 record already points here). Before
186 on the same only-silent-wrong-answer logic that put 188 ahead of it.

## Explicitly out

Detached tasks / borrow-transfer (no detach exists to design for);
`async` borrow regions or lifetimes (extent = task life, nothing finer);
MT reference captures (probe 4: already refused; a Sync-checked MT borrow
design is future work if ever); the join-at-the-brace teardown reordering
(declined in 188 unit 5, CancelGuard deadlock).
