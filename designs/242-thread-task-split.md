# Design 242 — Thread and Task: two engines, two names, no implicit fates

**Status: AUTHORED + RULED Aug 22 2026** (designed in conversation with the
user; every open point below carries its ruling — none remain). **Queue:
after the in-flight Aug-22 group (234 remainder + df-218xy), BEFORE design
238 units 2-7.** (Note: the DF-242a-c findings predate this brief and are
unrelated — they are the small-fix batch's range.)

## The problem, as found

A user asking "how do I fire-and-forget?" discovers, in order: that
`let _ = spawn { … }` — the natural guess — silently BLOCKS (the thread
engine's `Task<T>` deinit joins if unjoined, so the zero-width discard is a
sequential call plus thread overhead); that the thing `spawn {}` returns is
named `Task` while actual cooperative tasks hand out a `TaskHandle`; and
that true fire-and-forget has no affordance at all, only the
group-at-the-top-of-main idiom. Three findings in one question. The engines
are different machines — one blocks, one suspends; one's handle joins on
drop, the other's doesn't; `Channel.recv` vs `receive` — and the vocabulary
actively miscommunicates which one a call site is on.

## RULINGS (user, Aug 22 — all made in the design conversation)

1. **The namespace IS the engine.** `Thread.*` = OS threads, blocking.
   `Task.*` = cooperative, suspending. The suffix spelling
   (`Task.spawn_thread`) was considered and REJECTED: it makes two runtimes
   read as flavors of one, and the method's namespace would disagree with
   its return type. (Swift's `Task.detached` is not a precedent — both its
   forms are one engine.)
2. **`Thread.spawn { } -> Thread<T>`** (rename of today's
   `spawn {} -> Task<T>`), freeing the `Task` vocabulary for the
   cooperative engine: **`TaskHandle<T>` renames to `Task<T>`**, returned by
   `group.spawn` and the new `Task.spawn` alike. `VoidTaskHandle` renames
   to **`VoidTask`** — it stays a distinct named type because the
   visible-`Void` rule (122/132, absolute per DF-225h) makes `Task<Void>`
   unwritable as an annotation, and because its join semantics genuinely
   differ (joining a finished `VoidTask` returns; double-joining a valued
   `Task` panics). `Thread<Void>`'s analogue is **`VoidThread`**, same
   grounds.
3. **`Task.spawn { } -> Task<T>` spawns into a BACKGROUND SINGLETON
   group** — lazily constructed on first use (the `__saw_reactor`
   process-global getter, design 117, is the synthesis precedent; zero cost
   unused; a freestanding runtime may provide or refuse it), riding the
   ambient current-thread scheduler. At `main`'s return the singleton
   CANCELS every live member, joins, then exits — deterministic destruction
   holds on the cancel path (cancel wakes even io-parked tasks, design
   102). An MT (`threads: N`) flavor is explicitly NOT v1.
4. **`.detach()` exists on both handle types, consuming.**
   `Task<T>.detach()` hands the task to the process (it runs to completion
   or is cancelled at exit) and explicitly declares the result dropped at
   completion — the moral `let _ =`, so never-hide-errors is satisfied by
   the spelling. `Thread<T>.detach()` is the daemon thread: values deinit
   if it completes; at process exit the OS terminates it — the same
   documented boundary as 218b ruling 3's never-completed frame (process
   death drops nothing; any order exceeds the analog).
5. **NO IMPLICIT FATE: the singleton-form handles are must-consume.** The
   result of `Thread.spawn` must reach `join()` or `detach()` on EVERY
   path; the result of `Task.spawn` must reach `join()`, `detach()` or
   `cancel()` on every path. Both implicit-discard positions (bare
   statement, `let _ =` — design 151's family, extended: here even the
   EXPLICIT discard is banned because dropping has load-bearing semantics)
   AND an unconsumed scope exit are errors. Join-and-discard as an implicit
   default was considered and REJECTED (a joining deinit blocks every exit
   edge including error paths and buys completion nobody observes);
   cancel-on-drop was considered and REJECTED in favor of the error (the
   user decides). The per-path analysis is design 189's join-release
   machinery reused. v1 is FUNCTION-LOCAL: storing or returning an
   unconsumed must-consume handle is refused, naming `group.spawn` as the
   structured way to manage a dynamic set (`Vector<Task<T>>` stays a group
   idiom).
