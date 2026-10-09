# compiler/tests/mir: the MIR lowering's corpus

The corpus the MIR stage (`compiler/mir`, SL-452) is held to. This file
specifies `sawc2 mir`'s records and dump, the position matrices the corpus
covers, and the constructs the lowering refuses.

```
mir/
  README.md        this specification
  mir_lane.py      the lane compiler/tests/run.py runs
  golden/          NAME.saw, a program, and NAME.mir, its expected record
  refuse/          NAME.saw, a construct the lowering refuses
  corpus_info.py   how much of tests/corpus/ lowers, for information
```

## `sawc2 mir`

```sh
.build/sawc2 mir (--dump | --check) [--notes] [--std-root DIR]
                 [--module-path NAME=DIR]... [FILE | @LIST]...
```

Each FILE is the entry of its own program, which is resolved, type checked,
then lowered, every module checked in full and refused nowhere. The flags are
resolve's (see `compiler/tests/resolve/README.md`). Each entry gets one
record, starting with the line `FILE<TAB>path`, holding in order:

- one `ERROR<TAB>rule<TAB>file:line:col<TAB>message` line per refusal:
  resolve's, then typecheck's, then the lowering's, each in the order they
  were made;
- with `--notes`, typecheck's `NOTE` lines;
- one `INVARIANT<TAB>module<TAB>message` line per problem any verifier
  finds, resolve's, typecheck's (bodies and summaries included), then each
  fact the lowering found typecheck left unrecorded, then the MIR verifier's;
- with `--dump`, the dump of each module checked in full, in load order.

The exit code is 1 when any program has a refusal, 2 on a usage failure, and 0
otherwise. A module with a refusal of its own is not lowered, and neither is a
body another module's refusal poisoned; a function the lowering refuses a
construct in is neither dumped nor verified.

## The dump

A module's dump is the line `module IDENTITY`, then each function lowered from
its bodies, in the order typecheck checked them, each closure right after the
function it is written in. A function reads:

```
fn NAME -> RESULT {
    let _K: TYPE;  // NOTE
    window wK: ACCESSOR MODE [conditional] [sync];

    bbK: {
        STATEMENT;
        TERMINATOR;
    }
}
```

- NAME is what the body is: a function's, method's, `init`'s or default-bodied
  requirement's target text (its identity and parameters, as typecheck's dump
  prints a call's target); `default TARGET.PARAM` for a parameter's default
  value; `static IDENTITY`, `raw IDENTITY` and `align IDENTITY` for a
  static's initializer, a raw-backed case's value and an `@align` argument;
  `static_assert MODULE L:C` and `test MODULE L:C`; `closure#K of PARENT` for
  the K-th closure, counted from 0, written in function PARENT.
