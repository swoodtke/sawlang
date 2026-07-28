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

- **D10. Cortex-M0-class atomics** — lowering strategy for ARMv6-M (no
  CAS); decide with the first such port. [19, 20]

## Language & semantics

- **L1.** Partial moves — DECIDED forbidden on all structs (design 35);
  remaining work is the small audit/diagnostic item in that doc
  (destructure-move and take() deferred wait-and-see). [15, 35]
- **L2.** Return-type reconciliation for type-param / associated-type
  returns in generic bodies — documented deferred looseness from brief 24.
  [02, 24]
- **L3. VERIFY:** cross-module fallback lookup in
  `typechecker/types.py` (`get_struct_info`/`get_enum_info`) scans all
  modules ignoring visibility, resolving by dict order. Brief 26 fixed
  collisions at the codegen merge; the typechecker-side lookup may still
  need a visibility check + ambiguity diagnostic. [critique structural]
- **L5.** Array-mutation gaps (brief-33 observations, XFAIL-ledgered):
  `a[0].v = 99` silently no-ops (`array_elem_field_assign.saw`);
  `a[0] = newElem` never deinits the overwritten element
  (`array_elem_overwrite_deinit.saw`). [33]
- **L6.** Module-qualified MemberAccess (`mod.struct_value.field`) reaches
  codegen without `resolved_type` — pre-existing typechecker annotation
  gap, worked around non-fatally in brief 31's signedness probe
  (defaults to signed). Close by annotating in the module member-access
  checker. [31 report]
- **L7.** Consuming a generic-instantiated `Result<T,E>` via direct
  `match`/`try!` at the instantiation's binding site hits
  monomorphization gaps ("Undefined struct: T"); routing through a
  concrete-typed consumer works. Pre-existing, found in brief 30's
  generic lock-in test. [30 report]
- **L8.** Generic function taking a generic container BY PARAMETER
  (`unbox<T>(b: Box<T>)`) recurses in monomorphization — pre-existing,
  broader sibling of L7, reproduced with zero equality involvement
  (brief 32 report). [32 report]
- **L9.** `==` over Optional- or array-bearing members not yet
  lowerable (auto-conform deliberately excludes them; clean error at
  comparison site). Extend the equals derivation when needed. [32]
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
- **S4.** String equality/comparison — `==` resolved by design 32
  (builtin Equatable conformance over existing `equals`); ordering
  comparisons (`<` etc. / a Comparable trait) still open. [11, 32]
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
- **A4.** IO reactor — model decided (poller-only v1, kqueue/epoll over
  unbounded sources; never-block invariant); build at/after stage 2. [18]
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

- **L1 (partial moves) — DECIDED Jul 28 (user): forbidden on all
  structs, uniformly**; destructure-move and Optional take() deferred
  wait-and-see (purely-additive relaxations). Accepted consequence:
  safe code cannot extract owning fields from owned structs until a
  relaxation lands. → design 35. [15, 35]
- **D5 (async IO) — was already decided by the Jul 28 never-block
  revision in paper 18 (poller-only v1 reactor; bounded local IO stays
  sync; pool later only for `extern blocking`/optimization); the paper's
  "does NOT decide" line was stale and is now fixed. [18]
- **D6 (async self-isolation) — DECIDED Jul 28 (user):** `&var self` /
  reference params may span suspension points freely — sound via task
  confinement (refs can't escape their task's call stack; cross-task
  sharing is Mutex/channel-mediated with sync critical sections).
  Recorded in paper 18. [18]
- **D7 (call-site sigils) — DECIDED Jul 28 (user):** call sites mirror
  the parameter — `&x` for `&T`, `&var x` for `&var T`, validated both
  directions; completes the sigil symmetry with types/receivers/
  captures. Implementation + migration → design 34. [10, 12, 34]
- **D9 (arrays of owning types) — DECIDED Jul 28 (user):** `[T; N]`
  inherits T's copy class (trivial/ExplicitCopy/NoCopy); per-element
  `.copy()`; no large-trivial-copy warning threshold. Suspected live
  soundness hole (arrays never covered by containment/drop glue) —
  probe-first implementation → design 33. [06, 33]
- **D2 (equality) — DECIDED Jul 28 (user):** `Equatable` mirrors the
  Copy family — trivial structs + payload-free enums auto-conform;
  everything else opts in with synthesized memberwise/payload-deep `==`
  (desugared to `.equals`); resource types never conform; fixes the
  tag-only payload-enum `==` bug. Decision + implementation → design 32.
  [13, 32]
- **D1 (integer overflow) — DECIDED Jul 28 (user):** checked arithmetic
  always, every profile — overflow panics (incl. INT_MIN/-1 and signed
  negation of min); intentional wrap via Swift-style `&+ &- &*`
  operators. Decision + implementation → design 31. [05, 13, 31]
- **D3 (Result auto-wrap + error union) — DECIDED Jul 28 (user):**
  concrete `T == E` bare returns are a compile error (explicit variant
  required); generic bodies keep abstract per-parameter wrapping; the
  multi-error union is a closed, compiler-synthesized, UNNAMEABLE enum —
  escape prevented structurally. Decision + implementation → design 30.
  [critique concern 3, 30]
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
