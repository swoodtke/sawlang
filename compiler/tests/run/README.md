# compiler/tests/run: the backend and `sawc2 build`, against Stage 0

The programs the LLVM backend (`compiler/llvm`, package `sawllvm`, SL-505)
and `sawc2 build` are held to: each is built by sawc2 against the new std and
by Stage 0 against its own, both binaries run, and their output compared.

```
run/
  README.md      this specification
  run_lane.py    the lane compiler/tests/run.py runs
  NAME.saw       a program
  hello.ll       the `.ll` sawc2 writes for hello.saw, pinned
```

## `sawc2 build`

```sh
compiler/driver/sawc2 build [-O0|-O1|-O2|-Os|-Oz] [--std-root DIR] [--target TRIPLE]
                            [--module-path NAME=DIR]... FILE [-o OUT]
```

The compiler binary spawns no process (SL:architecture §4).
`.build/sawc2 build ... FILE` writes the program's whole `.ll` to standard
output and exits 0, or prints the record of what refused it (as `sawc2 mono
--check` prints one) and exits 1. The `.ll` opens with its link manifest, as
comment lines:

```
; sawc2 link manifest
; target arm64-apple-darwin
; speed -O0
; runtime hosted
```

The target is `--target` (default `arm64-apple-darwin`); `--module-triple
TRIPLE` makes the module's `target triple` line name TRIPLE rather than the
target, the spelling of the clang that will compile it.

`compiler/driver/sawc2` is the script that connects the pieces. A build
links for the host alone, since the runtime objects are the host's: the
script asks `$CLANG` (else `clang`) which triple it compiles IR for here
(`clang -###`), takes the sawc2 target that triple is, and refuses a
`--target` naming any other one before anything is written, rather than
link a host binary from a module laid out for another target. It then runs
the binary at the host's target with that triple as the module's, writes
`OUT.ll` (`-o` defaults to `.build/NAME`), and runs
`clang SPEED -x ir OUT.ll RUNTIME... -o OUT`, which compiles the module for
the triple it names, with no override and nothing silenced. A
hosted runtime is Stage 0's prebuilt one, the objects Stage 0 builds and
caches under `.build/rt/<key>/`: `compiler/tools/runtime_objects.py` asks
Stage 0's `sawc/rt_build.py` for them at llvmlite's host triple, which is
what a Stage 0 build links, so the cache a Stage 0 build filled is the one
used. The script finds the binary at `.build/sawc2` (`$SAWC2_BIN` overrides
it) and Python as `$SAW_PYTHON`, the repository's `.venv`, or `python3`. The
speed flag passes through the driver's one `driver_speed_level` funnel
(design 265); `-O0` is the default. Every other command runs the binary as
it is.

## The backend

One LLVM function per item, in item order; every layout fact is the target
description's (`compiler/tests/mono/README.md`, "Layouts").

- **Values.** A local is an `alloca`, scalar typed (`iN`, `double`, `ptr`) or
  `[N x i8]` for a memory value. A place is its root's address and a
  `getelementptr` per projection at the target's offset; a `(*P)` is a load,
  an index into a raw pointer scales by the element's size, and a forced
  payload (`o!`, `try!`) checks the case first. A scalar value moves as an SSA
  value, a memory value by `memcpy`; a `copy` of a type with copy glue calls
  the glue.
- **Calls.** A scalar parameter passes by value; a memory parameter passes
  the address of a value the callee copies on entry; a memory result comes
  back through a leading `sret` pointer. A function value is called through
  its code pointer with its environment first. An `extern` is called by the C
  convention the target gives.
- **Checks.** `+`, `-` and `*` use `llvm.{s,u}{add,sub,mul}.with.overflow` by
  the operand's signedness, `&+`, `&-` and `&*` wrap; `/` and `%` check a zero
  divisor and the signed `MIN / -1`; a shift checks its count; an `as` that
  can lose its value checks that it fits and names the value; a forced payload
  checks its case. Each panics with Stage 0's wording, `panic at FILE:LINE:
  REASON` (design 122), through the panic sink.
- **Builtins.** `print` reads every argument first, then writes each piece of
  its format string and each rendered argument through `__saw_rt_write`, then
  a line break; a String argument's bytes and length are read in place
  through the `string_bytes` and `string_length` roles, and a String handed
  over by `move` is dropped after. `panic` and a failed `assert` render the
  same parts after their `panic at` prefix into stack scratch for the panic
  sink: a message over 508 bytes is cut there, on a UTF-8 boundary, and
  marked `…` before its line break (spec, Panic). Stage 0 cuts on a byte, so
  the two differ only where the cut falls inside a scalar. Integers render through the compiler's own
  `__saw_render_int` and `__saw_render_uint` helpers. Any other argument
  renders through its `Printable.format` into a fixed builder over 512 bytes
  of stack scratch, Stage 0's size, so a longer rendering is cut and marked
  `…` by the builder. `sizeof` and `alignof`
  are the target's; the four `__saw_atomic_*` builtins are LLVM atomics of
  the orderings their names state.
- **Building through the builder.** An interpolation builds its String
  through a growable builder: `init()`, each part's `Printable.format` in
  order, `build()`, then the builder's drop. A `Vector` literal is its type's
  `init()`, then a `push` per element in order; a refused push panics with
  `collection literal: ` and its error, rendered as a format argument is.
- **Comparisons.** An integer, a Bool or a raw-backed enum compares by
  `icmp` at its signedness. A String compares its bytes through the String
  layer's `string_equals` and `string_compare`, each operand read in place,
  an ordering read off the `Ordering` as a declared `compare`'s is. Two raw
  pointers compare by address; any other pointer-sized operand, a
  reference or a function pointer, is refused. `==` and `!=` on a trivially
  copyable value in memory compare part by part: a payload-free enum by its
  case, an Optional by its case and then, when both are present, its
  payload, a struct or tuple member by member; a type declaring its own
  `Equatable`, a String or a Float inside one is refused.
- **Strings and statics.** A String literal is a private constant in the
  String layer's literal block (an immortal refcount, the length, the bytes,
  a NUL), wrapped through `string_literal`; a literal message's bytes are
  written as they are. A static is a global holding the evaluator's value.
- **The entry.** The C `main(argc, argv)` keeps both for the argument
  accessors the compiler emits into every program (rt/ABI.md, "Program
  arguments"), calls the program's `main`, and exits with its `Int`, or 0
  for a `Void` main.
- **Determinism.** Functions are written in item order and globals in first
  use; every symbol is derived from what the item is (`@"saw NAME"`).

| rule | refuses | due program |
|---|---|---|
| `backend.not-yet` | what the backend does not lower yet: a Float constant, an operator on a Float, or on anything but an integer, a Bool, a String, two raw pointers or the memory values compared part by part, an erasure, a slice, a take capture, a fixed array, a repeat, a `Map` or a `Set` literal, a static that is not an integer or a Bool, a conditional borrow, a variadic extern or an aggregate crossing the C convention, an unsupported layout, a `main` returning neither `Void` nor `Int`; a constant is refused at its own spelling, inside an aggregate too | `float_field` |

## The lane

`run_lane.py` builds every program both ways, eight at a time, under
`.build/run-lane/`. The sawc2 side is the binary the runner selected (Stage 2
by default, `compiler/tools/build.py`), handed to the script as `$SAWC2_BIN`.
The lane compares:

- a plain program passes when sawc2's binary, built at -O0 and again at -O2,
  writes the same bytes as Stage 0's and exits with the same status, a
  panic's abort included;
- a `// differs: REASON` program compares its exit status and every line
  but a `panic at` line's location, for a panic std raises, since each
  compiler's std is its own file;
