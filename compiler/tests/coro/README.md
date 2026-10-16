# compiler/tests/coro: coroutine lowering

Coroutine lowering (`compiler/coro`, package `sawcoro`, SL:coroutines §3.1)
is the stage between mono and the backend. This file specifies `sawc2 coro`'s
records, the suspension decision, what a frame holds and how it is laid
out, which frames are lowered and how, the rules it refuses by, and the lane.
The stage decides, per item, whether it needs a frame, what that frame holds,
and whether this compiler lowers it; an item that needs a frame it does not
lower is refused.

```
coro/
  README.md               this specification
  coro_lane.py            the lane compiler/tests/run.py runs
  golden/                 NAME.saw, a program; NAME.coro, its frame decisions
                          and lifetimes;
                          NAME.layouts, its frames' layouts; NAME.lowered, its
                          lowered frames' resume functions
  refuse/                 RULE.saw or RULE.VARIANT.saw, a program refused
  inject/                 NAME.saw, a program a unit program lowers, then
                          edits, to prove the verifier refuses a shape no
                          lowering emits
  modules/                packages a fixture imports, one directory each
  parks/task_tail.saw     what the park goldens' copy of std adds to task.saw
  parks/NAME.saw          a verifier injection's unit program that needs
                          that copy, which the lane runs (see "The verifier")
  census.py               the coroutine census, for information
  expect.py               a corpus program's run directives, read and judged
  stage0/                 Stage 0's recorded snapshot and its writer, snapshot.py
                          (see "The Stage 0 snapshot and the census")
```

## `sawc2 coro`

```sh
.build/sawc2 coro (--dump | --layouts | --lowered | --check) [--notes] [--std-root DIR]
                  [--target TRIPLE] [--module-path NAME=DIR]... [FILE | @LIST]...
```

Each FILE is the entry of its own program, brought through mono as
`sawc2 mono` brings it. Its record, after the `FILE` line, holds everything
`sawc2 mono --check` prints; then, when nothing there is an `ERROR` or an
`INVARIANT` line, one `ERROR<TAB>rule<TAB>file:line:col<TAB>message` line per
refusal of this stage, an `INVARIANT<TAB>coro<TAB>message` line per broken
invariant, and with `--dump` one line per item:

```
item #K: NAME  (frame yes (via CHAIN))
item #K: NAME  (frame yes (task root))
item #K: NAME  (frame yes (task root, via CHAIN))
item #K: NAME  (frame no)
```

NAME is mono's dump name for the item (`compiler/tests/mono/README.md`), in
mono's item order; a task root's ends in `task root`, and its line says so,
then its chain when it also suspends. CHAIN is the item, then each item its suspension was found
through, then the source: `main -> caller -> nap -> usleep`. Each link is the
declaration's path inside its module (`ping`, `Walker.walk`), so the two
instantiations of a generic function name it alike, and an accessor's
prologue and epilogue both name the accessor. After the item lines, `--dump`
prints each frame's storage lifetimes, in item order (see "Storage
lifetimes", below). With `--layouts`, the record
holds instead each frame laid out for `--target` (`arm64-apple-darwin` by
default), in item order (see "Frames", below), or the line `no frame` when
the program has none; with `--lowered`, each lowered frame's resume function
for `--target`, in item order (see "Lowering"), or the line `no lowered
frame`. The exit code is 1 when any program has a refusal or an
invariant, 2 on a usage failure, and 0 otherwise. `sawc2 build` runs this
stage, and prints its record when it refuses (`compiler/tests/run/README.md`).

## Which items suspend

After mono every statically dispatched call, a call through a generic bound
included, has a concrete target, so *definitely suspends* is decided here,
over mono's items (SL:architecture §3.9). The decision is one funnel,
`compiler/coro/src/suspends.saw`, whose docstring names its entry points.

