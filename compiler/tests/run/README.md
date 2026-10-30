# compiler/tests/run: the backend and `sawc build`, against Stage 0

The programs the LLVM backend (`compiler/llvm`, package `sawllvm`, SL-505)
and `sawc build` are held to: each is built by sawc against the new std and
run, and its output compared with Stage 0's recorded run of it, built against
Stage 0's own std ("The oracle").

```
run/
  README.md      this specification
  run_lane.py    the lane compiler/tests/run.py runs
  sanitize_lane.py  the sanitizer lane, run.py's `sanitize` step ("The sanitizer lane")
  NAME.saw       a program
  stage0/TRIPLE/NAME.stage0  Stage 0's recorded run of NAME.saw on host TRIPLE
  hello.ll       the `.ll` sawc writes for hello.saw with `-g0`, pinned
  noalias.defines  the `define` lines sawc writes for noalias.saw's own functions with `-g0`, pinned
  debug/         the line-table programs and debug_info.ll, the `!dbg` shape of one
                 function, pinned ("Line tables")
  runtime_dirent.ll  the `.ll` `sawc runtime` writes for runtime/host_macos/dirent.saw, pinned
  frame_pointers.saw  a program defining one function of each kind, whose defines the lane checks
  probes/        programs held to what their own headers state ("Probes")
  modules/       packages a program imports as `modules.NAME`, never run alone
```

## `sawc build`

```sh
.build/sawc-stage1 build [-O0|-O1|-O2|-Os|-Oz] [-g | -g0] [--std-root DIR] [--target TRIPLE]
                   [--target-features FEATURES] [--sanitize address] [--module-path NAME=DIR]...
                   FILE [-o OUT]
.build/sawc-stage1 build [...] -c FILE [-o OUT]
.build/sawc-stage1 build [...] --emit-ll FILE
.build/sawc-stage1 build [...] --freestanding FILE [-o OUT]
.build/sawc-stage1 build [...] --runtime FILE [-o OUT]
```

`--freestanding` builds an object as `-c` does, under the freestanding
profile. Typecheck makes the program's profile record (`TcProfile`, one of
five kinds, from the driver's `--freestanding` and `--runtime` and `sawc
runtime`'s runtime source), and every later stage reads it:
the exports are the roots, a `main` is an ordinary function, there is no C
entry and no argument accessor, the seams are declarations the environment
defines, the backtrace table sits in no named section, and a hosted-only std
import is refused (`import.hosted-only`). The object is compiled with
`-ffunction-sections -fdata-sections -fno-pic` (`driver_object_arguments`).
The target's default features apply when `--target-features` names none
(`target_effective_features`: `-neon,-fp-armv8` on aarch64). A Mach-O target
is refused by a `driver.freestanding-mach-o` record naming the bare-metal ELF
triples sawc describes, exit status 1, and nothing is written. A bare-metal
target's clang is its record's (below); another hosted target with no
manifest of its own takes the host's clang, since no runtime is linked.

`--runtime`, and v0.18.0's spelling `--runtime-provider`, build a runtime
provider: a program whose `@export`s may be the frozen seams, each checked
against runtime/ABI.md. A hosted provider keeps its `main` and links as any
program does but with none of the manifest's runtime objects, so it defines
every seam it reaches: before the link, every `__saw_rt_*` symbol its module
declares and does not define is refused by a `provider.undefined-seam`
record naming it, at the entry file's first line, exit status 1, and nothing
is written (`ll_check_provider_seams`). With `-c` the object leaves such seams
to its link, and with `--freestanding` the provider is the kernel shape, its
seams exported and the rest undefined. `--runtime-build` is refused with exit
status 2, naming `sawc runtime`, which is the one build of a runtime's own
sources.

`sawc build FILE` compiles the program, writes its whole `.ll` to `OUT.ll`
(`-o` defaults to `.build/NAME`), and runs
`clang -target TRIPLE SPEED [-fsanitize=address] -x ir OUT.ll -x none RUNTIME... [-lm] -o OUT`,
blocking until clang exits. `-lm` is there for a Linux target only, since
glibc keeps the math functions in libm, apart from libc, while macOS's
libSystem carries them. A refusal prints its record (as `sawc coro
--check` prints one), writes nothing and exits 1; a failure to write the
`.ll` or to start clang prints why and exits 1; otherwise the exit status
is clang's. The `.ll` is written unbuffered and closed explicitly, and clang
is waited for explicitly, so no step's result rests on a `deinit` (SL:hazards
S28, whose workaround markers name the canonical buffered form). With
`--emit-ll` the `.ll` goes to standard output instead and nothing is linked.

With `-c`, OUT gets `.o` appended when it lacks it, the `.ll` is written to
`OUT.ll`, and clang compiles it to the object OUT, `clang -c -target TRIPLE
SPEED [-fsanitize=address] -x ir OUT.ll -o OUT`, and links nothing. That
argument list has one builder, `driver_object_arguments`, which `sawc
runtime` and the Mach-O link's compile step use too. The object keeps the
executable's linkage: every function internal but the exports and, when the
program declares one, the C entry `main`. A program with no `main` owes none
under `-c`, and its module then has no C entry and no argument accessors.

`--target-features F` puts `"target-features"="F"` in the module's one
attribute group, which every define names, since clang reads a function's
subtarget from its attributes when it compiles IR. `-Os` adds `optsize` to the
group and `-Oz` adds `optsize minsize`: clang adds neither to IR it is handed,
and `minsize` is what runs the machine outliner. A feature list holding
anything but letters, digits and `+-,._` is a usage error.

The module carries DWARF line tables unless `-g0` is given (`-g` is the
default spelled; `compiler/llvm/src/debug.saw`). An ELF executable keeps them
from the one clang run above. A Mach-O executable keeps only a debug map naming
the object they are in, so a Darwin build with line tables runs three steps
instead, each of whose failure fails the build:

```
clang -target TRIPLE SPEED [-fsanitize=address] -c -x ir OUT.ll -o DIR/OUT.o
clang -target TRIPLE SPEED [-fsanitize=address] DIR/OUT.o -Wl,-reproducible -Wl,-oso_prefix,DIR/ RUNTIME... -o OUT
dsymutil --oso-prepend-path DIR OUT -o OUT.dSYM
```

then removes `DIR/OUT.o`. DIR is the real path of OUT's directory, so the
debug map names the object as `OUT.o` and the binary holds no temporary or
build directory: two builds in two directories are the same bytes, which the
fixpoint lane's Stage 3 requires. The linker must be Xcode 15's or later,
whose `ld -v` names project `ld` and which has `-reproducible`; an older one
fails the build, naming `-g0`. A runtime source (`sawc runtime`) and the seed
(`compiler/tools/seed.py`) carry none.
The `.ll` opens with its link manifest, as comment lines:

```
; sawc link manifest
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
host's. They are named by the runtime manifest, `sawc-runtime.txt` in the
directory of the executable that runs: its real path, from
`Env.executable_path()` (the runtime's `__saw_rt_executable_path`), so a
sawc run by a bare name through `PATH`, or through a symbolic link, finds the
manifest beside the file it really is. The manifest is a `target TRIPLE` line
naming the sawc target the objects are built for, a `clang PATH` line naming
the clang that compiles and links for it, then an `object PATH` line per
object, which is what `sawc runtime` prints; `compiler/tools/build.py`
writes it beside Stage 1 and Stage 2 from Stage 1's `sawc runtime` (below).
The manifest is how sawc knows its host: its `target` is the default of
`sawc build`, of `--emit-ll` and of `sawc runtime`, so a sawc built on
Linux aarch64 builds for `aarch64-unknown-linux-gnu`, and the link runs the
manifest's clang, never a `clang` found on `PATH`.
A `--target` naming another target links against that target's own runtime,
named by `sawc-runtime-TRIPLE.txt` beside the binary, which
`compiler/tools/build.py --runtime TRIPLE` writes only once its clang passes
the opaque-pointer check for that target (below) and the runtime, shim.c and
its C headers included, builds for it. A target with no such
manifest is refused, saying it is not the host and has no runtime, before
anything is written: a build never links the host's objects into a module laid
out for another target. In the Linux VM, `--target x86_64-unknown-linux-gnu`
is configured that way, and Rosetta runs what it links. The runtime is built at the module's own target, so a
link prints nothing.

A bare-metal target (`target_bare_metal` in `compiler/target`, today
`aarch64-unknown-none-elf`, whose layouts and C convention are Linux
AArch64's) has no runtime and no C library, so sawc never links for it. A
build for one without `-c`, `--emit-ll`, `--freestanding` or `--runtime` is
refused with exit status 2 before anything is written, naming `-c`. With
`-c` the object is compiled by the clang its record names:
`sawc-runtime-TRIPLE.txt` beside the binary, a `target` and a `clang` line
and no object, which every stage build writes for each of build.py's
`BARE_METAL_TARGETS` (`configure_bare_metal_targets`, which probes clang
again only when the record or what `pick_clang` looks at changes) and
`build.py --runtime TRIPLE` rewrites. Where no capable clang exists, the
build writes no record and says nothing, and `-c` is refused, saying so. The speed flag passes through the driver's one
`driver_speed_level` funnel (design 265); `-O0` is the default.

## `sawc runtime`

```sh
.build/sawc-stage1 runtime [--std-root DIR] [--rt-root DIR] [--target TRIPLE] [--clang PATH] --out DIR
.build/sawc-stage1 runtime [--std-root DIR] [--target TRIPLE] --emit-ll FILE
```

`sawc runtime --out DIR` builds a target's runtime (designs 113b and 149,
SL:open-questions D41) into `DIR`, which must exist: sawc has no API to
create a directory, so a missing one is refused, saying so. The target is
`--target`, else the host the manifest names, and the clang is `--clang`,
else the manifest's; with neither flag and no manifest the command is
refused. The sources are compiled against the new std (by default the
checkout's `std/`, found from the binary's location), the one std they are
written for. The ABI table (`compiler/typecheck/src/runtimeabi.saw`) lists the
target's sources under the runtime root (`--rt-root`, by default the checkout's
`runtime/`): every `.saw` of `common/`,
then of `host_macos/` or `host_linux/`; a target the table has no row for is
refused. Each is compiled as a runtime source to `DIR/NAME.ll`,
unbuffered and closed explicitly, and by `CLANG -c -target TRIPLE -O2 -x ir`
to `DIR/NAME.o`; then `CLANG -c shim.c -O2 -fno-strict-aliasing -target
TRIPLE` writes `DIR/shim.o`. TRIPLE is the module's (`target_clang_triple`),
so the objects and the programs they link into name one target. A runtime
source is checked under the runtime-source profile (`TcProfileKind.RuntimeSource`): its exports may be the frozen
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
its record, as `sawc build` does; a clang that fails gives its exit status.
Nothing is cached here: `build.py` keys and caches the directory (D41's
ruling). Two builds into two directories write the same bytes. With
`--emit-ll FILE`, that one runtime source's `.ll` goes to standard output.

