# compiler/tests/borrowck: the borrow check's corpus

The corpus the borrow check (`compiler/borrowck`, package `sawborrowck`,
SL-460) is held to. This file specifies `sawc2 borrowck`'s records and dump,
the initialisation analysis it shares with the MIR verifier, the rules it
refuses by, and the drop labels it exports for drop elaboration. Today it is
the check's initialisation half (U6d1); loans and conflicts are U6d2's.

```
borrowck/
  README.md          this specification
  CONFORMANCE.md     every borrow-check row of examples/conformance/INDEX.md, and its owner
  borrowck_lane.py   the lane compiler/tests/run.py runs
  golden/            NAME.saw, a program, and NAME.borrowck, its expected record
  refuse/            RULE.saw or RULE.VARIANT.saw, a program the check refuses
  differential.tsv   the tests/corpus move errors the check does not refuse, and why
```

## `sawc2 borrowck`

```sh
.build/sawc2 borrowck (--dump | --check) [--notes] [--std-root DIR]
                      [--module-path NAME=DIR]... [FILE | @LIST]...
```

Each FILE is the entry of its own program, which is resolved, type checked,
lowered, then borrow checked. Each entry gets one record, starting with the
line `FILE<TAB>path`, holding in order:

- everything `sawc2 mir --check` prints for it (`compiler/tests/mir/README.md`);
- one `ERROR<TAB>rule<TAB>file:line:col<TAB>message` line per refusal of the
  borrow check, in the order its functions were checked;
- one `INVARIANT<TAB>module<TAB>message` line per problem its verifier finds;
- with `--dump`, the dump of each module checked in full, in load order.

The exit code is 1 when any program has a refusal, 2 on a usage failure, and 0
otherwise. Every function the MIR stage lowered and refused nowhere is
checked.

## The initialisation analysis

`compiler/mir/src/initialisation.saw` (`init_analysis`) is a forward dataflow
over one function's blocks, per move path. It is the one answer to "which
parts of this local are still initialised": the MIR verifier asks it for its
move-path invariants, and the borrow check for its refusals and its labels.
No other dataflow over moves exists.

A **move path** is a local, or a path inside one through fields, tuple
elements and payloads. A payload downcast, `(_3 as Err).0`, is a path like a
field, and its `!` form is the same path. A place that reaches through a
reference or an index stops at the path before it: an access through it
reads that path and changes nothing.

On one execution path, each move path is in exactly one **condition**:

| letter | condition |
|---|---|
| `U` | unassigned: not yet written (only a local before its first assignment) |
| `W` | whole |
| `P` | partial: written, then a part of it moved out |
| `M` | moved: it, or a path around it, moved out |
| `D` | dropped: it, or a path around it, dropped |

The analysis keeps, per path, the set of conditions some execution path
reaching the point leaves it in. A join is a union, so a single letter is a
definite fact: **definitely initialised** is `W` alone, **moved** is a set
with no `W` and no `P`, and anything else is **maybe initialised**. At the
entry, the parameters are `W` and every other local `U`.

Each statement and terminator is a run of **accesses** in evaluation order:
an assignment's operands (a `copy` reads, a `move` moves), the place a `ref`
borrows, its target's index locals, then its target, which it writes; a
drop's place; a switch's operand or place; a call's function value, its
arguments, then its destination. An access does this to the conditions:

- a **move** leaves its path and every path inside it `M`, and turns each
  path around it from `W` to `P`;
- a **write** leaves its path and every path inside it `W`. A write to a part
  of a `P` path leaves that path `P`: the part written need not be the one
  that left. A whole-referent replacement through a `&var`, `(*_1) = v`,
  reaches through a reference, so it is a read of `_1`, never a move;
- a **drop** leaves its path and every path inside it `D`;
- a read, a borrow, and any access through a reference or an index change
  nothing.

An accessor's state record carries a local that owns something and is not
definitely whole at some `lend` with a drop flag (`compiler/tests/mir/README.md`,
"Accessors"). Its two record statements are accesses of their own:

- the prologue's `(*_1).K = move _L` is a **transfer** of `_L`: it acts as a
  move, but the borrow check reports no use of it, since the local may already
  be gone and its flag says whether it was;
- the epilogue's `_L = move (*_1).K` is a **resume** of `_L`: it leaves the
  local and every path inside it `W M`, maybe initialised, so its drop is
  `flagged` and a use of it in the epilogue after a move in the prologue is
  still a use after move.

## Rules

| rule | refuses | fixtures |
|---|---|---|
| `move.use-after` | a read, a borrow, a move or a call through a place that may have been moved, or a part of which may have been moved out (`M` or `P`); a write to a part of a place that may have been moved whole | `move.use-after`, `.double`, `.loop`, `.branch`, `.field-init`, `.force`, `.consumed`, `.partial`, `.while-condition` |
| `consumes.some-paths` | a `consumes` method's receiver, or a field of it, moved out on some paths to a `return` and left on others (spec, Moving a field out); a path that diverges reaches no `return`, so it is exempt | `consumes.some-paths` |

