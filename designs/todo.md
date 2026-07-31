# Saw — Open Work Tracker

Open items ONLY. Landed work lives in `designs/NN-*.md` + git history
(this file was pruned Jul 30; see git history of this file for the old
landed recaps). Conventions: cite source designs in [brackets]; VERIFY
items need a probe before being treated as real work.

## Milestones
- **App-1 Blade: DONE** (design 64 + 67; real resolver/lock/git/
  incremental/self-hosting bootstrap; `make blade-bootstrap`).
- **App-2 SOS kernel (ESP32-P4, riscv32): NEXT.** Milestone: UART
  "blink" from a Saw kernel on the P4. See sos/spec.md.

## Decisions needed (user input required)
- **D10.** Cortex-M0-class atomics (ARMv6-M has no CAS) — decide with
  the first such port. [19, 20]
- **SOS**: boot protocol + syscall ABI (sos/spec.md §5) — the next
  design session.

## Design 68 progress (cross-module mono/receiver confusion)
- ROOT CAUSE (DF6(b)): erased-box default-type-arg mangling divergence.
  The typechecker canonicalizes `Box<any Trait>` to arity-2
  `Box<any Trait, Global>`; codegen registers composite types embedding
  it (the err arm of `Result<T, Box<any Error>>`) from the RAW arity-1
  method annotation. A `match`/`try` then mangle-missed the registered
  enum and the LLVM-type fallback silently picked a same-sized WRONG
  monomorphization (payload read as the wrong type). Fix: normalize the
  erased box to ONE canonical arity-1 in codegen `_canonicalize_type_kind`
  and route the match / `_get_result_enum_name` (try) lookups through it,
  so registration and lookup never diverge. (b) un-worked-around: DepList
  is `Vector<Dependency>` again; 770 suite + 17 blade + libs + bootstrap
  green.

## Open bugs / ledger
- **DF9(c)/semver re-import — IN PROGRESS (design 68).**
  Re-import libs/semver into blade's resolver (delete the self-contained
  matcher, add the path dep, regenerate lock). Same erased-box family as
  (b); verifying the fix covers the `Version.version` receiver confusion.
  [64, 67, 68]
- **DF4 (meta).** Blade bit-rots as the compiler tightens — re-validate
  periodically (the bootstrap target is the canary). [49]
- **DF5.** Keywords (`extension` etc.) can't be identifiers — fine, but
  an eventual contextual-keyword sweep is noted. [49]
- **B4 limit.** A git dep's locked REV isn't pinned without
  re-resolution (build-from-lock path reconstruction is future work);
  path deps unaffected. [64, 67]
- **C6 — VERIFY (conflicting records).** Method-level generic type
  params on non-generic-type extensions (`extension String { func
  f<R> }`): the brief-40 sweep note says fixed (value-returning
  `withCString<R>`), a later entry says open. Probe, then close or fix.
  [38, 40]
- **L2.** Return-type reconciliation for type-param/associated-type
  returns in generic bodies — documented deferred looseness. [02, 24]
- **L9.** `==` over Optional-/array-bearing members: deliberate clean
  error; extend the equals derivation when needed. [32]
- **L12.** Fixed arrays can't take extension methods (parse error);
  also blocks fixed-array `.len()` (spec-illustrative). [40]

## Deferred features (decided or triaged, not scheduled)
- Erased-error DOWNCASTING (needs a type-id design; catch-all boxes are
  opaque until then). [56]
- Debug trait (synthesized structural formatting) — own design. [56]
- Enum-direct Printable (enum method dispatch is a general gap). [56]
- Named tuple PATTERN form `(x: a, y: b)`. [63]
- Map `entries()` snapshot; Map ExplicitCopy/.copy(). [54, 57]
- Labeled-arg `_` opt-out; labeled-only enforcement. [66]
- Integer range-cover exhaustiveness. [63]
- Generic-method type-arg inference. [36]
- Closure-Deinit: wire `codegen_env_dtor` into closure drop glue (C4
  verified no leak today — env released at creating frame's exit). [21b, 59]
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
- **A5.** Effect polymorphism via monomorphization-time re-inference —
  BLOCKS generic suspending/driven functions. [18, 22]
- **A2.** Multi-threaded work-stealing executor + Send-on-frames check.
- **A3.** Explicit-only cancellation points (`Task.cancelled()`, select).
- **A4.** IO reactor (poller-only v1, kqueue/epoll, never-block).
- **A6.** `extern blocking` offload pool. **A7.** Separate-compilation
  interface format w/ suspends bit. **A8.** Suspension-path diagnostic
  anchors. **A9.** Actor sugar. [18]
- Two runtimes coexist (thread-engine spawn/Task vs cooperative
  TaskGroup) — unification unscheduled. [21b, 52b]

## App-2 / freestanding path
- **F7** remainder: assembly boot shim + wiring (compiler surface DONE
  — @export/@section/Never, design 58). **F8** linker scripts. **F9**
  QEMU riscv32 smoke ("blink") + CI. **F10** fence/barrier primitives
  for DMA ordering. [20, 46, 58]
- ISR conventions; riscv32 target completion (i32 word landed, 47).
- **F5.** `Once`/`Lazy<T>`, `PerCpu<T>`, UnsafeCell-equivalent story.
- **F6.** dtoa/Float printing under freestanding. [20]
- **T1f.** Debug info (line tables → backtraces). [tier-1]
- `AllocatedBy<Slab>` sugar. [19, 42]

## Testing & infra
- **M2.** Unit tests for lexer/parser/typechecker internals; fuzz/
  differential testing; property tests over copy/move rules. [critique]
- CI: GitHub Actions workflow for suite + bootstrap (salvaged from old
  root todo.md).
- Runtime error messages with source locations (subsumed by T1f).

## Research tier (post-both-apps)
Const generics; const fn; macros; compile-time reflection (PMP
generation consumer, 46); Char/Int128/Float32; `**`/`::` operators;
Deque; RwLock/Barrier; std.net (after A4); async select;
Sender/Receiver split; §11 futures (effect system, dependent/linear/
refinement types, first-class modules); REPL/LSP/formatter; `defer`/
`do` reserved-word decisions.