6. **`group.spawn` is EXEMPT — the obligation attaches to the SPAWN FORM,
   not the type.** A group handle may be dropped freely (bare statement
   included): the group is a declared, in-scope consumer and its Deinit is
   the join barrier — the accept-loop idiom
   (`while true { group.spawn(handle(accept())) }`) is unchanged. Group
   handles do NOT take `detach()` in v1: a group task may hold borrows
   (design 189) whose release point is the group's scope, and detaching
   past it is the use-after-free the rule exists to prevent.
7. **Borrows are banned AT the two singleton forms.** `Thread.spawn` and
   `Task.spawn` accept no borrow captures and no `&`/`&var` arguments — a
   detachable task has no join to release a borrow, and enforcing at the
   FORM (not at `detach()`) means the checker never traces handle
   provenance. Owned captures (moves, `Arc`, `Send` values) are the point
   and stay; "non-capturing" was considered and rejected as too strong.
8. **`Thread.spawn`'s body is `sync`-ENFORCED** (the `SpinLock.lock`
   precedent). A suspending body needs an executor, and "suspending work on
   a dedicated thread" already has a structured spelling:
   `TaskGroup(threads: 1)`. No per-thread reactor exists or is needed —
   there is ONE process-global reactor with precise cross-thread wake
   (designs 91/102/117), and `threads: N` workers are the existence proof
   that executors share it. What a suspending context needs is an executor
   loop, never a reactor.
10. **RULED Aug 24 (user) — the Task spelling + the SPAWN-BRACE rule,
   uniform across ALL THREE forms.** The Task engine's PRIMITIVE is the
   CALL form (`Task.spawn(work(3))`, matching `group.spawn`) — the brief's
   original brace-only spelling cannot suspend (the transform frames named
   functions only) and is superseded. The brace form survives as SUGAR over
   it with an EXPLICIT-CAPTURE-LIST REQUIREMENT, uniform across
   `Thread.spawn { }`, `Task.spawn { }` and `group.spawn { }`: the capture
   list IS the parameter list (`{ [count, conn] in ... }` — by-value
   capture semantics, which for a spawned body are exactly
   parameter-passing: transfer at the spawn, per tier, `[move x]` legal);
   an IMPLICIT capture (an enclosing local the list does not name) is a
   TEACHING ERROR pointing at the list; borrow entries (`[&x]`/`[&var x]`)
   are refused at the two singleton forms per ruling 7 and allowed at
   `group.spawn` per ruling 6/design 189; an enclosing TYPE parameter named
   by the body is refused v1 (future work). No new grammar — the list
   parses today; the desugar lifts the body verbatim into a hidden named
   function (listed captures = its parameters), which is why no capture
   analysis, no DF-218h interaction (a spawned env escapes → heap env), and
   no hidden-alloc wrinkle (design 135 names spawn's env) exist. The
   ~42-site Thread-brace corpus migration to explicit lists rides unit 3.
   Reader-visibility rationale: everything crossing a concurrency boundary
   is spelled at the crossing. TRAILING-BRACE syntax
   (`Task.spawn(priority: 3) { [p] in ... }`) is deliberately NOT here —
   briefed separately as design 243 and BACKLOGGED (a grammar-doctrine
   exception to be granted consciously, not under way).
9a. **RULED Aug 24 (user) — the crew-escape question, shape (a):** the
   must-consume obligation is discharged by a MOVE INTO STORAGE WHOSE OWNER
   CONSUMES IN ITS OWN `Deinit` — ruling 6's principle (a declared consumer
   discharges the obligation) extended from groups to owning types. v1
   approximation: the storing type declares a hand-written `deinit`
   (necessary, not sufficient); a checked "a `Thread<T>`/`Task<T>` field
   obliges the owner's deinit to consume it" rule is NAMED FUTURE WORK, not
   v1. std's `TaskGroup.crew` compiles under this reading unchanged.
9b. **RULED Aug 24 (user) — the runtime backstop:** an unjoined, undetached
   `Thread<T>`/`VoidThread`/`Task<T>`/`VoidTask` PANICS in its deinit,
   naming the type and the legal consumes. Under the checked rule this path
   is reachable only through 9a's approximation gap (an owner's deinit that
   forgot), which is a caller-checkable bug — a fault, not a status (the
   design-134 double-join precedent). This RETIRES the old implicit fates
   entirely: no silent join-on-drop, no cancel-on-drop — every fate is
   explicit, and the evading path dies loudly. Boundary: panics do not
   unwind, so no panic-during-panic hazard; a live OS thread at process
   death is the already-ruled process-death boundary.
