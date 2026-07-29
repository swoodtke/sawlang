# Saw — Open Work Tracker

## PATH TO APPLICATIONS (goal set Jul 29, user)

Two application testbeds, in order:

**App-1: Blade** (the package manager, blade/ — already 615 lines of
real Saw; milestone 5 done: CLI, TOML, builder, scaffolding). Finish it
for real: dependency resolver (semver — the forcing consumer for
ordering/comparison), Saw.lock (deterministic sorted output), git
integration, incremental builds. Blade's pain points are the Tier-1
punch list's ground truth.

**App-2: minimal kernel on ESP32-P4** (RISC-V RV32IMAFC dual-core).
Consequences to plan for: a **riscv32 target** (32-bit! — see D13:
codegen currently assumes 64-bit Int/pointers), volatile/MMIO access
(D12 — undesigned, kernel-blocking), ISR conventions, custom entry +
linker scripts (F7/F8), and a QEMU riscv32 stage before hardware (F9).
Milestone: UART "blink" from a Saw kernel on the P4.

**Tier-1 briefs (any-real-app blockers), post-async:**
- T1a. Bitwise operators (`& | ^ ~ << >>`) + hex/binary literals.
- T1b. Runtime bounds checks on dynamic array indexing (closes a real
  safety hole; panic machinery exists).
- T1c. Ordering + hashing: Comparable/Ord + sort, Hash + real HashMap
  (Map is Vector-backed linear scan) — needs D13/D14 shapes decided.
- T1d. Pattern-matching completion: literal/range patterns, guards,
  tuple destructuring.
- T1e. `panic(msg)`/`assert` (M4) + in-language test support (shape:
  D15).
- T1f. Debug info (line tables minimum → backtraces); multiplies
  productivity of everything after it.

**Path decisions — ALL DECIDED Jul 29 (user), briefed:**
- **D12 → design 46**: `UnsafeMemory<T, Use>` — intent markers
  (Device/Normal), explicit always; compiler derives access discipline
  (Device=volatile, scalar-only, RO/WO markers; Normal=plain +
  whole-struct + ptr/len/end region accessors); platform setup derives
  its obligations (cache attrs are PMA/boot-code territory; the
  declaration is the coordination point; future reflection hook).
  Unsafe-prefix HOUSE RULE ratified. NEW tracker item: fence/barrier
  primitives for DMA ordering (F10).
- **D13 → design 47**: platform-width Int/UInt (i32 on riscv32).
- **D14 → design 48**: Hashable mirrors Equatable (auto trivial +
  synthesis, streaming FNV-1a Hasher); Comparable opt-in only
  (Ordering enum, synthesized lexicographic); Vector.sort/sort_by;
  HashMap<K,V,A>; Map stays (deprecation = later decision).
- **D15 → design 49**: panic(msg)/assert builtins (closes M4) +
  `blade test` convention (tests/ = ordinary programs, exit 0 = pass).
- **F10.** Fence/barrier primitives (fence rw,io etc.) for DMA
  ordering — surfaced by the D12 discussion; needed by App-2. [46]


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

## SPEC-GAP PRIORITIES (Jul 29 sweep of LANGUAGE_SPEC planned-not-implemented)

Full extraction lives in the sweep report (agent transcript); this is
the prioritized digest. Excludes items ALREADY queued: T1b bounds,
T1d patterns, 48 Ord/Hash, 49 assert/blade-test, 51 any (in flight),
A1a CFG split, A1b multi-task async, T1f debug info, F10 fences.

### NEED TO HAVE (blocks App-1 Blade or App-2 kernel)
- **N1. Trait default method bodies** — spec'd since day one; unlocks
  Display/Debug/Error ergonomics. [App-1]
- **N2. Display trait + user types in string interpolation** — rides
  N1; Blade output quality. [App-1]
- **N3. Error trait** (`message()`, catch-all matching) — buildable
  once 51 lands (`any Error`). [App-1]
- **N4. Map iteration (keys/values/entries) + string→number parsing
  helpers** — Blade TOML tables, semver, lock files. [App-1]
- **N5. std.time (Instant/Duration, hosted)** — blade test timing,
  build reports. [App-1]
- **N6. Minimal attribute grammar + C-callable exports** —
  no_mangle-equivalent, repr(C), extern exports; the kernel entry
  symbol (F7) needs it; also unlocks future #[test]/derive surface.
  [App-2]
- **N7. Built-in type extensions where still missing (extension Int
  etc.)** — small; String already has them. [App-1]

### NICE TO HAVE (real weight, not blocking)
Default parameter values; `..=` + enumerate(); Int.max/min constants +
fixed-width literal suffixes (the design-47 literal note); Set<T>
(HashMap-backed) + Map/Set literals; unsafe blocks (formalize the
naming convention into scoping); slices (needs its own design —
interacts with no-escape refs); where clauses; static_assert;
\x/\u{} escapes (string model reserved room); import aliasing `as`;
submodule directories; Vector literals; std.io Read/Write traits (on
N1+51); `loop` keyword; computed properties; conditional extensions;
method overloading beyond init; use-before-init detection.

