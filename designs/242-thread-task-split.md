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
