# Design 189 — scoped task borrows: the capture's extent is the task's life

**LANDED Aug 9 (units 1-3; unit 4 NOT built — see below). Three commits, the
full suite green at each (1578 passed, 4 pre-existing xfails at the last).
Units 1 and 2 landed as ONE commit: the diagnostics ARE what the checks emit,
and there was no separable second change. All three pins flipped XPASS —
`spawn_capture_alias`, `spawn_capture_caller_alias`, `spawn_capture_move_root`
— and their EXPECT directives now pin the chosen wording. Design 188's pins are
untouched: a program that breaks the LIFO ordering still gets exactly 188's
error, because `_check_spawn_capture_order` returns the specs it refused and the
extent registration skips them.**

**Diagnostic wording chosen** (the brief asked for the existing vocabulary plus
one sentence naming the task and the release point):

```
error: exclusive access violation: `n` cannot be written here — the task
       spawned at line 21 holds `&var n` until `h.join()` releases it
error: cannot `move` `buf` while a spawned task borrows it: the task spawned at
       line 26 holds `&var buf` until `h.join()` releases it
```

The access clause varies over read / written / captured into another task /
accessed by reference; the extent clause is one sentence with two forms, the
second being ``its group `group` is torn down at the end of this scope (nothing
joins its handle)``. The hint names the join and then `Arc<Mutex<T>>`/`Channel`.

**One rule beyond the brief's letter, in its spirit: the LOOP case.** A capture
still live when a loop body ends would open a second exclusive borrow of the
same root on the next iteration — one textual spawn, N live borrows, the Law
violated by iteration rather than by a second line. It is refused at the spawn,
beside the cross-iteration MOVE rule that already lives in `_check_loop_body`.
Spawn-and-join-inside-the-body is untouched and pinned as an accept.

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

1. **The extent machinery** — LANDED. `TaskCaptureBorrow` records live in
   function-local checker state beside the move state (`core.py`), registered at
   `_check_taskgroup_spawn` and released at `h.join()` / group death. Five
   existing access sites consult them: `_check_call_exclusivity` (which is where
   a second `[&var n]` capture is refused — a capture list is already part of a
   call's access set, so DF-189a needed no new site), `_check_identifier`
   (reads), `_check_move_expr`, the assign/compound-assign statements (writes,
   charging the access path's ROOT), and `_check_loop_body`. Conservative at
   every join point: `_check_block` restores what was live on entry, so a join
   inside a branch does not release for the code after it.
2. **Diagnostics** — LANDED WITH UNIT 1 (see the wording above). The errors are
   the existing exclusivity/move vocabulary plus one sentence; no new error
   family, no new `ErrorKind`.
3. **Pins + accepts** — LANDED. The three pre-pinned probes flipped.
   `examples/spawn_capture_join_releases.saw` is the accept side as one running
   program: disjoint roots into two concurrently-live tasks, two shared
   `[&base]` captures live at once with a caller read between the spawns, and
   spawn-join-in-a-loop-body over a `Vector` root (the storage DF-189c handed a
   task after freeing). Two new error pins cover the conservative edges:
   `errors/spawn_capture_unjoined_handle.saw` (discarded handle, and a join
   inside an `if`) and `errors/spawn_capture_across_iterations.saw` (the loop
   rule). Probe 4's MT rejection needed nothing: design 188 unit 5 already
   pinned it at `errors/spawn_capture_mt_send.saw`, and 189 leaves it untouched.
   The single-capture spawn-join-use idiom is 188's `spawn_capture_declared_
   before.saw` and was deliberately not duplicated.
4. **Design-88 relaxation (OPTIONAL — separate ratification): NOT BUILT, and
   still owed a ruling.** The same machinery would bless reference PARAMS at
   spawn roots (`group.spawn(f(&x))`) under the same declared-before +
   handle-extent rules, restoring param/capture symmetry in the permissive
   direction and retiring the Arc/Mutex tax on scoped sharing. Unit 1 has now
   proved the extent model in the capture position, which was the precondition
   this unit was waiting on; it remains future work until ratified.

## What landed against what the brief asked

Everything in units 1-3, plus the loop rule described in the status block. The
release points are exactly as ratified: the handle carries the borrow, `join()`
releases, group death is the fallback for a discarded or unjoined handle, an
exclusive capture excludes caller reads, and `cancel` does not release. A handle
that escapes its scope or is stored keeps its borrow to group death — reached
here by not recognizing a join on anything but an identifier receiver, and by
clearing the handle name (not the borrow) when the handle binding dies unjoined,
so the diagnostic stops naming a binding that is out of scope.

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