### MAYBE LATER (research-tier or post-both-apps)
Const generics; const fn; macros (declarative/derive beyond N6's
minimal attributes); compile-time reflection (future consumer: board
PMP generation per design 46); Char / Never / Int128 / Float32; `**`
and `::` operators; Deque; RwLock/Barrier; std.net (waits on A4
reactor by design); async `select`; Sender/Receiver split handles;
generic-method type-arg inference; §11 futures (effect system,
dependent/linear/refinement types, first-class modules); REPL/LSP/
formatter; `defer`/`do`/`ref` keywords (candidates to DROP from the
reserved list — no designs exist).

### Resolved-by-decision / stale-spec (fix docs, no work)
Rc (Arc-only, decided design 16); thread API + async/await (colorless
— never); `=>` arrows (superseded); swapAt (landed as Vector.swap,
brief 40 — spec stale); StringBuilder "future work" note (landed 38);
`dyn` reservation (retired by D16). **Verify-then-fix the four
spec/TODO contradictions:** multiple bounds `A + B`, glob imports,
scoped visibility (all probably landed — spec markers stale), named
tuple field access + `.value` on distinct types (probably NOT landed —
spec examples aspirational).

## Language & semantics

- **BRIEF 40 SWEEP (Jul 29) — L3, L4, L6, L9, L10, L11, M1, M3, C6 all
  CLOSED** (fixed or verified-fine with locking tests; see
  designs/40-cleanup-family.md + its report in the commit trail).
  Notable: `&var self`-on-`let` was also unenforced (fixed);
  `withCString<R>` is now value-returning (C6 fixed).
- **L13.** UInt division/modulo emit `sdiv`/`srem` (wrong for high-bit
  values) — XFAIL-ledgered `uint_division_signedness.saw` (brief 40
  item-3 sidecar discovery). Fix: pick udiv/urem by signedness like the
  overflow intrinsics already do. [40 report]
- **L12.** Fixed arrays cannot take extension methods (parse error) —
  blocked M1's fixed-array swap variant. [40 report]

- **L1.** Partial moves — DECIDED forbidden + LANDED (design 35,
  `2829364`): field/nested/index forms all get naming diagnostics; the
  audit found `move arr[i]` had been silently moving the whole array
  into an ICE. Destructure-move and take() stay wait-and-see. [15, 35]
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
- **L7.** ~~Generic Result direct consumption~~ — FIXED (brief 36):
  return-type substitution + match scrutinee normalization; red-proven
  tests kept. [30 report, 36]
- **L8.** ~~Generic-container-parameter monomorphization recursion~~ —
  FIXED (brief 36): type_args substituted against the active
  type_param_context before nested monomorphization; red-proven tests
  kept. [32 report, 36]
- **L9.** `==` over Optional- or array-bearing members not yet
  lowerable (auto-conform deliberately excludes them; clean error at
  comparison site). Extend the equals derivation when needed. [32]
- **L10.** Implicit tail-return of an owned ImplicitCopy value
  auto-wrapped into `Ok(...)` releases the owned buffer at scope exit
  while the payload still points at it (premature free) — found in
  brief 38's fromBytes; worked around with explicit `return move`.
  Needs the auto-wrap path to treat the wrapped value as transferred.
  [38 report]
- **C6.** Method-level generic type params don't monomorphize on
  NON-generic-type extensions (`extension String { func f<R>(...) }` →
  "Undefined struct: R") — blocks value-returning `withCString<R>`.
  Sibling of C5, surfaced in brief 38. [38 report]
- **L4. VERIFY:** `Vector<File>.copy()`-style diagnostic — was a raw
  Python traceback (brief 09 report); brief 26's ICE wrapper now catches
  it, but it should be a proper user-facing typechecker error, not an ICE.
  [09, 26]

## String stack

- **S1.** ~~API expansion~~ — LANDED (brief 38): `fromBytes` +
  `Utf8Error`, `bytes()`/`chars()` iterators (retain-safe), `withCString`
  over the NUL-terminated payload (non-escaping closure; returns Void —
  generic `<R>` form blocked on C6). [07, 11, 38]
- **S2.** ~~UTF-8 validation~~ — LANDED/RESOLVED (brief 38): runtime
  validation in fromBytes (shared `_decode_at`); literal-side proven
  structurally unreachable (UTF-8 source decode + no byte escapes) —
  documented guarantee, TODO if byte escapes ever land. [07, 11, 13, 38]
- **S3.** ~~StringBuilder~~ — LANDED (brief 38): O(1) length appends,
  `append_int`, canonical refcount-correct `build()`, independence +
  1M-iteration flat-memory verification. [07, 38]
- **S4.** String equality/comparison — `==` resolved by design 32
  (builtin Equatable conformance over existing `equals`); ordering
  comparisons (`<` etc. / a Comparable trait) still open. [11, 32]
- **S5.** Small-string optimization — ABI-gated; "before separate
  compilation or never." [07]

## Closures & iteration

