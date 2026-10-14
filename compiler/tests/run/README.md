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
  noalias.defines  the `define` lines sawc2 writes for noalias.saw's own functions, pinned
  runtime_dirent.ll  the `.ll` `sawc2 runtime` writes for sawc/rt/host_macos/dirent.saw, pinned
  frame_pointers.saw  a program defining one function of each kind, whose defines the lane checks
  probes/        programs the lane runs apart from the comparison
  modules/       packages a program imports as `modules.NAME`, never run alone
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
`Env.executable_path()` (the runtime's `__saw_rt_executable_path`), so a
sawc2 run by a bare name through `PATH`, or through a symbolic link, finds the
manifest beside the file it really is. The manifest is a `target TRIPLE` line
naming the sawc2 target the objects are built for, a `clang PATH` line naming
the clang that compiles and links for it, then an `object PATH` line per
object, which is what `sawc2 runtime` prints; `compiler/tools/build.py`
writes it beside Stage 1 and Stage 2 from Stage 1's `sawc2 runtime` (below).
The manifest is how sawc2 knows its host: its `target` is the default of
`sawc2 build`, of `--emit-ll` and of `sawc2 runtime`, so a sawc2 built on
Linux aarch64 builds for `aarch64-unknown-linux-gnu`, and the link runs the
manifest's clang, never a `clang` found on `PATH`.
A `--target` naming another target links against that target's own runtime,
named by `sawc2-runtime-TRIPLE.txt` beside the binary, which
`compiler/tools/build.py --runtime TRIPLE` writes only once its clang passes
the opaque-pointer check for that target (below) and the runtime, shim.c and
its C headers included, builds for it. A target with no such
manifest is refused, saying it is not the host and has no runtime, before
anything is written: a build never links the host's objects into a module laid
out for another target. In the Linux VM, `--target x86_64-unknown-linux-gnu`
is configured that way, and Rosetta runs what it links. The runtime is built at the module's own target, so a
link prints nothing. The speed flag passes through the driver's one
`driver_speed_level` funnel (design 265); `-O0` is the default.

## `sawc2 runtime`

```sh
.build/sawc2 runtime [--std-root DIR] [--rt-root DIR] [--target TRIPLE] [--clang PATH] --out DIR
.build/sawc2 runtime [--std-root DIR] [--target TRIPLE] --emit-ll FILE
```

`sawc2 runtime --out DIR` builds a target's runtime (designs 113b and 149,
SL:open-questions D41) into `DIR`, which must exist: sawc2 has no API to
create a directory, so a missing one is refused, saying so. The target is
`--target`, else the host the manifest names, and the clang is `--clang`,
else the manifest's; with neither flag and no manifest the command is
refused. The sources are compiled against the new std, `--std-root std` by
default, the one std they are written for. The ABI table
(`compiler/typecheck/src/runtimeabi.saw`) lists the target's sources under the
runtime root (`--rt-root`, `sawc/rt` by default): every `.saw` of `common/`,
then of `host_macos/` or `host_linux/`; a target the table has no row for is
refused. Each is compiled as a runtime source to `DIR/NAME.ll`,
unbuffered and closed explicitly, and by `CLANG -c -target TRIPLE -O2 -x ir`
to `DIR/NAME.o`; then `CLANG -c shim.c -O2 -fno-strict-aliasing -target
TRIPLE` writes `DIR/shim.o`. TRIPLE is the module's (`target_clang_triple`),
so the objects and the programs they link into name one target. A runtime
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
manifest naming the target, the clang and the objects. A refused source prints
its record, as `sawc2 build` does; a clang that fails gives its exit status.
Nothing is cached here: `build.py` keys and caches the directory (D41's
ruling). Two builds into two directories write the same bytes. With
`--emit-ll FILE`, that one runtime source's `.ll` goes to standard output.

## The clang

sawc2's `.ll` uses opaque pointers (`ptr`) throughout, which LLVM 15 made the
default and Debian 12's own `clang` (14) refuses. `build.py`'s `choose_clang`
is the one place a clang is chosen: `SAWC2_CLANG` if it is set, else the
first of `clang-19`, `clang-18`, … `clang-15`, `clang` on `PATH`, and the
choice must compile the two-line module `define ptr @f(ptr %p) { ret ptr %p }`
for the target. The capability is tested rather than a version read, since
Apple's clang numbers its versions apart from LLVM's. A clang that fails it
is refused by name with the requirement, and none at all stops the build
before `sawc2 runtime` runs. The chosen clang's absolute path goes into the
manifest's `clang` line, and its `--version` into the runtime's and Stage 2's
cache keys.

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
- **noalias.** A reference parameter is `noalias`: an exclusive one always,
  `&var self` and a glue's included, by the Law of Exclusivity; a shared one
  when its referent is not cell-carrying (typecheck's `is_cell_carrying`,
  spec, Interior mutability), since nothing writes cell-free storage a
  shared borrow holds. A raw pointer, a memory parameter's address, the
  `sret` pointer, a slice and a closure's environment carry nothing. Every
  decision is `ll_param_attributes` in `compiler/llvm/src/attributes.saw`
  (SL-592). Unsafe code reaching a borrowed place around the borrow is what
  the spec rules out (Reference passing).