## The clang

sawc's `.ll` uses opaque pointers (`ptr`) throughout, which LLVM 15 made the
default and Debian 12's own `clang` (14) refuses. `build.py`'s `choose_clang`
is the one place a clang is chosen, once per target: `SAWC_CLANG` if it is
set, with no fallback, else the first of `clang-19`, `clang-18`, … `clang-15`,
`clang` on `PATH` that compiles the two-line module `define ptr @f(ptr %p) {
ret ptr %p }` for that target (`pick_clang`). The capability is tested rather
than a version read, since Apple's clang numbers its versions apart from
LLVM's, and per target, since a clang need not have every backend: Apple's has
no RISC-V. The lane checks the choice for `aarch64-unknown-none-elf` with no
override, with `SAWC_CLANG` naming that clang, and with it naming no
executable, which is refused by name, and the bare-metal record, which
must already be there from the stage build before `configure_target`
rewrites it. A clang that fails it
is refused by name with the requirement, and none at all stops the build
before `sawc runtime` runs. The chosen clang's absolute path goes into the
manifest's `clang` line, and its `--version` into the runtime's and Stage 2's
cache keys.

## The backend

One LLVM function per item, in item order; every layout fact is the target
description's (`compiler/tests/mono/README.md`, "Layouts").

- **Values.** A local is an `alloca`, scalar typed (`iN`, `double`, `ptr`) or
  `[N x i8]` for a memory value. A place is its root's address and a
  `getelementptr` per projection at the target's offset; a `(*P)` is a load,
  an index into a raw pointer scales by the element's size, an index into a
  fixed array checks `0 ..< N` first and panics with Stage 0's `array: index
  out of range: I (len N)`, and a forced
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
- **Windows.** A window's open calls its accessor's prologue and its close
  the epilogue, as internal calls. A conditional lend's prologue returns an
  Optional of the lent reference: an open with an absent edge
  (`conditional_open` in `compiler/llvm/src/calls.saw`) calls it into a slot
  of its own, then on `Some` stores the reference into its destination and
  takes the present edge, and on `None` takes the absent edge with nothing
  written. An open with no absent edge stores the Optional itself, which MIR
  then discriminates (SL-686).
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
  `compiler/target`): `"frame-pointer"="non-leaf"` on every target sawc
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
- **Partial conversions.** An integer's `from` and a raw-backed enum's
  `from(raw:)` are one funnel, `partial_into` in `compiler/llvm/src/ops.saw`,
  each writing `Some` of the value or `None`. The spelling picks the test,
  never the payload's layout, since a raw-backed enum is laid out as its
  backing integer: `from` is present when the value's round trip through the
  target is itself and no sign is lost; `from(raw:)` when a `switch` over the
  enum's case tags, the ones a `match` compares, finds the value widened as a
  stored tag is (`tag_word` in `compiler/llvm/src/places.saw`). The switch is
  exact, so a gap between declared values, a negative raw and either extreme
  each answer as declared, where a range test would admit a value no case
  declares (SL-540). The probes `raw_from_signed` and `raw_from_unsigned`
  pin every backing width, a generic enum, an enum with no cases, a widened
  argument and two of sawos's decodes.
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
- **Builtins.** `print` reads and renders every argument first, then hands
  each piece of its format string and each rendered argument, as a table of
  pointer and length records in its frame, to one `__saw_rt_write_line` call,
  which adds the line break and writes the line under the runtime's output
  lock. A nonzero status branches to `__saw_fail_print` after that call
  returns: std's `print_failure` role renders `failed printing to stdout: `
  and the `SystemError`, and `__saw_fail` panics with it at the site. `print()`
  is an empty table. A String argument's bytes and length are read in place
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
  are the target's, and a fixed array's `len()` the length its type carries; the four `__saw_atomic_*` builtins are LLVM atomics of
  the orderings their names state. A fixed array's `swap(i, j)` checks both
  indices, `i` first, with the indexing panic, then exchanges the two
  elements' bits, so nothing is copied or dropped. A spelled `copy()` no
  declaration writes, on an array, an Optional or a tuple, calls its
  referent's copy glue into its destination, which copies each part by its
  own `copy()` in order. `array_swap`, `array_swap_out_of_range`,
  `wrapper_copy` and the probe `wrapper_copy_array_of_wrappers` pin both
  (SL-734). Every builtin passes `mono_builtin_supported`
  (`compiler/mono/src/worklist.saw`) and `LlEmitter.builtin`
  (`compiler/llvm/src/calls.saw`), one row each.
- **Building through the builder.** An interpolation builds its String
  through a growable builder: `init()`, each part's `Printable.format` in
  order, `build()`, then the builder's drop.
- **Collection literals.** One funnel, `collection_literal_into` in
  `compiler/llvm/src/literals.saw`, lowers every kind; mono's
  `resolve_collection_literal` makes the items and glue it calls. A fixed
  array literal writes each element into its slot in index order. A repeat
  `[v; N]` writes the value once as the first element and copies it into
  each later one through the element's copy glue (a loop), as Stage 0 does,
  fills an all-zero scalar with one `memset`, and drops the value when N is
  0. A `Vector`, `Map` or `Set` literal is its type's `init()`, then a
  `push(value:)`, `insert(key:value:)` or `insert(value:)` per entry in
  order; a refused insertion panics with `collection literal: ` and its
  error, rendered as a format argument is, and the value a repeated map key
  replaces is dropped at once. A fixed array's drop glue releases its
  elements in reverse index order and its copy glue copies them in index
  order, each a loop. `fixed_array_literal`, `repeat_literal`,
  `fixed_array_glue`, `map_set_literal` and `map_literal_alloc_failure` pin
  the kinds, element kinds and positions (SL-710).
- **Floats.** A Float literal is its `double` bits, written in LLVM's
  hexadecimal spelling: typecheck's float literal funnel, `tc_float_bits`,
  converts the text exactly (design 253's decimal path, integer arithmetic
  only), to the nearest binary64 with ties to even, and a literal past the
  finite range saturates to infinity or zero. `+ - * /` are `fadd`, `fsub`,
  `fmul` and `fdiv`, unchecked, a compound assignment included; unary `-` is
  `fneg`, so `-x` of `0.0` is `-0.0`. The comparisons are `fcmp oeq`, `une`,
  `olt`, `ole`, `ogt` and `oge`, so every one involving a NaN is false but
  `!=`. `float_constants`, `float_operators` and `float_equality` pin each
  constant position, operator and value class. A Float's synthesized hooks
  (`compiler/tests/mono/README.md`, "Member glue") answer as Stage 0's:
  `float_hook_copy`, `float_hook_equals`, `float_hook_compare` and
  `float_hook_hash` pin each over the two zeros, a NaN and the infinities,
  called directly, through a bound, and as a `Set` element or `Map` key.
- **Comparisons.** An integer, a Bool or a raw-backed enum compares by
  `icmp` at its signedness. A String compares its bytes through the String
  layer's `string_equals` and `string_compare`, each operand read in place,
  an ordering read off the `Ordering` as a declared `compare`'s is. Two raw
  pointers compare by address; any other pointer-sized operand, a
  reference or a function pointer, is refused. `==` and `!=` on a trivially
  copyable value in memory compare part by part: a payload-free enum by its
  case, an Optional by its case and then, when both are present, its
  payload, a struct or tuple member by member, a Float member by `fcmp oeq`.
  Which types those are is typecheck's `compares_in_place`, the one test
  both sides ask: a structural `==` on any other type, one declaring its own
  `Equatable` or holding a String or a fixed array, arrives as a call to the
  `Equatable.equals` requirement, which mono's member glue answers
  (`structural_equality_operator`, SL-759).
- **Erased values** (spec, `any Trait` existentials; SL-721). A pointer to
  an erased value, a `&any Trait` or the pointer an erased box holds, is two
  words: the value's address, then its vtable's. A vtable is a private
  constant per (concrete type, trait), `[drop, size, align, type id,
  slots...]` in words (`compiler/llvm/src/erased.saw`): the concrete type's
  drop glue or a drop that does nothing, its layout's size and alignment, its
  interned type as its id, then each slot's implementation, or null for one
  nothing dispatches. A requirement names no `Self` past its receiver, so an
  implementation's signature is its dispatch's with the receiver the value's
  address, and a dispatch loads the slot and calls it as an internal call is
  made. A rendered erased value calls its `format` slot the same way. A
  borrow of an erased place copies the two words it was reached through.
  An erasure of a reference stores its address beside the vtable; of a
  value, a fresh allocation from the box's allocator's `alloc` with the
  concrete layout, the value moved in, its address beside the vtable; of a
  `Result`, its `Ok` as it is and its concrete `Err` boxed so. A refused
  allocation panics with `allocation failed`, as Stage 0's erasure does.
  An erased box's drop glue runs the vtable's drop on the payload, then
  frees it through the allocator's `dealloc` with the vtable's size and
  alignment. `existential_receivers`, `existential_positions` and
  `existential_errors` pin the forms, members and positions.
- **Strings and statics.** A String literal is a private constant in the
  String layer's literal block (an immortal refcount, the length, the bytes,
  a NUL), wrapped through `string_literal`; a literal message's bytes are
  written as they are. A static is an internal, writable global, written
  once by `static_global` in `compiler/llvm/src/places.saw` (its funnel): an
  integer or a `Bool` as its scalar; any other value the evaluator holds as a
  packed constant with every part at the offset the target's layout gives
  it, zero bytes between, so no LLVM layout rule moves a part (an integer, a
  `Bool`, an atomic's word and a case's tag each an integer of its size, a
  struct and an array their parts in order, a part no byte of which is set
  `zeroinitializer`, which costs the image nothing); and a static with no
  initializer as `zeroinitializer` of its size, at its alignment.
  `static_aggregates`, `static_zerofill`, `static_imported`,
  `static_var_mutated`, `static_large_table`, `lock_statics` and the probe
  `static_alias_construction` pin the kinds, element types and positions
  (SL-722); the due program `static_float_leaf` pins the refusal of a static
  whose initializer holds a Float, since the constant evaluator holds no
  Float value yet (SL-722).
- **The entry.** The C `main(argc, argv)` keeps both for the argument
  accessors the compiler emits into every program (runtime/ABI.md, "Program
  arguments"), calls the program's `main`, and exits with its `Int`, or 0
  for a `Void` main. A plain `main` of a program that spawns is followed by
  std's `__saw_exec_close_background`, which cancels and then finishes every
  task still in the background group. A `main` with a lowered frame is not called: its frame
  goes on the C entry's stack at state 0 and is handed, with its frame
  descriptor, to std's entry executor `__saw_exec_run_main`, and the exit
  status is read from the frame's result once the executor returns. Such a
  program also gets the frame descriptor, a constant laid out as std's
  `FrameDescriptor`, whose `resume` and `drop_result` are function values
  over two thunks, and `__saw_frame_resume`, one resume through a descriptor
  (runtime/ABI.md, "The compiler → executor boundary"). A runtime source has no entry and no accessors.
- **Resume functions.** A lowered frame's item is emitted as its resume
  function, `i32 @"saw resume NAME"(ptr %frame, ptr %cx)`, and never as a
  plain function: an entry switch on the state word, then the body's
  blocks, a frame slot one `getelementptr` off the frame pointer, and at each
  suspension point its park or its child's drive
  (`compiler/tests/coro/README.md`, "Lowering").
- **Spawn sites.** Each task root with a lowered frame gets its frame
  descriptor, as `main`'s does, and a lowered spawn site's spawn terminator
  stores that descriptor's address into its destination and continues; the
  rest of the site is ordinary MIR (`compiler/tests/coro/README.md`, "Spawn
  sites"). A spawn site whose task root has no lowered frame is refused as
  `backend.not-yet`: calling the root would run the task's body in the
  spawner.
- **Drive sites.** A lowered drive site's terminator stores its task
  root's descriptor into its destination, as a spawn site's does, and the
  item's entry points the site's frame local at an `alloca` of the root
  frame's size and alignment; the rest of the site is ordinary MIR over
  std's drivers (`compiler/tests/coro/README.md`, "Drive sites"). A drive
  site whose task root has no lowered frame is refused as
  `backend.not-yet`.
- **Exports.** Each `@export`ed function is a root, defined under its C
  symbol with external linkage, an integer narrower than 32 bits taken and
  returned `signext` or `zeroext` as C does; an `extern` naming the symbol is
  called with no declaration beside it. An exported static is a global under
  its C symbol with external linkage, emitted whether or not a function reads
  it; so is a placed one, internal (the probe `export_static`).
- **Placement.** One funnel, `ll_placement` in
  `compiler/llvm/src/program.saw`, visits every `@section` and `@align`
  whatever carries it, and an attribute no carrier claims is a broken
  invariant, never a dropped attribute. An `@align`ed local's `alloca` and an
  `@align`ed static's global take the larger of the stated alignment and the
  type's own, and an all-zero static stays `zeroinitializer`; typecheck has
  judged the value (`constant.align`), and one the fold leaves to a layout
  (`sizeof`, `alignof`) is folded against the target here and meets the same
  judge. A frame-resident local's `@align` is refused by coroutine lowering
  (`coro.align-frame-resident`). The probes `align_static`, `align_local` (a
  `var`) and `align_local_let` print each slot's address modulo its
  alignment. A `@section` puts `section "NAME"` on its static's global or on
  every define of its function, a generic one's instances and its resume
  function included, with the linkage the function or static has without it.
  An empty name is refused (`section.invalid`), and so is, on a Mach-O target
  (`target_mach_o`), a name that is not `SEGMENT,section` with each part 1
  to 16 characters, which LLVM would abort on rather than report; an ELF
  target takes the name verbatim. The probes `section_static` and
  `section_function` run each position.
- **Determinism.** Functions are written in item order and globals in first
  use; every symbol is derived from what the item is (`@"saw NAME"`). NAME is
  mono's item name, which no two items share (`compiler/tests/mono/README.md`,
  "The dump"), so no symbol is defined twice: the probes `accessor_pair` and
  `extension_same_name` and the program `Range` pin the declarations whose MIR
  spellings coincide.

| rule | refuses | due program |
|---|---|---|
| `backend.not-yet` | what the backend does not lower yet: an operator on anything but an integer, a Bool, a Float, a String, two raw pointers or the memory values compared part by part, a Float operator but `+ - * /`, the comparisons and unary `-`, a slice, a static whose initializer holds a Float or a value the evaluator does not hold, a conditional borrow through a dispatch, a by-value aggregate crossing the C convention (a `UnsafePointer<any Trait>` among them, two words, and its optional), an offload of a variadic extern or of one passing or returning an optional pointer, or on a target whose word is not 64 bits, a pointer cast to or from an integer narrower than a pointer, an unsupported layout, a `main` returning neither `Void` nor `Int`; a constant is refused at its own spelling, inside an aggregate too | `static_float_leaf` |

**Suspension.** The backend's input is coroutine lowering's program
(`compiler/tests/coro/README.md`), which lowers the frames whose every
suspension is a park, an offloaded `blocking` extern call, an op-budget
point, an effect-only test suspension or the drive of a lowered child, and
refuses every
other item that needs a frame (`coro.not-yet`) and every suspending cycle
(`coro.suspending-cycle`), so every suspending call that reaches the backend
is a lowered point, and none is emitted as a plain call that blocks the
thread. No op-budget point reaches it: coroutine lowering turns each one in a
frame into a charge of the frame's counter and deletes every other. `yield_main` is the walking skeleton, a suspending `main` the entry
executor drives; `drive_arguments` drives children that take arguments and
return values, `drive_test_suspensions` parks through `__saw_suspend`
and `__saw_test_suspend`, and `default_on_suspending` leaves literal defaults
out at calls of suspending functions, methods, generic, spawn and drive
roots; `coro_conservative_generic_instance_not_promoted`,
`crossmodule_embed_annotation_positions` and `crossmodule_embed_type_identity`
are corpus programs whose `main` yields (the last two with their packages
under `modules/`). The test drivers run over a plain `main`:
`coro_nested_suspend_two_deep`, `coro_drive_void_body`, `expr_suspend_return`,
`coro_unconsumed_result` and `coro_driven_match_move_out_releases_once` are
corpus programs, `drive_shapes` drives
methods, a static method, generic roots, references, a loop, a sync helper
and a `sync` function, `drive_ownership` owning arguments and results, and
`drive_sync_root` roots that never suspend. The op budget (SL:coroutines
A9): `yield_main_loop` and `suspend_budget_point` are suspending `main`s
with a loop, `op_budget_counts` counts a driven loop's forced yields,
`op_budget_loop_shapes_driven` charges each loop shape without changing its
count, `op_budget_interleaving` cedes before the body that runs the counter
out, `background_compute_preemption` and `taskgroup_compute_preemption`
cede from a task that only computes, in the background group and in a
`TaskGroup`, and `background_task_spawn` also reads `cancelled()` in a task.
Timers (SL:coroutines A11): `main_timer_park` and `async_main_sleep_yield`
sleep in a suspending `main`, `drive_timer_park` in a driven frame,
`task_suspending_parent_sleep` in a driven frame whose spawned tasks sleep
too, `task_sleep_ordering` wakes two sleeping tasks in deadline order, and
`task_cancel_idle_sleep` cancels a sleeping task once the executor has
idled until `main`'s earlier deadline, and `instant_after_sleep` measures a
sleep with `std.time`'s `Instant`. The due program `suspend_cycle` pins
the refusal of a cycle at a build. The offload (SL:coroutines A14a, A14b):
`suspend_blocking_main` offloads a `blocking` extern from a suspending
`main`, and `offload_cancel_waits_for_the_call` cancels a task while its
offloaded call is in flight: the task waits for the call, which writes into
its frame after the cancel, before it leaves.

**Closures** (spec, Escaping-closure heap environments; SL-525). A function
value is three words, its code, its environment and its release, and
`closure_into` in `compiler/llvm/src/closures.saw` is its one construction.
A non-escaping closure's environment is a local of the function that builds
it (SL-805), which owns its copy captures until the statement ends, and a
`[move r]` capture there is `take`'s pair of addresses, the value's and its
take flag's. An escaping closure that captures something keeps its captures
in a heap block from the compiler's allocation (`compiler_allocation`, a
refusal panicking with `closure environment: allocation of N bytes (align A)
failed`), the word before them an atomic count set to one, and its release
is the closure's own teardown: the captures' drop glue, in reverse capture
order, then the block freed. Every other value's release is null. A function
value's copy glue copies the three words and, for a release that is not null,
adds one to the count (monotonic); its drop glue subtracts one (release
ordering), and the value that took the count to zero fences with acquire and
runs the release; a count already at zero panics as an over-release. A
function value's callee is read in place, never copied. `closure_captures`
runs the non-escaping forms, `closure_nonescaping_owning_captures` their
owning captures, `escaping_environment`, `closure_environment_positions` and
`closure_environment_release` the escaping ones, and the probes
`closure_environment_optional_and_generic_owner`, `closure_release_order`,
`coro_sendable_heap_capture_crosses` and `thread_closure_shared_release`
what Stage 0 is no oracle for.

## The lane

`run_lane.py` builds every program with sawc, eight at a time, under
`.build/run-lane/`: `sawc build` run by the binary the runner selected
(Stage 2 by default, `compiler/tools/build.py`). The lane compares:

- a plain program passes when sawc's binary, built at -O0 and again at -O2,
  writes the same bytes as Stage 0's recorded run and exits with the same
  status, a panic's abort included;
- a `// differs: REASON` program compares its exit status and every line
  but a `panic at` line's location, for a panic std raises, since each
  compiler's std is its own file;
