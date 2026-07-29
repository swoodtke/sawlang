# Design Brief 52b — The multi-task runtime on TaskGroup (A1b remainder)

**Status (Jul 29): LANDED.** All seven items ship. `Resumable`/`__Poll` are
builtin; every frame gets synthesized `Resumable` conformance (`resume` +
`__wake_reason`, both `sync`). `group.spawn(f(args))` lowers via a synthesized
`__spawn_<f>` that erases the frame into `Box<any Resumable>`, enqueues it, and
returns `TaskHandle<T>`; `join()` takes the frame's `__result` exactly-once
(force-unwrap + `__forget`), unjoined results drop once at group teardown. The
executor lives in the group (round-robin; yield / earliest-deadline sleep /
channel-yield) and is `sync`, so the group's `Deinit` drives every child to
completion — structured join out of LIFO destruction. Cancellation is a frame
`__cancel` word (`handle.cancel()` / `cancelled()`), observed cooperatively, NO
forced destroy. Suspending channel receive = `Channel.try_receive()` + the Part-0
`yield_now`-on-empty loop. Nine tests, deinit-oracle + -O0 verified; full suite
green, zero xfails. The 21b thread engine is untouched.

**Verdict on the group-Deinit/LIFO hazard (item 4):** SOUND. The group is
declared before its handles and before shared resources, so LIFO destroys it
FIRST — it drains children while those resources are still alive; handles die
before the frames they point into; and task frames are self-contained (spawn
strips references, paper 18), so a task never touches an outer-scope local. No
scope-ordering bite.

**Deviations (v1, clean diagnostics / documented, not miscompiled):** a spawned
function must be non-`Void`; a `TaskGroup` as a direct frame-resident local of a
suspending function is unsupported (opt-encoded-local-address gap — do group work
in a non-suspending helper); a suspension inside `if let` is not split (Part 0
gap — hoist the yield into a plain `if`); the suspending channel receive is the
loop idiom rather than a first-class `ch.receive()` method (nested suspending
method-call embedding is future work). `TaskGroup.Deinit` pops+drops each frame
explicitly (the auto field-cleanup of a `Vector<Box<any Resumable>>` FIELD did
not tear its erased boxes down — worked around, exactly-once preserved).

---


**Source:** brief 52's Part 1, stopped honestly at budget with the
foundation VALIDATED (erased `Vector<Box<any Resumable>>` with a
`&var self -> __Poll` trait method: boxing, dispatch, and the full
pop/resume/re-push drive loop all work — see brief-52's report; the
if-let move-out double-free fix `7728063` was the prerequisite).
**Ownership model (adopting brief-52's recommendation — this IS the
decided C1 nursery model, not a new decision):** a **`TaskGroup`
local**; `group.spawn(f(args))`; the group's **`Deinit` runs the
executor to completion of all children** — structured join at scope
exit falls directly out of LIFO destruction. No global queue, no
static Vector needed, no forced destroy anywhere (the only frame drop
is group teardown after Done).

## Items
1. **`Resumable` conformance synthesis:** driven/spawnable frames get
   compiler-synthesized conformance to a builtin `Resumable` trait
   (`&var self` resume returning `__Poll`; plus the `__wake` read
   surface — report the exact shape). Object-safe by construction
   (verify against design 51's rules).
2. **`group.spawn(f(args))` lowering:** transform marks `f` a
   spawnable root (frame + conformance, like `__drive`); codegen
   builds the frame, boxes via `Box<any Resumable>.make`, pushes onto
   the group's queue; returns `TaskHandle<T>` carrying the typed
   result access (brief-52 sketch: capture of the frame's `__result` —
   pin the mechanism so the handle stays valid while the box lives in
   the queue/group; report it precisely). Handle `.join()` drives the
   group until that task is Done, returning the result; dropping an
   unjoined handle is fine (result dropped at group teardown —
   exactly-once).
3. **Cancellation:** frame-resident `__cancel` word;
   `handle.cancel()` sets it; `Task.cancelled() -> Bool` (or
   equivalent surface — report) reads the CURRENT task's flag inside
   task code; cancellation-aware waits return through normal control
   flow. NO forced destroy.
4. **Executor in the group:** round-robin over ready tasks; honor
   __wake (yield = requeue; sleep = time-ordered; channel-wait = wake
   on send). Suspending `main` composes (a group inside main's frame).
   Nothing precluding the freestanding static-task variant.
5. **Suspending `Channel.receive`** + cancellation-aware
   `receive_or_cancelled() -> T?`; wake-on-send integration with the
   group executor. 21b thread engine untouched, coexistence
   documented.
6. **Tests:** deterministic two-task yield interleaving; sleep
   ordering; producer/consumer over suspending channel (uses Part 0's
   loop suspension); cancel observed at a check AND at a
   cancellation-aware receive with deinit-oracle cleanup; structured
   join at scope exit (group Deinit drains); handle.join() typed
   results; unjoined-handle result drop exactly-once; suspending main
   with a group. -O0 spot checks on lifetime tests.
7. **Docs:** LANGUAGE_SPEC concurrency section rewritten to the
   shipped model; CLAUDE.md.

## Hazards
Frame lifetimes cross scopes through the group — design 51's erased
teardown is the net; every cancel/join/unjoined path gets a
deinit-oracle test. The TaskGroup Deinit running arbitrary user code
(the executor) during destruction is novel — verify interaction with
LIFO cleanup ordering (the group must be the last thing alive in its
scope... probe and pin the rule; if scope ordering bites, report
precisely). Protocol extensions in their own commits. Full suite per
commit; zero xfails end state.

## Report back
Per item: mechanism + verification. The TaskHandle result-access
mechanism and the group-Deinit/LIFO interaction verdict explicitly.
Suite tally; deviations; non-allowlisted commands.
