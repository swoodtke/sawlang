# The std cone's hazard review

SL:architecture §4 ("The bootstrap std") asks for one review of the `sawc/std`
bodies that Stage 0 compiles into sawc2, against SL:hazards, with the subset
checker's rules run over them and each firing either explained or recorded as a
trust obligation. This is that review, for the cone in `std_cone.txt` (SL-441).
The runtime objects a hosted link adds are reviewed with it, because their
bodies are in the same executable.

`sawc/std` is frozen. Nothing here proposes an edit to it: a defect found in a
cone body becomes an SL issue for the new std.

## Method

### The cone

`std_cone.py` runs the frozen compiler in-process on the build `build.py`
does (`compiler/driver` over the stage packages, for `arm64-apple-darwin`), and
on each runtime source a hosted link adds (`sawc/rt/common` and
`sawc/rt/host_macos`, each with `--runtime-build`). It wraps five code
generator methods for that process only, never editing `sawc/`:

- the deferred-body registry (`_defer_body`), which names the LLVM symbol each
  body defines;
- the four body generators (`_generate_function`, `_generate_method`,
  `_generate_init_method`, `_generate_static_method`), through which every
  Saw-declared body passes, monomorphized instances and synthesized methods
  included;
- `_emit_static_global`, which names each static's LLVM global;
- `generate`, which indexes the typechecked program's declarations before any
  body and stops the compile once the unoptimized module exists.