- a `// differs:` program whose REASON cites an SL:hazards entry is one whose
  output Stage 0 orders wrongly, a destruction timing it gets wrong (C10,
  C11): its `// prints: LINE` headers, one per line of output, are the
  oracle in Stage 0's place. sawc must print exactly them, Stage 0 the same
  lines in another order, since such a hazard moves a line and never adds or
  loses one, and both must exit alike; a Stage 0 that prints them in order
  fails the program too, so the line comes off when the hazard no longer
  shows there, and a Stage 0 whose order varied between its recorded runs is
  not compared;
- a `// due: REASON` program, with `// refuses: RULE at L:C` after it, must
  be refused there by that rule; once sawc builds it the lane fails, so the
  lines come off as the slice grows; every rule of `ll_rules` has one;
- a build that links prints nothing, standard output or standard error, at
  -O0 and at -O2: the linker has no object built for another macOS to warn
  about, and clang's `ignoring invalid debug info` warning, which drops a
  module's line tables and still exits 0, fails the program;
- the line tables, below ("Line tables");
- `hello.saw`'s `.ll`, as `sawc build -g0 --emit-ll --target arm64-apple-darwin`
  writes it, equals `hello.ll` byte for byte, and `runtime/host_macos/dirent.saw`'s,
  as `sawc runtime --emit-ll` writes it for the same target,
  `runtime_dirent.ll` (`--write` rewrites both); naming the target keeps the
  pins one pair of files on every host;