9. **A `Thread.spawn` body is a BLOCKING-PERMITTED sync context.** A
   `blocking` extern called there runs DIRECTLY — no offload, the thread
   blocks and that is the point (calling a thread-phobic or long-blocking C
   library is a headline use). Without this the use case has no legal
   spelling at all: `blocking` externs are refused in ordinary sync
   contexts, and the two-declarations rule bans a non-blocking redeclaration
   of the same symbol. The blessed wait-here spelling
   `Thread.spawn { … }.join()` composes with it.

## Units

0. **Census.** Every `spawn {` site, every `Task<`/`TaskHandle`/
   `VoidTaskHandle` mention (annotations, fields, docs), `recv` vs
   `receive` call sites, any stored thread handles. Corpus + spec + skill.
   Probe the current `spawn {}` body's effect handling (is a suspending
   body refused today, and where) — the unit-4 enforcement needs the
   current shape on record.
1. **The renames** (mechanical, 236-style compiler-driven migration):
   `spawn {}` → `Thread.spawn {}`; `Task<T>` → `Thread<T>`;
   `TaskHandle<T>` → `Task<T>`; `VoidTaskHandle` → `VoidTask`; add
   `VoidThread`. The old spellings are ERRORS with fixits naming the new
   (no deprecation aliases — the corpus migrates in this unit, and outside
   consumers get the teaching error). Conformance/example sweep rides.
2. **The consumption rules** (rulings 5-6): the must-consume per-path check
   for the two singleton forms, both implicit-discard positions refused,
   the function-local escape refusal, the fixits naming all consumes
   (`join`/`detach`/`cancel`, and `Thread.spawn { }.join()` in the Thread
   diagnostic). Conformance rows FIRST (obligation 3): this converts two
   silent hazards (the zero-width block; the forgotten handle) into
   errors — the rows state the refusals and the group-form control.
