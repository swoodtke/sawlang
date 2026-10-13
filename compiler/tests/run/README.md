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
  runtime_dirent.ll  the `.ll` `sawc2 runtime` writes for sawc/rt/host_macos/dirent.saw, pinned
  probes/        programs the lane runs apart from the comparison
```

## `sawc2 build`

```sh
.build/sawc2 build [-O0|-O1|-O2|-Os|-Oz] [--std-root DIR] [--target TRIPLE]
                   [--module-path NAME=DIR]... FILE [-o OUT]
.build/sawc2 build [...] --emit-ll FILE
```

`sawc2 build FILE` compiles the program, writes its whole `.ll` to `OUT.ll`
(`-o` defaults to `.build/NAME`), and runs
`clang -target TRIPLE SPEED -x ir OUT.ll -x none RUNTIME... -o OUT`,
blocking until clang exits. A refusal prints its record (as `sawc2 coro
--check` prints one), writes nothing and exits 1; a failure to write the
`.ll` or to start clang prints why and exits 1; otherwise the exit status
is clang's. The `.ll` is written unbuffered and closed explicitly, and clang
is waited for explicitly, so no step's result rests on a `deinit` (SL:hazards
S28, whose workaround markers name the canonical buffered form). With
`--emit-ll` the `.ll` goes to standard output instead and nothing is linked.
The `.ll` opens with its link manifest, as comment lines:

```
; sawc2 link manifest
; target arm64-apple-darwin
; speed -O0
; runtime hosted
```

The module's `target triple` is the target's clang triple
(`target_clang_triple` in `compiler/target`), and the same string is clang's
`-target`, so clang compiles the module as written and needs asking nothing.
For `arm64-apple-darwin` that is `arm64-apple-macosx11.0.0`: a versionless
Darwin triple is one clang replaces with the host's own deployment version,
with a warning, and learning that version would take capturing clang's
output.

A hosted build links for the host alone, since the runtime objects are the
host's. They are named by the runtime manifest, `sawc2-runtime.txt` in the
directory of the executable that runs: its real path, from
`Env.executable_path()` (`_NSGetExecutablePath`, then realpath(3)), so a
sawc2 run by a bare name through `PATH`, or through a symbolic link, finds the
manifest beside the file it really is. The manifest is a `target TRIPLE` line
naming the sawc2 target the objects are built for, then an `object PATH` line
per object, which is what `sawc2 runtime` prints; `compiler/tools/build.py`
writes it beside Stage 1 and Stage 2 from Stage 1's `sawc2 runtime` (below).
A `--target` naming another target is refused, saying it is not the host,
before anything is written, rather than link a host binary from a module laid
out for another target. The runtime is built at the module's own target, so a
link prints nothing. The speed flag passes through the driver's one
`driver_speed_level` funnel (design 265); `-O0` is the default.

## `sawc2 runtime`

```sh
.build/sawc2 runtime [--std-root DIR] [--rt-root DIR] --out DIR
.build/sawc2 runtime [--std-root DIR] --emit-ll FILE
```

`sawc2 runtime --out DIR` builds the host's runtime (designs 113b and 149,
SL:open-questions D41) into `DIR`, which must exist: sawc2 has no API to
create a directory, so a missing one is refused, saying so. The sources are
compiled against the new std, `--std-root std` by default, the one std they
are written for. The ABI table
(`compiler/typecheck/src/runtimeabi.saw`) lists the host's sources under the
runtime root (`--rt-root`, `sawc/rt` by default): every `.saw` of `common/`,
then of `host_macos/`. Each is compiled as a runtime source to `DIR/NAME.ll`,
unbuffered and closed explicitly, and by `clang -c -target TRIPLE -O2 -x ir`
to `DIR/NAME.o`; then `clang -c shim.c -O2 -fno-strict-aliasing -target
TRIPLE` writes `DIR/shim.o`. TRIPLE is the module's (`target_clang_triple`),
so the objects and the programs they link into name one macOS. A runtime
source is checked with `runtime_build` set: its exports may be the frozen
seams it owns, each held to the table's arity and widths (the typecheck
lane's `export.*` rules), it needs no `main`, and mono roots its exports. The
backend defines each export under its C symbol with external linkage, every
other function internal, and emits no `main`, no `__saw_rt_get_argc` or
`__saw_rt_get_argv`, which are the program's, and no backtrace table.

Then the seams are counted: the exports of every source and the seams the
table says the shim defines must be the table's runtime seams, each exactly
once. A seam no object defines, one two objects define, and an export that is
no runtime seam are each printed, and the command exits 1 with no manifest, so
a runtime missing a seam never links. Otherwise it prints the runtime
manifest naming the fourteen objects. A refused source prints its record, as
`sawc2 build` does; a clang that fails gives its exit status. Nothing is
cached here: `build.py` keys and caches the directory (D41's ruling). Two
builds into two directories write the same bytes. With `--emit-ll FILE`, that
one runtime source's `.ll` goes to standard output.

## The backend

One LLVM function per item, in item order; every layout fact is the target
description's (`compiler/tests/mono/README.md`, "Layouts").

- **Values.** A local is an `alloca`, scalar typed (`iN`, `double`, `ptr`) or
  `[N x i8]` for a memory value. A place is its root's address and a
  `getelementptr` per projection at the target's offset; a `(*P)` is a load,
  an index into a raw pointer scales by the element's size, and a forced
  payload (`o!`, `try!`) checks the case first. A scalar value moves as an SSA
  value, a memory value by `memcpy`; a `copy` of a type with copy glue calls
  the glue. An `as` between a raw pointer and an integer of the pointer's
  width is `inttoptr` or `ptrtoint`, so `0 as UnsafePointer<T>` is null.
- **Calls.** A scalar parameter passes by value; a memory parameter passes
  the address of a value the callee copies on entry; a memory result comes
  back through a leading `sret` pointer. A function value is called through
  its code pointer with its environment first. An `extern` is called by the C
  convention the target gives; a variadic one through its function type, each
  extra argument by C's default promotions (an integer narrower than 32 bits
  widened to `i32` by its signedness).
- **Checks.** `+`, `-` and `*` use `llvm.{s,u}{add,sub,mul}.with.overflow` by
  the operand's signedness, `&+`, `&-` and `&*` wrap; `/` and `%` check a zero
  divisor and the signed `MIN / -1`; a shift checks its count; an `as` that
  can lose its value checks that it fits and names the value; a forced payload
  checks its case. Each panics with Stage 0's wording, `panic at FILE:LINE:
  REASON` (design 122), through the panic sink.
- **The failure funnel.** Every failing path, a check's, `panic`'s, a failed
  `assert`'s and a refused literal push's, is one call of a compiler helper,
  then `unreachable`: `__saw_fail_overflow`, `_divide`, `_shift`, `_unwrap`
  and `_try` take the site's file and line, `__saw_fail` a constant message
  besides, `__saw_fail_signed` and `_unsigned` a reason and the value, and
  `__saw_fail_parts` a lead and a table of the message's parts in the
  caller's frame. The helpers render the message into their own 512-byte
  buffer and hand it to the panic sink, so a checked function keeps only its
  compare and branch, and clang can inline an accessor such as `Vector.[]`.
  They are `noinline` and `noreturn` but not `cold`: `cold`, like `!prof`
  weights on the branches, sets off clang's hot/cold splitting, which grows
  the object with a `.cold.N` function per failing block and measured no
  faster (SL-528). The funnel's entry points are named in
  `compiler/llvm/src/prims.saw`.
- **Builtins.** `print` reads every argument first, then writes each piece of
  its format string and each rendered argument through `__saw_rt_write`, then
  a line break; a String argument's bytes and length are read in place
  through the `string_bytes` and `string_length` roles, and a String handed
  over by `move` is dropped after. `panic` and a failed `assert` render the
  same parts after their `panic at` prefix, through the failure funnel: a
  message over 508 bytes is cut there, on a UTF-8 boundary, and
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
  for a `Void` main. A runtime source has no entry and no accessors.
- **Exports.** Each `@export`ed function is a root, defined under its C
  symbol with external linkage, an integer narrower than 32 bits taken and
  returned `signext` or `zeroext` as C does; an `extern` naming the symbol is
  called with no declaration beside it. An exported static is refused as
  `backend.not-yet`.
- **Determinism.** Functions are written in item order and globals in first
  use; every symbol is derived from what the item is (`@"saw NAME"`).

| rule | refuses | due program |
|---|---|---|
| `backend.not-yet` | what the backend does not lower yet: a Float constant, an operator on a Float, or on anything but an integer, a Bool, a String, two raw pointers or the memory values compared part by part, an erasure, a slice, a take capture, a fixed array, a repeat, a `Map` or a `Set` literal, a static that is not an integer or a Bool, an exported static, a conditional borrow, an aggregate crossing the C convention, a pointer cast to or from an integer narrower than a pointer, an unsupported layout, a `main` returning neither `Void` nor `Int`; a constant is refused at its own spelling, inside an aggregate too | `float_field` |

**Suspension.** The backend's input is coroutine lowering's program
(`compiler/tests/coro/README.md`), which refuses every item that needs a
frame (`coro.not-yet`) and every suspending cycle (`coro.suspending-cycle`),
so no suspending call reaches the backend and it never emits one as a plain
call that blocks the thread. Every op-budget point that reaches it is
outside a frame, and writes nothing. The due programs `suspend_blocking_main`,
`suspend_cycle` and `suspend_budget_point` pin the two refusals at a build.

## The lane

`run_lane.py` builds every program both ways, eight at a time, under
`.build/run-lane/`. The sawc2 side is `sawc2 build` run by the binary the
runner selected (Stage 2 by default, `compiler/tools/build.py`). The lane
compares:

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
- a build that links prints nothing, standard output or standard error: the
  linker has no object built for another macOS to warn about;
- `hello.saw`'s `.ll`, as `sawc2 build --emit-ll` writes it for the default
  target, equals `hello.ll` byte for byte, and `sawc/rt/host_macos/dirent.saw`'s,
  as `sawc2 runtime --emit-ll` writes it, `runtime_dirent.ll` (`--write`
  rewrites both);
- `sawc2 build --target` refuses every target but the host's, saying so, and
  leaves no binary and no `.ll`;
- `sawc2 runtime --out` writes the same files, byte for byte, into two
  directories, and refuses a copy of `sawc/rt` that leaves a seam undefined
  (`sleep.saw` without its `@export`) or defines one twice (`dirent.saw`
  exporting `os_ops.saw`'s `__saw_rt_fs_chdir`), naming the seam and printing
  no manifest;
- `probes/executable_path.saw`, built by sawc2 and by Stage 0, run by a bare
  name that a renamed relative symbolic link on `PATH` resolves, from another
  working directory, prints its binary's real path: what the manifest lookup
  rests on.

Stage 0 is the oracle: a difference is a sawc2 bug until shown otherwise
(SL:architecture §5).

## The timing report

`run_lane.py --bench` builds each kernel of `bench/` with `sawc2 build -O2`
and with Stage 0, runs each binary once to warm it, then five times, and
prints the best time of each and their ratio:

- `sieve`: a sieve to two million over a `Vector<Bool>`, `set` and `[]`;
- `sort`: an insertion sort of 20,000 `Int`s, whose inner loop is all `v[k]`
  and `v.set`, so it shows whether the checked accessors inline (SL-528);
- `collatz`: checked arithmetic with no memory traffic;
- `accumulate`: a million pushes, then a fold over the elements.

It gates nothing. A build that fails, or two binaries whose outputs differ,
fail the report, but a time never does: it is only as good as the machine is
quiet, so quote one from an idle machine and repeat a noisy run. The runner
never runs it.

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

Building the runtime (SL-522, U7c M2) met seven classes. The first six were
the new std's cell and `Atomic`, its sequentially consistent atomic
intrinsics, layout `static_assert`s, pointer-integer casts, variadic extern
calls and pointer arithmetic (SL:open-questions D38 to D40), pinned by
`atomic_ops`, `layout_asserts`, `pointer_address`, `variadic_extern` and
`pointer_offset`; the seventh was the runtime-build mode itself, `sawc2
runtime` above (D41). With it, every source of `sawc/rt/common/` and
`sawc/rt/host_macos/` builds with no refusal.