- Locals are numbered from 0 in each function. `_0` is the return place, then
  the parameters, the receiver first (`// self`) and a closure's environment
  first (`// env`), then the rest. The note names a binding: `// param NAME`,
  `// NAME` for a `let`, `var` or pattern binding, `// ref NAME` for one whose
  local holds a reference its name reads through (a borrow binding, an
  alias into a borrowed scrutinee, a guard's view of a binding); a temporary
  has none. A receiver is `&Self` or `&var Self`, and `Self` for a `consumes`
  method, which owns it.
- Each window the function opens: its accessor's target text, `shared` or
  `exclusive`, `conditional` for a lend that may be absent, `sync` for a
  `borrows(sync)` accessor.
- Blocks are numbered from 0 in each function, `bb0` the entry. Types print in
  their canonical spelling (`compiler/tests/typecheck/README.md`, "Type
  spellings").

A **place** is `_K`, or `static IDENTITY`, then its projections: `P.FIELD`, a
tuple's `P.K`, `P[_K]` indexed by a local, `(*P)`, `(P as CASE).K` for a
payload a switch has proven, and `(P as CASE!).K` for one that panics on
another case, as `o!` and `try!` do.

An **operand** is `copy PLACE`, `move PLACE`, or `const TEXT: TYPE`, TEXT as
the source spells it: an integer, a string with its quotes, `true`, `()`, a
format placeholder `{}`, a function's target text, a const parameter's name,
`Int.max` or a source location's directive.

A **statement** is `PLACE = RVALUE;`, `drop(PLACE);` (drop it if it is still
initialised), or `budget(yield-capable);` / `budget(charge-only);`, an
op-budget point. An **rvalue** is:

| rvalue | reads |
|---|---|
| `OPERAND` | the operand |
| `ref(shared, PLACE)`, `ref(exclusive, PLACE)` | a reference to the place |
| `Add(A, B)`, `Eq(A, B)`, ... | a builtin binary operator; `Range` and `RangeInclusive` build ranges |
| `Neg(A)`, `Not(A)`, `BitNot(A)` | a builtin unary operator |
| `cast(A as T)`, `widen(A as T)`, `adopt(A as T)`, `erase(A as T)`, `slice(A as T)` | `as`, and the adjustments that build a new value |
| `from(A as T)`, `from(truncating:)(A as T)`, `from(raw:)(A as T)`, `alias(A as T)` | the conversions no declaration writes |
| `TYPE { FIELD: A, ... }` | a struct's memberwise construction |
| `TYPE::CASE(A, ...)` | an enum case; `Optional`'s and `Result`'s are the auto-wraps |
| `(A, B)`, `[A, B]`, `[A; N]` | a tuple, a fixed array, a repeat literal |
| `vector [...]: T`, `set [...]: T`, `map [K: V, ...]: T` | a collection literal |
| `closure#K of PARENT [A, ...]` | a closure, its captures in its table's order |
| `interpolate [A, ...]` | an interpolated string's segments, placeholders and values |

A builtin operator's operand is the value for a trivially copyable type, a
reference, a slice or a function value, and a shared reference to it for any
other type; a constant stands for itself.

A **terminator** is `goto -> bbK;`, `return;`, `unreachable;`, a switch, or a
call:

- `switch OPERAND -> [true: bbK, false: bbK];` on a `Bool`;
  `switch discriminant(PLACE) -> [CASE: bbK, ..., otherwise: bbK];` on an enum,
  `otherwise` present when some case is not named;
- `[PLACE = ] CALLEE [(owner T)] [(inst T...)] [ARGS] -> [return: bbK]
  [SUSPENSION];`, or `-> !` for a call that never returns. CALLEE is `call
  TARGET`, `call default TARGET.PARAM` (a parameter's default value), `call
  builtin NAME`, `call value OPERAND` (a function value), `window_open wK
  TARGET`, `window_close wK TARGET`, or `lend`. A window's open continues
  `-> [present: bbK, absent: bbK]`, the absent edge only for a conditional lend
  the construct branches on at once; a close takes no arguments. ARGS are in
  the target's parameter order, a receiver first.
- SUSPENSION is ` suspends` for a call that may suspend whatever its type
  arguments, or ` suspends when T.Trait.req ...` for one that may when the
  conditions over the function's own type parameters hold (typecheck's
  summaries, evaluated at the call's instantiation), sorted. A call that
  never suspends says nothing.

## The position matrices

**The operand funnel's entry points** (`operand` in `compiler/mir/src/lower.saw`,
whose docstring lists them), each covered by a golden case:

| position | entry point | covered by |
|---|---|---|
| a `let` or `var`'s value | `lower_let` | operands, drops |
| an assignment's value; a compound assignment's | `lower_assign`, `lower_compound` | operands, order |
| a returned value; a block's or branch's tail | `lower_into` | operands, branches |
| a value a statement discards, `let _` | `lower_discarded` | drops |
| a condition of `if`, `while`, `guard`, a guard | `condition_operand` | branches, matches |
| a call's arguments, in written order | `call_arguments` | operands, order |
| a receiver a `consumes` method takes | `receiver_operand` | operands |
| a struct's, a case's, a tuple's, an array's, a collection's operands | `aggregate_operands` | operands, adjustments |
| a closure's captures | `closure_captures` | closures |
| a builtin's arguments: `print`, `panic`, `assert`, a builtin method | `builtin_operand` | operands, drops |
| a format argument, an interpolated segment | `format_operand` | operands, drops |
| a declared `equals` or `compare` a comparison calls | `operator_call` | operands |
| a conversion's argument, `as` | `conversion_operand` | operands |

**Transfers**: a spelled `move` and a generic local's single-path read moves
(operands, `forward`); an owned temporary is handed off; a named place of the
Copy tier copies, through its type's written `copy()` when it has one
(operands, `Retained`); a borrowed operand is copied or referenced as the
rvalue table says.

**Adjustments**, each made explicit (adjustments):

| kind | lowered to |
|---|---|
| `adopt` | the constant retyped, `const 7: UInt8`; any other value `adopt(A as T)` |
| `never` | nothing: control does not reach the position |
| `some`, `ok`, `err` | `Int?::Some(A)`, `Result<...>::Ok(A)`, `Result<...>::Err(A)` |
| `slice` | `slice(A as &[T])` |
| `deref` | the `(*P)` projection |
| `borrow`, `borrow-var` | `ref(shared, P)`, `ref(exclusive, P)`, a receiver's taken just before its call |
| `shared` | `ref(shared, (*P))`, a reborrow |
| `erase` | `erase(A as T)` |
| `widen` | `widen(A as T)` |

**Constructs**:

| construct | lowered as | covered by |
|---|---|---|
| `if`, `else if`, `else` | a switch per condition, each arm into the destination | branches, windows |
| `if let`, `guard let`, `while let` | a discriminant switch, or a conditional window's two edges | branches, windows |
| `while`, `while { }`, `for` | a head, a body, an op-budget point on each backedge | drops, points, windows |
| `break`, `continue`, `return` | the scopes' exits, then the edge | drops |
| `&&`, `\|\|` | a switch per operand | branches |
| `??` | a discriminant switch per operand, peeling one layer of a nested Optional, keeping the left operand whole against an Optional default of its own type | branches, peel |
| `borrow p` handed to a `&` or `&var` parameter | a reference taken inside the window, which stays open to the statement's end | windows |
| `borrow v.get(i)` in `if let` or `??` | the conditional window `v.get(i)` opens | windows |
| each kind of body | a function of its own | bodies |
| `try`, `try!`, `try?` | a switch with a return of `Err`; the `Ok!` projection; a switch building an Optional | branches, adjustments |
| `match` | a decision tree | matches |
| `borrow let x = p { }` | a window, closed on every edge out of the body | windows |
| `borrow var p += v`, `borrow p` | a window closed at the statement's end, or once the value is copied out | windows |
| `v[i]` read, `v[i] = x` | a derived getitem or setitem around the place accessor's window, or the declared `[]`, `[]=` | windows, order |
| `x.f(...)` on a `borrows` accessor | a window on a place, or a copy out of it | windows |
| a closure | an aggregate of its captures, its body a function of its own | closures |
| `lend p` | a `lend` call, the accessor's pause | windows |
| a call of a function that may suspend | a suspension point, conditional in a generic body | points |

## Refusals

A construct the lowering does not handle yet is refused as `slice.not-yet`,
never lowered wrong. Each fixture in `refuse/` starts with `// refuses:
slice.not-yet at L:C`.

| refused | fixture |
|---|---|
| a `match` on a conditional lend | conditional-match |
| a `borrow` block binding a conditional lend | conditional-block |
| a `for` over an iterator held in a place | iterator-place |
| a `for` head that lends a place; a `borrows` call lending a slice or a borrowing struct outside a `for` head; a `borrows` function called with no receiver; a setitem derived from a conditional lend; a conditional lend's place read other than through `!` | none: nothing in the slice reaches them |

## The verifier

`compiler/mir/src/verify.saw` runs on every function lowered and refused
nowhere, and checks, from the MIR alone:

- every block ends in one terminator, and every edge names a block;
- every place names a local or a static and has a type, every projection a
  type, an index projection a local; every operand is a move or a copy of a
  place, or a constant with a spelling; every rvalue has a type;
- no conversion is left implicit: an assignment's rvalue has its place's type,
  a `Use` keeps its operand's, and a call's argument after its receiver has
  its parameter's type at the call's instantiation;
- every call names its target (a declaration, a builtin, a function value)
  and an instantiation as long as its target's generic list;
- every call is a suspension point exactly as typecheck's summaries,
  evaluated at its source node, make it, and a conditional one carries its
  conditions;
- over the blocks, no owned local may still be live at a `return`, or when it
  is assigned again, so every scope exit drops it; no window may still be
  open at a `return`, or when it opens again, so every path out of its body
  closes it;
- every loop backedge, an edge to a block on the depth-first path from the
  entry, leaves a block whose last statement is an op-budget point.

## The lane

`mir_lane.py` runs one `sawc2 mir` process per group and checks that each
golden program's record equals its `.mir` file byte for byte (`--write`
rewrites them after a deliberate change, for review), that each refusal
fixture is refused first at its position (`--fill` writes a `// refuses:
TODO` header), that no golden or fixture record carries an `INVARIANT` line,
and that the compiler's own source lowers whole, the sawc2 build and each
unit program, with no refusal and no invariant; a unit program the parser
refuses is counted apart. It prints how many functions of the sawc2 build
were lowered. `corpus_info.py` lowers every file of `tests/corpus/` and prints
how many lower clean; it does not gate.
