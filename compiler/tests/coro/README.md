# compiler/tests/coro: coroutine lowering

Coroutine lowering (`compiler/coro`, package `sawcoro`, SL:coroutines §3.1)
is the stage between mono and the backend. This file specifies `sawc2 coro`'s
records, the suspension decision, the rules it refuses by, and the lane. The
stage decides, per item, whether it needs a frame; frames, the resume
function and `park` arrive with the units after it (SL:coroutines §4), and
until then every item that needs a frame is refused.

```
coro/
  README.md               this specification
  coro_lane.py            the lane compiler/tests/run.py runs
  golden/                 NAME.saw, a program; NAME.coro, its frame decisions
  refuse/                 RULE.saw or RULE.VARIANT.saw, a program refused
  modules/                packages a fixture imports, one directory each
```

## `sawc2 coro`

```sh
.build/sawc2 coro (--dump | --check) [--notes] [--std-root DIR]
                  [--module-path NAME=DIR]... [FILE | @LIST]...
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
prologue and epilogue both name the accessor. The exit code is 1 when any
program has a refusal or an invariant, 2 on a usage failure, and 0
otherwise. `sawc2 build` runs this stage, and prints its record when it
refuses (`compiler/tests/run/README.md`).

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

## Rules

| rule | refuses | fixture |
|---|---|---|
| `coro.suspending-cycle` | a cycle of items that suspend, which has no finite frame since a callee's frame is embedded in its caller's by value; once per strongly connected component, naming the shortest cycle through its first item in item order, at that item's declaration, with the note that the refusal is pending SL-322's heap frames | `coro.suspending-cycle` and its variants, one from each of the eight recursion tests of `tests/corpus/errors/`, and `generic`, a cycle that suspends at one instantiation only |
| `coro.not-yet` | an item that needs a frame, since no frame is lowered yet, at the call its suspension was found through, its cause chain in the message; only when no cycle is refused, and only the program's own items when any of them needs a frame, every std item that suspends being reached from one | `coro.not-yet` |

A refusal whose node lies in std or the builtin module is reported at the
nearest call the program writes on the chain of items that reached it, its
message naming the std position, as mono's are.

The recursion tests themselves reach this stage only once their vocabulary
does: `yield_now` and `__saw_suspend` (SL:coroutines A2), `__saw_drive` (A4),
`Task.spawn` (A7c) and `group.spawn` (A8b). Each fixture keeps its test's
shape with a `blocking` extern as the suspension and `main` calling the
recursive function directly, and says which form it stands in for.

## The lane

`coro_lane.py` checks that each golden program's `--dump` record equals its
`.coro` file byte for byte (`--write` rewrites them, for review), with no
`INVARIANT` line and no refusal but this stage's; that each fixture in
`refuse/` is refused first at its header's position by the rule its name
starts with, the refusal's message holding each `// message:` line of its
header, and every rule has a fixture; and that `sawc2 coro --check` reports
no `INVARIANT` line over the mono lane's golden programs and the run lane's
programs, which is where a disagreement with typecheck would show. Every
package under `modules/` is mapped with `--module-path` by its directory's
name.
