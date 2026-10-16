# compiler/tests/drops: drop elaboration's corpus

The corpus drop elaboration (`compiler/drops`, package `sawdrops`, SL-468) is
held to. This file specifies `sawc2 drops`'s records and dump, the elaborated
MIR, its flags, the glue resolution it records, the rule it refuses by, and
the verifier that runs after it.

```
drops/
  README.md          this specification
  drops_lane.py      the lane compiler/tests/run.py runs
  golden/            NAME.saw, a program, and NAME.drops, its expected record
  refuse/            RULE.saw or RULE.VARIANT.saw, a program refused, or a due row
  inject/            NAME.saw, a program a unit program elaborates, then edits
  conformance.tsv    the conformance rows drop elaboration owns, and their summaries
```

## `sawc2 drops`

```sh
.build/sawc2 drops (--dump | --check) [--notes] [--std-root DIR]
                   [--module-path NAME=DIR]... [FILE | @LIST]...
```

Each FILE is the entry of its own program, which is resolved, type checked,
lowered, borrow checked, then elaborated. Each entry gets one record,
starting with the line `FILE<TAB>path`, holding in order:

- everything `sawc2 borrowck --check` prints for it
  (`compiler/tests/borrowck/README.md`);
- when nothing there is an `ERROR` or an `INVARIANT` line, the program is
  elaborated, and the record goes on with one
  `ERROR<TAB>rule<TAB>file:line:col<TAB>message` line per refusal of drop
  elaboration, then one `INVARIANT<TAB>module<TAB>message` line per problem
  elaboration met or its verifier finds;
- with `--dump`, the dump of each module elaborated, in load order.

MIR some verifier found a problem in is not elaborated: the drops it holds
are not the ones the program owes. The exit code is 1 when any program has a
refusal, 2 on a usage failure, and 0 otherwise.

## Elaboration

Every `drop(p)` a path reaches is elaborated by the label the borrow check
gave it (`compiler/tests/borrowck/README.md`, "Drop labels"), read off the
shared initialisation analysis; nothing here derives initialisation again:

| label | elaborated as |
|---|---|
| `static` | `drop(p);`, unconditional |
| `elided` | nothing |
| `flagged` | `switch copy _F -> [true: bbD, false: bbC];`, then in bbD `drop(p);` and the flag cleared, `goto -> bbC;` |

A drop in a block no path reaches is removed, with the rest of that block
kept.