- every `define` in those two `.ll` files, and in `frame_pointers.saw`'s
  (one function of each kind the backend writes), carries
  `"frame-pointer"="non-leaf"`, itself or through its attribute group;
- `sawc build --target` links for the host and every configured target, and
  refuses every other target, saying so, leaving no binary and no `.ll`;
- with `--target TRIPLE` (`tools/linux.py run-lane --arch x86_64`), every
  program's sawc side is built for TRIPLE and held to Stage 0's host build:
  the expected output is the same on every target;
- `noalias.saw`'s own `define` lines (its functions, its closure and its
  glue), written with `-g0`, equal `noalias.defines` (`--write` rewrites it), so each parameter
  row's attributes are pinned: `&var`, `&var self`, a cell-free `&` and
  `&self` carry `noalias`, a cell-carrying `&`, a raw pointer, a by-value
  aggregate, a function value, a closure's environment and `%ret` do not.
  Then the lane copies `compiler/llvm/src`, replaces the funnel's
  cell-carrying test with `false`, builds a sawc from the copy at -O0 with
  the selected binary, and requires its `define` lines to fail that
  comparison at `bump(gauge: &noalias.Gauge)`: the injection proves the pin
  catches a funnel that drops the exemption;
- `sawc runtime --out` writes the same files, byte for byte, into two
  directories, and refuses a copy of `runtime/` that leaves a seam undefined
  (`sleep.saw` without its `@export`) or defines one twice (the host's
  `dirent.saw` exporting `os_ops.saw`'s `__saw_rt_fs_chdir`), naming the seam and printing
  no manifest;
- an accessor the lane writes to `.build/run-lane/long_accessor.saw`, with a
  local live across its `lend` and 1100 `if`s after it, is held as a stated
  probe (below) to the `42` and `5` it prints: its length is past the round
  count a capped dataflow stops at (SL-610), and Stage 0 cannot parse a
  `borrow` block;
- every program of `probes/` is held to what its header states (below);
- every program of `riscv32/` holds the riscv32 word check (below);
- no record under `stage0/` names a program that is gone.

Stage 0 is the oracle: a difference is a sawc bug until shown otherwise
(SL:architecture §5).

### The riscv32 word check

`riscv32_ir.py` holds the backend to riscv32's 32-bit word with no riscv32
machine to run on. Each program of `riscv32/` is built `--emit-ll
--freestanding --target riscv32-unknown-none-elf`, once with `+m,-a,+c` and
once with `+m,+a,+c`:

- a `word_*.saw` program uses no type wider than the word, so every `i64` in
  its module must be an enum tag widened to the 64-bit tag carrier, or a
  switch or compare of one; any other `i64` is a word the backend wrote at
  64 bits;
- a `wide_*.saw` program renders `Int64` and `UInt64`, through the 64-bit
  renderers `__saw_render_int64` and `__saw_render_uint64`, which take an
  `i64` and return the word;
- each module compiles with the clang `build.py`'s `pick_clang` picks for
  riscv32 (`SAWC_CLANG` overrides), and its object references no
  `__atomic_*_8` and, for a word program, no 64-bit division routine. Without
  `+a`, the atomics program references exactly `__atomic_load_4`,
  `__atomic_store_4`, `__atomic_fetch_add_4`, `__atomic_fetch_sub_4` and
  `__atomic_compare_exchange_4`; with `+a` it references none.

When no clang compiles IR for riscv32, the object half is skipped, its reason
in the lane's counts. The `i64` half always runs.

## Line tables

The backend's line tables (`compiler/llvm/src/debug.saw`) are pinned two ways,
by the programs of `debug/`:

- **Their shape.** `panic_lines.saw`'s `crash`, as `sawc build --emit-ll
  --target arm64-apple-darwin` writes it with its default line tables, is cut
  out with every metadata node its `!dbg` attachments reach, each renumbered
  by first use, and equals `debug/debug_info.ll` (`--write` rewrites it). The
  cut leaves the rest of the module out, so an edit to std moves the pin only
  when it moves `crash` itself.
- **Their symbolization.** Each program is built at -O0 and -O2, must print
  nothing and is run: it panics, and its `panic at FILE:LINE` names the line.
  Every call into `__saw_fail_parts` or into a `try!`'s helper (`saw try
  failure E`, which a failing `try!` calls) in the binary whose innermost
  frame is in FILE must then symbolize to that line, in the function that
  panics, and there must be one. A call made from inside the failure funnel's
  own helpers is not a site: they are artificial, at line 0 of the entry
  file, so the `try!` helper's own call into `__saw_fail_parts` is skipped.
  The call's own address is looked up, not the return
  address after it, since the helpers never return. On Mach-O the binary's
  `.dSYM` must be beside it with no object left, `dwarfdump --verify` must
  pass, and `atos -i` reads it; on Linux `llvm-symbolizer`, the one beside the
  manifest's clang, reads the executable. `coro_lines.saw`'s `step` suspends,
  so its frame is a resume function, and at -O2 clang inlines it into the
  descriptor's thunk: the pin then reads the inlined frame, which keeps
  `step`'s line only because the thunk carries an artificial subprogram
  (`debug_artificial`): code inlined into a function with none loses its
  lines. `try_lines.saw`'s `claim` panics through a `try!`, so its site is
  the call into the `AllocError` helper.

The pins launch no process under a debugger, which a sandboxed session may be
refused; the binary runs alone and every lookup is static.

## The sanitizer lane

`--sanitize address` builds a program under AddressSanitizer: `address` is
the one value the flag takes, and any other is a usage error naming it. The
module's one attribute group gains `sanitize_address`, so every function the
backend defines is instrumented, clang links with `-fsanitize=address`, and
each lowered frame's resume function poisons and unpoisons the frame's bytes
by rule 5's lifetimes (compiler/tests/coro/README.md, "The verifier"). Without
the flag the `.ll` is byte for byte what it was.

`sanitize_lane.py`, run.py's `sanitize` step, builds each of this directory's
`coro_*` programs that is not due, the offload pins
(`offload_cancel_waits_for_the_call`, `offload_start_refused`,
`suspend_blocking_main`) and each `thread_*`, `coro_*`, `generic_default_*`,
`conditional_lend_*`, `borrow_value_read_*`, `temporary_part_*` or
`match_whole_binding_*` probe that states its output (the generic defaults
because a default computed at another width than its slot's overwrites the
stack, SL-830; the conditional lends because the lent reference is read out of
an Optional on the present path alone, SL-686; the borrow value reads because
their windows close before the value they read is used or dropped, SL-838; the
temporary parts because the rest of the temporary drops apart from the part
read out of it, SL-844; the whole bindings because a `match` arm's binding
alone releases the temporary it takes, SL-852), at
-O0 plainly and under `--sanitize address`, into `.build/sanitize-lane/`. A
case passes when the sanitized binary prints the same bytes and exits with the
same status as the plain one, and AddressSanitizer reports nothing; leak
detection is off, since the lane checks frame accesses, and stack-use-after-
return detection is on, since a resume function's own stack slots die each
time it returns `Pending`, so a read of one after a suspension is a frame
access gone wrong (`probes/coro_closure_environment_*`, SL-805). Then the injection:
`compiler/tests/coro/inject/asan_inject.saw`, built by sawc and run, lowers
`asan_overlap.saw` for a sanitizing build, moves `late` onto the offset of
`early`, which dies first, requires the verifier's rule-5 reports, and writes
the refused program's `.ll` anyway, which no `sawc build` can do.
`build.link_module` links it as a hosted `sawc build` would, under
AddressSanitizer, and it must abort with a `use-after-poison` read of 8 bytes
in `keep`'s resume function before the print that read feeds.

## The oracle

The lane never runs Stage 0. Its oracle is `stage0/TRIPLE/NAME.stage0`,
Stage 0's run of `NAME.saw` recorded on host TRIPLE in the format of
`compiler/tests/oracle.py`: the program, the triple, the SHA-256 prefix of the
program's bytes and of each `modules/` file it imports (`source`), Stage 0's
build, and its two runs from
`.build/run-lane/`, their exit status and standard output and error with the
checkout's root removed, a stream or a status that differed between the runs
recorded as `varies`. The lane reads the host's directory, so the macOS run
reads `arm64-apple-darwin/` and the Linux VM `aarch64-unknown-linux-gnu/`,
also for its x86_64 cross-built side.

A plain program whose record is missing, made for another triple or made from
other bytes fails, naming the command that records it:
`run_lane.py --stage0 [NAME...]` builds each program that is not due with
Stage 0 and runs it as the lane runs sawc's, and writes its record for this
host; over every program it also removes a record that names none. That and
`--bench` are the lane's only runs of Stage 0, and both take the v0 compiler
from `oracle.v0_compiler`, which names its checkout in one place: v0.18.0's
(`tools/toolchain.py v0-root`: `SAWLANG_V0_ROOT`, else the tag fetched and
cached). The VM's clone of HEAD holds no Stage 0, so the Linux records are not
rewritten: a Linux record is v0.18.0's, and a program edited since is
rerecorded on the Mac only, or converted to a stated probe.

A record says which program bytes it was made from, not which Stage 0 made
it: every snapshot that compares with Stage 0 is v0.18.0's, regenerated only
through `oracle.v0_root` (`SAWLANG_V0_ROOT`, else the tag fetched and cached):
this lane's, the mono, std and borrowck lanes' (each lane's `--stage0`),
`compiler/tools/std_suspension.py --write`, and the coro and corpusdiff
snapshots' writers.

## Probes

A probe is a program Stage 0 is no oracle for: it cannot build it, or runs
it differently, so the program states its own outcome. The lane finds each
`probes/NAME.saw` by listing the directory, so adding one touches nothing
else. Its leading comment lines carry these header lines, in any order and
among its prose:

- `// probe: KIND`, one of the kinds below;
- `// about: WHAT IT PINS (SL-N)`, one line ending with its issue;
- `// stage 0: WHAT STAGE 0 DOES WITH IT`, why Stage 0's output is no oracle
  here;
- `// speeds: -O0 -O2`, the levels sawc builds it at, each a build held whole
  (a read of an uninitialised local can pass at one level and not another);
- `// prints: LINE`, a line of its standard output, in order;
- `// exits: N`, on a `stated` probe, the exit status its run ends with, 0 to
  255, where a probe stating none must exit 0;
- `// stderr: LINE`, on a `stated` probe, a line of its standard error, in
  order: a probe stating any writes exactly those lines there, and one stating
  none is not held to its standard error;
- `// panics: TEXT`, text its panic line on standard error holds;
- `// undefined: SYMBOL`, a symbol its link must leave undefined;
- `// ll defines: SYMBOL`, a symbol the `.ll` of each build defines, a
  function or a global, under its plain or quoted name;
- `// ll omits: SYMBOL`, a symbol the `.ll` of each build names nowhere;
- `// c helper: NAME.c`, a C file in `probes/` linked into each build, for a
  probe that needs C on the other side of an `extern` or an `@export`. sawc
  writes the `.ll` (`sawc build --emit-ll`), the clang the target's runtime
  manifest names compiles the helper at -O2, so the helper reads the C
  convention as strictly as optimized C does, and the same clang links the two
  as `sawc build` would, at the probe's speed, with the manifest's runtime
  objects and the target's libraries. A `.c` file no probe names fails the
  lane;
- `// leaks: none`, on a `stated` probe: each build, once it prints its
  lines, is run again under macOS's `leaks --atExit`, which must report
  `0 leaks`. Off macOS there is no such checker, and the lane says so: the
  probe counts under "leak check is skipped off macOS" instead.

| kind | sawc at each speed | its lines |
|---|---|---|
| `stated` | builds it with nothing printed; the binary prints exactly its `// prints:` lines, writes exactly its `// stderr:` lines on standard error when it states any, and exits with its `// exits:` status, else 0, and with `// leaks: none` leaks nothing | `prints` and `stderr`, at least one between them; at most one `exits`; at most one `leaks` |
| `panics` | builds it with nothing printed; the binary prints exactly its `// prints:` lines on standard output and one `panic at` line holding the `// panics:` text on standard error, followed by nothing or by the panic path's task dump (its header, then each task's line and its frame lines), and aborts | `prints`, any number; one `panics` |
| `link-fails` | does not link it: the build prints no refusal, and the linker names every `// undefined:` symbol undefined | `undefined`, at least one |
| `custom` | whatever its function in `run_lane.py`'s `CUSTOM_PROBES` checks | `probe` and `about` alone |
| `module` | never builds it alone: it is a module another probe imports, as `import NAME`, and one that no probe imports fails | `probe` and `about` alone |

