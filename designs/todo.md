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
- **D14 → design 48 — LANDED** (`ea3021b`): Comparable (opt-in,
  Ordering enum, synthesized lexicographic), Hashable (mirrors
  Equatable, FNV-1a Hasher), Vector.sort/sort_by (both need `T: Copy`),
  HashMap<K,V,A> (open-addressing/linear-probe/tombstone, NoCopy). [HashMap
  later RENAMED → Map and the Vector-backed Map RETIRED by design 54.]
  Note: brief 49's original commit was lost
  and recommitted (`307f9e4`) alongside 48 — see handoff.md.
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
- **N1–N3 → design 56 — LANDED**: trait default method bodies
  (per-conformer synthesis from a deep-copied body, override-or-inherit,
  calls-required-dispatch-to-conformer, through trait inheritance, `any`
  vtable slot, effects per instantiation, missing-no-default still errors);
  **Printable** (streaming `format` + default-body `to_string`; builtin
  conformance for integers/Float/Bool/String rendered inline, NO
  synthesis; interpolation + `print` accept Printable, builtins stay
  byte-identical; `T: Printable` bound); `trait Error: Printable {}` (both
  conformance spellings, object-safe/any-able); erased Results FULL
  (`Result<T, Box<any Error>>` return type, auto-erase at all three return
  checkpoints via `ErasedErrWrap`, `try` re-box + passthrough, `Err(e)`/
  `catch` bind the box with `{e}` via vtable). Boxing uses Global (hosted;
  freestanding keeps concrete/union errors — spec note added).
  Choices/deferrals: NO Debug trait (own design); **enum-direct Printable
  deferred** (enum method dispatch is a general missing feature — enum data
  is rendered through a Printable wrapper struct's `format`); erased-error
  **downcasting deferred** (needs a type-id design). Enablers landed
  alongside: `&var` re-borrow of a mutable-reference param; cross-module
  `type_conforms_to`. Blade dogfood: manifest errors migrated to
  `Result<Manifest, Box<any Error>>` (ManifestError auto-erase + TomlError
  `try` re-box), new `blade/tests/erased_manifest_error.saw`. Compiler suite
  568 passing, 0 xfails. [App-1]
- **N4/N5/N7 → design 57 — LANDED** (`designs/57-blade-enablers.md`):
  HashMap iteration (visitors each/each_key/each_value + snapshots
  keys()/values(), old Map skipped); String.to_int()/to_int(radix:)/
  to_float() -> Optional; DF3 call-site optional auto-wrap; std.time;
  extension Int/Float. Compiler suite 587, 0 xfails. Choices/deferrals:
  * **Visitor element passing:** BY VALUE via the same whole-slot copy
    path get/_get_value use (the brief's "by value" fallback) — per-
    category by-reference (&K/&V for ExplicitCopy/NoCopy) is not
    expressible yet (no by-ref projection into an enum payload inside a
    vector slot), so visitors work for any K/V that get already supports
    (trivial + ImplicitCopy, e.g. Int/String; payload-free enum values).
    Snapshots keys()/values() are K: Copy / V: Copy bounded; no entries()
    (deferred). HashMap order is unspecified (table order; sort keys() for
    determinism).
  * **to_float precision:** naive accumulation (NOT correctly-rounded
    strtod — last-ULP may differ); exponent accumulator clamped so it
    can't overflow. to_int accumulates as a non-positive magnitude with
    wrapping-op + divide-back overflow detection (portable, no Int.max
    constant; Int.min round-trips). radix is a design-55 overload.
  * **DF3 payload scope:** all call forms + init + enum-payload construction
    covered (the memberwise struct-field path already wrapped via LLVM
    shape-matching). One level only (`T??` is unspellable anyway; an
    already-optional argument is passed through, never re-wrapped). Bare
    `None` call arguments now annotated (were untyped). See DF3 ledger.
  * **std.time:** hosted-only (added to HOSTED_STD_MODULES). Two compiler
    clock shims (saw_clock_monotonic_nanos / saw_unix_timestamp_secs) keep
    the timespec layout + macOS(6)/Linux(1) CLOCK_MONOTONIC variance inside
    codegen. Duration.format uses early-returns (a void if/else-chain in
    tail position emits an invalid void phi — worked around).
  * **Int/Float extensions** required NEW primitive-extension infra:
    registered Int/Float as pseudo-structs (like String) and generalized
    the String-only self-type / method-dispatch spots to a primitive map
    across typechecker + codegen. Int.abs panics on Int.min; Int.pow checked
    (negative exp panics); Float via libm (fabs/floor/ceil/round/sqrt/
    fmin/fmax), IEEE NaN. Survey: no hand-rolled abs/min/max in Blade.
    KNOWN LIMITATION: match-expression inside a Void-returning closure
    ICEs (void phi) — pre-existing, sidestepped in the enum-value test.
  * **Blade dogfood:** toml.saw int_value()/get_int() (to_int); tester.saw
    Instant/Duration timing + HashMap failed-name tally sorted via keys();
    blade tests toml_int_value.saw + df3_map_time.saw. [App-1]
- **N6 → design 58 — LANDED**: Swift-style `@attr` grammar (v1: top-level
  func/static only; unknown/dup/bad-arity/wrong-position all clean errors);
  unified `@export`/`@export("sym")` = C calling convention + unmangled/named
  symbol + external linkage + DCE-survival via `@llvm.used` (verified at the
  DEFAULT -O1 pipeline). Restrictions: non-generic, effect-`sync` (export is an
  effect ROOT like `main`, marked in effects.py), C-safe signature whitelist
  (fixed-width ints, Int/UInt, Float, UnsafePointer<T>, Void/Never return —
  `Never` now spellable, lowered `void`+noreturn = the `_start` shape). NO
  repr(C): the decl-order natural-ABI layout is documented as THE struct layout
  rule (spec §Structs + §UnsafeMemory updated). `@export` statics relax to
  arrays/structs of whitelisted fields; the vector-table idiom
  (`@export("_vectors") @section(".vector_table") static VECTORS: [UInt32; 64]`)
  is verified on an ELF target. `@section` on funcs/statics (composes with
  @export). Symbol hygiene: dup export symbol / `main`/`saw_*`/`__saw_*`
  collision = error; overloaded name may `@export` only ONE overload w/o an
  explicit symbol. Choices/deferrals:
  * **Bool VERDICT — REJECTED in v1.** The extern-IMPORT path lowers Bool as a
    bare `i1` (no zeroext/i8 normalization), which does not match the platform
    C `_Bool` ABI, and NO stdlib extern actually passes a Bool, so there is no
    sound precedent to mirror. Symmetric: neither side has a validated Bool ABI.
  * **Testing:** in-binary round trip preferred (an `extern "C"` decl of an
    `@export`ed symbol in the same unit UNIFIES with the definition via bodyless-
    decl reuse — no C compiler, no separate module needed). Committed run-tests
    use mach-o `SEG,sect` section names (ELF `.foo` names crash mach-o object
    emission on the host); ELF section names + the vector-table idiom + noreturn
    + `@llvm.used` at -O1 are verified via `--emit-ir` scratch probes and were
    all confirmed. The test harness has no per-test flag/emit-ir directive.
  * **`@inline` deferred** (grammar makes it trivial later).
  Compiler suite 607, 0 xfails. **Unblocks F7** (kernel entry symbol / vector
  table — the export machinery is ready; the boot shim stays assembly). [App-2]

### NICE TO HAVE — TRIAGED Jul 29 (user, one-by-one)
**ADD before apps** (→ briefs 53/54, both now WRITTEN + DECIDED Jul 29):
- **Design 53 "ergonomics" — LANDED**: default params (trailing-only,
  arbitrary exprs per-call through the value-transfer checkpoint, no
  other-param/self refs, effects flow through, DECL-SITE shape-expansion
  rejection extending design-55's `_overload_sig_key`; free funcs +
  methods + inits); `..=` (dedicated Int.max-safe RangeInclusive, no b+1
  desugar); `vec.enumerated()` + `each_indexed` (concrete (Int,T)
  iterator/closure); `Int.max`/`.min` + `.max`/`.min` on all fixed-width
  types + UInt; Rust-style literal suffixes (`255u8`/`0xFF_u8`, exact-
  typed, range-checked at the literal — closes 47's riscv32 gap; distinct
  fixed-width kinds no longer implicitly convert); `\u{}` escapes (scalar-
  validated at lex, UTF-8 encoded); import aliasing (module `as` + per-
  symbol `as`, local renames, dup-local error); `static_assert` (const-
  eval at codegen — exact sizeof/alignof — clean compile error on
  fail/non-const, zero codegen on pass); **DF1 `let _` discard CLOSED**
  (true discard: move-consuming, immediate drop, no binding, `var _`
  error). **use-before-init VERDICT (Part 7): structurally impossible** —
  every `let`/`var` requires an initializer (uninitialized decl is a parse
  error), so no definite-init analysis is needed; documented in the spec,
  no code. Compiler suite 640 → docs commit, 0 xfails. [ergonomics]
- **Design 54 "collections" — LANDED**: **Map UNIFICATION** — the
  Vector-backed Map RETIRED, HashMap renamed → Map (one hash dictionary;
  the Map-deprecation open decision is **CLOSED**; the name `HashMap` no
  longer resolves; unspecified order documented; old Map's copy() not
  carried over — ExplicitCopy is future work). **Set<T>** (core + algebra:
  union/intersection/difference/is_subset/is_superset) — implemented as a
  **wrapper over `Map<T, SetMark>`** (probed: the zero-field unit value
  works cleanly; chosen over a parallel open-addressing rewrite). Algebra
  bound is `T: Copy` (even membership-only ops read elements by value — the
  57-snapshot limit). **Collection literals** per the closure rule:
  `{k: v}` map / `{a, b}` set / `{:}` empty map; `{}`, `{expr}`,
  `{ x in ... }` are ALWAYS closures (Set<T>()/Set.of(x) for empty/single);
  duplicate keys last-wins; bounded parser lookahead, no type feedback.
  **Context-driven Vector literals** (`[1,2,3]` / `[]` build a Vector when
  the expected type is `Vector<T,A>`; array default byte-identical).
  Enablers landed: method calls on a `&T` reference-param receiver (was an
  ICE); `_generate_enum_init` substitutes type args against the active
  monomorphization context (a generic-enum sizing bug exposed by Set and
  Map coexisting). Compiler suite 661, 0 xfails. Known pre-existing (NOT
  54): `Map`/`Vector` with a *custom* allocator leaks its buffer on deinit
  (reproduces with explicit construction; design 37/48 territory). [both apps]

**DEFERRED** (user, Jul 29): slices (needs own design vs no-escape
refs); `\x` byte escapes; where clauses; extension sugar (computed
properties, conditional extensions); submodule directories; std.io
traits (post-N1, Blade-driven).

**PROMOTED/DROPPED (second pass, Jul 29):**
- **Overloading beyond init — LANDED (design 55, exact-match model).**
  Namespace overload sets (functions + methods), `_resolve_overload` with
  the pinned tie-breaks (exact>optional-wrap; before Result/optional
  auto-wrap; concrete>generic — generic competes only with explicit
  call-site type args, no inference), decl-site distinctness check
  (post-alias, bare type params folded), `$OL$` type-signature mangling
  stamped on symbol + AST node, single-chokepoint (value-transfer / effects
  / exclusivity all key on the resolved callee; per-overload effect nodes).
  All four call forms (free/method/static/module). 12 example tests. Choices
  made: `append_int` REMOVED (absorbed into `append(Int)` overload, one
  example migrated); init keeps its existing name-based mangling (untouched —
  it did not fall out to unify cleanly, and init resolution is param-name
  based, orthogonal to the type-signature scheme). DEFERRED (noted in code):
  overloaded GENERIC methods (method-level type-arg folding), overloading
  across SPECIALIZED extensions, and nested-generic decl-site keys
  (top-level type-param folding only). `append_char` left separate on
  purpose (unifying Int8 into `append` would make `append(<int literal>)`
  ambiguous with `append(Int)`).
- **`loop` and `ref` keywords — DROPPED (design 55 doc item, LANDED).** Neither
  was ever a compiler keyword, so the removal was spec-only: dropped from
  Appendix A's reserved list + all `loop { }` spec mentions (`while {}` is the
  idiom). **`do` and `defer` KEPT reserved.**
- **Unsafe blocks — DROPPED by principle (design 55 doc item, LANDED):**
  spec Unsafe Code section rewritten around "unsafety is type-carried, not
  region-carried" (the Unsafe type prefix IS the model; no unsafe
  blocks/func/trait; `unsafe` keyword stays reserved costlessly).

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

