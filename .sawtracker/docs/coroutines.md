# sawc2 coroutines: the implementation plan (SL-545)

**Status: APPROVED by the user (Oct 12), with §5 ruled (below and in SL:open-questions, "Q-coro1 to Q-coro7"). The heap-frame word is `frame_alloc`, not the draft's `indirect`.** Every §4 unit is filed as a child of SL-545; the unit-to-issue map is on SL-545. The plan text is authoritative over the issues.

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
  - An embedded child is resumed by a direct call with the same signature. A heap child, a suspending `any Trait` dispatch and a suspending closure (phase C) are resumed through a *frame descriptor*: a constant record of `{resume, size, align, result glue, backtrace index}`, emitted by the backend (§5, decided). The executor calls `main`'s frame through one from A3b, and every task root through one from A7a.

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
| blocking extern (INLINE offload) | `park(offload)`: start the job, park on its pipe, take it | `expr_suspend_blocking` | A14a, A14b |
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
| `Task.spawn(f(…))` | a task-root item; a heap task box sized by the root's layout; enqueue through the frame descriptor; a must-consume handle | `background_task_spawn` | A7a, A7c |
| `group.spawn(f(…))` | the same root into the group's slots; a group handle, not must-consume; spawn borrows are extents carried by the handle | `taskgroup_two_task_yield`, `taskgroup_eager_teardown` | A8a, A8b, A8c |
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
| offload job | an fd park on the job's pipe; take (join) before leaving, cancelled or not. Spec, offload "Cancellation": a cancelled task waits for its C call, and its frame keeps the call's storage until the join (t4; risk R6) | can run | `offload_seam_first_tick`, plus A14b's cancel-during-call pin | A14a, A14b |
| signal watch | an fd park inside `SignalWatch.next` | can run (it counts as I/O) | `conformance/K98_signal_wakes_a_parked_watcher` | A15 |

**Language refusals Stage 0 makes and sawc2 matches:**

| refusal | sawc2 rule | pin | unit |
|---|---|---|---|
| suspending recursion, naming the cycle | `coro.suspending-cycle` (new), after mono | `errors/coro_mutual_suspending_recursion` and 7 more | A1 |
| K37, `any` dispatch to a suspending implementation | `effect.any-suspends` (exists) | `conformance/K37_existential_dispatch_suspending_impl_refused` | in place |
| a closure body | `effect.closure-suspends` (exists) | `errors/coro_suspending_closure_body_in_a_visitor` | in place |
| `sync` contexts, `deinit`, `@export` | `effect.sync`, `export.suspends` (exist) | 27 tests | in place, with the vocabulary in A2 |
| a drive site in a suspending body | `coro.drive-in-suspending` (new) | `drive_site_in_suspending_body` | A4 |
| `Task.spawn` borrows, extents, `NoMove`, must-consume, `Never` body, Send gate, the freestanding `Task.spawn` | spawn-site rules | the K-rows named in §3.2 | A7c, A8c, A17b, A18 |

## 4. Units

Each unit is one patch of about a day, separately testable. Each lists its scope, what it depends on, the files it touches (for overlap planning), its pins, its done-when and an estimate in agent-days.

Pins are named by their `tests/corpus/` program: each becomes a run-lane copy compared with Stage 0's binary, or a `tests/coro/` golden, refusal or injection. "Census +N" means the corpus census lane (A0b) counts N more of the 490 programs building and passing.

**Phases:**
- **0, groundwork** (1 day);
- **A, the embedded core:** Stage 0 parity, by by-value frames;
- **B, the overlay layout:** the user's stack-like frames. These are core units: B1 can start as soon as the verifier (A5) exists, and B runs beside A's std track;
- **C, heap frames:** after A and B.

**Three tracks**, whose files do not overlap, so two agents can run at once. Every unit has a track (revised for t6):

| track | files | units entirely inside it | crossing units, with what they cross into |
|---|---|---|---|
| **back:** compiler back half | `compiler/coro/` (new), `compiler/llvm/`, `compiler/mono/`, `compiler/driver/`, `compiler/tools/build.py`, `compiler/tests/{coro,run,mono}/` | A0, A0b, A1, A3c, A5, A6, A7a, A9, A14a, A16a, B2, B3, B4, C2, C3, C4 | A3a (`compiler/mir/`, the projection kind only); A3b (`std/task.saw`, the stub entry); A4 (`compiler/resolve/src/lookup.saw`); A8b (`compiler/typecheck/`); A17b (`compiler/typecheck/src/api.saw`); B1 (`compiler/borrowck/`, `compiler/drops/`); C1, C5, C6 (front half) |
| **std:** std and runtime | `std/`, `sawc/rt/`, `compiler/tests/std/` | A7b, A8a, A10, A11, A12b, A13a, A13b, A14b, A15, A16b, A17a | A12a (`sawc/std/taskgroup.saw` under §5 Q7, and the regenerated `compiler/typecheck/src/runtimeabi.saw`) |
| **front:** compiler front half | `compiler/resolve/`, `compiler/typecheck/`, `compiler/borrowck/`, `compiler/drops/`, `compiler/tools/std_suspension.py` | A7c, A8c, A18 | A2 (`std/{task,duration,prelude}.saw`) |

**The dispatch rule:** two units run at once only when neither one's files, crossings included, touch the other's. The two hot files are `compiler/coro/src/lower.saw` (back) and `std/taskgroup.saw` (std), and after the t6 and t7 splits each is touched by one track only.

### Phase 0: groundwork

**A0. Refuse a suspending call the backend cannot lower yet (SL-546).**
- **Scope:**
  - After mono, evaluate each call's `suspend` flag at its concrete instantiation.
  - The backend refuses a definitely suspending call, and a yield-capable budget point in a function that suspends, as `backend.not-yet` ("a suspending call is not lowered yet (SL-545)").
  - Every later unit removes cases from this refusal.
- **Depends on:** nothing.
- **Files:** `compiler/llvm/src/bodies.saw`, and a condition evaluator in `compiler/mono/src/` (A1 later takes it over); `compiler/tests/run/`.
- **Pins:** run-lane `// due:` programs `suspend_blocking_main` (the p02 probe) and `suspend_cycle` (p21).
- **Done when:** neither builds, each refused at the call, and the run lane is otherwise unchanged.
- **Estimate:** 0.5.

**A0b. A snapshot of the Stage 0 oracle, and the census lane.**
- **Scope:** before Stage 0 retires (SL-539, the seed), record for each of §3.2's 490 programs:
  - Stage 0's stdout and exit status;
  - its frame sizes from `--emit-frame-layout`;
  - its backtrace table's frame and state counts.

  These go in `compiler/tests/coro/stage0/`, as a TSV and per-program expectations. The run lane keeps comparing against live Stage 0 while it exists, and falls back to the snapshot after.

  **Settled with the Air (t9):**
  - **Each row records its target triple.** Frame sizes and backtrace offsets depend on pointer width and alignment, and SL-536 brings Linux and an x86_64 cross target. B4 compares only rows of the same triple.
  - **A0b is a hard prerequisite of removing `sawc/`.** Once Stage 0 is gone, nothing can regenerate its outputs, sizes or table shapes, and B4 and every "against Stage 0" pin rest on them. So A0b lands first: it has no dependencies. SL-539's removal checklist should name it (merged, with all 490 snapshotted) as a precondition, which is for the lead to add.

  `compiler/tests/coro/census.py` (informational, like `mir/corpus_info.py`) counts how many of the 490 programs and the 93 refusal tests sawc2 builds and passes, by first refusal. It also generates §1's *gated* list: the programs whose missing names include a std module or type outside this plan. The rest is the plan-complete set.