The error stands at the use; its message names where the move happened,
the nearest move of the place, of a place around it or of a part of it that
reaches the use. Positions are the statement's or terminator's source node
(`compiler/tests/mir/README.md`, "Source nodes"). A use is reported once per
source node.

A `consumes` body with a field moved on some paths only is the user's error,
not the lowering's, so the MIR verifier does not check its move paths
(`init_consumes_partial`). Its release, the fields no path moves out, is
then short on the paths that keep a field; the refusal is what stops that
from reaching code.

### Who refuses a partial move

The borrow check works on MIR, where a consuming destructure moves parts out
of a temporary by design (`dissolve`), so it does not judge whether the
source may move a part out. It checks only the consequences: no use, borrow
or whole drop of a place after a part of it left, and each `consumes` field
leaving on every path or on none.

| rule | owner |
|---|---|
| a field, element or payload moved out of a binding, `move p.x`, `move v[0]` | typecheck, SL-462 (refused nowhere yet) |
| moving out through a reference, or out of a borrowed match payload | typecheck, SL-462 (refused nowhere yet) |
| `move self.f` or `move self` outside a `consumes` method | typecheck, `consumes.move-self` |
| `move self.f` deeper than one field | MIR lowering, `slice.not-yet` (`consumes-deep-move`) |
| `move self` whole in a `consumes` body | MIR lowering, `slice.not-yet` (`consumes-whole`) |
| a `consumes` field moved on some paths to a return only | the borrow check, `consumes.some-paths` |
| a use of `self` after `move self.f` | the borrow check, `move.use-after` |

Until SL-462 lands, a user's `move p.f` of an owning field reaches the MIR
verifier as an `INVARIANT` (the whole drop after a part left), and one of a
trivially copyable field is lowered as a copy and refused by nothing.

## Drop labels

Every drop a path reaches is labelled in the side table drop elaboration
reads (`BorrowckProgram.labels`, by statement), from its place's conditions
just before it (SL:architecture §3.7):

| label | conditions | drop elaboration |
|---|---|---|
| `static` | `W` alone | a plain drop |
| `elided` | no `W`, no `P` | nothing |
| `flagged` | anything else | a drop under a flag |

A drop through a reference or of a static is `static`. A `P` drop is
`flagged`, and is also the MIR verifier's whole-drop invariant: valid MIR has
none.

## The dump

A module's dump is the line `module IDENTITY`, then each function checked, in
the MIR dump's order:

```
fn NAME {
    place PATH: TYPE;  // NAME
    ...

    bbK: {
        [C C ...] STATEMENT;
        [C C ...] drop(PLACE);  // LABEL
        [C C ...] TERMINATOR;
    }

    bbK: unreached
}
```

- NAME is the MIR dump's.
- Each `place` line is a move path whose type owns something a drop releases
  (the MIR's owned places), spelled as the MIR dump spells a place, with the
  name a diagnostic gives it.
- Each statement and terminator is the MIR dump's, after a bracket holding,
  for each place listed, its conditions just before it, as letters in the
  order `U W P M D`; a drop ends in its label.
- A block no path reaches is `unreached`.

## The verifier

`compiler/borrowck/src/verify.saw` runs on every function checked, and fails
loudly, naming the function and the statement, on:

- a block a path reaches with no initialisation state for every path;
- a drop a path reaches with no label, a label on a statement that is no
  drop, or on one no path reaches;
- a label other than the one its place's conditions give at the drop,
  re-derived from the shared analysis, in either direction.

The independent oracle for the labels is the Air's drop-after-move checker,
which reads `sawc2 mir --dump` and shares nothing with either client: every
drop-after-move site it lists must be labelled `elided` or `flagged`.

## The lane

`borrowck_lane.py` checks the conformance matrix (every row of the five
sections, each with an owner, every path it names existing, every row the
borrow check owns naming a fixture or golden here); that each golden's record
equals its `.borrowck` file byte for byte (`--write` rewrites them); that each
refusal fixture is refused first at its header's position (`--fill` writes a
`// refuses: TODO` header), with no `INVARIANT` under `sawc2 borrowck` and
neither an `ERROR` nor an `INVARIANT` under `sawc2 mir`, and that every rule
has a fixture; that the compiler's own source, the sawc2 build and each unit
program, and the new std's entry under `--std-root std`, check with no
refusal and no invariant; and the differential: every tests/corpus program
whose expected diagnostic names a move is refused by a borrow-check rule, or
`differential.tsv` says why not. It counts the drop labels over the sawc2
build and over tests/corpus, for information.

| aspect | golden |
|---|---|
| straight-line moves | moves |
| branches and joins | branches |
| loops: a move used again on the backedge, a revived condition move | loops |
| early exits: `return`, `break`, `try` | exits, loops |
| `consumes` field moves: every path, none, a diverging path | consumes |
| re-initialisation, a whole-referent replacement through `&var` | reinit |
| a closure capturing by `move` | closures |
| a dissolve under `try`, `??`, `if let`, `guard let`, `while let`, `for`, a binding `match` arm | dissolves |
| the drop labels | every golden |