- **Frame pointers.** Every function the module defines (an item's, glue,
  the entry point and accessors, the formatting and failure helpers, and a
  runtime source's) names the module's one attribute group, `#0`, written
  last from the target's frame pointer policy (`Target.frame_pointer` in
  `compiler/target`): `"frame-pointer"="non-leaf"` on every target sawc2
  knows, so profilers, lldb and crash reports can walk the frame chain.
  Darwin's arm64 convention requires the frame record, and clang keeps it in
  every non-leaf C function there; Linux requires none, and keeps the same
  because a hosted program is profiled there too (SL-594). Every define's
  closing attributes are `ll_function_attributes` in
  `compiler/llvm/src/attributes.saw`, whose entry points are named there.
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
  for a `Void` main. A `main` with a lowered frame is not called: its frame
  goes on the C entry's stack at state 0 and is handed, with its frame
  descriptor, to std's entry executor `__saw_exec_run_main`, and the exit
  status is read from the frame's result once the executor returns. Such a
  program also gets the frame descriptor, a constant laid out as std's
  `FrameDescriptor`, whose `resume` and `drop_result` are function values
  over two thunks, and `__saw_frame_resume`, one resume through a descriptor
  (rt/ABI.md, "The compiler → executor boundary"). A runtime source has no entry and no accessors.
- **Resume functions.** A lowered frame's item is emitted as its resume
  function, `i32 @"saw resume NAME"(ptr %frame, ptr %cx)`, and never as a
  plain function: an entry switch on the state word, then the body's
  blocks, a frame slot one `getelementptr` off the frame pointer, and at each
  suspension point its park or its child's drive
  (`compiler/tests/coro/README.md`, "Lowering").
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
(`compiler/tests/coro/README.md`), which lowers the frames whose every
suspension is a ready park or the drive of a lowered child, and refuses every
other item that needs a frame (`coro.not-yet`) and every suspending cycle
(`coro.suspending-cycle`), so every suspending call that reaches the backend
is a lowered point, and none is emitted as a plain call that blocks the
thread. Every op-budget point that reaches it is outside a frame, and writes
nothing. `yield_main` is the walking skeleton, a suspending `main` the entry
executor drives; `coro_conservative_generic_instance_not_promoted`,
`crossmodule_embed_annotation_positions` and `crossmodule_embed_type_identity`
are corpus programs whose `main` yields (the last two with their packages
under `modules/`). The due programs `suspend_blocking_main`, `suspend_cycle`,
`suspend_budget_point` and `suspend_park_point` pin the refusals at a build:
a `blocking` extern's offload, a cycle, a budget point and a timer park.

**Closures.** A closure's environment is a slot of the frame that builds it,
which is sound only for a closure that does not escape; mono refuses an
escaping closure that captures anything (`compiler/tests/mono/README.md`).
`closure_captures` runs the non-escaping forms, and the due program
`escaping_environment` pins the refusal at a build until SL-525.

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
- `hello.saw`'s `.ll`, as `sawc2 build --emit-ll --target arm64-apple-darwin`
  writes it, equals `hello.ll` byte for byte, and `sawc/rt/host_macos/dirent.saw`'s,
  as `sawc2 runtime --emit-ll` writes it for the same target,
  `runtime_dirent.ll` (`--write` rewrites both); naming the target keeps the
  pins one pair of files on every host;
- every `define` in those two `.ll` files, and in `frame_pointers.saw`'s
  (one function of each kind the backend writes), carries
  `"frame-pointer"="non-leaf"`, itself or through its attribute group;
- `sawc2 build --target` links for the host and every configured target, and
  refuses every other target, saying so, leaving no binary and no `.ll`;
- with `--target TRIPLE` (`tools/linux.py run-lane --arch x86_64`), every
  program's sawc2 side is built for TRIPLE and held to Stage 0's host build:
  the expected output is the same on every target;
- `noalias.saw`'s own `define` lines (its functions, its closure and its
  glue) equal `noalias.defines` (`--write` rewrites it), so each parameter
  row's attributes are pinned: `&var`, `&var self`, a cell-free `&` and
  `&self` carry `noalias`, a cell-carrying `&`, a raw pointer, a by-value
  aggregate, a function value, a closure's environment and `%ret` do not.
  Then the lane copies `compiler/llvm/src`, replaces the funnel's
  cell-carrying test with `false`, builds a sawc2 from the copy at -O0 with
  the selected binary, and requires its `define` lines to fail that
  comparison at `bump(gauge: &noalias.Gauge)`: the injection proves the pin
  catches a funnel that drops the exemption;
- `sawc2 runtime --out` writes the same files, byte for byte, into two
  directories, and refuses a copy of `sawc/rt` that leaves a seam undefined
  (`sleep.saw` without its `@export`) or defines one twice (the host's
  `dirent.saw` exporting `os_ops.saw`'s `__saw_rt_fs_chdir`), naming the seam and printing
  no manifest;
- `probes/executable_path.saw`, built by sawc2 and by Stage 0, run by a bare
  name that a renamed relative symbolic link on `PATH` resolves, from another
  working directory, prints its binary's real path: what the manifest lookup
  rests on;
- an accessor the lane writes to `.build/run-lane/long_accessor.saw`, with a
  local live across its `lend` and 1100 `if`s after it, built by sawc2 at -O0
  and at -O2 with nothing printed, prints the `42` and `5` it states, and
  `probes/accessor_loops.saw`, whose accessors keep locals live across their
  `lend` and around loops (a window inside a loop, a value carried into the
  next iteration, a loop before the `lend`, two nested loops), prints its
  `// prints:` lines the same way. Stage 0 cannot parse a `borrow` block, so
  each program states its own output; the long one's length is past the
  round count a capped dataflow stops at (SL-610);
- `probes/consumes_refill.saw`, whose `consumes` bodies move a field out and
  assign it again (straight-line, on both arms, before an early return, then
  out again, on a type that writes its own `deinit`, and on a generic
  receiver), prints its `// prints:` lines the same way: each refilled value
  is released with the rest of the receiver. Stage 0 refuses the assignment
  as a use after the move (SL-611).

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