Every kind takes one `about` line, and every kind but `custom` and `module`
also takes one `stage 0` and `speeds` line, any `ll defines` and `ll
omits` lines, and at most one `c helper` line. A probe states one kind, and a line
its kind does not take fails it, as does a missing one, so no header claims
what the lane does not check. A custom probe needs an entry in
`CUSTOM_PROBES`, and every entry there needs its custom probe; the entry
says why the check cannot be header lines. There are fourteen.
`memory_volatile_survives_optimization.saw` writes a `Device` view's register
twice and reads it twice, does the same through a field a `Device` view
projects, and a `Normal` view's register the same way: its `.ll`, as sawc
writes it for the host and after the host clang's `-O2`, holds exactly four
`load volatile` and four `store volatile` over the whole module, so a merged
`Device` access or a volatile `Normal` one fails it (SL-914).
`runtime_provider.saw` defines every seam a printing `main` reaches over
libc: built with `--runtime` and with `--runtime-provider`, at -O0 and -O2,
the binary defines those seams itself and prints its line; built
`--freestanding --runtime` for `aarch64-unknown-none-elf`, the object exports
them and leaves libc's `write` undefined; a bare-metal `--runtime` link and
`--runtime-build` are each refused with exit status 2.
`runtime_provider_missing_seam.saw` leaves out `__saw_rt_last_raw_code`: with
`--runtime` it is refused by one `provider.undefined-seam` record naming it,
nothing written, and with `--runtime -c` its object leaves the seam undefined.
`freestanding_object.saw` is built with `--freestanding --target
aarch64-unknown-none-elf` at -O0 and -O2: an ELF64 AArch64 relocatable object
whose export `nm` reads defined and external in a `.text.` section of its
own, with an empty `.text`, the panic seam undefined, no C `main` and no
argument accessor, and the file's `main`, which takes a parameter and returns
an `Int`, local (or inlined away at -O2). Its `.ll` names the aarch64 default
`-neon,-fp-armv8` in the attribute group, and an explicit `--target-features`
replaces it; for `arm64-apple-darwin` the build is refused by a
`driver.freestanding-mach-o` record naming `aarch64-unknown-none-elf`, writing
nothing.
`bare_metal_object.saw` is built with `-c --target aarch64-unknown-none-elf`
at -O0 and -O2, with the target's clang record the stage build wrote, whose
absence fails the probe: the object must be an ELF64 AArch64 relocatable file whose export
`nm` reads defined and external, and the same build without `-c` must be
refused with exit status 2, naming `-c`, writing nothing.
`object_output_linkage.saw` is built with `-c` at -O0 and -O2 under an `-o`
naming no `.o`, and `nm` must read its export defined and external, `helper`
internal (or inlined away at -O2), the panic seam undefined, and no `main` or
argument accessor, which no header can state about an object.
`attribute_group_levels.saw`'s `.ll` is written for the pinned target with no
flags, `-O2`, `-Os`, `-Oz`, `--target-features +foo,-bar` and the last two
together, and each must end with its own one `attributes #0` line, every
define naming it; a feature list holding a quote must be refused with exit
status 2.
`leaks_check_sees_a_leak.saw` drops its only pointer to a block it got from
C's `malloc`, and the leak check must report exactly that one block: a
checker that sees nothing would pass every `// leaks: none` probe, and the
block's size is the allocator's, which no header can state.
`executable_path.saw` is built by sawc and run by a bare name that a
renamed relative symbolic link on `PATH` resolves, from another working
directory, and must print its binary's real path, which no header can state:
what the manifest lookup rests on. `print_lines_stay_whole.saw` is run 50
times at -O0 and at -O2; its two threads' lines, each longer than a pipe's
atomic write, must all come back whole and in each thread's order, an
interleaving no header can state. `print_beside_a_panic.saw` must end by
SIGABRT with its panic beside a thread printing in a loop, once with both
streams merged and drained (every line whole, the panic between lines) and
once with standard output a pipe nobody reads. The three `dump_tasks_beside_*`
probes call `dump_tasks()` while another thread recycles a pool's cells, grows
a group past its capacity or tears pools down, and are run 10 times at -O0 and
at -O2: each run must exit 0, each dump's header must count the task lines
under it and name both tasks `main` holds, and the final dump, made once the
churn has stopped, must name those alone and no group it could not read. Which
churned tasks a dump catches is the scheduler's, so no header can state it.