3. **`Task.spawn` + the singleton** (ruling 3): the lazy group, the
   ambient-scheduler placement, cancel-then-join at exit (a conformance
   row: a detached task's values deinit on the cancel path at exit),
   `detach()` on `Task<T>`/`VoidTask`, borrow ban at the form. Document
   the sync-main caveat (background tasks first poll at the exit join,
   already cancelled — the cooperative model being itself).
4. **`Thread.spawn` semantics** (rulings 8-9): the sync-enforced body, the
   blocking-permitted context, `Thread<T>.detach()` with its boundary
   sentence, Send both directions unchanged (design 193).
5. **Docs** (design 125): LANGUAGE_SPEC's concurrency chapter restructures
   around the two-engine split (the engines-don't-mix warning becomes the
   namespace rule); README's concurrency example; the saw-lang skill's
   cheat sheet, the recommendation gradient stated: default
   `Task`/`TaskGroup` → `TaskGroup(threads: N)` for parallelism →
   `Thread.spawn` for a dedicated blocking thread.

## Gates

Compiler branch: per-commit full suite + freestanding_runner (+ corodiff
--quick on transform-adjacent commits; + sos_runner on any sos/-touching
commit). Terminal: full battery, all stages. Unit 1's rename sweep gates
`bootstrap` explicitly (blade/libs are consumers).

## Explicitly out

An MT background singleton (`threads: N`) — later opt-in with its Send
obligations. `detach()` on group handles (ruling 6). Any deprecation-alias
period. Changing `Channel.recv`/`receive` naming (already correctly split
per engine; unit 5 documents the pairing).

## Landing — unit 3 (Aug 25, branch `design-242-c`)

Three commits, each gated. What each one decided, since the mechanisms are not
recoverable from the diff.

### 3a — `Task.spawn`, the background singleton, the handle's fate

**The singleton's storage was the whole problem.** A `TaskGroup` is `NoMove`
precisely because it is a scope whose address its members hold, so there is no
way to BUILD one and then put it somewhere: `Box.make` moves, an assignment
through a pointer moves, and a `static` is refused three times over (a static
may not own a resource; `None` is not a const-init form; an optional field is
not zero-initable — and `Vector`'s fields belong to `std.vector`, so a const
literal could not be written even where the first three allowed it). What
resolves it is a fact rather than a workaround: an ALL-ZERO `TaskGroup` already
IS a valid empty single-threaded group — every `Vector` field is `{None, 0, 0}`,
`workers` is 0 (the ST engine, `< 2`), the lock and cond are absent and every
flag is clear. So `__saw_bg_group()` allocates the bytes, zeroes them, and the
group exists; the publish is `__saw_host_reactor`'s create-then-CAS, and the
group is process-lifetime like the reactor instance.

**The exit hook did not exist and had to be built.** There is no at-exit hook in
the language or the runtime — no `atexit`, no `global_ctors`, no teardown seam —
and a SYNC `main` is emitted verbatim, so there was no existing place to append
to either. `_wrap_main_for_background` renames whatever `main` the transform
ended up with (the user's own body, or the entry executor the pass just
synthesized) to `__saw_program_main` and puts a wrapper over it. A wrapper
rather than an appended statement, because the close must run on every edge out
of the program and a mid-`main` `return` is one of them; design 221's four
return shapes all forward through one binding, and codegen's C-entry treatment
keys on the NAME `main`, so it lands on the wrapper.

**The 9b fault keys on PROVENANCE.** `Task<T>`/`VoidTask` gained `background`
(set by `__bgspawn_<f>`) and `fate_ptr` (addressing a new `__fated` word in the
group-owned cell). Keying on the TYPE was not available: ruling 6 lets every
`group.spawn` handle drop, and a type-keyed check would fire on the accept-loop
idiom. The fate word lives in the CELL rather than the handle because a handle
may outlive its task by any amount and `deinit` runs long after the frame is
gone; it is WRITTEN only for a background handle, whose slot is PINNED at birth
so the cell survives — a group handle's cell is released the moment its slot
recycles, and writing there is a use-after-free. That is not theoretical: the
first cut wrote unconditionally and `taskgroup_slot_reuse_mt` died of SIGBUS.

**Rider, DF-256a**, exposed by the background form and fixed here: a GENERIC
struct's own fields were invisible to codegen's type-registration topological
sort, so a `Task<Int>` field contributed the name `Task` and stopped — while
registering the container asks `_ensure_monomorphized_struct` to build the
instantiation right there, needing `Task<T>`'s `UnsafePointer<TaskGroup>`
already registered. Every program until now happened to have a `TaskGroup` of
its own to order it.

### 3b — `Thread.detach()` and `__saw_rt_thread_detach`

The problem `detach()` has and `join()` does not: after a detach nobody joins,
so nobody frees the control block, and the two parties who could (the detacher
and the thread's own exit path) run concurrently. The handshake is a word both
can reach, which is why the seam takes the BLOCK where `__saw_rt_thread_join`
takes the handle.

The block gained a `state` word seeded with its own SIZE. The detacher
exchanges 0 in and frees if a negative comes back; the thread's exit exchanges
`-size` in and frees if 0 comes back. Exactly one side frees, no lock, no wait,
and the size travels in the word so the seam can call `__saw_rt_dealloc`
without knowing `T`. Recorded in rt/ABI.md as an ADDITIVE amendment on design
234's `__saw_rt_last_raw_code` precedent, with the one frozen word spelled out.
Both races probed directly, plus 400 detaches under `MallocScribble`.

### 3c — the spawn brace's capture list

`_check_spawn_brace_captures`, one funnel, one entry point today
(`Thread.spawn { ... }`). The migration re-ran the census rather than trusting
unit 0's: 54 real brace sites, 27 capturing implicitly (26 in `examples/`, 1 in
`sawc/std/taskgroup.saw`), 2 already listed, 25 capturing nothing.

### NOT LANDED, and why

**The cooperative brace sugar** — `Task.spawn { [x] in ... }` and
`group.spawn { [x] in ... }` — is the one part of ruling 10 still open. The
rule it would be checked by is in place and its funnel names the entry point
that will register; what is missing is the LIFT.

The obstacle is the lifted function's RETURN TYPE. A Saw function with no
declared return type is `Void` (probed: `func f() { 5 }` then `print(f())` is
``cannot print value of type `Void` ``), so the lift cannot defer the question
to the ordinary function checker, and the type is not known until the body is
checked. The two ways out both have a shape worth deciding rather than picking:
check a deepcopy of the body in a sandbox to learn the type and build the real
function from the original (design 70's pristine-template machinery exists for
exactly this and is not free), or give a synthesized declaration a
deferred-return-type mechanism. Doing it in the transform instead does not
work: the effect graph and `_spawn_roots` are the typechecker's, and the lifted
body's suspension is what the frame is built from.

Ruling 10's other v1 fence — refusing an enclosing TYPE parameter named by a
brace body — belongs with the lift and not before it: without a lift a type
parameter in a `Thread.spawn` body is fine, because the closure is compiled
inside its enclosing generic.