- **Depends on:** nothing.
- **Files:** `compiler/tests/coro/` only.
- **Pins:** the census lane prints today's 0 / 490.
- **Done when:** the snapshot is checked in, and the census runs in `run.py` as information.
- **Estimate:** 0.5.

### Phase A: the embedded core

**A1. The `compiler/coro` stage, and the *definitely suspends* fixpoint.**
- **Scope:**
  - A new package, `sawcoro`, in `STAGE_PACKAGES`, between mono and the backend, with `sawc2 coro (--dump | --check)`.
  - A worklist fixpoint over mono's items and their static call edges (principle 6: identity-based cycle detection, no depth bound). An item suspends if it contains a park or calls one that suspends.
  - Each item's frame decision and its cause chain in the dump, such as `(frame yes (via p21.slow -> usleep))`. `run<Fast>` prints `(frame no)` (this closes SL-526's visible half).
  - The cycle refusal `coro.suspending-cycle`, naming the cycle (`ping -> pong -> ping`) with Stage 0's pending note citing SL-322.
  - A0's refusal moves here: an item that needs a frame is refused until A3b.
- **Depends on:** A0.
- **Files:** `compiler/coro/src/{api,program,suspends,dump}.saw` (new), `compiler/driver/src/main.saw`, `compiler/tools/build.py`, `compiler/tests/coro/` (new lane: `coro_lane.py`, `golden/`, `refuse/`), `compiler/tests/run.py`.
- **Pins:**
  - `refuse/coro.suspending-cycle.*`, from `errors/coro_{mutual,main,method,group_spawn}_suspending_recursion` and the other four recursion tests;
  - golden `effects.coro` from the p21 probe.
- **Done when:** the 8 recursion tests refuse with the cycle named, and the dump agrees with typecheck's summaries wherever the arguments are concrete. The lane checks the second point: a disagreement is an invariant failure.
- **Estimate:** 1.5.

**A2. The task vocabulary and the park intrinsics** (front-half track, plus `std/`).
- **Scope:**
  - `std/task.saw` with `yield_now`. `std/duration.saw` with `Duration`. `sleep` and `cancelled` as declared std functions whose bodies call park lang intrinsics (`__saw_park_ready`, `__saw_park_timer`, …; the lang-item table names them).
  - Typecheck: a call to a park intrinsic is a suspension source in `summarize_declared`, so under the new std suspension comes from bodies, not from the Stage 0 table.
  - `tools/std_suspension.py`'s derived-set cross-check learns the new std.
  - The prelude names `sleep` and `Duration`, as Stage 0's does.
- **Depends on:** nothing (parallel with A1).
- **Files:** `std/{task,duration,prelude}.saw`, `compiler/resolve/src/{lang,prelude}.saw`, `compiler/typecheck/src/{summaries,effects}.saw`, `compiler/tools/std_suspension.py`, `compiler/tests/typecheck/`.
- **Pins:**
  - the 27 sync-context refusal tests reach `effect.sync` (today 4 do);
  - a typecheck golden where `yield_now` suspends under `--std-root std`.
- **Done when:** the sync-context rows pass under the new std, and `std.task` resolves.
- **Estimate:** 1.

**A3a. Frame-resident values and frame-slot places.**
- **Scope:**
  - For each framed item, the first-cut storage lifetime of each local: maybe-initialised (`MirInit`) through its scope-end drop. That is conservative, and B1 refines it.
  - The resident set: the values whose lifetime contains a suspension point.
  - One layout entry, `assign(values, interference) -> offsets`, here with the *no-sharing* policy, so that B2 changes the policy and nothing else.
  - A new MIR projection, the frame slot `(*frame).[off: T]`, with its dump spelling and verifier rule.
  - `sawc2 coro --layouts`.

  The frame has no drop glue (§3.1).
- **Depends on:** A1.
- **Files:** `compiler/coro/src/{frames,layout,dump}.saw`. `compiler/mir/src/{model,dump,verify}.saw` take the projection kind only, a small cross-track touch.
- **Pins:** golden layouts for p01 (`yield` in a loop, a value across it).
- **Done when:** the layout and resident sets are stable in goldens, and the backend still refuses (A3b lowers).
- **Estimate:** 1.