## BLADE DOGFOOD FINDINGS (brief 49, Jul 29 — feed N-family / small fixes)
- **DF1 — LANDED (design 53 Part 8).** `let _` is now a true discard:
  evaluates the RHS, consumes it as final owner (move for NoCopy), drops
  it immediately at statement end, binds nothing; two `let _` never
  collide; `_` unreadable; `var _` is an error. Destructuring/param
  discards deferred (no tuple-destructuring `let` yet).
- **DF2 — LANDED (design 59 A).** `Command`/`system()`/`.run()`/
  `.output()` divided wait status by 256, discarding signal-death info —
  a SIGABRT (failed assert/panic), when /bin/sh execs the command and is
  killed, left a raw WIFSIGNALED status with a zero exit byte, so `/256`
  read exit 0 = success. Fixed with one `decode_wait_status(Int32)` helper
  (std/process.saw) used by BOTH run() and output()/pclose: normal exit ->
  0..255 byte; signal death -> 128 + signum (shell convention); stop/other
  -> nonzero; result is 0 only for a genuine exit-0. `blade test` already
  compared the raw status to exactly 0 (correct), so it is unaffected.
  Proving test: examples/process_signal_death.saw (`kill -ABRT $$` reports
  nonzero, normal exit 3 preserved).
- **DF3 — LANDED (design 57 Part 3).** Call-site `T -> T?` optional
  auto-wrap. One level only (`Int -> Int?`; `Int -> Int??` is moot —
  `T??` is unspellable in the type grammar; an already-optional argument
  is passed through, never re-wrapped). Ordered AFTER overload resolution
  (design 55 rule 1 "exact beats optional-wrap" holds: `f(5)` picks
  `f(Int)` over `f(Int?)`). NOT through a generic-instantiation boundary
  (`id<Int?>(5)` is an error — explicit optional required). Move/copy
  rules unchanged (the wrap consumes the argument exactly as `Some(x)`
  would; NoCopy payload moves in, dropped once). All call forms + init +
  enum-payload covered. Impl: typechecker `_arg_type_ok` records a
  `autowrap_to_optional` flag on the argument node (generic boundary via
  `_df3_allow_wrap`); codegen `_maybe_autowrap_optional` builds the
  `{i1 1, T}` optional at the argument edge in `_gen_transfer_value`
  (struct memberwise init already wrapped via LLVM shape-matching). Also
  fixed: a bare `None` call argument is now annotated with the concrete
  optional type (was untyped before).
