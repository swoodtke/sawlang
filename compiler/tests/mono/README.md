# compiler/tests/mono: monomorphization and layout

The corpus monomorphization (`compiler/mono`, package `sawmono`, SL-505) and
the target description (`compiler/target`, package `sawtarget`) are held to.
This file specifies `sawc2 mono`'s records, the item model, the glue, the
layout table, the rules mono refuses by, and the lane.

```
mono/
  README.md               this specification
  mono_lane.py            the lane compiler/tests/run.py runs
  golden/                 NAME.saw, a program; NAME.mono, its items; NAME.layouts,
                          its layout table
  refuse/                 RULE.saw or RULE.VARIANT.saw, a program refused
  layout_exceptions.tsv   a type whose layout differs from Stage 0's, and why
  stage0/                 Stage 0's recorded runs of the layout probes (see "The lane")
```

## `sawc2 mono`

```sh
.build/sawc2 mono (--dump | --layouts | --check) [--notes] [--lowerings] [--std-root DIR]
                  [--target TRIPLE] [--module-path NAME=DIR]... [FILE | @LIST]...
```

Each FILE is the entry of its own program. It is resolved, type checked,
lowered, borrow checked and elaborated as `sawc2 drops` does, its constants
evaluated, then monomorphized. Its record, after the `FILE` line, holds
everything `sawc2 drops --check` prints; then, when nothing there is an
`ERROR` or an `INVARIANT` line, one `ERROR<TAB>rule<TAB>file:line:col<TAB>message`
line per refusal of mono, an `INVARIANT<TAB>mono<TAB>message` line per broken
invariant mono met, and with `--dump` each item, with `--layouts` the layout
table. The exit code is 1 when any program has a refusal, 2 on a usage
failure, and 0 otherwise. `--target` names the triple the layouts are for:
`arm64-apple-darwin` (the default) or `x86_64-unknown-linux-gnu`.

The file is lowered to MIR once. The evaluator borrows that program and
evaluates its constants before the borrow check and drop elaboration rewrite
its bodies, and mono reads the statics' values from the evaluator's table,
keyed by declaration; it checks the two tables have one length.

`--lowerings`, which `resolve`, `typecheck`, `mir`, `eval`, `borrowck` and
`drops` take too, ends each record with a `LOWERINGS<TAB>N` line: how many
times its source was lowered to MIR. Every subcommand from `mir` on owes 1,
and the two before it 0.

## Items

An **item** is a function's body at concrete arguments, a type's drop or copy
glue, the member glue of a requirement no written member or default body
meets, or an `extern` the program calls by its C name. A function item's
identity is its source MIR function and its canonical concrete arguments:

- the receiver type's arguments, for the parameters of the type an extension
  method extends;
- the function's own type arguments;
- `Self`, for a trait's default body.

Typecheck interns types by canonical form with defaults filled (SL-382), so
two spellings of one instantiation are one item. A closure, a default
value's function and an accessor's prologue and epilogue are items under
their parent's arguments. A glue item is (drop or copy, concrete type), a
member glue item (requirement, concrete type); an extern item is its C name,
so two std modules declaring one seam call one symbol.

**The worklist** starts from the roots, in this order: the entry module's
`main`, which a runtime source (`sawc2 runtime`) has none of, and which is
never a test-only declaration: a normal build emits none, so a program whose
only `main` is test-only roots none and is refused as one with no `main`
(golden `test_only_main`; typecheck's `top_decl` passes test-only
declarations over for each lookup by name that picks a root); each `@export`ed
function, in declaration order, which typecheck's export funnel records; then
the lang functions the backend's own lowering calls (the panic sink,
`string_literal`, `string_bytes` and `string_length`). A builtin
comparison of Strings reaches the String layer's `string_equals` (`==`,
`!=`) or `string_compare` (an ordering), each an item made where the first
such comparison is found. Items are
instantiated first in, first out, in the order they are found; within an item
blocks are walked in order, and statements and terminators in order, so the
item numbering is a function of the program alone. One root comes after the
worklist's end: std's entry executor, `__saw_exec_run_main` (its lang role),
which coroutine lowering roots, and runs the worklist on to its end for,
only when `main` has a lowered frame (`compiler/tests/coro/README.md`), so a
program with a plain `main` reaches none of it.

