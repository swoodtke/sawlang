# compiler/tests/borrowck: the borrow check's corpus

The corpus the borrow check (`compiler/borrowck`, package `sawborrowck`,
SL-460) is held to. This file specifies `sawc2 borrowck`'s records and dump,
the initialisation analysis it shares with the MIR verifier, the loan
analysis, the rules it refuses by, and the drop labels it exports for drop
elaboration.

The check needs no lifetimes and never looks outside a function, which is
sound only because a reference never escapes the function that made it:
typecheck's `type.reference-position` family (SL-462) refuses every position
that would let one out, and `premise/` pins that a returned reference never
reaches the borrow check.

```
borrowck/
  README.md              this specification
  CONFORMANCE.md         every borrow-check row of examples/conformance/INDEX.md, and its owner
  borrowck_lane.py       the lane compiler/tests/run.py runs
  golden/                NAME.saw, a program, and NAME.borrowck, its expected record
  refuse/                RULE.saw or RULE.VARIANT.saw, a program the check refuses
  premise/               NAME.saw, a program an earlier stage refuses so the check stays sound
  differential.tsv       the tests/corpus move errors the check does not refuse, and why
  loan_differential.tsv  the tests/corpus loan errors the check does not refuse, and the
                         expected successes it does, each with its mechanism
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

A non-escaping closure's `[move v]` of a value that owns something takes `v`
when the body runs (`compiler/tests/mir/README.md`, "Takes"). Its
`take(_L, _F)` is a **take** of `_L`, and this one analysis owns both halves
of it. It is a use, refused like a move when `_L` may already be gone, and it
leaves `_L` and every path inside it `W M`. The `M` is the static half: every
later read, borrow or move of `_L` is a use after move, whose message names
the take as the move. The `W` is the dynamic half: the drop at `_L`'s scope
end is `flagged`, and elaboration guards it with the take flag the closure
body clears. The loan half reads the take as a move of `_L`
(`loan.move-while-borrowed` applies) and makes no loan of it, since nothing
can reach `_L` after it. Inside the body, the take reaches through the
environment's reference, so it is a read of `_1` there.

## The loan analysis

`compiler/borrowck/src/loans.saw` (`borrowck_loans`) is the one answer to
"which borrows are live here"; the conflict rules (`conflicts.saw`) and the
dump are its clients.

- **Loans.** A `ref(shared | exclusive, P)` makes a loan on `P`. A
  `window_open` makes one on its receiver's place, the place of the `ref` its
  receiver argument was made by: exclusive when the use site borrowed
  exclusively, or when the accessor takes `&var self` or lends `&var T` and
  declares no shared twin (`@synthesize(shared)`), shared otherwise
  (SL:borrowing §3). A window whose receiver is reached through another
  window's lent place is a later hop of one chain, and an exclusive one
  makes the hop it is nested in exclusive too, transitively (§2.2). Stage
  0's std predates declared modes, so each of its
  accessors serves both from one declaration, the use site choosing. A
  closure that copies a reference into its environment makes a loan on the
  referent. A `ref` of an accessor's state record makes none.
- **Liveness.** A window's loan is live from its open's present edge to its
  `window_close`, so a conditional lend's absent edge carries none. Any other
  loan is live where a local carrying it is live, by a backward liveness of
  locals over the CFG (a use is any read, move, borrow or access through the
  local; a whole assignment kills it; a drop uses nothing; a `return` uses
  `_0`), and after a path from its creation reaches the point. A loan a
  window's argument carries lives while the window is open. An accessor's
  epilogue starts with the windows its prologue left open across the `lend`
  (the halves' record, `compiler/tests/mir/README.md`, "Accessors"), each
  with a loan of its own there: on its receiver, traced to its root in the
  prologue and named by the locals the state record restores, with the
  prologue's charge. The restores themselves are the split's moves and
  access nothing a loan holds (SL-495).
- **Carrying.** A local carries the loan made into it, and the loans of
  every value assigned into it: an operand read from a local's own storage,
  or a reference or function value read through one, carries; a value read
  through a reference carries nothing, since references are never stored. A
  reborrow, a `ref` through a reference, carries that reference's loans.
  Carrying is flow-insensitive.
- **Authorisation.** An access through a reference names a place rooted in
  the reference's local, so it never overlaps the loan the reference holds.
- **Overlap.** Two places overlap when they share a root and no step parts
  them at distinct fields, tuple elements, payload fields of one case, or
  constant indices (an index local assigned one integer constant, once). A
  place that ends where the other goes on through a deref names the
  reference, not its referent. A window's loan is on its whole receiver,
  whatever it lends.
- **Tracing.** `borrowck_trace` follows a deref of a reference back to the
  place the reference was made from: a `ref`'s place, the local it was copied
  or moved from, or a window's receiver. It stops at a parameter or a local
  assigned more than once.

## Rules

| rule | refuses | fixtures |
|---|---|---|
| `move.use-after` | a read, a borrow, a move or a call through a place that may have been moved, or a part of which may have been moved out (`M` or `P`); a write to a part of a place that may have been moved whole | `move.use-after`, `.double`, `.loop`, `.branch`, `.field-init`, `.force`, `.consumed`, `.partial`, `.while-condition`, `.take`, `.retake` |
| `consumes.some-paths` | a `consumes` method's receiver, or a field of it, moved out on some paths to a `return` and left on others (spec, Moving a field out); a path that diverges reaches no `return`, so it is exempt | `consumes.some-paths` |
| `loan.read-while-exclusive` | a read or a shared borrow of a place overlapping a live exclusive loan | `loan.read-while-exclusive`, `.tuple-element`, `.forwarded` |
| `loan.write-while-shared` | a write or an exclusive borrow of a place overlapping a live shared loan | `loan.write-while-shared`, `.receiver` |
| `loan.exclusive-twice` | a write or an exclusive borrow of a place overlapping a live exclusive loan | `loan.exclusive-twice`, `.dynamic-index` |
| `loan.move-while-borrowed` | a move of a place overlapping a live loan, a take included | `loan.move-while-borrowed`, `.take` |
| `loan.drop-while-borrowed` | a drop, at a scope's end or before an assignment, of a place overlapping a live loan | `loan.drop-while-borrowed` |
| `loan.window-root` | any access but a move or a drop that conflicts with a live window's loan on its whole root | `loan.window-root`, `.receiver-order`, `.two-windows`, `.beside-root`, `.forced`; a chain of hops, each exclusive under an exclusive one: `.chain` (block), `.chain-argument` (statement), `.chain-field`, `.chain-member`, `.chain-method`, `.chain-lend`, `.chain-cell`, and `.chain-for` (due); a window a `borrow` block keeps open across its `lend`, in the epilogue: `.carried` |
| `loan.closure-carrier` | any access but a move or a drop that conflicts with a loan a live closure carries | `loan.closure-carrier` |
| `loan.nested-call` | in a call's access set (spec, Nested calls), two written references overlapping, one exclusive and one inside a nested call, or a written `&var` inside a nested call overlapping the receiver of a call it is nested in, a shared reservation for the whole call | `loan.nested-call`, `.receiver`, `.sibling` |
| `loan.sync-suspend` | a suspension point, a call that may suspend or a yield-capable budget point, while a `borrows(sync)` window is open; typecheck's `borrows.sync-window` refuses the block form first | `loan.sync-suspend` |
| `lend.root` | a `lend` of a place that is not the receiver's own storage (spec, The lent place is rooted in the receiver): the accessor's own local or parameter, a place a reference parameter refers to (`&var` included), or a static. The receiver's storage is a place rooted in `self`, one reached through an indirection whose pointer was read out of the receiver (`lend buf[index]`), and, by tracing, a window opened on either | `lend.root`, `.parameter`, `.reference-parameter` |
| `lend.sync-undeclared` | a `lend` while a `borrows(sync)` window is open, in an accessor not declared `borrows(sync)` | `lend.sync-undeclared` |
| `lend.missing` | a path through a `borrows` body whose lend is not conditional that returns without lending | `lend.missing` |
| `lend.twice` | a `lend` in the code after a `lend`, an epilogue | `lend.twice` |
| `assign.rhs-borrow` | an assignment, plain or compound, whose right side writes `&var` of a place overlapping what it assigns: the right side runs first, so the write through the borrow is overwritten | `assign.rhs-borrow`, `.plain` |

The struct carrier, a borrowing struct carrying its window's loan, is due
when `lends` enters the slice (SL-461): `refuse/loan.struct-carrier.saw`,
headed `// due:`, is held to the `slice.not-yet` that stands in its way.

