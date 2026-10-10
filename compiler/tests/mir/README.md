# compiler/tests/mir: the MIR lowering's corpus

The corpus the MIR stage (`compiler/mir`, SL-452) is held to. This file
specifies `sawc2 mir`'s records and dump, the position matrices the corpus
covers, and the constructs the lowering refuses.

```
mir/
  README.md        this specification
  mir_lane.py      the lane compiler/tests/run.py runs
  golden/          NAME.saw, a program, and NAME.mir, its expected record
  spans/           NAME.saw, a program, and NAME.mir, its expected `--spans` record
  refuse/          NAME.saw, a construct the lowering refuses
  inject/          NAME.saw, a program a unit program lowers, then edits, to
                   prove the verifier refuses a shape no lowering emits
  corpus_info.py   how much of tests/corpus/ lowers, for information
```

## `sawc2 mir`

```sh
.build/sawc2 mir (--dump | --check) [--notes] [--spans] [--std-root DIR]
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
  the K-th closure, counted from 0, written in function PARENT; `prologue
  TARGET` and `epilogue TARGET` for a `borrows` accessor's two halves (below).
- Locals are numbered from 0 in each function. `_0` is the return place, then
  the parameters, the receiver first (`// self`) and a closure's environment
  first (`// env`), then the rest. The note names a binding: `// param NAME`,
  `// NAME` for a `let`, `var` or pattern binding, `// ref NAME` for one whose
  local holds a reference its name reads through (a borrow binding, an
  alias into a borrowed scrutinee, a guard's view of a binding); a temporary
  has none. A receiver is `&Self` or `&var Self`, and `Self` for a `consumes`
  method, which owns it. `// record` marks an accessor's state record: a
  half's first parameter, `&var` of the record, or a caller's local holding
  one for a window.
- Each window the function opens: its accessor's target text, `shared` or
  `exclusive`, `conditional` for a lend that may be absent, `sync` for a
  `borrows(sync)` accessor, and `record _K` for the local holding its
  accessor's state record.
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
`Int.max` or a source location's directive. `format TEXT` is the format string
of `print`, `panic` or `assert`, the message that format arguments follow or
that holds `{}` slots, spelled as the literal is: a constant whose slots the
call's next operands fill, rendered through stack scratch with nothing
allocated (design 137). Only a real interpolation, `"x = {x}"`, builds a
`String` with `interpolate`.

A **statement** is `PLACE = RVALUE;`, `drop(PLACE);` (drop it if it is still
initialised; a part's place drops that part alone), or `budget(yield-capable);` / `budget(charge-only);`, an
op-budget point. Only a value that owns something a drop releases is dropped:
anything but a reference, a slice, a trivially copyable type, or a tuple, an
array or an Optional of those alone. An **rvalue** is:

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
| `interpolate [A, ...]` | an interpolated string's segments, placeholders and values, a `String` it allocates |

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
  prologue TARGET` or `window_close wK epilogue TARGET`, which call its
  accessor's halves at the instantiation the open took. A window's open
  continues `-> [present: bbK, absent: bbK]`, the absent edge only for a
  conditional lend the construct branches on at once. ARGS are in the
  target's parameter order, a receiver first; a window's open passes its
  record first when it holds one, and its close passes only that record. A
  `lend` stands only in an accessor's body before it is split, so no dump
  shows one.
- SUSPENSION is ` suspends` for a call that may suspend whatever its type
  arguments, or ` suspends when T.Trait.req ...` for one that may when the
  conditions over the function's own type parameters hold (typecheck's
  summaries, evaluated at the call's instantiation), sorted. A call that
  never suspends says nothing.

The functions of a static's initializer, a raw-backed case's value, an
`@align` argument and a `static_assert`'s condition are the constant
positions `compiler/eval` evaluates (`compiler/tests/eval/README.md`).
Const-generic arguments, array lengths and repeat counts have no function of
their own yet; SL-457 owns lowering them.

## Accessors

A `borrows` accessor that lends a place lowers to two functions around its
`lend` (SL:architecture §3.5; `compiler/mir/src/split.saw`). Its body is
lowered whole, `lend` a call that pauses it, then split there, before any
caller is lowered, since a caller holds the state record the split lays out:

- the **prologue**, the blocks the entry reaches without resuming from a
  `lend`: `_0` is the lent reference (an Optional of it for a conditional
  lend), `_1` the record, then the accessor's parameters. Each `lend` writes
  `_0`, then every record field, then returns; a return the entry reaches
  without lending is a conditional lend's absent path, and gives `None`;
- the **epilogue**, the blocks a `lend` resumes into: `_0` of `Void`, `_1` the
  record. Its entry reads each field into its local and continues where the
  `lend` resumed, testing the resume index when there are several;
- the **state record**, a tuple of the locals live across the `lend`
  (liveness over the whole body: read on some path after it before written),
  in local order, then a `Bool` drop flag for each of them that owns
  something and is not definitely whole at some `lend`, then an `Int` resume
  index when the body lends at more than one place. An accessor with none of
  them has no record and no `_1`. A window the prologue opens to forward a
  place stays open into the epilogue, which closes it. A flagged local's
  record write is a transfer and its load a resume, which the initialisation
  analysis models (`compiler/tests/borrowck/README.md`); the flag field
  itself is written by drop elaboration (`compiler/tests/drops/README.md`),
  where the flag is born, so the MIR leaves it unwritten. A local partly
  moved out at a `lend` has no one flag, and is refused as `slice.not-yet`.

A caller's window holds the record in a local of its own, instantiated at the
window's call, and passes it by exclusive reference to both halves. An
accessor whose body this program does not lower, an interface module's (std's
today), has no halves here: its window holds no record, and its calls name
its halves only by its target. A window call is a suspension point only when
its half holds a call that may suspend; one of an accessor whose body is not
lowered is one as the accessor's summary makes it.

| case | covered by |
|---|---|
| a plain accessor | accessors `Grid.[]` |
| a conditional lend | accessors `Grid.find` |
| a record of two live locals | accessors `Grid.counted` |
| two `lend`s and a resume index | accessors `Grid.either` |
| a forwarded `lend`, its window open across | accessors `Grid.forwarded` |
| a prologue that may suspend | accessors `Grid.waited` |
| a `borrows(sync)` accessor | accessors `Lock.hold` |
| a caller holding records | accessors `use_all` |

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
rvalue table says. A part of a trivially copyable type (a field, an element,
a payload) is read as `copy` wherever its position takes it by value: the
bits are the same, and the value it lies in stays whole, so that value's one
drop is still right (destructures `relayed`). So is a part holding a shared
reference or slice. A part holding an exclusive reference, `&var T`, read by
value through no reference, is always a `move`, even where its position copies:
it is a reborrow out of a container that is dead after it, never a second live
alias of the referent (references). No transfer moves an owning value out
through a reference: a hand-off or a last read of a place reached through one,
such as `s.compare(&t)` handing the `deref` of a fresh `&t` to a by-value
parameter, copies a Copy-tier value (`copy (*_K)`), and a pattern binding of
an owning part reached through one copies it or aliases it (below).

These copies the lowering chooses, and so do a closure's capture loads and
copy captures (Closure environments, below), so they ask
`mir_copies_silently`, not typecheck's tier: a type that is or mentions a type
parameter copies only where the bounds grant `Copy`. Typecheck answers that
every parameter copies, the requirement design 219 checks at each call, but
it records no requirement for a copy the lowering invents, so at a NoCopy
instantiation such a copy would be freed twice. Otherwise each rule takes its
non-Copy path: read in place, alias, or leave the move for the verifier to
report. Drops golden `generics` holds each, and the unit program
`compiler/mir/tests/verify_moves.saw` requires an unbounded `T` handed off
through a reference to stay a reported move.

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
| `if let`, `guard let`, `while let` | a discriminant switch, or a conditional window's two edges | branches, windows, guards |
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
| a receiver or a subscript's base reached through a `borrows` accessor, chained, through `!`, under a key or an index | its windows opened in receiver position, before the arguments, keys or index (`open_receiver_windows`); a plain receiver's borrow taken just before the call; an assignment's target opens its windows after the right side, a compound one's too | receivers |
| a closure | an aggregate of its captures, its body a function of its own | closures |
| `print("x = {}", x)`, `panic`'s and `assert`'s format messages | a `format` constant, the arguments after it; `"x = {x}"` an `interpolate` | formats |
| `lend p` | the end of the accessor's prologue, the start of its epilogue | windows, accessors |
| a call of a function that may suspend | a suspension point, conditional in a generic body | points |

**Optional heads** (`open_head` in `compiler/mir/src/lower.saw`, whose
docstring lists its entry points: `if let`, `guard let`, `while let`). The
subject is evaluated in a head scope of its own. Its absent edge runs that
scope's exits at once, its Optional and the subject's owned temporaries
dropping there; `close_head` ends the scope on the present edge before it
hands out the absent one, so a `guard`'s else block, lowered after, leaves
only the scopes around the guard and drops nothing of the head a second
time. Each way out of a `guard let`'s else block, with a temporary owning a
`String` in the subject:

| way out | covered by |
|---|---|
| `return` | guards `returned` |
| `break` | guards `broken` |
| `continue` | guards `continued` |
| `try`'s error edge | guards `propagated` |
| `guard var` | guards `mutable` |
| in a closure's body | guards `closed` |
| a guard nested in a loop, by `break` and by `continue` | guards `nested` |
| a `try` inside the subject | guards `tried` |
| an owning payload, `h!.label(n)`: taken by the binding on the present edge, the `None` dropped once on the absent one | guards `present` |

**Consuming destructures** (`dissolve` in `compiler/mir/src/lower.saw`,
whose docstring lists its entry points). Saw has no partial moves, so a value
comes apart only where a construct consumes it whole: a pattern whose bindings
take parts by move, a payload taken out of an Optional or a Result, a field or
element of a temporary read by value, and a `consumes` body's `move self.f`.
The value, always a temporary (a consumed local moves into one first, `move
o!` included), is dissolved at the destructure: the parts the bindings take
move into them, every other owned part drops right there, in reverse
declaration order (spec, Synthesized destruction), and the value is never
dropped whole on that path, so it leaves its scope. A path that takes no part
drops the value whole there instead. A construct is consuming when some
binding takes an owned part by move; one that only copies or borrows changes
nothing.

| position | dissolved at | covered by |
|---|---|---|
| `try e` | the switch: the `Ok` payload into a temporary, the `Err` payload into the returned `Err`; a trivially copyable `Err` is copied out, and the Result drops whole | destructures `propagated`, `relayed` |
| `try! e` | the checked `Ok!` payload, moved into a temporary when its position takes it by value | destructures `forced` |
| `try? e` | the `Ok` edge's `Some`; the `Err` edge drops the Result whole | destructures `optional` |
| `a ?? b` | the present edge's payload; the absent edge drops the `None` | destructures `coalesced` |
| `move o!` | the Optional moved whole into a temporary, then its payload | destructures `moved_force` |
| `f()!`, `f().field`, `f().0` by value | the temporary, around the part | destructures `temporary_parts` |
| `match` on a consumed local or a temporary | each leaf, after its bindings | destructures `matched`, `matched_temporary` |
| `if let`, `guard let`, `while let` | the present edge, after the binding; `if let x = move o` moves `o` into a temporary first | destructures `optional`, `unwrapped`, `drained` |
| a destructuring `let` | after its bindings | destructures `destructured` |
| `for`'s `next()` Optional | each item, after the binding; an item nothing binds drops there | destructures `iterated` |
| `move self.f` in a `consumes` body | every exit: the fields the body moves out nowhere, never the whole receiver nor its `deinit` body; a field moved on some paths to a return only is borrowck's `consumes.some-paths` | destructures `Holder.take_kept` |

**Scrutinees read through a reference** (SL-475). A pattern-matching head
whose scrutinee's place reaches through a `Deref` of a reference matches the
referent where it sits: a switch on `discriminant((*_K))`, no temporary, no
drop, and no consuming destructure. Typecheck records a borrowed scrutinee's
use as a test and its bindings as borrows; `lower_match` and `optional_switch`
still decide by the place, not the use, so a `move` recorded for such a
scrutinee could not move its referent out. A binding of an owning
part reached through a reference (`binding_use`) never moves it out: a
Copy-tier part is copied, any other is aliased (`// ref NAME`), as a part of
a borrowed scrutinee is. Each head and scrutinee kind is a function of
golden `scrutinees`:

| head | `borrow let` | `borrow var` | `&` / `&var` parameter | `&self` / `&var self` field | `[&x]` capture | conditional lend's payload |
|---|---|---|---|---|---|---|
| `match`, a `borrow` payload | `match_borrow_let` | `match_borrow_var` | `match_parameter`, `match_parameter_var` | `match_field`, `match_field_var` | `match_capture` | `match_lend_payload` |
| `match`, a by-value payload: Copy / NoCopy (an alias) | `match_borrow_let_copy` / `match_borrow_let_alias` | | | | `match_capture_copy` | |
| `match`, no binding; nested under a payload | `match_borrow_let_none`; `match_nested` | | | | | |
| `if let`, `if borrow let` | `if_let_borrow_let`, `if_let_borrow_let_none`, `if_borrow_unwrap` | `if_let_borrow_var` | `if_let_parameter` | `if_let_field` | `if_let_capture` | |
| `guard let` | `guard_let_borrow_let` | | `guard_let_parameter` | `guard_let_field` | | |
| `while let` | `while_let_borrow_let` | | `while_let_parameter` | `while_let_field` | | |

A by-value binding of a NoCopy payload is refused by typecheck under `if let`,
`guard let` and `while let` (`transfer.implicit-copy`), so those heads have no
alias row. A user's `move` of an aliased binding is typecheck's to refuse
(`transfer.move-from-borrow`); one it missed would lower through the alias,
and the verifier would report it.

**Closure environments** (`lower_closure`). A closure's body reads its
captures out of its environment, `_1`, at entry. An escaping closure's
environment is shared by every copy of the closure and released once, at its
last owner (spec, Escaping-closure heap environments), so a call never takes
ownership out of it (`load_owned_capture`, SL-475), and neither does a call of
any closure take a `[copy x]` capture, which the environment holds from
creation. At creation, `capture_copy` builds a copy capture: a silent copy for
the Copy tier, and otherwise a call of the `copy()` the type's ExplicitCopy
conformance declares (`_5 = call Vector.copy() [...]`), or, for a type
parameter bounded `ExplicitCopy`, the bound's (`call ExplicitCopy.copy()
(owner T)`), as a spelled `x.copy()` lowers; so the environment and the
binding never share one buffer. One no copy resolves for is an `INVARIANT`,
never a bitwise copy (typecheck's refusal is SL-481). In the body, a by-value
capture that owns nothing, or is of the Copy tier, is copied into a local the
call drops, retained by its copy (`_2 = copy (*_1).0`); any other is read in
place,
through a reference the capture's name reads through (`_2 = ref(shared,
(*_1).0)`, `// ref r`). This is the spec's "loaded into a per-call local" read
so that it never transfers: what the local holds is a copy or a view, never
the environment's value. Typecheck refuses every consuming use of such a
capture (`capture.escaping-consume`), so no move out of an escaping
environment is left to lower. A non-escaping closure's `[move v]` still loads
with a move (`_2 = move (*_1).0`): that is the take-once transfer, which
needs a shape of its own and a drop flag the body clears (SL-477), and the
verifier exempts it by name. Each closure kind and capture kind is a function
of drops golden `captures`.

## Refusals

A construct the lowering does not handle yet is refused as `slice.not-yet`,
never lowered wrong. Each fixture in `refuse/` starts with `// refuses:
slice.not-yet at L:C`.

| refused | fixture |
|---|---|
| a `match` on a conditional lend | conditional-match |
| a `borrow` block binding a conditional lend | conditional-block |
| a `for` over an iterator held in a place | iterator-place |
| a consuming destructure of a type that writes its own `deinit`, since the spec does not say whether dissolving one skips that body | consuming-deinit |
| the release of a consumed receiver that moves out whole, or is an enum, when its type writes its own `deinit` | consumes-whole |
| a `for` head that lends a place; a `borrows` call lending a slice or a borrowing struct outside a `for` head; a `borrows` function called with no receiver; a setitem derived from a conditional lend; a conditional lend's place read other than through `!` | none: nothing in the slice reaches them |

Two constructs typecheck refuses before lowering, as `transfer.partial-move`,
are invariants here rather than refusals: a `consumes` body moving out of
`self` deeper than one field, and an accessor's local partly moved out at a
`lend` (only a source `move` of a part leaves a local partial). Meeting
either prints an `INVARIANT` line.

## The verifier

`compiler/mir/src/verify.saw` runs on every function lowered and refused
nowhere, and checks, from the MIR alone:

- every block ends in one terminator, and every edge names a block;
- every place names a local or a static and has a type, every projection a
  type, an index projection a local; every operand is a move or a copy of a
  place, or a constant with a spelling; every rvalue has a type;
- no conversion is left implicit: an assignment's rvalue has its place's type,
  a `Use` keeps its operand's, and every call's arguments have the types its
  own target takes at the instantiation and owner the call carries, a
  synthesized call (a `copy()` hook, a derived getitem's or setitem's window,
  `for`'s `next`, a comparison's `equals`) and an extern included: a
  receiver by reference in the mode the call takes it (a window's in its use
  site's mode) or by value for `consumes`, then each parameter, as many as
  the target declares; a function value's call its type's parameters; a
  `lend` the reference its accessor lends; a default's result its
  parameter's type. Only a builtin, which declares no signature, and a C
  variadic tail, which no declaration types, go unchecked;
- every call names its target (a declaration, a builtin, a function value)
  and an instantiation as long as its target's generic list;
- every call is a suspension point exactly as typecheck's summaries,
  evaluated at its source node, make it, and a conditional one carries its
  conditions; a window call whose half holds no call that may suspend is
  none;
- no accessor that lends a place is lowered whole; each half belongs to its
  accessor; every window call names its accessor's half and passes the
  record its accessor lays out, instantiated, or names none and passes none
  for an accessor whose body is not lowered; the epilogue reads no local the
  record does not give it, and every record local is read after the `lend`,
  so the record holds exactly the locals live across it; each prologue
  return writes all of the record's fields but the drop flags, or none; a
  prologue's return may
  leave its record locals live and its carried windows open, which the
  epilogue resumes with;
- over the blocks, no owned local may still be live at a `return`, or when it
  is assigned again, so every scope exit drops it; no window may still be
  open at a `return`, or when it opens again, so every path out of its body
  closes it;
- no path drops a place whole once a move has taken any part out of it (a
  field, an element, a payload, not through a reference): a consuming
  destructure dissolves its value, and the move ends the local's life. There
  is no exemption for a part that owns nothing, since such a part is read as
  `copy` (Transfers, above);
- no path drops a place twice, an owned local, a statement's temporary or a
  part of either, with no assignment to it between, and no path reads,
  borrows, writes a part of, or indexes with a local after its drop with no
  assignment between. The drop semantics, drop it if it is still initialised,
  make such a drop harmless at run time, so this is the check that tells a
  lowering's misplaced exit apart from a correct one. These move-path facts,
  and the liveness at a `return`, are the initialisation analysis's
  (`compiler/mir/src/initialisation.saw`, specified in
  `compiler/tests/borrowck/README.md`), whose other client is the borrow
  check. A `consumes` body moving a field on some paths to a return only is a
  user's error the borrow check reports, so its move paths are not checked
  here;
- every loop backedge, an edge to a block on the depth-first path from the
  entry, leaves a block whose last statement is an op-budget point;
- every statement and terminator the entry reaches carries a source node;
- no operand moves an owning value out through a `Deref` of a reference
  (SL-475): that storage is someone else's, who drops it again. A value that
  owns nothing, a reference part such as an accessor record's `&var` field,
  may move, and a raw pointer's pointee is not a reference's. Two shapes are
  exempt, each a whole entry `(*_1).K`: an epilogue's load of record local K,
  which its accessor owns across the split, and a non-escaping closure's load
  of a `move` capture K, the take-once transfer that is owed a shape of its own
  (SL-477). The initialisation analysis reads a move
  through a reference as a read of the reference, so this is the one check
  that sees one. The verifier reads no text, so its rejection is pinned by the
  unit program `compiler/mir/tests/verify_moves.saw`, which edits a lowered
  copy through a reference into a move and requires the report.

## Source nodes

Every statement and terminator carries the source node it lowers, which the
later stages report at; `--spans` follows each one in the dump with
`  @LINE:COL`. The node is the one being lowered when the statement is
emitted, set only through `source_at` in `compiler/mir/src/build.saw`, whose
docstring names its entry points. One rule covers what no expression spells:

- a scope exit's drops and window closes carry the exit that caused them: the
  `return`, `break`, `continue` or `try`, and for a fallthrough the closing
  brace of the block that ends;
- a consuming destructure's part moves and drops carry its pattern;
- a budget point carries its loop;
- an accessor's halves keep the nodes of what they copy; a `lend`'s record
  writes carry the `lend`, and the epilogue's entry the accessor's body.

Each shape has a span golden in `spans/`, recorded with `--dump --spans`:

| shape | covered by |
|---|---|
| a move, then a use | moves |
| a drop at a block's fallthrough; on `return`, `break`, `continue`, `try` | exits |
| a dissolve; an optional head's temporaries on both edges | dissolve |
| a call, a switch, a loop's budget point | calls |
| an accessor's halves; a window's open and close | accessor |

## The lane

`mir_lane.py` runs one `sawc2 mir` process per group and checks that each
golden and span program's record equals its `.mir` file byte for byte (`--write`
rewrites them after a deliberate change, for review), that each refusal
fixture is refused first at its position (`--fill` writes a `// refuses:
TODO` header), that no golden or fixture record carries an `INVARIANT` line,
and that the compiler's own source lowers whole, the sawc2 build and each
unit program, with no refusal and no invariant; a unit program the parser
refuses is counted apart. It prints how many functions of the sawc2 build
were lowered. `corpus_info.py` lowers every file of `tests/corpus/` and prints
how many lower clean; it does not gate.
