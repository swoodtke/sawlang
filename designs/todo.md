# Saw — Open Work Tracker

Living document. Consolidates every unresolved item from the design briefs
(`designs/01`–`27`) and the outstanding issues from the original critique
(`todo_jul26.md`, now historical). Sourced from a full sweep of all design
docs on Jul 27, 2026, cross-checked against landed commits.

Conventions: each item cites its source design(s). Items marked **VERIFY**
need a probe against current source before being treated as real work.
When an item becomes harness-expressible, encode it as an XFAIL ledger test
(brief 12 discipline) before fixing it.

---

## Decisions needed (user input required)

- **D1. Integer overflow semantics** — wrap, panic, or UB? Also gates
  INT_MIN/-1 division trapping (out of scope in brief 05). [05, 13]
- **D2. Struct equality semantics** — memberwise `==`? Derived? What about
  structs containing resources? [13]
- **D3. Result auto-wrap ambiguity** — `return x` in `Result<T, E>` when
  `T == E` (reachable via generics): define the tie-break or restrict
  auto-wrap to unambiguous cases. Also: the auto-created multi-error union
  needs real spec semantics (what is `error`'s type? can it escape the
  catch block? interaction with generics / future `Error` trait).
  [critique concern 3; not covered by any brief]
- **D5. IO integration for async** — kqueue/epoll reactor vs blocking-pool;
  explicitly open in the concurrency model paper. [18]
- **D6. Async self-isolation** — may a suspending method's `&var self` span
  suspension points? Decide deliberately at the async milestone. [18]
- **D7. Call-site `&x` vs `&var` param validation** — should the call site
  distinguish `&x` (immutable lend) from `&var x`, with the compiler
  enforcing the match? Flagged in briefs 10/12 as "design decision
  pending." [10, 12]
- **D9. Arrays of owning types** — copy semantics (recommended: move-only
  with per-element `.copy()`); plus whether to warn on implicit copies of
  large trivially-copyable structs (recommended: no threshold for now).
  [06]
- **D10. Cortex-M0-class atomics** — lowering strategy for ARMv6-M (no
  CAS); decide with the first such port. [19, 20]

## Language & semantics

- **L1.** Partial moves of struct fields (`move p.x`) — currently
  undesigned/unsupported; parser behavior unaudited. [15]
- **L2.** Return-type reconciliation for type-param / associated-type
  returns in generic bodies — documented deferred looseness from brief 24.
  [02, 24]
- **L3. VERIFY:** cross-module fallback lookup in
  `typechecker/types.py` (`get_struct_info`/`get_enum_info`) scans all
  modules ignoring visibility, resolving by dict order. Brief 26 fixed
  collisions at the codegen merge; the typechecker-side lookup may still
  need a visibility check + ambiguity diagnostic. [critique structural]
- **L4. VERIFY:** `Vector<File>.copy()`-style diagnostic — was a raw
  Python traceback (brief 09 report); brief 26's ICE wrapper now catches
  it, but it should be a proper user-facing typechecker error, not an ICE.
  [09, 26]

## String stack

- **S1.** API expansion: `fromBytes` (Result-returning), `bytes()` /
  `chars()` views, `withCString` scoped borrow. [07, 11]
- **S2.** UTF-8 validation (compile-time for literals; `fromBytes` at
  runtime). [07, 11, 13]
- **S3.** Mutable `StringBuilder` on the new refcounted representation.
  [07]
- **S4.** String equality/comparison operators. [11]
- **S5.** Small-string optimization — ABI-gated; "before separate
  compilation or never." [07]

## Closures & iteration

- **C1.** Full non-escaping closures with explicit bracketed reference
  captures — UNBLOCKED (D8 decided); briefed with C2 as
  `designs/29-nonescaping-closures-impl.md`. [16, 29]
- **C2.** Stdlib iteration API (`Vector.each`/`map`/`fold`) — item 6 of
  brief 29. [16, 29]
- **C3.** `Weak<T>` — Arc's weak-count slot is already reserved; build when
  stored callbacks give it a use case. [16, 21]