Every body the generators emit is mapped back to its declaration: by position
for authored bodies and instances (an instance keeps its template's position),
through the conformance for a trait default spliced into a conformer, and by
owner and name for a synthesized method. A closure belongs to the body its
symbol names. The linked program's symbol graph is then read from each module's
unoptimized text, and the cone is what `main` reaches in it, crossing from
sawc2's module into a runtime object through the seams the objects export.
Each reached body adds the std types and traits it names, from every `SawType`
its nodes carry; those close over field and payload types, marker conformances,
bounds and parent traits. A generic declaration records the type arguments of
each instance reached, with a type the compiler source declares written as its
ownership class, `(owning)` or `(plain)`, so the file does not change with every
new compiler type. `std_cone.py --instances` prints the full tuples.

The output is sorted and does not depend on the hash seed or on the std cache:
three seeds and a run with `SAW_NO_STDCACHE=1` give the same file. The target is
pinned so the file does not depend on the host that writes it; on this host the
pinned build and the default one give the same cone.

### What the method cannot see

- **Code the compiler emits inline.** `Optional`, `Result` (a type codegen
  synthesizes, not a std declaration), `??`, `?.`, `try`, interpolation, `print`
  and the bounds checks lower to IR inside the caller's body, or to
  compiler-emitted helpers that the file lists by symbol
  (`__saw_string_alloc`, `__saw_panic$bt$*`, ...). A helper's body is the
  compiler's, not std's, so it is outside this review; the new compiler has to
  provide each one.
- **The C bodies.** `sawc/rt/shim.c` and the C library are listed under
  "external C symbols" and are not reviewed.
- **The Linux runtime.** The cone is the macOS build's. A Linux-hosted Stage 0
  links `sawc/rt/host_linux`, whose bodies are not in the file.
- **Compile-time-only uses.** A declaration the typechecker consults but
  codegen never emits (a `static_assert`, a requirement checked and not called)
  is in the cone only when an emitted body names it.
- **Reached is not executed.** The cone is what the program can reach, not what
  a given run runs. The task-backtrace walk below is reached from the panic seam
  but finds no task group in sawc2, so almost all of it never runs.
- A `@name` inside string data is not mistaken for a reference: only symbols the
  module declares count.

### The synthesized calls, probed

Each probe is a small program built twice, with and without one construct, and
`std_cone.py --entry` over both; the delta is what the construct adds.

| Construct | What it adds |
|---|---|
| interpolation (`"n is {n}"`) | the compiler-emitted string helpers (`__saw_string_alloc`, `__saw_string_release`, `String_deinit`), the runtime allocator (`rt_alloc`, `rt_dealloc`, `ALLOC_*`), and `snprintf`/`strcat`/`strcpy`/`strlen`. Stage 0's interpolation builds its string in IR; it does not call std's `StringBuilder` |
| a bounds check (`[Int; 2]` read at a variable index) | the panic seam's whole std side: `__saw_bt_panic` and the task-backtrace walk in `std.taskgroup`, `TaskGroup`, `VoidThread`, `Box`, `Resumable`, `Vector.len` at `Box<any Resumable>?`, the `Atomic` statics, `__saw_rt_panic`/`__saw_rt_write` |
| a drop (a local `Vector<Int>` that goes out of scope) | `Vector.deinit` and `GlobalAllocator.dealloc`, which no source line names, beside `Vector.init()` and `Vector.len` |
| `try` propagating a `Result<Int, E>` | nothing |
| `?.` and `??` on an optional | nothing |

`Result` and `Optional` are built into Stage 0, so their machinery adds no std
declaration; the new compiler must provide it too.

### The review

Every body in the cone was read against each SL:hazards entry. The subset
checker's rules were then run over the cone with `std_cone.py --rules`: the
source rules over each file, the build rules with each file as its own build,
and `owned-operand` as Stage 0's own code generator judges sawc2's build
(object-only, so every body of every loaded std module, generic bodies at each
instantiation). A firing counts when it falls inside a cone declaration, or on
an extension head of a cone type.

The rules split in two (SL-441 c1):

- **Hazard rules** cite an SL:hazards entry. Each firing is listed below with the
  reason it is safe in that declaration: a trust obligation. `sync-only` is
  counted here, because a suspending std body would bring the coroutine
  transform into sawc2. The loud entries (L*) are included, and most of their
  reasons are one sentence: a body Stage 0 compiles has not hit a loud failure.
- **Discipline rules** cite only SL:architecture: they encode the compiler
  source's own discipline, and fire over std by design. They are summarized by
  rule.

## Summary

The cone is 250 declarations in 19 modules: 13 in `builtin`, 51 in three runtime
modules, and 186 in 15 std modules. `owned-operand` finds no site anywhere in
sawc2's build, and the frame ledger for it has no frame and no suspension site.

No firing is a defect. Obligations by hazard:

| Entry | Rule | Declarations | Verdict |
|---|---|---|---|
| C1 (raw memory) | `raw-pointer` | 96 | Raw memory is one of the new std's named low-level features. Each body keeps its own invariant (below). C1's own shape, `move *p`, occurs nowhere |
| S1 | `generic-extension-init` | 2 | `Vector.init()` takes no parameter. `Arc.init(value:)` moves `value` by a placement write, and a probe with a `NoCopy` payload whose `deinit` prints shows one drop, at the end |
| S2 | `borrowed-match-payload` | 2 | Each scrutinee is a call's result, an owned temporary. The rule treats every call as borrowed |
| S3 | none | 3 | `try` appears in `StringBuilder.append(value:)`, `.append(scalar:)` and `Env.args`. The error is `AllocError`, which owns nothing, and nothing owned is evaluated before the `try` in the same expression. No `try?`, no `catch` |
| S4 | `root-reuse` | 7 | Each argument reads `self` only to produce an `Int` or `Byte`, evaluated before the call. No access overlaps at run time, and the missing check only matters for source Stage 1 also compiles |
| S5 | `var-ref-into-let` | 2 | `buf` is the closure's own `&var DataBuf` parameter, not a `let` |
| S9 | `type-alias` | 1 | `Byte = UInt8`. No generic in the cone is instantiated at `Byte`, so SL-49's `G<Alias>` face is not reached; SL-383/384 concern aliases over structs |
| S10, S12, S13, L8 | `nested-optional`, `any-type`, `box-type` | 2 | `TaskGroup`'s `Vector<Box<any Resumable>?>` fields. No `TaskGroup` is constructed in sawc2; the only instance reached on them is `Vector.len`, and nothing is taken out of a box |
| S11, S15 | `cell-type` | 12 | `Arc<DataBuf>` in `Data`, and `Atomic<Int>` statics. `Arc` does not use `UnsafeMutableInterior`, and drops its payload (probed). No cell method is called on an indexed element |
| S18 | `program-unique-names` | 1 | `ASCII_ZERO` in `std.stringbuilder` and `std.net`: private statics take module-local symbols, and SL-195's collision is loud |
| S23 | `owned-operand` | 0 | No site. The head-receiver face, which the rule does not check, was read for and not found |
| §4 sync | `sync-only` | 5 | The backtrace walk names `TaskGroup` and `VoidThread` as types. sawc2's frame ledger has no frame and no suspension site |
| leak tolerance | `deinit-body` | 5 | Each `deinit` frees memory or closes a descriptor; `Arc.deinit` panics only on an over-release, which is a double drop, not a skipped one |
| L1, L2, L5, L6, L7, L9, L17 | `integer-overload`, `closure-syntax`, `empty-struct`, `bounded-extension`, `fixed-array`, `name-collision`, `prelude-type-name` | 46 firings by declaration | Loud entries: Stage 0 compiles these bodies, so the failure each describes did not happen. `prelude-type-name` fires on the prelude's own declarations |

Surprises, for the new std's scope:

- **The panic seam brings in the task executor's backtrace.** Every panic and
  bounds check calls `__saw_bt_panic`, and that pulls 44 declarations of
  `std.taskgroup` into sawc2, with `TaskGroup`, `VoidThread`, `Box`,
  `any Resumable` and three `Atomic` statics. In sawc2 the walk finds an empty
  group list and goes straight to `__saw_rt_panic`. The new std can give a sync
  program a panic path without any of it.
- **`Data` needs `Arc` and the retired `with_unique`.** `File.read` returns
  `Data`, whose copy-on-write goes through `Arc<DataBuf>` and a closure
  passed to `Arc.with_unique` for every byte `push` writes. `with_unique` is on
  the lockdown's retired list, so the new std's `Data` needs another way to
  write unique storage.
- **`std.net` comes with `std.file`,** through `IoError`, `IoErrorKind` and
  `raw_code_now`. The runtime side of an error adds `rt.host_macos.net_os`'s
  errno table and its pthread-keyed raw-code slot.
- **Interpolation calls no std code.** Its builder is compiler-emitted IR over
  `snprintf` and `strcat`, not `StringBuilder`.

## Declarations

One row per declaration with a body, and one per type. Rule names are the
hazard rules that fire in it; "Shapes" is the reading against SL:hazards.
Declarations with no body (externs, marker traits, statics with a literal
initializer) are listed after each module's table. "rt" marks what only the
runtime objects reach.

### builtin

| Declaration | Rules | Shapes |
|---|---|---|
| struct `UnsafeMutableInterior` | `cell-type`, `raw-pointer`, `prelude-type-name` | S11. Only inside `Atomic`, whose construction and methods codegen intercepts |
| struct `Atomic` | `cell-type`, `prelude-type-name` | S11, S15. Used as `Atomic<Int>` statics, called by name, never through an index |
| type `Byte` | `type-alias` | S9: a distinct alias of `UInt8`, used in non-generic signatures only |

No body: traits `Copy`, `Deinit`, `Error`, `NoCopy`, `NoMove`, `Printable`,
`Send`, `Sync`, `UnsafeSend`, `UnsafeSync` (`prelude-type-name` on each). The
`Atomic` method bodies are never run: codegen lowers every call.

### std.alloc

| Declaration | Rules | Shapes |
|---|---|---|
| struct `GlobalAllocator` | `empty-struct`, `prelude-type-name` | L5 needs a zero-sized `Result` payload; `GlobalAllocator` is never one |
| `GlobalAllocator.alloc`, `.dealloc` | `raw-pointer` | C1: forwards to the seams |
| struct `AllocError` | `prelude-type-name` | Two `Int` fields; owns nothing, which is what keeps every `try` over it leak-free |
| `AllocError.format` | none | `try!` on appends; panics rather than leaks |

No body: trait `Allocator`; externs `__saw_rt_alloc`, `__saw_rt_dealloc`.

### std.arc

| Declaration | Rules | Shapes |
|---|---|---|
| struct `Arc` | `cell-type`, `raw-pointer`, `bounded-extension`, `prelude-type-name` | S11: a cell over `DataBuf`, which owns memory |
| `Arc.init(value:)` | `generic-extension-init`, `cell-type`, `raw-pointer` | S1: an `init` in a generic extension that takes an owning parameter by value. It moves `value` by a placement write, not a memberwise build, and the probe drops the payload once |
| `Arc.strong_count` | `raw-pointer` | C1 read |
| `Arc.with_unique` | `raw-pointer` | S16: returns `body(...)` as `R?`, at `R = Bool` and `R = Void`. Retired in the new std |
| `Arc.deinit` | `raw-pointer`, `deinit-body` | Frees the block after an in-place payload drop. Its panics fire on over-release only |
| `Arc.copy` | `cell-type`, `raw-pointer` | Atomic add through the seam |

No body: externs `__saw_atomic_add_i64`, `__saw_atomic_sub_i64_release`,
`__saw_atomic_fence_acquire` (compiler-emitted helpers).

### std.box, std.compiler.frame, std.task

| Declaration | Rules | Shapes |
|---|---|---|
| struct `Box` | `box-type`, `bounded-extension`, `raw-pointer`, `prelude-type-name` | S12, L8. Only as a field type of `TaskGroup`; no `Box` method is reached |
| trait `Resumable` | `prelude-type-name` | Only inside `any Resumable` in a `TaskGroup` field |
| struct `VoidThread` | `sync-only`, `raw-pointer`, `prelude-type-name` | Only as `TaskGroup.crew`'s element type; no thread is spawned |

### std.data

| Declaration | Rules | Shapes |
|---|---|---|
| struct `DataBuf` | `raw-pointer` | C1: owns `capacity` bytes at `buffer` |
| `DataBuf.make` | `raw-pointer` | C1 |
| `DataBuf.cap`, `.head` | `raw-pointer` (`head`) | none |
| `DataBuf.at`, `.store`, `.absorb` | `raw-pointer` | C1: unchecked index; every caller bounds-checks against `Data.length` or has just been through `_make_ready` |
| `DataBuf.grow` | `raw-pointer` | C1: alloc, copy, free |
| `DataBuf.deinit` | `raw-pointer`, `deinit-body` | Frees the buffer |
| struct `Data` | `cell-type`, `prelude-type-name` | S11: `Arc<DataBuf>?` storage; one generic deep, no defaulted parameter (S13 does not apply) |
| `Data.init()`, `.init(capacity:)`, `.len`, `.capacity`, `._is_unique`, `._grow_target_from`, `.to_string` | none | none |
| `Data.get` | `root-reuse` | S4: `self.storage!.at(self.offset + index)`, all shared reads |
| `Data.push` | `root-reuse` | S4: `self._store_at(self.length, ...)`, an `Int` read before the call |
| `Data._grow_target` | `root-reuse` | S4: `self._grow_target_from(self.capacity(), ...)`, shared reads |
| `Data._make_ready` | `root-reuse`, `var-ref-into-let`, `closure-syntax` | S4 as above. S5's rule misreads the closure's `&var DataBuf` parameter. A closure capturing two `Int`s by value is passed to `Arc.with_unique` |
| `Data._rebase` | `borrowed-match-payload`, `cell-type`, `raw-pointer` | S2's rule misreads `match Arc<DataBuf>(value: move fresh)`: the scrutinee is an owned temporary |
| `Data._store_at` | `var-ref-into-let`, `closure-syntax` | As `_make_ready` |
| `Data.byte_ptr` | `raw-pointer` | C1: a read pointer into shared storage |
| synthesized `Data.copy`, `Data.deinit` | none | The derived retain and the field drop of `storage` |

No body: extern `memcpy`.

### std.env, std.path

| Declaration | Rules | Shapes |
|---|---|---|
| struct `Env` | `prelude-type-name` | none |
| `Env.argc` | none | none |
| `Env.arg` | `raw-pointer` | C1: `argv[index]`, after the bounds check |
| `Env.args` | none | S3: `let _ = try result.push(arg)`. `push` consumes `arg` on both paths, and `AllocError` owns nothing |
| struct `Path`, `Path.init(s:)`, `Path.as_str` | `prelude-type-name` (`Path`) | none; `init` is in a non-generic extension |

No body: externs `__saw_rt_get_argc`, `__saw_rt_get_argv`, `__saw_string_from_bytes`, `strlen`.

### std.file

| Declaration | Rules | Shapes |
|---|---|---|
| struct `File` | `prelude-type-name` | none |
| `File.open` | `raw-pointer` | Passes `path: Path` on by value |
| `File._opened` | `raw-pointer` | S23's cast face, already bound first under a workaround marker (SL-427's std half) |
| `File.read` | `borrowed-match-payload`, `raw-pointer` | S2's rule misreads `match Data(capacity: bytes_read)`, an owned temporary. C1: the `malloc` staging buffer is freed on every path |
| `File.deinit` | `deinit-body` | Closes the descriptor |
| enums `OpenMode`, `SeekWhence` | none | Raw-backed; used only through `as UInt8` |

