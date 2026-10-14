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
  golden/                 NAME.saw, a program; NAME.coro, its frame decisions;
                          NAME.layouts, its frames' layouts; NAME.lowered, its
                          lowered frames' resume functions
  refuse/                 RULE.saw or RULE.VARIANT.saw, a program refused
  modules/                packages a fixture imports, one directory each
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
item #K: NAME  (frame no)
```

NAME is mono's dump name for the item (`compiler/tests/mono/README.md`), in
mono's item order. CHAIN is the item, then each item its suspension was found
through, then the source: `main -> caller -> nap -> usleep`. Each link is the
declaration's path inside its module (`ping`, `Walker.walk`), so the two
instantiations of a generic function name it alike, and an accessor's
prologue and epilogue both name the accessor. With `--layouts`, the record
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

An item **needs a frame** when it suspends; a task root will need one even
when it does not, and arrives with spawn lowering.

**Agreement with typecheck.** Where typecheck's summary of a body is
unconditional, the decision must agree with it at every instantiation: a
body typecheck says suspends suspends here, one it says never suspends does
not, and a closure body never suspends. A disagreement is an `INVARIANT`
line, not a refusal: one of the two stages is wrong.

## Frames

A frame is bytes with a layout, not a struct with glue (SL:coroutines §3.1).
What each item's frame holds is decided by one funnel,
`compiler/coro/src/frames.saw`, and where each value sits by another,
`compiler/coro/src/layout.saw`; each docstring names its entry points. No
frame is found when a cycle is refused, since none is finite then.

**Program points and suspension points.** An item's program points are each
statement and each terminator of its body, in block order. A call that
definitely suspends adds one more point after its terminator's: the moment
the call is suspended, its arguments taken and its destination not yet
written. The suspension points are those, and each yield-capable op-budget
point, which lowers to a yield in a framed item (SL:architecture §3.9). They
are numbered in block order from 1, the states the resume function re-enters
at; state 0 is the start.

**Storage lifetimes, first cut.** A local's storage lifetime is the set of
points just before which the initialisation analysis says it may be
initialised, whole or in part (`compiler/mir/src/initialisation.saw`), so it
runs through its scope-end drop, and a local that is moved is dead until it
is assigned again. A local only ever copied never stops being initialised, so
its lifetime runs to the end. That is conservative: unit B1 replaces it with
lifetimes that end at a last use and cover every loan into a value.

**What a frame holds**, in this order:

- the state word, an `Int`, live at every point;
- the result, `_0`, which the caller moves out after `Ready`;
- every parameter, the receiver and an environment included, which the
  caller writes into the frame before the first resume;
- every other local whose storage lifetime contains a suspension point, in
  local order;
- a child slot per suspending call to an item that needs a frame, in the
  order of the calls: the child's frame, embedded by value, live from the
  call, where the child starts, through its suspension point, where it is
  driven to `Ready`. Two calls of one function have a slot each.

Every other local stays on the resume function's stack. A resident local is
reached through a frame slot, `(*frame).[OFFSET: T]`, a MIR projection
(`compiler/tests/mir/README.md`). The frame has no drop glue: every drop stays
where drop elaboration placed it, at its MIR position. Window records join
the frame with the unit that lowers them (SL:coroutines A6).

**Layout.** Each value's size and alignment are the target's
(`compiler/target`), and a child slot's are its child's frame's, so frames
are laid out callees first. Two values interfere when their storage
lifetimes share a point. `coro_assign` takes the values and their
interference and gives each an offset; its policy is no sharing, each value
at the next offset its alignment allows after the one before, so packing
(SL:coroutines B2) changes that policy and nothing else. The frame's
alignment is its values' largest, and its size the end of its last value
rounded up to it. A frame holding a value the target cannot lay out, a child
frame that cannot be among them, gets no offsets.

**The `--layouts` record**, per frame, in item order:

```
frame #K: NAME  (size S align A)
    suspend N: bbB call LABEL
    suspend N: bbB budget
    (*frame).[OFFSET: T]  size S align A  state
    (*frame).[OFFSET: T]  size S align A  _L WHAT  (across N...)
    (*frame).[OFFSET: frame NAME]  size S align A  child  (across N)
    stack: _L...