**Rendering** goes through the builder role (design 137). A format argument
of `print`, `panic` or `assert` that is not an integer, a `Bool` or a String
reaches the builder's `init(bytes:capacity:)`, its `len()` and its drop glue;
an interpolation reaches its `init()`, its `build()` and its drop glue; and
each value either renders reaches the item of its `Printable.format(into:)`,
which the render funnel (`render_of`) resolves through the requirement funnel,
once per type. A `Vector` literal reaches its type's `init()` and
`push(value:)`, and the rendering of `push`'s error, which a refused push
panics with. Each is made where the first construct needing it is found.

**Instantiation** copies the source function into the MIR's arenas after every
generic function, substituting every type: locals, places, projections,
operands, rvalues, a call's owner and instantiation. The copy keeps its
source's local and block numbering. Then each call is resolved to its item:

| call | resolved to |
|---|---|
| a function, a method, an `init` | its body at the receiver's arguments and the call's own |
| a trait requirement on a concrete owner | the owner's conformance: the member it writes, or the trait's default body under `Self`; a requirement met with neither, by a derivation or by a builtin type's own conformance, is its member glue (`resolve_requirement`, the one funnel); so is an `equals`, `compare` or `hash` the type meets with no conformance at all, through a tuple's, an Optional's or a fixed array's parts or a trivially copyable struct's or enum's automatic conformance (`met_without_conformance`); a `copy()` of `Copy` or `ExplicitCopy` on a struct, an enum, a tuple or an array is the type's copy glue instead, whether a conformance synthesizes it or the type meets the bound with no conformance at all, through the Copy tier or a composite's parts. Which glue answers is `glued`'s one decision |
| a trait requirement on an `any Trait` owner | no item: a vtable slot (below), which the backend calls through the receiver's vtable |
| a parameter's default value | the default's function |
| a window's open or close | the accessor's prologue or epilogue |
| a spawn site, a drive site | its root's task root (below) |
| an `extern` | its extern item |
| a builtin | itself, when the backend's slice lowers it |

**Glue** is made once per concrete type, as a synthesized concrete MIR function,
by one funnel (`glue_of` in `worklist.saw`), whose entry points are a drop
statement, a copy operand, and a `copy()` requirement call no written member
answers (`glued`):

- **drop glue** follows drop elaboration's resolution: the type's written
  `deinit`, then its owning fields in reverse declaration order, an enum's
  active payload under a switch on its case, a tuple's elements;