No body: externs `__saw_rt_fs_open`, `__saw_rt_fs_read`, `__saw_rt_fs_lseek`, `close`, `malloc`, `free`.

### std.net

| Declaration | Rules | Shapes |
|---|---|---|
| enum `IoErrorKind`, `IoErrorKind.of`, `.describe` | `prelude-type-name` (the enum) | `from(raw:)` takes a cast, not a bare literal (L1) |
| struct `IoError` | `prelude-type-name` | Owns its `syscall` `String`: the one owning error type in the cone. Nothing propagates it with `try`; the driver `match`es it |
| `IoError.of(syscall:tag:)`, `.of(syscall:kind:)` | none | An overload set on an enum, not an integer width (L1 does not apply) |
| `IoError.format` | none | `try!` on appends; the `describe()` temporary is an argument, dropped by the callee |
| `raw_code_now` | none | The range check keeps the `as Int32` from panicking |

No body: extern `__saw_rt_last_raw_code`.

### std.scalar

| Declaration | Rules | Shapes |
|---|---|---|
| enum `InvalidScalar`, struct `Scalar` | `prelude-type-name` | none |
| `InvalidScalar.format`, `Scalar.init(value:)`, `Scalar.value` | none | none |

No body: statics `MAX_SCALAR`, `SURROGATE_MIN`, `SURROGATE_MAX`.