```

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

- a ready park: a call of the ready park point (`std.task`'s
  `__saw_park_ready`, by its lang role), which `yield_now`'s body is, or of
  the test intrinsic `__saw_suspend`;
- a call of the test intrinsic `__saw_test_suspend`, a suspension for the
  effects alone (design 22): it frames its caller and runs as nothing;
- a call driving a child whose frame is lowered.

and it holds no op-budget point (A9), no borrow window (A6), and no
frame-resident local that an index projection reads, which a place cannot
name as a frame slot. Children are decided before their callers. Every other
item that needs a frame keeps `coro.not-yet` (Rules, below), so the backend
only meets lowered frames.

A lowered item's concrete body is rewritten in place: it gains one local,
the frame pointer `_F`, a `&var Int` pointing at the frame's state word, and
each place rooted in a frame-resident local `_L` becomes `(*_F).[OFFSET:
T]` followed by the place's own steps. A drive's call `dest = g(args)` in
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

A call of `__saw_test_suspend` becomes a goto where it returned. Nothing else
changes: no drop and no window close is added, since teardown is the body's
own, and the writes and the move-out are the transfers the call made. After
lowering, every drive is checked: its call carries no arguments and no
destination, its block writes each of the child's parameter slots (read from
the child's frame) exactly once, and a call with a destination returns to its
move-out. A broken one is an `INVARIANT` line, which the unit program
`compiler/coro/tests/drive_invariant.saw` provokes by unlinking a write. The
resume function, `resume(frame, cx) -> Poll` (rt/ABI.md, "The
compiler → executor boundary"), is the body's blocks behind a switch on the
state word: state 0 enters at `bb0`, state N re-enters suspension point N,
and the done state (-1) traps, since a driver that resumes a done frame has
lost track of it. A return records the done state and returns `Ready`. At a
suspension point, in place of its call:

- **a ready park** stores 0, the ready yield of the park word vocabulary,
  through the root token (`cx`'s first word), records its state and returns
  `Pending`; re-entered, it continues to the call's return block;
- **a drive** starts the child at state 0 in its slot, then resumes it
  directly; while the child returns `Pending`, the frame records its state
  and returns `Pending` too, since the child's park wrote the root's word;
  once it is `Ready`, the call's return block follows, the move-out for a
  call with a destination. Re-entered, it resumes the child again.

A suspending `main`'s frame is driven by std's entry executor,
`__saw_exec_run_main(descriptor, frame)`, which the stage roots (mono's one
root after the worklist) only when `main` is lowered. The C entry puts the
frame on its own stack at state 0, hands it over with its descriptor, and
reads `main`'s result from the frame once the executor returns.

**The `--lowered` record**, after an `INVARIANT` line per drive that fails
its check, per lowered frame, in item order:

```
resume #K: NAME  (frame size S align A, pointer _F)
    state 0: bb0
    state N: bbB park ready
    state N: bbB drive #J CHILD at (*frame).[OFFSET]
fn NAME -> T { ... }
```

then the lowered body as `sawc2 mir --dump` spells a function, frame slots
included.

## Rules

| rule | refuses | fixture |
|---|---|---|
| `coro.suspending-cycle` | a cycle of items that suspend, which has no finite frame since a callee's frame is embedded in its caller's by value; once per strongly connected component, naming the shortest cycle through its first item in item order, at that item's declaration, with the note that the refusal is pending SL-322's heap frames | `coro.suspending-cycle` and its variants, one from each of the eight recursion tests of `tests/corpus/errors/`, and `generic`, a cycle that suspends at one instantiation only |
| `coro.not-yet` | an item that needs a frame this compiler does not lower (Lowering, above), at its first suspending call that is not lowered, the chain through it in the message: each child it drives that is not lowered, then the source or the child that ends it, so a frame holding a lowered park beside one that is not names the one that is not; failing a call, at the call its suspension was found through, naming the budget point, window or index that is not lowered; only when no cycle is refused, and only the program's own items when any of them is refused, every std item that suspends being reached from one. And every spawn site (`compiler/tests/mir/README.md`), at its form, whatever its root does, until spawn lowering gives each its task root (SL:coroutines A7a): lowering one as a call of its root would run the task's body in the spawner | `coro.not-yet`, `beside-a-lowered-park`, and `spawn-site`, whose root never suspends |
| `effect.sync` | a copy-policy `copy()` (`Copy` or `ExplicitCopy`, a written member) that suspends at its instantiation, at its declaration, naming its chain as Stage 0 does (`method Wrap.copy calls Slow.step → blocking extern usleep`): the compiler calls it at transfer sites no source names. Typecheck refuses one that suspends at every instantiation; this is the instantiation's half, decided per item | `effect.sync.copy-hook`, beside the run lane's `copy_hook_per_instantiation`, the same program built at `Fast` |

A refusal whose node lies in std or the builtin module is reported at the
nearest call the program writes on the chain of items that reached it, its
message naming the std position, as mono's are.

The recursion tests themselves reach this stage only once their vocabulary
does: `yield_now` and `__saw_suspend` (SL:coroutines A2), `__saw_drive` (A4),
`Task.spawn` (A7c types it, and A7d lowers its site) and `group.spawn`
(A8b). Each fixture keeps its test's
shape with a `blocking` extern as the suspension and `main` calling the
recursive function directly, and says which form it stands in for.

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
directory's name.

The layout goldens' frames are the first cut's (golden `yield_loop`, a loop
whose suspension carries values across it): the values each frame holds, and
offsets with no sharing. Golden `drive_and_park` is the lowered shapes: drives
of children, two of one function among them, ready parks, and values across
both, reached through frame slots; the run lane builds and runs the same
shapes (`yield_main`). Golden `drive_arguments` is the drive of a child that
takes arguments, an `Int`, a `String` and a struct by value, and returns a
value, and the two test intrinsics, `__saw_suspend` parking and
`__saw_test_suspend` a goto; the run lane's `drive_arguments` and
`drive_test_suspensions` run those shapes.