- A call **may** suspend when typecheck flags it (`MirCall.suspend` is
  `Always`, or `When` a condition over the caller's type parameters).
- A call is a **source** when it may suspend and its target's suspension is
  not decided by a body here: the target has no body (an `extern`, an
  interface-only std function, one mono could not make), which keeps
  typecheck's answer, or its summary comes from its declaration rather than
  its body, as a park intrinsic's does. A `blocking` extern is a source.
- An item **suspends** when its body holds a source, or a call that may
  suspend to an item that suspends. A window's open and close are calls to the
  accessor's prologue and epilogue, so an accessor whose prologue suspends
  makes its caller suspend.

It is solved as a least fixpoint, breadth first from the sources over the
call edges reversed, so a cycle suspends only when a call in it reaches a
source, each item is marked once, and its cause chain is a shortest one. The
graph is walked with work lists, never recursion (SL:architecture §2,
principle 6). So `run<Fast>`, whose bound's `step` does not suspend at
`Fast`, needs no frame, while `run<Slow>` does (golden `effects`), and a cycle
that reaches no source is ordinary recursion, unframed and never refused, even
when typecheck flags its calls (golden `cycle_without_suspension`, which the
run lane also builds and runs).

A default value's item is a call of its own in the caller, so a suspending
default makes the caller suspend and leaves its function unframed (golden
`default_caller`).

An item **needs a frame** when it suspends, and a task root (mono's
specialization of a spawn site's root) needs one even when it does not
(SL:architecture §3.9). A spawn site is no call of its root, so it is no
edge of the graph, and a task root suspends exactly when its function does.

**Agreement with typecheck.** Where typecheck's summary of a body is
unconditional, the decision must agree with it at every instantiation: a
body typecheck says suspends suspends here, one it says never suspends does
not, and a closure body never suspends. A disagreement is an `INVARIANT`
line, not a refusal: one of the two stages is wrong.

## Frames

A frame is bytes with a layout, not a struct with glue (SL:coroutines §3.1).
What each item's frame holds is decided by one funnel,
`compiler/coro/src/frames.saw`, each value's storage lifetime by another,
`compiler/coro/src/lifetimes.saw`, and where each value sits by a third,
`compiler/coro/src/layout.saw`; each docstring names its entry points. No
frame is found when a cycle is refused, since none is finite then.

**Program points and suspension points.** An item's program points are each
statement and each terminator of its body, in block order. A call that
definitely suspends adds two more after its terminator's: the moment the call
is suspended, its arguments taken and its destination not yet written; then,
when the call returns, its return edge, where its destination is written,
the resume transition out of that state. The suspension points are the
first of those, and each yield-capable op-budget point, which lowers to a
yield in a framed item (SL:architecture §3.9). They are numbered in block
order from 1, the states the resume function re-enters at; state 0 is the
start.

**Storage lifetimes.** A frame value's storage lifetime is the set of
program points just before which its bytes are needed. Residency, the
layout's interference and the dump all read it from the one funnel,
`compiler/coro/src/lifetimes.saw`:

- **the state word and the op-budget counter:** every point;
- **a local**, the result and the parameters included: the points just before
  which the initialisation analysis says it may be initialised, whole or in
  part (`compiler/mir/src/initialisation.saw`), and the point of each
  assignment that writes into it, whole or in part, other than through a
  dereference. So it runs from the statement that initialises it through its
  scope-end drop, and a local that is moved is dead until it is assigned
  again. A local only ever copied never stops being initialised, so its
  lifetime runs to the end. The assignment's own point is in it because the
  backend writes an rvalue straight into its destination, a moved memory
  value by one `memcpy` and an aggregate member by member, while it still
  reads the values the statement moves out of (golden `pack_move`);
- **a window's state record**, a local whose accessor's halves write and read
  it through a reference the analysis never sees: also every point at which
  its window may be open, from its open's terminator through its close's
  call, the time a suspending half runs and its open's return edge among
  them (golden `windows`);
- **a child slot:** its call's terminator, before which its parameter slots
  are written; its suspension point, where it is driven to `Ready`; and when
  the call has a destination, its return edge, where its result is moved out;
- **an offload's storage:** its call's terminator, which starts the job; its
  suspension point; and its return edge, where the take reads the job word.

No loan needs a set of its own. References are parameters only, so a frame
never holds a reference local, and a loan live across a suspension is a call
argument to a suspended child, a window's lend or a spawn borrow, each
already inside the maybe-initialised set of the value it points into or the
record's window. Nor does a lifetime end at a last use: an owning value is
read by its own scope-end drop (the spec's "Scope-end release"), so its
storage is never dead before that drop, and only a value with no drop could
end earlier.

Sequential suspending calls have disjoint child-slot lifetimes, so the layout
overlays them (goldens `lifetimes` and `pack_sequential`).

**The lifetimes in `--dump`**, per frame, in item order:

```
lifetimes #K: NAME
    state: every point
    op budget: every point
    _L WHAT: POINTS
    child NAME: POINTS
    offload EXTERN: POINTS
```

one line per value, in the frame's order (below). POINTS is `every point`,
`none`, or the points in order: `bbB.N` for statement N of block B and
`bbB.t` for its terminator, a run of them in one block as `bbB.N-M`; `sK` for
state K, the suspension point, which for a yield-capable op-budget point is
its statement; and `rK` for the resume transition out of state K, its call's
return edge. So `bb0.t s1 r1` is a child driven at state 1 whose result is
moved out, and `bb0.t s1` one with no destination.

**What a frame holds**, in this order:

- the state word, an `Int`;
- when the body has an op-budget point, the op-budget counter, an `Int`
  (Lowering, below);
- the result, `_0`, which the caller moves out after `Ready`;
- every parameter, the receiver and an environment included, which the
  caller writes into the frame before the first resume;
- every other local whose storage lifetime contains a suspension point, in
  local order;
- a child slot per suspending call to an item that needs a frame, in the
  order of the calls: the child's frame, embedded by value. Two calls of one
  function have a slot each;
- an offload storage per call of a `blocking` extern (Lowering, below),
  among the child slots in the order of the calls: an `[Int; N + 1]` for an
  extern of N parameters, the job word, then each argument widened to a
  word.

Every other local stays on the resume function's stack. A resident local is
reached through a frame slot, `(*frame).[OFFSET: T]`, a MIR projection
(`compiler/tests/mir/README.md`). The frame has no drop glue: every drop stays
where drop elaboration placed it, at its MIR position. So a window held open
across a suspension keeps its record in the frame, and a one-statement window
between two suspensions keeps it on the stack.

**Layout.** Each value's size and alignment are the target's
(`compiler/target`), and a child slot's are its child's frame's, so frames
are laid out callees first. Two values interfere when their storage
lifetimes share a point, and two values share a byte only when they do not
interfere. `coro_assign` takes the values and their interference and gives
each an offset by a deterministic greedy packing (SL:coroutines B2):

1. the state word takes offset 0, since the resume function loads the state
   from the frame's first byte and a drive starts a child at its slot's
   base; it counts as interfering with every value;
2. then each other value in turn, by decreasing size and then in the frame's
   order, takes the lowest offset its alignment allows whose bytes no value
   already placed that interferes with it holds.

So sequential children and exclusive arms share one slot (goldens
`pack_sequential`, `pack_arms`, `pack_tree`, `pack_p2_layout`), and so do
values whose lifetimes are disjoint (golden `pack_disjoint`). The frame's
alignment is its values' largest, and its size the end of its last value
rounded up to it. A zero-size value, such as an empty struct, the `Void`
payload of a `try!`, an empty tuple or a zero-length array, occupies no byte
and is placed after every value that does: it takes the lowest offset its
alignment allows that lies on no byte another value holds, often the frame's
end. A slot is told apart by its offset and its type, and zero-size
parameters of one type share a slot (golden `zero_size`). A frame holding a value the target cannot
lay out, a child frame that cannot be among them, gets no offsets.

The frame's **lower bound** is the most bytes its values need at one
program point: the sum of the sizes of the values live there, at the point
where that sum is largest. It is the packing's goal, not a size formula
(SL:architecture §3.9): with fixed offsets over a general control-flow graph
a packing may not reach it, and alignment adds to it.

**The `--layouts` record**, per frame, in item order:

```
frame #K: NAME  (size S align A, lower bound B)
    suspend N: bbB call LABEL
    suspend N: bbB budget
    (*frame).[OFFSET: T]  size S align A  state
    (*frame).[OFFSET: T]  size S align A  op budget
    (*frame).[OFFSET: T]  size S align A  _L WHAT  (across N...)
    (*frame).[OFFSET: frame NAME]  size S align A  child  (across N)
    (*frame).[OFFSET: [Int; N]]  size S align A  offload EXTERN  (across N)
    stack: _L...
```

S in the header is the frame's extent and B its lower bound (Layout, above).
The header's parenthesis is `(unsupported: T)` for a frame holding a value
of type T the target cannot lay out, and each OFFSET is then `?`; a child
slot's type is `frame NAME`, its child item's frame. LABEL names
the call's target as a cause chain does. WHAT is the local's note, as mono's
dump writes it: `result`, `param NAME`, `self`, `env`, `record`, `flag NAME`,
the binding's name (`ref NAME` for a borrow binding), or nothing for a
temporary. The across list is each state the value's lifetime contains, left
out when it has none. `stack:` lists the locals after `_0` the frame does not
hold, or says `none`.

## Lowering

Which frames are lowered is one funnel, `compiler/coro/src/lower.saw`, whose
docstring names its entry points (SL:coroutines §3.1). A frame is
**lowered** when every suspension point in it is a shape this compiler
lowers:

- a park, of any reason: a call of one of `std.task`'s park points, by its
  lang role (`__saw_park_ready`, which `yield_now`'s body is;
  `__saw_park_timer`, which `sleep`'s is; `__saw_park_fd` and
  `__saw_park_fd_until`; `__saw_park_channel`; `__saw_park_offload`), or of
  the test intrinsic `__saw_suspend`, a ready park;
- a call of a `blocking` extern, which is offloaded (below);
- a call of the test intrinsic `__saw_test_suspend`, a suspension for the
  effects alone (design 22): it frames its caller and runs as nothing;
- a yield-capable op-budget point (design 127), which charges the frame's
  counter and parks ready when it runs out;
- a call driving a child whose frame is lowered, a window's open or close
  among them when the accessor's prologue or epilogue suspends: the half is
  the child, and the window's record is in the caller's frame while it runs.

and none is the open of a conditional window, one with an absent edge, whose drive would continue on one edge where the window
has two. Children are decided before their callers. Every other
item that needs a frame keeps `coro.not-yet` (Rules, below), so the backend
only meets lowered frames.

A lowered item's concrete body is rewritten in place: it gains one local,
the frame pointer `_F`, a `&var Int` pointing at the frame's state word, and
each place rooted in a frame-resident local `_L` becomes `(*_F).[OFFSET:
T]` followed by the place's own steps. A projection names its index by local,
and a frame value is no local any more, so an index by a frame-resident `_L`
becomes an index by a new stack local `_t`, one per such `_L`, loaded `_t =
copy (*_F).[OFFSET: T]` just before each statement or terminator naming the
place, with no suspension between (golden `index_reads`; the run lane's
`coro_index_read_from_frame`). A drive's call `dest = g(args)` in
block `bbB`, whose child slot is at offset S, is rewritten too (SL:coroutines
§3.1):

- `bbB` gains, after its statements, one write per argument into the child's
  parameter slot, `(*_F).[S + P: T] = arg`, the argument moving or copying
  as the call passed it;
- the call keeps its target and loses its arguments and its destination: it
  is the drive, which passes nothing;
- when the call has a destination, its return edge goes to a new block,
  numbered after the body's own, `dest = move (*_F).[S + R: T]; goto ->
  bbN`, which moves the child's result out once it is `Ready` and continues
  where the call returned.

A park's call `__saw_park_R(args)` in block `bbB` is rewritten so that the
park records itself in the task's context before it arms anything
(SL:architecture §3.9, SL-355's R1). The frame gains a second local, the
context pointer `_C`, a `&var std.taskgroup.TaskContext` the resume function
points at its `cx`; the park word is `(*(*_C).park)`, an `Int`, and the
deadline `(*_C).deadline`, a `UInt64`, each reached by its field. The park
word's values are std's vocabulary (`std/taskgroup.saw`): 0 ready, 1 a timer,
-1 a descriptor, below -1 a channel's readiness word by its negated address.
Each argument moves or copies as the call passed it, and the call, its
arguments taken, ends the last block the rewrite leaves: it is the park.

| reason | the park's blocks |
|---|---|
| ready | `bbB` gains `(*(*_C).park) = const 0` |
| channel | `bbB` gains `(*(*_C).park) = WORD` |
| timer | `bbB` ends in `_d = __saw_exec_timer_deadline(NANOS)`, then a new block records `(*_C).deadline = move _d` and `(*(*_C).park) = const 1` and parks |
| fd | `bbB` gains `(*_C).deadline = DEADLINE`, or `const 0` for `__saw_park_fd`, `(*(*_C).park) = const -1` and the token `_t = cast(copy (*_C).park as Int)`, and ends in the arm `__saw_exec_io_register(FD, WRITE, move _t)`; a new block parks |
| offload | `bbB` gains `(*_C).deadline = const 0`, `(*(*_C).park) = const -1` and the token, and ends in `_p = __saw_exec_offload_pipe(JOB)`; a new block ends in the arm `__saw_exec_io_register(move _p, const 0, move _t)`; another parks |

A signal watch parks as a descriptor does. So in every reason the record
dominates the arm, and an arm's token is the park word's address, which
lives as long as the task. The executor functions each lowering calls are
`std.taskgroup`'s; mono reaches them from the park's call. A park this
executor does not wait on yet panics, never returns early: an offload park
panics naming the unit that brings its executor half (SL:coroutines A14b). A
descriptor park's arm is the reactor's (A12a): it panics when the arm fails,
and the reactor's poll latches the park word once the descriptor is ready. A
channel park arms nothing: it is resumed once the readiness word it names is
nonzero, which a send or a close on that channel sets (A13a). A timer park,
which arms nothing either, is resumed once its deadline passes, at a drive
point (SL-645) and in the entry executor alike (the run lane's
`drive_timer_park` and `main_timer_park`). Every park returns nothing: its
cancelled outcome is the task's cancel word, which the frame reads after its
park (A10), and a timer has no outcome but its deadline; `std.task`'s
`io_wait` reads a bounded descriptor park's timed-out outcome off the clock
after the cancel word (the std lane's `park_` executor programs).

A call of `__saw_test_suspend` becomes a goto where it returned.

A call of a `blocking` extern, `dest = ext(args)` in block `bbB` (design
103; SL:coroutines A14a), is offloaded: the extern runs on a thread of its
own while the frame parks, and the frame's offload storage at offset S holds
the job and the arguments. Which calls are offloaded is one funnel,
`coro_offloaded_extern` in `compiler/coro/src/frames.saw`, which the frame's
storage, the lowering and the verifier all ask. The call keeps its arguments
and loses its destination, and new blocks follow it:

| block | what it holds |
|---|---|
| `bbB` | the start: the call itself, `ext(args) -> bbH` |
| `bbH` | `_c = copy (*(*_C).cancel)`, then `switch move _c -> [true: bbT, false: bbD]`: the cancel exit |
| `bbD` | `_d = __saw_exec_offload_done(copy (*_F).[S: Int])`, the job's completion |
| `bbE` | `switch move _d -> [true: bbT, false: bbP]`: the completion exit, else the park |
| `bbP` ... | the offload park on the job `copy (*_F).[S: Int]` (the table above), whose park returns to `bbH` |
| `bbT` | the take: `dest = ext()`, which goes where the call returned |

The backend writes the start and the take, which never pend. The start
widens each argument into its word, `(*_F).[S + 8(J + 1)]` for argument J,
starts the job with the extern's thunk (`__saw_rt_offload_start`), and
records the job in `(*_F).[S]`; the take joins the job's thread
(`__saw_rt_offload_take`) and narrows the extern's result from the word it
returns into the destination. A thunk is synthesized once per offloaded
extern: it reads each argument back at its declared type and makes the
ordinary extern call (runtime/ABI.md, "Blocking-extern offload"). A wake
that finds the job running and the task not cancelled parks again, since
the take would hold the executor's thread in the C call; a cancelled task
takes all the same, waiting for the call, since the storage and every
pointer argument must outlive the job's thread (spec, the offload's
"Cancellation"). `__saw_exec_offload_done` and `__saw_exec_offload_pipe` are
the executor's half, which panics until SL:coroutines A14b lands.

Two cases are not offloaded. A `Thread.spawn` body is a `sync` item with no
frame (SL:architecture §3.8), so its `blocking` extern calls are plain calls:
whether such a call is a suspension source at all is decided in
`coro_call_is_source` once the form reaches this stage (SL-765). The
freestanding profile, which has no thread to offload onto, refuses a
`blocking` extern call in a framed body; sawc2 has no freestanding profile
yet, so the refusal has no fixture, and it keys on the profile at the
calls `coro_offloaded_extern` finds.

An op-budget point (SL:coroutines A9) charges the frame's op-budget counter
at offset K, which `bb0` starts at 128 first thing, since state 0 enters
there and no edge of the body does; a body whose entry block is a jump target
is an `INVARIANT` line. MIR opens each loop's body with its point, the last
statement of a block that ends in a goto to the body's first block `bbT`
(`compiler/tests/mir/README.md`), so an iteration that runs the budget out
cedes before its body runs, as the spec places it. A yield-capable point:

- the point becomes the charge, `(*_F).[K: Int] = SubWrapping(copy
  (*_F).[K: Int], const 1)`, then the test `_u = Le(copy (*_F).[K: Int],
  const 0)`, and the goto becomes `switch move _u -> [true: bbY, false:
  bbT]`;
- a new block `bbY` restarts the counter, `(*_F).[K: Int] = const 128`,
  records a ready park, `(*(*_C).park) = const 0`, and ends in the park,
  `call std.task.__saw_park_ready() -> [return: bbT] suspends`, a call of the
  ready park point by its declaration, which is the suspension point.

A charge-only point, inside a `borrows(sync)` window, becomes the charge
alone: it counts and never parks, so the next point that may yield does so
sooner. Every op-budget point of a body with no lowered frame is deleted,
since nothing outside a frame yields (SL:architecture §3.9). So a frame's
loops start 128 bodies between forced yields, counting from the frame's
start, and each forced yield comes before the body that runs the counter
out, as Stage 0's do (the run lane's `op_budget_interleaving`).

A read of the running task's cancel word is a call of std's
`__saw_cancel_requested`, by its lang role, or of a std function with no
parameters that returns that call's result and does nothing else, as
`cancelled()` does (`coro_cancel_read`). In a lowered frame its block gains
`dest = copy (*(*_C).cancel)`, the word through the task's context, and ends
in a goto where the call returned; the call is gone from the body, and the
frame gains the context local if it had none (golden `cancel_read`).
Outside a frame the call runs, and its body answers `false`, since no task
is running there; so does a call made in a sync helper a task calls, as in
Stage 0, where only a `cancelled()` written in a framed body reads the word.

Nothing else changes: no drop and no window close is added, since teardown is the body's
own, and the writes and the move-out are the transfers the call made. After
lowering, every drive is checked: its call carries no arguments and no
destination, its block writes each of the child's parameters (its slot read
from the child's frame) exactly once, and a call with a destination returns to its
move-out. A broken one is an `INVARIANT` line, which the unit program
`compiler/coro/tests/drive_invariant.saw` provokes by unlinking a write. The
resume function, `resume(frame, cx) -> Poll` (runtime/ABI.md, "The
compiler → executor boundary"), is the body's blocks behind a switch on the
state word: state 0 enters at `bb0`, state N re-enters suspension point N,
and the done state (-1) traps, since a driver that resumes a done frame has
lost track of it. A return records the done state and returns `Ready`. At a
suspension point, in place of its call:

- **a park**, of any reason, an op-budget point's yield among them, records
  its state and returns `Pending`, its record and arm having run in its
  blocks; re-entered, it continues to the call's return block;
- **a drive** starts the child at state 0 in its slot, then resumes it
  directly; while the child returns `Pending`, the frame records its state
  and returns `Pending` too, since the child's park wrote the root's word;
  once it is `Ready`, the call's return block follows, the move-out for a
  call with a destination. Re-entered, it resumes the child again.

A suspending `main`'s frame is driven by std's entry executor,
`__saw_exec_run_main(descriptor, frame)`, which the stage roots (mono's one
root after the worklist) only when `main` is lowered. The C entry puts the
frame on its own stack at state 0, hands it over with its descriptor, and
reads `main`'s result from the frame once the executor returns. The executor
runs every task `main` spawns beside it and closes the background group
before it returns; for a plain `main` that spawns, the C entry closes the
group after `main` returns.

### Spawn sites

A spawn site `dest = spawn FORM f(args)` (`compiler/tests/mir/README.md`) is
lowered, once every frame is laid out and before the frames are lowered, in
every item that holds one, framed or not, when its task root's frame is
lowered (`compiler/coro/src/spawn.saw`, whose docstring names its entry
points). The site's block keeps its spawn terminator, which loses its
arguments and now leaves the address of the task root's frame descriptor in
a new local `_D`: the descriptor is an item's, which no MIR operand names, so
the backend writes it there. Three new blocks, numbered after the body's own,
follow it:

- `_B = call __saw_exec_task_box(copy _D)`, the task's storage, sized and
  aligned by the descriptor;
- the task root's frame started in the box, `(*_B).[0: Int] = const 0` for
  its state word and `(*_B).[P: T] = arg` per argument into its parameter
  slot, each moving or copying as the site passed it; the form's provenance,
  `_P = TaskProvenance::Singleton`; then `_G = call __saw_exec_background()`;
- `dest = call H.__saw_spawn(copy _G, copy _D, copy _B, move _P)`, for the
  handle type H, which enqueues the box and mints the handle, then the
  site's own return edge.

A group site (golden `group_task_root`) adds two blocks, not three: its
group is the shared reference the site passes first, `_R`, so the writes go
into the handle's own block followed by `_G = cast(move _R as
UnsafePointer<TaskGroup>)` and `_P = TaskProvenance::Group`, with no call of
`__saw_exec_background`.

So the rewrite adds no ownership operation: the arguments travel as the site
passed them, and the handle lands where the site put it. Every lowered site
is checked: its spawn call carries no arguments and returns to the box, the
box returns to the writes, and the writes set the state word and each of the
root's parameters (its slot read from the root's frame) exactly once. A broken
one is an `INVARIANT` line.

### Drive sites

A drive site `[dest =] drive FORM f(args)` (`compiler/tests/mir/README.md`),
a test driver's call, runs its root to its end over a frame on the caller's
stack (`compiler/coro/src/drive.saw`, whose docstring names its entry
points). Its root is the root's task root, as a spawn site's is: mono keys it
apart from the ordinary item, and it is framed whether or not it suspends,
with its op-budget points live, as Stage 0 frames a driven root. A drive site
in an item that has a frame is refused (`coro.drive-in-suspending`, Rules,
below), so a lowered site is always in an item with none. It is lowered,
after the spawn sites, when its task root's frame is lowered, and the
site's call loses its arguments:

- the site's block gains, after its statements, the root's frame started in
  the storage a new local `_R` points at, `(*_R).[0: Int] = const 0` for its
  state word and `(*_R).[P: T] = arg` per argument into its parameter slot,
  each moving or copying as the site passed it. The storage is the
  backend's: an `alloca` of the root frame's size and alignment in the
  item's entry, whose address the entry stores into `_R`, so a drive
  allocates nothing;
- the drive terminator now leaves the address of the task root's frame
  descriptor in a new local `_D`, as a lowered spawn terminator does;
- a new block calls std's driver, `__saw_exec_drive(copy _D, copy _R, const
  SITE)` for `__saw_drive` and `dest = __saw_exec_drive_steps(copy _D, copy
  _R, const SITE)` for `__saw_drive_steps`, SITE naming the driver and the
  site's position;
- for `__saw_drive` with a destination, one more block moves the root's
  result out, `dest = move (*_R).[R: T]; goto -> bbN`, where the site
  returned. `__saw_drive_steps`'s driver drops the result through the
  descriptor's `drop_result`, since nothing takes it.

The driver resumes the frame with a context of its own, its park and cancel
words its locals, until the root returns, counting each `Pending`. A ready
yield is resumed at once, so a drive point never cedes to the run queue for
one (SL:coroutines §4, A4, t8); a timer park hands its wait to the
executor's shared sweep, which runs other tasks meanwhile and idles until
the earliest deadline, its own among them (A11, SL-645), and a park whose
wait the executor does not perform yet panics, naming the reason, SITE and
the unit that brings it. Every
lowered site is checked: its drive call carries no arguments and returns to
the driver's call, its block writes the state word and each of the root's
parameters (its slot read from the root's frame) exactly once, and a move-out
follows the driver when there is one. A broken one is an `INVARIANT` line.

**The `--lowered` record**, after an `INVARIANT` line per drive or spawn
site that fails its check, per lowered frame, in item order:

```
resume #K: NAME  (frame size S align A, pointer _F)
resume #K: NAME  (frame size S align A, pointer _F, context _C)
    state 0: bb0
    state N: bbB park ready | timer | fd | channel | offload
    state N: bbB drive #J CHILD at (*frame).[OFFSET]
    offload bbB start #J EXTERN, storage (*frame).[OFFSET]
    offload bbB take #J EXTERN, storage (*frame).[OFFSET]
    spawn bbB task root #J ROOT, descriptor _D, box _B
fn NAME -> T { ... }
```

then the lowered body as `sawc2 mir --dump` spells a function, frame slots
included. Then each item with no lowered frame that holds a lowered spawn or
drive site, in item order: a `spawner #K: NAME` line for one that spawns, a
`driver #K: NAME` line otherwise, its `spawn` lines, its `drive bbB task root
#J ROOT, descriptor _D, frame _R` lines, and its body.

## The verifier

The borrow check runs before this stage, so it never sees the paths lowering
makes; a verifier after lowering checks that lowering preserved what was
decided before it (SL:architecture §3.9, SL:coroutines A5). It is one funnel,
`compiler/coro/src/verify.saw`, whose docstring names its entry points, and
`coro_lower_for` runs it on every lowering, so `sawc2 build`, `--lowered` and
every lane that builds a program run it too. It recomputes every fact from the
MIR, and reads none of the lowering's own records (its points and resume
functions): only which frames are lowered, their layouts, and the target's size
of each slot's type.

The lowering rewrites places and calls in place, so just before it starts the
verifier records every body it may rewrite: each lowered frame's, and each one
holding a spawn or a drive site. For each it keeps every place and call as it
was, and each drop with its block; for a frame, also its suspension points,
numbered as its states are, with the initialisation analysis's conditions of
each local at each. Once the lowering is done, each recorded body is checked
against four rules, and a broken one is an `INVARIANT` line,
`verify rule N (NAME): `ITEM`: …`:

1. **frame in place.** A frame slot is only ever the second step of its place,
   right after the dereference of the local pointing at the frame, at an
   offset of at least 0, and no place dereferences that local without one, so
   the frame's bytes are never read, written or moved as a whole. A lowered
   frame's own pointer is the one such local its body never writes; it is used
   for nothing but its slots, and each slot's bytes, from its offset through
   its type's size, lie inside the frame. Each place the
   body named is either as it was or, for a frame value, its slot followed by
   its own steps, at one offset for all of the local's places, the offset its
   frame's layout gives it. No local is reached both in its slot and on the
   stack, the result and the parameters never stay on the stack (one the body
   never names is in the slot its layout gives it), and no index reads a
   frame value's local: an index by one is an index by a local the
   lowering added whose every write copies that value's slot. So nothing
   relocates a frame a loan points into.
2. **teardown by state.** At each suspension state, the conditions of each
   local, recomputed over the lowered body read with every place put back as
   it was, equal the ones recorded, and a local that may be initialised there
   lives in the frame, since a suspension loses the resume function's stack.
   So does the state record of each window that may be open there, or that
   the suspending call opens: the analysis never sees a record written, since
   its accessor's halves write it through a reference, so this is the check
   that can. An op-budget point's state is read at the ready park its block's
test of the counter yields at. Only an effect-only suspension
(`__saw_test_suspend`) and a read of the cancel word may leave the body, and
the read's destination is written once, by a copy of the word through the
task's context, last in a block going where the call returned.
   The drops are exactly drop elaboration's, each once, in the block it was
   placed in. A call that loses its arguments or destination is a child's
   drive, a park, a spawn site or a drive site; each operand it passed is used
   exactly once after lowering, a drive or a site's in a write into its
   parameter's slot, a drive's in its own block, which its state re-enters
   past. A drive's result is moved out of the child's result slot once, on its
   return edge, into the call's destination. An offload's start keeps its
   arguments, each used there alone, and loses its destination; it goes to a
   test of the cancel word whose true edge reaches the take, a call of the
   same extern with no arguments, the destination's one write, going where
   the call returned. Nothing else reaches into a
   child's frame, nothing reaches into an offload's storage but a read of its
   job word, and no place lowering adds reaches a frame value of the body
   itself but an index's load into its stack local. So lowering adds no
   ownership operation, and teardown at each state
   is the body's own.
3. **windows close once.** Every window a body opens is closed exactly once on
   every path, a resumed state's included: none opens while it may be open,
   none closes while it may already be closed, and none may be open at a
   `return`. An accessor's epilogue starts with the windows its prologue
   carries, which the prologue may leave open.
4. **record before arm.** Each park's record in the task's context, its park
   word and, for a timer, a descriptor or an offload, its deadline, reaches its
   park, and its arm when its reason arms the reactor, as one record on every
   path with no suspension since. The record holds its reason's value (0
   ready, 1 a timer, -1 a descriptor or an offload, the channel's operand for
   a channel), the deadline its park's bound or 0, and a descriptor park's arm
   registers the descriptor and direction the park was given. An armed park is
   entered only from its arm.

Each rule has a unit program that lowers a fixture of `inject/`, finds it
clean, edits the lowered MIR into a shape no lowering emits, and requires the
verifier's report naming the rule:

| rule | unit program | fixture | edit |
|---|---|---|---|
| 1 | `compiler/coro/tests/verify_frame_slots` | `teardown` | a drop's place loses its slot step, so it names the whole frame |
| 2 | `compiler/coro/tests/verify_teardown` | `teardown` | a drop of a frame-resident `String` is unlinked |
| 2 | `compiler/coro/tests/verify_window_records` | `window_records` | a window record open across a suspension is put back on the stack |
| 3 | `compiler/coro/tests/verify_windows` | `windows` | a window close returns to a second close of its window |
| 4 | `parks/verify_records` | `records` | a descriptor park's record moves past its arm |
| 1, 2 | `compiler/coro/tests/verify_zero_size` | `zero_size` | a drop's slot starts inside the frame and runs past its end; a statement copies a child's zero-size result slot, at that child's end and the frame's |

`records` parks on a descriptor, which no std module calls yet, so it is
lowered under the lane's copy of std, as the park goldens are; its unit
program sits under `parks/`, and the lane builds and runs it once that copy is
made, rather than `compiler/tests/run.py`'s unit step, which runs beside the
lane. The goldens, the run lane's programs and the census are the clean side:
their lowering is verified with every build.

## Rules

| rule | refuses | fixture |
|---|---|---|
| `coro.drive-in-suspending` | a drive site (`__saw_drive` or `__saw_drive_steps`) in an item that has a frame: one that suspends, as Stage 0 refuses it (DF-218n), or a task root, which runs inside an executor too; at the site, with Stage 0's message naming the root to call directly, where it embeds | `coro.drive-in-suspending`, from `tests/corpus/drive_site_in_suspending_body`; `function`, from `drive_site_in_suspending_function`; and `task-root`, a spawned body that never suspends |
| `coro.suspending-cycle` | a cycle of items that suspend, which has no finite frame since a callee's frame is embedded in its caller's by value; once per strongly connected component, naming the shortest cycle through its first item in item order, at that item's declaration, with the note that the refusal is pending SL-322's heap frames | `coro.suspending-cycle` and its variants, one from each of the eight recursion tests of `tests/corpus/errors/`, and `generic`, a cycle that suspends at one instantiation only |
| `coro.not-yet` | an item that needs a frame this compiler does not lower (Lowering, above), at its first suspending call that is not lowered, the chain through it in the message: each child it drives that is not lowered, then the source or the child that ends it, a child refused for a conditional window among them, so a frame holding a lowered park beside one that is not names the one that is not; failing a call, at the call its suspension was found through, naming the conditional window that is not lowered; only when no cycle is refused, and only the program's own items when any of them is refused, every std item that suspends being reached from one | `coro.not-yet`, a conditional window two calls down; `beside-a-lowered-park`, the drive of a child holding one beside a ready park; and `conditional-window`, a conditional window whose prologue suspends |
| `effect.sync` | a copy-policy `copy()` (`Copy` or `ExplicitCopy`, a written member) that suspends at its instantiation, at its declaration, naming its chain as Stage 0 does (`method Wrap.copy calls Slow.step → blocking extern usleep`): the compiler calls it at transfer sites no source names. Typecheck refuses one that suspends at every instantiation; this is the instantiation's half, decided per item | `effect.sync.copy-hook`, beside the run lane's `copy_hook_per_instantiation`, the same program built at `Fast` |

A refusal whose node lies in std or the builtin module is reported at the
nearest call the program writes on the chain of items that reached it, its
message naming the std position, as mono's are.

The recursion tests themselves reach this stage only once their vocabulary
does: `yield_now` and `__saw_suspend` (SL:coroutines A2), `__saw_drive` (A4b),
`Task.spawn` (A7a) and `group.spawn` (A8b). `spawn` and `group-spawn` have
their tests' own shape; each other fixture keeps its test's shape with a `blocking` extern as
the suspension and `main` calling the recursive function directly, and says
which form it stands in for.

## The lane

`coro_lane.py` checks that each golden program's `--dump` record equals its
`.coro` file, its `--layouts` record its `.layouts` file and its `--lowered`
record its `.lowered` file, byte for byte (`--write` rewrites them, for
review), with no `INVARIANT` line and no
refusal but this stage's; that each fixture in `refuse/` is refused first at
its header's position by the rule its name starts with, the refusal's
message holding each `// message:` line of its header, and every rule has a
fixture; and that `sawc2 coro --layouts` reports no `INVARIANT` line over the
mono lane's golden programs and the run lane's programs, which is where a
disagreement with typecheck would show, and lays out every frame they hold.
Every package under `modules/` is mapped with `--module-path` by its
directory's name. Last, it builds each unit program under `parks/` with
sawc2, against the new std and the stage packages, and requires it to exit 0
(see "The verifier"). Nothing in the lane runs Stage 0.

## The Stage 0 snapshot and the census

`stage0/` is Stage 0's behaviour on the corpus programs it frames at least
one function for, and on the coroutine refusal tests, recorded in the format
of `compiler/tests/oracle.py` with the target triple of each record:
`stage0/index.tsv` and `stage0/TRIPLE/PATH.stage0` for the programs (the
run, the frame layouts and the backtrace table), `stage0/refusals.tsv` and
`stage0/refusals/PATH.stage0` for the refusal tests. `census.py`, which
`compiler/tests/run.py` runs for information, reads it and never runs Stage 0:
it fails only when the snapshot is not whole, and counts the programs sawc2
builds and passes and the refusal tests it refuses by the plan's rule.
`stage0/snapshot.py --write` regenerates the snapshot with the v0 compiler,
which `oracle.v0_compiler` finds; nothing else does.

The layout goldens' frames are the first cut's (golden `yield_loop`, a loop
whose suspension carries values across it, and whose op-budget point gives
its frame a counter): the values each frame holds, and
their packed offsets. The `pack_` goldens are the packing's shapes:
sequential children (`pack_sequential`), exclusive `if` and `match` arms
(`pack_arms`), values in disjoint ranges (`pack_disjoint`), a move whose
destination and source never share a byte (`pack_move`), design 163's
synthetic call tree (`pack_tree`; Stage 0 lays its `root` out in 7,440
bytes) and the oracle sweep's `p2_layout`, four sequential children
(`pack_p2_layout`; 432 bytes in Stage 0). Golden `lifetimes` is the storage lifetimes, one
function per shape: a value live across one suspension only, a child slot
through its result's move-out, a window's record, an offload's storage, and
sequential children whose lifetimes are disjoint. Golden `drive_and_park` is the lowered shapes: drives
of children, two of one function among them, ready parks, and values across
both, reached through frame slots; the run lane builds and runs the same
shapes (`yield_main`). Golden `drive_arguments` is the drive of a child that
takes arguments, an `Int`, a `String` and a struct by value, and returns a
value, and the two test intrinsics, `__saw_suspend` parking and
`__saw_test_suspend` a goto; the run lane's `drive_arguments` and
`drive_test_suspensions` run those shapes. Golden `task_root` is the task
roots and the lowered spawn sites: a root that never suspends, a root that
does, and a function both spawned and driven, which is two items, spawned
from a plain `main`; the run lane's `task_spawn`, `task_spawn_and_embed` and
`task_handle_escaped` run spawned tasks. Golden `drive_site` is the lowered
drive sites: a root that suspends, one that never does, one also embedded,
and both forms over a result with a destructor; the run lane's
`coro_nested_suspend_two_deep`, `coro_drive_void_body`, `expr_suspend_return`,
`coro_unconsumed_result`, `coro_driven_match_move_out_releases_once`,
`drive_shapes`, `drive_ownership` and
`drive_sync_root` run them, and std's lane's `exec/drive_timer_park` pins a
drive point's timer park and its refusal of a park word that names no park.
Golden `windows` is borrow windows in lowered
frames: one held open across a suspension, its record a frame value across
that state; one on an accessor whose prologue and epilogue suspend, driven as
children at the open and the close; and one-statement windows between
suspensions, whose record stays on the stack. The run lane's
`coro_windows_beside_suspension` and `probes/coro_windows_held` run those
shapes. Golden `index_reads` is an index by a frame value, through its stack
local, which the run lane's `coro_index_read_from_frame` runs. Golden
`zero_size` is a zero-length array, which the backend cannot build yet, at a
frame's end, mid-frame, beside an index's frame value, as two parameters
sharing a slot and as a child's result at its caller's end, and a one-case
enum, which keeps its tag; the run lane's `probes/coro_zero_size_struct`,
`probes/coro_zero_size_void` and `probes/coro_zero_size_tuple` run an empty
struct, the `Void` payload of a `try!` and an empty tuple in those positions.
Golden
`op_budget` is op-budget points: yield-capable ones in a frame that also
yields and in a driven root that never suspends, a charge-only one inside a
`borrows(sync)` window, and the points deleted from a driver's own loop;
golden `cancel_read` is reads of the cancel word, in a frame and in a sync
helper. The run lane's `op_budget_counts`, `op_budget_loop_shapes_driven`,
`background_compute_preemption`, `taskgroup_compute_preemption`, `yield_main_loop` and
`background_task_spawn` run them.

Golden `offload` is the offload of `blocking` extern calls: one with no
argument and no result, and one taking a pointer into the frame, a narrow
integer and a Float, each with its storage in the frame and its start, its
cancel exit and completion exit to the take, and its park returning to the
cancel test, the re-park edge. Golden `chains` offloads in a function, a
method, a default body and an accessor's prologue. The run lane's
`probes/suspend_blocking_main` builds an offload and panics where the
executor's half, SL:coroutines A14b, is not here yet; the run pins come with
A14b.

The park goldens, `park_timer`, `park_fd`, `park_channel`, `park_offload`
and `park_signal`, are one park reason each (the ready park is
`drive_and_park`'s and the drive goldens'), with the record before the arm in
each lowered body; `park_fd` holds
both descriptor parks, and `park_signal` reaches its park through a watch's
`next`. A program cannot name a park point, and the std modules that will
call them are not ported yet, so every `park_NAME.saw` program is brought
under a copy of std, `.build/coro-lane/std/`, whose `task.saw` ends in
`parks/task_tail.saw`: public entry points to the park points, and a
`SignalWatch`. `park_timer` needs none of them and is brought the same way.