### std.string

| Declaration | Rules | Shapes |
|---|---|---|
| `to_c_char`, `String.is_empty`, `.starts_with`, `.equals`, `.substring`, `._digit_value`, `.to_uint(radix:)`, `._ubyte_at`, `._decode_at`, `._utf8_error_offset` | none | `_digit_value`'s `-1` begins a line inside an `else` block (L12's shape, loud, and compiled) |
| `String.len` | `raw-pointer` | C1: reads the header |
| `String.byte_at` | `raw-pointer` | C1 read after the bounds check |
| `String._substring` | `raw-pointer` | C1: fills a fresh block, `new_ptr as String` |
| `String._parse_uint` | `root-reuse` | S4: `self._digit_value(self._ubyte_at(i))`, shared reads |
| `String.fromBytes` | `raw-pointer` | C1; the invalid-UTF-8 path releases `candidate` at scope end |
| struct `Utf8Error` | `prelude-type-name` | One `Int` field |

No body: externs `__saw_string_alloc`, `__saw_string_len`, `strlen`.

### std.stringbuilder

| Declaration | Rules | Shapes |
|---|---|---|
| struct `StringBuilder` | `raw-pointer`, `prelude-type-name` | C1 |
| `StringBuilder.init()`, `._grow_target`, `._is_continuation`, `._scalar_byte`, `._c_char` | none | none |
| `StringBuilder.append(s:)`, `.append(b:)` | `integer-overload` | L1: the `Byte` overload |
| `StringBuilder.append(value: Int)` | `integer-overload`, `root-reuse` | S3: `try` over `AllocError`, with only a `Byte` argument. S4: `self.append(self._scalar_byte(...))`, a `Byte` computed before the call |
| `StringBuilder.append(scalar:)` | `integer-overload`, `root-reuse` | As `append(value:)`, ten times |
| `StringBuilder._place`, `._place_char`, `._overflow`, `._mark_truncated`, `.clear`, `._reserve`, `.build` | `raw-pointer` | C1: every write is below `capacity`, which `_reserve` has just checked |
| `StringBuilder.deinit` | `raw-pointer`, `deinit-body` | Frees an owned buffer; leaves fixed storage alone |