A **drop flag** `_F` is a `Bool` local that mirrors whether its path is
whole. Flags are created only for the paths a flagged drop names, and for an
accessor's record locals that carry one across its split (below), and are
numbered after the function's locals, but for a take flag, which MIR made and
elaboration adopts (below); the dump's note names the path, `// flag _3`. bb0 starts by setting each flag from the entry's conditions (a
parameter's path is whole there). After each statement, and before each
terminator, every flag whose path its accesses change is updated: set where
the path becomes whole, cleared where it stops being, by the net effect of
the accesses in order. The effect is the analysis's own transfer
(`drops_flag_effect` in `compiler/drops/src/program.saw` runs `apply` on the
two extreme states), so a flag is set at an assignment, cleared at a move or
a drop, and kept by a read, a borrow or a write through a reference. A flag
lives across a suspension like any other local; the coroutine frame builder
carries it.

**Take flags.** A local a non-escaping closure's `[move v]` takes
(`compiler/tests/mir/README.md`, "Takes") already has a flag: the take flag
MIR made at the capture, which the closure body clears when it takes the
value. Elaboration adopts it as that path's drop flag before it makes any
other, so the body and the guarded drop read one flag, and two takes of one
path naming two flags are an `INVARIANT`. It is written like any other flag
(set in bb0 from the entry's conditions, set at each assignment), except at
the take itself, which keeps it: the analysis leaves the path `W M` there, and
the flag's value passes to the closure. The drop at the local's scope end is
`flagged`, so it comes out as `switch copy _F -> [true: bbD, false: bbC]`,
then `drop(_L); _F = const false;` in bbD. The dump notes an adopted flag
like any other, at its own place among the locals.

**Partial paths.** The MIR already decomposes a value whose parts left: a
consuming destructure drops each owned part it does not move (`leftovers`),
and a `consumes` body's release drops each field, a drop the borrow check
elides where the field left (`compiler/tests/mir/README.md`). So elaboration sees drops of parts, each
elaborated by its own label, and never a whole drop of a partly moved place
in valid MIR; a flagged drop of one is reported as an `INVARIANT` and
elaborated to nothing. The every-path-or-none rule (`consumes.some-paths`)
makes a `consumes` field's release static, so a flag on a consumed receiver
or a field of it is an `INVARIANT` too. A `match`, `if let` or `while let`
drops its leftovers on each exit of its body rather than at the
destructure, and no path between can make a leftover anything but whole,
so those drops are `static` too and need no flag (golden `leftovers`).

**Order.** A drop never moves: scope exits drop in reverse declaration order
and a statement's temporaries in reverse creation order, as the MIR placed
them, and a guarded drop keeps its place. The binding a same-scope
redefinition replaces is the MIR's to release at the redefinition, once the
new binding holds its value and before the statement's temporaries, and its
scope's exits drop it nowhere else; that drop takes its label like any other,
so an initializer that moved the old binding leaves it elided, and one that
moved it on some paths leaves it flagged (golden `redefinitions`, spec,
Shadowing). A borrowing struct a `for` head
lends is registered with the loop's scope after the window it is lent in, so
it is destroyed before that window closes, on every route out, and a `deinit`
may still read through its reference (golden `borrowing_struct`).

**Panic does not unwind.** `__saw_rt_panic` writes its message and exits, so
elaboration generates no cleanup path, and a path that diverges reaches no
`return`: the verifier's "destroyed exactly once on every path to a return"
excludes it, which is what makes its leak check sound.

## Accessors

A local an accessor's state record carries, and that is not definitely whole
at some `lend`, has a flag field in the record
(`compiler/tests/mir/README.md`, "Accessors"). The prologue writes that field
from the local's flag, `(*_1).K = copy _F;`, just before the transfer that
moves the local into the record; the epilogue reads it back,
`_F = copy (*_1).K;`, just after the resume that loads the local, when the
epilogue needs a flag for it. The local's drop at the end of the body is then
guarded by the flag, at scope end after the epilogue, where Stage 0 runs it.

## Glue resolution

Elaboration decides where a drop happens; what a drop does for a type is the
type's glue, generated once per concrete type at monomorphization
(SL:architecture §3.8). After its blocks, each function's dump lists, sorted,
`glue TYPE: RESOLUTION` for each type it drops:

| resolution | for |
|---|---|
| `deinit TARGET in the TRAIT conformance, then structural` | a type whose extension writes `deinit`, found whatever bound the conformance declaring it carries: the copy policy is the type's for every argument |
| `structural` | its fields in reverse declaration order, an enum's active payload, a tuple's or array's elements, an Optional's or Result's payload |
| `closure environment` | a closure value |
| `builtin` | a vocabulary type Stage 0's compiler supplies the glue of (`String` under Stage 0's root) |
| `per instantiation` | a type mentioning a type parameter, never guessed |
| `trivial` | a type that owns nothing (no drop names one) |

## Fates

A handle a singleton spawn form mints must reach `join()`, `detach()` or
`cancel()` on every path (spec, *No implicit fates*). The obligation follows
the FORM, not the type: `group.spawn` mints the same `Task<T>`, and its
handle may be dropped (golden `fates_group`). So it is the spawn site that
owes it, `mir_owes_fate` over the MIR's spawn terminator (`compiler/tests/mir/README.md`), and no type
or lang role carries it. Where a site owes one is decided by one funnel,
`mir_mint_obligation` (`compiler/mir/src/model.saw`), whose docstring names
its entry points: `Task.spawn`'s lowering now, and `Thread.spawn`'s with
SL:coroutines A18.

The check, `check_fates` (`compiler/drops/src/elaborate.saw`), follows each
handle's VALUE rather than a binding's name, forward over the borrow-checked
MIR to a fixpoint, before elaboration rewrites it. Per local it holds the
site whose handle the local may hold, on some path, with no fate written:

- a call of `join`, `detach` or `cancel` of `Task` or `VoidTask` whose
  receiver borrows the local whole writes the fate;
- a move into another local carries the handle, whole or as a part of what
  the assignment builds: a struct, a case, a tuple, a closure's environment;
- a move into storage whose owner declares a hand-written `deinit` (an
  assignment into a field, an element or a referent of it, or an argument of
  a method whose receiver borrows it) discharges the obligation: that
  `deinit` is the fate, and the handle's run-time panic backstops one that
  forgets (spec: *No implicit fates*; `conformance/K86`).

Every other way out is refused, once per site, at the site: an implicit
drop (a scope's end, a statement's end, an overwrite), a move into the return
place, into storage whose owner declares no `deinit`, into a call's
argument, or a take capture. A handle no binding ever held is reported as
discarded where it is made. The check reads and adds nothing, so a program it
accepts elaborates exactly as before (golden `fates`).

**The escape matrix**, each row against Stage 0's spawn-obligation funnel
(`sawc/typechecker/types.py`), each cell probed with both compilers:

| route | sawc2 | Stage 0 |
|---|---|---|
| a bare statement, `let _ =` | refused, discarded | refused, discarded |
| bound, dropped on some path (a branch, a loop iteration, an early `return`) | refused | refused |
| `return` of a bound handle, or of a spawn as a tail | refused | refused |
| moved into a struct literal, a tuple, an `Optional`, a capture | refused at the carrier's drop | refused |
| assigned into a field of a type with no `deinit` | refused | refused |
| assigned into a field of a type that declares a `deinit` | discharged, the run-time panic backstops | discharged |
| pushed into a `Vector` (which declares a `deinit`) or a `deinit`-owning field's collection | discharged | discharged |
| moved into a function's argument | refused | refused |
| a struct literal of a type that declares a `deinit` | refused at the carrier's drop | refused |
| moved into another local, then given a fate there | accepted | **refused**: Stage 0 keys the obligation on the first binding's name |
| a fate on each arm of an `if` | accepted | **refused**: Stage 0 undoes a consume made inside a nested block on the way out, though every arm consumed |
| a fate written, then the handle moved and dropped | accepted | accepted |
| `Task.spawn(f()).join()` | accepted | accepted |

The two divergences are both cases sawc2 accepts and Stage 0 refuses; each
follows from the check being per path and per value, as the spec states it.
A handle reached through a reference (`let r = &t; r.join()`) or a field
(`k.held.join()`) writes no fate the check sees, so the handle's local, or
its carrier, is refused at its drop: conservative, as Stage 0 is.

## Rules

| rule | refuses | fixture |
|---|---|---|
| `drop.must-consume` | a spawn handle that leaves the check with no fate written (above) | `drop.must-consume`, a bound handle never consumed, and its variants: `branch` (consumed on one branch), `bare` and `let-underscore` (the two discard spellings), `return`, `argument`, `field` (into a struct the check follows), `storage` (into a field of a type with no `deinit`), `capture` |

A **due row** starts `// due: NAME when CONDITION`, then `// refuses: RULE
at L:C`, the refusal standing in its way today. The lane holds it to that
refusal, and fails once the refusal is lifted, so the row cannot land
silently. NAME is a rule of `drops_rules`.

## The dump

A module's dump is the line `module IDENTITY`, then each elaborated function
in the MIR dump's order, printed as the MIR dump prints one
(`compiler/tests/mir/README.md`), its flags noted `// flag PLACE`, then a
blank line and its `glue` lines when it drops anything.

## The verifier

`compiler/drops/src/verify.saw` runs on every function elaborated. It solves
the output with the shared analysis's accesses and transfer, refined by the
one fact elaboration adds, that the false edge of a switch on a flag leaves
the flag's path, and every path inside it, not whole; the flag checks make
that fact sound. It fails, naming the function and the block, on:

- a drop with no label: each is plain or guarded by a flag;
- a plain drop of a path some path leaves not whole, which covers a second
  drop; a guarded drop of a partly moved path, or in a block its flag's true
  edge does not alone enter;
- a switch reading a flag some path has not set;
- a `return` where an owned local, or an owning field or element of a
  partly moved one, may still be whole, or where an owning field of a
  `consumes` body's receiver may: its fields are read from its type, so a
  field the release names nowhere is seen too, whole wherever the receiver
  is whole or partly moved;
- a flag not starting as its path's entry conditions give, a statement that
  changes its path not followed by the matching update before the path is
  touched again, a terminator whose update does not stand before it, or a
  constant update where its path does not change: one no change before it
  explains and the terminator after it does not owe, such as a flag cleared
  without its move, which would make the false edge's fact unsound;
- a flag on a `consumes` body's receiver or a field of it;
- a prologue `lend` that writes its record but not every flag field.

The verifier reads no text, so each rejection that matters is pinned by a unit
program that elaborates a fixture of `inject/`, edits it, and requires the
report: `compiler/drops/tests/verify_flags.saw` turns the move a flag's clear
stands for into a copy, and `compiler/drops/tests/verify_consumed.saw`
removes a consumed receiver's drop of a refilled field, then of a field only
that drop names.

**A limit: the leak check does not follow enum payloads.** At a `return` it
follows a partly moved value's fields and tuple elements, never a payload
path. The analysis keeps every case's payload paths, and only one case is
active at run time; after a join, a case another path never entered looks
whole, so following them would refuse every match whose arms take parts of
different cases. An owning payload a lowering failed to drop beside a payload
it moved out therefore escapes this check: MIR's `leftovers`, which drops every
owned part a destructure does not take, is what rules it out, and §3.8 must
not read this verifier as covering it. `compiler/drops/tests/leak_payloads.saw`
pins the limit: it unlinks the drop of the payload `first_name` leaves in
`inject/payloads.saw` and requires the verifier to stay silent, so the program
fails, and becomes a rejection pin, once the limit is closed.

## The lane

`drops_lane.py` checks that each golden program's record equals its `.drops`
file byte for byte (`--write` rewrites them; a first line `// flags: ...`
passes flags, and under `--std-root` the expectation holds the entry module's
dump alone); that each fixture in `refuse/` is refused first at its header's
position, a due row by the refusal in its way, and every rule has a fixture;
that the compiler's own source, the sawc2 build and each unit program, and
the new std's entry under `--std-root std`, elaborate with no refusal and no
invariant; that every tests/corpus program that elaborates does so with no
invariant; and that every conformance row CONFORMANCE.md gives `§3.7` names a
fixture here and its program in `conformance.tsv` gives the summary recorded
there. It counts the drop flags over the sawc2 build and over tests/corpus.

| aspect | golden |
|---|---|
| straight-line, static and elided only | straight |
| a conditional move: a flag set and cleared | conditional |
| a loop moving on some iterations | loops |
| early exits: `return`, `break`, `continue`, `try` | exits |
| the catch forms' edges: a `try` leaving a `try` block's body through its scopes, a value moved on some paths before it dropped under its flag; the catch block's `error` dropped as the block ends or a `return` leaves it; an inline catch's payload moved out and its `error` dropped with its block | catches |
| a dissolve under each consuming form: part drops | dissolves |
| what a `match`, `if let` or `while let` leaves over, static, on each exit of its body: the arm's end, a `return`, across a suspension, per iteration and on `break` | leftovers |
| a `consumes` body: field release, a field moved out and assigned again released with it, no flag | consumes |
| a same-scope redefinition: the binding it replaces released there, static, elided or flagged, before the statement's temporaries; by `let`, a destructuring `let` and `guard let`; per iteration in a loop; a closure's own bindings redefined and its parameter shadowed | redefinitions |
| statement temporaries in reverse creation order; one on a short circuit's right side, or `??`'s, dropped on that side before the sides join, unflagged, in a loop too | temporaries |
| drops inside a window's body before its close; a `for` over a borrowing struct | windows |
| a borrowing struct that owns something, built with `lends self`, destroyed before its window closes | borrowing_struct |
| glue: `deinit`, structural, closure environment, builtin, per instantiation | glue |
| an escaping closure's captures, released once by the environment, never by a call; each closure kind and capture kind | captures |
| the same over a type parameter: unbounded read in place, `ExplicitCopy`'s `copy()` at creation, `Copy` copied; a `Copy` hand-off through a reference | generics |
| glue under the new std: `Vector<Token>` and `Vector<Int>` | glue_std |
| a flag across an accessor's split (the Air's probe) | accessor |
| a flagged drop across a suspending call | suspension |
| a take: its take flag adopted, kept at the take, guarding the scope-end drop; a parameter taken, one local taken twice under one flag | takes |
| spawn handles the must-consume check accepts: `cancel()` alone, a move then a fate, a fate then a move, a fate on each arm, the chained `join()`, one per loop iteration, storage a declared `deinit` owns | fates |

## The flag counts

The borrow check labels 1 drop `flagged` over the sawc2 build and 28 over
tests/corpus (its lane counts them over every record). Elaboration has 1
flag over the sawc2 build, one per flagged drop. Over the corpus it has 25,
8 of them take flags it adopts: 3 of the 28 flagged drops are in programs the
borrow check refuses (`use_after_move_branch`, `use_after_move_loop`,
`use_after_move_loop_body_always_breaks`), which are not elaborated.
