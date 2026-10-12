# sawc2 coroutines: the implementation plan (SL-545)

**Status: DRAFT, being written.** Nothing here is approved until the user says so. The Air reviews each section as it lands.

The authorities, in order:
1. LANGUAGE_SPEC §6 (Concurrency) for meaning, and GRAMMAR.md for spelling;
2. SL:architecture §3.9 for the agreed design;
3. `sawc/rt/ABI.md` for the runtime seams;
4. Stage 0 (`sawc/coro_transform.py`, `sawc/coro_shapes.py`, design 275's ledger) as the behavioural oracle, not the template.

Probes cited as `.build/scratch/coroplan/...` live in the planning worktree (`.claude/worktrees/agent-af352e18ad8c5756f`); `stage0/` and `sawc2/` there are the two sweeps' probe directories.

## 1. Scope and non-goals

**"sawc2 coroutines done" means:** every program in `tests/corpus/` that Stage 0 compiles into a coroutine builds with sawc2 and behaves as its `EXPECT` directives say. That target has two levels (settled in t1):
- **Plan-complete, which closes SL-545:** the 490 minus a *gated* list, the programs that also need a std port this plan leaves out (`std.net` past A12b's slice, `Arc`, `Map`, `json`, `mutex`, `directory`, …). The census lane (A0b) generates that list from each program's missing names, so it cannot drift. The plan's last check is the census green over the plan-complete set.
- **Fully done:** each gated program flips when its port lands, tracked by that port's issue, not by SL-545. "A coroutine" here means one or more framed functions in Stage 0's frame ledger (`--emit-frame-ledger`); §3.2's census counts 490 such programs and 93 coroutine refusal tests. **Every language refusal Stage 0 makes is matched:** the same programs are refused, under a sawc2 rule ID, with a message that names the same limit. Stage 0's *implementation limits* (the spec's "Not yet supported" list) are lifted, since MIR lowering has nothing to refuse there (§3.3). The mechanism is SL:architecture §3.9's, not Stage 0's:
- a post-mono *definitely suspends* fixpoint;
- by-value frames, packed by storage lifetime;
- teardown keyed by state;
- the closed `park(reason)` protocol;
- a post-lowering MIR verifier.

Two requirements from the user (SL-545 c2) are in scope beyond Stage 0:
1. **A stack-like frame layout.** A frame's size approaches its deepest live chain: sequential child frames overlay, exclusive arms overlay, and values live in disjoint ranges share bytes. This is core work (§4, phase B), not a later optimisation.
2. **Heap-allocated frames, for recursion,** as a later phase (§4, phase C). The resume ABI is uniform from the first unit, `resume(frame: ptr, cx: ptr) -> Poll`, so heap frames extend the design rather than rework it.

**Also in scope,** since a coroutine cannot run without them:
- the new std's task surface: `std.task`, `Task`, `VoidTask`, `TaskGroup`, `Task.spawn`, `cancelled()`, `yield_now`, `dump_tasks`;
- `sleep` and `Duration`;
- `std.channel`'s cooperative half;
- the reactor glue: the executor's register/poll funnel over the existing `__saw_rt_reactor_*` seams;
- the offload lowering;
- the backtrace table.

**Behaviour that differs from Stage 0 on purpose.** Each such case is annotated in the corpus as `oracle known wrong: SL-nnn` (SL:architecture §5). Examples:
- SL-353's lost wake: the park records its word before it arms, as §3.9 rules, and SL-355's R5 atomic latch comes with the runtime;
- SL-430's leaked error from a propagating `try`;
- SL-431's ICE on a `Result<Void, E>` coroutine that falls off its end;
- every frame and `__release` double free, which §3.9's state-keyed teardown rules out by construction.

**Non-goals for the embedded phases (A and B).** Each one stays a clean refusal that names its pending design, as it does in Stage 0:
- **heap frames:** suspending recursion stays refused, naming the cycle, until phase C;
- **suspending closures:** a suspension inside a closure body stays refused (spec: suspension; Stage 0's `ClosureExpr` REFUSE row). Phase C's follow-on units plan the lift;
- **suspending `any Trait` dispatch:** stays refused at the dispatch (K37), with the same pending note.

**Out of scope entirely:**
- `Thread.spawn` and the OS-thread engine. They are sync items and need no frame (SL:architecture §3.8). They have their own std work;
- porting `std.net`, `std.process` and `std.signal`'s full surfaces. This plan delivers the park reasons they need, plus one pinned consumer per reason. The rest of each port is std work that depends on these units;
- design 152's frame-size warning. It can hang off `--emit-frame-layout` later;
- a VM backend. The lowered MIR is target-independent, so a VM inherits the state machines, but no VM unit is planned here.

## 2. What sawc2 has today

**In short:** sawc2 *knows* what suspends, and nothing after the borrow check *does* anything about it. Typecheck solves may-suspend and sync-callable to a fixpoint. MIR marks suspension points and places classified budget points, and the borrow check refuses a `borrows(sync)` loan across either. From mono on, the flags pass through unevaluated, and the backend emits a suspending call as a plain call (SL-546). Under `--std-root std` the new std has no task, time, channel, net or frame module, so the only suspension source a program can reach today is a `blocking` extern.

The probes behind this section are under `.build/scratch/coroplan/sawc2/` in the coroplan worktree: the programs `pNN_*.saw`, and each stage's output in `out/<stage>_<probe>_{new,s0}.txt`, under the new std and under Stage 0's std.

### 2.1 Resolve and parse
- **Has:**
  - Both spawn forms parse, with no dedicated syntax: `Thread.spawn { [n] in … }` is a member call with a trailing closure and a capture list, and `group.spawn(f(…))` is a plain call (`out/parse_p12.txt`, `out/parse_p16.txt`).
  - Resolve's Stage 0 prelude table names `sleep`, `cancelled`, `Duration`, `TaskGroup`, `Task` and `VoidTask` (`resolve/src/prelude.saw`).
- **Missing:**
  - `walk.saw:is_spawn_form` refuses `Thread.spawn`/`Task.spawn` as `slice.not-yet` ("the `Thread.spawn` and `Task.spawn` forms are not in the bootstrap slice yet").
  - `lookup.saw` refuses every `__saw_*` intrinsic as `slice.not-yet`. That includes the test entries `__saw_drive`, `__saw_drive_steps` and `__saw_suspend`, which 143 of §3.2's coroutine programs use.
  - The lang-item table (`resolve/src/lang.saw`) has no task, frame, executor, handle or `Duration` vocabulary.

### 2.2 Typecheck
- **Has:**
  - **The effects fixpoint.** `summaries.saw:solve_summaries` runs one unit per body and per closure, as a least fixpoint over reverse dependency edges.
  - **Each summary** holds `suspends`, `nonsync`, and the condition atoms (suspend-when, sync-callable-unless, copy, refuses-when).
  - **`eval_call`** handles each call kind:
    - a function value never suspends, and is nonsync unless its type is `sync`;
    - a call through a bound keeps the condition, such as `(suspends when T.Worker.step)`;
    - an `any` dispatch is nonsync only;
    - a concrete call substitutes its type arguments.
  - **The phase-3 checks** (`effects.saw`), each refusing its own rule:
    - `effect.sync`, including the `deinit` variant;
    - `effect.closure-suspends`;
    - `effect.any-suspends`, which is K37;
    - `export.suspends`;
    - D19's per-instantiation sync check.

    Probe `p20_effects.saw` triggers each one (`out/tc_p20_new.txt`).
  - The dump (`typecheck --dump`, `--summaries`) prints the summary of every function (`out/tc_p21_dump.txt`).
- **Where suspension comes from.** Typecheck has no park concept: a summary starts suspending only in `summarize_declared`, at one of three things:
  - a `blocking` extern;
  - an interface-only std module's row in `stdsuspension.saw` (generated from Stage 0's std check by `tools/std_suspension.py`);
  - an untabled std function, taken as suspending.

  Under `--std-root std` every body is checked and none suspends, except through a `blocking` extern.
- **Missing:**
  - **No suspending-recursion refusal anywhere.** `ping`/`pong` build and run (`out/build_p21_new.txt`). The refusal belongs after mono (unit A1), where the edges are exact.
  - **No park primitive.** `sleep` is `slice.not-yet` in `bodies.saw`.
  - **`group.spawn` is `slice.not-yet`,** and `known.task_group` only looks in `std.taskgroup`.
  - **None of the spawn-site checks exist:**
    - `Thread.spawn`'s Send audit and its sync body;
    - `Task.spawn`'s refusal of borrows;
    - the Send-on-frames gate for a `threads: N` group;
    - spawn-borrow extents.

    Resolve refuses the forms before any of them would run.
  - The spawn brace's capture rule is implemented (`captures.saw:spawn_brace`), but nothing reaches it.

### 2.3 MIR
- **Has:**
  - **A suspension point is a flag on a call terminator:** `MirCall.suspend` is `Never`, `Always` or `When` (with condition texts), set by `build.saw:suspension`. The dump prints `-> [return: bbK] suspends;`, and the verifier requires it to agree with typecheck (`tests/mir/README.md`).
  - **The op budget is a statement, `Budget { yields }`,** on every loop backedge and every `continue` (`lower.saw`). It is classed by `build.saw:budget_class`: charge-only inside an open `borrows(sync)` window, yield-capable otherwise (`out/mir_p22_new.txt`, `out/bc_p03b_new.txt`). §3.5's placement is complete: points appear in `sync` functions and closure bodies too, as §3.9 expects, since lowering decides which stay live.
  - **Windows.** `window_open` and `window_close` carry `suspends` when the accessor half may suspend (`lower.saw:open_half`, `build.saw:close_window`; golden `tests/mir/golden/accessors.mir`).
  - **The accessor split** (`split.saw:split_accessor`) is the nearest thing to a frame:
    - the body is lowered whole, with `lend` as a `MirCallKind.Lend` call, then cut into a prologue (blocks before a lend) and an epilogue (blocks a lend resumes into);
    - the state record is a tuple of the locals live at a resume block (`split.saw:liveness`, a whole-body backward liveness), plus a `Bool` drop flag per owning local not definitely whole at a lend (`record_flag_slots`), plus an `Int` resume index when there are several lends;
    - the caller owns the record and passes it `&var` to both halves.

    So the ingredients exist: liveness across a pause, a record of the live set, drop flags carried in the record, and a resume index. The initialisation analysis (`initialisation.saw`, `MirInit`) that drop elaboration uses is also reusable.
- **Missing:**
  - Liveness or initialisation *at a suspending call*.
  - Any per-suspension state number, resume entry or cancel entry.
  - Embedded child storage.

  `split_accessor` handles one pause kind (`lend`) at function granularity, and refuses code after a lend that is reachable without lending, and a partly moved local at a lend.

### 2.4 Borrow check and drop elaboration
- **Has:**
  - **The suspension rule is enforced.** `loans.saw:suspends_at` counts a call with `suspend != Never` and a yield-capable `Budget`, and `conflicts.saw:check_suspension` refuses `loan.sync-suspend`, with a fixture of its own (`tests/borrowck/refuse/loan.sync-suspend.saw`). Typecheck refuses the block form earlier as `borrows.sync-window` (`out/tc_p03_new.txt`).
  - **Ordinary loans span a suspension:** p03b keeps loans L3 to L5 live across `call nap() … suspends`, and it is accepted.
  - **Drop flags are ordinary `Bool` locals,** and per `tests/drops/README.md` "a flag lives across a suspension like any other local; the coroutine frame builder carries it".
- **Missing:**
  - **Must-consume is wired but empty:** `elaborate.saw:drops_must_consume_roles()` returns no roles. Its fixture `refuse/drop.must-consume.saw` is `due:` until spawn enters the slice.
  - **Loan live ranges are not published.** The borrow check computes them, but no later stage can read them. The frame packer needs them (§3.9: a value's storage lifetime covers any loan into it). Unit B1 decides how they cross.

### 2.5 Monomorphization
- **Has:**
  - The worklist from `main`, the `@export`s and the lang functions.
  - The `suspend` flags, copied into each item verbatim (`out/mono_p02_new.txt`).
  - The layout table (`--layouts`), backed by `compiler/target`.
- **Missing:**
  - **No task-root items.** The mono README says so: "spawn is not lowered, so no task root exists and every op-budget point is inert".
  - **No post-mono *definitely suspends* fixpoint.** `run<Fast>` still prints `suspends when T.Worker.step` (SL-526, `out/mono_p21_new.txt`).
  - No cycle refusal, no frame layout, and no `--emit-frame-layout`.

### 2.6 The LLVM backend and the run lane
- **Has:**
  - The runtime objects a coroutine needs are already built and linked into every hosted program: `sawc2 runtime` builds `reactor.o`, `offload.o` and `op_budget.o` from `sawc/rt/` (`.build/sawc2-runtime.txt`). Nothing calls them yet.
  - The backtrace table's slot exists: the README notes a runtime source gets "no backtrace table", so a program does get one, empty today.
- **Missing:**
  - **Every coroutine construct.** `bodies.saw` emits nothing for `Budget` (`case Budget -> {}`), and nothing in `compiler/llvm/src/` reads `suspend`.
  - **A refusal.** A suspending call is emitted as an ordinary call (`bin_p02.ll`: `call i32 @usleep(i32 10)`), and the program runs, synchronously. SL-546 is filed for this. Its fix is unit A0.
  - The run lane's `backend.not-yet` list has no suspension case.

### 2.7 The new std (`std/`)
- **Has:**
  - `alloc`, `box`, `data`, `env`, `file`, `mem`, `panic`, `path`, `prelude`, `process`, `scalar`, `string`, `stringbuilder`, `systemerror`, `utf8` and `vector`, about 2,500 lines in all.
  - In the prelude, `Atomic<T>`, `UnsafeMutableInterior<T>`, `Send`/`Sync` and `NoMove`, which is what an executor written in Saw needs (D38).
  - `std.process`'s `Command.wait` is the ruled S28/SL-522 workaround. It polls `__saw_rt_proc_try_wait` with `__saw_rt_sleep_ns` naps, and nothing in it suspends.
- **Missing, against `sawc/std/`:**
  - **The task surface:** `task.saw` (Thread, VoidThread, `yield_now`, `dump_tasks`) and `taskgroup.saw`, 3,062 lines in Stage 0. That covers `TaskGroup`, `Task`, `VoidTask`, the `__saw_exec_*` executor, the task cells, `__saw_host_reactor()`, the deadlock walk and the backtrace dump.
  - **The frame vocabulary:** `compiler/frame.saw` (`Slot`, `Poll`, `Resumable`, `UnsafeRef`).
  - **The modules a park reason needs:** `time` and `duration` (`sleep`, `Instant`), `channel`, `net` (its `io_wait` layer), `signal`, and `process`'s cooperative half.
  - **What the corpus's coroutine programs also lean on:** `arc`, `mutex`, `map`, `set`, `json`, `directory`. These are std porting work outside this plan (§1), but they gate some of §3's programs (§3.2).
- **Runtime seams already in the ABI table** (`typecheck/src/runtimeabi.saw`) that the task surface uses:
  - `__saw_rt_reactor_{create,register,unregister,poll,wake,destroy}`;
  - `__saw_rt_offload_{start,done,pipe_fd,take}`;
  - `__saw_rt_op_budget_{tick,reset}`;
  - `__saw_rt_sleep_ns` and `__saw_rt_clock_monotonic_nanos`;
  - `__saw_rt_thread_{spawn,join,detach}` and `__saw_rt_lock_{acquire,release}`.

  SL-355's R5 (an atomic wake word with a CAS latch, and a `register` that returns a status) is not in `sawc/rt/` yet. Its reviewed runtime half is preserved on SL-355 (c20). Unit A12a decides where it lands.

### 2.8 Open sawc2 issues in this area
- **SL-546** (filed by this plan): suspending calls compile as plain calls; cycles are accepted.
- **SL-526:** mono prints unevaluated suspension conditions.
- **SL-510:** no object-safety check. It touches `any`, not suspension.

## 3. The target

### 3.1 How §3.9 reads as a lowering

This is the shape every unit in §4 builds toward. Where it fixes a detail §3.9 leaves open, it says so, and those details are for the Air to check.

- **A new stage, `compiler/coro` (package `sawcoro`), between mono and the backend.** Its input is mono's concrete items. Its output is lowered MIR, which the backend consumes, and nothing earlier.
  - `sawc2 coro (--dump | --layouts | --check)` gives it a test surface, and a `tests/coro/` lane holds its goldens, refusals and verifier injections, the way `tests/mir/` and `tests/mono/` do.
  - The stage owns three things: the *definitely suspends* fixpoint, frame layout, and the state machine.
- **The ABI is uniform from the first unit:** `resume(frame: ptr, cx: ptr) -> Poll`, where `Poll` is `Ready` or `Pending`.
  - `cx` is the task's context record. It holds:
    - the root token (the address of the task's park word);
    - the cancel word's address;
    - the task's identity, for the backtrace walk.
  - An embedded child is resumed by a direct call with the same signature. A heap child, a suspending `any Trait` dispatch and a suspending closure (phase C) are resumed through a *frame descriptor*: a static record of `{resume, size, align, result glue, backtrace index}`. The executor already calls every task root through one of these from unit A7.

  So phase C adds a second way to reach a child, not a new protocol.
- **A frame is bytes with a layout, not a struct with glue.**
  - Its fields are:
    - the state word;
    - every value whose storage lifetime contains a suspension point (frame-resident values);
    - an embedded slot per driven child;
    - a state record per window open across one;
    - the result slot.
  - A resident MIR local is rewritten to a frame-slot place, `(*frame).[offset: T]`, which the backend lowers as one `getelementptr`. A local live only between two suspension points stays an `alloca` in the resume function.
  - **The frame has no drop glue.** Every drop is the one drop elaboration already placed, at its MIR position. Lowering moves the storage; it adds no ownership operation (§3.9).

  This is what makes teardown keyed by state by construction. Stage 0's double frees all came from a *second* teardown path: a frame struct's memberwise deinit, plus `__release`, plus the rebuild store (SL-183 unit 3, sites a–c). Here there is none.
- **Destruction follows the language's rule: "a frame dies only by its own code reaching an exit"** (spec: Frame lifetime / no forced destroy). Cancellation is cooperative:
  - a cancelled park resumes and reports it (a receive returns `Err(Cancelled)`, an io read an `IoError`);
  - `cancelled()` reads the cancel word through `cx`;
  - control leaves through ordinary MIR edges, whose drops and `window_close`s are already there.

  So §3.9's "cancel path at each state" is these ordinary edges, and the verifier checks that what they drop at each state is exactly that state's live set. The one frame-level teardown left is a result nobody took, which the task's cell owns (design 134). **Settled with the Air (t3):** this reading leaves no forced-destroy entry (see the next bullets). If one is ever wanted, it is generated from the same per-state live sets, as a second consumer of the same data.
- **Driving a child**, at a suspending call `x = g(args)`:
  1. the arguments are written into the child's parameter slots and its state is set to 0;
  2. a drive block calls `resume_g(&frame.slot_g, cx)`;
  3. on `Pending`, the frame records its own state and returns `Pending`;
  4. on `Ready`, it moves the result out of the child's result slot and continues.

  Re-entry at that state jumps back to the drive block. There is no wake-word copying: the child's park writes the *root's* word through `cx`. So §3.9's "propagation op" is the `Pending` return, and its merge is the identity. That is the shape SL-355's ruled identity-guarded merge already proved sound.
- **`park(reason)` is one MIR terminator,** lowered per reason. Each lowering records the park word through the root token, then arms (SL-355's R1), then returns `Pending`. On resume it reads its outcome: ready, timed out, or cancelled.
  - The std's park points (`yield_now`, `sleep`, `io_wait`, a channel wait, an offload wait, a signal watch) are std-internal lang functions that lower to it.
  - So `Channel.receive` and the `TcpStream` reads are *ordinary* suspending std methods with a `park` inside. They embed like any callee, with none of Stage 0's inline special case (`_emit_recv_call`).
- **The op budget.** A live budget point (in a task root, in a framed callee, in a suspending `main`) lowers to a decrement, plus a `park(ready)` when the counter runs out.
  - The counter is a frame-resident value of the frame that owns the loop, set to 128 at frame init. That is Stage 0's per-frame counter (`__saw_loop_budget`), kept because exact-interleaving tests pin it (`taskgroup_compute_preemption`).
  - A charge-only point decrements and never parks.
  - Every point in an unframed item is deleted.
- **Joining drives the scheduler; it is not a suspension.** That matches Stage 0, where `Task.join` drives the ambient scheduler on the calling thread and a joining `main` is not framed (`std/taskgroup.saw` `join`; probe `stage0/p3_dump.saw`).
  - **The invariant that makes this sound** (t2): a join inside a task runs the scheduler *re-entrantly*. A task joins a task, and a nested group's `Deinit` drives its members. **A nested drive never resumes a frame that is active on the C stack.** On a `threads: N` group, `active` is claimed and cleared under the queue lock.
  - Stage 0 enforces it by skipping every `active` frame in the sweep (`sawc/std/taskgroup.saw`, "Reentrancy-safe"). Without the skip, a nested sweep resumes a frame whose own `resume` is further up the stack and corrupts its state.
  - This is a runtime property of the executor, invisible to the MIR verifier. So it is pinned, at A8a, by `taskgroup_nested_groups` (expects `124`), and A7b ports the skip.
- **Every frame leaves through its own code** (t3). The cases that could have wanted a forced destroy were each checked:
  - `__saw_drive_steps` drives to completion, counting `Pending`s (`coro_discarded_tail_move_cross_module`);
  - program exit is cancel, then join;
  - a panic aborts.

  A7b makes it a checked invariant: the executor releases a task box only after its root has returned `Ready`, so a future early-stopping driver fails loudly instead of leaking a frame's live values.

### 3.2 The census: which corpus programs need coroutines

**Probe:** `probe_census.py` and `probe_census_sub.py` in `.build/scratch/coroplan/`. They ran over all 2,584 files of `tests/corpus/` (top level, `conformance/`, `errors/`) on the coroplan worktree at 39759790f. For each file:
- Stage 0's `--emit-frame-ledger` ran over its `examples/` twin;
- `sawc2-stage2 build --std-root std --emit-ll` ran over the corpus file.

**A program needs coroutines when Stage 0 frames at least one function for it.** The full list is chat file **f24** (`coro_programs.txt`), with each program's first sawc2 refusal.

| | top level | `conformance/` | `errors/` | total |
|---|---|---|---|---|
| runnable programs (`EXPECT: success` or `panic`) | 1,412 | 207 | 10 | 1,629 |
| ... that need coroutines | 392 | 97 | 1 | **490** (30%) |
| coroutine refusal tests (`EXPECT: error` naming a coroutine rule) | 19 | 24 | 50 | **93** |

**The 490 by the first refusal sawc2 gives today:**

| first refusal | programs | what it is |
|---|---|---|
| `import.unknown-module` | 368 | `std.task` (233 at top level), `std.net`, `std.channel`, `std.time` |
| `slice.not-yet` | 72 | resolve's refusal of a `__saw_*` intrinsic: `__saw_drive`, `__saw_drive_steps`, `__saw_suspend` |
| `name.undefined` | 38 | `yield_now`, `TaskGroup`, `sleep`, `Duration`, `Channel` |
| `member.unknown` | 6 | std members the new std lacks |
| a sawc2 crash | 6 | `panic at vector.saw:68: index out of range: -1` in typecheck. It is not coroutine-specific: the same crash hits 25 programs with a `Map` or `Set` literal under the new std. Reported to the lead, not filed by this plan |

**What stands between the 392 top-level programs and a build:**
- **234 lack only coroutine vocabulary:** `std.task`, `yield_now`, `TaskGroup`, `sleep`, `Duration`, `Channel` and the test intrinsics. These are this plan's direct targets.
- **73 also need std ports outside this plan:** `std.net` (45 name it), `Arc` (23), `Map`, `json`, `mutex`, `directory`.
- **67 are refused for something else first:** mostly the intrinsics again, then whatever follows.
- **13 lack only non-coroutine names.**
- **5 crash.**

**Test entries.** 143 of the 392 use `__saw_drive`, `__saw_drive_steps` or `__saw_suspend`, and 125 are driven *only* that way, with no group and no spawn. **Decided (reversible):** sawc2 supports the three as test-only lang intrinsics, with Stage 0's meaning, so that those pins keep testing the shapes they were written for. The alternative is migrating 125 files to `Task.spawn(...).join()`, which would change what they measure (`__saw_drive_steps` counts `Pending`s).

**Feature use among the 392:** `yield_now` 229, `TaskGroup` 206, `__saw_drive` 137, `__saw_suspend` 65, `sleep` 39, `TcpStream` 36, `borrow` 27, `TaskGroup(threads:)` 25, `__saw_drive_steps` 20, `receive` 18, `io_wait` 17, `cancelled()` 16, `Command` 15, `TcpListener` 13, `blocking` externs 11, `Task.spawn` 3, `dump_tasks` 3.

Stage 0's ledger frames 1 function in 99 of the programs, 2–3 in 162, 4–9 in 112, and 10 or more in 19. Its suspension sites total:

| context | embed | inline |
|---|---|---|
| driven root | 405 | 376 |
| embedded | 197 | 459 |
| spawned | 212 | 264 |

**The 93 refusal tests by rule:**

| rule | tests |
|---|---|
| a suspension in a `sync` context | 27 (4 already refused by sawc2 as `effect.sync`) |
| suspending recursion | 8 |
| a closure body | 6, plus 4 citing a driven function by name |
| spawn borrow extents | 6 |
| `NoMove` group | 4 |
| a `Never` task body | 3 |
| must-consume handles | 3 |
| a `borrows(sync)` window held across a suspension | 3 |
| the `threads: N` Send gate | 7 |
| a `Thread.spawn` body | 2 |
| a drive site in a suspending body | 2 |
| K37 | 1 |
| one each | the suspending default, `blocking` agreement (2), the freestanding refusals (2), the tuple-pattern `while let`, the spawn brace's capture rule, the retired `spawn { }`, `dump_tasks` gating (2), `@align` on a frame local |

The list is chat file **f25** (`coro_refusal_tests.txt`).

### 3.3 The shape matrix

**One fact collapses most of Stage 0's table.** Stage 0 rewrote source, so each syntactic slot needed its own disposition (SPLIT / HOIST / INLINE / EMBED / REFUSE). sawc2's MIR already fixes evaluation order, puts every suspending call in its own call terminator at any expression depth, and makes every control-flow construct plain blocks (SL:architecture §3.5). So in MIR:
- **every SPLIT row** is "the CFG is the state machine";
- **every HOIST row** is "already a temporary";
- **INLINE and EMBED** become `park` and child driving.

The matrix stays, as the **test plan**: each row is a lowering claim plus the Stage 0 program that pins it. Every pin named here passed under Stage 0 in the oracle sweep (`stage0/reps.log`, 44 programs, all matching EXPECT). Each one becomes a run-lane program in the unit named, and also passes in the corpus census lane (unit A0b).

**Containers** (a suspension inside a construct's block):

| row (Stage 0) | sawc2 lowering | pin | unit |
|---|---|---|---|
| `if` / `else` (SPLIT) | blocks; the arms are exclusive, so their resident values overlay (B2) | `coro_suspend_in_if_branch` | A6 |
| `if let` (SPLIT, guarded) | blocks; the binding is a local like any other | `coro_iflet_over_suspending` | A6 |
| `guard let` (SPLIT) | blocks | `coro_guardlet_over_suspending` | A6 |
| `while` (SPLIT) | blocks plus a backedge; the budget point is live in a framed item | `coro_suspend_in_while` | A6, A9 |
| range `for` (SPLIT) | a window on the head plus a loop over `next` (§3.5); the iterator is resident | `coro_suspend_in_for` | A6 |
| collection `for` (SPLIT via a `while let` rewrite) | the same window plus loop; a borrowing iterator's window record is resident | `conformance/K149_sawtracker_loop_shape` | A6 |
| `match` arm (SPLIT) | a decision tree; the arms overlay | `coro_suspend_in_match_arm` | A6 |
| `#lend_var` / `borrow` block (`ScopedBlock`) | a window whose record is resident across the suspension; `window_close` on every exit edge | `lend_var_coro_and_forwarding` | A6 |
| `try { } catch { }` (SPLIT) | the catch is a block reached from every error edge; the caught error is a resident local | `coro_try_catch_suspending` | A6 |
| inline `try EXPR catch { }` (SPLIT via rewrite) | the same blocks; no rewrite needed | `coro_suspending_call_in_inline_catch` | A6 |
| closure body (REFUSE, SL-316) | **stays refused** in phases A and B (`effect.closure-suspends`, already in typecheck); lifted in phase C6 | `errors/coro_suspending_closure_body_in_a_visitor` | A1; C6 |

**Heads** (Stage 0's HOIST rows, now plain temporaries):

| row | pin | unit |
|---|---|---|
| `if` condition | `conformance/K41_suspending_if_condition_head` | A6 |
| `while` condition, re-evaluated per iteration | `conformance/K42_suspending_while_condition_head` | A6 |
| `if let` and `guard let` subject | `expr_suspend_iflet_scrutinee` | A6 |
| `for` range endpoint | `conformance/K43_suspending_for_range_head` | A6 |
| `match` scrutinee | `conformance/K40_suspending_match_scrutinee_head` | A6 |
| receive and `try` in heads | `conformance/K47_channel_receive_binding_and_try_heads` | A13a |

**Statements and expressions:**

| row (Stage 0) | sawc2 lowering | pin | unit |
|---|---|---|---|
| `let x = g()`, bare `g()`, `return g()` (EMBED) | child driving (§3.1) | `coro_nested_suspend_two_deep`, `expr_suspend_return` | A4 |
| suspend primitive (INLINE) | `park(ready)` or `park(timer)` | `async_main_sleep_yield` | A3b, A11 |
| `Channel.receive` (INLINE) | an ordinary suspending std method, embedded | `channel_recv_nested` | A13a |
| blocking extern (INLINE offload) | `park(offload)`: start the job, park on its pipe, take it | `expr_suspend_blocking` | A14 |
| any operand, argument, receiver, interpolation or short-circuit right side (HOIST, the ANF pass) | MIR temporaries in evaluation order; a short-circuit right side is its own branch (§3.5) | `expr_suspend_{arg,binop,andor,interp,coalesce,chain_head}` | A6 |

**Stage 0's implementation limits, lifted.** The spec's "Not yet supported" list exists because a source rewrite could not express these shapes. In MIR each is ordinary blocks, so sawc2 builds them rather than copy the refusal, and each pin flips from `error` to a run program:
- a value-producing `break` out of a spanning loop;
- a tuple-pattern `if let` or `while let` over a suspension (`while_let_tuple_over_suspension_refused`);
- a multi-hop `?.` assignment with a suspending right side;
- a suspending `try { } catch { }` raising two error types (`coro_try_block_two_error_types`, which is already `refuses:`-pinned).

**Settled with the Air (t5):** this is a "language changed" annotation under SL:architecture §5, and the spec's list shrinks in the same unit (A6). The decision is reversible: if lifting is wrong, sawc2 refuses the same four. **These four pins have no behavioural oracle,** since Stage 0 refuses them. Each expected output is derived from the spec by hand, marked `spec-derived expectation (no oracle)` in its file, and reviewed as part of A6's review, the way an "oracle known wrong" entry is adjudicated.

**Spawn, drive and park forms:**

| row | sawc2 lowering | pin | unit |
|---|---|---|---|
| suspending `main` | an entry executor drives `main`'s frame through the std executor | `async_main_sleep_yield` | A3b |
| `__saw_drive(f(…))`, `__saw_drive_steps`, `__saw_suspend` | test intrinsics: a sync driver loop over a stack-allocated frame that never parks; `__saw_suspend` is `park(ready)` with no wake | `coro_drive_void_body` | A4 |
| `Task.spawn(f(…))` | a task-root item; a heap task box sized by the root's layout; enqueue through the frame descriptor; a must-consume handle | `background_task_spawn` | A7 |
| `group.spawn(f(…))` | the same root into the group's slots; a group handle, not must-consume; spawn borrows are extents carried by the handle | `taskgroup_two_task_yield`, `taskgroup_eager_teardown` | A8a, A8b |
| a function spawned *and* embedded | two items, a task root and the ordinary framed item; no trampoline (Stage 0's `f$spawnroot`) is needed, since the task root *is* the separate specialization | `coro_spawn_and_embed` | A7a |
| `TaskGroup(threads: N)` | the live worker pool plus the Send gate over the frame's resident values | `taskgroup_threads_parallel_sum`, `conformance/K02_nonsend_across_suspend_local_mt` | A17 |
| `Thread.spawn { }` | no frame: a sync item on an OS thread (§3.8). Out of scope (§1), except its body-is-sync refusal | `conformance/K83_thread_spawn_body_is_sync_enforced` | A18 |
| `join` | std code that drives the scheduler; not a suspension | `taskgroup_two_task_yield` | A7b |
| `cancel` / `cancelled()` | the cancel word in the task's cell, read through `cx`; parks observe it | `taskgroup_cancel_during_sleep` | A10 |

**Park reasons** (§3.9's closed set). The deadlock walk's classification is the current executor's rule (`__saw_exec_quiescent_now`):

| reason | lowering | deadlock walk | pin | unit |
|---|---|---|---|---|
| ready yield (`yield_now`) | record ready, return `Pending` | runnable | `taskgroup_two_task_yield` | A3b |
| op-budget forced yield | the same | runnable | `taskgroup_compute_preemption` | A9 |
| timer (`sleep`, the `timeout:` twins) | record the deadline; the executor's earliest-deadline timer | can run | `taskgroup_sleep_ordering` | A11 |
| fd readiness (`io_wait`) | record `-1`, then register through the executor funnel | can run | `net_precise_wakeup` | A12 |
| io-budget yield (design 89-c) | std's `__saw_rt_op_budget_tick` then `yield_now`; no compiler part | runnable | `net_budget_fairness` | A12b |
| channel wait | record the channel's readiness-word address | **parked**: the only state the walk counts | `conformance/K63_channel_wait_is_a_park`, `conformance/K67_quiescent_channel_deadlock_is_reported` | A13 |
| offload job | an fd park on the job's pipe; take (join) before leaving, cancelled or not. Spec, offload "Cancellation": a cancelled task waits for its C call, and its frame keeps the call's storage until the join (t4; risk R6) | can run | `offload_seam_first_tick`, plus A14's cancel-during-call pin | A14 |
| signal watch | an fd park inside `SignalWatch.next` | can run (it counts as I/O) | `conformance/K98_signal_wakes_a_parked_watcher` | A15 |

**Language refusals Stage 0 makes and sawc2 matches:**

| refusal | sawc2 rule | pin | unit |
|---|---|---|---|
| suspending recursion, naming the cycle | `coro.suspending-cycle` (new), after mono | `errors/coro_mutual_suspending_recursion` and 7 more | A1 |
| K37, `any` dispatch to a suspending implementation | `effect.any-suspends` (exists) | `conformance/K37_existential_dispatch_suspending_impl_refused` | in place |
| a closure body | `effect.closure-suspends` (exists) | `errors/coro_suspending_closure_body_in_a_visitor` | in place |
| `sync` contexts, `deinit`, `@export` | `effect.sync`, `export.suspends` (exist) | 27 tests | in place, with the vocabulary in A2 |
| a drive site in a suspending body | `coro.drive-in-suspending` (new) | `drive_site_in_suspending_body` | A4 |
| `Task.spawn` borrows, extents, `NoMove`, must-consume, `Never` body, Send gate, the freestanding `Task.spawn` | spawn-site rules | the K-rows named in §3.2 | A7, A8, A17, A18 |

## 4. Units
_(to be written: an ordered list; each unit with scope, dependencies, the stages and files it touches, pins, and open questions)_

## 5. Open questions for the user
_(to be written)_

## 6. Risks
_(to be written)_