No body: statics `ASCII_ZERO` (`program-unique-names`), `MINUS_SIGN`,
`MARKER_LEN`, `MARKER_BYTE_0..2`; externs `memcpy`, `__saw_string_from_bytes`.

### std.taskgroup

| Declaration | Rules | Shapes |
|---|---|---|
| struct `TaskGroup` | `sync-only`, `any-type`, `box-type`, `nested-optional`, `raw-pointer`, `prelude-type-name` | S10, S12, S13 in its fields. Never constructed in sawc2: only read through a pointer from a list that stays empty |
| `__park_is_io`, `__park_is_flag` | none | none |
| `__bt_u32`, `__bt_emit`, `__bt_emit_name`, `__bt_known_frame`, `__bt_frame_rec`, `__bt_state_of`, `__bt_state_rec`, `__bt_depth`, `__bt_emit_frame`, `__bt_emit_stack` | `raw-pointer` | C1: reads of the backtrace table, bounded by the table's own counts and `BT_MAX_*` |
| `__bt_emit_int` | `raw-pointer`, `fixed-array` | L7: a local `[Int8; 24]`, written through its address |
| `__bt_slot_live`, `__bt_emit_status` | `sync-only`, `raw-pointer` | S15's receiver shape, `g[0].done.get(slot)!`, but read-only |
| `__bt_each_live_slot` | `sync-only`, `raw-pointer` | Walks `__saw_bt_head`, which is 0 in sawc2 |
| `__saw_bt_live_count` | `closure-syntax`, `raw-pointer` | A closure with a `[&var count]` capture list |
| `__saw_bt_dump` | `closure-syntax`, `raw-pointer` | A closure capturing `tbl`. Not run in sawc2 |
| `__saw_bt_panic` | `raw-pointer` | Atomic load and store on statics by name |