- **C4. VERIFY:** general (non-spawn) escaping-closure environment
  teardown / closure-`Deinit` — brief 21b shipped the spawn-consumer path;
  confirm what non-spawn escapes do. [21b]

## Concurrency & async

- **A1.** Stage 2 async: stackless coroutine / state-machine transform
  (start with the llvmlite coro-intrinsics probe). [18]
- **A2.** Stage 3: multi-threaded work-stealing executor +
  Send-on-coroutine-frames check. [18]
- **A3.** Explicit-only cancellation (`Task.cancelled()`, select points).
  [18]
- **A4.** IO reactor (blocked on D5). [18]
- **A5.** Effect polymorphism via monomorphization-time re-inference —
  adopt at stage 2. [18, 22-findings]
- **A6.** `extern blocking` offload machinery (hosted pool). [18]
- **A7.** Separate-compilation module-interface format carrying each public
  function's `suspends` bit + effect shape. [22-findings]
- **A8.** Diagnostic anchor refinement for suspension-path errors (minor).
  [22-findings]
- **A9.** Actor sugar over Arc+Mutex+queue. [16, 18]

## Freestanding & allocators

- **F1.** `Allocator` trait + `Global` implementation — UNBLOCKED (D4
  decided); briefed as `designs/28-allocator-stage3.md` with `alignof<T>()`
  and the placement-write contract. [19, 28]
- **F2.** Default type parameters (`A = Global`) — generics feature; stage
  4, after brief 28. [19]
- **F3.** Slab allocators + `AllocatedBy` sugar. [19]
- **F4.** Module-level `static` declarations (needed for slab regions and
  const-init `Mutex`-in-static). [19]
- **F5.** `Once`/`Lazy<T>`, `PerCpu<T>`, `UnsafeCell`-equivalent + the
  unsafe story for user lock-free structures. [19]
- **F6.** dtoa / Float printing under `--freestanding` (currently a
  compile error). [20]
- **F7.** Custom entry symbols (`_start` / vector table). [20]
- **F8.** Linker scripts. [20]
- **F9.** QEMU/CI freestanding smoke target ("blink"). [20]

## Stdlib & misc

- **M1.** `swapAt`-style stdlib escape hatch for dynamic-index exclusivity.
  [08]
- **M2.** Testing depth beyond the e2e harness: unit tests for
  lexer/parser/typechecker internals, fuzz/differential testing, IR-level
  assertions. Property tests over the copy/move rules would have caught
  the original safety gaps. [critique structural]
- **M3.** Parser top-level dispatch dedup between `parse()` and
  inline-module parsing (~40 lines; skipped in brief 26 as invasive).
  [26]

## In flight

- Brief 27 (symbol-object split; closure param inference in struct-init
  fields; `_check_init_method_call` branch) — agent working now. [27]

## Recently resolved (recorded here to stop re-flagging)

- **D8 (closure syntax) — DECIDED Jul 28 (user):** `escaping` marker in
  the function type's post-parameter slot (matching `sync`); explicit
  captures in a bracketed list (`{ [&var sum] x in ... }`), distinct from
  reference-typed closure params. Implementation → brief 29. [16]

- **D4 (allocator model) — DECIDED Jul 28 (user): A + C ratified.** Global
  seam stays; allocator-as-type-parameter is the model; default type
  params accepted as staged cost. Placement-write primitive pinned
  (`ptr[i] = move value`: bitwise move, source consumed, no destination
  release); `alignof<T>()` gap found. Stage 3 → brief 28. [19]

- Immutable-borrow receiver exclusivity hole (`x.read(&var x)`) — FIXED
  `76adfb3` (design docs 10/12 not yet annotated). [10, 12]
- `sync` post-parameter syntax slot — APPLIED `00918b3` ("apply after 21b"
  note in 18 is stale). [18]
- Suite-timing concern — measurement artifact of concurrent runs; suite is
  ~24s uncontended. [todo_jul26]
- The brief-01 high-value safety tests (NoCopy-into-call, CustomCopy args,
  mangling stress, >1KB interpolation, dangling interpolation, div-by-zero,
  const-index bounds) — encoded and passing since briefs 01/03/05/12.