`run_lane.py NAME` runs the programs and probes named `NAME`.

## The timing report

`run_lane.py --bench` builds each kernel of `bench/` with `sawc build -O2`
and with Stage 0 (the v0 compiler, since a time is no record), runs each
binary once to warm it, then five times, and prints the best time of each and
their ratio:

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

What stood between `sawc build` of sawc's own driver and a working Stage 2
(SL-398, U7b), class by class, in the order met. Mono stops at its refusals,
so the backend's classes were counted with mono's set aside, and the backend
reports only the first refusal in each function, so its counts are functions
refused, not sites.

| class | count | resolution | pin |
|---|---|---|---|
| `mono.not-yet`: `Printable.to_string()` on `Int`, a builtin conformance with no member written | 9 | the requirement funnel answers it with Printable's default body, whose `format` is member glue: a signed integer appended through the builder's `append(value: Int)` | `int_to_string` |
| `mono.not-yet`: a `SystemError` format argument of `print` | 2 | a format argument that is not an integer, a Bool or a String renders through its `Printable.format` into a fixed builder over 512 bytes of stack scratch | `printable_format` |
| `backend.not-yet`: a raw-backed enum's layout (`Alt`, `Rule`, `OpenMode`, and the types holding one) | 167, and 475 functions whose result or local it was | the target lays one out as its backing integer, each case's tag the evaluator's value for it; a cast reads the backing's signedness | `raw_enum`; mono golden `layouts` |
| `backend.not-yet`: `==` and `!=` on a payload-free enum | 590 | the tags compare | `enum_equality` |
| `backend.not-yet`: `T.min`, `T.max` | 2 | the bound of the constant's own type | `integer_bounds` |
| `backend.not-yet`: an interpolation | 1 | the growable builder: `init()`, each part's `format`, `build()` | `interpolation` |
| `backend.not-yet`: a `Vector` literal | 1 | its type's `init()`, then a `push` per element, a refused push panicking with its error | `collection_literal` |
| `backend.not-yet`: `==` on an `Alt?`, met once the enum classes were gone | 1 | trivially copyable memory values compare part by part, an Optional's payload only when both are present | `value_equality` |
| clang: `__saw_rt_get_argc` declared by std's `extern` and defined by the entry point | 1 | the entry point's definitions stand for the declaration | `program_arguments` |
| Stage 2 wrong: every token's text lexed as decimal byte values | the lexer's every token | the new std lacked `StringBuilder.append(b: Byte)`, so a `Byte` argument widened into `append(value: Int)` (SL-529) | `byte_append` |

With these, sawc builds its driver with no refusal, clang accepts the
module, and the link is `.build/sawc-stage2`, which the fixpoint lane
(`compiler/tests/fixpoint/fixpoint_lane.py`) holds to Stage 1.

Building the runtime (SL-522, U7c M2) met seven classes. The first six were
the new std's cell and `Atomic`, its sequentially consistent atomic
intrinsics, layout `static_assert`s, pointer-integer casts, variadic extern
calls and pointer arithmetic (SL:open-questions D38 to D40), pinned by
`atomic_ops`, `layout_asserts`, `pointer_address`, `variadic_extern` and
`pointer_offset`; the seventh was the runtime-build mode itself, `sawc
runtime` above (D41). With it, every source of `runtime/common/` and
`runtime/host_macos/` builds with no refusal.