No body: trait `__TaskCell`; statics `BT_*`, `WAKE_IO`, `__saw_bt_head`,
`__saw_bt_dumping` (`cell-type`); externs `__saw_rt_panic`, `__saw_rt_write`.

### std.vector

| Declaration | Rules | Shapes |
|---|---|---|
| struct `Vector` | `raw-pointer`, `bounded-extension`, `name-collision`, `prelude-type-name` | L6 on its conditional conformances. L9's rule reads `extension Vector<String>` (a specialization) as a type parameter |
| `Vector.init()` | `generic-extension-init` | S1 without a parameter |
| `Vector.len`, `._grow_target` | none | none |
| `Vector.[]`, `Vector.get` | `raw-pointer` | `borrows` accessors lending `buf[index]` after the bounds check. S14 is a call-site face; the compiler source calls them positionally |
| `Vector.push` | `raw-pointer` | C1: a placement write into the uninitialized tail slot, after `_reserve`. At `(owning)` instances the error path must drop `value`, and a missed drop only leaks |
| `Vector._reserve` | `raw-pointer` | C1: alloc, copy, free |
| `Vector.deinit` | `raw-pointer`, `deinit-body` | Drops each live element in place, then frees the buffer |

No body: extern `memcpy`.

### The runtime objects

| Declaration | Rules | Shapes |
|---|---|---|
| `rt_alloc`, `rt_dealloc` (rt) | `raw-pointer` | C1. `ALLOC_*` are `Atomic<Int>` statics (`cell-type`), written only by the test hook |
| `rt_fs_open`, `rt_fs_read`, `rt_fs_lseek` (rt) | `raw-pointer` | Forward to the C library; failures return the negated tag |
| enum `SysError` (rt) | none | Raw-backed |
| `errno_value`, `raw_code_store`, `rt_last_raw_code`, `rt_last_syserror` (rt) | `raw-pointer` | none |
| `raw_code_key` (rt) | `raw-pointer` | `&fresh` of a local `var`, and a CAS on the `RAW_CODE_KEY` static (`cell-type`) by name |

`owned-operand` judges sawc2's build only, so these bodies were read for S23's
positions by hand: they compare and cast `Int`s and pointers, and interpolate
nothing.

## Trust obligations

One entry per hazard rule that fires, naming each declaration and why it is
safe there. Line numbers are in `std_cone.py --rules`.

- **`raw-pointer` (C1).** 96 declarations, listed in the tables above. The cone's
  raw memory is the new std's first named low-level feature, so this is the
  review's main obligation. Each pointer is guarded by its owner's invariant:
  `Vector` by `length <= capacity` and a bounds check on every index;
  `StringBuilder` by `_reserve` before every write; `Data`/`DataBuf` by
  `_make_ready` and `Data.length`; `String` by `byte_at`'s bounds check and
  `__saw_string_alloc`'s block size; `Arc` by its control block layout; the
  backtrace walk by the table's counts and `BT_MAX_*`. C1's own shape, the
  uncharged `move *p`, occurs in no cone body.
- **`generic-extension-init` (S1).** `Vector.init()`: SL-80 needs an owning
  parameter moved into the value, and this `init` has none. `Arc.init(value:)`:
  the parameter is moved by a placement write; probed with a `NoCopy` payload
  whose `deinit` prints, which ran once.
- **`borrowed-match-payload` (S2).** `Data._rebase` (twice) and `File.read`:
  the scrutinee is a call, whose result the arm owns. SL-192 needs a scrutinee
  reached through a reference.
