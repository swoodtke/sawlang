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
  safety hole; panic machinery exists). — LANDED (design 63).
- T1c. Ordering + hashing: Comparable/Ord + sort, Hash + real HashMap
  (Map is Vector-backed linear scan) — needs D13/D14 shapes decided.
- T1d. Pattern-matching completion: literal/range patterns, guards,
  tuple destructuring. — LANDED (design 63; + distinct-type cast + named
  tuple fields).
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

## Design 67 — Blade dogfood bug batch (DF6–DF12)

In progress (interruption-safe: one DF per commit). Progress log (newest last):
- **DF12 LANDED** — root cause was NOT a bounds/overflow (ASan clean 60+) nor
  uninitialized memory (calloc-zeroing the heap didn't help): a **String
  refcount double-release**. An aggregate that OWNS a refcounted (`String`/`Arc`)
  payload was BITWISE-copied without a retain, yet still RELEASED that payload at
  every drop — so a shared `String` was freed once per copy, corrupting the
  allocator free list (intermittent SIGBUS/SIGTRAP; deterministic under
  `libgmalloc` as `__saw_string_release` reading a freed header; the
  "deterministic-with-a-pipe" variant was the same corruption under the pipe's
  allocation pattern). Two shapes:
  (a) an **enum with an owning payload** (`DepSource { PathDep(String) }`) —
  enums can't DECLARE ImplicitCopy, so their copy tier is structural, and the
  value-transfer checkpoint classified them as neither move-gated nor
  ImplicitCopy → free bitwise copy. Fix: `Namespace.is_implicit_copy_enum`
  (structural: owning + every payload cleanly retainable), wired into the
  typechecker checkpoint (marks `needs_copy`) and codegen `_get_cleanup_behavior`
  (→ `implicit_copy`), kept OUT of `_is_implicit_copy_type` so it doesn't force a
  containing struct to opt in (an owning-enum field is compiler-handled like a
  `String` field). Plus: a `match` arm result now routes through
  `_gen_transfer_value` so an extracted owning payload (`case Path(d) -> d`) is
  retained (the consume-mode arm cleanup releases the same binding).
  (b) a **struct-with-String read out of a CONTAINING struct's field**
  (`root.root_dir`, a `Path`) passed by value — `_transfer_needs_copy` retained
  an owning aggregate read out of an INDEXED slot (design 65 L17) but not out of
  a struct FIELD / tuple element; same rationale (the container keeps ownership,
  the projection is a duplication). Fix: extend that clause to
  `MemberAccess`/`TupleIndex`. Regression: `examples/owning_aggregate_copy.saw`.
  DF11 fell out for free (the corruption was what made the cross-module
  `dependencies()` in `manifest_deps_hash` intermittently take the Err branch →
  `manifest_hash = "0"`; now a stable real hash — to be confirmed + lock updated
  at the DF11 step). Suite 765 -> 766; blade tests 16 green; bootstrap green with
  the DF12 retry/redirect workaround REMOVED.
- **DF10 LANDED** — a `match` whose result type is optional (`T?`) with a bare-`T`
  value arm and a `None` arm ICE'd codegen (phi mixed a bare `ptr` with the
  `None` arm's `{i1, ptr}` -> LLVM verifier error). Fix:
  `_reconcile_optional_arms` in the typechecker detects arms mixing `T?`/`None`
  with a bare `T`, wraps each bare non-None arm in `OptionalWrap` (value + block
  tails), and reconciles the match to `T?` — the mirror of the existing Result
  auto-wrap. Regression: `examples/match_arm_optional_wrap.saw`. Suite 766 -> 767.
  (Blade's `path_dir`/`is_git_source` split-helper workaround left in place; it's
  harmless and a single `-> String?` merge isn't required.)
- **DF8 LANDED** — a function/method whose body is an if/else where BOTH arms
  `return` leaves a degenerate, unreachable fallthrough block; codegen emitted
  `ret ir.Constant(<returnType>, 0)` there, and `0` is not a valid AGGREGATE
  constant payload (struct/enum/optional/array/tuple) -> llvmlite `format_constant`
  ICE ("'int' object is not iterable") at `ret` emission. NOTE: the trigger is the
  2-branch return of ANY aggregate, not specifically a nested-struct field (the
  original ledger over-narrowed it). Fix: emit `ir.Undefined` of the return type on
  that unreachable path (functions, methods, closures — the three parallel sites).
  Regression: `examples/return_struct_from_branches.saw`. Suite 767 -> 768.
- **DF7 LANDED** — an `if let` whose branches produce a VOID value (a call to a
  user function returning Void — which, unlike `print`, yields a NON-None void
  value) reached the result-capturing path and allocated a Void stack slot,
  asserting in llvmlite ("not isinstance(pointee, VoidType)"). Precise trigger:
  a void USER-function-call branch tail (not the ledger's `{ return }`, which
  terminates the block -> None and was already safe). Fix: normalize a Void
  branch value to None in `_generate_if_let_expression`, mirroring the Void
  contract `_generate_if_expression` already enforces. Regression:
  `examples/if_let_void_branches.saw`. Suite 768 -> 769.
- **DF6 — (a) FIXED + locked; (b) RE-LEDGERED (still open).** Symptom (a) — the
  arity-1/arity-2 default-type-arg mangling divergence for a `Vector<T>` nested in
  an erased `Result` (`KeyError: Result$…Vector$1$…`) — no longer reproduces:
  defaults fill consistently before mangling (all `Vector$2$…$Global`), and a
  single- OR multi-module `Result<Vector<Dependency>, Box<any Error>>` compiles and
  runs correctly. Locked with `examples/vector_in_erased_result.saw`. Symptom (b) —
  a `Vector<Dependency>` element read confused with another Vector monomorphization
  — STILL reproduces IN THE FULL BLADE BUILD ONLY. Probed the un-work-around
  (reverted blade's columnar `DepList` to hold `Vector<Dependency>`): it ICEs
  `Cannot find field name in struct with type i8` at the resolver's
  `try visit(d.name, …)` — `d` from `guard let d = deps.get(i)` is codegen-typed
  `i8` (a `Vector<Dependency>.get` monomorphization collision, likely with a
  `Vector<Bool>`/byte-vector in blade's type set). Faithful ISOLATED repros —
  cross-module `Vector<Dependency>` in an erased Result, a `DepList`-style wrapper
  struct with `get()` forwarding, AND the `DepSource` owning-enum field — all
  compile and run fine, so (b) is specific to blade's full type population and NOT
  reproducible in isolation. Columnar `Vector<String>` workaround RETAINED; (b)
  needs its own investigation (a monomorphization name-collision / element-type
  tracking bug, distinct from the DF12 corruption). Suite 769 -> 770 (test only;
  no compiler edit for DF6).
- **DF11 LANDED (fixed by DF12).** `manifest_deps_hash` returned "0" in the FULL
  build flow because the second cross-module `Manifest.dependencies()` call
  (after `resolve` already made one) intermittently took the Err branch — that
  was the DF12 owning-copy heap corruption, not a distinct bug. With DF12 fixed,
  `blade build` now writes a STABLE, non-zero `manifest_hash` (verified identical
  — `1317565583076547404` — across 5 consecutive fresh builds), so drift
  detection is no longer degraded. Regenerated the committed `blade/Saw.lock`
  (`manifest_hash "0"` -> the real hash). The existing `blade/tests/lock_drift.saw`
  already asserts non-zero + stable + drift-detected (it passed pre-fix because the
  small single-purpose test binary didn't allocate enough to corrupt); no new test
  needed. No compiler edit.

## Design 64 — Blade for real (deps/semver/lock/git/incremental/self-host)

In progress. Commit units B0..B8 landed one at a time (interruption-safe).
Progress log (newest last):
- B0 landed: sawc `--module-path NAME=DIR` (repeatable; precedence exact
  std > mapped > file-relative; mapped-shadows-local = error). Threaded
  through compile/emit-ir paths. Test runner gained a `// COMPILE-FLAGS:`
  directive (`{TESTDIR}` placeholder). 3 fixtures (lib/submodule/shadow).
  Suite 761 -> 764.
- B1 landed: TOML inline tables (`k = { a = "1", ... }`, one level) in
  libs/toml (blade/src/toml.saw) + `TomlSection.is_table/table_value/names`;
  manifest `[dependencies]` schema (`DepSource` Path/Git, `Dependency`,
  columnar `DepList`) + `Manifest.dependencies()` (erased Result) rejecting a
  bare version dep ("no registry yet"), both-sources, and no-source. Fixed a
  real compiler bug in passing (see DF6). Suite 764 -> 765; blade tests 6 -> 9.
- B2 landed: `libs/semver/` real package (Saw.toml `name = "semver"` +
  `src/lib.saw`). `Version` (MAJOR.MINOR.PATCH; Equatable auto + Comparable via
  empty-body synthesis = lexicographic + Printable), `parse_version`
  (pre-release/build-metadata parse-rejected); `VersionReq`
  (Exact/Caret/Tilde/AtLeast) + `parse_req` (bare = exact pin) + `matches` (0.x
  caret rule) + Printable. 4 blade tests in libs/semver/tests
  (parse/compare/match/print) green. Hit + worked around DF8. Suite 765
  (unchanged; no compiler edit).
- B3 landed: `blade/src/resolver.saw` — transitive path-dependency graph,
  one-version-per-name, source-identity (path normalization) two-sources error,
  cycle + self-dep errors (cycle-before-dedup), and version-requirement
  validation naming EVERY requirer on conflict. Columnar `Resolution`/`ReqList`
  (String vectors). 5 blade tests + fixtures (simple/chain/conflict/cycle/
  twosrc). IMPORTANT: could NOT `import` the external semver package (DF9);
  resolver uses a self-contained minimal matcher instead. Suite 765 (no compiler
  edit).
- B5 landed: `blade/src/git.saw` — `git ls-remote --tags` parsing (leading-`v`,
  peeled `^{}` commit-sha preference, semver-only tags) into (version, tag, rev)
  candidates; `ls_remote_tags`/`clone_tag`/`checkout_rev` (Command.output/run).
  Wired into the resolver: a git dep is resolved by highest satisfying tag,
  cloned into `.blade/deps/<name>-<version>/` (self-gitignoring `.blade/`), and
  recorded with kind "git" + rev. 3 blade tests: git_parse (pure), git_local_repo
  and git_resolve (local file:// repos built in .build/scratch via system() — no
  network). Blade tests 14 -> 17. Suite 765 (no compiler edit).
- B4 landed: `blade/src/lock.saw` — deterministic Saw.lock (sorted [pkg.<name>]
  sections, no timestamps -> byte-identical), `serialize`/`write_lock`/
  `parse_lock`, and a manifest-deps `manifest_hash` (djb2, wrapping) with
  `lock_is_current` drift detection. toml module gained `TomlDoc.section_names`.
  2 blade tests (lock_roundtrip incl. byte-identical + write; lock_drift). Blade
  tests 17 -> 19. Suite 765. (Build-honoring/`blade update` orchestration is B6.)
- B6 landed: `blade build` runs the full pipeline — resolve (write Saw.lock),
  compile the root with one `--module-path <name>=<checkout>/src` per resolved
  dep (B0), and content-hash build avoidance in `.blade/build-hash` ("up to
  date"; `--force` bypasses). Honours a `SAWC` override. `blade test` uses the
  same dep flags (tester.dep_flags). `blade build --force` via cli/main. Fixed
  normalize_path to preserve a leading `/` (absolute manifest roots). New
  self-contained blade test `dep_build` (resolve -> module-path -> compile ->
  run on the buildapp fixture); end-to-end build/avoidance/force verified by
  .build/scratch/run_build_e2e.py. Blade tests 19 -> 20. Suite 765. Next: B7
  (CLI add/tree/timing) + B8 (self-hosting — but see DF9: importing the external
  semver package is compiler-blocked, so B8's blade-depends-on-semver plan needs
  a compiler fix first).
- B7 landed: CLI polish — `blade tree` (prints the resolved graph: name version
  (kind: loc)), `blade add <name> --path <dir> | --git <url> [--version <req>]`
  (appends to Saw.toml [dependencies], re-resolves + writes lock), and per-test
  timing in `blade test` output (`... ok (Nms)` via std.time Duration). Verified
  via .build/scratch/run_tree_add.py. Blade tests 20 (timing added). Suite 765.
- B8 LANDED — design 64 COMPLETE. Re-probed DF9: a cross-package erased-`try`
  re-box + `{e}` interpolation actually WORK in isolation (DF9 was a narrower
  combination), so the toml extraction is viable. Extracted `libs/toml` (real
  package + own `blade test` suite: toml_parsing/int_value/missing_section/
  inline_table); Blade's manifest+lock now `import toml` (external), Blade's
  Saw.toml depends on it by PATH, blade/src/toml.saw deleted. Added a portable
  `declared` source column to Resolution so the committed `Saw.lock` records the
  relative path (`../libs/toml`), not an abs dir. Bootstrap loop
  (`tools/blade_bootstrap.py` + `make blade-bootstrap`): stage0 (sawc builds
  blade) -> stage1 (blade builds blade through its own pipeline) -> stage1 test
  16 green -> second build up-to-date -> --force -> stage2 test 16 green. Blade
  tests 16 + libs/toml 4 + libs/semver 4. Suite 765. Docs: README Blade section,
  TESTING.md bootstrap. **App-1 (Blade) milestone: real package manager done.**
  Deferred: libs/semver is NOT a blade dep (the resolver is self-contained; a
  full re-attempt to import semver into blade is future work).

### Dogfood findings — design 64 (Blade)
- **DF-GlobConf — FIXED (this brief, `typechecker/core.py`).** A glob import
  (`import foo.*`) or specific import copied a public struct/enum symbol into
  the importing namespace but NOT its trait conformances, and the glob path
  does not register the source module in `ns.modules` — so a containment/
  conformance query in the importer (e.g. "does DepList implement NoCopy?")
  saw the copied struct as non-conforming and wrongly errored. Fix: propagate
  conformances alongside imported struct/enum symbols. Regression test
  `examples/glob_import_conformance.saw` (would fail pre-fix).
- **DF6 (RECORDED, worked around) — generic-with-default-type-param mangling
  divergence.** Two symptoms, one root cause: nested generic default type args
  (`Vector<T>` -> `Vector<T, Global>`) are NOT filled consistently, so
  `mangle_type` produces `Vector$1$T` in some paths and `Vector$2$T$Global` in
  others. (a) `Result<Vector<T>, Box<any Error>>` as a return type ICEs on the
  err-return path (`KeyError: Result$2$Vector$1$Dependency$...` — the Result
  enum was registered under the arity-2 name). (b) In the full multi-module
  Blade build, a `Vector<Dependency>` element extraction is confused with
  another Vector monomorphization (a `Dependency` read back as `TomlValue`).
  Blade workaround: `DepList` stores columnar `Vector<String>` (consistently
  mangled) and reconstructs `Dependency` on `get(i)` — no `Vector<user-struct>`
  as a Result Ok type or across the module boundary. Proper fix (recursive
  default-type-arg filling before mangling) deferred — flagged for a compiler
  brief.
- **DF7 (RECORDED, worked around) — `if let x = opt { return ... }` in
  statement position ICEs codegen** ("assert not isinstance(pointee,
  VoidType)" — `_generate_if_let_expression` allocas the Void-typed branch
  result). Hit writing the dependency validation; restructured to unwrap with
  `?? ""` sentinels + plain `if`. Proper fix: treat a value-less/diverging
  if-let body as a statement (no result alloca).
- **DF8 (RECORDED, worked around) — returning a struct-literal with a
  NESTED-STRUCT field from 2+ branches ICEs codegen** ("'int' object is not
  iterable" in llvmlite's aggregate `format_constant` at `ret` emission). A
  `struct Wrap { version: Version }` with `if c { return Wrap(version: v) }
  else { return Wrap(version: v) }` builds a malformed aggregate CONSTANT for
  the returned value (a nested-struct field set to a scalar). A SINGLE
  construction/return is fine. Hit in semver `parse_req`; worked around by
  selecting the operator into a `var` and constructing `VersionReq` exactly
  once at the end. Proper fix: the struct-literal codegen must not fold a
  literal with non-constant (SSA) nested-aggregate fields into an ir.Constant.
- **DF9 (RECORDED, worked around) — BLADE CANNOT IMPORT THE EXTERNAL semver
  PACKAGE (blocks B8 as written).** Writing the resolver to `import semver`
  (libs/semver via `--module-path`) and use its `Version`/`VersionReq` ICE'd the
  compiler THREE distinct ways: (a) a cross-module erased-`try` re-box inserting
  a `SemverError` into `Box<any Error>` ("Can only insert {i8*,i8*}..."); (b) an
  erased-error `{e}` interpolation dispatching an existential method
  ("Can't index at [1] in SemverError"); (c) receiver-type confusion — a
  `Manifest` value read back as `semver.Version` ("Undefined method:
  Version.version"). These are the same cross-module monomorphization/mangling
  family as DF6, amplified by a second package's type population. NET: a Saw
  program importing an external, generic/error-heavy package is not yet viable,
  so **B8's "blade depends on semver + toml by path" plan is compiler-blocked**.
  Workaround: the resolver uses a self-contained minimal version matcher;
  libs/semver stays a standalone, tested package. Needs a compiler brief
  (likely the DF6 recursive-default-type-arg-filling fix) before B8.
- **DF10 (RECORDED, worked around) — an optional produced in a MATCH ARM that is
  also the function result is not wrapped.** `func f(...) -> String? { match x {
  case A(s) -> s, case B(_) -> None } }` emits a phi mixing a bare `ptr` (the
  unwrapped `s`) and `{i1,ptr}` (None) -> LLVM verifier error. Worked around by
  splitting into non-optional helpers (return `""` + a separate bool). Proper
  fix: coerce a non-optional match-arm value to the function's optional result
  type (the DF3 auto-wrap, extended to match-arm-return position).
- **DF9 UPDATE — largely a FALSE ALARM.** The cross-package erased-`try` re-box
  and `{e}` interpolation ICEs I attributed to any external-package import were
  actually a NARROWER combination (semver's generic `Version` + the resolver's
  multi-error mix). In isolation both work (verified), and the `libs/toml`
  extraction — an external package whose `TomlError` is erased and `try`-boxed
  across the boundary by Blade — compiles and runs fine (B8). The resolver still
  keeps its self-contained matcher; re-importing semver into blade is untried.
- **DF11 (RECORDED) — `manifest_deps_hash` returns "0" in the build flow.** When
  `lock.saw`'s `manifest_deps_hash` calls `Manifest.dependencies()` inside the
  full Blade build (after `resolve` already called it), it takes the `Err`
  branch, so the committed `Saw.lock` has `manifest_hash = "0"`. Same
  cross-module class as DF6/DF9(c) (a second cross-module call returning wrong).
  Non-fatal: the value is self-consistent (stable across machines/runs), so the
  lock is stable, but drift detection is degraded (always "0"). Needs a compiler
  fix to the cross-module method-call path.
- **DF12 (RECORDED, worked around) — Blade's self-build intermittently crashes
  (SIGBUS/SIGTRAP), and crashes deterministically when its stdout is a PIPE.**
  `blade build` on the large Blade program hits a nondeterministic memory
  corruption (observed rc 138/0/133 across identical runs) — a Saw runtime bug
  in a large program. Separately, driving `blade build` with a pipe as stdout
  crashes every time (a file or TTY is fine). Both surfaced by the B8 bootstrap;
  worked around there by redirecting to a file + bounded build retries. `blade
  test` (also the full binary) is reliable, so the fault is specific to the
  build/self-compile path. Highest-value compiler bug to chase next.

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
  (reproduces with explicit construction; design 37/48 territory) — FIXED in
  design 59 B. [both apps]
- **Design 59 "small-fixes batch" — LANDED**: seven parts, one commit each.
  **A (DF2)** process wait-status decode — one `decode_wait_status` helper;
  signal deaths report 128+N, not exit 0. **B** custom-allocator deinit leak
  in Map/Vector — monomorphized deinit now appends field cleanup, and struct
  field assignment releases the old owning value, both routed through the
  value's own `A` (Global fast path byte-identical). **C** void-phi ICE — a
  Void merge (if/else-chain or match in tail of a Void fn/closure) no longer
  builds a phi. **D** riscv32 Hasher — state typed fixed-width `Int64` (64-bit
  hash on every target, hosted digest byte-identical; riscv32 --emit-ir
  verified). **E1** duplicate-key map-literal shadowed-value leak fixed
  (discarded insert-return dropped); **E2** `{a>0, b>0}` set-literal lookahead
  fixed (`<`/`>` no longer depth brackets — closure suite green, workaround
  retired). **F** ledger sweep: L13/L5/L10/L6/L4/L3 all verified-fixed and
  CLOSED with named proving tests; C4 verified no leak/double-free (no fix).
  **G** 52/52b v1 gaps scoped only (A1c). Discovered + DEFERRED: L14
  (enum-payload container element deinit) + L15 (collection-literal owning-
  element aliasing double-free) — a joint fix, out of this batch's scope
  (both LANDED in design 61 below). Compiler suite 669, 0 xfails. [both apps]
- **Design 61 "container element-drop fixes" — LANDED**: L14+L15 (joint) +
  L16, three commits. L14: `_canonicalize_type_kind` re-tags STRUCT-named-enum
  -> ENUM at monomorphization so enum drop glue selects for owning enum-payload
  container elements; `match` on an owned enum now consumes the scrutinee
  (bindings own their fields, drop once unless moved), fixing Map grow/remove/
  overwrite; Map probe helpers bind `_` for the value to avoid dropping a
  non-retained slot copy. L15: let-annotation canonicalize+default-fill so a
  literal-bound container's deinit resolves — no leak, no residual-temp
  double-free. L16: clean typechecker error for `.value`/member on a distinct
  non-struct `type`. Deferred out: L17 (owning-KEY containers + Arc-in-enum
  extraction — needs copy-with-retain). Compiler suite 676, 0 xfails. [both apps]
- **Design 63 "patterns + bounds + cast + named tuples" — LANDED** (six
  commits, suite 688 -> 722, 0 xfails). **Part 1 (distinct-type `as` cast):**
  a distinct alias projects TOWARD its underlying with `id as Int` — the
  sanctioned replacement for the never-implemented `.value` (T1b/L16 followup).
  One-directional; partial projection to a chain alias legal; sibling-alias
  (`UserId as OrderId`) + reverse rejected. TypeAliasSymbol now stores the
  unresolved immediate target to tell a partial projection from a sibling.
  Non-integer underlyings (String/Bool/struct) project by identity. Design-61
  `.value` error now suggests the cast. **Part 2 (T1b, dynamic array bounds
  checks):** a non-constant fixed-array index is checked `0 <= i < N` (one
  unsigned compare, negatives caught) -> panic "index out of range"; ALWAYS ON,
  no flag; read + `&arr[i]` + assign + compound-assign paths; constants fold
  away; raw-pointer/UnsafeMemory the explicit unchecked escape. **Part 3 (T1d,
  patterns):** new Pattern AST + a general if-chain match lowering ALONGSIDE the
  untouched enum switch (design 61 consume model + coroutine CFG walk preserved).
  Literal (Int/Bool/String via `_emit_equals` borrow chain), range (`1..9` +
  `1..=9`), guard (`case n if ...`, runs after binding, falls through), tuple
  arms nested with payload-enum/Optional patterns. Routing = general when
  scrutinee is not an enum OR any arm has a guard/literal/range/tuple/binding.
  Exhaustiveness: literal/range/guarded never prove it; `true`+`false` exhaust
  Bool; irrefutable arm = fallback; integer range-cover NOT computed (future
  work). Plus `let`/`var` destructuring (DestructuringLet, irrefutable only,
  per-position `_`, nested, whole tuple consumed per L1, use-after-move holds)
  and `if let`/`guard let (x, y) = optTuple`. **Part 4 (named tuples):**
  `(x: Int, y: Int)` types + `(x: 3, y: 4)` literals (SawType.tuple_field_names /
  TupleLiteral.field_names, carried through repr/substitute/resolve); named<->
  positional same-shape compatible, different-names/reorder incompatible, all-
  or-nothing labeling; `.name` access (stamped index -> extract_value) + `.0`/
  `[i]`; named PATTERN form deferred (clean error). Report-back: non-primitive
  cast underlyings NOT restricted (struct/String identity projection works via a
  codegen `value.type == to_llvm` fallback). Deferred/untouched: L17 (still
  needs copy-with-retain); named free-FUNCTION-call args remain unsupported
  (pre-existing; named tuples are orthogonal) — **NOW CLOSED by design 66
  below.** [both apps — closes T1b + T1d]

- **Design 66 "labeled arguments, lenient model" — LANDED** (four commits,
  suite 739 -> 759, 0 xfails). Closes the named-args ledger item (design 63's
  deferred "named free-FUNCTION-call args unsupported"). **Binding rule:**
  arguments bind LEFT TO RIGHT — a positional arg binds the next unbound param;
  a labeled arg binds its named param at-or-after the cursor, skipping FORWARD
  only over defaulted params (mid-default skip closes the trailing-only default
  limitation), never backward, never reordered; unknown label eliminates the
  candidate. Labels are REQUIRED only at real ambiguity, AVAILABLE always;
  positional-only calls take the byte-identical legacy path (the binding
  machinery — `_bind_args`/`_compute_binding` — engages only when a label is
  present), and a per-call `arg_plan` interleaves mid-skipped defaults for
  codegen. Applies to free funcs, instance/static methods, module-qualified
  calls; NO closure labels (structural types). **Overloads:** the label filter
  eliminates candidates FIRST, then design-55 exact-type matching runs on
  survivors; same TYPES + different LABELS now coexist (`f(a:b:)` vs
  `f(kind:value:)`; `f(0, value: 4)` resolves by one label — the user-confirmed
  case), a positional call over such a pair is an ambiguity error listing the
  labeled forms, same types + same names stays a decl error. Decl-site
  distinctness (`_overload_sig_key`/shape-expansion) is now name-qualified;
  `$OL$` mangling gains a `$LB$` label suffix ONLY for same-type overload pairs
  (non-overloaded + type-distinct symbols unchanged, IR-verified). **Parse
  ambiguity:** `name(label: value, …)` is syntactically struct init; the parser
  builds a StructInit and the typechecker reinterprets it as a labeled call when
  the name is a function/closure/type-param (a real struct name resolves to init
  first, so init is never disturbed). **Init NOT unified** (deliberate): init /
  struct-field / enum-payload construction keeps its order-INDEPENDENT set-based
  name matching — the ordered binding rule would break reordered `Point(y: 4,
  x: 3)` (verified valid today); verdict recorded in designs/66. [both apps —
  labeled calling for the Blade dogfood]

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

### Resolved-by-decision / stale-spec — CLOSED (design 60, Jul 30)
All named items fixed in LANGUAGE_SPEC.md / README.md / CLAUDE.md by
design 60 (see designs/60-stale-docs.md; ran concurrently with 59 in a
worktree, cherry-picked onto main). Rc→Arc-only (design 16), async/await
+ thread-API purge (colorless; 44/45/52/52b), `=>` arrows (superseded
note only), swapAt→Vector.swap (40), StringBuilder future-work note
removed (38), `dyn` retired (51). The four VERIFY-then-fix
contradictions were probed:
  - multiple bounds `T: A + B` — LANDED (spec de-planned)
  - glob imports `import mod.*` — LANDED (spec de-planned)
  - scoped visibility `public(package)` — LANDED (spec de-planned)
  - named tuple field access + `.value` on distinct types — NOT landed
    (named-tuple literal = parse error; `.value` on a distinct `type`
    was ledger item **L16 — now CLOSED (design 61): a clean typechecker
    error, not the feature**); spec examples relabeled illustrative/planned.
Additional Part-3 corrections: Comparable (48), extension Int/Float
(57), Never return type (58), `..=` operator (53) all reconciled from
stale "planned" markers. README fully refreshed (real install/test
instructions, current std list, headline features, no fictional URLs;
license status corrected — see LICENSE, added Jul 30: Apache-2.0 WITH
LLVM-exception).

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
- **L13 — CLOSED (verified fixed, design 59 F).** UInt division/modulo now
  emit `udiv`/`urem`. Proving tests assert real high-bit values (not just
  compile): `uint_division_signedness.saw` (10000000000000000000 / 2 ==
  5000000000000000000, differs from the signed divide) and
  `uint_modulo_signedness.saw` (10000000000000000000 % 7 == 3); both PASS,
  no XFAIL. [40 report, 59 F]
- **L12.** Fixed arrays cannot take extension methods (parse error) —
  blocked M1's fixed-array swap variant. [40 report]
- **L14 — CLOSED (design 61, joint with L15).** Root cause: a named type that
  denotes an ENUM is parsed/kept STRUCT-kinded (the parser can't know), and
  while `_get_llvm_type`/`_needs_cleanup` special-case such names, the drop-glue
  selector `_emit_drop_at` dispatched purely on `saw_type.kind` — so a
  monomorphization binding like the `T` of `Vector<MapSlot<K,V>>` reached
  drop-glue tagged STRUCT and the enum tag-switch cleanup (payload drops) never
  ran. Fixed at the source: `_canonicalize_type_kind` (codegen/generics.py)
  re-tags STRUCT-named-enum -> ENUM (recursively) and default-fills omitted
  trailing type args, applied where the monomorphization context is recorded
  (`_ensure_monomorphized_struct/_enum`) and on written let-annotations; erased
  `Box<any Trait>` is left untouched. Enabling element drops surfaced the
  Map/Set move/read ownership bugs (as L15 predicted): `match` on an owned enum
  scrutinee now CONSUMES it (owning bindings own their fields, drop once at arm
  end unless `move`d; scrutinee drop suppressed), fixing grow/remove/overwrite;
  the Map probe helpers bind `_` for the value so a non-retained slot inspection
  never releases the live payload. Proving tests (all PASS):
  `vector_enum_payload_deinit`, `map_owning_value_deinit`,
  `map_owning_remove_overwrite`. [61]
- **L15 — CLOSED (design 61, joint with L14).** Root cause: the literal built
  into a temp and returned `load(tmp_ptr)`, and — separately — a written
  `let m: Map<Int, V> = { ... }` annotation kept 2 type args, so its deinit
  lookup missed the 3-arg (`…,Global`) monomorphized deinit and the whole
  container leaked at scope end. Fixed by canonicalizing+default-filling the
  let annotation (so the deinit resolves) plus the L14 consume-model (so each
  element transfers exactly once, no residual temp double-free). Proving tests:
  `map_literal_owning_values`, `vector_literal_owning_deinit`,
  `vector_literal_owning_use_after_move_error` (moved element bindings still
  error), and the pre-existing `map_literal_dup_key_no_leak` (E1, exact count).
  [61]
- **L16 — CLOSED (design 61).** `.value` (or any member) on a distinct `type`
  over a non-struct underlying (`type MyInt = Int; x.value`) reached codegen and
  ICE'd ("Cannot find field value in struct with type i64"). The `.value`
  accessor is not a language feature (spec labels it planned/illustrative), so
  the typechecker's `_check_member_access` now emits a clean error naming the
  alias; a distinct alias of a STRUCT still falls through to the field check.
  Proving test: `distinct_type_value_access_error`. [61]
- **L17 — CLOSED (design 65) for the core; one narrow followup remains.**
  Two symptoms, both fixed:
  - *Symptom 2 (aggregate extraction garbage):* the enum payload byte array was
    sized by a naive field-size SUM (`_estimate_type_size`) that ignored
    alignment padding, so any payload with internal padding — `Arc<T>` (an
    optional pointer `{i1, ptr}` = 16 bytes, sum 9) or an optional/pointer after
    a smaller field — was TRUNCATED on construction and read OUT OF BOUNDS on
    match extraction. Fixed by sizing the payload with the variant struct's true
    `get_abi_size(target_data)` (codegen/core.py). Both match lowering paths
    (design-61 switch + design-63 general if-chain) share the extraction and both
    benefit. Tests: `enum_arc_struct_payload_match`, `enum_optional_payload_roundtrip`.
  - *Symptom 1 (owning key/value probe over-drop):* reading an owning aggregate
    out of a container slot (`Vector.get`'s `buf[i]` of a `MapSlot<String,V>` /
    an `Arc`-bearing payload) now COPIES WITH RETAIN — recursive
    `_emit_retain_at` (mirror of drop glue) via `_generate_copy` /
    `_transfer_needs_copy`, so the copy is a genuine owner. The match consume
    model RELEASES a `_`-discarded owning payload field with the symmetric
    inverse `_emit_release_at` (releases refcounted leaves, skips a non-refcounted
    `Deinit` value the slot still owns — keeps the design-61 exactly-once VALUE
    tests green). Instance-method owning by-value params are now registered for
    cleanup (made safe by teaching the placement-move `ptr[i]=value` to clear the
    source drop flag); generic free-function params too. Also fixed a shared
    `_needs_cleanup` cache poisoning where a STRUCT-kinded name that denotes an
    enum (L14) cached the bare name `False`. Owning for-loop variables are now
    released per iteration. Verified exactly-once via Arc strong_count:
    `set_owning_key_refcount`, `map_string_owning_value_balance`.
  - *ROOT CAUSE of the honest v1 limit:* copy-with-retain balances owning
    keys/values that are ImplicitCopy (refcounted: String, Arc, Arc-bearing
    structs). A pure **NoCopy struct with a side-effecting `Deinit` but no
    refcount** (a `Val{id:Int}` counter) CANNOT be a safe Set/Map KEY: the
    generic map bitwise-copies keys to probe, and such copies cannot be balanced
    (retain is a no-op, drop runs the deinit). This over-counts (memory-safe for
    a pure counter, but would double-free a real resource). Such keys should
    become a clean typechecker error (keys must be copyable-with-retain) — a
    deferred followup. NoCopy-Deinit VALUES stay exact (moved, never probe-copied).
  - *FOLLOWUPS — all CLOSED in the design-65 followup pass:*
    - `moved_variables` process-global never reset per function → **CLOSED**:
      reset at every function-body entry + save/restore around nested
      monomorphized/closure generation. Test `moved_variables_per_function_reset`.
    - Struct init with a fixed-width int field + bare literal ICE → **CLOSED**:
      codegen coerces to the field width, typechecker range-checks the literal
      (clean error). Tests `struct_fixed_width_field_literals`,
      `struct_fixed_width_field_out_of_range_error`.
    - Set `union`/`intersection`/`difference` owning-element leak → **CLOSED**
      by restructuring the algebra to an indexed `while (a.get(i))` walk (which
      drops the snapshot correctly) instead of `for e in a.iter()`. Test
      `set_algebra_owning_balance`. The underlying cause is recorded as **L18**.
    - NoCopy keys → **CLOSED** (L19 below), user-approved rejection.
- **L18 — CLOSED (design 65 followup).** A `for x in coll.iter()` over a custom
  iterator inside a GENERIC method leaked the loop variable's owning elements.
  Root cause (the coordinator's hypothesis, confirmed): the typechecker stamps
  the for-loop's `element_type` with the loop variable's type AS WRITTEN — inside
  a generic body `Vector<T>.iter()` yields the UNSUBSTITUTED param `T`. Codegen's
  per-iteration loop-variable cleanup gates on `_needs_cleanup(element_type)`;
  with `element_type = T` (a bare type param) that is False, so the RETAINED
  element `next()` returns was never released — one leaked ref per iteration.
  (The copy-with-retain work only EXPOSED it by making `next()` retain.) Same
  family as the earlier `_needs_cleanup` STRUCT-named-enum poisoning and the
  generic-param substitution fixes. Fix: substitute `element_type` through the
  active `type_param_context` before the `_needs_cleanup` gate, in both for-loop
  lowerings (codegen/loops.py). The natural `for e in a.iter()` shape was RESTORED
  in the Set algebra methods (union/intersection/difference/is_subset/is_superset)
  and `set_algebra_owning_balance` stays exact. [65]
- **L19 — CLOSED (design 65 followup, user-approved).** Map/Set KEYS are now
  restricted to copyable-with-retain types: the container probes keys BY COPY
  (hash/compare/slot inspection), so a NoCopy key, or a `Deinit`-only move-only
  key, cannot be balanced (its probe copies would run the deinit → miscount /
  double-free). The typechecker rejects such a key at construction
  (`Map<K,V>()` / `Set<T>()`) and at the map/set LITERAL forms, with a clean
  bound-style error naming the type ("map key type `Counted` must be copyable
  (trivial, ImplicitCopy, or ExplicitCopy with retain semantics): `Counted` owns
  a Deinit without a copy"). Trivial/POD, `String`, `Arc<T>`, and other
  ImplicitCopy keys stay legal; **ExplicitCopy keys stay legal too** (the retain
  glue deep-copies via `copy()` and releases via `deinit()` symmetrically — a
  balanced probe). VALUES are unaffected (NoCopy values are moved, never
  probe-copied, and stay exact). Set inherits the rule through its wrapper; the
  internal `Map<T, SetMark>` in set.saw is checked with a GENERIC T and passes,
  so the error fires at the user's `Set<T>()` site. Tests:
  `map_nocopy_key_error`, `set_nocopy_key_error`, `map_nocopy_key_literal_error`;
  existing String/Int/Arc key tests stay green. [65]

- **L1.** Partial moves — DECIDED forbidden + LANDED (design 35,
  `2829364`): field/nested/index forms all get naming diagnostics; the
  audit found `move arr[i]` had been silently moving the whole array
  into an ICE. Destructure-move and take() stay wait-and-see. [15, 35]
- **L2.** Return-type reconciliation for type-param / associated-type
  returns in generic bodies — documented deferred looseness from brief 24.
  [02, 24]
- **L3 — CLOSED (verified fixed, design 59 F).** The cross-module lookup
  now honors visibility with an ambiguity diagnostic. Proving tests (all
  PASS): `l3_private_struct_bare.saw` (a bare reference to another module's
  PRIVATE struct is "undefined struct `Secret`", not silently resolved),
  `l3_struct_ambiguity.saw` (two modules exporting a public `Shape` is
  "ambiguous struct `Shape`", not dict-order), `l3_qualified_still_works.saw`
  (legitimate qualified access still succeeds). [critique structural, 59 F]
- **L5 — CLOSED (verified fixed, design 59 F).** Array-mutation gaps closed;
  proving tests assert real behavior, not just compile: `array_elem_field_assign.saw`
  (`a[0].v = 99` then prints 99 — the mutation lands) and
  `array_elem_overwrite_deinit.saw` (`a[0] = new` runs the overwritten
  element's deinit at overwrite, then reverse-order scope cleanup). Both
  PASS, no XFAIL. [33, 59 F]
- **L6 — CLOSED (verified fixed, design 59 F).** The typechecker's module
  member-access checker stamps `resolved_type` on the nested qualified
  object (typechecker/expressions.py `_check_member_access`, "so
  signedness/type-driven lowering never falls back"), and the interpolation
  path reads the fail-loud `_expr_type` — the design-56-era defensive
  print-path fallback is gone. Probe: `_int_is_signed` is never reached with
  a None type for the module case. New proving test
  `l6_module_qualified_signedness.saw`: a DIRECTLY module-qualified UInt
  field (`mod.factory().field`) in an overflow-checked add (5e18+5e18=1e19,
  exceeds signed max) AND in interpolation renders unsigned, no panic.
  (The deliberate signed-default in `_int_is_signed` for genuinely
  unannotated non-critical hints is kept by design — not a workaround.)
  [31 report, 59 F]
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
- **L10 — CLOSED (verified fixed, design 59 F).** The auto-wrap path treats
  the wrapped value as transferred, so no premature free. Proving tests
  assert the payload is intact after a filler string that would reuse a
  freed slot: `autowrap_ok_no_premature_free.saw` (Ok-wrapped String prints
  intact), plus `autowrap_err_no_premature_free.saw` and
  `autowrap_optional_no_premature_free.saw`. All PASS, no XFAIL. [38 report,
  59 F]
- **C6.** Method-level generic type params don't monomorphize on
  NON-generic-type extensions (`extension String { func f<R>(...) }` →
  "Undefined struct: R") — blocks value-returning `withCString<R>`.
  Sibling of C5, surfaced in brief 38. [38 report]
- **L4 — CLOSED (verified fixed, design 59 F).** `Vector<File>.copy()` is a
  clean user-facing typechecker error, NOT an ICE/traceback: "type
  `Vector<File, Global>` has no method `copy`: requires `T: Copy`, and `File`
  does not conform" with a `T: Copy` hint. Probe:
  `.build/scratch/l4_vecfile.saw`. [09, 26, 59 F]

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
- **C4 — VERIFIED (design 59 F): no leak/double-free proven; closure-Deinit
  is real future work.** Probed a non-spawn escaping closure (bound/returned)
  dropped WITHOUT being called: a moved-in NoCopy capture deinits exactly
  once (`.build/scratch/c4_probe.saw`: 1 Res -> 1 deinit) and an Arc capture
  returns to its baseline refcount (`c4_arc.saw`: 1/2→1), so NO value leak
  and NO double-free — per the brief's "fix only if a leak/double-free is
  proven", no fix. Discovered (deferred, needs the closure-Deinit feature,
  NOT a small fix): the generated env destructor (`codegen_env_dtor`) is only
  invoked by the spawn trampoline, so a non-spawn closure's drop does not run
  it — the owning capture is released at the CREATING frame's exit rather
  than at the closure's drop (early but exactly-once), and the heap env block
  itself is not freed on that path. Wiring `codegen_env_dtor` into the
  closure-typed variable's drop glue is the real C4/closure-Deinit work. [21b]

## Concurrency & async

- **A1.** Stage 2 async — TRANSFORM FULLY COMPLETE: straight-line +
  nested calls + methods (44/45) AND control-flow suspension (52 Part
  0: CFG-walk state machine — while/for-range/if/match/break/continue,
  arbitrary nesting; honest rejections: for-over-iterable suspension,
  value-producing break from suspending loops, move in spanning
  conditions). Single-task runtime landed (45). **A1b = brief 52b —
  LANDED**: TaskGroup-owned run queue (the C1 nursery model; group Deinit
  runs the executor = structured join via LIFO), spawn/TaskHandle/cancel/
  suspending-channel, on design 51's validated erasure. Soundness catches
  en route: datalayout offsets (45), struct-init optional wrap + if-let
  move-out double-free (52). Generic driven functions still blocked on A5.
  [44, 45, 52, 52b]
- **A1c. 52/52b v1 gaps — CLOSED (design 62, LANDED; ran in a worktree
  concurrent with 61, cherry-picked onto main):**
  * **G1 TaskGroup inside a suspending fn — CLOSED.** A frame-resident
    TaskGroup is plain-encoded (addressable `self.group`, real empty-
    `TaskGroup()` placeholder); `__Frame_*` structs exempted from
    Deinit/NoCopy containment (torn down memberwise). group Deinit
    drains children across a parent suspension (structured join via
    LIFO); nested groups compose (each executor drives only its own
    queue); cancellation words frame-resident. Tests:
    taskgroup_in_suspending_fn, _suspending_parent_sleep,
    _suspending_deinit_join, _suspending_cancel, _nested_groups.
  * **G2 if-let/guard-let over a suspending call — CLOSED.** Condition
    hoisted to a driven temp; guard-let shares the machinery; while-let
    absent from grammar. New self_opt frame encoding (no double-wrap of
    `T?` fields — fixed a latent miscompile for optional-returning
    suspending callees) + assign-to-optional None-propagation. Tests:
    coro_iflet_over_suspending, coro_guardlet_over_suspending,
    coro_iflet_suspending_deinit.
  * **G3 first-class `Channel.receive()` — CLOSED.** Cooperative
    suspending receive lowered INLINE (try_receive+yield_now against
    the caller's frame — no callee frame, so the generic-method-frame
    blocker never arises); named `receive` (the blocking thread-engine
    method was already `recv` — same signature can't overload by
    effect). Buried expression-position receive rejected cleanly.
    Tests: channel_recv_producer_consumer, _cancel, _nested,
    _buried_error. [52, 52b, 62]
- **Design 62 "async v1 gaps" — LANDED**: G1/G2/G3 above, one commit
  each + docs (spec concurrency section + CLAUDE.md). Suite 669 → 681
  in its worktree; 688 combined with design 61 on main. Naming:
  cooperative `receive` / blocking `recv`.
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
