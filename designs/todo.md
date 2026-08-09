# Saw — Open Work Tracker

Open items ONLY. Landed work lives in `designs/NN-*.md` + git history
(this file was pruned Jul 30; see git history of this file for the old
landed recaps). Conventions: cite source designs in [brackets]; VERIFY
items need a probe before being treated as real work.
Historical/landed recaps: designs/todo_aug1-aug9.md (split Aug 9);
older history is in this file's git log (pruned Jul 30).

## Design 188 — safety-audit batch (APPROVED + QUEUED, held; all rulings Aug 9)

Source: the Aug-8 external review (`review.md`) + systematic audit
(`safety_audit.md`, 247 rows, probes in `.build/scratch/safety/` —
GITIGNORED, which is why the load-bearing repros are promoted to example
pins below). Nine findings. ALL FOUR RULINGS RATIFIED in the Aug-9
one-by-one review — the brief's units 2-5 record each decision and the
alternatives explored and declined. D-numbers cite the audit's sections.

- **DF-188a (SOUNDNESS, audit D1): an enum case payload may be a
  reference.** Design 163d's NAMES walk covers fields/generics/returns/
  closures but not enum payloads, so `case Held(r: &Int)` is accepted,
  constructible, and escapes into `Vector` storage outliving the call;
  reading it back ICEs two ways instead of UAF-ing. Fix: the same walk +
  the field position's diagnostic over payload types. PIN:
  `examples/enum_ref_payload_escape.saw`.
- **DF-188b (SOUNDNESS, audit D2): a `type` alias launders a reference.**
  The walk reads types AS WRITTEN; `type R = &Int` bypasses every guarded
  position and `R(&x)` inhabits it. Fix: resolve aliases before the walk.
  Return position is only ACCIDENTALLY covered (fails on a type mismatch).
  PIN: `examples/typealias_ref_launder.saw`.
- **DF-188c — RULED (Aug 9): spawn captures split by soundness, not
  symmetry.** (i) a reference capture of a binding declared AFTER its
  group is an ERROR (the LIFO order runs its deinit before the join —
  the diagnostic names the order and the fix); (ii) reference captures
  into `threads: N` groups refused pending a Sync-checked design (probe
  current behavior first); (iii) single-threaded declared-before stays
  LEGAL — structured concurrency's promise, sound by construction with
  DF-188d's NoMove. Join-at-the-brace considered and declined (deadlocks
  the drop-to-terminate idioms). Follow-up brief filed below: scoped
  task borrows. PIN: `examples/spawn_capture_after_group.saw`. Full
  record: brief unit 5.
- **DF-188d — RULED (Aug 9): `NoMove`, a new declared relocation tier;
  `TaskGroup` is its first conformer.** Duplication and relocation are
  separate axes: `NoMove` REQUIRES an explicit `NoCopy` (never implies —
  declaring it on a Copy-tier type is an error), a NoMove value moves
  exactly once (constructor into binding), whole-referent replacement
  stays legal, the containment contagion is a declared cascade and is
  DOCUMENTED. Not a generic bound. `NoMove + ExplicitCopy` recorded as a
  compatible later opening. Interior-heap pinning considered and
  declined for TaskGroup. PIN: `examples/taskgroup_move_live.saw`. Full
  record: brief unit 4.