- **`root-reuse` (S4).** `Data.get`, `Data.push`, `Data._grow_target`,
  `Data._make_ready`, `String._parse_uint`, `StringBuilder.append(value:)`,
  `StringBuilder.append(scalar:)`: each argument reads `self` for an `Int` or a
  `Byte`, computed before the call borrows the receiver. SL-284 is a missing
  check, not a miscompile, and these bodies are never compiled by Stage 1.
- **`var-ref-into-let` (S5).** `Data._make_ready`, `Data._store_at`: the
  receiver `buf` is the closure's parameter, typed `&var DataBuf` by
  `with_unique`.
- **`type-alias` (S9).** `Byte`: no generic in the cone is instantiated at it
  (the instance list), and it aliases a primitive, not a struct.
- **`nested-optional` (S10), `any-type` (S12), `box-type` (L8).** `TaskGroup`'s
  fields, and `Box` itself: no `TaskGroup` exists in sawc2, and the only method
  instantiated on those fields is `Vector.len`.
- **`cell-type` (S11, S15).** `Arc` (with `Data`, `Data._rebase`,
  `Arc.init`, `Arc.copy`): the placement-write constructor retires its
  parameter, and `Arc.deinit` drops the payload, as the probe shows.
  `UnsafeMutableInterior` and `Atomic`: compiler-intercepted, over `Int` only,
  and called on statics by name (`ALLOC_ALLOW`, `ALLOC_LIMIT_ACTIVE`,
  `RAW_CODE_KEY`, `__saw_bt_head`, `__saw_bt_dumping`), never on an indexed
  element.
- **`program-unique-names` (S18).** `ASCII_ZERO`: declared privately in
  `std.stringbuilder` and `std.net`; private statics get module-local symbols,
  and SL-195's failure would be loud.
- **`owned-operand` (S23).** No firing. The rule does not check a temporary
  receiver in a control-flow head; no cone body has one that owns memory (the
  heads call methods on `self`, on named locals, or on `GlobalAllocator()`,
  which is empty).
- **`sync-only` (§4).** `TaskGroup`, `VoidThread`, `__bt_slot_live`,
  `__bt_emit_status`, `__bt_each_live_slot`: these name the executor's types but
  suspend nothing. `--emit-frame-ledger` over sawc2's build reports no frame and
  no suspension site.
- **`deinit-body` (leak tolerance).** `Vector.deinit`, `StringBuilder.deinit`,
  `DataBuf.deinit` and `Arc.deinit` free memory; `File.deinit` closes a
  descriptor. A skipped one leaks and has no other effect.
- **Loud entries.** `integer-overload` (L1: `StringBuilder.append`, four
  overloads), `closure-syntax` (L2: `Data._make_ready`, `Data._store_at`,
  `__saw_bt_live_count`, `__saw_bt_dump`), `empty-struct` (L5:
  `GlobalAllocator`), `bounded-extension` (L6: `Vector`, `Arc`, `Box`),
  `fixed-array` (L7: `__bt_emit_int`), `name-collision` (L9: `Vector` through
  `extension Vector<String>`), `prelude-type-name` (L17: 32 of the prelude's own
  types and traits). Stage 0 compiles every one of these bodies, so none of the
  refusals or crashes these entries describe happened.

## Discipline rules

These fire over std because std is written in full Saw. They record no Stage 0
defect.

- **`std-api`** (59 declarations): std's own internals call what the compiler
  source may not: the allocator and its seams, `sizeof`/`alignof`, `memcpy`, the
  string runtime, `Atomic` methods, `IoError.of`. Twice it is `with_unique`,
  which the new std retires; that is the "`Data` needs `Arc`" surprise above.
- **`closure-capture`** (4 declarations): `Data._make_ready` and
  `Data._store_at` capture `Int`s by value, `__saw_bt_dump` captures `tbl`, and
  `__saw_bt_live_count` has a `[&var count]` capture list. The capture bugs the
  subset excludes (SL-26, SL-30, SL-345, SL-387) have no hazard entry; the two
  backtrace closures do not run in sawc2, and the `Data` ones capture only
  `Int`s.
- **`borrows-accessor`** (2 declarations): `Vector.[]` and `Vector.get` are
  `borrows` accessors with `lend`, the new std's other named feature.