**A3b. The resume function, `park(ready)`, and the entry executor: the walking skeleton.**
- **Scope:**
  - `resume(frame, cx) -> Poll`. The entry switch on the state word, the `park(ready)` lowering (record the word through `cx`'s root token, set the state, return `Pending`), and `Done`.
  - The backend: frame-slot places, `Poll`, and the C entry calling std's `__saw_exec_run_main(desc, frame)`. That is a minimal single-root loop in `std/task.saw`, which A7b replaces with the real executor.
  - The frame descriptor's static record.

  This is the first running suspending program.
- **Depends on:** A1, A2, A3a.
- **Files:** `compiler/coro/src/lower.saw`, `compiler/llvm/src/{bodies,places,module}.saw`, `std/task.saw` (a small cross-track touch).
- **Pins:**
  - run-lane `yield_main`: a suspending `main` whose loop yields between prints;
  - corpus `async_main_*` programs without `sleep`.
- **Done when:** they print as Stage 0 does at -O0 and -O2.
- **Estimate:** 1.5.

**A3c. The `park` lowering for every reason** (back track; settled with the Air, t7).
- **Scope:** §3.9's "one lowering per case": one coro case per reason, each written and reviewed here, so "record before arm" is enforced per reason and A5's rule 4 checks each one.
  - *timer:* record the deadline;
  - *fd:* record `-1`, then call the executor's arm funnel `__saw_exec_io_register(fd, dir, token)`;
  - *channel:* record the readiness word's negated address;
  - *offload:* record `-1`, then arm the job's pipe through the same funnel;
  - *signal:* the fd case, reached through `SignalWatch.next`.

  Each case also reads its outcome on resume: ready, timed out, or cancelled. The std intrinsics name the reason and pass its operands; the executor functions each lowering calls are declared in std, and their bodies arrive with the std units (A11, A12a, A13a, A14b, A15). So the std units never touch `compiler/coro/`.
- **Depends on:** A3b.
- **Files:** `compiler/coro/src/lower.saw`, `compiler/tests/coro/golden/`.
- **Pins:** a lowered-MIR golden per reason, in which the record store precedes the arm.
- **Done when:** the five goldens are stable, and A5's rule 4 accepts them once it lands.
- **Estimate:** 1.

**A4. Driving a child frame, and the test intrinsics.**
- **Scope:**
  - Embedded child slots: parameter slots written at the call, the drive block, `Pending` returned as is, and `Ready` with the result moved out (§3.1).
  - `__saw_drive`, `__saw_drive_steps` and `__saw_suspend` as test lang intrinsics, with `steps` counting `Pending`s. Resolve stops refusing the three. A drive point is a root over a stack-allocated frame, and its rule depends on the reason a `Pending` reports (t8):
    - **on a ready yield,** it resumes at once;
    - **on any other reason** (timer, fd, channel, offload, or a group it runs inside), it hands the wait to the executor's sweep and idle wait. That shares the ambient scheduler, as Stage 0's drive points do: "one sweep … shared by every drive point" (`sawc/std/taskgroup.saw`).

    Until A7b provides that sweep, a non-ready `Pending` at a drive point panics, naming the reason, rather than spin. A busy re-resume would mask a lost wake.
  - `coro.drive-in-suspending` for a drive site in a body that suspends.
- **Depends on:** A3b.
- **Files:** `compiler/coro/src/lower.saw`, `compiler/llvm/src/calls.saw`; cross-track, `compiler/resolve/src/lookup.saw`.
- **Pins:**
  - `coro_nested_suspend_two_deep`, `coro_drive_void_body`, `expr_suspend_return`;
  - refusals `drive_site_in_suspending_body` and `drive_site_in_suspending_function`.

  The drive-point programs that sleep or run a group move to the unit that makes them pass: `taskgroup_suspending_parent_sleep` to A11; `taskgroup_nested_groups`, `taskgroup_in_suspending_fn`, `taskgroup_suspending_cancel` and `taskgroup_suspending_deinit_join` to A8a.
- **Done when:** the pins pass. Census: the intrinsic-driven programs whose parks are all ready yields or `__saw_suspend`s start passing. The census lane reports the exact count, rather than this plan guessing it.
- **Estimate:** 1.5.

**A5. The post-lowering verifier, first cut.**
- **Scope:** `compiler/coro/src/verify.saw` checks §3.9's rules on lowered MIR, by recomputing them, not by trusting the lowering's tables:
  1. a frame slot is only ever addressed in place through the frame pointer, so nothing relocates a frame a loan points into;
  2. at each suspension state, the maybe-initialised resident values equal what `MirInit` gives for the matching point, and every drop on every edge is one drop elaboration placed. Lowering added none (teardown by state, §3.1);
  3. every window is closed exactly once on every path, those out of a resumed state included;
  4. each park's record store dominates its arm.

  Injections go in `tests/coro/inject/`, as `tests/mir/inject/` does: drop a drop, add a second `window_close`, swap a record and its arm. Each must fail naming the rule.
- **Depends on:** A4.
- **Files:** `compiler/coro/src/verify.saw`, `compiler/tests/coro/inject/`.
- **Pins:** the three injections, plus every A3–A4 golden verifying clean.
- **Done when:** the injections fail and the corpus census shows no verifier failure.
- **Estimate:** 1.5.

**A6. Control flow, windows and expressions across a suspension.**
- **Scope:** §3.3's container, head and expression rows, plus the four lifted limits. Most of it is pins over the general CFG A3–A5 already handles. The new parts:
  - a window's state record resident across a suspension;
  - an accessor whose prologue or epilogue suspends, which embeds as a child (`window_open … suspends`);
  - collection `for` with a borrowing iterator.
- **Depends on:** A5.
- **Files:** `compiler/coro/src/lower.saw`, `compiler/tests/{coro,run}/`.
- **Pins:** every A6 row of §3.3; `lend_var_coro_and_forwarding`; the four lifted limits as run programs (`while_let_tuple_over_suspension_refused` and `coro_try_block_two_error_types` flip from refusal to run). Those four are marked `spec-derived expectation (no oracle)`, and their expected outputs are reviewed with the unit (t5). The spec's "Not yet supported" list shrinks in the same patch.
- **Done when:** all of them pass. This is the last unit before B1, so it should finish while frames are still unshared.
- **Estimate:** 1.5.

**A7a. Task roots and spawn lowering** (back track).
- **Scope:**
  - Mono adds a task-root item per cooperative spawn site (§3.8), and coro frames it whether or not it suspends, with its budget points live.
  - Spawn lowering asks std for a task box sized by the root's layout, writes the arguments into the root's parameter slots, and enqueues the box with its descriptor.
  - It serves both `Task.spawn` and `group.spawn`; A8b only adds the group's operand.
- **Depends on:** A4, A7c; A7b for the run pins.
- **Files:** `compiler/mono/src/worklist.saw`, `compiler/coro/src/lower.saw`.
- **Pins:** `background_task_spawn`, `coro_spawn_and_embed`.
- **Done when:** both pass.
- **Estimate:** 1.

**A7c. The `Task.spawn` form's front half** (front track).
- **Scope:**
  - resolve accepts `Task.spawn`;
  - typecheck refuses borrows at the form (K88) and a `Never` task body;
  - drop elaboration's must-consume roles name `Task<T>` and `VoidTask`, so `drop.must-consume`'s due fixture goes live.
- **Depends on:** A2.
- **Files:** `compiler/resolve/src/walk.saw`, `compiler/typecheck/src/bodies.saw`, `compiler/drops/src/elaborate.saw`.
- **Pins:** `conformance/K88_background_spawn_takes_no_borrows`, the `Never`-body tests, K78/K79/K85, `refuse/drop.must-consume`.
- **Done when:** the refusals pass. The accepted forms reach A0's backend refusal until A7a.
- **Estimate:** 1.

**A7b. The std executor core** (std track).
- **Scope:** the run queue; task slots with generations; cells holding the result and the cancel word (design 134); `Task<T>` and `VoidTask` with `join` (driving the scheduler), `detach` and `cancel`; the background group, built on the first `Task.spawn` and closed at `main`'s return (cancel, then join); the freestanding refusal. Ported from `sawc/std/taskgroup.saw` into the bootstrap language, calling frames only through the descriptor. Two invariants come with it (§3.1, t2 and t3):
  - a nested drive skips every frame that is active on the C stack;
  - a task box is released only after its root returned `Ready`, asserted.
- **Depends on:** A2. Testable before A7a against a hand-built descriptor.
- **Files:** `std/task.saw`, `std/taskgroup.saw` (new), `compiler/tests/std/`.
- **Pins:** a std-lane program driving two hand-built frames; then, with A7a, `background_task_spawn`.
- **Done when:** the pins pass.
- **Estimate:** 1.5.

**A8a. `TaskGroup` in std** (std track).
- **Scope:**
  - the `TaskGroup` type, `NoMove`;
  - `Deinit` driving the group's members to completion through the shared sweep;
  - a frame-resident group (G1);
  - handles that are not must-consume, with `detach` on one panicking.
- **Depends on:** A7b.
- **Files:** `std/taskgroup.saw`.
- **Pins** (with A8b): `taskgroup_two_task_yield`, `taskgroup_eager_teardown`, `taskgroup_nested_groups` (re-entrant join, expects `124`; t2), `taskgroup_in_suspending_fn`, `taskgroup_suspending_cancel`, `taskgroup_suspending_deinit_join`, the four `NoMove` refusal tests.
- **Done when:** with A8b, census +200 or so (`TaskGroup` appears in 206 of the 392).
- **Estimate:** 1.

**A8b. The `group.spawn` form** (back track, crossing into the front).
- **Scope:** typecheck stops refusing `group.spawn` (`known.task_group` looks in the new std), and A7a's spawn lowering takes the group as its queue.
- **Depends on:** A7a, A8a.
- **Files:** `compiler/coro/src/lower.saw`; cross-track, `compiler/typecheck/src/{api,bodies}.saw`.
- **Pins:** A8a's.
- **Done when:** they pass.
- **Estimate:** 0.5.

**A8c. Spawn borrows as extents** (front track).
- **Scope:** a `&`/`&var` argument or a borrow capture at a group spawn opens a loan the handle carries until `join` releases it, or until the group dies (spec: The borrow's extent is the task's life). This brings:
  - the declared-after-the-group refusal;
  - the loop-body refusal;
  - `move` of a borrowed root refused.
- **Depends on:** A8b.
- **Files:** `compiler/borrowck/src/{loans,conflicts}.saw`, `compiler/typecheck/src/captures.saw`.
- **Pins:** `spawn_capture_alias`, `spawn_capture_move_root` and the other spawn-extent tests.
- **Done when:** the 6 refusal tests pass and `fill(&var buf, 3)` runs.
- **Estimate:** 1.

**A9. The op budget, and the `cancelled()` read** (back track).
- **Scope:**
  - A live budget point in a framed item lowers to the per-frame counter (128 at frame init), plus `park(ready)` when it runs out.
  - Charge-only points decrement and never park.
  - Points in unframed items are deleted.
  - `cancelled()` lowers to a read of the cancel word through `cx`. Moved here from A10, so that the std track never edits `lower.saw` (t6).
- **Depends on:** A3b; A8b for the budget pin.
- **Files:** `compiler/coro/src/lower.saw`.
- **Pins:** `taskgroup_compute_preemption`, and the oracle sweep's `stage0/p5_budget.saw` (127, then 0).
- **Done when:** both pass.
- **Estimate:** 0.5.

**A10. Cancellation** (std track).
- **Scope:** the cancel word lives in the task's cell, and `cx` points at it; a cancel wakes the parked task; each park reports it. The compiler's one read is A9's.
- **Depends on:** A7b, A9.
- **Files:** `std/task.saw`, `std/taskgroup.saw`.
- **Pins:** `taskgroup_cancel_during_sleep` (with A11), the `cancelled()` programs.
- **Done when:** all pass.
- **Estimate:** 1.

**A11. Timers.**
- **Scope:** the executor half of `park(timer)` (A3c lowers it): `sleep(d)`; `Instant` (`std/time.saw`); the earliest-deadline timers; the reactor poll as the idle wait, with the earliest deadline as its timeout. The shared sweep's idle wait serves drive points too (A4, t8).
- **Depends on:** A7b, A3c.
- **Files:** `std/{task,taskgroup,time}.saw`.
- **Pins:** `taskgroup_sleep_ordering`, `async_main_sleep_yield`, `taskgroup_suspending_parent_sleep` (a drive point whose frame sleeps).
- **Done when:** all pass.
- **Estimate:** 1.5.

**A12a. The fd park and the register funnel.**
- **Scope:**
  - The executor half of `park(fd)` (A3c lowers it): `io_wait(fd, dir, deadline)` in std, and `__saw_exec_io_register`, the one arm funnel the lowering calls after it records `-1`.
  - On a timed-out or cancelled exit, the park unregisters.
  - SL-355's R5 runtime half (c20): the atomic wake word, the poll's CAS(-1 → 0) latch, and a `register` that returns a status, a failed arm panicking with the fd and errno. Where it lands is §5 Q7.
- **Depends on:** A11, A3c.
- **Files:** `std/taskgroup.saw`, `sawc/rt/host_{macos,linux}/reactor.saw`, `sawc/rt/ABI.md`, `compiler/typecheck/src/runtimeabi.saw` (regenerated); by §5 Q7, `sawc/std/taskgroup.saw`.
- **Pins:** a std-lane program parking on a pipe; SL-355's `parksoak` stress program as a run-lane program, with 0 stalls.
- **Done when:** the pins pass.
- **Estimate:** 1.

**A12b. A minimal cooperative `std.net`.**
- **Scope:** `TcpStream.pair`, `read`, `write` and `TcpListener.listen`/`accept` over `park(fd)`, with 89-c's io budget. The rest of `std.net` is std porting work (§1).
- **Depends on:** A12a.
- **Files:** `std/net.saw` (new).
- **Pins:** `net_precise_wakeup`, `net_budget_fairness`.
- **Done when:** both pass.
- **Estimate:** 1.

**A13a. Channels, cooperative half.**
- **Scope:** `std/channel.saw`: a `Copy` handle with an internal refcount and lock; `send`, `receive`, `close` and `try_receive`; the readiness word that `park(channel)` (A3c) records. `ChannelError` comes from design 230. The thread engine's blocking `recv` is out of scope.
- **Depends on:** A7b, A3c.
- **Files:** `std/channel.saw` (new).
- **Pins:** `channel_recv_nested`, `conformance/K63_channel_wait_is_a_park`, `conformance/K47_channel_receive_binding_and_try_heads`.
- **Done when:** all pass.
- **Estimate:** 1.

**A13b. The deadlock walk.**
- **Scope:** quiescence by elimination with §3.3's per-reason classification, read twice with a nap; the panic, then the task dump. The dump has frame lines once A16b lands; before that, its header only.
- **Depends on:** A13a.
- **Files:** `std/taskgroup.saw`.
- **Pins:** `conformance/K67_quiescent_channel_deadlock_is_reported`, and the oracle sweep's `stage0/p4_deadlock.saw`.
- **Done when:** both pass.
- **Estimate:** 1.

**A14a. Offload, the compiler half** (back track).
- **Scope:**
  - A `blocking` extern called in a framed body lowers to the offload sequence: `__saw_rt_offload_start`, then `park(offload)` on the job's pipe (A3c), then `take`, the join, on every exit, cancel included.
  - One C-ABI `word(word)` thunk is synthesized per offloaded extern, reading its frame-resident argument slots.
  - Not offloaded: in a `Thread.spawn` body a `blocking` extern is a plain call. In the freestanding profile it is refused.
- **Depends on:** A3c.
- **Files:** `compiler/coro/src/lower.saw`, `compiler/llvm/src/calls.saw`.
- **Pins:** lowered-MIR goldens for the sequence on its completion and cancel exits. The run pins come with A14b.
- **Done when:** the goldens are stable.
- **Estimate:** 1.

**A14b. Offload, the executor half** (std track).
- **Scope:** the job park in the executor, and `take` on a cancelled task's exit (spec, offload "Cancellation"; t4).
- **Depends on:** A12a, A14a.
- **Files:** `std/taskgroup.saw`.
- **Pins:**
  - `expr_suspend_blocking`, `offload_seam_first_tick`, and A0's `suspend_blocking_main`, now built;
  - a cancel-during-call program (t4): a cancel while the C call is in flight returns only after the call, and the frame's buffer stays valid until the take.
- **Done when:** all pass.
- **Estimate:** 0.5.

**A15. The signal watch.**
- **Scope:** `std/signal.saw`'s `SignalWatch.next` over `park(fd)`, ported.
- **Depends on:** A12a.
- **Files:** `std/signal.saw` (new).
- **Pins:** `conformance/K98_signal_wakes_a_parked_watcher`.
- **Done when:** it passes.
- **Estimate:** 1.

**A16a. The backtrace table** (back track).
- **Scope:**
  - `__saw_bt_table` built from the final layouts: per frame, its state word's offset, and per state its line and the offset of the child it drives.
  - `sawc2 coro --bt-table` decodes it.
  - It keeps Stage 0's blob format, so `tools/lldb_saw.py` keeps working.
- **Depends on:** B2, since offsets are final only after packing.
- **Files:** `compiler/coro/src/bttable.saw` (new), `compiler/llvm/src/module.saw`.
- **Pins:** decoded-table goldens for `task_backtrace_nest` and the oracle sweep's `stage0/p3_dump.saw`, compared with Stage 0's frame and state counts (A0b).
- **Done when:** the goldens match.
- **Estimate:** 1.

**A16b. `dump_tasks` and the panic-path dump** (std track).
- **Scope:** the walker over task slots and the table; the status words; the dump the panic path prints; and the unsynchronized-snapshot header on a multi-threaded group.
- **Depends on:** A16a, A7b.
- **Files:** `std/taskgroup.saw`, `std/task.saw`.
- **Pins:** `task_backtrace_nest`, `stage0/p3_dump.saw`, and K67's dump lines.
- **Done when:** all pass.
- **Estimate:** 1.

**A17a. `TaskGroup(threads: N)`.**
- **Scope:** the live worker pool; the run-queue lock and condition variable; the per-thread io budget; `cancel_addr` pinning a slot.
- **Depends on:** A8a, A12a (the reactor wake's broadcast).
- **Files:** `std/taskgroup.saw`.
- **Pins:** `taskgroup_threads_parallel_sum`, and the 25 `threads:` programs in the census.
- **Done when:** the pins pass.
- **Estimate:** 1.5.

**A17b. The Send-on-frames gate.**
- **Scope:** for a root spawned into a `threads: N` group, every resident value of it and of its embedded children, plus its result, must be `Send`. The check runs post-mono in coro (`coro.spawn-not-send`), naming the first offender, and refuses reference parameters.
- **Depends on:** A8b.
- **Files:** `compiler/coro/src/suspends.saw` (or `send.saw`), with a small cross-track touch to `compiler/typecheck/src/api.saw` for the `threads:` tracking.
- **Pins:** `conformance/K02_nonsend_across_suspend_local_mt`, `errors/taskgroup_threads_nonsend_reject`, the 7 Send-gate tests.
- **Done when:** all pass.
- **Estimate:** 1.

**A18. The remaining refusals.**
- **Scope:**
  - the `Thread.spawn` body's sync rule (K83) and the retired `spawn { }`, typecheck rules only;
  - the suspending default omitted;
  - `@align` on a frame-resident local (N11);
  - the freestanding `Task.spawn`;
  - `dump_tasks`' prelude gating;
  - `blocking` agreement.
- **Depends on:** A8b.
- **Files:** `compiler/typecheck/src/{bodies,effects,captures}.saw`, `compiler/resolve/src/walk.saw`.
- **Pins:** the remaining rows of the 93 (`coro_refusal_tests.txt`).
- **Done when:** the census shows every refusal test passing, except phase C's and the out-of-scope thread engine's. With A18, phases A and B close on the census green over §1's plan-complete set.
- **Estimate:** 1.

### Phase B: the overlay layout (core)

**B1. Storage lifetimes.**
- **Scope:**
  - The borrow check publishes each function's loan live ranges as plain data: a side table keyed by MIR ids (§3.0). Drop elaboration and mono carry it unchanged; it is type-independent, so substitution leaves it alone.
  - Coro computes each value's storage-live point set: maybe-initialised, plus any loan into it, plus its drop and epilogue points (§3.9: "the last thing that needs the bytes").
    - A child slot is live from its parameter writes through its result's move-out.
    - A window record is live from `window_open` through `window_close`.
  - `coro --dump` prints each set by state and transition.
- **Depends on:** A5.
- **Files:** `compiler/borrowck/src/{program,loans}.saw`, `compiler/drops/src/program.saw`, `compiler/mono/src/program.saw` (carry only), `compiler/coro/src/lifetimes.saw` (new). It crosses tracks, and it is the one unit that touches borrowck's output contract.
- **Pins:** golden lifetimes for: a value live across one suspension only; a loan extending a value past its last direct use; a child slot; a window record.
- **Done when:** the goldens are stable, and A3a's conservative lifetimes are replaced with no layout change yet.
- **Estimate:** 1.

**B2. Interference and fixed-offset packing.**
- **Scope:**
  - The interference graph over resident values, child slots and window records.
  - A deterministic greedy packing: by decreasing size, then first id; first fit at an aligned offset clear of every interfering value already placed. Callees are packed first, over the acyclic suspending call graph.
  - `--layouts` prints each value's offset, size and alignment, the total extent, and the lower bound: the largest sum of bytes live at one point (§3.9: the bound, not a formula).
- **Depends on:** B1.
- **Files:** `compiler/coro/src/{layout,dump}.saw`.
- **Pins:** golden layouts for:
  - sequential `a(); b()`;
  - exclusive `if` and `match` arms;
  - values in disjoint ranges;
  - design 163's synthetic tree (`w2`, `w4`, `w8`, `t1`, `root`), against Stage 0's snapshot sizes (A0b). `root` is 6,768 B there, and the overlay estimate is about 928 B;
  - the oracle sweep's `stage0/p2_layout.saw`, whose `caller` holds four 80-byte children (432 B in Stage 0).
- **Done when:**
  - each pin's extent is at most its sequential-overlay size from design 163's recurrence;
  - the census still passes;
  - `irdet`-style determinism holds: two runs give the same bytes.
- **Estimate:** 1.5.

**B3. The verifier's no-intersecting-lifetimes check.**
- **Scope:**
  - **The static check:** recompute storage lifetimes *from the lowered MIR's frame-slot accesses*, not from B1's sets, over parked states and the resume transitions. Then check that no two values sharing bytes intersect.
  - **Its dynamic twin** (t10, risk R2): a sawc2 sanitize flag that stamps `sanitize_address` on every function, plus, under it, `__asan_unpoison_memory_region` / `__asan_poison_memory_region` on each frame value's slot where its storage lifetime starts and ends. The run lane builds the coroutine programs once with it.
- **Depends on:** B2.
- **Files:** `compiler/coro/src/{verify,lower}.saw`, `compiler/llvm/src/module.saw` and `compiler/driver/src/main.saw` (the flag), `compiler/tests/coro/inject/`, `compiler/tests/run/`.
- **Pins:**
  - an injection that forces two interfering values onto one offset fails, naming both, the point and the state;
  - another that moves a drop past the end of its lifetime fails;
  - the same overlap injected at run time is reported by ASan at the access, and the clean corpus reports nothing.
- **Done when:** all three fail as described, and the corpus is clean both ways.
- **Estimate:** 1.5.

**B4. Frame sizes against Stage 0.**
- **Scope:** a lane over every corpus frame: sawc2's extent against Stage 0's snapshot. It fails on a frame larger than Stage 0's unless an exception with a reason is recorded (such as a resident value Stage 0 got wrong), and it reports the total saving.
- **Depends on:** B2, A0b.
- **Files:** `compiler/tests/coro/`.
- **Pins:** the lane itself.
- **Done when:** the lane passes with its exceptions reviewed.
- **Estimate:** 0.5.

### Phase C: heap frames, and what the same ABI unlocks

These units start after A and B. Q1–Q4 in §5 are their rulings.

**C1. Heap edges.**
- **Scope:** per §5 Q1, the edges into a heap-framed function inside its suspending-call cycle hold a box pointer instead of an embedded child. The child frame is allocated per Q2, driven by a direct call, and freed after `Ready` (its drops have run in its body). `--layouts` reports such a task as unbounded, naming the edge. The cycle refusal's fixit names the spelling.
- **Depends on:** phases A and B; §5 Q1 and Q2a.
- **Files:** `compiler/coro/src/{suspends,layout,lower}.saw`, plus the spelling's front-half rule (resolve and typecheck).
- **Pins:** the 8 recursion tests rewritten with the spelling, as run programs; the unmarked ones still refused.
- **Done when:** all pass.
- **Estimate:** 1.5.

**C2. The indirect drive.**
- **Scope:** a heap child reached through the descriptor in its box's header, which C5 and C6 need. The verifier learns that a heap frame is freed exactly once, after `Ready`, and never while a loan into it is live.
- **Depends on:** C1.
- **Files:** `compiler/coro/src/{lower,verify}.saw`.
- **Pins:** an injection that frees a box twice.
- **Done when:** the injection fails.
- **Estimate:** 1.

**C3. Recursion depth and cancellation through a heap chain.**
- **Scope:**
  - Depth: a 10,000-deep suspending recursion resumes and completes, using native stack in line with its sync twin (§5 Q4).
  - Cancellation: a task parked 1,000 levels deep is cancelled. It unwinds through the ordinary edges and frees every box. The allocator-count probe shows zero outstanding allocations.
- **Depends on:** C2.
- **Files:** `compiler/tests/{coro,run}/`.
- **Pins:** the two programs above.
- **Done when:** both pass.
- **Estimate:** 1.

**C4. Heap frames under the allocation profiles and freestanding.**
- **Scope (the user's Q-coro2a, 2b and 3 rulings):**
  - a failed frame allocation panics under the compiler-inserted-allocation boundary;
  - `--no-hidden-alloc` ACCEPTS `frame_alloc`, since the signature names the allocation;
  - a new `--no-frame-alloc` flag refuses any reachable `frame_alloc` function, naming the function and the call chain;
  - a new `-W frame-alloc` warning category (off by default, never affecting the exit code) warns at each call into a `frame_alloc` function;
  - an unbounded task is REPORTED in the frame-size report, never refused, freestanding included, wherever the runtime provides `__saw_rt_alloc`.
- **Depends on:** C1.
- **Files:** `compiler/coro/src/suspends.saw`, the driver (the flag and the warning category).
- **Pins:** a `--no-hidden-alloc` acceptance; a `--no-frame-alloc` refusal naming the chain; a `-W frame-alloc` warning (`EXPECT-WARNING-CONTAINS`) and its absence without the flag; a freestanding acceptance with the unbounded report.
- **Done when:** all the pins pass.
- **Estimate:** 0.5–1.

**C5. Suspending `any Trait` dispatch (K37 lifted).**
- **Scope:** per §5 Q5, a suspending requirement's vtable entry carries a frame descriptor and an init thunk, and the caller's storage is the union slot or a heap box. K37's refusal becomes a run program.
- **Depends on:** C2. Outside this plan, it needs sawc2 to call methods through `any` at all; today that is `slice.not-yet`.
- **Files:** `compiler/coro/`, `compiler/mono/src/` (method tables).
- **Pins:** `conformance/K37_existential_dispatch_suspending_impl_refused`, flipped.
- **Done when:** it runs.
- **Estimate:** 1.5.

**C6. Suspending closures.**
- **Scope:** a closure body that suspends is framed. The closure value carries its descriptor and init thunk, and a call allocates the frame per Q6, then drives it. `effect.closure-suspends` is lifted.
- **Depends on:** C2.
- **Files:** `compiler/coro/`, `compiler/typecheck/src/effects.saw`, `compiler/mir/src/lower.saw` (closure calls).
- **Pins:** the closure-body refusal tests, flipped.
- **Done when:** they run.
- **Estimate:** 2.


### Order, parallelism and totals

**The critical path to a running program:** A0 → A1 → A3a → A3b, with A2 alongside A1. That is about 4.5 agent-days, and A3b's `yield_main` is the walking skeleton. A3c and A4 follow on the back track, and A5 freezes the rules before anything widens. A0b goes first of all, since it has no dependencies and gates `sawc/`'s removal (t9).

**Two agents at once, by track:**

| agent | sequence |
|---|---|
| **1, back** | A0b, A0, A1, A3a, A3b, A3c, A4, A5, A6, B1, B2, B3, B4, A16a; then A7a, A8b, A9, A14a, A17b as their dependencies allow |
| **2, std, plus the front half between std units** | A2 (alongside A1), A7c, A7b, A8a, A10, A11, A12a, then A12b, A13a, A13b, A14b, A15, A16b, A17a in any order their dependencies allow; A8c and A18 in the gaps |

The sync points are:
- A3b needs A2;
- A7a needs A7c;
- A8b needs A8a;
- A10 needs A9;
- A14b needs A14a;
- A16b needs A16a.

None of these puts two agents on one file.

**Totals:**

| phase | units | agent-days | wall time with two agents |
|---|---|---|---|
| 0, groundwork | A0, A0b | 1 | |
| A, the embedded core | A1–A18, after the t6/t7 splits | 31.5 | about 3.5–4 weeks for 0, A and B together |
| B, the overlay | B1–B4 | 4.5 | inside A's wall time, on the back track |
| C, heap frames | C1–C4 | 4 | 1 week after A and B |
| C, the follow-ons | C5, C6 | 3.5 | + 0.5 week; C5 also waits on `any` method calls |

For comparison, the lead's guide (SL-545 c2) was 3 weeks for the core, 3–5 days for the overlay and 1–1.5 weeks for heap frames. The core comes out larger mostly because about 13 of phase A's 31.5 days are std porting that Stage 0 already had: the executor, `TaskGroup`, timers, the fd park, `std.net`'s slice, channels, the deadlock walk, offload's executor half, signals, the dump and the thread pool (the std track's units). The compiler part alone, about 18.5 days, is close to the guide.

### Amendments during implementation
The plan holds except where an amendment below says otherwise. Each one is the lead's reversible ruling on an implementing agent's stop, recorded on the units it touches.

- **A2 (SL-553 c3):**
  - its sync-context pin is the tests its vocabulary reaches (see the next entry);
  - its files gain `compiler/typecheck/src/lang.saw`, `compiler/tools/subset_check.py` and a `compiler/tests/std/subset/` fixture;
  - the park intrinsics are role-bound std declarations in `std/task.saw`;
  - `cancelled()` does NOT park, as in Stage 0: it reads `__saw_cancel_requested() -> Bool` (body `false`), which A9 lowers inside frames.
- **A2 and A4 (SL-553, adopting the Air's adjustment):** the typecheck SUMMARIES of `__saw_test_suspend` (design 22, effect-only, never lowered) and `__saw_suspend`, resolve's acceptance of their names, and the 15 sync-context refusal tests that call them are A2's, so A2's pin is about 23 of the 27. A4 keeps `__saw_suspend`'s `park(ready)` lowering and the drivers.
- **A18 (SL-580):** takes K83 and K112, and settles `runtime_build_suspending_body_error`'s bare `yield_now`.
- **A6 (SL-559) and A12b (SL-570), from A0b's census (SL-551):** the pins that need `Vector.iter`, `Map`, `std.mutex` or `Arc` stay gated, and the same shapes are pinned with the plan's vocabulary.
- **A0b:** the census hook in `compiler/tests/run.py` lands with A0b.

## 5. Open questions for the user

**RULED by the user (Oct 12):**
- **Q1:** opt-in, as the effect-slot word `frame_alloc` (`func walk(n: &Node) frame_alloc -> Int`). Read `indirect` below as `frame_alloc`.
- **Q2a:** (a), a panic under the existing boundary.
- **Q2b:** (i), accepted under `--no-hidden-alloc`, PLUS a separate flag. The lead spelled it `--no-frame-alloc` (a refusal), with a `-W frame-alloc` warning category beside it (unit C4).
- **Q3, Q4, Q5, Q6 and Q7:** (a), (a), (b), (a) and (a), each as recommended.

The options and reasoning below are kept as the record. Q1–Q6 belong to phase C, so phases A and B do not wait on them; Q7 is needed by A12a.

### Q1. Heap frames: opt-in or automatic, and how is it spelled?
Today a cycle in the suspending-call graph is refused, since it has no finite frame.
- **(a) Automatic.** The compiler heap-allocates the back edges of each cycle and the refusal disappears. Nothing is written, so a reader cannot see which calls allocate, or that a task's size is no longer static.
- **(b) Opt-in at the declaration.** A marker on the recursive function; calls *into* it from inside its own cycle get a heap frame, and calls from outside embed as usual. An unmarked cycle stays refused, with the marker as the fixit. Two spellings:
  - an effect-slot word, `func walk(n: &Node) indirect -> Int`, after Swift's `indirect enum`;
  - an attribute, `@heap_frame`.
- **(c) Opt-in at the call site:** `indirect walk(n.left)`. That is precise, but every recursive call carries it.

**Recommendation: (b), as the effect-slot word.** The doctrine says reader-visibility trumps inference, and a heap frame changes two things a caller can see: it may allocate (Q2a), and a task loses its static size (Q3). The effect slot is where callers read a function's contract, beside `unsafe` and `sync`. Freestanding targets depend on static task sizes, so a silent switch would undercut a guarantee those targets are designed around.

### Q2a. What happens when a heap frame cannot be allocated?
- **(a) A panic,** under the existing panic boundary for compiler-inserted allocations (design 234's list). No new boundary is needed, since this is exactly such an allocation.
- **(b) Fallible calls:** a call into an `indirect` function returns `Result<T, AllocError>`, and every recursive call site handles it.
- **(c) A fallible declaration:** the function must return `Result<_, E>` with `E` able to carry an `AllocError`, and a failed allocation surfaces as that `Err`.

**Recommendation: (a).** (b) makes recursion unreadable. (c) is defensible, and is the fallback if the user wants allocation failure visible in a signature.

**Freestanding:** heap frames are allowed wherever `Box` is, meaning the runtime provides `__saw_rt_alloc`.

### Q2b. Does `--no-hidden-alloc` accept a heap frame? (split out on the Air's t11)
Design 135 rejects "the allocations the compiler inserts that no source construct names", and Q1's spelling decides which reading is natural:
- **(i) The declaration names it.** Under Q1 (b), `indirect` in the callee's signature says "allocate" the way `Box(...)` does, so the profile accepts heap frames. A kernel audits them by finding `indirect`. A call to any function whose body allocates is already accepted, and this is the same visibility, one step stronger since it is in the signature.
- **(ii) The allocation must be named at the call.** The profile refuses heap frames, and Q1 (c)'s call-site spelling is the way in.

An escaping closure's environment is refused today, but that analogy is weaker than it looks: a closure literal never says "allocate", while `indirect` does.

**Recommendation: (i) with Q1 (b).** If the user prefers Q1 (c), (ii) follows from it, and the call-site word is what the profile accepts.

### Q3. A task whose frame tree has a heap edge has no static size. What follows from that?
- **(a) Report it:** `--emit-frame-layout` says "unbounded: heap edge at `walk`", and design 152's frame-size warning gains a category for it. The program is allowed.
- **(b) Refuse it in the freestanding profile.**
- **(c) Let the author state a bound.** Depth is not checkable, so the bound would be a run-time check that panics.

**Recommendation: (a).** Q1 (b) already makes the cost visible at the declaration. (b) would forbid recursion on exactly the targets that might want a bounded form of it later, and that design can come when one asks for it.

### Q4. How is a deep heap chain driven, and cancelled?
- **(a) Recursively.** Each level's `resume` calls the next, so one poll costs O(depth) time and native stack. That is the same depth a sync twin's recursion would use, and the same SL-313 limit applies to both.
- **(b) An executor-managed frame stack.** A resume returns "descend into this child" or "return to my parent", so one poll costs O(1). `Poll` grows two variants, and the executor grows the stack.

Cancellation is the same either way: it is cooperative, so each level returns through ordinary edges and frees its child's box after `Ready`. C3 pins a 1,000-deep cancel.

**Recommendation: (a).** It is parity with sync recursion, and it needs no ABI change. (b) can be added later, since the uniform ABI leaves room for it.

### Q5. Suspending dispatch through `any Trait` (K37): which design?
These are DF-223b's options:
- **(a) A heap frame per call,** made by the vtable's init thunk;
- **(b) A union slot.** The caller embeds storage sized to the largest frame among the conformers coerced to that `any`. Mono sees the whole program, so the set is known, and the static size is kept with no allocation;
- **(c) Keep it refused,** and say a suspending method cannot be reached through `any`.

**Recommendation: (b),** falling back to (a) for a conformer that is itself `indirect`. One caveat: this cannot start before sawc2 calls methods through `any` at all, which today is `slice.not-yet`.

### Q6. Suspending closures: which design?
- **(a) A heap frame per call,** through the descriptor and init thunk the closure value carries.
- **(b) Size the slot per function type.** It is not knowable without whole-program flow analysis of function values.
- **(c) Keep it refused.** Spec: "a closure body cannot suspend".

**Recommendation: (a),** refused under `--no-hidden-alloc` as an escaping environment already is, and allowed elsewhere as Q2a says.

### Q7. Where does SL-355's runtime half (R5) land?
R5 is the ruled atomic wake word with its CAS(-1 → 0) latch, plus a `register` that returns a status. It is in neither runtime yet, and `sawc/rt/` is shared by both compilers.
- **(a) Land it at A12a in `sawc/rt/` and both stds.** `sawc/std/taskgroup.saw`'s change is the maintenance fix SL:architecture §4 names for exactly this seam. It breaks the ABI for runtime providers (the 0.12.0 cut the user ruled); sawos follows in SO-18 when it resumes.
- **(b) sawc2 takes R1–R4 now, on the compiler side, and the runtime half waits for Stage 0's retirement.** Until then, SL-353's lost wake stays latent in `threads: N` groups.
- **(c) Give sawc2 its own reactor copy.** Two runtimes is what §3.11 avoids.

**Recommendation: (a).** The code is already reviewed (SL-355 c20), and without it A17a's multi-threaded pool inherits a known hang. It needs the user because it touches the frozen tree and sawos's ABI.

### Decided by the planner (reversible)
Each is recorded where it applies, and the Air reviewed §1–§3's. Reversal is cheap in each case.

| decision | where | reversal |
|---|---|---|
| no forced-destroy entry, since every frame leaves through its own code; checked by an executor assertion | §3.1, A7b; t3 | generate one from the per-state live sets |
| the test intrinsics `__saw_drive`, `__saw_drive_steps`, `__saw_suspend` stay, with Stage 0's meaning | §3.2, A4 | migrate 125 programs |
| Stage 0's four implementation-limit refusals are lifted, with spec-derived pins | §3.3, A6; t5 | refuse the same four |
| the op-budget counter is per frame, 128 at frame init, matching Stage 0 | §3.1, A9 | move it into `cx`, per task |
| `Channel.receive` and the net reads are ordinary suspending methods, with no inline special case | §3.1 | none needed |
| the walking skeleton is a suspending `main` that yields; the first spawned task arrives in A7a | A3b | none needed |
| the borrow check publishes loan ranges as data (one owner), and coro does not recompute them | B1 | coro recomputes from the MIR |
| packing is greedy first fit by decreasing size, deterministic, with the lower bound reported beside it | B2 | another heuristic behind the same `assign` entry |
| the frame descriptor is emitted by the backend as a constant, not as a Saw `static`, since a non-integer static is `backend.not-yet` | A3b | a Saw static, once the backend lowers one |

## 6. Risks

Each risk names what could blow up the estimate, then the unit that retires it, and how.

**R1. Frame packing over a general CFG** (B1–B3).
- **The risk:**
  - with fixed offsets the interference need not admit a tight packing;
  - a value live around a loop is live in every state of it;
  - a greedy packer can land far above the lower bound.

  None of that is incorrect, but it is the user's requirement.
- **How it is retired:**
  - B1 computes lifetimes and checks them in goldens *before* B2 packs anything, so a lifetime bug and a packing bug are told apart;
  - B2 reports the lower bound beside every extent, so quality is measured, not argued;
  - design 163's synthetic tree is the yardstick (Stage 0 6,768 B; the overlay recurrence about 928 B);
  - A3a's no-sharing policy stays behind the same `assign` entry, so a packing bug can be bisected by switching policy without touching lowering.

  MIR from structured source has a reducible CFG, so liveness is the ordinary dataflow.

**R2. A storage lifetime that is too short** (B1, B3).
- **The risk:** this is the one silent failure mode: two values share bytes while one still needs them. A loan that outlives its value's last direct use, a drop flag, a window epilogue reading the record, and a child's result move-out are the four ways to get it wrong.
- **How it is retired:**
  - B1 takes loans from the borrow check's own facts, not a second analysis;
  - B3 recomputes lifetimes from the *lowered* MIR's frame-slot accesses and fails on any intersection, with injections proving it can fail;
  - B3 adds a *dynamic* twin of that check (settled with the Air, t10; probe `air-review/coro/asan/`). Plain ASan can't see R2 for two reasons:
    - clang instruments only functions carrying `sanitize_address`, and sawc2's `.ll` has none;
    - R2 is two values overlapping inside one live frame allocation, which whole-allocation tracking never reports.

    So sawc2 gains a sanitize flag that stamps the attribute, a small backend change useful beyond coroutines. Under that flag, coro emits `__asan_unpoison_memory_region` where each value's storage lifetime starts and `__asan_poison_memory_region` where it ends. An access through a lifetime B1 computed too short then reports at the access. Normal builds pay nothing. The run lane builds coroutine programs once with the flag.

**R3. Cancellation** (A10, A12a, A14b).
- **The risk:** cancellation is cooperative, so correctness lives in each std park (record, arm, observe the cancel word, unregister on the way out). That is the SL-353 family: a wake lost between arming and recording.
- **How it is retired:**
  - every park goes through one MIR terminator, whose lowering records before it arms (verifier rule 4, A5);
  - A12a brings SL-355's atomic latch (Q7) and its `parksoak` stress program as a run-lane pin;
  - A10's pins cover cancel during sleep, io and a channel wait.

**R4. The deadlock walk** (A13b).
- **The risk:** the walk decides by elimination over unsynchronized reads, and a false positive aborts a correct program. Design 127's forced yields look exactly like a permanent wait.
- **How it is retired:**
  - A13b ports Stage 0's rules verbatim (`__saw_exec_quiescent_now`: only readiness-word parks count, and the walk reads twice with a nap) rather than re-deriving them, as §3.9 asks;
  - besides K67 and the oracle sweep's `stage0/p4_deadlock.saw`, a negative pin: a long compute task beside a parked channel waiter must never be reported.

**R5. The re-entrant scheduler** (A7b, A8a).
- **The risk:** a nested drive that resumes a frame active further up the C stack corrupts it, and no static check sees it (t2).
- **How it is retired:** A7b ports Stage 0's skip, under the queue lock on a multi-threaded group, and A8a pins `taskgroup_nested_groups`.

**R6. Offload cancel latency is unbounded** (A14a, A14b; t4).
- **The risk:** a cancelled task parked on an offload waits for its C call to finish (spec, offload "Cancellation"). SL-544 is the instance: `std.process`'s stdout drain is a `blocking` extern, so cancelling `output()` waits for the child.
- **How it is retired:** A14b pins the behaviour. The std ports this plan unblocks use an fd park (`io_wait`) for any wait with no bound, and keep the offload for calls that finish.

**R7. Stage 0 retires mid-plan** (A0b).
- **The risk:** the seed ruling retires `sawc/` once a seed bootstraps (SL-539), and the run lane's oracle is Stage 0's live binary.
- **How it is retired:** A0b snapshots the 490 programs' outputs, frame sizes and table shapes first, so the plan never depends on Stage 0 surviving.

**R8. The std porting volume, and sawc2 gaps met inside it** (A7b, A11–A15, A17a).
- **The risk:** a third of phase A is std code that Stage 0 already had, written in the bootstrap language. It will meet sawc2 gaps that nobody has needed yet. Two are already known:
  - a method call through `any` is `slice.not-yet`, so the executor cannot use Stage 0's `Box<any Resumable>`;
  - a static that is not an integer or a Bool is `backend.not-yet`.

  §3.1 designs around both: a backend-emitted frame descriptor, called through function pointers.
- **How it is retired:** per agent conduct, a unit that meets a gap stops, files it with its mechanism, and reports. The std track is kept separate from the compiler track, so one waiting does not stall the other.

**R9. Compile time on large frames** (A6, B4).
- **The risk:** Stage 0's frames drove LLVM into quadratic time and an aggregate limit (SL-230, SL-232, SL-336), because a frame was a first-class aggregate.
- **How it is retired:** in sawc2 a frame is bytes addressed by `getelementptr`, with no `insertvalue` and no frame-sized SSA values, so that class cannot recur. A resume function's state switch still grows with its state count, so B4's lane records compile time on the largest corpus frames alongside sizes.

**R10. Heap-frame depth** (C3; Q4).
- **The risk:** recursive driving costs O(depth) native stack per poll.
- **How it is retired:** C3 measures 10,000 levels against the sync twin, and Q4's option (b) is the fallback, which the uniform ABI leaves room for.