- **copy glue** runs where a value of a type that is not trivially copyable
  is copied, read from typecheck's tier: the `copy()` its `Copy` conformance
  writes when it writes one, else a memberwise rebuild whose parts copy by
  their own glue; typecheck refuses a `copy()` written outside a policy
  (golden `copy_hooks`; MIR's `declared_copy` answers for both stages).
  Concrete MIR spells a String's copy as a call of `String.copy()`, so copy
  glue appears only where a generic body's `copy` lands on such a type, or
  where a `copy()` call under a `T: ExplicitCopy` or `T: Copy` bound does
  (run programs `explicit_copy_bound_every_owner`,
  `vector_iter_owning_elements`).

A type that owns nothing has no glue. A function value's drop glue and copy
glue are items with no MIR body, which the backend writes as the release and
the retain of the environment the value may share (`function_value_glue`;
compiler/tests/run/README.md, "Closures"), and a call of one never suspends.
An escaping closure that captures something, by typecheck's
`closure_escaping`, keeps its captures on the heap, so mono makes the drop
glue of their tuple for its release (SL-525).

**Member glue** is made once per (requirement, concrete type) by its own
funnel (`member_glue_of`), the body a conformance has with nothing written:
a scalar's builtin hook, or an aggregate's `equals`, `compare` or `hash`. One
table in `glue.saw` (`member_refusal`) decides which cells are lowered, and
one builder (`build_member_glue`) builds each lowered cell's body. A scalar's:

| kind | `copy()` | `equals` | `compare` | `hash` | `format` |
|---|---|---|---|---|---|
| every integer width, signed and unsigned | the value | `==` | `<`, then `==`, at the type's signedness | its bits as an `Int` into `write_int`, a narrow width zero-extended | its decimal digits through `append(value: Int)` |
| `Bool` | the value | `==` | refused: the spec grants no `Comparable` (SL-715) | 1 or 0 into `write_int` | `true` or `false` through `append(s:)` |
| `Float` | the value | `==`, IEEE (`fcmp oeq`) | `<`, then `>`, else `Equal`, so a NaN pair is `Equal`; a generic `<=` or `>=` desugared to it is refused until SL-722 Q3 rules on NaN | 0 when `== 0.0`, else its bits read through its address, into `write_int` | refused: waits for `std.float`'s formatter (SL-722 U5) |
| a raw pointer | the value | refused: the spec grants no `Equatable` (SL-715) | | | |
| `Void` | nothing | | | | |

An unsigned 64-bit value past `Int.max` is appended as its quotient by ten,
when that is not zero, then its last digit. Each append panics as `try!` does
if a growable builder cannot grow. Each answer is Stage 0's, the hash words
included, so a `Map`'s order is too (run programs `scalar_copy`,
`scalar_equals`, `scalar_compare`, `scalar_hash`, `scalar_format`, the
probe `void_copy_hook`, and for `Float`, over the two zeros, a NaN and the
infinities, `float_hook_copy`, `float_hook_equals`, `float_hook_compare` and
`float_hook_hash`). An empty cell is one typecheck grants no
conformance for.

An aggregate's hook asks its parts' hooks in turn, each a requirement call
that the requirement funnel resolves as it resolves any, at the place the
glue was first reached, so a part's hook is its written member, a default
body or member glue again, and a part's refusal is reported there
(`mono.not-yet.derived`, a `Bool` field's `compare`; `mono.not-yet.aggregate`,
a raw pointer in a tuple). Each answer is Stage 0's:

| kind | `equals` | `compare` | `hash` |
|---|---|---|---|
| a struct | each field's, in declaration order, the first that fails deciding | each field's, in declaration order, the first not `Equal` deciding | each field's, in declaration order |
| a tuple | each element's, in order, the first that fails deciding | | each element's, in order |
| an enum | the same case, then each payload field's | the case's position, or a raw-backed case's value at the backing's signedness, then each payload field's | the case's position, or a raw-backed case's value zero-extended, through `write_int`, then each payload field's |
| an Optional | the same case, then the payload's | | 1 for `Some` and 0 for `None`, then the payload's |
| a fixed array | each element's, in index order | | each element's, in index order |

A tuple, an Optional and a fixed array meet `Equatable` and `Hashable`
through their parts and `Comparable` never (spec, Ordering), so typecheck
refuses their `compare` at the use (`operator.undefined.ordered-*`,
`type.bound.comparable-*`, `type.bound.sort-tuple`); the table refuses the
cell too.

A struct's or an enum's cell is its written `@synthesize`, or the automatic
`Equatable` and `Hashable` of a trivially copyable struct or payload-free
enum, which no conformance writes; a payload-carrying enum gets no automatic
conformance, and no struct or enum an automatic `Comparable`. The run
programs `aggregate_equals`, `aggregate_compare`, `aggregate_hash`,
`aggregate_map_keys` and `structural_equality_operator` (a structural `==`
the backend cannot compare in place, SL-759) pin the kinds at each position
(an operator, a bound, an interpolation, a `Map` key or `Set` element,
`Vector.sort`), and the probe
`automatic_hashable_through_bound` the one Stage 0 refuses. A `copy()` on a
struct, an enum, a tuple, an array or a function value is its copy glue
(above); every other hook on any other type is refused as `mono.not-yet`.

