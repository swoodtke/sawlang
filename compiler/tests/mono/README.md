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
```

## `sawc2 mono`

```sh
.build/sawc2 mono (--dump | --layouts | --check) [--notes] [--std-root DIR]
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

The evaluator owns the MIR program it runs over and hands nothing back, so
the statics' values come from a second lowering of the same file. Both
lowerings are functions of the same input, so their declarations are
numbered alike; mono checks the counts agree.

## Items

An **item** is a function's body at concrete arguments, a type's drop or copy
glue, or an `extern` the program calls by its C name. A function item's
identity is its source MIR function and its canonical concrete arguments:

- the receiver type's arguments, for the parameters of the type an extension
  method extends;
- the function's own type arguments;
- `Self`, for a trait's default body.

Typecheck interns types by canonical form with defaults filled (SL-382), so
two spellings of one instantiation are one item. A closure, a default
value's function and an accessor's prologue and epilogue are items under
their parent's arguments. A glue item is (drop or copy, concrete type); an
extern item is its C name, so two std modules declaring one seam call one
symbol.

**The worklist** starts from the roots, in this order: the entry module's
`main`, then the lang functions the backend's own lowering calls (the panic
sink, `string_literal`, `string_bytes` and `string_length`). A builtin
comparison of Strings reaches the String layer's `string_equals` (`==`,
`!=`) or `string_compare` (an ordering), each an item made where the first
such comparison is found. Items are
instantiated first in, first out, in the order they are found; within an item
blocks are walked in order, and statements and terminators in order, so the
item numbering is a function of the program alone.

**Instantiation** copies the source function into the MIR's arenas after every
generic function, substituting every type: locals, places, projections,
operands, rvalues, a call's owner and instantiation. The copy keeps its
source's local and block numbering. Then each call is resolved to its item:

| call | resolved to |
|---|---|
| a function, a method, an `init` | its body at the receiver's arguments and the call's own |
| a trait requirement on a concrete owner | the owner's conformance: the member it writes, or the trait's default body under `Self` |
| a parameter's default value | the default's function |
| a window's open or close | the accessor's prologue or epilogue |
| an `extern` | its extern item |
| a builtin | itself, when the backend's slice lowers it |

**Glue** is made once per concrete type, as a synthesized concrete MIR function,
by one funnel (`glue_of` in `worklist.saw`), whose entry points are a drop
statement and a copy operand:

- **drop glue** follows drop elaboration's resolution: the type's written
  `deinit`, then its owning fields in reverse declaration order, an enum's
  active payload under a switch on its case, a tuple's elements;
- **copy glue** runs where a value of a type that is not trivially copyable
  is copied, read from typecheck's tier: the type's written `copy()` when its
  conformance writes one, else a memberwise rebuild whose parts copy by their
  own glue. Concrete MIR spells a String's copy as a call of `String.copy()`,
  so copy glue appears only where a generic body's `copy` lands on such a
  type.

A type that owns nothing has no glue, and neither does a function value: a
closure capturing a value that owns something is refused where it is built.

**Budget points.** Spawn is not lowered, so no task root exists and every
op-budget point is inert; the backend writes nothing for one. Coroutine
lowering decides which stay live (SL:architecture §3.9).

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
`copy glue TYPE`, `extern NAME`. `(from #ORIGIN)` names the item whose body
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
| `Void`, `Never` | zero-sized |
| a struct, a tuple | members in declaration order, each at its alignment |
| `Optional<T>` | a one-byte flag (`Some` 1, `None` 0), then `T` at its alignment |
| any other enum, `Result` included | an `Int32` tag (the case's ordinal), then each case's payload as a record from one offset, the largest payload alignment |
| a function value | its code pointer, then its environment pointer |
| `[T; N]` | N elements |

A raw-backed enum, an `any` existential and a type that contains itself
inline are unsupported, and the backend refuses a program reaching one.

**The C convention for `extern` calls** is the target's too: a scalar or a
pointer passes and returns directly, an `UnsafePointer<T>?` result is a
nullable pointer (null is `None`), and an aggregate by value is refused.

## Rules

| rule | refuses | fixture |
|---|---|---|
| `mono.not-yet` | what the backend's slice does not lower: a builtin outside it, a format argument that is not an integer, a Bool or a String, a requirement no member or default meets, a call of a body this program does not lower, a closure capturing an owning value | `mono.not-yet`, `mono.not-yet.format`, `mono.not-yet.std` |
| `mono.depth` | a concrete argument nested more than 64 deep, once per program, at the first call that met the limit | `mono.depth`, `mono.depth.method` |

A refusal whose node lies in std or the builtin module is reported at the
nearest call the program writes on the chain of items that reached it
(each item's origin and the node there), its message naming the std
position, since that call is the one the program's author can change; the
backend's `backend.not-yet` refusals go through the same funnel.

Unbounded instantiation (polymorphic recursion) is ruled to be refused before
mono, by a check on the generic call graph (SL:architecture §3.8); that check
is SL-507. `mono.depth` is mono's backstop, so mono never loops. Today any
recursive generic call, polymorphic or not, meets an invariant of
typecheck's body verifier first (SL-509), so the fixture reaches the limit
with a written type instead.

## The lane

`mono_lane.py` checks that each golden program's `--dump` and `--layouts`
records equal its `.mono` and `.layouts` files byte for byte (`--write`
rewrites them, for review) and carry no `ERROR` or `INVARIANT` line; that each
fixture in `refuse/` is refused first at its header's position by the rule its
name starts with, and every rule has a fixture; and that each type of a
layout table that Stage 0 can spell (not a reference, a function type, `Void`
or `Never`) has Stage 0's size and alignment: the lane builds the golden
program with Stage 0, its `main` renamed and a new one printing `sizeof` and
`alignof` of each type, and compares. A difference fails unless
`layout_exceptions.tsv` (`TYPE<TAB>reason`) gives the reason, and an exception
no difference uses fails as stale. A bare `Void` or `Never` is not compared
(Stage 0's `alignof<Void>()` is an internal error), but every type holding
one is: golden `voids` reaches them, and `Void?` and the types holding it are
the exceptions, Stage 0 giving `Void` a byte of its own inside an Optional.