- a `// differs:` program whose REASON cites an SL:hazards entry is one whose
  output Stage 0 orders wrongly, a destruction timing it gets wrong (C10,
  C11): its `// prints: LINE` headers, one per line of output, are the
  oracle in Stage 0's place. sawc2 must print exactly them, Stage 0 the same
  lines in another order, since such a hazard moves a line and never adds or
  loses one, and both must exit alike; a Stage 0 that prints them in order
  fails the program too, so the line comes off when the hazard no longer
  shows there;
- a `// due: REASON` program, with `// refuses: RULE at L:C` after it, must
  be refused there by that rule; once sawc2 builds it the lane fails, so the
  lines come off as the slice grows; every rule of `ll_rules` has one;
- `hello.saw`'s `.ll`, as the binary writes it for the default target with
  no module triple, equals `hello.ll` byte for byte (`--write` rewrites it);
- `sawc2 build --target` refuses every target but the host's, saying so, and
  leaves no binary.

Stage 0 is the oracle: a difference is a sawc2 bug until shown otherwise
(SL:architecture §5).

## The self-build census

What stood between `sawc2 build` of sawc2's own driver and a working Stage 2
(SL-398, U7b), class by class, in the order met. Mono stops at its refusals,
so the backend's classes were counted with mono's set aside, and the backend
reports only the first refusal in each function, so its counts are functions
refused, not sites.

| class | count | resolution | pin |
|---|---|---|---|
| `mono.not-yet`: `Printable.to_string()` on `Int`, a builtin conformance with no member written | 9 | the requirement funnel answers it with Printable's default body, whose `format` is member glue: a signed integer appended through the builder's `append(value: Int)` | `int_to_string`; mono `refuse/mono.not-yet.unsigned` |
| `mono.not-yet`: a `SystemError` format argument of `print` | 2 | a format argument that is not an integer, a Bool or a String renders through its `Printable.format` into a fixed builder over 512 bytes of stack scratch | `printable_format` |
| `backend.not-yet`: a raw-backed enum's layout (`Alt`, `Rule`, `OpenMode`, and the types holding one) | 167, and 475 functions whose result or local it was | the target lays one out as its backing integer, each case's tag the evaluator's value for it; a cast reads the backing's signedness | `raw_enum`; mono golden `layouts` |
| `backend.not-yet`: `==` and `!=` on a payload-free enum | 590 | the tags compare | `enum_equality` |
| `backend.not-yet`: `T.min`, `T.max` | 2 | the bound of the constant's own type | `integer_bounds` |
| `backend.not-yet`: an interpolation | 1 | the growable builder: `init()`, each part's `format`, `build()` | `interpolation` |
| `backend.not-yet`: a `Vector` literal | 1 | its type's `init()`, then a `push` per element, a refused push panicking with its error | `collection_literal` |
| `backend.not-yet`: `==` on an `Alt?`, met once the enum classes were gone | 1 | trivially copyable memory values compare part by part, an Optional's payload only when both are present | `value_equality` |
| clang: `__saw_rt_get_argc` declared by std's `extern` and defined by the entry point | 1 | the entry point's definitions stand for the declaration | `program_arguments` |
| Stage 2 wrong: every token's text lexed as decimal byte values | the lexer's every token | the new std lacked `StringBuilder.append(b: Byte)`, so a `Byte` argument widened into `append(value: Int)` (SL-529) | `byte_append` |

With these, sawc2 builds its driver with no refusal, clang accepts the
module, and the link is `.build/sawc2-stage2`, which the fixpoint lane
(`compiler/tests/fixpoint/fixpoint_lane.py`) holds to Stage 1.