- **C1.** Non-escaping closures — LANDED (brief 29, `c69d657`..`4b34f5c`):
  escaping type bit + variance, bracketed capture lists, env-of-
  references lowering, exclusivity join (iterator invalidation is a
  compile error), forwarding rules. [16, 29]
- **C2.** Iteration API — FULLY LANDED: `each` (brief 29) + `map<U>`/
  `fold<A>` (brief 36, on generic methods). [29, 36]
- **C5.** ~~Generic methods~~ — LANDED (brief 36): method-level type
  params with explicit call-site instantiation
  (`v.map<String>(...)`), (struct × method) canonical mangling,
  per-pair monomorphization. Type-argument INFERENCE remains future
  work. [36]
- **C3.** `Weak<T>` — Arc's weak-count slot is already reserved; build when
  stored callbacks give it a use case. [16, 21]
- **C4. VERIFY:** general (non-spawn) escaping-closure environment
  teardown / closure-`Deinit` — brief 21b shipped the spawn-consumer path;
  confirm what non-spawn escapes do. [21b]

## Concurrency & async

- **A1.** Stage 2 async — TRANSFORM COMPLETE for straight-line +
  nested calls + methods (briefs 44/45 Part 0); single-task runtime
  slice landed (yield_now/sleep as real suspension sources; suspending
  main auto-wrapped in the entry executor; __wake protocol word).
  Remaining, in order: **A1a** CFG-based split (suspends inside
  loops/if/match — currently honest compile errors; pure
  implementation); **A1b** cooperative spawn/join + cancellation +
  suspending Channel.receive — BLOCKED ON D16 (type-erased task
  handles: Saw has no function pointers or trait objects to put
  heterogeneous frames in one run queue); generic driven functions
  blocked on A5. Bonus fix en route: empty module datalayout made O1
  and object emission disagree on struct offsets (pre-existing
  miscompile class, now pinned everywhere). [44, 45]
- **D16 — DECIDED Jul 29 (user): user-facing `any Trait` NOW**
  (design 51): contextual `any` keyword, erased values behind &/Box
  only (no hidden existential container), construct-erased-directly
  (no unsizing coercion), v1 object-safety exclusions (Copy family /
  generic methods / associated types), vtable teardown through Box.
  Opaque/static counterpart PUNTED — provisional future keyword
  **`generic`** (user preference; return-position reverse-generics
  nuance recorded in design 51). A1b (executor consumer) follows
  design 51. `dyn` keyword reservation retired. [45 report, 18, 51]
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

- **F1.** `Allocator` trait + `Global` — LANDED (brief 28, `b516e2c`):
  std/alloc.saw, alignof<T>(), all stdlib allocation through Global
  (zero-cost verified in IR), placement-write contract documented,
  try_with_capacity fallible factory + AllocError. Stage 4 (F2) next
  when scheduled. [19, 28]
- **F2.** ~~Default type parameters~~ — LANDED (brief 37): `= Default`
  in type-param lists, defaults filled before mangling (one identity:
  `Vector<Int>` ≡ `Vector<Int, Global>`), `A` public on Vector AND Map,
  LoudAlloc dispatch proof, cross-allocator type distinctness tested.
  Remaining stage-4 tail: slabs (F3) + statics (F4). [19, 37]
- **F3.** ~~Slab allocators~~ — LANDED (brief 42): `std/slab.saw` CAS
  bump + LIFO free-list over caller statics; `Box<T, A = Global>` with
  placement-move factories (`Box<T>.make`/`make_or`); kernel idiom
  proven to exhaustion and reclaim; freestanding-verified. Enabling:
  conditional-move DROP FLAGS (fixed a pre-existing branch-move leak),
  `&T`→pointer / pointer↔Int casts. `AllocatedBy` sugar stays deferred
  per paper 19. [19, 42]
- **M4.** No user-facing `panic(message)` builtin — MakeBox's OOM panic
  reuses the force-unwrap message; old TODO.md wanted panic/assert too.
  Small, worth shipping with proper message plumbing. [42 report]
- **F4.** ~~Module-level statics~~ — LANDED (brief 41): decided
  semantics enforced (Sync-only, const-init, immortal, no static mut,
  interior mutability via methods), zero-init BSS arrays, minimal
  `Atomic<Int>` (seq_cst load/store/fetch_add/CAS), freestanding
  .rodata/.bss verified. Also fixed L13 (UInt udiv/urem). [19, 41]
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
- **D11 (async lowering path) — DECIDED Jul 29 (user): SOURCE-LEVEL
  transform (path B)**, AST-level formulation (frame = ordinary Saw
  struct compiled by the proven deinit/containment/drop-flag
  machinery); driven by .bss static task frames (kernels/embedded
  first) + self-hosting portability (no LLVM-middle-end semantics
  coupling). LLVM probe scripts retained as reference. PLUS the
  **no-forced-destroy ruling** (recorded in paper 18): no Task.kill;
  frames die only via their own control flow — deletes
  per-suspension-point destroy paths from the transform. [18, 43]
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