- **DF4.** Blade bit-rot: needed `guard var` (was `guard let` + &var
  method) and `move` for Data/Vector args — expected migration, not a
  bug, but Blade needs periodic re-validation as the compiler tightens.
- **DF5.** `extension` (and other keywords) can't be identifiers —
  expected; noted for the eventual contextual-keyword sweep.

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
- **L14 (design 59 E, DISCOVERED — DEFERRED).** Owning **enum-payload**
  container elements are not dropped on container deinit: a
  `Vector<enum-with-owning-payload>` (and hence `Map<K, owning V>`, whose
  slots are `Vector<MapSlot>`) drops nothing for its `Occupied` payloads
  because the element type reaches the drop glue kind-tagged STRUCT (the
  type-arg default), so the enum drop path is never selected. A direct
  `Vector<Struct>` drops correctly; only enum payloads leak. A codegen
  re-tag of the element type to ENUM in the cleanup path fixes plain-insert
  Map value deinit — BUT it exposes L15 (turns that leak into a
  double-free in the literal path), so it was reverted here and both need
  a joint fix. Probe: `.build/scratch/vec_elem_deinit.saw`
  (Vector<Struct>=2 drops, Vector<enum>=0). [59 E investigation]
- **L15 (design 59 E, DISCOVERED — DEFERRED).** A collection **literal**
  bound to a value with owning elements has a tmp/`m` ownership-handoff
  bug: the literal builds into a temp and returns `load(tmp_ptr)` (a
  bitwise copy of the NoCopy container), so the temp and the binding alias
  the same buffer. With element drop glue active this double-frees the
  owning elements (behaviour is monomorphization-order / allocator
  dependent — masked as a leak while L14 suppresses element drops). The
  narrow E1 fix (drop the discarded insert-return) is unaffected and
  correct. Probe: `.build/scratch/e1_ca.saw` (3 values created,
  4–5 deinits with element drops on). [59 E investigation]

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

- **A1.** Stage 2 async — TRANSFORM FULLY COMPLETE: straight-line +
  nested calls + methods (44/45) AND control-flow suspension (52 Part
  0: CFG-walk state machine — while/for-range/if/match/break/continue,
  arbitrary nesting; honest rejections: for-over-iterable suspension,
  value-producing break from suspending loops, move in spanning
  conditions). Single-task runtime landed (45). **Remaining: A1b =
  brief 52b (in flight)** — TaskGroup-owned run queue (the C1 nursery
  model; group Deinit runs the executor = structured join via LIFO),
  spawn/TaskHandle/cancel/suspending-channel, on design 51's validated
  erasure. Soundness catches en route: datalayout offsets (45),
  struct-init optional wrap + if-let move-out double-free (52).
  Generic driven functions still blocked on A5. [44, 45, 52, 52b]
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
- **F7.** Custom entry symbols (`_start` / vector table) — UNBLOCKED by design
  58: `@export("_start")`/`@section` + `Never` return (noreturn) + exported
  vector-table statics are the mechanism. Remaining F7 work is the boot shim
  (stack setup, stays assembly) + wiring, not compiler surface. [20, 58]
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