- **DF-188e (COMPILER, audit D5): `n += 1` on a `&var` param after a
  suspension ICEs** ("Unsupported container expression in compound
  assignment") — the transform's frame-field rewrite has no compound-assign
  case. `n = n + 1` works. ADDED TO DESIGN 187 (same surface). PIN:
  `examples/coro_ref_param_compound_assign.saw`.
- **DF-188f — RULED (Aug 9, "yes to D6" — THE HEADLINE): place windows
  join the Law of Exclusivity.** Two by-reference accesses to one root in
  one call, at least one a `borrows` place, silently lose writes (std
  `Data` corrupts); the copy-policy error was masking it on the tiers
  that would have caught it. Ruling: fold place-window ROOTS into the
  existing path-disjointness check ("a place borrow charges its root" is
  already the spec's words), exclusivity diagnostic on EVERY copy tier;
  the audit's correct-shapes boundary table becomes the accept-side test
  set. Re-examine DF-176c against the landing. PIN:
  `examples/place_window_exclusivity.saw`. Full record: brief unit 2.
- **DF-188g — RULED (Aug 9, "yes with the narrow receiver rule"): a lend
  must be rooted in the receiver.** A `borrows` accessor lending its own
  local or parameter is refused — reads were sound, writes vanished into
  the dying frame (`c.slot() = 99` silent no-op). The NARROW form: even
  outlives-the-window storage (an accessor's `&var` param) is refused;
  widening later is compatible, the reverse is not. PIN:
  `examples/lend_accessor_local.saw`. Full record: brief unit 3.
- **DF-188h (SPEC/IMPL, audit D8): the `unsafe` effect is unchecked between
  a trait requirement and its conformer**, both directions. Not unsound
  (the boundary check that matters fires — an undeclared unsafe body via a
  safe requirement is rejected); the documented direction (conformer must
  declare what the requirement declares) should be enforced. PIN:
  `examples/unsafe_trait_requirement_effect.saw`.
- **DF-188i (SPEC/IMPL, audit W01): `std.spinlock` and `std.slab` are
  reachable BARE** — `IMPORT_REQUIRED_STD_MODULES` (sawc.py) lists neither,
  spec says gated. Fix: add both + a test that walks the spec's own
  gated-module table so the list cannot drift again. PIN:
  `examples/spinlock_import_gate.saw`.

Also from the audit, for the record: DF-174h's failure mode CHANGED — the
too-deep `??` default no longer emits invalid IR; it silently takes the
absent path (audit row O10). The type error is still owed (187 unit 7,
note updated there). Audit rows confirming fixed items: V17 (DF-146j),
O10/O11 controls, the 26/26 trap table.

## Design 189 — scoped task borrows (APPROVED + QUEUED, Aug 9; probe-CONFIRMED soundness)

`designs/189-scoped-task-borrows.md`, authored from the five-probe
investigation the user directed ("first probe it and then write a brief
depending on the probe outcome"). Probes CONFIRMED TWO SILENT UAFs in
safe code: (a) a deinit-bearing root declared after its group is freed
before the task's write (188's DF-188c(i), now labeled HOLE); (b) `move`
of a captured root between spawn and join hands the task freed memory —
in the ordering 188 calls legal, so extent tracking is REQUIRED for
soundness, not hygiene. Also probed: two `&var` captures of one root
co-live silently (Law violated); MT captures are ALREADY refused via
Send on the closure param (nothing owed there but a regression pin).
The rule: a capture borrows its root for the task's life, the HANDLE
carries the borrow, join releases it (group death is the fallback for a
discarded handle); an exclusive capture excludes caller reads too —
standard XOR over a task-length window. Design-88 param relaxation rides
as an optional unit, ratified separately. RATIFIED Aug 9; queue slot:
immediately after 188, before 186. Queue RESUMED same day:
184 ∥ 187 dispatched, then 188 → 189 → 186 serial.

## Design 187 — coro fix batch + 182 completion (QUEUED, held)

`designs/187-coro-fix-batch.md`, approved Aug 8. Ten units, one surface:
DF-158e (freestanding embedding MISCOMPILE, SOS-M2 blocker) + DF-158c
(@export width swap on rv32) lead; then DF-158a/b/d (transform
diagnostics + the yield_now no-op), DF-174g/h (nested-optional wrap/peel
+ `??` depth), DF-182e's ruled Send additions, DF-182c's store-to-move
surgery, and a cooperative `Command.output()` closing DF-181a whole.
Five xfail pins flip. HELD: do not dispatch until the user resumes the
queue (standing order: stop after 183 integrates).

## Design 185 — const bitwise + flag enums (LANDED, Aug 8)

Closed items: see todo_aug1-aug9.md.

- **DF-185b FILED (OPEN, pre-existing, surfaced by this brief's unit 3).
  A `static` initializer is still literals-only, so a constant
  EXPRESSION cannot initialize one.** `static SIZE: Int = 4 * 1024` and
  the brief's own unit-3 example `static RW: UInt8 = Perm.Read |
  Perm.Write` are both refused ("static `SIZE` must be initialized by a
  compile-time constant"), even though those expressions now fold in
  every position that CONSUMES a constant. The rule is design 41's
  `_is_const_init` list (literals, POD struct literals, constant array
  literals, `Atomic(<int>)`), unrelated to the const evaluator, and
  widening it is its own decision with its own ordering questions:
  - `_is_const_init` would accept anything `const_eval` folds, and
    codegen would emit the folded value rather than the written
    expression;
  - DF-172j's `_collect_const_statics` runs BEFORE registration and
    decides what a static means in a constant from its initializer AS
    WRITTEN. To keep `static SIZE = 4 * 1024` foldable in `[UInt8;
    SIZE]` it would have to evaluate there too — in declaration order,
    with a cycle rule, and with no enum registered yet (so the
    flag-enum half needs the pass reordered or enum raw values read off
    the AST);
  - cross-module: the symbol carries `const_value`, so an importer sees
    whatever the declaring module decided — fine, but it has to be
    decided once.
  Pinned by `examples/static_const_expr_init_xfail.saw` (XFAIL,
  intended behavior in the EXPECT directives, so the fix flips it to
  XPASS). Everything else in unit 3 landed; this is the one sentence of
  the brief that did not.

## Design 158 — logical task backtraces (LANDED, Aug 8)

Three units landed: the per-monomorphized-frame state tables as one
read-only in-binary blob (`__saw_bt_table`, always on), `tools/lldb_saw.py`
(`saw tasks` / `saw bt` / `saw table`), and the alloc-free in-process dump
(`dump_tasks()` from std.task, plus the automatic post-panic one) hosted and
freestanding.

**SIZE (the reserved veto point).** 246-517 bytes per hosted program across
the nine-program gate corpus — 0.23% to 0.83% of the binary. 287 bytes for the
SOS kernel image that runs tasks. 138 bytes for a program with NO coroutine
frames at all (header + the debugger's executor descriptor + the string table)
— the SOS kernel that spawns nothing, and Blade, both land there. A frame
record is 24 bytes, a state entry 12, and names are shared in one string
table, so the cost tracks frames rather than program size.
`tools/test_bt_table.py --sizes` reprints it any time. The debugger's vtable
map (unit 2) adds one pointer per frame on top.

Five findings, ALL PRE-EXISTING (each reproduced on `main` before 158
touched anything). Two carry XFAIL pins; three are recorded here because
they have no user-facing spelling to pin.

**DF-158a — a diverging `panic` in RESULT position of a suspending body is a
codegen ICE.** `func boom() -> Int { sleep(...)  panic("x") }` spawned into a
group: the transform stores the panic's (nonexistent) value into the frame's
`__result` and codegen stores a Python `None` —
`internal compiler error: 'NoneType' object has no attribute 'type'`. Both
the tail and the explicit `return panic(...)` spelling. `panic` is `Never`,
so no store should be emitted: the frame is dead at that point. A `Void`
return type compiles and runs; so does the same `panic` tail in a SYNC
function, which localizes it to the result-store in a coroutine frame.
PINNED: `examples/coro_panic_value_position_xfail.saw`.

**DF-158b — a suspending call in a `Void` body's TAIL position is
rejected.** `func f() { yield_now() }` — the parser makes the block's only
statement its tail expression, the transform lowers a tail through
`_rewrite_expr`, which has no state to split into, and the call is rejected
as "a nested/expression position": a message about a shape the author did
not write. Any statement after it (`return`, another call) compiles. `Void`
is the whole scope: a body returning a value has a result to compute from
its tail, a `Void` one has nothing to store, so the tail should lower
exactly as a statement would. PINNED:
`examples/coro_tail_suspend_void_xfail.saw`.

**DF-158c — an `@export`ed seam's return WIDTH is wrong on a 32-bit
target.** `@export("__saw_rt_clock_monotonic_nanos") func f() -> Int64` emits
`define i32` for riscv32 (and one declared `-> Int` emits `i64`) — the two
are swapped, so the declared type and the emitted C ABI disagree. Invisible
on the 64-bit hosts, where `Int` and `Int64` are the same machine width.
`--runtime-provider`'s signature check does NOT catch it: it compares the
SAW-declared types, which are correct, against ABI.md. Minimal repro is two
`@export`ed seams and `--target riscv32-unknown-none-elf`; the symptom
downstream is an LLVM parse failure where the executor's `Int64` clock
arithmetic meets the i32 definition. Nothing in tree hits it today (sosrt
exports only word/pointer-shaped seams), which is why it survived; it blocks
the SOS live-task dump on riscv32, so that case is arm64-only with a comment
pointing here. NO XFAIL: the failing spelling needs a 32-bit cross-compile,
which the examples suite does not do.

**DF-158e — a `-c` / freestanding compile does not EMBED a nested suspending
callee.** `object_only` decides `is_entry`, `is_entry` is what records a
suspending `main` as a coroutine root, and without that the closure walk
never reaches a spawn root's suspending callees: `fmiddle` gets a frame,
`fleaf` does not, and the call lowers as a direct BLOCKING call. Verified by
`grep -c __Frame_fleaf` on the IR — 21 occurrences without `-c`, zero with
it. This is a miscompile, not a diagnostic: in a kernel the nested park runs
inline instead of parking. It is also why `sos/tests/taskdump.saw` is one
frame deep. `--emit-frame-layout` had the same root cause for its own
reason (it reported no frames at all for the whole `async_main_*` family)
and is FIXED in unit 1 — the flag follows `--emit-ir` now. The transform
side is untouched. NO XFAIL: an examples test cannot spawn under `-c`.

**DF-158d — `yield_now()` in a nested callee does not make its caller
suspend.** `func leaf() { yield_now() ... }` called from a spawned `middle`
leaves `middle` with a single-state frame and no embedded child, so the
yield is the outside-a-frame no-op and the task never cedes. The digest's
documented escape hatch for a compute loop in a sync helper is "put a
`yield_now` in the helper", which is exactly this shape. Seen on both the
hosted and freestanding paths; likely the same effect-edge gap design 96
closed for nested std METHOD calls, never closed for the std.task
`yield_now` WRAPPER (design 114 made it a wrapper). NO XFAIL: writing one
means asserting an interleaving, which the standing rule forbids — it wants
a probe that counts cedes.

## Design 180 — sleep(Duration) (LANDED, Aug 8)

Closed items: see todo_aug1-aug9.md.

**Aug 8 review: all three items below RATIFIED as-is** (the prelude file
move, the negative-span panics, the `as_` renames). The panic ruling is
now a stated API principle: **panic on inputs the caller could have
checked** — a caller bug — and reserve Result/status returns for
conditions the caller could not reasonably know about (allocation
failure, a peer dying mid-operation). It is the same line the accessor
rule draws. Carried into SOS as designs/178 pin 6: an invalid handle
crashes the process.

- **DF-180a (OPEN, filed Aug 8): a static and an instance method cannot share
  a name.** `Duration.secs(2)` (construct) and `d.secs()` (project) are never
  ambiguous at a call site — one names the type, the other a value — but
  declaring both is rejected: ``method `secs` is already defined for struct
  `Duration` with an indistinguishable signature``, hinted "overloads must
  differ in arity or parameter types". The distinguishability check does not
  consider whether a method has a `self` receiver, though resolution reaches
  the two through separate paths. It cost design 180 the accessor names the
  brief asked to keep: the family was renamed `as_nanos` / `as_micros` /
  `as_millis` / `as_secs` so the constructors could be `ns` / `us` / `ms` /
  `secs`. That reads well (bare name constructs, `as_` projects) and is what
  Rust does, so this is not urgent — but the rule as written rejects a
  program with no ambiguity in it, and a receiver-aware key looks small.

## Design 183 — the offload story, made real (LANDED, Aug 8)

DF-181e and DF-181f are both closed above; the offload now works on the seams
and the signatures the design-181 audit needed. Four things worth a look at
review, each a decision the brief left to the implementation:

- **A contradicting `blocking` redeclaration is an ERROR, not an upgrade.**
  DF-181f could have been fixed either way. Making the annotation win would give
  a user the whole-program escape hatch of annotating a std seam — and would let
  a downstream declaration turn a function another module calls into a suspension
  source, landing errors inside code its author never wrote. The audit's escape
  hatch does not need it: a user offloads their own distinctly-named wrapper, and
  DF-181e is what makes that wrapper spellable. Relaxing this later is possible;
  the reverse would not be.
- **The thunk is COMPILER-synthesized, so the C shim never casts a function
  pointer.** The alternative was an arity switch in `shim.c` casting `job->fn` to
  `long(*)(long, long, ...)`, which is the usual trick and is undefined behavior
  that happens to work on both integer-register ABIs. Emitting
  `__saw_blk_thunk$<extern>` in IR instead means the real call is made with the
  extern's real LLVM signature by the same lowering every other extern call uses.
  `shim.c` lost a line rather than gaining a switch.
- **Float is in the offloadable set**, because the brief's rule is "whatever
  `@export` admits" and `@export` admits it. It costs nothing: the thunk moves a
  `Float` through the job's integer word as bits, exactly. The brief's
  parenthetical list omitted it; the governing sentence did not.
- **The argument slots are copied into the JOB, not borrowed from the caller.**
  The worker reads them at a time `start` cannot bound, so the alternative was to
  make the call site's slot array outlive the park, which would have put it in
  the coroutine frame and coupled the thunk to frame layout. `start` copies,
  `take` frees after the join. The call site's array is an entry-block slot, so
  an offload inside a driven loop does not grow the resume frame's stack.

## Design 186 — UnsafeMutableInterior (APPROVED + QUEUED, Aug 8)

Brief in `designs/186-unsafe-mutable-interior.md`, fully ratified: interior
mutability as ONE unsafe primitive + a computed cell-carrying property,
replacing the three compiler-known names; `UnsafeSync`/`UnsafeSend` declared
markers (Sync/Send stay derivation-only); Mutex rebuilt inline (futex /
os_unfair_lock, zero = unlocked, static-eligible); `Once<T>` promoted in as
the set-once static (splitting `unsafe static var` back to genuinely-mutated
state); three-tier statics fence (zero / memberwise-const / never-runtime).
Queue position: after the current wave and the net track — typechecker +
codegen + builtin.saw + std surface, shares with everything, runs alone.

## Design 182 — Command without threads (PARTIAL, Aug 8) — RULED, completion queued

Closed items: see todo_aug1-aug9.md.

**`Command.run()` is cooperative and spends no thread waiting. `Command.output()`
is unchanged and still blocks, because it cannot be made suspending yet — see
DF-182e, which is the ruling this section is asking for.**

### Why `output()` did not land, and the four findings behind it

Making `Command.output()` suspending is a two-line change to the same park loop
`run()` uses. What stops it is its BLAST RADIUS: suspension is colorless, so every
caller becomes a coroutine frame, and four separate limits turn up in real code
that reads a child's output. Three are transform gaps (two fixed here, one pinned);
the fourth is a language question only the user can answer.

- **DF-182c (COMPILER, OPEN, filed Aug 8): an `if let` / `guard let` over a `move`
  SCRUTINEE whose continuation spans a suspension is rejected.** Reading an owning
  value out of an Optional needs `move` (design 131), so this is the ordinary
  shape for consuming one, and `devtools/irdet` is written exactly this way. The
  `move` owes a drop-flag clear; putting it in both branches of the synthesized
  dispatch is the right ORDER (tried, and the ordering holds), but the dispatch's
  value path also STORES the unwrapped payload into a frame field, and that store
  is a copy — which a NoCopy payload refuses outright and an ExplicitCopy one
  would double-drop. The store has to become a move before the clear has anywhere
  to go, which is more surgery than this brief should do unreviewed. Pinned by
  `examples/coro_move_scrutinee_span_xfail.saw`.
- **DF-182e — RULED (user, Aug 8: "containers are Send if T is Send and
  UnsafeSend where the compiler needs to be told a type is Send").** The
  semantics: an OWNING container is `Send` iff its contents are —
  `Vector<T: Send>`, `Map<K: Send, V: Send>`, `Set<T: Send>` conditional;
  `Data`/`StringBuilder` unconditional by the same argument as `String`'s
  carve-out. Mechanism NOW: additions to the by-name override list
  (`namespace.py:_send_sync`) in the 182-COMPLETION unit below; mechanism
  LATER: design 186's declared `UnsafeSend` conformances replace the whole
  fiat list in its migration unit. **The 182-completion unit** (queued
  BEHIND 158 + 183 — both hold the coro_transform/codegen surface): the
  Send additions, the DF-182c store-becomes-move fix, `output()` goes
  suspending on `run()`'s park loop, and both pins flip
  (`process_output_starvation_xfail`, `coro_move_scrutinee_span_xfail`);
  `__saw_rt_proc_wait` drains to zero callers and is removed per the ABI
  note. Original finding, for the record: no std
  container was `Send`, so a task that held one across a suspension could
  not run in a multi-threaded TaskGroup. `String` is Send by an explicit carve-out
  ("immutable buffer + atomic refcount"); `Vector`, `Map`, `Set`, `Data`,
  `StringBuilder` are all NOT, because Send is derived structurally and
  `UnsafePointer<T>` poisons any struct holding one (`namespace.py:_send_sync`).
  Verified directly: a task holding a `Vector<Int>` across a `yield_now` is
  refused by `TaskGroup(threads: 2)`.

  This is what actually blocks `output()`. `devtools/irdet` runs its compiles in
  `TaskGroup(threads: N)` and holds the first compile's `Data` across the second
  compile; today that is legal because `Command.output()` does not suspend, and a
  cooperative `output()` makes it a compile error. The devtool is not doing
  anything exotic — "fan compiles out across threads and compare the two results"
  is the plain shape — so working around it in irdet would be hiding the finding.

  The narrow fix is a `Data` carve-out beside `String`'s, and the argument is the
  same one: `Data` is a copy-on-write window over an `Arc<DataBuf>`, the refcount
  is atomic, reads go through `&self` on a buffer that is immutable while shared,
  and the only writes are behind `Arc.with_unique`, which hands out `&var` exactly
  when nobody else holds the storage. The broad fix is a way for a std container
  to say its raw-pointer field does not poison it — the same thing the existing
  `Arc`/`Mutex`/`Channel`/`Task`/`SpinLock`/`UnsafeMemory` overrides say by name,
  which would reach `Vector` and the rest too. Either is a soundness decision, so
  it is the user's, not an agent's.

- **NOT EXECUTED HERE: the Linux half.** `rt/host_linux/proc_wait.saw` is written
  against the documented `pidfd_open`/epoll contract and only COMPILE-checked on
  this macOS machine (`--runtime-build --target x86_64-unknown-linux-gnu` and
  `aarch64-...`, and the emitted object references `pidfd_open` as expected); the
  remote test worker is macOS too. CI is the first real execution. One judgement
  call in it worth review: it declares the libc wrapper `pidfd_open` rather than
  going through the variadic `syscall(2)`, which keeps DF-113c's no-variadic-extern
  rule and turns a libc older than glibc 2.36 into a link error naming the file
  instead of a silently wrong argument register.

## Design 181 — blocking-call audit findings (filed Aug 7)

Full inventory + policy menu in `designs/181-blocking-call-audit.md`.
Headline: **169 externs across sawc/std/ + sawc/rt/, NOT ONE annotated
`blocking`.** The design-103 offload machinery works and is unused by std.

- **DF-181a (P0-adjacent, filed Aug 7): `Command.run()` / `Command.output()`
  starve every sibling task for the child's whole lifetime.** **HALF CLOSED
  (design 182, Aug 8):** `run()` parks on the reactor and spends no thread;
  `output()` is untouched and still blocks in both `read` and `waitpid`, pinned by
  `examples/process_output_starvation_xfail.saw` and blocked on DF-182e. See the
  design-182 section above. The original finding follows. Both reap via
  the unannotated `__saw_rt_proc_wait` (waitpid) and `output()` first drains
  the child's stdout through the unannotated `__saw_rt_proc_read_stdout`
  (a blocking `read` on a blocking pipe). The cooperative executor thread
  sits inside them, so nothing else runs. DEMONSTRATED, not inferred: with
  task A running `/bin/sleep 2`, a sibling's FIRST tick lands at 2012 ms and
  it then completes 20 cooperative yields in 0 ms — it was runnable the
  entire time. Unbounded (the child may never exit) and reachable from a
  common, documented API. Test:
  `examples/process_run_starvation_xfail.saw`. Fix is a policy call:
  reactor-integrate the stdout pipe (cheap — std.net already has the
  machinery) and annotate the wait, which fits the design-103 whitelist
  exactly — but see DF-181f, which blocked the annotation at the time (closed
  by design 183 unit 1).
- **DF-181b (P0-adjacent by reach, filed Aug 7): every std.file /
  std.directory seam is a naked blocking call.** **DOCUMENTED (design 182 unit 2,
  Aug 8):** the prompt-by-policy contract is now stated where a reader meets it —
  `//!` module docs on std.file and std.directory, and a paragraph in
  LANGUAGE_SPEC beside the never-block invariant. All three say the same thing:
  synchronous by design, prompt on a healthy local disk, unbounded on a network
  mount / FUSE / device node / FIFO, no per-call opt-out, and a `spawn`-ed `Task`
  is where work that cannot afford the stall belongs. The seams themselves are
  unchanged — the recommendation was documentation, not offload.

  **The escape hatch that is still missing (io_uring).** The only way to make
  file IO genuinely non-blocking without a thread hop is a completion-based
  interface: `io_uring` on Linux, which is Linux-only and a project of its own
  (a submission/completion ring is a different seam shape from the readiness
  reactor, so it is an ADDITION to rt/ABI.md rather than a swap of the fs ops).
  POSIX AIO is not an option — it is a thread pool in libc on both hosts.
  Revisit if a Linux-only fast path ever becomes acceptable; until then the
  documented policy above IS the answer. Original finding follows.
  `__saw_rt_fs_open`/`_read`/
  `_write`/`_lseek`/`_opendir`/`readdir`/`closedir`/`_mkdir`/`_rmdir`/
  `_chdir`/`getcwd`/`_unlink`/`_rename`/`access` — no annotation, and unlike
  the reactor/sleep seams NOT ONE comment in the tree acknowledges that they
  block. Bounded-slow on a healthy local disk; genuinely UNBOUNDED on a
  network mount, a FUSE filesystem, or a FIFO (`File.open` on a FIFO blocks
  until a writer arrives). Recommendation in the brief is prompt-by-policy
  + a documented sentence rather than offload (a thread hop per read is the
  wrong default, and freestanding has no threads at all) — but the silence
  is not defensible either way.
- **DF-181c (filed Aug 7): `Channel.recv` from a cooperative task wedges the
  executor forever.** **DOCUMENTED (design 182 unit 3, Aug 8):** `recv`'s
  docstring now states the consequence rather than only naming the engine — never
  from a cooperative task, the thread it stops is the executor's, the sender that
  would unblock it can no longer run, and `receive()` is a drop-in twin. Still
  only documentation: making the call a compile error inside a suspending body
  (the brief's "better" option) is unbuilt. Original finding follows.
  It blocks the calling thread in `pthread_cond_wait`
  with no sender bound. `channel.saw:206` documents which ENGINE it belongs
  to but never states the consequence, and nothing prevents the call. The
  cooperative twin `receive` is a drop-in. Cheap fix: document it loudly;
  better: make `recv` inside a suspending body a compile error.
- **DF-181d (filed Aug 7): `TcpStream.connect` silently IGNORES its `host`
  argument.** `connect(host: String, port: Int)` never reads `host` —
  `net.saw:389-390` calls `__saw_rt_tcp_connect_start(port)`, whose body
  builds a `loopback_sockaddr`. So `connect("example.com", 80)` dials
  127.0.0.1:80 and reports success. Silent wrong-destination: violates both
  "never hide errors" and "APIs do the expected thing". Related: there is NO
  DNS anywhere in sawc/ (no getaddrinfo/gethostbyname/inet_pton), so the
  classic unbounded-resolver hazard is absent TODAY — but resolution will be
  the worst blocking call in the library the day hostnames land, and should
  be designed offloaded or reactor-integrated from the start, never added as
  a naked seam.
- **DF-181e (filed Aug 7): the design-103 offload whitelist `(Int) -> Int`
  is too narrow to express the annotations the audit recommends.**
  **CLOSED (design 183 unit 2, Aug 8).** The offloadable set is now the C-ABI
  set `@export` already admits — fixed-width integers, Int/UInt, Float,
  UnsafePointer, Void/Never returns — with no limit on arity. The runtime's one
  word is a pointer to the call's argument SLOTS, and `fn` is a thunk the
  compiler synthesizes per offloaded extern (`__saw_blk_thunk$<name>`) that reads
  the slots back at their declared types and makes the real call, so the C ABI is
  the compiler's ordinary extern lowering and the runtime knows nothing about
  arity. `__saw_rt_offload_start` gained `(fn, argp, argc)` and copies the slots
  into storage the job owns; `take` frees them after the join.
  The signature gate moved from the coroutine transform's call site to the
  DECLARATION, beside @export's, with @export's message. Tests:
  `examples/offload_multi_arg_pipe_read.saw` (three arguments, a pointer into
  frame storage that the worker writes through),
  `examples/offload_signature_shapes.saw` (narrow ints, zero arguments, a Void
  return, Float), `examples/errors/offload_signature_reject.saw`. The escape
  hatch DF-181b assumes now exists. Original finding follows.
  Of the naked calls, only `__saw_rt_proc_wait(job: Int) -> Int` fits.
  `__saw_rt_proc_read_stdout` (3 args), every `__saw_rt_fs_*` I/O seam
  (3 args) and `__saw_rt_thread_join` (Void return) are all off-whitelist.
  This also removes the escape hatch the DF-181b policy assumes: a user who
  knows they are on a network mount has no way to offload the read. Widening
  it (multi-arg + a real pool) was already future work; this audit is the
  concrete demand for it.
- **DF-181f (COMPILER, filed Aug 7): the `blocking` annotation is SILENTLY
  IGNORED on `__saw_rt_*` runtime seams — so "annotate the seams" does not
  work today.** **CLOSED (design 183 unit 1, Aug 8).** Cause: neither guess in
  the original finding. `_register_extern_function` discards a redeclaration
  whose parameter and return types match an existing one, and it discarded the
  `blocking` flag along with it — nothing `__saw_rt_*`-specific, just that every
  runtime seam std declares IS such a redeclaration. `blocking` is now part of
  the signature the two declarations must agree on, and disagreement is a clean
  error at the annotation. The annotation deliberately does not WIN instead:
  extern symbols are global by name, so letting a downstream declaration upgrade
  one would make a function another module calls a suspension source from a
  distance. Whoever owns the declaration owns the claim. Both branches pinned —
  `examples/offload_seam_first_tick.saw` (the audit's control probe as a test: an
  annotated seam blocks 300 ms and the sibling's first tick lands under 150 ms)
  and `examples/errors/blocking_extern_decl_conflict.saw`. Original finding
  follows. Design 103 promises an offload or "a clean anchored error,
  never a silent miscompile"; on exactly the symbols this audit would
  annotate, neither happens. Demonstrated three ways: an off-whitelist
  `blocking func getpid() -> Int32` errors cleanly (in both `let` and
  statement position), the IDENTICAL shape on
  `blocking func __saw_rt_last_syserror() -> Int` compiles silently, and
  `blocking func __saw_rt_sleep_ms(ms: Int)` (off-whitelist, Void return)
  compiles AND blocks the thread for the full 2 s with no offload and no
  error. Mechanism not pinned down; the transform's
  `_blocking_extern_sym` does `ns.lookup_function(name)` and checks
  `is_blocking`, so the likely cause is either effect inference never
  marking a `__saw_rt_*` call suspending (leaving the body untransformed, so
  `_check_blk_whitelist` never runs) or the lookup resolving to a
  compiler-registered seam symbol instead of the user's declaration. Blocks
  DF-181a and DF-181b remediation — fix this FIRST.

## DECIDED — Aug 7 afternoon round (user, one-by-one review)

Closed items: see todo_aug1-aug9.md.

- **DF-168b DECIDED: defer with trigger** — revisit when compile speed next
  hurts, or before the self-hosted compiler port freezes the pipeline shape.
- **Float64 DECIDED: implement the Float32/Float64 family** (design 173,
  brief authored; queued after 170/171 integrate — typechecker/codegen
  contention). Spec stays wrong only until 173 lands.
- **DF-155a DECIDED: non-breaking knob.** `output()` keeps its meaning;
  explicit stderr capture/discard control + accessor added beside it.
  Small std.process unit, joins the soundness/semantics batch.
- **Rights-table single-source: BACKLOG** on the tracker's own trigger
  (revisit if kinds multiply).

## Design 174 — the T = U? sweep (Aug 7, probe-only investigation)

Closed items: see todo_aug1-aug9.md.

- **DF-174a — FIXED (design 176 unit 7).** Design 24's decidability rule decides
  whether a return-type MISMATCH can be judged in an abstract generic body, and
  rightly defers that to monomorphization; the OPTIONAL wrap was riding the same
  gate and should not have been. It is decidable abstractly: `-> T?` is an
  optional at every instantiation and a non-optional tail is its payload at
  every instantiation, so exactly one wrap is correct for all of them — `T =
  Int?` included, where `Int?` wraps once into `Int??`. The non-decidable branch
  now performs the wrap (and stamps a bare `None` tail) and nothing else, so
  mismatches stay deferred. The `return x` spelling and the generic METHOD path
  never consulted decidability and were always right; the free-function tail was
  the one path that did. Tests: `examples/optional_generic_return_tail_xfail.saw`
  (the pin, flipped) and `examples/generic_optional_tail_return.saw` (the shapes
  that share the path — already-optional tail, `None` tail, diverging tail, value
  `if` arms, generic method, and the `T = Int?` instantiation).
  Original finding follows.
- **DF-174a (COMPILER, P0-severity, filed Aug 7 by the 174 sweep): a generic
  function returning `T?` skips the return auto-wrap for a TAIL EXPRESSION and
  emits MALFORMED LLVM IR.** `func wrap<T>(x: T) -> T? { x }` compiles to
  `ret i64 %x` against a `{ i1, i64 }` result type; the LLVM verifier is the
  only thing catching it, and what it is catching is a skipped optional wrap
  that would otherwise be a type-confused read. **NOT Optional-specific** — it
  reproduces at `T = Int` exactly as at `T = Int?`, so it is a generic-return
  bug the sweep happened to walk into. The `return x` spelling of the same
  function is correct, and so is the non-generic `func w(x: Int) -> Int? { x }`;
  it is specifically `-> T?` plus a tail expression. Severity is the highest of
  this batch: a crash today, a soundness hole if the verifier ever stops
  looking. Test: `examples/optional_generic_return_tail_xfail.saw`.
- **DF-174g (COMPILER, filed Aug 8 by the DF-174c sugar work; PRE-EXISTING,
  verified in the `Optional<...>` spelling with no `??` token anywhere): a value
  needing MORE THAN ONE wrap into a nested optional slot is mis-lowered.**
  `_fit_optional_slot` wraps exactly ONCE, which was all any slot asked for
  while the containers were the only source of a nested optional (their payload
  is already one layer down). Naming the type puts a BARE value two layers below
  its slot, and one wrap leaves an `Int?` in an `Int??` cell: the outer layer
  reads present and the inner is garbage, so the FIRST peel works and the second
  crashes (exit 133). At three layers it does not even compile — `internal
  compiler error: 'IntType' object has no attribute 'gep'`. Probes:
  `.build/scratch/p174c_min5.saw` (`let a: Optional<Int?> = 5`),
  `p174c_min6.saw` (an `Int?` local into an `Int??`),
  `p174_pre_three2.saw` (`Optional<Optional<String?>> = "x"`, the ICE);
  `p174_pre_three.saw` shows a three-deep `= None` compiling fine, so it is the
  WRAP depth that breaks, not the type depth. A one-line recursive fit was tried
  and does NOT fix it (the crash survives), so the gap is in the wrap/peel pair
  rather than the store — same family as DF-174b, which took design 176 unit 8.
  Not reached by any container route: `let got: Int?? = v.get(0)` and passing it
  to a `func f(o: Int??)` both work, which is what the DF-174c pin exercises.
- **DF-174h (COMPILER, filed Aug 8 by the DF-174c sugar work; PRE-EXISTING,
  same verification): `a ?? b` whose DEFAULT is one layer too deep is accepted
  by the typechecker and emits invalid LLVM IR.** `v.get(9) ?? v.get(0)` on a
  `Vector<Int?>` — both operands `Int??` — should be a clean type error (`??`
  peels one layer, so the default owes an `Int?`), and instead reaches codegen,
  which builds a phi with `{i1, i64}` on one edge and `{i1, {i1, i64}}` on the
  other: `LLVM IR parsing error ... defined with type ... but expected ...`, a
  compiler crash rather than a diagnostic. Probe:
  `.build/scratch/p174_pre_coalesce.saw`. The fix is a typechecker one (check
  the default against the PEELED type); the IR error is the symptom.

## DECIDED — Aug 8 morning round (user, the 181 policy)

Closed items: see todo_aug1-aug9.md.

- **STILL OPEN by choice:** the DF-181d connect fix scope (IPv4-literals-now
  vs full resolution). 182 briefs once it's ruled.

## DECIDED — Aug 7 evening round (user)

Closed items: see todo_aug1-aug9.md.

- **DF-176a: SKIPPED by choice (user)** — stays filed; the compound
  spelling (`*=`) is the idiom; the RHS-first-vs-clean-error ruling waits
  for a real collision.

## Design 172 note (branch PARKED for user review; full findings ride the branch)

- **PART 2 IS DONE (Aug 7).** Unit 2 landed as written — DF-172e was the only
  blocker and design 177 removed it — and it grew by one symmetric half: the
  seam family's PROCESS end was C for the same reason, so both user
  `syscall.c` files are now their syscall instruction and nothing else, which
  is what their own headers said they should be. The SOS C floor is 383 -> 207
  -> **135** code lines (-65% overall), and every surviving line is an
  instruction or `mem*`/atomics. Three compiler bugs found on the way
  (DF-172f/g/h) are FIXED in isolated commits for cherry-pick to main; DF-172i
  is a coverage note. Full findings below; the branch parks for review.

- **DF-172e CLOSED — "172 part 2" IS DISPATCHABLE.** The decided while{}-Never
  item (decision 9, tracker commit 3134cf7) landed as **design 177**, so
  `__saw_rt_panic`'s frozen `noreturn` signature has a Saw body available: a
  conditionless `while { }` with no `break` types `Never`, and the freestanding
  shape is pinned by `examples/while_never_freestanding.saw`. 172's unit 2
  (arena → Saw, completing the seam family) stopped on nothing else — everything
  around it was probed and measured on the parked branch — so it resumes as
  written. The compiler half of 172 (unit 7, NEON-off default for freestanding
  aarch64) is cherry-picked to main (e6b5cbe); DF-162a CLOSED measured (arm64
  kernel object: 5 NEON block-moves → 0).

- **DF-172j FIXED (RULED Aug 8, landed on main Aug 8).** A module `static` may
  be an array length, a repeat count, a const generic argument and a
  `static_assert` operand. **The entry itself rides the parked 172p2 branch —
  this is the note that reconciles at its merge; do not edit the parked copy,
  mark it FIXED against these commits.** The rule as built: an `Int`/`UInt`
  static whose initializer is a plain integer literal (optionally negated)
  folds, const arithmetic composes over it (`[0; REGION_SIZE * 2]`), and the
  name resolves as an ordinary read does — a local wins (so design 100's derived
  shadow stays the runtime value it looks like), a const generic parameter wins
  over both, and cross-module is the ordinary visibility gate. That closes the
  SOS finding's own case: `static REGION_SIZE: Int = 65536` is now the one
  checked source for `[UInt8; REGION_SIZE]` and `[0; REGION_SIZE]`, and the
  named-array-type-plus-`sizeof` workaround is retired.

  What stays an error, with a message that now says WHICH static and why rather
  than reading as "no static may be named here": a mutable `unsafe static var`,
  a static of any other type, one declared with no initializer, and one whose
  initializer is not an integer literal. DF-172f's pin
  (`examples/array_length_nonconst_error.saw`) was split — its case is legal
  now, so it holds the mutable-static half and `const_static_length.saw` holds
  the legal one.

  CROSS-MODULE, both halves: the BARE spelling works and is pinned
  (`import dep.{REGION_SIZE}` then `[UInt8; REGION_SIZE]`; a dependency's
  PRIVATE static is not nameable at all, so the gate needed nothing new). The
  **QUALIFIER spelling is filed, not guessed — DF-172l below.**

  Implementation shape worth knowing before touching it: `const_eval` stays a
  pure function of the AST (the typechecker stamps the value on the identifier
  node, exactly as it stamps `Int.max` and a raw-enum case on a MemberAccess),
  and the fold reaches DECLARED types through two whole-program walks — lengths
  before registration, const type ARGUMENTS after it, because the second needs
  the referenced type's parameter list. A struct FIELD's type is the position
  that forces this: it is stored as written and is never resolved before codegen
  reads it.

- **DF-172k FIXED (found by the 172j work, landed with it).** Two adjacent holes
  in the same rule, neither about statics:
  1. A NEGATIVE array length. `[UInt8; -1]` and `[UInt8; 2 - 3]` folded and
     reached llvmlite as `[-1 x i8]`, which came back as
     `internal compiler error: LLVM IR parsing error`. The repeat count has
     checked this since design 148; the type position had not. Reported where it
     folds now, and the length is left unfolded so it is one error rather than a
     cascade against `[UInt8; -1]`.
  2. A BINDING's annotation is the one `[T; N]` position codegen never sees:
     when the initializer supplies its own type the annotation is only compared
     against it, and an unfolded length compares equal to anything. `var buf:
     [UInt8; NOPE] = [0; 4]` compiled clean with the annotation silently
     dropped. Under 172j that would have read as the fold WORKING when it was
     the check missing, which is why it could not be left.

  **NUMBERING — reconcile at 172p2's merge.** `k` was assigned here, on main,
  while design 172's own letters ride the parked branch and cannot be read. If
  the parked branch already spends `DF-172k`, renumber THIS one (five citations:
  `sawc/codegen/types.py`, `sawc/typechecker/types.py`, and the two
  `examples/array_length_*_error.saw` headers, plus the landing commit), not
  theirs.

- **DF-172l CLOSED by design 185 (units 2 + 3, Aug 8).** Filed as: `[UInt8;
  dep.REGION_SIZE]` is a **parse error** ("Expected `]` after array type") while
  the repeat count beside it reaches a clean semantic error — one rule, two
  spellings, two failure modes. Both halves are done. Unit 2 gave the type
  position the SAME expression grammar the repeat count takes (`]` closes it, so
  the `>`-delimiter argument that shaped design 148's small grammar never
  applied there); unit 3 answered the resolution question the finding said was
  not to be guessed at, by widening DF-172j's stamping walk from identifiers to
  the member accesses a constant may name — `Int.max`, a raw-backed enum case,
  and a module static, each in both the bare and the qualified spelling, all
  resolved by the ORDINARY machinery (`_module_qualifier` + `get_enum_info`), so
  a local still wins and a private static of another module is still invisible.
  Pinned by `examples/const_qualified_length.saw`, renamed qualifier included.
  The generic-ARGUMENT position deliberately keeps the narrow grammar: there `>`
  really is the delimiter.

## Design 176 findings (places/optional plumbing batch, Aug 7)

Closed items: see todo_aug1-aug9.md.

- **DF-176a (COMPILER, filed Aug 7 by unit 13's probing; PRE-EXISTING, verified
  against unmodified `main`): a place READ in the RHS of a place WRITE to the
  same root is a wrong error or an ICE.** `v[0] = v[0] * 4` on a local root
  reports ``cannot copy value of type `Vector<Int, GlobalAllocator>` which
  implements ExplicitCopy`` — the element is a trivial `Int` and nothing is
  being copied; the same shape through a receiver field
  (`self.cells[i] = self.cells[i] * by`, in a `&self` OR a `&var self` method)
  dies with `internal compiler error: 'self' not found in current scope`. The
  root is `place_uses._assignment`, which lowers the RHS first and then wraps
  the whole assignment in the TARGET's window, so the RHS window ends up NESTED
  inside the write window and two overlapping borrows of one root reach the
  checker with no diagnostic that names them. The compound spelling
  (`v[0] *= 4`, `self.cells[i] *= by`) works and is the idiom, so the
  user-visible cost is a read-modify-write spelling that fails confusingly
  rather than a capability gap. Needs a decision before a fix: either evaluate
  a place write's RHS BEFORE opening the target window (making the shape legal,
  which is what every other language does here) or make it a clean exclusivity
  error naming the two windows and pointing at `*=`. Probes:
  `.build/scratch/p176_scale{,2,4,5}.saw`.
- **DF-176c (COMPILER, soundness, filed Aug 8 by DF-176b's migration sweep;
  PRE-EXISTING): the same lost mutation through a PLACE WINDOW rather than a
  method call.** `self.grid[0] += 100` in a plain `&self` method, where `grid`
  is an inline field of a type with a `borrows` accessor, is a SILENT NO-OP
  (`.build/scratch/p176b_placewrite.saw` prints `first 1`, not `101`); the same
  write in a `&self` BORROWS body LANDS on a `let` root
  (`p176b_placewrite2.saw` — two pure reads of a `let` leave its counter at 2).
  Exactly DF-175a's two consequences, reached through the fourth spelling.
  DF-176b's rule does not cover it and deliberately does not try: the window
  call is SYNTHESIZED by `place_uses._window_call` (marked `place_lowered`), so
  judging it by the `&var self`-method rule would name a method the source never
  mentions — and would reject `lend self.inner[i]`, design 175's legitimate
  forwarding case, which is sound precisely because a borrows body's receiver
  travels by pointer. Wants its own ruling, and it is a real one: the plain-body
  half is unambiguously the vanishing-write bug, but the borrows-body half
  interacts with `#lend_var` (an exclusive specialization may legitimately want
  a place write in its prologue) and with the composition pessimization design
  175 already documented. Fix site is the place lowering, not
  `_reject_var_self_call_on_shared_self`.

## Design 175 findings (`#lend_var` investigation, Aug 7 — PROBE-ONLY, no compiler changes)

Closed items: see todo_aug1-aug9.md.

- **DF-175c — OPEN (minor, docs). `--emit-docs` cannot distinguish a
  `&var self` borrows accessor from a plain `&var self` method** — the former
  reports `"self": "borrows-var"`, same as the latter, so window-ness is only
  recoverable from the signature string (`docs_emit.py:425-442`). A `&self`
  borrows receiver correctly reports `"self": "window"`. Cheap fix
  (`"window-var"`); matters more once accessors are flavored.

## Design 179 findings (`#lend_var`, Aug 7 — IMPLEMENTED, six units)

Closed items: see todo_aug1-aug9.md.

- **DF-175c stays OPEN** (`--emit-docs` cannot tell a `&var self` borrows
  accessor from a plain `&var self` method). The synthesized twin needed no
  suppression work — its reserved `__` name already falls under `docs_emit`'s
  synthetic-declaration filter — so the flavor note was not the trivial change
  the brief made it conditional on, and 175c is left as filed.

## Design 169 part 2 — std.cbor itself (LANDED, Aug 7)

Closed items: see todo_aug1-aug9.md.

All six units are built; the landing report is at the bottom of
`designs/169-serialize-cbor.md`. `sawc/std/cbor.saw` is the deterministic-profile
codec (import-required, both profiles): `CborDecoder.open` validates the whole
input against max_depth/max_size/max_items over an EXPLICIT work stack before
any typed read runs, so depth is the stack's height and no input reaches the
call stack — a 100000-deep blob is refused at byte 64. Nothing panics on input:
UTF-8 is validated in place rather than through a `String`, and the decoder's one
allocation is the work stack, sized at open. `examples/cbor169_vectors.saw`
WALKS `tests/cbor_vectors/`, so the 32 accept + 20 reject blobs now gate the Saw
codec and `tools/sawcbor.py` together, forever, with no regeneration step; the
`struct_endpoint` and `lock_entry` vectors are reproduced byte for byte by the
`@synthesize` derivation. Unit 6 moved `blade/src/lock.saw` from five parallel
`Vector<String>` to `LockEntry` + `Vector<LockEntry>` with both directions
derived (bootstrap 21 tests to 22, green stage1 + stage2) — but LEFT `Saw.lock`
as TOML on disk, which is the one scope call wanting user ratification (a lock
file is read in review and three are tracked here; the switch is two call sites
if binary was the intent). Findings DF-169e/f/g/h below. The state-of-the-world
the dispatch inherited follows.

## Design 169 — DF-findings (Serialize/Deserialize + std.cbor, units 1/2/5 LANDED)

Closed items: see todo_aug1-aug9.md.

- **DF-169e — a STATIC trait requirement is not callable on a type PARAMETER.**
  Inside `func decode<T: Deserialize>(bytes: Data) -> Result<T, DecodeError>`,
  the call `T.deserialize(from: &var dec)` is ``undefined variable `T` `` plus a
  follow-on "body has no value". The INSTANCE half of a bound dispatches fine
  (`v.label()` under `<T: Named>` works), so this is specifically the static
  call. It matters more than it looks: unit 1 made `deserialize` static so that
  `Deserialize` would be a generic BOUND and never an existential (DF-169b), and
  a bound whose requirement cannot be called generically buys nothing. `std.cbor`
  therefore ships `encode<T: Serialize>(value:)` and NO `decode<T>` twin — a
  caller names the concrete type, `LockEntry.deserialize(from: &var dec)`. Repro:
  `.build/scratch/probe_static_bound.saw` (a two-requirement trait, one static
  one instance, called both ways).
- **DF-169f — a place WRITE whose RHS names `self` is an ICE.**
  `self.marks[0] = self.tick` and `self.marks[0] = self.width()` both die with
  `internal compiler error: 'self' not found in current scope`, no source anchor.
  Place lowering rewrites the write into an accessor call taking the window as a
  CLOSURE and hoists the RHS into that closure body, which never captured `self`
  — so the failure is not about the place at all, it is about what the RHS
  mentions. A literal or local RHS (`self.marks[0] = 4`) is fine, and so is a
  place READ off `self` in any position. Reading the RHS into a local first
  compiles and runs, which is what `sawc/std/cbor.saw` does at its two map-key
  bookkeeping sites (`item_done`, `close_item`). An ICE with no anchor is the
  worst shape a rejection can take, so this is the first thing to fix in the
  places batch. Pinned: `examples/place_write_self_rhs_ice_xfail.saw`.
- **DF-169g — the automatic ImplicitCopy tier does not satisfy a `Copy` BOUND.**
  Design 159 put a struct whose owning members are all trivial/ImplicitCopy on
  the ImplicitCopy tier with no declaration owed, and the BINDING half works:
  `struct Ticket { code: String }` compiles bare and `let b = a` is a free retain
  leaving both live. The CONFORMANCE half never registered, so the same type
  fails a `T: Copy` bound — ``type `Vector<Ticket, GlobalAllocator>` has no
  method `iter`: requires `T: Copy`, and `Ticket` does not conform``. std's own
  `Path` is one of these (`struct Path { value: String }`), so `Directory.list`
  hands back a `Vector<Path>` that cannot be iterated; the design-169 vector
  harness reaches each entry as a PLACE instead (`entries[i].ext()`, a borrow, so
  the tier never comes up). The two halves of one tier should agree. Repro:
  `.build/scratch/probe_auto_tier_bound.saw`.
- **DF-169h — a place window refuses a `&var` argument naming a NoCopy LOCAL.**
  `v[i].serialize(to: &var enc)` over an encoder you just built is ``cannot copy
  value of type `CborEncoder` which implements NoCopy``, anchored at the
  SUBSCRIPT, with a `move` hint that would be wrong — the program copies no
  encoder anywhere. Same lowering as DF-169f from the other side: the window
  becomes a closure and the local is captured by value instead of having its
  address taken. Forwarding a `&var` PARAMETER into the same window works, which
  is exactly why design 169 unit 2's derived `Vector` walk never hit it (its
  encoder arrives as a parameter) and why this surfaced only in `blade/src/
  lock.saw`, whose `to_cbor` builds the encoder locally. The spelling that
  compiles is a value read first (`let entry = lock.entries[i]`), which for a
  five-String record is five retains rather than a borrow. Two of the four
  findings in this brief are one bug in the place lowering seen from two sides;
  fixing the capture would close both. Pinned:
  `examples/place_nocopy_arg_in_window_xfail.saw`.
- **DF-169i — a std-module static as a DEFAULT PARAMETER VALUE breaks at the
  caller, with a bogus anchor.** `public func open(bytes: Data, max_depth: Int =
  DEFAULT_MAX_DEPTH)` in `sawc/std/cbor.saw` compiles, and so does a call from
  inside std; a call from a user module is ``undefined variable
  `DEFAULT_MAX_DEPTH` `` anchored at an unrelated line of the CALLER (the
  default is substituted at the call site, where std statics are not visible —
  the known cross-module static gap, design 82). Two things are wrong
  independently: the visibility gap itself, and a diagnostic that points at
  whatever line the substitution landed on rather than at the parameter that
  supplied it. `std.cbor` writes its three limit defaults as literals because of
  this, with the names in a comment above them.

## Design 170 — checked integer casts (LANDED, Aug 7)

Closed items: see todo_aug1-aug9.md.

`as` between integer types traps on an unrepresentable value; `T.from(x)` is
the `None`-returning twin and `T.from(truncating: x)` the deliberate wrap.
Follow-ups and findings the sweep produced:

- **DF-170b (FOLLOW-UP, mechanical): re-run the cast census over
  `sawc/std/data.saw`.** Skipped in this sweep because design 165 was
  rewriting the file concurrently. As it stood at 170's dispatch it had 23
  ` as ` tokens, 13 of them pointer casts and ZERO integer casts, so it was a
  no-op for this design — but the rewrite could introduce integer casts, and
  nothing checked the rewritten file. Grep it for ` as ` and triage each hit
  provably-in-range (keep `as`) vs deliberate-wrap (`from(truncating:)`).
- **The `fd as Int32` cluster (~30 sites, KEPT as `as` deliberately).**
  `sawc/rt/common/os_ops.saw` plus both `reactor.saw` files hold fds in `Int`
  fields and narrow at each libc call. Every one is guarded non-negative at
  creation and an fd is always small, so the checked cast now ENFORCES an
  invariant that was previously only true — which is the outcome the design
  wants, not a site to respell. The tidier end state is typing the seam
  fields `Int32` end-to-end so no cast exists at all; that is a refactor
  worth doing on its own, not under a semantics change.

## Review sweep (Aug 4) — TRIAGED (user, Aug 4 evening), briefs 122-127

Closed items: see todo_aug1-aug9.md.

- **DF-146k — OPEN, needs a user decision (Aug 6). A `borrows` accessor cannot
  be declared SHARED-ONLY, so a container whose own invariants depend on an
  element cannot publish one at all.** This is why DF-146d's Set half did not
  land. Design 141 decision 3 puts the window's flavor at the USE SITE, out of
  one declaration — which is right for a Vector element and for a Map VALUE, and
  wrong for a Map KEY or a Set element: `s.get(x)!.mutate()` would change an
  element's hash and lose it in its own table, with no diagnostic anywhere.
  Rust draws the same line by having `HashSet::get` and no `get_mut`; Saw has no
  spelling for it. Options: a `shared borrows` declaration that pins the flavor;
  or accept that slot-keyed containers publish only by-value reads. (The second
  option once floated here, `borrows -> &T`, is gone: a return type that names a
  reference is a parse error since DF-163a's fix.) Until then `Set` has no
  element accessor, and the spec says so.
  **PROBE VERDICT (design 179 unit 5, probe-only — no accessor built). The
  IMPLEMENTATION question is now answered; the DECISION is untouched.** A
  shared-only accessor is expressible TODAY with no new language surface, by
  gating a compile-time reject on `#lend_var`:
  ```saw
  public func [](&self, i: Int) borrows -> Int {
      if i < 0 || i >= 4 { panic("Keys.[]: index out of range") }
      if #lend_var {
          static_assert(false, "Keys.[] lends a KEY: writing one changes its hash")
      }
      lend self.items[i]
  }
  ```
  Reads compile and run; an exclusive use site is a COMPILE ERROR carrying the
  author's own message, verified for both shapes that open one — an assignment
  (`k[0] = 99`) and a `&var` argument (`bump(&var k[0])`). It works because
  `static_assert`'s condition is type-checked at check time but its VALUE is
  evaluated at codegen (`typechecker/statements.py:901-905`), and design 179's
  exclusive twin is a generic method only monomorphized when a use site
  retargets to it: no exclusive use site, no twin emitted, no assertion
  evaluated. The shared copy never contains the assert at all, because the fold
  PRUNES rather than skips.
  NOT SHIPPABLE AS THE SPELLING, for one reason: the diagnostic has NO source
  location — not the write site, not the accessor —
  `error: static assertion failed: Keys.[] lends a KEY: ...` and nothing else.
  For a std `Set` accessor a user would see that and nothing pointing into
  their own code.
  RECOMMENDATION: a viable IMPLEMENTATION, not a viable SPELLING. If `Set`
  should publish a shared-only element accessor, the honest surface is the
  `shared borrows` declaration floated above, LOWERED to exactly this — emit no
  twin, and error in `place_uses._flavored_method`, where the use site's own
  line and column are already in hand (every other diagnostic in that pass uses
  them). Roughly ten lines for a message anchored at the write. Probes:
  `.build/scratch/p179_setlock_{read,write,ref}.saw`.
  Adjacent, same brief: a borrows body cannot FORWARD another conditional place
  (`lend self.map.get_key(k)!` — `lend` takes an
  Identifier/MemberAccess/ArrayIndex/TupleIndex/deref, and even if it took a
  place call, `_span_call` would lower the absent path to a PANIC rather than to
  the caller's `__absent()`). That is what a Set accessor would have needed to
  delegate to Map, and it is the reason a wrapper type cannot re-export a
  conditional place today.

- **DF-146p — OPEN, diagnostic quality (Aug 6; RENUMBERED from DF-146l by
  design 176 unit 12 — see the collision note at the head of the design-176
  findings). An exclusivity violation INSIDE
  a place window is reported as a copy error against the container.** Writing
  `m["a"]!.n += grow(&var m)` (or the Vector form `v[0].n += grow(&var v)`) is
  correctly REJECTED — the window body captures the root the window is holding —
  but the message is `cannot copy value of type Map<...> which implements NoCopy`
  with the hint `use `move` to transfer ownership instead`, which is advice that
  cannot help. The window-closure lowering should attribute a capture of the
  window's own root to the open window instead. Pre-existing (the Vector shape
  behaves identically on main), low severity, wrong-signpost rather than
  unsound.

**Follow-up filed by design 127:** the compute budget cannot reach a loop the
coroutine transform cannot state-split. `_split_for` rejects a suspension inside
a `for` over a NON-RANGE iterable ("use a `while` loop"), so 127 skips such a
loop and everything nested inside it — instrumenting one would turn working
programs into compile errors. A long `for x in v.iter()` in a task body
therefore still starves siblings. Lifting it means teaching `_split_for` to
state-split an arbitrary iterator (hold the iterator in the frame and split
around `next()`), which also retires the existing rejection. Same shape, lower
value: a compute loop inside a SYNC callee is likewise unreachable — that one
wants the instrumentation to follow sync call edges out of a task body, which
would make sync helpers suspending and needs a design decision first. [127]

**Follow-up filed by design 130 (now OPEN — 130 landed Aug 5):** decompose the
oversized functions the unsafe migration marked wholly-unsafe —
`__saw_exec_worker` (~150 lines), the `rt/host_*/reactor.saw` bodies,
`rt/common/os_ops.saw` (15 of the runtime's 47 marks on its own) — so the "an
unsafe function is short enough to review as a unit" policy is actually true.
Shape: extract the raw-pointer bookkeeping into small `unsafe` helpers and leave
the surrounding loop safe. Deliberately NOT in 130 (mechanical migration kept
separate from judgment-heavy refactoring of the executor's hot paths). [130]

**P4 — design/gap briefs to consider:** ~~structural `Deinit`/`ExplicitCopy`
synthesis~~ DONE (design 128: deinit is implicit, copy/equality derivations are
`@synthesize`-gated); ~~DF-121a newline-in-brackets~~ (LANDED as design 129,
Aug 5 — the 210-char `blade/src/resolver.saw` signature that was the evidence
is now wrapped); std gaps ranked G1 bit intrinsics (S–M), G2
checked/saturating arithmetic (S, tracker already wants it), G3 slices
(L, language-level), G4 radix/hex formatting (S), G5 iterator adaptors (M);
compiler pre-port restructures R1 declared AST contract + R2 stable NodeId +
R11 astdiff oracle as the port-order prerequisites (then AST+parser next,
coro_transform last).

## Design 155 — irdet in Saw, the first devtool port (LANDED, Aug 7)

Closed items: see todo_aug1-aug9.md.

### What the port found (the DF product)

- **DF-155a — a child's stderr can be merged, but not captured or discarded.**
  `Command.merge_stderr()` landed with unit 1 because the port could not produce
  readable output without it (a corpus sweep expects ~40 compiles to fail, and
  their diagnostics are not the tool's to print). The fuller question is open and
  is a design decision, not an implementation one: a `CommandOutput.stderr` of
  its own needs a second pipe and a second read seam, and would change what
  `output()` does today for every existing caller. Three shapes are defensible
  (separate capture / discard-to-null / the merge that landed); the user picks.
- **DF-155b — std cannot report the core count.** Python's irdet defaulted `-j`
  to `min(10, cores - 2)`; the port has a fixed 8 with `-j` to override. Wanted:
  something like `System.cpu_count()`. Small, and every parallel tool will want
  it.
- **DF-155c — a `String` cannot be a `static`.** Statics take compile-time
  constants and a String owns a heap buffer, so every named string constant in
  the port is a zero-argument function (`func sawc_path() -> String { ... }`).
  It reads acceptably and the call folds, but the ceremony is visible, and the
  no-magic-numbers ruling pushes toward naming MORE constants, not fewer.
- **DF-155f — verdicts do not stream out during a `--all` sweep.** The tool
  spawns every task, then joins in input order — which is what keeps the report,
  the JSONL stream and the exit status independent of completion order (the
  Python one got that from `executor.map`). But a suspending `main`'s loop is
  charged by design 127, so the spawn loop force-yields and the corpus is largely
  CHECKED before the join loop begins: the JSONL records then land in a burst
  near the end instead of continuously. Every verdict still arrives and the
  worker's heartbeat is independent, so this costs a live progress view rather
  than a result. The fix is a sliding window (spawn `2*jobs` ahead, join the
  oldest), which needs a FIFO `Vector` cannot give — there is no `pop_front`, and
  handles are move-only.

## Design 168 — the compile-speed batch: LANDED (Aug 7)

Closed items: see todo_aug1-aug9.md.

- **DF-168a — `_CatchError_{node_id}` is the last node-id-derived name in the
  compiler.** `typechecker/expressions.py:9077`, the union enum a multi-type
  `try`/`catch` synthesizes. Same class as DF-164a, and its own comment claims
  the name "reaches codegen and the emitted type table" — but no current program
  shows it doing so: `try_catch_multi_match` emits ZERO occurrences of
  `_CatchError_` in its `.ll`, and no `try_catch_*` example is among the 45
  `reemitdiff` flagged. Left alone rather than changed on a guess. The fix is
  NOT the mechanical one the other six got: a `try`/`catch` inside a generic body
  can be checked per instantiation with DIFFERENT error sets, so a position-only
  name would let two unions share one layout. Name it from the position PLUS the
  variant identities, or leave it.
- **DF-168b — the place-lowering re-entry re-checks std for every program, and a
  dirty flag cannot avoid it.** DF-164d, measured after the rest of the batch:
  the re-entry is now the single largest stage of a compile (30.3% of `hello`;
  two passes, ~0.4 s, for a driven program). The obvious saving does not apply —
  `hello.saw` is four lines with no place uses of its own and STILL forces it,
  because the program `transform_place_uses` rewrites is **std** (85 extensions),
  and it `uncheck`s every program in its list once any one changed. std is dirty
  for essentially every program. What WOULD work: std's post-lowering state is
  the same for every program, so cache the pair AFTER place lowering. The blocker
  is that `transform_place_uses` gets ONE merged namespace with no per-module
  scoping, so a user `borrows` extension on a std type could in principle change
  how std's own bodies lower — either a design-142 scoping violation to fix
  first, or a contribution the key must cover. A design question, not an
  implementation detail. Worth its own brief: it is ~30% of every compile and
  design 168's cache machinery is most of the implementation.

## Design 138 — the all-sources docs consistency sweep (LANDED, Aug 6)

Closed items: see todo_aug1-aug9.md.

### DF-138c — `std.slab` is not gated by the prelude rule

**OPEN, needs a DECISION (not a guess).** Every import-required std module is
gated: a bare `Data`, `Mutex` or `FixedStringBuilder` is the clean
"`X` is not in the prelude and must be imported" error. `std.slab` is not.
`SlabHead`, `slab_alloc` and `slab_dealloc` all resolve with no import
(`.build/scratch/s06_slab.saw`, `s09_slabfn.saw` — the latter builds a working
`Vector<Int, JobSlab>` over a static region without naming `std.slab` once).

The prelude list in design 82 does not include them, so the rule and the
implementation disagree. Two readings, and the brief's own instruction was to
record rather than guess:

- **slab is deliberately prelude** — it is part of the freestanding toolkit, and
  a kernel writing an allocator arguably should not need the import. Then the
  prelude list gains `std.slab` and the docs are the bug.
- **the gate has a hole** — std/slab.saw's names leak the way std did before
  design 82. Then `sawc` is the bug and the kernel idiom needs
  `import std.slab.*` added to it.

The spec's Slab-allocators example relies on the current behavior, so it is
correct either way today; §9's module table carries a note pointing here rather
than asserting a prelude status the tree does not have.

**TWIN (Aug 7, from the user's repo review): `std.spinlock` has the same
hole.** LANGUAGE_SPEC says it is import-gated (`import std.spinlock`), but
`IMPORT_REQUIRED_STD_MODULES` (sawc.py) lists neither `spinlock` nor `slab`
— verified by grep. Unlike slab there is no prelude-by-design reading:
design 149 documented the import, so for spinlock the gate is simply the
bug. Whatever the slab DECISION is, the fix unit should sweep the whole
std directory against the spec's import table so no third twin survives.

### DF-138b — CLAUDE.md's "complete flag set" line is not complete

**OPEN, trivial.** `CLAUDE.md`'s Compiler-usage block says "That is the complete
flag set (`sawc.py:1274-1345`)" but omits `--target-features`,
`--runtime-provider` and `--ids`. Left unfixed deliberately: this brief's scope
on CLAUDE.md was the orientation digest only. One-line fix for whoever is next
in that file.

## Design 150 — Rust-style imports (LANDED, Aug 6)

Closed items: see todo_aug1-aug9.md.

### DF-150 findings (all FIXED in the brief)

- **Not fixed, recorded:** a bare type name from a whole-module USER-module
  import still half-resolves through `_cross_module_lookup`, producing the
  nonsense `cannot assign `Point` to variable of type `Point`` rather than a
  clean "not in scope, did you mean `qmod.Point`". std is unaffected (the
  prelude gate catches it first with the three-form hint, which is what the
  brief's negative test pins). Repro: a `let p: Point = Point(x: 1, y: 2)`
  under `import qmod`. Worth a small follow-up; the fix is to stop
  `_cross_module_lookup` answering for qualified-only imports, which needs a
  check of what else depends on that fallback.

## Design 163 — frame-overlay sizing: the INVESTIGATION REPORT (Aug 7 — user decides)

Closed items: see todo_aug1-aug9.md.

`designs/163-frame-overlay-investigation.md`. Measurement + constraints only; no
layout change shipped. **Lead recommendation: DECLINE the overlay now, land the
tooling, and put design 152's frame-size warning on top of it as the trigger to
revisit.** The reasoning is that the saving is large in theory and ~absent in
this tree, while the cost lands squarely in frame teardown — the code path that
has produced a silent double-free in four separate briefs (124/131/134/146).

### What landed (tooling only — no behavior change)

- **`sawc --emit-frame-layout`** (`sawc/frame_layout.py`, flag in `sawc/sawc.py`,
  mirroring `--emit-ir`'s shape). JSON per monomorphized `__Frame_*`: total ABI
  size + alignment, every field's offset/size/alignment, which fields are
  embedded children (`kind: "sub"`, with the callee frame and the resume state
  the child is live in), plus `own_bytes`/`sub_bytes`, the state count, and the
  spawn-root/method flags. Layout comes from LLVM (`codegen.struct_types` is the
  authority); a `layout_agrees` field cross-checks our C-layout walk against
  `get_abi_size` and was true for all 339 frames measured.
- **`tools/framesizes.py`** — sweeps a corpus, aggregates the distribution and
  top offenders, and solves the overlay recurrence bottom-up. `--only`,
  `--top`, `--json`, `--frame NAME`.
- **Two three-line stashes in `coro_transform.py`** feeding the report:
  `info['drive_state']` in `_emit_nested_call`, and `frame_struct.coro_frame_info`
  at the end of `build_resume`. Read-only; no codegen consults them.

### Unit 1 — reality

Corpus = `examples/` (103 programs contain a suspending function; 339
monomorphized frames). **`blade` and the SOS kernel contribute ZERO frames** —
both are entirely synchronous, so `--emit-frame-layout` reports `"frames": {}`
for each. Two of the brief's three flagship shapes therefore do not exist.

Frame size today: min 32, **p50 72**, p90 432, p99 672, **max 688** bytes; mean
140. Per-task spawn cost (177 spawn-root frames, each a heap box): mean 181 B,
max 688 B.

The shape that decides everything is the **child-count histogram**:

| children | frames | share |
|---|---|---|
| 0 | 271 | 80% |
| 1 | 38 | 11% |
| 2 | 15 | 4% |
| 3 | 15 | 4% |

Overlay can only help a frame with **two or more** children — 30 frames, 9% of
the corpus. Nothing in the tree has more than three.

### Unit 2 — the hypothetical

Every `__subN` is live in **exactly one** resume state. Construction and the
`_goto` into the drive block happen in the same resume tick (`_goto` is a state
assignment + `continue`, never a suspension) and the Done arm moves the result
out and leaves for `after`, so the child's storage is live precisely while
`__state == drive`. The tool CHECKS this rather than assuming it: **zero
violations across all 339 frames**. So the overlay size is a clean recurrence —
`overlay(F) = layout(F's own fields, with the contiguous `__subN` run replaced
by one slot of size max over children of overlay(c))`.

Corpus-wide: **47600 B → 41344 B, 13.1%**. Only 30/339 frames shrink; of those,
median size after overlay is 65% of today. Restricted to the frames that CAN
shrink (>=2 children): 17576 → 11320, **35.6%** (min 25%, max 43%). Spawn roots:
**147 of 177 (83%) are unchanged**; the mean falls 181 → 146 B. Taking each
program's largest task frame (the real per-task heap box): mean **155 → 132 B**,
14.8% across 103 programs.

Top offenders today: `__Frame_recirc` / `__Frame_iflet_shadow` 688 → 400 (42%),
`__Frame_guardlet_*` 672 → 384 (43%), `__Frame_serve` 656 → 424 (35%).

**Flagships.** The accept-loop server (`net_accept_loop_concurrent`) is the
disappointment: `__Frame_server` is **552 → 552, 0%**. It has ONE suspending
call site (`listener.accept()`), and its bulk is a 296-byte `TaskGroup` local,
not children. Its siblings do better — `__Frame_client` 536 → 392 (27%),
`__Frame_handle` (`net_http_roundtrip`) 576 → 432 (25%). Blade's dependency walk
and the SOS root have no frames at all.

**But the corpus understates the model badly.** A synthetic probe
(`.build/scratch/probe_width2.saw`, using `TcpStream.read` as the suspension)
separates the two axes:

| shape | children | today | overlay | saving |
|---|---|---|---|---|
| `w1` — 1 call site | 1 | 272 | 272 | 0% |
| `w2` — 2 sequential | 2 | 496 | 352 | 29% |
| `w4` — 4 sequential | 4 | 944 | 512 | 46% |
| `w8` — 8 sequential | 8 | 1840 | 832 | 55% |
| `d1` — depth-4 chain, 1 call each | 1 | 496 | 496 | **0%** |
| `t3` — branching 2, depth 1 | 2 | 608 | 336 | 45% |
| `t2` — branching 2, depth 2 | 2 | 1280 | 400 | 69% |
| `t1` — branching 2, depth 3 | 2 | 2624 | 464 | **82%** |
| `root` — 6 call sites over the above | 6 | **6768** | **928** | **86%** |

Depth ALONE saves nothing, exactly as predicted — a call chain is genuinely
live at once, so the chain IS the high-water mark. The blow-up is
**branching x depth**: today's flat-frame model is O(k^depth) in a call tree of
branching factor k, the overlay is O(depth). A 6-call-site root over that tree
is **7.3x**. Nothing in the tree today is anywhere near it, but an ordinary
HTTP-handler decomposition (parse -> headers -> body, each calling two
suspending helpers) lands in the `t1`/`root` regime, and Saw boxes one frame
per task.

### Unit 3 — constraints

| # | constraint | verdict |
|---|---|---|
| 1 | `lend` windows (141/146) | **compatible** |
| 2 | state-aware teardown (124/134) | **needs work — the whole cost** |
| 3 | design 158 backtrace tables | **compatible** (gets simpler) |
| 4 | held references / re-borrows (88/106) | **compatible** |
| 5 | DF-138a spawn trampoline | **compatible** (no interaction) |
| 6 | generation-checked slots (134) | **compatible** (no interaction) |

**1. Lend windows — compatible, and the hazard cannot arise today.** A `borrows`
accessor is forced `sync`: `place_transform.py:194-198` sets `decl.is_sync = True`
unconditionally, and `effects.py:698-709` rejects any suspension in it. The
window PARAMETER's type is built `sync` too (`place_transform.py:168-173`,
`:181-184`), and the use site synthesizes a closure checked against it
(`place_uses.py:482-513` -> `effects.py:282-284`), so a suspending call inside a
window is rejected before the coro transform ever runs (place lowering precedes
it and forces a re-typecheck). A `borrows` accessor is therefore never a
coroutine, has no frame, and occupies no `__subN` — a lend window makes ZERO
children live, not two. The brief's "lend-until-epilogue" hazard is real as a
liveness description and vacuous as a constraint. Two riders: nothing pins the
rejection with a test (it is structural, via two independent `sync` gates), and
DF-146k floats `shared borrows` (its `borrows -> &T` alternative is a parse error
since DF-163a's fix) — if that fence is ever lifted this becomes a genuine
two-live-children shape and overlay needs re-verification.

**2. State-aware teardown — NOT state-keyed today, and this is the entire cost.**
`__release` is a flat statement list with no reference to `__state`
(`coro_transform.py:4189-4227`; its one conditional is the `__io_fd >= 0`
reactor disarm), and it deliberately EXCLUDES sub-frames — `_owned_frame_fields`
(`:4170-4187`) documents "each sub-frame releases itself at ITS own Done". Child
storage is reclaimed by the frame struct's MEMBERWISE teardown
(`codegen/resources.py:637-664`, `_emit_field_cleanup_at` recursing into each
`__subN` by STATIC FIELD TYPE), which is also the path a frame torn down WITHOUT
completing takes at group teardown. The whole correctness argument today is
"every owned field's None/Some tag is a valid drop flag at all times": the frame
is fully `StructInit`'d at construction (`_build_frame_init:4267-4316`,
recursively zero-initializing every embedded child) and a completed child left
all its fields None, so re-dropping it is a no-op. Overlay breaks the
*at all times* clause. Three sites need work, all mechanical given each child's
single live state:

  (a) `_emit_field_cleanup_at` must switch on `__state` to pick the live child's
      TYPE — nothing else can, and a shared slot has no single static type.
  (b) `_build_sub_frame`'s rebuild store (`:3789`, through
      `codegen/statements.py:497-509` "LIVE-SLOT RELEASE") drops the slot's prior
      occupant AS THE NEW CHILD'S TYPE — a type confusion the instant two callee
      frames share an offset. The overlay slot must be stored WITHOUT the
      live-slot release; it is known dead.
  (c) `_build_frame_init`'s recursive child zero-init becomes one slot zeroing.
      This is a construction-cost WIN, not just a size one: today spawning a task
      writes the whole sum-sized frame, so `root` above memsets 6768 bytes to
      construct what the overlay would construct in 928.

**3. Design 158 tables — compatible, and simpler.** 158 is a brief, not code, so
the constraint is on the design. Because each child is live in exactly one
state, `(function, state) -> child offset` stays a static function of the state;
under overlay the OFFSET becomes constant (the slot) and only the child TYPE
varies by state — which the table must record anyway.

**4. Held references — compatible; no legal program can observe a reused slot.**
Seeded reference arguments always point from a child OUTWARD into the caller /
task frame (`coro_transform.py:3784-3793`, "a raw pointer into THIS (caller)
frame's storage"; `__recv` likewise at `:3796-3807`) — never sideways at a
sibling, never down into a child. A callee's result is COPIED OUT into a caller
local plus `__saw_forget` before the slot is released (`:3714-3722`). Probed the
one hole the code review flagged, `-> &T`: `return v` on a `&Int` param fails
("expected return type `&Int` but got `Int`"), but `return &v` and
`return &local` both COMPILE (see DF-163a, fixed Aug 7 — a reference return is a
parse error now, so what follows records what the probe found on the day). The
suspending case — the only one
that could aim into a sub-frame — is closed on BOTH paths: spawn rejects cleanly
("local `r` of type `&Int` is a reference held across a suspension"), and the
driven path errors (see DF-163c).

**5/6. Trampoline and generation slots — no interaction.**
`_make_spawn_trampoline` (`:4754-4808`) synthesizes `f$spawnroot` whose sole
statement embeds `__Frame_f`: one child, one drive state, high-water mark ==
sum, so overlay neither helps nor hurts it. The generation counter is
`TaskGroup.gen: Vector<Int>` (`std/taskgroup.saw:278-287`, bumped in
`__recycle:451-458`) with handles as `(slot, generation)` pairs; no
generation state lives in a frame, whose only 134 field is `__cellp`.

### Unit 4 — recommendation

**The brief's suggested cheap partial (branch-arms-only) should be declined on
its own terms.** It was proposed to "dodge the sequential-liveness analysis" —
but the measurement shows there is no such analysis to dodge. Sequential
liveness is already exact and free: the transform stamps each child's single
live state, and it held across all 339 corpus frames with zero violations.
Branch-arms-only would be strictly MORE work (it must distinguish arms) for
strictly LESS saving. The real choice is implement-in-full vs decline.

**Recommend DECLINE now, with a trigger.** The case against implementing today:

- 13.1% corpus-wide, and 80% of frames have no children at all.
- 83% of spawn roots do not move; the mean per-task frame is 155 B.
- The flagship accept-loop server saves **0%** — its bulk is a `TaskGroup` local.
- Two of the three flagship shapes (blade, SOS) have no coroutines whatsoever.
- The cost is concentrated in frame teardown, where a mistake is a silent
  double-free, and where 124/131/134/146 each already found one.

The case for is entirely prospective and rests on the `root` number: the model
is multiplicative where the overlay is additive, so the day a real Saw server
gets a normal handler decomposition, per-task memory jumps by ~7x with no
warning. That is a good reason to make the exponential VISIBLE and a poor reason
to rewrite teardown before any program has hit it.

**So: land the tooling (done), and hang design 152's task-frame-size warning off
`--emit-frame-layout`'s data** — the same numbers, reported at compile time.
Suggested threshold from the measured distribution: warn above ~1 KB (p99 today
is 672 B, max 688 B, so the corpus is silent) and additionally when a frame's
`sub_bytes` exceed its `own_bytes` by more than 2x (the signature of the
branching blow-up; no corpus frame trips it — the >=256 B frames split 45% own /
55% embedded). **Revisit 163 the first time a real program trips either.** The
transform sketch is written down above (three sites, (a)-(c)) so picking it up
later is cheap.

If the user prefers to implement now, the shape is: keep the source-level
`__subN` fields exactly as they are and do the overlay in CODEGEN — emit the
frame struct as `{own fields..., [N x i8] __overlay}` in `_register_struct` and
resolve each `__subN` GEP to the slot. That confines the change to layout +
field addressing + the three teardown sites, leaves `coro_transform` untouched,
and keeps the state-keying in one place. Test plan: an example per child-count
(2, 4, 8 sequential) asserting output AND an `EXPECT-OBJECT-MAX-BYTES`-style
size bound; a cancellation test per shape (the group-teardown path is the one
`__release` does not cover); a loop-carried rebuild test (site (b)); the
`t1`/`root` tree shape end-to-end; and `irdet --all`, since the slot's size is a
`max` over a dict-ordered child set and is exactly the kind of thing design 141
caught being nondeterministic.

### DF findings from the investigation

- **DF-163b — a nested `yield_now()`/`sleep()` silently does not cede.** A user
  helper whose only suspension is a cooperative primitive is treated as
  suspending when spawned DIRECTLY (2 states) but NOT when called from another
  suspending function: the call is emitted as a plain sync call and the caller
  gets one state and no `__subN`. Repro (`.build/scratch/probe_susp3.saw`):
  `func helper(n: Int) -> Int { yield_now()  n + 1 }`;
  `func viahelper(n: Int) -> Int { let x = helper(n)  let y = helper(x)  y }`;
  `group.spawn(viahelper(1))` -> `__Frame_viahelper` has `states: 1`,
  `children: []`. `group.spawn(helper(1))` -> `__Frame_helper` has `states: 2`.
  Same for `sleep`. The program runs and prints the right answer — it just never
  yields, which is the "never silently block" contract design 96/101/104 exist to
  hold. A std suspending METHOD (`stream.read()`) propagates correctly through
  the same nesting, so this is specific to the cooperative free-function
  primitives. **Worth its own brief** — it also means the corpus measurement
  above UNDERSTATES the child population: fix this and more frames gain children.
- **DF-163e — CLOSED BY RULING, note for whoever picks up DF-146k.** DF-146k
  floats `shared borrows` *or* `borrows -> &T` as spellings for a shared-flavor
  place. `borrows -> &T` is now a parse error like any other reference return, so
  `shared borrows` (or an equivalent that never names a reference) is the only
  live candidate. Nothing to do unless 146k is taken up.

## Design 160 — remote test worker (LANDED, Aug 6)

Closed items: see todo_aug1-aug9.md.

- **DF-160d — the daemon's silent console costs operator confusion (Aug 7,
  from the user's first Studio deployment attempt).** The user saw /health
  answer (core count reached the client) and concluded nothing was happening
  remotely, because a healthy job shows NOTHING on the worker's console — job
  output goes to per-job log files and per-request HTTP logging is
  suppressed. Follow-up: a `--verbose` console mode (request lines + job
  lifecycle + a pointer to the live log path at job start), and the startup
  banner should print WHERE job logs will appear. Small unit, rides any 160
  follow-up. The user's deployment investigation is still open — first real
  sandbox application (DF-160a below) also still pending.
- **DF-160a — the sandbox profile could not be APPLIED during development, only
  compiled.** A process already inside a seatbelt sandbox cannot apply a second
  one: `sandbox_apply` returns EPERM, so `sandbox-exec` fails outright from
  inside a sandboxed agent (and `launchctl submit`, the obvious escape, is
  unavailable). Everything else in the design was validated against a live
  loopback worker; the profile was validated by COMPILING it through
  libsandbox, which resolves every operation and filter name against the
  running kernel and rejects a profile naming one that does not exist (proven
  by a negative case in the self-test). What remains unproven until the user
  runs it on the Studio is whether the allowances are SUFFICIENT — a denial
  would show up as a job that fails where the same job passes locally. The
  daemon's startup line reports `sandbox: ACTIVE`, and the first
  `remote_battery.py` run against the real machine is the check. If a gate
  fails there and not here, the profile is the first suspect: `log stream
  --predicate 'sender == "Sandbox"'` names the denied operation.
- **Follow-ups, not blocking.** (a) SOS stays local — QEMU on the worker is
  the opt-in the brief deferred. (b) One job at a time; a second client
  degrades rather than queues, which is right for two machines and would want
  revisiting for three. (c) The worker keeps `.build/rt` between jobs keyed by
  a digest of `sawc/`; nothing else survives a job, so a compiler-touching
  brief pays one runtime build per submission.

## Design 151 — discarding a `Result` is an error (LANDED, Aug 6)

Closed items: see todo_aug1-aug9.md.

- **DF-151m — FILED, NOT FIXED (typechecker; found while fixing DF-151j,
  Aug 7).** **`&var` into a projection rooted at a `let` binding compiles and
  mutates — the `let` promise is broken for fields, tuple elements AND fixed
  array elements alike.**
  ```saw
  func bump(x: &var Int) { x = x + 1 }
  let p = Pair(a: 1, b: 2)
  bump(&var p.a)
  print("{p.a}")            // 2 — no error, and the `let` was written through
  //                           `p.a = 2` on the same binding IS rejected
  ```
  PRE-EXISTING and not tuple-specific; tuples inherit it because DF-151j made
  them consistent with fields, which is the correct outcome for that unit and
  the reason this is filed rather than fixed there. `_check_reference_expr`
  checks `&var` mutability for an Identifier operand, for `self`, and for a
  projection out of a `&self` receiver (`_projects_from_self`, DF-146b) — but
  there is no arm for a projection rooted at a LOCAL, so the walk
  `_assign_target_immutable_struct_root` already performs for every assignment
  target is simply never run on a reference operand.
  Expected shape: run that same walk in `_check_reference_expr` when
  `expr.mutable` and the operand is a projection, with the message the
  assignment path gives. Blast radius is why it is its own unit — the rule
  reaches every `&var` into a field or element in std, blade and the libs, and
  any legitimate one written through a `let` root today becomes a compile error
  that has to be re-spelled `var`.
- **DF-151k — FILED, NOT FIXED (typechecker; found while fixing DF-151i,
  Aug 7).** **`type_satisfies_copy_bound` has no OPTIONAL and no TUPLE arm, so a
  fixed array of either is refused `.copy()` even when the element tier provides
  one.**
  ```saw
  let a: [Arc<Res>?; 2] = [...]
  let b = a.copy()
  // error: type `[Arc<Res>?; 2]` is not Copy; its element type is not copyable
  // ... and the same for `[(Arc<Res>, Int); 2]`
  ```
  Both messages are false: `Arc<Res>?` and `(Arc<Res>, Int)` each report an
  'implicit' `copy_tier`, and `o.copy()` / `t.copy()` on those very types
  compile. The array arm of `_check_copy_call` is the only `.copy()` path that
  consults `type_satisfies_copy_bound` instead of `copy_tier`, and that
  predicate answers structurally for ARRAY and FUNCTION and then falls to a
  NAME lookup — an optional and a tuple have no name, so both return False.
  Only NON-trivial element payloads are affected: `[Int?; 2]` and
  `[(Int, Int); 2]` copy fine, caught by the `is_trivially_copyable` test at the
  top, which is why this sat unnoticed.
  Shared by two wrappers, so it is not tuple-specific and was left out of
  DF-151i deliberately — the surface there was the `.copy()` arm, and
  `type_satisfies_copy_bound` also gates generic `T: Copy` bounds, giving a fix
  a wider blast radius than that unit's scope. Expected shape: give it the two
  structural arms its ARRAY arm already models (a wrapper satisfies the bound
  iff its payload/elements do), then re-check what widening the `T: Copy` bound
  admits — `Vector<(Arc, Int)>.iter()` becomes legal, which is correct per
  design 139 but should land with a test.
  Repro noted in `df151i_tuple_copy.saw`, where the array-of-tuples case is
  commented out rather than written.
- **DF-151g — FILED, NOT FIXED (codegen; found while fixing DF-151d, Aug 6).**
  **A `_`-discarded NoCopy payload in a match arm never runs its deinit.**
  ```saw
  enum Slot { case Filled(r: Res), case Empty }   // Res is NoCopy with a deinit
  match filled() { case Filled(_) -> 1, case Empty -> 0 }   // Res.deinit never runs
  ```
  Deliberate, and deliberately wrong for this case. `match.py`'s design-65 (L17)
  branch releases a `_`-bound owning payload with `_emit_release_at`, which
  RELEASES a refcounted field but leaves a non-refcounted `Deinit` one untouched
  — because `Map._slot_state`'s `Occupied(_, _)` peek matches a by-value,
  NON-RETAINED copy of a slot the map still owns, and firing the payload's deinit
  there would destroy the map's live value. So the same code serves an OWNER and
  an ALIAS, and it can only be right for one.
  Same for a NAMED local (`let s = filled(); match s { case Filled(_) -> ... }`),
  so it is not about DF-151d; an `Arc` or `String` payload is unaffected (the
  release is the whole drop). The real fix is upstream: `Map._slot_state` should
  read its slot through a BORROW rather than a by-value copy, at which point the
  consume path stops seeing an alias and this branch can become a full
  `_emit_drop_at`. Doing it the other way round — changing the release to a drop
  first — would break the design-61 exactly-once VALUE tests, so the order
  matters. `examples/df151d_match_temporary_scrutinee.saw` measures an
  `Arc<Res>` payload for exactly this reason; a bare NoCopy payload would have
  read as a leak that is this finding, not that one.

## Design 149 — runtime authoring in Saw (LANDED, Aug 6)

Closed items: see todo_aug1-aug9.md.

**Not in v1:** a non-trivially-destructible static (statics stay deinit-free);
relaxed/acquire-release orderings on `Atomic` or `SpinLock` (everything is
seq_cst); a `SpinLockIrq` for the same-core ISR case, which the brief assigns to
sos-side composition when M2-era interrupt work lands.

## Design 145 — DF-findings (enum methods; the std private-symbol reach)

Closed items: see todo_aug1-aug9.md.

- **DF-140h-fn — OPEN, stopped deliberately (unit A, design 145). Wants its own
  brief.** The same reservation exists for private std FREE FUNCTIONS, and the
  fix is a materially bigger change than the statics half. Repro:

  ```saw
  func tcp_socketpair() -> Int { 77 }   // private in sawc/std/net.saw
  func main() { print(tcp_socketpair()) }
  // error: function `tcp_socketpair` is already defined with an
  //        indistinguishable signature
  ```

  Also `unix_timestamp` (std/time.saw — which is separately worth a look: it is
  a DOCUMENTED std.time API function declared without `public`). The
  `__saw_exec_*` family in std/taskgroup.saw is worse than reserved: redefining
  one reports `internal compiler error: Undefined function: __saw_exec_run`
  rather than any diagnostic.

  Why it did not land with the statics half: statics have one identity (a name),
  so a per-module overlay is contained. Functions carry OVERLOAD SETS, and
  design 55/66/105 built the `$OL$` symbol scheme assuming one flat set per
  name. Filtering the set by accessor module was tried and gets the front end
  right, but two same-named functions from mutually-invisible modules then reach
  codegen as one overload set and ICE (`internal compiler error:
  tcp_socketpair$OL$`). Doing it properly means making overload-set IDENTITY
  module-scoped — a per-module overlay for private functions, a std-side
  symbol-stamping pass (`_stamp_module_private_functions` runs only from
  `check_module` and guards on `def_module == own_module`, so std never reaches
  it), and a decision about whether a module's private function overloads with a
  public one visible in that module. That is a design question design 145 does
  not settle, so the front-end change was reverted rather than landed half-done.

## Design 137 — DF-findings (fixed-capacity formatting)

Closed items: see todo_aug1-aug9.md.

- **DF-148b — FILED (design 148, found writing `std/fixedbuf.saw`). A `static`
  is not readable from a `static_assert` condition**, so a threshold used in one
  has to be a literal even where the codebase has a name for it
  (`static_assert(N >= 5, ...)` in `FixedStringBuilder.init`, where
  std.stringbuilder calls the same number `MIN_FIXED_CAPACITY`). This collides
  with the no-magic-numbers style rule. The evaluator now HAS an identifier arm
  (design 148 gave it one for const parameters), so the fix is small: admit a
  `static` whose initializer is itself const. The comment at
  `codegen/core.py:1562` already claims statics are emitted first "so
  const-static references resolve" — it was aspirational.

- **DF-148a — FILED (design 148 unit B). A repeat literal cannot repeat a
  GENERIC element, because no bound expresses "copies are free".** `[t; N]`
  where `t: T` is refused: `T: Copy` admits ExplicitCopy (which needs a
  `.copy()` per slot, and a repeat has nowhere to write one), while
  `T: ImplicitCopy` excludes the POD types that are freer still — so `Int` fails
  an `ImplicitCopy` bound and the natural `Ring<T, const N: Int>` is unwritable.
  The element type is concrete in v1 and the error says so. Two ways out worth
  deciding between: a bound that means trivial-or-ImplicitCopy, or letting
  `T: Copy` through and emitting a per-slot `copy()` in codegen (which is what
  the splat loop already does for the retain case). Not urgent — the acceptance
  shape `FixedBuf<const N: Int>` has a concrete `UInt8` element — but it is the
  first thing anyone writing a generic container will hit.

- **Follow-up (not a bug): the `{}` Printable scratch is per call site.** Each
  user-`Printable` format argument gets its own 512-byte entry alloca, because
  every segment of a `panic` message is built before any is concatenated — two
  arguments sharing one buffer would print the second value twice
  (`format_args_panic` pins this with two of them). Across SEPARATE format calls
  the buffers could be shared, since each call consumes its segments before the
  next runs, so a function with N such arguments costs N x 512 bytes of stack
  where it could cost (max args in one call) x 512. Not pooled here: the win is
  bounded and the failure mode of getting it wrong is silent wrong output. Worth
  doing for the embedded profile, ideally alongside LLVM lifetime intrinsics so
  stack coloring can do it rather than the frontend.

## SOS M1 — design 140 (BUILT, branch PARKED for user review)

riscv32 boot-to-root-server. `make sos-test` is 11 cases; the two-image boot
prints kernel banner -> root banner -> clean exit. SOS-review policy applies:
the branch is NOT integrated without explicit user sign-off.

> **SUPERSEDED BY THE ADOPTION PASS (Aug 6).** The branch to review is now
> `worktree-agent-ae0afeb4057ec52bc` — this work rebased onto main at bbdb2e3
> and modernized to designs 139-161. The original parked branch
> (`worktree-agent-a45480eb72c6ab0f1`, 8b027c7) no longer compiles against
> current main. See "SOS M1 — the adoption pass" below for the rebase conflicts,
> what changed, and the open questions. Everything in THIS section still
> describes the design; only the spellings moved.

REVISED after the first user review (five items + a rebase onto designs
132/133). The numbered-syscall pin below is SUPERSEDED by the object-op model.

**Pins TAKEN as written.** Syscall ABI per §5.7: a0 = HANDLE, a7 = OP, args
a1-a5, returns a0 = status / a1 = value, and EVERY syscall is an object op
(ratified Aug 5) — the earlier `0 debug_putc` / `1 exit` numbered table is
gone. The v1 object is the **System** singleton with ops `debug_print` and
`shutdown(status)`, rights-gated on DEBUG / SHUTDOWN; `exit` is deliberately
absent because process exit belongs to the future Process object. Dispatch is
§3's shape verbatim: handle-table lookup -> object type -> op table -> rights
check -> op. Root receives the System handle at boot (§12), in the first
argument register, so a Saw `_start(boot_handle: UInt)` just takes it. sosimg
magic `SOSI`, u16 version = 1, u8 segment count, the u32 §7 priority-map field,
all fixed-width little-endian (design 47). Root as an APPENDED BLOB after the
kernel image with linker-symbol bounds (`.payload`, `_payload_start` /
`_payload_end`) rather than a flash partition table. `[sos]` manifest section
driving a Blade `emit = "sosimg"` target. A U-mode fault or a malformed image
prints a cause tag and exits FAIL — M0's never-hang discipline kept throughout.

**Round 3 — API ownership (spec §5.7's vDSO discipline, ratified Aug 5).**
The typed wrappers moved into a PUBLIC `sos` module owned and exported by the
kernel package (`sos/kernel/sysapi/`, U-mode library code living in the
kernel's tree). Every op number, rights bit and status tag lives in ONE
kernel-internal package (`sos/kernel/abi/`) imported by BOTH the kernel's
dispatch tables and those wrappers, so the two halves of the contract cannot
skew and the kernel may renumber freely. Root dropped its own wrapper and stub
knowledge entirely and imports `sos` as a path dependency; a grep for an op
name across `sos/root/`, `sos/hal/` and `sos/tests/faulting-root/` sources
returns nothing. The kernel package also `@export`s a per-op C-ABI surface
(`sos_system_debug_print`, `sos_system_shutdown`) over the fixed-arity raw
`sos_syscall1` over the per-arch `ecall` stub — one implementation chain, three
entry altitudes (typed Saw, typed C, raw), with the Saw wrappers riding the
same chain rather than a second trap path. The user HAL's own runtime sinks
call the typed C surface, so the C altitude is exercised on every boot instead
of only being linked; root additionally calls `print` once, which runs the
whole C chain and demonstrates design 137's alloc-free formatting inside a
U-mode process. Each seam doc gained a short note saying which altitude is
supported for whom.

**Structure the revision landed** (review items 1-5):
- The format is a SHARED package, `sos/imgformat/` — the two structs, the
  constants, the `static_assert` ABI pin, and the target-independent
  well-formedness predicates. Consumed by BOTH sides and by both mechanisms:
  Blade through a manifest path-dependency, the kernel through
  `--module-path`. Kernel-specific bounds (ROOT_LOAD_BASE, the PMP budget)
  stay kernel-side.
- The kernel loader reads through TYPED VIEWS — `UnsafeMemory<SosimgHeader,
  Normal>(addr).read()`, then `seg.mem_len` — not offset arithmetic. The whole
  offset-constant family is gone. The validation logic and its overflow-careful
  order are unchanged; only the fetches are.
- Blade's byte helpers are a module-PRIVATE `extension Data`, called as
  methods. Being private is load-bearing: `blade/tests/sosimg_wire.saw` cannot
  reach them and brings its own reader, so a bug in the helpers cannot cancel
  itself out.
- `sos/rt/common/` (Saw, arch-free and role-free) + `sos/rt/common_c/support.c`
  (the C that must stay C, once) + `sos/hal/riscv32/{kernel,user}/` with an
  ABI.md per side. The ~200 duplicated lines across the two rt.c files are
  gone. NO arm64 directories were created: M1b adds them without moving
  anything.
- `[sos] native` is a space-separated LIST pointing into the HAL, so a root
  package's own sources name no architecture.
- Lockfiles committed for `sos/root` and `sos/tests/faulting-root` (app policy).

**Pins ADJUSTED (each veto-able; reasons given).**
- **sosimg field order + padding.** Header fields are ordered and padded so
  every u32 sits on a 4-byte boundary: magic(4), version(2), seg_count(1),
  reserved(1), entry(4), prio_map(4) = 16 bytes, then the segment table. The
  brief's order put `entry` at offset 6. Alignment is what lets the kernel's
  loader read the header with plain word loads instead of byte assembly.
- **`entry` is an absolute load address, not an offset.** Nothing relocates on
  Profile A (physical addresses, PMP not paging), so an offset would only be a
  base-addition the kernel has to perform and validate. Root is linked at a
  fixed address by root.ld either way.
- **Each segment record carries `mem_len` beside `file_len`** (20-byte record,
  not 13). The pinned record cannot express a segment whose memory image
  exceeds its file image, so a loader built from it could not zero-fill `.bss`
  — and root's `.bss` is a 4 KiB arena. The kernel zeroes `[file_len, mem_len)`.
- **`[sos] native = "<file>"` added** (not anticipated by the brief). A
  freestanding SOS process needs an `ecall`, which no amount of Saw expresses;
  root's `src/rt.c` is the syscall stubs plus the `__saw_rt_*` seams, the same
  minimal-native-surface shape as `sawc/rt/shim.c`. One translation unit.
- **PMP budget = 4 TOR regions** (8 of QEMU's 16 entries): up to 3 image
  segments plus the kernel-granted stack. Root links to 2 segments (R+X,
  R+W), so there is one spare. An image asking for more is rejected as
  malformed rather than silently under-protected.
- **Root region pinned at 0x8020_0000..0x8024_0000** (256 KiB) with a 16 KiB
  stack at the top, recorded in virt.ld's memory map and mirrored by root.ld.
  The kernel VALIDATES rather than assumes, so a mismatch is a diagnostic.
- **`boot_smoke` became `no_root_image`.** The kernel now requires a root
  image; built without one it must say so and FAIL, not exit 0 as if the
  system had run. The M0 banner assertion moved to the two-image case.
- **`debug_print` carries ONE CHARACTER in a1, not a (ptr, len) pair.** Passing
  process memory to the kernel needs bounds machinery that belongs with
  MemoryObject — the kernel would have to know which ranges the caller was
  granted, which is Process-object state M1 does not have. One character per
  op is seL4's `DebugPutChar` shape and keeps the op honest about what it can
  check. The typed wrapper hides it: root writes `system.debug_print(msg)`.
- **`umode_bad_syscall` became `umode_bad_calls`** and inverted. Under the
  object-op model a bad op or a bad handle is an ERROR, not a fault: the kernel
  returns a `SysError` status and the process runs on. The payload now checks
  three statuses itself (OK on a valid call, BAD_OP, BAD_HANDLE) and shuts down
  with 7 only if all three matched, so the emulator's exit code is the
  assertion.

**Bug found and fixed while revising (standing fix-on-discovery policy).**
`blade build` exited 0 on a failed build — only `blade test` ever called
`exit()`, so every other command printed `error: ...` and reported success.
A stale `sos/root/Saw.lock` therefore produced a "successful" build that
silently shipped the PREVIOUS image, and the SOS suite booted it without
noticing. Every failing path in `blade/src/main.saw` now exits non-zero
(carrying `BuildError.exit_code` where there is one), and `sos_runner.py`
deletes an existing image before rebuilding so a stale artifact cannot stand in
for a fresh one.

**Open / deferred.** The parsed `prio_map` is reported on the console but not
yet STORED — there is no Process object until the object-model brief (§7 says
the kernel stores whatever map the launcher passes; root's is applied
verbatim). The kernel's `__atomic_*_4` bodies in `sos/kernel/rt.c` and
`sos/root/src/rt.c` are plain read-modify-write, correct ONLY because v1 is
uniprocessor with no interrupts enabled (spec §7); enabling interrupts or SMP
must replace them, and building the Saw object for `rv32ia` would retire them.
A singleton `static` driver still awaits Once/Lazy (tracker F5), so `console()`
constructs its `Uart16550` per use.

## SOS M1 — the adoption pass (Aug 6, branch RE-PARKED for user review)

**Branch: `worktree-agent-ae0afeb4057ec52bc`.** The parked M1 branch
(`worktree-agent-a45480eb72c6ab0f1`, 8b027c7) rebased onto main at bbdb2e3 and
brought up to the rules that landed while it sat — designs 139-161. SOS-review
policy still applies: NOT integrated without explicit user sign-off. `make
sos-test` is 11/11 and the full battery is green (numbers at the end).

**The rebase.** Seven M1 commits over 118 commits of main, four conflicts, all
in shared plumbing rather than in SOS logic:

- `sos/kernel/main.saw` — main's design-135 commit edited comments in the M0
  kernel body that M1's unit A had already moved into `core/lib.saw`. Took M1's
  structure; the design-135 substance (the sos gate builds under
  `--no-hidden-alloc`) survives in `sos_runner.py`, whose comment says it.
- `tools/sos_runner.py` (twice) — main added `--no-hidden-alloc` to the compile
  line, M1 added `--module-path kcore=...` and the payload-object list. Both
  wanted, so both kept.
- `.gitignore` / `Makefile` — additive on both sides. One real decision:
  M1's own internal-rebase commit had already DELETED its `*.sosimg` ignore
  rules because design 143 moved Blade artifacts under `<package>/.build/`, so
  the deletion is what survived, alongside main's worker-jobs and fixture-lock
  rules.

**Two compiler bugs, found by writing the adopted idioms and fixed here.** Both
have regression tests in `examples/` and are why the branch touches `sawc/`.

- **DF-140j — a place use inside a struct or map literal reached codegen
  unlowered (ICE).** `place_uses._recurse` tested each list item for
  `Expression` then `ASTNode`. `StructInit.field_inits` is `(field_name, value)`
  and `MapLiteral.entries` is `(key, value)` — plain tuples, neither test — so
  the expressions inside them were never walked and a `borrows` accessor in
  those positions met codegen raw: `internal compiler error: Undefined method:
  Holder.at`. `let` and argument positions worked, which made it read as a
  module-boundary problem for a while. `_recurse` now descends into a tuple item
  through `_paired`. Test: `place_paired_literal_fields.saw`.
- **DF-140k — an extension method's parameter types were never resolved.** The
  parser gives every bare named type a STRUCT kind and only resolution knows
  which names are enums. A plain function has always resolved its parameters
  before binding them; an extension method did so only for a module-QUALIFIED
  annotation (design 68's L18 fix). Nothing noticed until a backed enum met
  design 145's cast, which looks for ENUM kind: ``cannot cast `Right` to
  `UInt` `` inside a method, with the identical cast compiling in a free
  function. The binding now resolves either way; the write-back to `param.type`
  stays qualifier-only, which is what the original comment was protecting.
  Test: `backed_enum_extension_param.saw`. Found because the rights check is
  `entry.allows(Right.Debug)` — an enum parameter cast inside a method on the
  receiver, i.e. two of design 153's idioms at once.

**A safety finding that changed a brief item — worth the user's attention.**
The adoption list asked for `imgformat`'s `SegFlags` to become "a backed-enum
FIELD in the typed header view". It should not, and the measurement is short:

    a wire byte of 6 (W|X — a combination `has_sane_perms` rejects), overlaid
    through `UnsafeMemory` on a struct whose field is a backed enum, read back
    as the FIRST case and matched its arm silently.

`SosimgSeg` is overlaid on bytes the loader did NOT produce. An enum-typed field
mints an enum value straight from an attacker-chosen byte with no `from(raw:)`
between them, and a `match` on a value naming no case still selects an arm — so
the kernel would install a PMP region from a permission it never validated. The
bits became `SegFlag` and the mask field stayed a raw `UInt8`, with `has` /
`has_sane_perms` as the validating boundary.

The general rule this suggests, for the skill's wire-idiom section: **a backed
enum is safe as a wire-struct field only when the producer is trusted. Anything
PARSED keeps its raw integer field and exposes a `from(raw:)` accessor.** The
skill currently shows `flags: SegFlags` as the idiom with no such caveat.
Flagged rather than edited — the skill is another agent's surface tonight.

**What was adopted.**

- **145-C, the syscall ABI.** `sosabi`'s four families of parallel `static
  UInt`s became backed enums. `SysOp.from(raw:)` retired `OP_SYSTEM_MAX`: the
  range check and the decode are one step now, and the dispatch is an exhaustive
  `match`, so a new op fails to compile until handled. It is backed by `UInt`,
  the width of the register the op arrives in, because a7 is PROCESS-CONTROLLED
  — a narrower backing would need a truncation first, and `0x100` would arrive
  as a valid `DebugPrint`. Verified `from(raw: 0x10000)` is None.
  The status enum is backed `UInt8` (its tags cross the trap boundary; design 47
  pins the width) and gained `describe()` + `Printable` + `Error`, which retired
  the free `sys_error(status)` helper. Because conformances must live with the
  type (orphan rule), the enum MOVED from `sysapi` to `sosabi`, so both halves
  of the contract now compile from one declaration. A process still never
  imports `sosabi` — checked with a two-module probe that it can interpolate the
  error and match its cases through the value alone.
  `Right` and `ObjType` complete the set; the mask arithmetic moved into
  `HandleEntry.allows(Right)`, and `ROOT_SYSTEM_RIGHTS = 3 // DEBUG | SHUTDOWN`
  became `root_system_rights()` (a function, because a static initializer takes
  plain literals and a `3` with a comment naming its bits is the magic number
  the pass exists to remove). (`Right` became the per-kind `SystemRight`, and
  the check moved onto a validated-handle type, in the review round below.)
- **145-C, the image format.** `SEG_FLAG_*` became `SegFlag`, per the finding
  above. The hand-assembled test payloads (`sos/tests/payload_*.S`) keep their
  own `.equ SEG_FLAG_R, 1` and status literals, unchanged and on purpose: they
  exist to pin the format independently of the Saw definition, so that two
  producers agree with one loader. Renumbering `SegFlag` would need them edited
  too, and nothing enforces that — which is the price of the independent check,
  and was equally true when the Saw side was statics.
- **146, the toml API.** `TomlDoc.get_section` is gone (it handed back a
  non-retained alias — DF-132a), so `blade/src/sosimg.saw`'s `[sos]` reader
  searches once with `index_of` and reads through `section_at` windows, the
  shape `manifest.saw` already used. `band_level` became an extension method on
  `TomlSection` rather than a free function taking `&TomlSection` — a question
  about a section reads as one, and a method call is also the single expression
  a place window wants.
- **153, the kernel's own families.** `TrapCause` (nine `CAUSE_*` statics, and
  with them `cause_tag`'s nine-branch if-else — the hardware CAN raise a cause
  the kernel does not model, so `from(raw:)` names that miss and the rest is
  exhaustive), `PmpPerm` (the third bits/mask instance, spelled like `Right` and
  `SegFlag`), and `ExitCode`, which is now `fatal`'s parameter type instead of a
  bare `UInt` in the position the harness asserts on.
- **Stale prose.** `rt.c` has not existed since design 140's revision split it
  into `sos/hal/riscv32/kernel/sink.c` and `sos/rt/common_c/support.c`; five
  places still described an image as `boot.S` + `rt.c`, including the kernel
  entry header and the runner's pipeline listing.
- **A workaround main fixed.** `sos/rt/common` named its digit constants
  `HEX_ASCII_ZERO` etc. to dodge DF-140h (a private std static reserving its
  simple name program-wide). Design 145 unit A fixed that, so they are
  `ASCII_ZERO` / `ASCII_LOWER_A_MINUS_TEN` again.

**What design 149 had NO target for, and why — checked, not skipped.**

- **Zero regions.** Already right, and already at real size: the 64 KiB kernel
  stack and the 128-byte trap frame are `.bss` reservations in `boot.S`, which
  is where they belong. No Saw declaration wants to become one.
- **`SpinLock`.** Nowhere, as the brief predicted. rv32 M1 is single-hart AND
  the kernel holds no mutable global state in Saw at all — the handle "table" is
  a comparison against one constant, deliberately, until the object model. Not
  forced.
- **`unsafe static var`.** Same reason: there is no compound static using a
  workaround, because there is no compound static.

**The one real design-149 opportunity, NOT taken here — the top item for
review.** `sos/rt/common_c/support.c` gave three reasons it had to be C. One is
permanent: a Saw byte-copy loop is what LLVM's loop-idiom pass rewrites into a
call to `memcpy`, which in a freestanding build IS this memcpy, so mem* stays C
under `-fno-builtin`. The other two WERE DF-140g, which design 149 closed:

  1. the arena needed mutable module state and a `.bss` reservation —
     `unsafe static var` plus a zero-initialized `static ARENA: [UInt8; N] =
     [0; N]` (zerofill in both profiles) now express it;
  2. the seams needed to `@export` reserved `__saw_rt_*` names —
     `sawc --runtime-provider` (Blade: `[package] runtime = true`) now allows it
     from an ordinary freestanding build, with each signature checked against
     `sawc/rt/ABI.md`.

So the arena and the four seams COULD be Saw today, and SOS is precisely the
case design 149 was built for. Not done here because it changes the allocation
and panic paths of the kernel and every process image at once — a deliberate
decision, not an adoption sweep. The file's comment now says this instead of
citing the closed gap. Note the build-path split when scoping it: the ROOT
packages are Blade packages and would use the manifest key, while the kernel is
built by `tools/sos_runner.py` invoking sawc directly — but `--runtime-provider`
is a plain sawc flag, so the kernel needs no move to Blade to adopt it.

**Open questions for the user.**

1. **The runtime migration above** — worth its own brief, or fold into M1b?
2. **`Unknown` lost its payload.** (The type is `SosStatus` since the review
   round below.) The old enum had `Unknown(status: UInt)`, carrying the
   unrecognized number; a backed enum is payload-free, so `Unknown` is now a
   plain case (255 — not a value the kernel returns) where the userspace
   `from(raw:)` miss lands. In M1 it is unreachable (both halves compile from
   one table) and no caller printed the number, so nothing regressed today. If a
   diagnostic should carry the raw tag later, that wants a struct error or a
   companion field, not a backed enum.
3. **The wire-enum caveat** for the saw-lang skill (above).
4. **The status enum living in `sosabi`, a KERNEL-INTERNAL package**, is a
   slight tension with that package's "nothing else imports this, ever"
   charter. It is forced by the orphan rule and it costs userspace nothing
   (verified), but the module docstring's claim is now narrower than it reads.
   The review round below put `SystemHandle` there for the same reason — one
   declaration the dispatch and the wrappers share — so the tension is now
   structural rather than incidental, and worth a line in the charter if the
   package grows a third resident.

**A gate-coverage note worth keeping.** The `SegFlag` rename swept `sos/` and
`blade/src/` but missed `blade/tests/sosimg_wire.saw`, and NOTHING in the usual
loop noticed: `test_runner.py` does not compile `blade/tests/`, so the suite,
lexdiff, astdiff, irdet and sos-test were all green with blade's own suite
broken. The only gate that runs `blade test` is the bootstrap, which is why a
brief's final battery has to include it rather than treating it as optional.

It nearly escaped anyway, through a harness bug of mine rather than a repo one:
the first battery script piped each gate into `tail`, so `$?` was `tail`'s status
and every gate looked green. Rewritten to capture each gate's real exit code and
report a FAILED list. Worth stating because the same shape would hide any gate
failure, not just this one.

**Gate battery** (re-run strictly, against the final tree). Full compiler suite
1343 green (1341 at the branch point plus the two regression tests above);
lexdiff zero mismatches; astdiff clean over 1499 files; `irdet --all` byte-
identical over 883 examples; abidoc 53 seam signatures matching the frozen set;
blade bootstrap `BOOTSTRAP: ok` (stage0->stage2, 21/21 twice + the lib suites);
gmgate 12 programs x 10 runs, 0 failing; `make sos-test` 11/11 under QEMU.

## SOS M1 — the review round (Aug 7, branch RE-PARKED for user review)

**Branch: `worktree-agent-a6dd63281e227ac66`.** The adoption-pass branch rebased
onto main at 9cd0f8f (clean; two of its DF-fix commits were already upstream and
dropped as duplicates) and the FOUR review-round changes applied. All four were
**ratified by the user on Aug 7** and written into `sos/spec.md` (§3 and §5.7
item 7) before any code moved; this pass implements what those sections say.
SOS-review policy still applies: NOT integrated without explicit user sign-off.

**The four changes.**

1. **Typed handles.** `type SystemHandle = UInt` in `sosabi`, taken by the
   Saw-facing wrappers and by the kernel's op layer. The distinct alias gives
   the wanted asymmetry for free: it flows TO `UInt` implicitly, and a raw word
   or another kind's handle cannot flow in. Two sites cross INTO the type —
   userspace adopting its boot handle, and dispatch after the table resolved the
   handle — which is what makes it mean "validated as System". The typing stops
   at the ABI boundary: `@export`ed symbols and `sos_syscall1` keep raw words.
2. **`SysError` -> `SosStatus`.** A status with an `Ok` case is not an error, and
   the `Sos` prefix separates it from the hosted runtime's own frozen `SysError`
   (`sawc/rt/ABI.md`), which is untouched. Cases keep their values.
3. **Kind-scoped rights.** `Right` -> `SystemRight: UInt32`, and the check moved
   onto `SystemObject` — the pairing of a validated handle with its rights word
   — so `allows` takes a `SystemRight` and nothing else.
4. **The universal low byte.** Bits 0-7 identical in every kind's enum (0
   Transfer, 1 Manage, 2-7 reserved); kind rights from bit 8. `static_assert`s
   pin it against the enums themselves.

**The lowering, verified rather than assumed.** The brief asked for one checked
lowering; both halves were read out of `--emit-ir`:

- Userspace: `%boot_handle` reaches `sos_syscall1` as itself. No `zext`, no
  `trunc`, no `bitcast`, no temporary — the construction, the `System.handle`
  field and the flow back out to a `UInt` parameter all lower to nothing.
- Kernel: `SystemObject` never materializes (no alloca, no insertvalue), and the
  rights check against root's constant mask folds away entirely.

So tier one of the handle model costs zero instructions in both directions.

**Three compiler gaps, found by writing the ratified idioms and fixed here.**
Each has regression tests in `examples/`, and each BLOCKED a ratified change
rather than merely inconveniencing it — which is why the branch touches `sawc/`
at all. Filed as DF-140l/m/n below.

- **A backed enum's case was not a compile-time constant**, so change 4 could not
  be written: `static_assert((SystemRight.Transfer as UInt32) == 1, ...)` was
  rejected, and the only way to assert anything about a wire table was to
  transcribe its numbers into the assertion — which is what an assertion exists
  to make unnecessary.
- **Distinct aliases had no constructor**, so change 1 could not be written.
  `UserId(42)` — the form LANGUAGE_SPEC documents and the `42 as UserId`
  diagnostic points at — was `undefined function`. The only spelling that
  produced an alias value was an annotated `let`, which accepts an underlying of
  just the four primitive kinds, so `type SystemHandle = UInt` had no way to be
  given a value AT ALL.
- **Sibling aliases flowed into each other**, which would have made change 1
  cosmetic. `let order: OrderId = user` compiled, and so did passing a `UserId`
  where an `OrderId` was expected; only the sibling CAST was rejected. A typed
  handle is a safety property exactly to the extent that another kind's handle
  cannot land in it, so this was the one that mattered most.
  - A fourth, found while fixing the third: **an IMPORTED alias was not treated
    as an alias**, so it neither flowed nor constructed one module away from its
    declaration, while annotations using it checked fine.

**Two notes for the user.**

1. **LANGUAGE_SPEC's Type Definitions section described three things that did not
   work** — the constructor, the sibling rejection, and `Float64`, which is not a
   type this compiler has at all (only `Float`). The first two now work and the
   section was rewritten against tested snippets. `Float64` was left alone: `let
   x: Float64 = 100.0` fails on its own, independent of aliases, so whether the
   fix is a real `Float64` or a spec correction is a decision, not a bug fix.
2. **The universal table is asserted per kind, by repetition.** Each kind's enum
   repeats the same two `static_assert`s. That repetition IS the check — there is
   no way yet to state the table once and have a kind conform to it — so adding a
   kind means copying the block. Worth revisiting if kinds multiply faster than
   expected.

**One interpretation made, worth confirming.** Spec §3 illustrates the typed
handle as `sos_system_shutdown(h: SystemHandle, ...)`, but `sos_system_shutdown`
IS the `@export`ed symbol, and the same paragraph requires exported symbols and
the stubs to keep raw `UInt` words (a C caller sees words; the export whitelist
is primitives). Both cannot hold for one function. The exported C surface was
kept raw and the typed handle put on the `System` METHODS — the Saw-facing
wrapper a Saw process actually calls. The alternative reading, a typed Saw
`sos_system_*` layer beneath the export, would add a fourth altitude to the
three the module documents and explicitly disclaims ("no altitude reimplements
the one below it").

**Gate battery** (each gate's real exit code captured, per the adoption pass's
harness note). Full compiler suite **1373** green (1366 at the branch point plus
7 regression tests for the three gaps); lexdiff zero mismatches over 1530 files
(tokens and docs); astdiff clean over 1530 files; `irdet --all` byte-identical
over 903 examples (38 skipped); blade bootstrap `BOOTSTRAP: ok` (stage0->stage2
plus the lib suites); `make sos-test` 11/11 under QEMU; gmgate 20 programs x 10
runs, 0 failing.

## Design 162 — DF-findings (SOS M1b: arm64 EL1 parity + the HAL extraction)

The headline finding is a negative one and worth stating first: **sawc's
freestanding aarch64 codegen needed nothing.** The Saw half of the kernel
compiled for `aarch64-unknown-none-elf` on the first attempt and every later
failure was in code this branch wrote — assembly, page tables, a manifest. The
port hit ONE compiler-surface sharp edge (DF-162a), and it is not a miscompile.

- **DF-162a — FILED. sawc's freestanding aarch64 profile emits Advanced SIMD,
  and a bare-metal EL1 target traps it out of reset.** `CPACR_EL1.FPEN` is 0
  after reset, so the first compiler-vectorized loop takes an EC=0x07 trap —
  in SOS's case a page-table fill loop in the HAL's C, which faulted BEFORE the
  exception vectors it was being run to install could report anything. The
  generated code is correct for a target with FP enabled; the sharp edge is that
  a freestanding arm64 target does not have FP enabled until its boot code says
  so, and the failure mode is a silent triple-fault-shaped hang rather than a
  link error. Every arm64 freestanding user hits this exactly once, invisibly.
  Three ways out, and picking one is a decision this branch did not take:
  (a) document it in the freestanding profile notes — cheapest, and matches how
  the riscv32 `--target-features +a` requirement is handled;
  (b) make `--target-features -neon,-fp-armv8` work and verify the aarch64
  backend copes with a general-registers-only lowering;
  (c) nothing, since a kernel has to write `_start` anyway.
  SOS took the HAL route — `boot.S` enables FPEN before any compiled code runs —
  and states the consequence in `sos/hal/arm64/kernel/ABI.md`: FP state is NOT
  saved across a trap, which is sound with one user thread and no preemption and
  becomes M2's context-switch problem.

- **DF-162b — FIXED here (unit 1). The "arch-free" kernel was not arch-free.**
  M1's structure note claimed the architecture lived in `sos/hal/`; in fact
  `sos/kernel/core/lib.saw` held an NS16550A register block, a `mcause` enum,
  the PMP wrappers, `mepc + 4`, the SiFive finisher and the board's memory map.
  All of it moved behind a `hal` module. The fix that matters is not the move
  but the ENFORCEMENT: `tools/sos_runner.py` scans the arch-free kernel for
  architecture names, comments included, and fails the run on a hit. A leaked
  constant still COMPILES — it is only wrong on the profile nobody happened to
  be building — so a claim like this one has to be mechanical or it decays.

- **DF-162c — FIXED here (unit 3). `HEX_DIGITS_PER_WORD = 8` made every kernel
  address diagnostic print the low half of a 64-bit word** and look like a
  complete answer. It was written when riscv32 was the only profile. Now
  `hex_digits_per_word()` asks `sizeof<UInt>()`, which is the fact the constant
  was standing in for.

- **DF-162d — FIXED here (unit 3). The sosimg format had no arch tag**, so the
  two profiles' images were byte-compatible headers wrapping incompatible
  instructions and the only thing stopping one booting on the other was that
  nobody had tried. v2 spends the reserved byte on a `SosimgArch` tag; the
  kernel refuses a mismatch before copying anything, Blade writes it from the
  target triple (an unknown triple is a build error, never an untagged image),
  and both profiles have a test that feeds their kernel the other's tag.

- **DF-162e — FIXED here (unit 2). The loader never checked that a segment's
  load address was aligned to the target's grant granularity.** A grant covers
  whole units of it, so a segment starting mid-unit is granted along with
  whatever shares its first unit, at that segment's permissions. On Profile A
  the unit is four bytes and the question never arose; on a page-granular
  profile it is how root's code silently becomes writable because its data
  started 200 bytes later. The check is arch-free (`hal.PROT_GRAIN`) and refuses
  the image.

- **DF-162f — FIXED here (unit 3). Blade's sosimg emitter read ELF32 only**, so
  no 64-bit profile could produce a root image at all. It now takes the class
  from the header and looks its field offsets up (ELF64 widens `e_entry` and
  `e_phoff` and moves `p_flags` ahead of the offsets, so nothing is shared but
  the identification bytes). The 32-bit address fields stay 32-bit ON BOTH
  PROFILES by design — one format, one overlay, one byte count — and an address
  that does not fit is now a REFUSAL naming the 4 GiB bound rather than a
  truncation into an image that loads somewhere the linker never meant.

- **DF-162g — FIXED here. `sos/hal/riscv32/user/ABI.md` documented
  `sos_syscall1_value`, which does not exist** in `syscall.c` and never did. A
  seam document that lists a symbol nobody implemented is worse than a short
  one. The row now says what is true: no M1 op returns a value, and the twin
  belongs beside `sos_syscall1` the day one does.

- **VERIFIED, no gap: the design 148/149 toolkit works on aarch64
  freestanding**, which the brief asked for proof of rather than assumption.
  A `static COUNTERS: SpinLock<Int>` compiles (16 bytes of `.bss`) and lowers to
  inline exclusives with NO `__atomic_*` libcalls left undefined — the opposite
  of rv32i without `+a`, where naming a `SpinLock` is a compile error pointing
  at the flag. Const generics, `[0; N]` and `static_assert(sizeof<Ring<8>>() ==
  64)` all fold at the 64-bit width.

- **CORRECTION to the brief's decision 3.** It notes cortex-a53 as having "LSE
  atomics present". Cortex-A53 is ARMv8.0-A and has no LSE (that is ARMv8.1).
  Nothing was blocked: ARMv8.0 load/store exclusives cover everything the kernel
  and `SpinLock` need, which is what the verification above measured. Worth
  correcting so a later brief does not plan around an extension that is not
  there.

## Design 172 — DF-findings (the SOS C diet)

**The count, over both parts.** Raw lines move with the reason comments the
brief asks for, so CODE lines (non-blank, non-comment) are the honest number:

| file | M1b | after part 1 | after part 2 |
|---|---|---|---|
| `sos/hal/arm64/kernel/sink.c` | 170 | 47 | 47 |
| `sos/hal/riscv32/kernel/sink.c` | 75 | 22 | 22 |
| `sos/hal/arm64/user/syscall.c` | 32 | 32 | **11** |
| `sos/hal/riscv32/user/syscall.c` | 31 | 31 | **11** |
| `sos/rt/common_c/support.c` | 75 | 75 | **44** |
| **total** | **383** | **207** (-46%) | **135** (-65%) |

Part 1 took it out of the two kernel HALs, which is the shape the brief
predicted: the kernel side had arithmetic wearing C's clothes. Part 2 took the
rest — the arena and the four `__saw_rt_*` seams into `sosrt`, and the process
side's two hooks + parked handle into `sos/kernel/sysapi/` — leaving `mem*`,
the atomic libcalls and four inline-asm leaves. Units 1, 2, 3, 4, 6, 7 and 8
landed; unit 5 filed DF-172a. Every surviving line states its reason in its own
file, and sos/spec.md §5c states the three reasons there are.

- **REVIEW ROUND (user, Aug 8): the two kernel HALs no longer each carry the
  write loop or the abort-status rule.** Both had the same twelve lines — poll a
  status register, place a byte, advance a cursor with `&+`/`&-`, count down —
  and the same three-line "mask to a byte, promote zero" promotion. Only the two
  register touches actually differed, and they differ in POLARITY as well as
  shape: a 16550 is ready when LSR bit 5 is SET, a PL011 when FR bit 5 is CLEAR.
  That is a device difference and it is now the only thing a HAL states.

  `sosrt` gained `trait ConsoleSink { can_write, put }` with a default
  `write_byte` (the poll-and-place, since every polled transmitter waits the same
  way), `console_write<S: ConsoleSink>` — the panic path's loop, once — and
  `abort_status(code)`. Each HAL keeps a two-method conformance and its own
  machine-stop mechanism. The bound is STATIC, so the loop monomorphizes per
  architecture with no vtable, no existential and no indirect call on the panic
  path.

  **The DF-172b check-freedom proof was re-run on BOTH monomorphizations, and
  that was the condition for shipping this at all.** Generic-ness could have
  bought a hidden check or an outlined call, so it was measured rather than
  assumed: in each, the generic loop, the trait's DEFAULT body and both accessor
  bodies inline completely, leaving `ptrtoint`, a plain `load i8`, the device's
  volatile load, an `and`, an `icmp`, the volatile store and `add`/`add -1`. No
  `llvm.uadd.with.overflow`, no bounds check, no trap block, no call back into
  `__saw_rt_panic` — 32 IR lines on riscv32, 33 on arm64, both fully inlined.
  `panic_from_check` (the panic-in-panic pin) stays green on both machines.

  Worth recording as a language result, not just an SOS one: a trait with a
  default body, monomorphized through a static bound, cost NOTHING on a path
  whose whole contract is that it cannot trap. That is the property that makes
  `ConsoleSink` the right shape for a HAL seam rather than a nice abstraction to
  be paid for later.

- **DF-172i — a COVERAGE NOTE, not a bug, recorded because it is easy to lose.
  The kernel's `@export`ed typed C surface has no in-tree CALLER any more.**
  `sos_system_debug_print` / `sos_system_shutdown` (sos/kernel/sysapi/) are the
  supported interface for non-Saw processes, and the process-side runtime sinks
  were their only consumer — so when part 2 made those sinks Saw, the last C
  caller went with them. The surface is still specified, still linked (an
  `@export` is anchored by `llvm.used`), and its BODIES still run on every boot
  because the Saw sinks call the same two functions; what no longer happens on
  every boot is a C caller crossing INTO them, which is what
  `sos/root/src/main.saw` and the `root_server_boot` harness case used to claim
  they proved. Both comments now say what is true, and both user ABI.md files
  carry the note.

  Worth a decision when a second process exists: the honest way back is a real
  non-Saw process in the harness, not a C shim kept alive to be called. Adding
  C to the tree to test the C interface is how the diet unwinds itself.

- **DF-172f — FIXED (compiler, isolated commit). An array length that names a
  module `static` was an ICE in TYPE position and a clean error in REPEAT
  position.** `[UInt8; ARENA_BYTES]` reached codegen with an unresolved length
  and died as `internal compiler error: Array type missing element type or
  size`, while `[0; ARENA_BYTES]` said `repeat count is not a compile-time
  constant: `ARENA_BYTES` is not allowed here` with a hint naming the three
  legal forms. One rule, two spellings, and the ICE was the one an author hits
  first, since the annotation is written before the initializer. Design 148
  already named codegen as the position that owns a DECLARED length's
  requirement; it just raised the wrong kind of exception. It now re-runs
  `const_eval` to recover the offending sub-expression and reports a
  `CodegenUserError` with the repeat count's own wording.
  `examples/array_length_nonconst_error.saw` pins it.

- **DF-172g — FIXED (compiler, isolated commit). A static typed through a NAMED
  ARRAY ALIAS ICEd.** `type Region = [UInt8; 65536]` + `static ARENA: Region =
  [0; 65536]` died as `internal compiler error: 'NoneType' object has no
  attribute 'kind'`. `_get_llvm_type` follows an alias, so the LLVM type was
  right, but the STRUCTURAL reads in `_const_from_expr` (`array_element_type`,
  `struct_name`) come off the SawType and are None on an alias node — so the
  array arm recursed with no element type. Resolved once at the top of
  `_const_from_expr` with the existing total `_resolve_type_alias`.

  The spelling is worth having, which is why this was worth fixing rather than
  avoiding: it is how a large region gets ONE declaration of its size — the
  length lives in the alias, `sizeof` reads it back, and an initializer whose
  length disagrees is already a clean type error. The SOS arena uses it. NOT a
  bug, and the test says so: an alias is a DISTINCT type, so it does not
  inherit indexing (`ARENA[0]` is a clean "cannot index into type `Region`")
  and the way in is `(&var ARENA) as UnsafePointer<T>`.
  `examples/static_named_array_type_init.saw` pins it.

- **DF-172h — FIXED (compiler, isolated commit). An `extern` declared
  `-> Never` lowered to an i8 placeholder instead of `void`.** Design 58 says a
  `-> Never` signature is a `void` + `noreturn` symbol, and
  `_declare_function` does that for a DEFINITION; `_declare_extern_function`
  had no such arm and took `_get_llvm_type`'s i8 — the value that exists only
  so an incidental type query does not crash.

  It reached past the declaration, because an `@export`ed definition UNIFIES
  with a pre-existing bodyless declaration of the same symbol and inherits its
  type. So a `-> Never` seam DECLARED in one module and DEFINED in another came
  out as `define noundef i8 @sos_rt_abort(i32)` — exactly the SOS shape, where
  `sosrt` declares the abort hook and each side defines it. Written in an entry
  file with no extern beside it, the same function emitted `void`, which is why
  every design-177 example looked right. Harmless on the targets in tree
  (nothing reads a diverging function's return register; the harness was green
  either way) and wrong everywhere it is written down. The declaration now also
  carries `noreturn`, which it never did.
  `examples/never_extern_module_abi.saw` pins the arrangement; verified by
  reverting the fix (`i8` before, `void` after).

- **DF-172j — LANGUAGE PAIN, filed, NOT blocking. A repeat literal's count and
  an array length cannot name a module `static`,** so a region's size has no
  obvious single spelling. `static ARENA_BYTES: Int = 65536` is refused in both
  `[UInt8; ARENA_BYTES]` and `[0; ARENA_BYTES]` (the first was DF-172f's ICE,
  the second a clean error), and the workaround — writing 65536 twice — is a
  drift the compiler cannot catch on its own.

  The spelling that DOES work, and what this branch adopted, is a named array
  type: the length lives in `type ArenaRegion = [UInt8; 65536]`, `sizeof`
  reads it back for the bound, and the initializer's own length is checked
  against the alias. That is good enough that this is pain rather than a
  blocker. What would remove it is const-evaluating a `static` whose
  initializer is already a literal, which is a language decision (does a
  `static` become a const-expression name, and if so which ones) rather than a
  spelling fix — the same shape as C's `#define SOS_ARENA_BYTES` versus
  `static const`.

- **DF-172a — FILED, and it is the brief's predicted one. Saw cannot name an
  externally-defined symbol's ADDRESS**, so the four `sos_payload_start` /
  `sos_payload_end` accessors stay C. Three shapes were probed and all three
  fail, each for a different reason, which is what makes this a language gap
  rather than a spelling one:

  ```saw
  extern "C" { static _payload_start: UInt8 }   // parse error: "Expected 'func'
                                                //   in extern block"
  extern "C" { func _payload_start() }
  let p = _payload_start                        // error: undefined variable
                                                //   (an extern func is not a value)
  @export("_payload_start")
  static PAYLOAD_START: UInt8 = 0u8             // compiles — and `nm` shows
                                                //   `B _payload_start`: a
                                                //   DEFINITION, which collides
                                                //   with the linker script's
  ```

  The DF-163f-blessed `(&sym) as UnsafePointer<T>` needs a `sym` that is a Saw
  binding; a linker symbol is not one. What the language is missing is an
  `extern` DATA declaration — "this name exists, the linker will place it, its
  address is what I want" — which is `extern char _end[]` in C and
  `extern "C" { static _end: u8 }` in Rust. Two shapes worth weighing when it
  is designed: whether it declares a TYPE at all (the C idiom uses an
  unsized array precisely so nobody reads through it), and whether taking the
  address is the only legal operation.

  There is a NON-language alternative that would delete these four functions
  today, and it is an open question for the user rather than a finding: the
  bounds could be passed INTO `kmain` from `boot.S` (`ldr x0, =_payload_start`),
  which names the symbol in assembly — already bucket 1 — and hands Saw a word.
  It costs every kernel entry a parameter and moves the payload from something
  the HAL is asked for to something the kernel is handed, so it is a seam
  change, not a cleanup.

- **DF-172b — NOT a gap: the panic-path writer is check-free by construction,
  verified from emitted IR.** Design 172 unit 4 says the UART writer STOPS
  rather than ships best-effort if check-freedom cannot be guaranteed. It can.
  `--emit-ir` on the whole call cone (`sos_rt_write` -> `console_byte` ->
  the design-112 driver) shows `ptrtoint`, a plain `load i8`, `add`/`sub` —
  NOT `llvm.uadd.with.overflow`, because the cursor advances with `&+`/`&-` —
  an `icmp`, a `getelementptr inbounds`, and volatile MMIO load/store. There is
  no bounds check, no overflow trap block and no call to `__saw_rt_panic`
  anywhere in it, so a panic raised inside the panic reporter is not merely
  unlikely, it is unreachable. The ingredients that make that true are the
  design-130 raw pointer surface, `&+`/`&-`, and the design-112 `UnsafeMemory`
  driver idiom — no new language work was needed.

- **DF-172e — CLOSED (design 177), and SPENT: part 2 landed on Aug 7.** Saw
  types a diverging loop as `Never`, so unit 2 (the arena + the four seams in
  Saw) went in exactly as the stopped unit had been probed, and the process
  side's hooks — blocked on the same signature — went with it. The predictions
  in the original finding below all held: the arena was expressible,
  `--runtime-provider` permitted and checked the exports, and `sosrt` was the
  module both roles already shared. The second cost it named is paid too —
  `sos_rt_abort` is `-> Never` on both sides now, so
  `__attribute__((noreturn))` is a type rather than a comment. The finding's own
  smallest-first
  suggestion is what landed: a conditionless `while { }` with no `break` types
  `Never`, and `while true { }` is excluded (see the decision entry in the Aug 7
  round). `func spin_forever() -> Never { while { } }` compiles freestanding to
  a `void` + `noreturn` symbol whose body is a bare back-edge —
  `examples/while_never_freestanding.saw` pins the shape. The second cost this
  entry names is paid too: a "this stops the machine" helper (`kcore`'s
  `fatal_image`, `grant_outside_window`) can be declared `-> Never`, which makes
  the guard self-documenting and lets the compiler drop the unreachable tail.
  Nothing else about unit 2 changed, so it resumes where it stopped. **Original
  finding follows.**

- **DF-172e — FILED, and it is what STOPPED unit 2 (the arena). Saw cannot
  type a diverging loop as `Never`**, so a freestanding runtime cannot write
  the `noreturn` panic seam the ABI requires.

  Everything else about unit 2 checks out, and was measured rather than
  assumed. A probe compiled clean under
  `--freestanding --no-hidden-alloc --runtime-provider`, and `nm` showed
  exactly the structure `support.c` has today — the four seams DEFINED, the two
  per-side hooks UNDEFINED:

  ```
  00000000 T __saw_rt_alloc      U sos_rt_abort
  00000000 T __saw_rt_dealloc    U sos_rt_write
  00000000 T __saw_rt_panic
  00000000 T __saw_rt_write
  ```

  The bump arena IS expressible (design 149's `unsafe static var` + a zero
  static + `(&var ARENA) as UnsafePointer<UInt8>`), an `extern "C"`
  declaration in one Saw module unifies with an `@export` definition in
  another, and `sosrt` is already a dependency of both the kernel and every
  process, so it is the module they would share. What fails is one signature:

  ```
  error: `@export` seam `__saw_rt_panic` does not match the runtime ABI:
         it returns `void` where the ABI returns `noreturn`
  ```

  — which is design 149's ABI check doing exactly its job. Meeting it needs a
  `-> Never` body, and the only two things in Saw that produce `Never` are
  `panic()` (which is what this seam IS, so it cannot call it) and an `extern`
  declared `-> Never`. A diverging loop is not one:

  ```saw
  func spin_forever() -> Never { while true { } }
  // error: function `spin_forever` should return `NEVER` but body has no value
  ```

  Profile B could scrape through, because its `sos_platform_exit` is still C
  (semihosting `hlt`) and can be declared `-> Never`. Profile A cannot: after
  unit 4 the finisher write is an ordinary Saw MMIO store and there is no C
  leaf left to lean on. Adding one back to buy a type would be the diet in
  reverse.

  **The decision this branch took: do NOT split the seam family.** Moving three
  of four seams to Saw and leaving `__saw_rt_panic` in C would thread
  `--runtime-provider` through the harness and two manifests, change the
  allocation and panic paths of the kernel and every process image at once, and
  leave `support.c` with a story that is HARDER to state than the one it has.
  `support.c`'s own header already says this move should be taken deliberately
  rather than as part of an adoption sweep, and a language gap in the middle of
  it is the strongest possible argument for that.

  **It costs something ELSE, visible in this branch's own code.** Because no
  Saw function can say "I stop the machine", every diverging helper is typed
  `Void` and the compiler believes control returns from it. So a bounds check
  written as

  ```saw
  if va < RAM_BASE {
      grant_outside_window(va)      // never returns — but the type says Void
  }
  let page = (va - RAM_BASE) >> PAGE_SHIFT
  ```

  reads to the checker as a path where the subtraction runs below `RAM_BASE`
  and traps. It is correct at run time and the harness proves it, but the
  guard's whole point is unstateable, and the same shape is already in
  `kcore`'s `fatal_image`. A `Never` return would make these guards
  self-documenting AND let the compiler drop the unreachable tail.

  What would unblock it, smallest first: an `extern` return type of `Never` is
  already accepted, so the narrow fix is making a loop with no `break` type as
  `Never` — the rule Rust has for `loop {}`. That is a typechecker change to
  the tail-expression rule for an infinite `while`, and it would also let any
  "this function stops the machine" signature say so, which is a thing a kernel
  wants to write more than once.

- **DF-172d — LANGUAGE PAIN, filed. A binary expression cannot be wrapped
  across lines outside brackets — NEITHER spelling works.** Design 129 made
  newlines insignificant inside `()`/`[]`/committed `<>`, but a bare
  continuation is still a statement end, so both of the two things a
  programmer reaches for are parse errors:

  ```saw
  let d = base | DESC_VALID | DESC_PAGE
        | ATTR_AF | ATTR_UXN            // error: Unexpected token: PIPE
  let d = base | DESC_VALID | DESC_PAGE |
          ATTR_AF | ATTR_UXN            // error: Unexpected token: NEWLINE
  ```

  The working spelling is a pair of parentheses around the whole expression,
  which is the shape this branch adopted:

  ```saw
  let d = (base | DESC_VALID | DESC_PAGE
           | ATTR_AF | ATTR_UXN)
  ```

  This is not a corner: OR-ing eight named bits into a hardware descriptor is
  the single most common line in a page-table or register driver, and it does
  not fit in 79 columns. The parenthesis is a workaround a reader has to
  decode as "line continuation" rather than as grouping, and forgetting it
  gives an error that names a token rather than the rule. Worth a decision:
  a trailing binary operator suppressing the newline is the low-risk half
  (the parser has already committed to needing an operand), a leading one
  needs lookahead. Neither is in this brief's scope.

- **DF-172c — the arm64 HAL keeps `CPACR_EL1.FPEN`, and the brief's line about
  dropping it is vacuous as written.** Two facts: the arm64 harness entry
  passed no `--target-features` to begin with (`"features": None`), so there
  were no explicit flags to drop; and `sos/rt/common_c/support.c` — whose
  `memcpy`/`memset` are PERMANENTLY C, being the loop-idiom self-recursion case
  — compiles to 16 SIMD references at `-O2` and is linked into the kernel and
  every process image. Turning FPEN off would trap in `memcpy`. So the boot
  line stays, now with that as its stated reason. Removing it needs
  `-mgeneral-regs-only` on every aarch64 C compile, which means a Blade
  manifest key for per-target C flags (Blade's native compile hardcodes its
  flag list today). Small, additive, and NOT part of this brief.

## Executor — open items

- **EXEC-1 — VERIFY (flagged during the ST lost-wakeup fix, Aug 4, lead).**
  Cross-poller one-shot consumption beyond the fixed case: every poller of the
  process-global reactor (an MT group's workers; a 21b `spawn {}` OS thread
  whose body runs its own cooperative io; the ambient ST sweep) can consume +
  latch a one-shot event belonging to a frame parked by a DIFFERENT poller's
  scheduler. The ST sweep now recovers via its pre-poll latched scan
  (`__saw_exec_any_latched_io`), but only for latches that land while it is
  scanning — a latch that fires while the sweep is already blocked in
  `poll(-1)` (only possible if another OS thread polls concurrently) would
  still wedge it: the event is consumed, the sweep's poll never returns, the
  latch is never read. The MT worker is bounded (50 ms) so it always re-scans;
  the ST sweep is not. NEEDS A PROBE to establish whether the window is
  reachable today (is a concurrent poll possible while the main thread is in
  the ST sweep's poll? MT drains block the main thread; a 21b OS-thread task
  doing reactor io concurrently with main-thread ST io looks like the
  candidate). If reachable: either bound the ST sweep's poll like the MT
  worker's, or self-wake the reactor whenever a poller latches a token it does
  not own. [design 91 / 102 / 118]

## Design 126 — findings (pre-port AST contract)

- **DF-126a — RC-2 is LATENT, not a live bug (measured, Aug 4).** The pre-port
  review called the un-substituted grafted annotations "a live bug, not just a
  port hazard": `substitute_ast_types` walks `dataclasses.fields()`, so while
  `resolved_type` and the ~50 other annotations were grafted at runtime, the
  monomorphizer could not see them, and every `SawType`-valued one was carried
  into an instantiation stale. R1 declares them, so the substituter sees them —
  but the claimed miscompile could not be reproduced. Repro method (kept here
  because it is the way to re-test this cheaply): make the loop at
  `typechecker/effects.py:51` skip `resolved_type` and every field whose
  metadata carries `saw_annotation`, i.e. reproduce exactly what the grafts hid,
  then run the suite. Result: **1034/1034 pass**, including
  `examples/coro_generic_mono_type_subst.saw`, which was written specifically to
  exercise the path (a driven generic-struct method at three instantiations,
  with a `match` over a `T`-parameterized enum and a `Vector<T>` literal live
  across the suspension). So the corpus cannot currently reach a shape where the
  stale annotation changes the emitted code. WANTED: either a shape that does
  distinguish (then it becomes a real regression test), or acceptance that R1's
  value here is contract correctness for the port rather than a bug fix. Do NOT
  describe RC-2 as a fixed miscompile without such a shape.

- **DF-126b — reproducible builds were broken; two causes fixed, no guard yet
  (Aug 4).** Compiling one unchanged source twice produced different IR
  (`examples/hello.saw` differed by thousands of lines). Causes: a `set` of type
  names seeding the codegen topological sort, and a `set` of capture names
  fixing closure environment field order. Both fixed under design 126 R2, and
  `make irdet` now guards a corpus sample. Note the general hazard remains
  unpoliced: any future `set`-of-`str` iteration that reaches emission order
  reintroduces this class silently, because Python randomizes string hashing per
  process and a single run always looks self-consistent.

  **The warning came true — TWO MORE INSTANCES, both in the coroutine transform,
  both FIXED (design 141, Aug 5).** Found by accident, which is the point:
  `tools/irdet.py` samples 40 examples via `random.sample` over the tracked file
  LIST, so simply ADDING two unrelated examples reshuffled the sample and pulled
  in a file that had been non-reproducible all along. Both causes are
  `set`-of-`str` iteration reaching emission order in `coro_transform.py`:
  (a) `promoted` — the set of promoted generic instantiations — was iterated
  into the work list at `transform_program`, which orders `closure`, which
  orders `fbs`, which orders the emitted frame structs and resume methods
  (`examples/coro_nested_generic_deep.saw`); (b) `modes` — the drive modes
  recorded per root by `_effect_record_driven`, a `set` — was iterated when
  emitting the `__saw_drive_*` / `__saw_drive_steps_*` wrappers, at three sites
  (`examples/coro_tuple_across_suspend.saw`). Both now sort. Verified with
  `irdet --all` rather than the 40-file sample.

  **GATE STRENGTHENED (design 146 unit D, Aug 5).** `make irdet` keeps the
  40-file sample as the cheap per-commit check; `make irdet-all` sweeps the
  whole corpus and is now the documented standard for a brief's FINAL gate
  battery (CLAUDE.md's testing section says so). Measured cost of the full
  sweep: **728 examples compiled twice under differing PYTHONHASHSEED, 102
  skipped (they need module paths or a host), 1128.6s of tool time / 18m49s
  wall** on the dev Mac. That is affordable once per brief and not once per
  commit, which is exactly the split. Still open as a cheaper guard: a static
  check for `set`-of-`str` iteration that reaches an emission list — the sweep
  catches instances, not the class.

## Milestones
- **App-1 Blade: DONE** (design 64 + 67; real resolver/lock/git/
  incremental/self-hosting bootstrap; `make blade-bootstrap`).
- **App-2 SOS kernel (ESP32-P4, riscv32): IN PROGRESS.** M0 DONE (design
  112): Saw kernel boots + prints a UART banner + exits cleanly under
  QEMU `virt` riscv32 (`make sos-test`). M1 BUILT (design 140), branch
  PARKED for user review: trap entry + M/U split + PMP, the two-syscall
  ecall ABI (§5.7), the sosimg format with a Blade `emit = "sosimg"`
  target, and `sos/root/` as a real separate package that banners through
  the syscall and exits 0 — 11 QEMU cases. NEXT: M1b arm64 EL1 parity +
  HAL extraction, BEFORE the object model. Ultimate milestone: UART
  "blink" on real P4 hardware. See sos/spec.md §11 + designs/112, /140.
- **Docs website (sawlang.com): VISION (user, Aug 4) — "eventually", not
  scheduled.** A complete site: installation, usage/tutorial, stdlib API
  reference extracted from source. Component (1) doc comments and (2)
  `--emit-docs` are **DONE** (design 121, Aug 4): `///`/`//!` are lexed as
  trivia in both lexers under the lexdiff parity contract, the parser attaches
  them, and `sawc <entry> --emit-docs` writes the typechecked surface as JSON
  (signatures, conformances, suspending-vs-sync effect, self ownership;
  design-80 gate on members). The pipeline is proven end to end on std.task +
  std.time. Remaining component designs to brief when scheduled:
  (3) `sawdoc` — the JSON→HTML generator WRITTEN IN SAW (surface-area strategy:
  markdown/string/file-IO heavy dogfood); (4) the std docstring pass across the
  rest of std (per-module content work, agent-friendly, follow the saw-docs
  skill); (5) site shell + hosting (static; README "Building from a fresh
  clone" section is the near-term precursor). Open questions for (3)/(4):
  Markdown validation and doc-example testing (`sawdoc test`?), and whether
  blade/libs sources join the documented set. [website]

## Queued briefs (Aug 4) — awaiting dispatch

Closed items: see todo_aug1-aug9.md.

- **PARSER-PORT INTEGRATION STRATEGY (user, Aug 7 — fold into the parser-port
  brief when the rewrite track resumes): a LANGUAGE-NEUTRAL BINARY AST FORMAT
  as the frontend/backend seam.** The format is now DECIDED-BY-BRIEF: design
  169 (Serialize/Deserialize traits + std.cbor, RFC 8949 deterministic
  profile — a standard with an existing Python impl instead of a bespoke
  notation, user Aug 7); the AST envelope (node-id high-water mark etc.)
  layers over it in the parser-port brief. 169 queues post-168 integration,
  before the parser port. The Saw-written lexer+parser emits the
  binary AST per module; the Python typechecker+codegen+LLVM backend consumes
  it — the Saw frontend drives real builds EARLY while the Python parser stays
  the oracle. Cut point is PARSE (the only clean seam: the 164 audit proved the
  parsed AST interchange-safe — 44k objects, ast_dump round-trip byte-identical;
  everything post-typecheck has SawType-aliasing hazards). Staging: (1) format
  spec + Python writer/reader, whole-corpus ast_dump round-trip gate; (2) Saw
  parser emits it, astdiff Saw-parse-vs-Python-parse gate; (3) the flip, Python
  parser kept behind a flag as the permanent battery oracle. Pins: single-source
  the serde on both sides from one schema (design-126 AST contract); the header
  CARRIES the node-id high-water mark and the consumer seeds its counter past it
  (the 164 gate's miscompile lesson); this format is the SEAM, not the Python-
  side perf cache — 168's tier-B pickle stays the Python speed answer; the
  format later doubles as the self-hosted compiler's own AST cache (no pickle
  in Saw).
- **Design 116 — self-hosting pilot: the lexer in Saw (dispatched Aug 4).**
  First permanent stage1 module + rewrite-decision instrument: `selfhost/lexer`
  Blade package mirroring sawc/lexer.py's token model, canonical token-dump
  format, `tools/dump_tokens.py` + `tools/lexdiff.py` differential harness over
  the WHOLE .saw corpus (zero mismatches = bar), LOC/perf metrics, DF-116
  findings as the explicit product. Full rewrite DEFERRED (user, Aug 4) until
  design churn slows; surface-area growth is the chosen mechanism. [116]
- **Design 117 — runtime ABI v2 minimization. LANDED (Aug 4).** Errno
  accessors DELETED; the reactor is INSTANCE-based and relocated to Saw
  (DF-113d dissolved); the thread surface is spawn/join. Per-unit commits:
  thread_spawn/join; instance reactor (rt/host_*/reactor.saw kqueue/epoll,
  compiler `__saw_reactor` singleton getter injected at seam call sites);
  errno→SysError (net, then file/dir/env). Full suite 998 + bootstrap + sos
  green each. `sawc/rt/ABI.md` rewritten as v2 (minimization principle,
  SysError tag table, instance-reactor contract, v1→v2 deprecation table).
  - **DF-117a — DECIDED (user, Aug 7): `if let` block termination matches
    plain `if` (a newline after the closing `}` ends the statement;
    `(if let {...}) - x` needs parens), the NoneType ICE becomes a real
    diagnostic regardless, and the net.saw/os_ops.saw `return 0 - X`
    workarounds revert to the wanted spelling. Queued in the
    soundness/semantics batch. Original finding:** A function whose body is `if let x = y { … }` immediately
    followed by a line beginning with a unary minus, e.g.
    `func f() -> Int { if let p = alloc() { … return r }\n    -SOME_CONST }`,
    parses the trailing `-SOME_CONST` as `(if let {…}) - SOME_CONST` and ICEs
    (`'NoneType' has no attribute 'type'` in operators.py — the if-let value is
    None). A plain `if {}` block does NOT absorb it (the newline terminates),
    so it is an if-let-specific inconsistency in block-expression statement
    termination. Wanted code: `… }\n    -SYS_OTHER` as the fallback value.
    Worked around cleanly with an explicit `return 0 - SYS_OTHER` (net.saw
    net_read_once; os_ops.saw trailing tags). Recorded per the do-not-work-
    around policy: the fix is a parser change to block-terminated-statement
    handling; deferred as out-of-proportion + genuinely ambiguous (blocks are
    expressions, so `block - x` is arguably valid) — flagged for a lead call.
  [117]
- **Design 113 — runtime extraction. IN PROGRESS (Aug 4).**
  - **Physical relocation: LANDED via design 113b (Aug 4).** The `saw_*` export
    reservation was loosened under `--runtime-build` and the seam bodies moved
    to `sawc/rt/` (Saw) + `shim.c` (the DF-113a/b/c bodies) — all seams except
    the IO reactor (DF-113d, see the 113b entry below). See designs/113b-rt-in-
    saw.md. DF-findings stay open as language gaps:
    - **DF-113a — no extern C global.** `__saw_rt_write`/`_panic` need the libc
      `stdout` FILE* (`__stdoutp` macOS / `stdout` Linux) for the `fwrite +
      fflush` that keeps `print` ordered against the still-`printf` Float path.
      Saw has no `extern static` / extern-global syntax, so the body can't be
      Saw. (Switching to `write(2)` would reorder against buffered float text —
      not byte-identical.)
    - **DF-113b — no C function-pointer type.** `__saw_rt_pthread_create` and
      the offload thunk (`word(word)`) pass a raw C function pointer to
      `pthread_create`. Saw's surface has no bare C function-pointer type
      (closures are fat pointers), so threads + offload can't be Saw bodies.
    - **DF-113c — no variadic extern.** `__saw_rt_set_nonblocking` must call
      `fcntl(fd, F_SETFL, ...)`, which is variadic in C (an arm64 ABI
      requirement — a fixed-arity decl reads the flag off the stack). Saw
      extern decls have no `...`, so the reactor's nonblocking-socket path
      can't be a pure-Saw body.
    - **Expressible in Saw today** (for the eventual relocation): alloc/dealloc
      (malloc/free), sleep_ms (usleep), the clocks (clock_gettime + a Saw
      timespec struct), the errno family (extern `__error`/`__errno_location`
      returning `UnsafePointer<Int32>` + `unsafe` deref), sin_set_family (byte
      stores), op-budget + reactor init CAS (`Atomic<Int>.compare_exchange` —
      seq_cst, i.e. stronger ordering than the synthesized monotonic; observably
      equivalent), and the kevent/epoll structs (Saw structs, natural ABI). The
      reactor's `set_nonblocking` dependency (DF-113c) is the only gap in an
      otherwise-Saw reactor.
    - Remaining scope when unblocked: build/cache/link machinery
      (`.build/rt/`, keyed on source hash, auto-linked for hosted builds, `-v`
      shows the objects, clear error if the rt fails to build); delete the IR
      synthesis; the negative test (freestanding still externs, no runtime
      auto-linked — needs a test-harness symbol-inspection directive, which
      doesn't exist yet, and only bites once hosted auto-links); `sawc/rt/`
      module-dir layout selected by target triple. [113]
- **Future designs — language gaps blocking a pure-Saw runtime** (each removes a
  113b shim body or unblocks the reactor when it lands): (1) extern C globals
  (`extern static stdout: ...`) — DF-113a, shrinks shim.c; (2) a bare C
  function-pointer type (closures are fat pointers; thread_spawn/offload thunk
  need thin ones) — DF-113b; (3) variadic extern declarations (fcntl-class arm64
  ABI requirement) — DF-113c. (DF-113d — the array-repeat/uninitialized-local
  poll-buffer gap — is no longer load-bearing: design 117 dissolved it with the
  instance reactor's per-call heap buffer; the language nicety is optional now.)
  General C-interop / low-level value beyond the runtime. [113/113b/117]
- **Design 114 — intrinsic scoping + naming. Part A LANDED (Aug 4); Part B
  LANDED (Aug 4); io_wait gating DEFERRED (see FLAG).**
  - **FLAG — DECIDED (user, Aug 7): io_wait stays UNGATED for now; the real
    gating FOLDS INTO DESIGN 118 (the executor-in-Saw relocation redraws
    this exact seam behind a Reactor trait, and the 11 white-box tests are
    rebuilt against that boundary — deleting reactor-level coverage to
    enforce a gate 118 will redraw would pay twice). No action until 118
    dispatches; its brief inherits this. Original flag:** The brief's Aug-4 audit stated io_wait is "used by std.net"
    (internal only) and budgeted NO io_wait migration. FALSE: **11 example
    programs call `io_wait(...)` directly** — white-box reactor tests that
    drive the FULL raw private seam (`tcp_socketpair`/`tcp_try_read`/
    `tcp_try_write`/`net_buffer`/`net_would_block`/`io_wait`) with controlled
    socketpairs to exercise park/precise-wakeup/cancel/deinit-across-parks at
    the reactor level: `net_io_main_entry`, `net_threads_io`,
    `net_loopback_echo`, `net_socketpair_echo`, `net_io_sleep_interleave`,
    `net_deinit_across_parks`, `net_nested_parks_roundtrip`, `net_io_cancel`,
    `net_precise_wakeup`, `net_precise_n_readers`, `net_three_park_sequence`,
    `net_cancel_parked_mt`. Gating io_wait to std bodies would break all of
    them; there is no public-API equivalent that still tests io_wait itself
    (the public TcpStream examples exercise the seam only indirectly). So
    honoring "io_wait outside std errors" requires a COVERAGE decision the
    brief did not authorize: either DELETE these 11 white-box reactor tests
    (relying on the public-API net tests for regression coverage) or KEEP
    io_wait ungated. Left io_wait exactly as-is (ungated) pending that
    decision; the yield_now gate is independent and complete.

## Design 120 — suspension in expression position (LANDED, Aug 4)

Closed items: see todo_aug1-aug9.md.

- **CARVE-OUT (recorded): multi-hop chained assignment with a suspending RHS.**
  `a?.b?.c = stream.read()` still rejects cleanly; the single-hop
  `a?.c = stream.read()` works. The lowering is a None-guarded
  read-modify-writeback of ONE payload (`var __wp = a!; __wp.c = rhs; a = __wp`);
  more than one hop needs the writeback nested per level. Wanted spelling: the
  multi-hop form lowering the same way. Workaround: `if let` the inner optional
  first. [120, 111]
- **FLAG (minor): a NoCopy payload under a suspending chained assignment
  reports at 0:0.** `var local: NC? = …; local?.x = s(7)` inside a driven
  function is a clean error (`cannot copy value of type ... which implements
  NoCopy`) — the lowering's `local!` read duplicates the payload — but the
  diagnostic carries no source position. The sync form compiles, so the shape is
  legal outside a coroutine. A guard in `_lower_optchain_assign` cannot fix it:
  the transform's typechecker handle has not merged the entry module's namespace
  yet, so `_is_no_copy_type` answers False there. Cosmetic; the program is
  rejected either way. [120, 111]

## Doc-sync audit findings (Aug 3) — two DECIDE items

Closed items: see todo_aug1-aug9.md.

Surfaced by the four-source consistency audit (README / spec / skill /
CLAUDE.md digest vs code); docs were updated to match the implementation,
these two need a design call:
- **DECIDE: method call on an integer literal.** `7.doubled()` is a parse
  error — the lexer consumes `7.` as a float-literal prefix; `(7).doubled()`
  and a bound name work. `Int(7).doubled()` does NOT work (probe Aug 3:
  "struct initialization requires named arguments" — constructor-call syntax
  is structs + distinct aliases only). Decide whether INT `.` IDENT should lex
  as a method call, or whether `(7).method()` is the blessed spelling
  (README's Type Extensions example now uses a binding meanwhile). [57]
  **PUNTED (user, Aug 4):** stays an error for now; `(7).method()` is the
  workaround spelling. Revisit on demand.
- **VERIFY (agent claim, Aug 3): two-suspend helper embedding failure.** The
  design-110 agent reported that a non-driven helper with TWO suspend points
  ("plain `yield_now(); print; yield_now()`, no references") fails to embed
  under a driven body with the nested/expression-position error. NOT reproduced
  by the lead: statement-position `let a = helper()` with two suspends compiles
  AND runs at depth 1 and depth 2 (probes `.build/scratch/probe_two_suspends*.
  saw`, Aug 3). The failing shape, if real, is more specific — extract the
  exact repro from the agent transcript before treating as work. [104, 96]
  **Deferred (user, Aug 4):** revisit only if it reproduces during the SOS
  work (design 112 onward flags suspending-shape oddities on discovery).

## Design 104 — coro embedding: if-let/guard-let bodies + remaining generic shapes (IN PROGRESS)

Closed items: see todo_aug1-aug9.md.

- **Item 2 (cross-module generic driven templates, design-74 shape 4) — ALREADY
  WORKS; regression test added.** The brief's premise (the `_pristine_` capture is
  module-local) is STALE: all modules in one compilation unit are checked by ONE
  shared typechecker (sawc.py's per-module loop in dependency order), so
  `_pristine_generics` / `_pristine_generic_struct_methods` accumulate templates from
  EVERY module (in-tree and `--module-path`). `_splice_fn_mono` /
  `_build_generic_struct_method_mono` therefore find a template regardless of its
  defining module. VERIFIED by probes + the new test `coro_cross_module_generic`
  (module `modules/coro_provider.saw` defines a generic suspending free fn
  `amplify<T: Seed>` + a generic struct `Cell<T: Seed>` with a suspending `charge`;
  entry drives `amplify` NESTED at two types → 211 and `Cell.charge` directly at two
  types → 207/208; IR: distinct `Frame_amplify$1$Lo/$Hi` + `Frame_Cell_charge$1$*`,
  zero plain calls). The stale `_promote_nested_generic_calls` comment ("cross-module
  = shape 4 → reject") corrected. Docs: spec + skill shape-4 now supported.
  **FLAG (discovered, orthogonal — NOT fixed):** a NESTED generic call whose template
  suspends UNCONDITIONALLY without calling a type-param method (`func g<T>(x: T) -> T
  { yield_now(); x }` called nested) fails SAME-MODULE too — the template is not
  `poly_candidate`, so `_process_effect_monos` never builds its instantiation's
  suspend node, so `_promote_nested_generic_calls` can't promote it and it lowers as
  a plain call → a clean (not silent) sync-violation error on the synthesized resume.
  Precise blocker: build a generic instantiation's effect node when the TEMPLATE
  structurally suspends (a direct `__suspend`/`yield_now`/`sleep`, not gated on a
  type-param method), not only when `poly_candidate`. Workaround: drive it directly
  (`__drive`/`spawn`), or give the template a type-param method call. Suite 941 (+1),
  bootstrap 17+17 + libs 4+4. [104, 74, 70, 96]

## Design 89-b — executor unification core (WORKTREE, IN PROGRESS)

Closed items: see todo_aug1-aug9.md.

- **Test matrix — LANDED (worktree).** Three NEW tests for behavior the old split
  executors could not produce (suite 888->891): `net_accept_loop_concurrent`
  (ACCEPTANCE — a server task accept-loops N=3, SPAWNING a handler per connection
  into its OWN group that runs eagerly on the shared scheduler while the server
  parks, + 3 concurrent client tasks; round-trips all N, deterministic 3/3);
  `taskgroup_spawn_and_loop` (the core gap — main parks in a sleep-loop while its
  spawned child INTERLEAVES `0,100,101,1,102,2,7`, not the old
  `0,1,2,100,101,102,7`); `taskgroup_nested_ambient` (nested groups + a task
  joining its own inner children = the reentrancy hazard, cross-group eager
  interleave). Existing coverage survives and validates the rest under the ambient
  scheduler: `taskgroup_sleep_ordering`/`structured_join`/`unjoined_drop`/
  `two_task_yield`/`cancel_check`, `net_io_sleep_interleave`, `net_serve_two/three_
  connections`. Updated the now-stale per-group-executor comments in
  `taskgroup_nested_groups` + `taskgroup_suspending_parent_sleep` (results kept).
  **DF finding (pre-existing, reproduces on parent):** spawning a function whose
  param transitively references a std struct (e.g. `f(h: TaskHandle<Int>)`) ICEs
  "Undefined struct: TaskGroup" during frame layout — unrelated to executor
  unification; reentrancy is instead tested via nested-group joins. [89, 52b, 76]

## Decisions needed (user input required)
- **D10.** Cortex-M0-class atomics (ARMv6-M has no CAS) — decide with
  the first such port. [19, 20]
- **SOS**: design session Aug 3 ratified spec §7–§10 — scheduling
  (8 levels, band enum + immutable manifest-declared launcher-approved
  map, LAUNCH capability, no inheritance, direct-switch, UP v1),
  thread/process lifecycle (fault→process-exit, no join/thread-kill,
  Thread+Process handles waitable, get_status/kill rights-gated),
  interrupt delivery (mask-on-fire/ack-to-rearm, ack-is-release,
  one-task-per-IRQ v1, `wait(ack:)` combined form), and the userspace
  runtime model (TaskGroup unchanged; NEW `HandlerGroup` = handles on
  a task pool, move-in/coat-check API, per-attachment non-reentrancy,
  borrow-per-invocation, wake-word key bridge). REMAINING before the
  kernel briefs (spec §11): ONE user design session — root server
  responsibilities + v1 userspace protocol; then the veto-able
  orchestrator pins (rights bits/op tables, memory layout, refcount
  placement, sosimg constants incl. priority-map field) land inside
  the M1/M1b briefs (numbers assigned at dispatch; the spec's old
  78/79 references are stale).

- **DF4 (meta).** Blade bit-rots as the compiler tightens — re-validate
  periodically (the bootstrap target is the canary). [49]
- **DF5.** Keywords (`extension` etc.) can't be identifiers — fine, but
  an eventual contextual-keyword sweep is noted. [49]
- ~~**DF6 (latent coro-transform bug, found in the post-92 net idiom
  skim, Aug 2).**~~ CLOSED (design 96). Root cause was NOT the
  infinite-loop shape but a `break`/`continue` inside a NON-spanning
  `if`/`match` nested in a suspension-spanning loop: `_lower_inplace`
  kept the raw jump, which breaks the resume method's `while true`
  DISPATCH loop instead of the logical loop → re-entry hangs. net
  read()'s break form triggered it via its `else if …else {break}`
  (a non-spanning inner if in the else of the spanning io_wait if).
  Fix: `_has_loop_ctrl` forces a CFG split of such an if/match when in
  a spanning loop, routing the jump to the loop state via `loop_ctx`.
  read() converted to the break form, NOTE removed; regression
  `coro_break_reentered_in_loop`.
- **B4 limit.** A git dep's locked REV isn't pinned without
  re-resolution (build-from-lock path reconstruction is future work);
  path deps unaffected. [64, 67]
- ~~**L18 — module-qualified type annotations (found in design 68).**~~
  FIXED (design 69). The typechecker resolved a dotted annotation
  (`v: mod.Type` / `let x: mod.Type` / `-> mod.Type`) for checking but
  left the dotted `struct_name` on the AST, so codegen ICE'd "Undefined
  struct: mod.Type". Fix at the source: write the resolved (qualifier-
  stripped) type back onto the AST — free-function params (registration),
  let annotations + method params/return (a guarded `_resolve_type` when
  `_annotation_has_module_qualifier` holds, so generic/Self are untouched).
  A related typechecker gap fell out (a method with a qualified param
  errored "body has no value" because the param scope kept the dotted
  type) — fixed by the same write-back. Locked by
  `examples/l18_module_qualified_annotation.saw`. [68, 69]
- **L2.** Return-type reconciliation for type-param/associated-type
  returns in generic bodies — documented deferred looseness. [02, 24]
- ~~**L9.** `==` over Optional-/array-bearing members: deliberate clean
  error; extend the equals derivation when needed.~~ CLOSED (landed e60d189;
  enum-Optional-payload case closed under design 72): the Equatable synthesis
  lowers `T?` (None/Some-aware) and `[T; N]` (element-wise) members. [32, 72]
- ~~**L12.** Fixed arrays can't take extension methods (parse error);
  also blocks fixed-array `.len()` (spec-illustrative).~~ CLOSED (design 72):
  fixed arrays get builtin `.len()` + `.swap(i, j)` (M1 escape hatch); user
  extensions on array types stay rejected with a clear diagnostic. [40, 72]

## Deferred features (decided or triaged, not scheduled)
- ~~Erased-error DOWNCASTING (needs a type-id design; catch-all boxes are
  opaque until then).~~ CLOSED (design 72): vtable `type_id` slot + `Box<any
  Trait>.is<T>()`/`take<T>()`. Catch-side match-on-concrete sugar still deferred
  (future). [56, 72]
- Debug trait (synthesized structural formatting) — own design. [56]
- Enum-direct Printable (enum method dispatch is a general gap). [56]
- Named tuple PATTERN form `(x: a, y: b)`. [63]
- Map `entries()` snapshot; Map ExplicitCopy/.copy(). [54, 57]
- Labeled-arg `_` opt-out; labeled-only enforcement. [66]
- Integer range-cover exhaustiveness. [63]
- Generic-method type-arg inference. [36]
- ~~Closure-Deinit: wire `codegen_env_dtor` into closure drop glue (C4).~~
  **CLOSED (design 71 landed):** escaping closures carry their env destructor
  and drop it at the closure's own drop (exactly once); early frame release
  removed; escaping closures are NoCopy. Residual owning-closure-in-copyable-
  struct-then-copied gap tracked under the design-71 section. [21b, 59, 71]
- `Weak<T>` (Arc slot reserved). [16, 21]
- Slices (needs own design vs no-escape refs); `\x` byte escapes;
  where clauses; extension sugar (computed properties, conditional
  extensions); submodule directories; std.io traits (Blade-driven).
  [user triage Jul 29]
- S5 small-string optimization — ABI-gated ("before separate
  compilation or never"). [07]
- Registry for Blade (salvaged sketch, old pm design): static HTTP
  index or git repo; `GET /api/v1/crates/{name}` metadata +
  `/{version}/download` tarball; `blade login/publish`. [pm_design,
  deleted Jul 30 — see git history]

## Async (post-52b roadmap)
- ~~**A5.** Effect polymorphism via monomorphization-time re-inference —
  BLOCKS generic suspending/driven functions.~~ DONE (design 70): effect
  inference runs PER instantiation (keyed by mangled symbol); the coroutine
  transform accepts suspending instantiations of generic functions/methods by
  monomorphizing them to concrete functions/methods before frame synthesis
  (driven free fn, `TaskGroup.spawn`, and `&var self` method all land). A `sync`
  context calling an instantiation that suspends is a violation reported AT the
  call, naming the instantiation + suspension path (minimal A8). Still rejected
  with precise diagnostics: a buried suspending method-on-`T` call inside a
  driven body, nested suspending generic calls, generic-struct-extension driven
  methods, and cross-module generic templates (re-ledgered below). [18, 22]
  - **A5-rest.** PARTLY DONE (design 74): driven methods on GENERIC structs
    (shape 2) and nested suspending generic calls (shape 3) LANDED; A8 diagnostic
    anchors LANDED (coroutine-transform rejections anchor at the user's
    file:line:col). Remaining, now CLEAN user-anchored rejections (re-ledgered
    under the design-74 section with analysis): buried suspending METHOD-call
    embedding (shape 1, the Part-0b method twin); cross-module generic driven
    templates (shape 4, design 68 territory). [70, 74]
- ~~**A2.** Multi-threaded work-stealing executor + Send-on-frames check.~~ DONE
  (design 75): `TaskGroup(threads: N)` runs N OS workers over a single
  mutex-protected shared queue (fork-join drain; per-worker lock-free deques
  deferred as documented — the sanctioned simpler shape). Send-on-frames gate on
  spawn into a multi-threaded group (params + across-suspend locals + result). D6
  confinement preserved (one worker per frame; frames move only between
  suspensions). Cross-task cancel via `TaskHandle.cancel_addr()`. [18, 52b, 75]
- **A3.** Explicit-only cancellation points (`Task.cancelled()`, select).
  MOSTLY DONE (design 76): cancellation observed at the io suspension point via the
  cancel-check-before-`io_wait` idiom (+ the existing channel/yield checks).
  Remainder: waking an ALREADY-io-parked task on cancel (self-pipe) — re-ledgered
  under design 76.
- ~~**A4.** IO reactor (poller-only v1, kqueue/epoll, never-block).~~ MOSTLY DONE
  (design 76): global kqueue/epoll reactor + `io_wait` intrinsic + std.net
  nonblocking TCP; ST group + entry executor never-block poll. Remainders
  re-ledgered under design 76 (MT integration, first-class inline-lowered
  read/accept/write). [18, 76]
- ~~**A6.** `extern blocking` offload pool.~~ DONE (design 76 front-end + the two
  type-system rejections; design 103 the runtime offload + coro lowering — a
  blocking call inside a suspending body now RUNS on a worker thread and parks on
  its pipe; see the design 103 entry). **A7.**
  Separate-compilation interface format w/ suspends bit. ~~**A8.** Suspension-path
  diagnostic anchors.~~ DONE (design 74): coroutine-transform rejections + sync
  violations anchor at the user's file:line:col with a source snippet, naming the
  instantiation + suspension path. ~~**A9.** Actor sugar.~~ DROPPED from the
  roadmap (user, Jul 31). [18, 74, 76]
- Two runtimes coexist (thread-engine spawn/Task vs cooperative
  TaskGroup) — unification unscheduled. [21b, 52b]

## App-2 / freestanding path
- ~~**F7** remainder: assembly boot shim + wiring. **F8** linker scripts.
  **F9** QEMU riscv32 smoke ("blink") + CI.~~ DONE (design 112, Aug 4):
  `sos/kernel/` boot.S + virt.ld + rt.c runtime seams + `main.saw` (UART
  driver over `UnsafeMemory<_, Device>`); boots under `qemu-system-riscv32
  -M virt -bios none`, prints a banner, exits 0 via `sifive_test`; trap
  stub + freestanding panic seam both FAIL the run (never hang);
  `make sos-test` (tools/sos_runner.py) + ubuntu CI job. **F10** fence/
  barrier primitives for DMA ordering. [20, 46, 58, 112]
- ISR conventions; riscv32 target completion (i32 word landed, 47).
- **DF-112a (design-112 discovery, FIXED in this brief — sawc touch, flag
  for the lead vs concurrent design 113):** two freestanding-riscv32
  blockers surfaced on first bare-metal use. (1) An ICE — `_generate_spawn`
  (codegen/calls.py) hardcoded `i64` for the `saw_alloc` seam args instead
  of `self.int_type`, so ANY freestanding riscv32 compile ICE'd ("i32 !=
  i64") because codegen emits every loaded stdlib method incl. a spawn-using
  one (last un-migrated design-47 site; closures were already migrated).
  Fixed to platform-width. (2) Dead-code strip — codegen emits every loaded
  stdlib method + its closure/vtable descriptors + backend constant pools
  regardless of reachability, and freestanding still loads channel/mutex/
  task/float-print methods referencing pthread/snprintf/float/atomic
  symbols a bare-metal target can't satisfy. Added a freestanding-only
  post-pass (`_apply_freestanding_sections`) that internalizes non-`@export`
  defs (so O1 `globaldce` deletes everything unreachable from `kmain` +
  `@llvm.used` — the primary mechanism, reaches fused constant pools that
  IR-level sections cannot) + per-symbol sections for `--gc-sections`.
  Host suite 993/993 green (freestanding-guarded, hosted byte-identical).
- **DF-112b (pin deviation, design 112):** the pinned ISA was
  `rv32imac_zicsr`, but llvmlite emits `rv32i` (base, ilp32 soft-float)
  for the `riscv32-unknown-none-elf` triple — sawc exposes no CLI feature
  string to request imac. rv32i runs fine on QEMU's default `virt` rv32
  CPU (a subset); boot.S/rt.c are assembled `rv32imac_zicsr` and link
  cleanly. If a kernel needs mul/div/atomics inline (not libcalls), sawc
  needs a `--target-features` surface — future work, not M0-blocking.
- **DF-118a (design-118 stage-3 discovery, FIXED in that brief — sawc touch):**
  the IO reactor seams (`__saw_rt_reactor_create/register/poll/wake/destroy`) were
  declared with a hardcoded `i64` in `codegen/core.py::_declare_io_runtime`, but
  they carry `Int` (platform word). Latent since design 117 — freestanding never
  referenced a reactor seam (the compiler-synthesized `__saw_reactor()` getter was
  `internal` + unreachable → stripped before the width mattered). Design 118 stage 3
  moved the reactor singleton into the prelude std (`__saw_host_reactor()` /
  `SystemReactor` in taskgroup.saw), so the seams are now CALLED from Saw and their
  IR is generated on the freestanding riscv32 target too — where `Int` is i32,
  producing an invalid `cmpxchg i32 … i64` against the `Atomic<Int>` cell (IR
  parse error). Fixed to `self.int_type` (platform word) — byte-identical on the
  64-bit hosted targets, correct i32 on riscv32 (same class as DF-112a). The
  sos_runner (freestanding riscv32 QEMU) is the regression test.
- **F5.** `Once`/`Lazy<T>`, `PerCpu<T>`, UnsafeCell-equivalent story.
- **F6.** dtoa/Float printing under freestanding. [20]
- ~~**T1f.** Debug info (line tables → backtraces).~~ DONE (design 69):
  DWARF line tables on by default; lldb breakpoints + `file:line`
  backtraces; panics/asserts name their source location. [tier-1]
- `AllocatedBy<Slab>` sugar. [19, 42]

## Testing & infra
- **M2.** Unit tests for lexer/parser/typechecker internals; fuzz/
  differential testing; property tests over copy/move rules. [critique]
- ~~CI: GitHub Actions workflow for suite + bootstrap.~~ DONE (design 69):
  `.github/workflows/ci.yml` (ubuntu + macos) runs the compiler suite,
  the debug-info test, the blade bootstrap, and semver/toml lib tests;
  README badge. Linux is a new target — first CI run may surface small
  follow-ups (PIC-reloc + sys.executable portability fixes landed).
- ~~Runtime error messages with source locations (subsumed by T1f).~~
  DONE (design 69): panics carry `FILE:LINE`.

## Research tier (post-both-apps)
Const generics; const fn; macros; compile-time reflection (PMP
generation consumer, 46); Char/Int128/Float32; `**`/`::` operators;
Deque; RwLock/Barrier; std.net (after A4); async select;
Sender/Receiver split; §11 futures (effect system, dependent/linear/
refinement types, first-class modules); REPL/LSP/formatter; `defer`/
`do` reserved-word decisions.