**Task roots.** A cooperative spawn site (`Task.spawn(f(x))`) is no call of
its root: the task runs the root in a *task root*, a separate specialization
of it (SL:architecture §3.8). That is an item of its own, keyed apart from
the root's ordinary item, so a function both spawned and called directly is
two items, and the dump names the task root `NAME task root`. The site makes
no ordinary item of its root. The first spawn site also reaches what its
lowering calls (`compiler/tests/coro/README.md`, "Spawn sites"): std's
`__saw_exec_task_box`, `__saw_exec_background` and
`__saw_exec_close_background`, and per site its handle type's `__saw_spawn`;
a std root that declares none of them is refused as `mono.not-yet`.
A drive site (`__saw_drive(f(x))`, `__saw_drive_steps(f(x))`) reaches its
root's task root the same way, since a driven root is framed whether or not
it suspends, and its first site of each form reaches std's
`__saw_exec_drive` or `__saw_exec_drive_steps` (`compiler/tests/coro/README.md`,
"Drive sites"). A task root reaches its result type's drop glue, which its
frame descriptor runs on a result nobody takes. A call of a park point
reaches what its lowering calls besides the park (`compiler/tests/coro/README.md`,
"Lowering"): the first timer park std's `__saw_exec_timer_deadline`, the
first descriptor or offload park `__saw_exec_io_register`, and the first
offload park `__saw_exec_offload_pipe`; a std root that declares none of them
is refused as `mono.not-yet`.

**Vtables** (spec, `any Trait` existentials; SL-721). An erasure, of a
reference into `&any Trait`, of a value into an erased box, or of a
`Result`'s concrete error into its erased box, attaches the vtable of its
concrete type at the existential's trait, made once per (type, trait) by one
funnel (`vtable_of`): a slot per requirement the trait dispatches, in
typecheck's `dispatch_requirements` order, and the concrete type's drop glue.
A dispatch, a call of a requirement whose owner is an `any Trait`, records
its slot, and so does the rendering of an erased value, whose
`Printable.format` it dispatches (`render_slot`). A slot is filled, through
the requirement funnel at the vtable's concrete type, only once something
dispatches it (`dispatch_of`), in every vtable of its trait whichever comes
first, so a requirement the program never dispatches is never instantiated
for an erased type. An erasure into a box also reaches its allocator's
`alloc`, and an erased box's drop glue its allocator's `dealloc`: the box
builds its allocator as `A()`, so it is a fieldless struct with no `init`,
or the erasure is refused as `mono.not-yet`. An erased box's drop glue has
no MIR body; the backend writes it (`compiler/tests/run/README.md`).

**Budget points.** Mono keeps every op-budget point; the backend writes
nothing for one. Coroutine lowering decides which stay live (SL:architecture
§3.9).

**Suspension.** Mono decides nothing about suspension: the dump prints each
call's flag as typecheck gave it, and coroutine lowering, the next stage,
decides which items suspend at their calls' concrete targets
(`compiler/tests/coro/README.md`).

## The dump

Each item, in item order, is a header line, then, for an item with a body,
its concrete function:

```
item #K: NAME [args T...] [inst T...] [self T]  (from #ORIGIN)
fn -> RESULT {
    let _0: TYPE;  // NOTE
    ...

    bb0: {
        STATEMENT;
        TERMINATOR; => #CALLEE
    }
}
```

NAME is the MIR dump's name for the source function, or `drop glue TYPE`,
`copy glue TYPE`, `member glue REQUIREMENT on TYPE`, `extern NAME`. A
function's name then adds what the MIR dump's spelling of its declaration
leaves out, wherever two declarations could share that spelling:

- `receiver shared` or `receiver exclusive`, for a `borrows` accessor, so a
  `&self` accessor and a `&var self` one of the same name and parameters
  (SL:borrowing §4) are told apart;
- `extends TYPE`, for a method of an extension of a type another module
  declares, since the spelling names that type by its last segment alone;
- `in module M`, for a top-level function of a module named like a
  vocabulary declaration, whose members print with no module (a module `Range`
  and the prelude's `Range.next()`).

A closure, a default value and an accessor's halves add their declaration's.
Every item has a name no other item has, and the backend spells each item's
symbols from it (golden `names`). `(from #ORIGIN)` names the item whose body
first reached it; a root has none. Statements and terminators print as the
MIR dump prints them (`compiler/tests/mir/README.md`), and a call terminator
is followed by ` => #K`, the item it reaches. A glue function's `_1` is its
parameter, `&var T` for drop glue and `&T` for copy glue.

## Layouts

`--layouts` prints the layout of every concrete type an item's local has, one
line each, sorted by spelling:

```
TYPE: size S align A KIND [offsets O...] [tag N, CASE=TAG @O..., ...] [of N]
```

KIND is `zero`, `int`, `float`, `pointer`, `record` (a struct, a tuple),
`enum`, `optional`, `closure` or `array`. The rules are Stage 0's, which
shares the runtime ABI with sawc2:

| type | layout |
|---|---|
| `Int8`, `UInt8`, `Bool` .. `Int64`, `UInt64`, `Int`, `UInt` | its width, aligned to it |
| `Float` | 8 bytes |
| a reference, `UnsafePointer<T>`, `FuncPointer<F>` | one word |
| a reference to an `any Trait`, an `UnsafePointer<any Trait>` (so an erased box) | two words, the value's address then its vtable's |
| `Void`, `Never` | zero-sized |
| a struct, a tuple | members in declaration order, each at its alignment |
| `Optional<T>` | a one-byte flag (`Some` 1, `None` 0), then `T` at its alignment |
| a raw-backed enum | its backing integer, each case's tag the value it states, read unsigned at the backing's width (`int tag N` in the table) |
| any other enum, `Result` included | an `Int32` tag (the case's ordinal), then each case's payload as a record from one offset, the largest payload alignment |
| a function value | its code pointer, then its environment pointer |
| `[T; N]` | N elements |

A raw-backed case's value is the evaluator's, which mono hands the target
before any layout is asked for (`target_for`). An `any` existential by value
and a type that contains itself inline are unsupported, and the backend
refuses a program reaching one.

**The C convention for `extern` calls** is the target's too: a scalar or a
pointer passes and returns directly, an `UnsafePointer<T>?` result is a
nullable pointer (null is `None`), and an aggregate by value is refused.

## Rules

| rule | refuses | fixture |
|---|---|---|
| `mono.not-yet` | what the backend's slice does not lower: a builtin outside it, a format argument or an interpolated part whose rendering the slice does not make, a requirement no member, default or member glue in the slice meets, a call of a body this program does not lower, an erased box whose allocator is not a fieldless struct with no `init`, a generic `<=` or `>=` at `Float` (a `compare` call MIR's ordering mark names), whose answer over a NaN is unruled (SL-722 Q3) | `mono.not-yet.format`, `mono.not-yet.std`, `mono.not-yet.aggregate`, `mono.not-yet.derived`, `mono.not-yet.bool-order`, `mono.not-yet.pointer-equality`, `mono.not-yet.float-order-le`, `mono.not-yet.float-order-ge` |
| `mono.depth` | a concrete argument nested more than 64 deep, once per program, at the first call that met the limit | `mono.depth`, `mono.depth.method`, `mono.depth.recursive`, and `mono.depth.branching`, whose argument doubles its parts at each step |
| `atomic.width` | an `Atomic<X>` at an `X` other than `Int` that only an instantiation forms, once per type, where the item was reached; one a written or inferred position carries is typecheck's (SL:open-questions D38) | `atomic.width` |
| `transfer.no-move` | a generic body's move out of a place, which typecheck records where the type names a type parameter, at an instantiation that makes the type `NoMove`: the first such move of each declaration at each set of arguments, its body's, its closures' and its accessor halves' together. A spelled `move`, a `[move x]` capture and a local's by-value read at its last use all count; the fresh placement of a by-value parameter no reference has named does not. A concrete type's is typecheck's (SL-662) | `transfer.no-move`, a `Vector`'s growth; `.element`, `Vector.pop`'s move out of its buffer; `.forward`, a read at its last use; `.capture`, a `[move x]` capture; `.placement-after-borrow`, the placement once a reference named the parameter; `.take`, an Optional's payload; `.map`, a `Map`'s entries |

A refusal whose node lies in std or the builtin module is reported at the
nearest call the program writes on the chain of items that reached it
(each item's origin and the node there), its message naming the std
position, since that call is the one the program's author can change; the
backend's `backend.not-yet` refusals go through the same funnel.

Unbounded instantiation (polymorphic recursion) is ruled to be refused before
mono, by a check on the generic call graph (SL:architecture §3.8); that check
is SL-507. `mono.depth` is mono's backstop, so mono never loops: until that
check lands, polymorphic recursion passes typecheck and reaches the limit
here (`mono.depth.recursive`), as a written type does (`mono.depth`). The
depth is typecheck's `nesting_depth`, memoized by type, and the copy glue's
triviality is its memoized `is_trivial`, so the limit is met in time linear in
the depth however a type shares its parts (`mono.depth.branching`).

## The lane

`mono_lane.py` checks that each golden program's `--dump` and `--layouts`
records equal its `.mono` and `.layouts` files byte for byte (`--write`
rewrites them, for review) and carry no `ERROR` or `INVARIANT` line; that each
fixture in `refuse/` is refused first at its header's position by the rule its
name starts with, and every rule has a fixture; and that each type of a
layout table that Stage 0 can spell (not a reference, a function type, `Void`
or `Never`) has Stage 0's size and alignment: the probe is the golden
program with its `main` renamed and a new one printing `sizeof` and `alignof`
of each type, and the lane compares the table with what Stage 0's recorded run
of the probe printed. It never runs Stage 0: the record is
`stage0/TRIPLE/NAME.stage0` for host TRIPLE, in the format of
`compiler/tests/oracle.py`, holding the SHA-256 prefix of the probe's text,
so a table that gains or loses a row makes it stale, and a missing or stale
record fails, naming `mono_lane.py --stage0`, which builds and runs every
probe with the v0 compiler (`oracle.v0_compiler`) and rewrites the records. A
record naming no golden program fails too. A difference fails unless
`layout_exceptions.tsv` (`TYPE<TAB>reason`) gives the reason, and an exception
no difference uses fails as stale. A bare `Void` or `Never` is not compared
(Stage 0's `alignof<Void>()` is an internal error), but every type holding
one is: golden `voids` reaches them, and `Void?` and the types holding it are
the exceptions, Stage 0 giving `Void` a byte of its own inside an Optional.
A golden program that Stage 0 cannot build says so in a `// stage 0: REASON`
line, as a run-lane probe does, and its table is compared with nothing: golden
`names`, whose `borrow` blocks and qualified extension head Stage 0 cannot
parse.

The lane also runs each subcommand `--lowerings` counts for over the golden
programs, two run-lane programs with constants (`statics`, `layout_asserts`),
a program mono refuses and one refused before mono, and requires each record's
count. The paths the driver cannot count, coroutine lowering's (the front half
of `sawc2 build`) and a runtime source's, are the unit program
`compiler/mono/tests/one_lowering.saw`, which reads the count off the program
each returns.