A loan conflict stands at the conflicting access, and its message names the
loan, where it came from (a window, a closure capture, an argument, a borrow)
and the place it holds, each traced to the names the source spells. Where
several live loans conflict, a window's names the conflict. A call set's
refusal stands at the nested reference, an assignment's at the assignment,
and a `lend` rule's at the `lend`. Each source node is refused once by the
loan rules, the call sets checked first, then assignments, then each access
in order.

The error of `move.use-after` stands at the use; its message names where the move happened,
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
| a field, element or payload moved out of a binding, `move p.x`, `move v[0]` | typecheck, `transfer.partial-move` (SL-462) |
| moving out through a reference, or out of a borrowed match payload | typecheck, `transfer.move-from-borrow` (SL-462); `move r.f` through a reference is `transfer.partial-move` |
| `move self.f` or `move self` outside a `consumes` method | typecheck, `consumes.move-self` |
| `move self.f` deeper than one field | typecheck, `transfer.partial-move` (SL-462) |
| `move self` whole in a `consumes` body | MIR lowering, `slice.not-yet` (`consumes-whole`) |
| a `consumes` field moved on some paths to a return only | the borrow check, `consumes.some-paths` |
| a use of `self` after `move self.f` | the borrow check, `move.use-after` |

Typecheck refuses a user's `move p.f` before MIR exists, so the MIR
verifier's whole-drop-after-a-part check and the copy a trivially copyable
part is read as see only the parts MIR moves itself.

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
    loan LK: shared|exclusive PLACE;  // ORIGIN at L:C
    ...

    bbK: {
        [C C ...] {LK ...} STATEMENT;
        [C C ...] {LK ...} drop(PLACE);  // LABEL
        [C C ...] {LK ...} TERMINATOR;
    }

    bbK: unreached
}
```

- NAME is the MIR dump's.
- Each `place` line is a move path whose type owns something a drop releases
  (the MIR's owned places), spelled as the MIR dump spells a place, with the
  name a diagnostic gives it.
- Each `loan` line is a loan the function creates, numbered in block and
  statement order: its mode, the place it charges as the MIR dump spells it,
  and where it came from, `ref`, `argument`, `capture` or `window wK`, at the
  position of the statement or terminator that creates it.
- Each statement and terminator is the MIR dump's, after a bracket holding,
  for each place listed, its conditions just before it, as letters in the
  order `U W P M D`, then, in a function with loans, the loans live just
  before it in braces; a drop ends in its label.
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
borrow check owns, U6d1's or U6d2's, naming a fixture or golden here); that
each golden's record equals its `.borrowck` file byte for byte (`--write`
rewrites them); that each refusal fixture is refused first at its header's
position (`--fill` writes a `// refuses: TODO` header), with no `INVARIANT`
under `sawc2 borrowck` and neither an `ERROR` nor an `INVARIANT` under `sawc2
mir`, and that every rule has a fixture; that a due fixture is still refused
by what stands in its way; that each premise program is refused first by the
earlier stage's rule its header names; that the compiler's own source, the
sawc2 build and each unit program, and the new std's entry under `--std-root
std`, check with no refusal and no invariant; and the two differentials.
Every tests/corpus program whose expected diagnostic names a move is refused
by a borrow-check rule, or `differential.tsv` says why not. Every program
whose expected diagnostic names an exclusivity or loan error is refused by a
rule of the loan half, and every program expected to succeed is refused by
none, or `loan_differential.tsv` names it with its direction (`accepts`: the
loan half refuses nothing Stage 0 refused; `refuses`: it refuses what Stage
0 ran) and its class: `owned` (another stage refuses it first, a migration
artifact included), `order` (an evaluation-order difference),
`stage0-over-refusal`, `stricter` (the loan half refuses by design what
Stage 0 compiles, the decision cited), `gap` (the loan half misses it) or
`mir-bug` (the lowering hands the check wrong MIR). A line may also name a
refusal fixture of this directory that Stage 0 compiles, always `refuses`:
the lane checks that a loan rule refuses it and that Stage 0 compiles it. It
counts the drop labels over the sawc2 build and over tests/corpus, for
information.

| aspect | golden |
|---|---|
| straight-line moves | moves |
| branches and joins | branches |
| loops: a move used again on the backedge, a revived condition move | loops |
| early exits: `return`, `break`, `try` | exits, loops |
| `consumes` field moves: every path, none, a diverging path | consumes |
| re-initialisation, a whole-referent replacement through `&var` | reinit |
| a closure capturing by `move` | closures |
| a take: `W M` after it, its drop `flagged`, whether or not the callee runs the body | takes |
| a dissolve under `try`, `??`, `if let`, `guard let`, `while let`, `for`, a binding `match` arm | dissolves |
| the drop labels | every golden |
| authorisation through a reborrow, a `&var` forwarded three deep | loans |
| field, tuple-element and constant-index disjointness; two shared borrows of one place | loans |
| a loan rooted in an `unsafe static var`, checked within the function | loans |
| nested windows, last opened first | windows |
| chains: an assignment's right side before the target's hops, a field beside the chain's, a read-only chain, a cell accessor's root after its window | chains |
| a conditional lend's absent edge carrying no loan | windows |
| a window's loan ending at its close | windows |
| a reference, and a window not `borrows(sync)`, spanning a suspension | windows |
| a shared window on a `let` root; shared windows rendered and compared side by side | windows |
| a plain receiver's two-phase borrow: `v.push(v.len())`, `b.add(b.size())` | calls |
| a call's access set accepted: `combine(n.get(), bump(&var n))`, disjoint fields, distinct roots | calls |
| an assignment's right side reading its target, or borrowing a disjoint path | calls |
| a non-escaping `[&var v]` closure writing `v`, its loan ending at its last call; a captured reference parameter | loan.closure-carrier |
| a `lend` rooted in `self` or forwarding a window on it, the forwarded window closed as the `lend` completes so the epilogue reaches the root again; a `lend` inside a `borrow` block beside a disjoint field; a `borrows(sync)` forward declared so; a conditional lend's absent path | accessors |
