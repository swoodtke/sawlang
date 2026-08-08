# Saw — Open Work Tracker

Open items ONLY. Landed work lives in `designs/NN-*.md` + git history
(this file was pruned Jul 30; see git history of this file for the old
landed recaps). Conventions: cite source designs in [brackets]; VERIFY
items need a probe before being treated as real work.

## Design 180 — sleep(Duration) (LANDED, Aug 8)

`sleep` takes a `Duration` and nothing else; the bare-Int form is gone.
DF-170a is closed above. One finding, and one decision the brief did not
anticipate:

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
- **The prelude pin needs ratifying.** Unit 2 put `Duration` in the prelude as
  recommended, which meant a FILE move (`std/duration.saw`) rather than a
  flag: prelude membership and code generation are decided by the same module
  gate, so a per-symbol exception would have made the name visible and its
  methods absent. `Instant` stayed import-required in `std.time`. Consequence
  worth a look at review: `time.Duration` no longer resolves, and
  `import std.time.{Duration}` is now an error (with a hint saying the type is
  in the prelude and the entry should be deleted).
- **`Instant.elapsed` / `duration_since` panic on a negative span** rather
  than returning one, since a `Duration` has no negative values. The first
  fires only if the monotonic clock steps backward; the second if `earlier`
  is the later of the two. The brief put Instant changes out of scope, so
  flagging rather than assuming: `duration_since` used to document a negative
  result as supported.

## Design 181 — blocking-call audit findings (filed Aug 7)

Full inventory + policy menu in `designs/181-blocking-call-audit.md`.
Headline: **169 externs across sawc/std/ + sawc/rt/, NOT ONE annotated
`blocking`.** The design-103 offload machinery works and is unused by std.

- **DF-181a (P0-adjacent, filed Aug 7): `Command.run()` / `Command.output()`
  starve every sibling task for the child's whole lifetime.** Both reap via
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
  exactly — but see DF-181f, which currently blocks the annotation.
- **DF-181b (P0-adjacent by reach, filed Aug 7): every std.file /
  std.directory seam is a naked blocking call.** `__saw_rt_fs_open`/`_read`/
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
  executor forever.** It blocks the calling thread in `pthread_cond_wait`
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
  is too narrow to express the annotations the audit recommends.** Of the
  naked calls, only `__saw_rt_proc_wait(job: Int) -> Int` fits.
  `__saw_rt_proc_read_stdout` (3 args), every `__saw_rt_fs_*` I/O seam
  (3 args) and `__saw_rt_thread_join` (Void return) are all off-whitelist.
  This also removes the escape hatch the DF-181b policy assumes: a user who
  knows they are on a network mount has no way to offload the read. Widening
  it (multi-arg + a real pool) was already future work; this audit is the
  concrete demand for it.
- **DF-181f (COMPILER, filed Aug 7): the `blocking` annotation is SILENTLY
  IGNORED on `__saw_rt_*` runtime seams — so "annotate the seams" does not
  work today.** Design 103 promises an offload or "a clean anchored error,
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

- ~~**DF-162a DECIDED: compiler default.** Freestanding aarch64 implies
  `-neon,-fp-armv8` unless `--target-features` overrides — freestanding
  output must not trap before main. Lands as a compiler-side unit in design
  172 (cherry-picks to main immediately per SOS flow); M1b's HAL drops its
  explicit flags when it rides.~~ **DONE (design 172 unit 7).**
  `target_info.effective_target_features` is the one place the default
  lives. It is load-bearing for the SAW half too, not only the C the finding
  was found in: the arm64 SOS kernel object carried five NEON block-move
  instructions (`ldr q0` / `ldp q1, q0`, a struct copy) and now carries none.
  The HAL did NOT drop `CPACR_EL1.FPEN` — see DF-172c, which is why.
- **sosimg v3 DECIDED: widen addresses to 64-bit NOW** (header 16→24,
  records 20→24, fixtures both arches, both producers/consumers). Unit added
  to design 172.
- **DF-168b DECIDED: defer with trigger** — revisit when compile speed next
  hurts, or before the self-hosted compiler port freezes the pipeline shape.
- **164 tier C CLOSED: declined by arithmetic; the design-144 std
  type-identity exemption STANDS.** 168's reachability strip ate the prize.
  If numbers ever reopen it, the per-exclusion-set object cache is the path
  that never touches 144.
- **171 Arc arm CONFIRMED**: shared-only paren-less place on Arc, NO
  exclusive place in any spelling, `with_unique` stays the ceremonial
  closure primitive for CoW-container authors (docs reposition: app code
  wants Mutex or a CoW value type).
- **DF-151m DECIDED: fix + migrate.** A `let` root's immutability is real;
  in-tree reliance migrates to `var` roots. Soundness-batch unit.
- **Float64 DECIDED: implement the Float32/Float64 family** (design 173,
  brief authored; queued after 170/171 integrate — typechecker/codegen
  contention). Spec stays wrong only until 173 lands.
- **DF-155a DECIDED: non-breaking knob.** `output()` keeps its meaning;
  explicit stderr capture/discard control + accessor added beside it.
  Small std.process unit, joins the soundness/semantics batch.
- **Rewrite-track backend DECIDED: IR-text + clang via std.process** (over
  LLVM-C FFI). The parser-port brief inherits this; the seam stays swappable.
- **Rights-table single-source: BACKLOG** on the tracker's own trigger
  (revisit if kinds multiply).
- **DF-146j DECIDED (user, Aug 7 after the nested-optional + asymmetry
  discussion): `Map.get` becomes the borrows-get SYNONYM of `[]`** — both
  conditional lends returning `V?`; the copy-shaped `get` (the last
  copy-shaped exception to the places model, and the source of the NoCopy
  over-release) is deleted. The panic-vs-None asymmetry between `Vector.[]`
  and `Map.[]` is RATIFIED as-is (dense-checkable domain panics on bug,
  sparse domain returns data; `!` composes the panic spelling from the
  Optional one). Nested `V??` differentiation verified by probe.
- **DF-146l/m/n/o ALL DECIDED (user, Aug 7): "we should fix all those
  issues."** 146l: the None-ICE propagation gaps get fixed AND any remaining
  untyped-None becomes a clean anchored error; 146m: auto-wrap fires at a
  generic param instantiated to an Optional; 146n: `m[k]! = v` becomes a
  legal assignment target (whole-value place write, panics on absent —
  symmetry with `v[i] = fresh`); 146o: optional-chain assignment accepts
  place-expression heads (`m[k]?.field = v` — head lends, absent path skips
  the write and the RHS, types `Void?`). DISPATCH: one "places/optional
  plumbing" batch agent (146j+l+m+n+o), AFTER 170 integrates (shared
  typechecker surface). PROBED (Aug 7, user's nested-optional question): `T??`
  instantiates honestly — `Vector<Int?>.get(0)` on a present-None element
  yields Some(None), absent yields None, one `if let` peels exactly the outer
  layer; same for `Map<String, Int?>.[]`. The `?.`-chain flattening rule does
  NOT apply to generic instantiation, so the conditional-lend contract is
  sound for optional-valued containers (probe:
  .build/scratch/probe_nested_opt.saw).
- **DF-146l — FIXED (design 176 unit 1), all four sites plus the hardening
  rule.** Site 1 (Map literal value) and every other ELEMENT position went
  through one fix: `_apply_literal_expected_type`, the recursion that already
  pushes a fixed integer width into a container's elements, now pushes an
  OPTIONAL expectation onto a bare `None` (stamped as `expected_type`, since
  `_check_expression`'s own stamp would overwrite a `resolved_type` written
  before the check). Site 2: `??` stamps its LHS's payload type onto a `None`
  RHS and returns that payload type rather than the literal's untyped one.
  Sites 3 and 4 turned out to be one bug in inference: `_unify_infer` BOUND a
  type parameter to the untyped optional, so `idn(None)` "solved" and then died
  in codegen. A bare `None` now records no binding at all, which makes the
  underdetermined call report itself cleanly AND fixes DF-174f for free (unit
  11 — nothing left for the later argument's `Int?` to conflict with). Site 4's
  remaining half is codegen: an OMITTED `None` default is materialized from the
  CALLEE's parameter type, the only thing that knows the instantiation (the
  default expression lives on the declaration, and stamping it would let one
  call's instantiation win for another's). That also fixed a second, separate
  ICE the first fix uncovered — a `b: T? = None` default reached the LLVM
  lowering with an abstract `T`. HARDENING: an untyped `None` reaching codegen
  is now a clean anchored error (`CodegenUserError`, rendered by the driver like
  `StaticAssertError`), never an ICE. NOT ACHIEVABLE and pinned as an error
  instead: `with_default(1)` where `T` appears only in `b: T = None` — a bare
  `None` names no type, so `T` is genuinely underdetermined; the ruling's "infer
  or fail cleanly" takes its second branch (`examples/errors/
  none_default_underdetermined.saw`). Original finding follows.
- **DF-146l (COMPILER, filed Aug 7, found by that probe): a `None` literal
  ICEs wherever expected-type propagation misses — FOUR trigger sites known**
  (2 filed Aug 7, 2 more added by design 174's sweep).
  (1) A Map literal value: `var m: Map<String, Int?> = {"x": None}`;
  (2) a `??` RHS against a nested optional: `m["x"] ?? None` (LHS `Int??`,
  RHS should adopt `Int?`);
  (3) **a bare `None` as a GENERIC CALL ARGUMENT** — `idn(None)` for
  `func idn<T>(x: T) -> T`. This one is genuinely underdetermined, so the
  right outcome is the clean "cannot infer type argument `T`" error, and the
  ICE hides it (explicit `idn<Int?>(None)` works);
  (4) **a `None` DEFAULT VALUE typed by a type param** — `func f<T>(a: Int,
  b: T = None)` ICEs at the DECLARATION, before any call site. Design 108
  makes such a default legal and lets it drive inference, so it should infer
  or fail cleanly.
  All four die with "internal compiler error: None literal has no type
  information" — the ICE (not a clean error) is itself the bug, and each
  missing propagation site is a trigger. Vector literals type the same shape
  fine. Same family as DF-165b. Workarounds: `m.insert(k, None)` and an
  annotated `let absent: Int? = None`. Small typechecker unit; queue with the
  soundness batch; the fix should turn any REMAINING untyped-None into a
  clean anchored error, not an ICE. Sites 1-4 are xfail-pinned as
  `examples/optional_generic_none_{map_literal,coalesce,generic_arg,
  default_value}_xfail.saw`.
- **DF-146m — FIXED (design 176 unit 2).** `_df3_allow_wrap` returns True
  unconditionally now: design 57's DF3 rule (auto-wrap must be explicit at a
  generic boundary) is retired, because it was invisible from the caller's side
  — whether `7` wrapped depended on whether the callee spelled the parameter
  `Int?` or `V`, and a bare `None` typed at that position either way. Still
  exactly one level; inference is unaffected (it runs first and solves a
  parameter from the argument's own type, so this only applies where the
  instantiation is already fixed). MIGRATION: one example,
  `examples/df3_generic_no_wrap_error.saw`, PINNED the retired rule and was
  rewritten to pin the new one (same filename, kept so the reversal is visible
  in its history). Original finding follows.
- **DF-146m (COMPILER, filed Aug 7): call-site optional auto-wrap does not
  fire at a GENERIC parameter instantiated to an Optional.** `m.insert("y", 7)`
  on a `Map<String, Int?>` errors "expects `Int?` but got `Int`" — the
  design-55 auto-wrap works for a written `Int?` parameter but not for `V`
  instantiated to `Int?` (a bare `None` DOES type there, so the paths
  diverge). Workaround: an annotated binding. Same batch.
- **DF-146o — LANDED (design 176 unit 5).** The write becomes the BODY of the
  head's window: `m[k]?.f = v` lowers to `m.[](k, { __p0 in __p0.f = v }, { })`.
  The `?` is CONSUMED by the lowering — it was the lend's own optionality, and
  inside the window the payload is simply there — which is also why the head is
  never read out as a value first (the field write would land in the copy). The
  expression still types `Void?`, and Saw offers exactly two positions for one,
  so each gets the window result it needs: `Void` for statement position, `Bool`
  for the `_`-blessed `if let`/`guard let`, and no `Void?` has to be synthesized.
  Named heads (`v.get(0)?.f = v`, DF-175d) work through the same path, once
  `_chain_assign_root` learned to walk a place method call as the projection it
  is — the subscript spelling of the same lend always walked through as an
  ArrayIndex, which is the whole of why one worked and the other did not. V1
  FENCE: a second `?` hop past the lend (`m[k]?.a?.b = v`) keeps design 111's
  existing behavior; the inner hop would need its own short-circuit inside the
  window. Original finding follows.
- **DF-146o (DESIGN QUESTION, filed Aug 7, user's spelling): optional-chain
  ASSIGNMENT rejects a place-expression head.** `m["x"]?.value = 42` and
  `v.get(0)?.value = 42` both error ("the head of an optional-chain
  assignment must be a mutable variable or a `&var`-reachable path") — design
  111's chained assignment predates 146's conditional lends and never learned
  place heads. The natural write-if-present idiom therefore doesn't exist;
  today's spelling is the double-lookup `if let _ = m[k] { m[k]!.f = v }`.
  Composing them (head lends, absent path skips the write like any `?.`
  short-circuit, types `Void?`) is the obvious completion — one cluster with
  DF-146n (assignment-target grammar vs places). Add to 171's probe round
  (conditional lend + `?.` composition: READS compose, WRITES don't).
- **DF-146n — LANDED (design 176 unit 4).** A `ForceUnwrap` is an assignment
  target when its subject is a place. The use-site lowering already knew how to
  consume the `!` (the same promise `v.get(i)!.m()` makes), so the write becomes
  an exclusive window's body and the absent path is the panic the `!` asked for.
  On an ordinary optional local the `!` is still not a target, and says so.
  Original finding follows.
- **DF-146n (DESIGN QUESTION, filed Aug 7): `m[k]! = v` is a parse error
  ("invalid assignment target")** — a `!` head is not an assignment target,
  so a Map value cannot be whole-value REPLACED through the place
  (`m[k]!.field = v` works; `v[i] = fresh` works on Vector). `insert` is the
  overwrite spelling meanwhile. Question for the user: should a forced
  conditional lend be assignable (symmetry with `v[i] = fresh`, panics on
  absent) or is insert-as-the-only-overwrite deliberate?

## Design 174 — the T = U? sweep (Aug 7, probe-only investigation)

**Headline: NO silent wrong behavior exists in the matrix.** 21 of the ~31
probed behaviors work; every break is loud (parse error, clean error, ICE, or
a malformed-IR crash). The two properties that would have been undiagnosable
if wrong were checked directly and are both CORRECT: drop counts through an
optional element type (`Vector<Res?>`/`Map<String, Res?>` deinit each `Some`
exactly once, `None` not at all; an ImplicitCopy payload read out of a place
is a real retain), and discriminant-aware hashing (`Set<Int?>` and
`Map<Int?, V>` keep `None` and `0` DISTINCT). The brief expected `Set<Int?>`
to be a clean refusal — it is instead correct, which is better. Full report +
verdict table: `designs/174-optional-generic-sweep.md`. 19 tests landed as
`examples/optional_generic_*.saw` (7 pins, 12 xfails).

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
- **DF-174b — FIXED (design 176 unit 8). Two collapsed layers, not one.**
  (1) Every codegen store into an optional slot asked "is the slot optional and
  the value not" — a SHAPE test, which cannot tell an already-fit value from one
  owing another layer, so an `Int?` into an `Int??` cell wrapped nothing and
  LLVM refused the store. Replaced at all seven sites by `_fit_optional_slot`,
  which compares the value against the slot's PAYLOAD type and keeps the shape
  test as the fallback; `_transfer_type_for` (which picks the type the copy/drop
  glue is driven with) had the identical blind spot and now asks the same way.
  (2) A bare `return None` from an `Int?`-returning task typed itself against
  the cell and became the OUTER None — the encoding's "no result yet" — so
  `join`'s `take()!` force-unwrapped nothing. The coro transform now says which
  layer a `None` return belongs to when the result type is itself optional.
  Tests: the pin, plus `examples/spawn_optional_result.saw` (single-threaded and
  `threads: 2` groups, absent and present results, and a `String?` payload
  through the same cell). Original finding follows.
- **DF-174b (COMPILER, filed Aug 7): spawning a task whose RESULT TYPE is an
  Optional ICEs.** `group.spawn(work())` where `work() -> Int?` dies with
  "internal compiler error: cannot store {i1, i64} to {i1, {i1, i64}}*". The
  group's result cell is `T?` (present once the task completes), i.e. `Int??`
  at `T = Int?`, but the completion path stores the bare `Int?`. A task
  returning a non-optional joins fine. Test:
  `examples/optional_generic_spawn_result_xfail.saw`.
- **DF-174c (LANGUAGE GAP, filed Aug 7): a nested optional type has NO
  SPELLING.** The containers genuinely produce `Int??` values (`Vector<Int?>.get`,
  `Map<String, Int?>.[]`, `pop`, `remove`) and those values behave correctly,
  but the type cannot be NAMED, so no function can take or return one and no
  local can be annotated as one. All three candidates fail: `Int??` is a parse
  error ("Expected '=' in variable declaration"); `Optional<Int?>` is not a
  spelling at all (DF-174d); `(Int?)?` makes the parenthesized type a distinct
  1-tuple-ish type whose `!` yields `(Int?)`. Consequence: every two-layer read
  must be peeled INLINE at each use — the natural `func report(o: Int??)`
  helper is unwritable. Test:
  `examples/optional_generic_nested_spelling_xfail.saw`.
- **DF-174d — FIXED (design 176 unit 9), all three parts.** (1) `Optional<T>`
  resolves to `T?` — a SPELLING, not a nominal registration, so the two are ONE
  type and flow into each other. It also gives the nested optional a written
  form (`Optional<Int?>`), which is what the containers genuinely produce, so
  the `func describe(o: Int??)` helper DF-174c wanted is writable today under
  that name. (`Int??` itself stays a parse error — the postfix sugar is the
  user decision this batch is explicitly out of.) (2) A written name with TYPE
  ARGUMENTS that resolves to nothing is now `unknown type `Frobnicate``, at the
  annotation. Type arguments are what make it decidable: a type parameter takes
  none and neither does an associated type, so a BARE unknown name is still
  indistinguishable from either and is left alone. (3) The adjacent nit: the
  not-`Printable` hint no longer advises `extension Int?: Printable`, which is
  unwritable in two independent ways; for an optional it says to unwrap first.
  Tests: `examples/optional_type_name.saw`,
  `examples/errors/unknown_generic_type_name.saw`,
  `examples/errors/print_optional_hint.saw`. Original finding follows.
- **DF-174d (COMPILER, diagnostic quality, filed Aug 7): `Optional<T>` is not a
  writable type name, and a bare UNKNOWN type name gets NO diagnostic.**
  `Optional` has zero meaning to the compiler — no `register_enum`, no
  `.saw` declaration, no parser special case — so `Optional<Int>` resolves to
  an opaque nominal STRUCT named "Optional" and `let a: Optional<Int> = 5`
  reports "cannot assign `Int` to variable of type `Optional<Int>`". `Result`
  WAS wired up this way (`typechecker/registration.py`, plus `is_result()`
  accepting the STRUCT spelling), so the asymmetry is historical, not
  principled. The deeper half: a bare unknown name is indistinguishable from a
  type parameter at resolution time, so `let a: Frobnicate<Int> = 5` gets the
  same confusing mismatch instead of "unknown type". Prelude docs list
  `Optional` as a core name and the spec documents `Optional.take`, so users
  WILL write it. Adjacent nit: interpolating an optional errors cleanly but
  hints "conform it with `extension Int?: Printable`", which is not writable
  advice (you cannot extend `Int?`, and the orphan rule forbids it).
- **DF-174e — FIXED (design 176 unit 10).** The write path read
  `_check_place_use`'s RETURN value and stripped an optional off it. That return
  is `T?` only when the accessor lends CONDITIONALLY; `Vector.[]` lends
  unconditionally, so on a `Vector<Int?>` the `Int?` WAS the element and the
  strip invented an `Int` — hence a diagnostic naming a type the program never
  mentions, and a refusal of exactly the right value. The element type is
  stamped on the place by the same function, and the write checks against that
  now. The refusal path still works and names the real element type
  (`examples/errors/place_assign_wrong_element_type.saw`). Original finding
  follows.
- **DF-174e (COMPILER, filed Aug 7): `v[i] = <a T? value>` on a `Vector<T?>` is
  refused, and the error names the WRONG element type.** Assigning an existing
  `Int?` through the place gives "cannot assign `Int?` to element of type
  `Int`" — but the element type of a `Vector<Int?>` IS `Int?`. The
  place-assignment path unwraps one Optional layer off the element type and
  then auto-wraps the RHS, which is why `v[i] = 9` and `v[i] = None` both work
  while handing it a value that is already the right type does not.
  `v.set(i, value)` accepts the same value, so the accessor and the place
  disagree about the element type. Test:
  `examples/optional_generic_place_assign_xfail.saw`.
- **DF-174f — FIXED (design 176 unit 11, delivered by unit 1's one-line change
  to `_unify_infer`). Later-arg inference would not unify a bare `None` with the
  Optional a later argument fixes.** The literal was BINDING the type parameter
  to the untyped optional, so the later `Int?` looked like a second, conflicting
  binding. A `None` records nothing now, leaving design 105's fixpoint to solve
  the parameter from whichever argument has a type — in either order. Original
  finding follows.
- **DF-174f (COMPILER, filed Aug 7): later-arg inference will not unify a bare
  `None` with the Optional a later argument fixes.** `pick(None, some)` where
  `some: Int?` and `func pick<T>(a: T, b: T) -> T` errors "cannot infer type
  argument `T`: it is required to be both `OPTIONAL` and `Int?`" — two
  requirements that are not in conflict, since `Int?` SATISFIES "is an
  optional". Design 105's fixpoint solves the shape; what fails is treating the
  None literal's own type as an irreconcilable constraint rather than a
  constraint any optional discharges. Same root family as DF-146m (None vs
  Optional unification at a generic parameter) and a natural companion fix.
  Clean error rather than an ICE, but a wrong rejection. Test:
  `examples/optional_generic_infer_later_arg_xfail.saw`.

## DECIDED — Aug 7 evening round (user)

- **DF-176b DECIDED — LANDED Aug 8** (batch unit 1; see the FIXED entry under
  "Design 176 findings"). Ban a `&var self` method call on a field of a `&self`
  receiver, with the INTERIOR-MUTABILITY EXEMPTION — fields of type
  Atomic / SpinLock / UnsafeMemory (the by-pointer-at-`&self` family) stay
  callable; everything else is the same error class as 176 unit 13.
- **DF-174c DECIDED: implement the `Int??` postfix sugar** (type-position
  `??` nesting; `Optional<Int?>` remains the generic spelling). Flips the
  suite's last cited xfail. Same batch.
- **DF-176a: SKIPPED by choice (user)** — stays filed; the compound
  spelling (`*=`) is the idiom; the RHS-first-vs-clean-error ruling waits
  for a real collision.
- **DF-170a: resolution rides the sleep-API redesign conversation**
  (user direction: unsigned + unit-typed sleep; shape under discussion).
  The bare chunking patch is NOT dispatched separately.

## Design 172 note (branch PARKED for user review; full findings ride the branch)

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

## Design 176 findings (places/optional plumbing batch, Aug 7)

**DF-146 letter collision — RESOLVED (unit 12), in the opposite direction to the
brief's wording, deliberately.** Two sets of entries shared `DF-146l/m/n/o`: the
Aug 6 set that came out of design 146's own landing, and the Aug 7 set this batch
fixed. The brief said to renumber the Aug 7 entries. By the time unit 12 ran that
had become the expensive direction and the confusing one: the Aug 7 numbers are
cited at **24 sites in the tree** (compiler comments and test headers) plus six
of this batch's own commit messages, while the Aug 6 set — three of its four
entries CLOSED — is cited **nowhere outside this file**. Renumbering it instead
costs four tracker edits and leaves every in-tree citation and every commit
message correct. So:

| was (Aug 6) | is now | subject |
|---|---|---|
| DF-146l | **DF-146p** | exclusivity-in-a-window reported as a copy error (still OPEN) |
| DF-146m | **DF-146q** | closure missed a capture used only in an interpolation |
| DF-146n | **DF-146r** | place window's flavor read after the chain was rewritten |
| DF-146o | **DF-146s** | struct field of enum type never dropped its payload |

`DF-146l/m/n/o` now mean the Aug 7 entries only, everywhere. The three Aug 6
commits (dbf4ab9, 125446f, d3bc5ed) name the retired letters in their messages;
this table is the map. Flag if the other direction was wanted — it is four more
tracker edits plus 24 in-tree ones.

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
- **DF-176b — FIXED (Aug 8, DF-176b/174c batch unit 1). The FIELD receiver
  form, with the interior-mutability exemption the user ruled.**
  `self.cells.push(9)` in a `&self` method is now the same error class as unit
  13's direct write, in both body kinds. One function answers all three forms
  DF-175a named: `_reject_var_self_call_on_shared_self` tests the RECEIVER —
  `self` itself (DF-179b, no carve-out possible) or storage inside it, which is
  `_writes_into_self_storage`'s question asked of a receiver instead of a write
  target. Factoring that walk into `_self_storage_type` is the whole mechanism:
  the same TYPE-tracking walk that lets `self.cancel_ptr[0] = true` through lets
  `self.rows[0].push(9)` through, because a heap element is shared by the copy
  rather than duplicated by it. THE EXEMPTION is by TYPE NAME — `Atomic`,
  `SpinLock`, `UnsafeMemory` — not codegen's recursive "contains an `Atomic`"
  test: that question is where the bytes travel, this one is whether the type's
  CONTRACT is mutation through a shared borrow. So a struct WRAPPING an `Atomic`
  is not exempt (its `&var self` methods take the whole wrapper, sibling fields
  included), which is a deliberate narrowing of the user's wording, stated in
  the spec. IN-TREE MIGRATION TAIL: ONE break, and it was not a user idiom —
  `examples/lend_var_coro_and_forwarding.saw`'s `lend self.inner[i]`, whose
  lowered `__lend_var_[]` call the rule reported by a name the source never
  writes. Skipping `place_lowered` calls fixed it and opened DF-176c above.
  Nothing in std, blade, libs, devtools or sos relied on the hole. Tests:
  `examples/errors/shared_self_field_var_method_call.saw` (the vanishing push),
  `examples/errors/shared_self_borrows_field_var_method_call.saw` (the
  `let`-root mutation), `examples/shared_self_field_call_exemption.saw` (the
  exemption, the indirection carve-out, and the `&var self` fix).
  Original finding follows.
- **DF-176b (COMPILER, soundness, filed Aug 7 by unit 13's probing): calling a
  `&var self` METHOD on a field of a plain `&self` receiver is unchecked.**
  The third form DF-175a named. `self.cells.push(9)` in a `func peek(&self)`
  compiles; the push runs against the receiver's COPY of the `Vector` header, so
  the caller sees no new element and the callee's growth is lost —
  `.build/scratch/p176_selfmethod.saw` prints `a 2` then `b 1`. Worse than the
  vanishing field write, because the copy and the original share a buffer: a
  push that does NOT reallocate writes into storage the caller owns while the
  caller's `length` stays behind. Design 176 unit 13 deliberately scoped itself
  to the direct-write form and this was left filed rather than reinterpreted.
  NOT a mechanical extension of the same rule — a struct holding an `Atomic` is
  received BY POINTER even at `&self`, so `func bump(&self) { self.n.fetch_add(1) }`
  is a blessed idiom that a naive "no `&var self` method on a `self` field" rule
  would break, and `SpinLock`/`UnsafeMemory` are the same shape. The fix has to
  ask whether the receiver's field is reached by pointer, which is the same
  question `_writes_into_self_storage` now answers for writes. Wants a user
  decision on the Atomic/interior-mutability carve-out first.

## Design 175 findings (`#lend_var` investigation, Aug 7 — PROBE-ONLY, no compiler changes)

Full report in `designs/175-lend-var-investigation.md`. Verdict: GO, but
ordered behind two soundness fixes. Probes in `.build/scratch/p175_*.saw`
(driver `probe_run175.py`). Headline correction to the brief's premise: the
const-generic "branch statically pruned before the check" precedent does NOT
exist — the typechecker checks a generic body once, abstractly, with an empty
const-param environment, and `static_assert(N > 4)` inside an `if N > 4`
branch FIRES for the `N = 2` instantiation (`p175_constgen_assert_prune`).
`#lend_var` does not need it: its specialization set is fixed at
{shared, exclusive} with no caller information, so the fold is a source-level
duplication in `place_transform.py` (which already runs pre-typecheck) and
each copy is then checked as an ordinary method. Mangling needs ZERO work —
accessors are already emitted per window result type
(`Grid_[]$1$Int` / `Grid_[]$1$Void`) and the flavor is not in that key.

- **DF-175a — FIXED (design 176 unit 13). A `&self` method may mutate its
  receiver; only the `&var self.<field>` PROJECTION form was checked.**
  The direct-write form is now rejected in both spellings (plain and compound),
  by a walk that tracks TYPES rather than syntax: storage INSIDE the receiver
  (field, nested field, tuple element, optional payload, inline `[T; N]`
  element) is refused, storage the receiver only POINTS AT is not — a `Vector`
  field's heap elements and an `UnsafePointer` field's pointee are shared by the
  copy, not duplicated by it, which is what `TaskHandle.cancel` writes and what
  a purely syntactic walk was rejecting. IN-TREE MIGRATION TAIL: ZERO. Nothing
  in examples/, std, blade, libs, devtools or sos relied on the hole once the
  indirection carve-out was right; the two std hits the first (syntactic) cut
  produced were both `self.cancel_ptr[0] = true`. Tests:
  `examples/errors/shared_self_field_write.saw` (vanishing write),
  `examples/errors/shared_self_borrows_epilogue_write.saw` (the landing one),
  `examples/shared_self_write_alternatives.saw` (the carve-out + `&var self`).
  Original finding follows.
  Design 146, the skill, and `examples/errors/var_ref_into_shared_self.saw`
  all state that a field write in a `&self` method is a hard error "including
  the prologue and epilogue of a borrows body". It is not. The check lives at
  `typechecker/expressions.py:863-889` and covers the `&var self.<field>`
  projection only; DIRECT field assignment (`self.hits = self.hits + 1`) and
  calling a `&var self` method on `self` are both unchecked
  (`_assign_target_immutable_struct_root`, `statements.py:1500-1533`,
  deliberately stops at `SelfExpr`). Two live consequences:
  (1) in a PLAIN `&self` method the write is a **silent no-op** — it lands in
  the by-value receiver copy and is discarded (`p175_plain_self_write_lands`
  prints `hits = 0` after two calls; same on a NoCopy receiver). This is the
  DF-146b bug class through the door that fix does not cover.
  (2) in a `&self` BORROWS body the receiver is by POINTER, so the same write
  **lands** — a pure read through a shared window on an IMMUTABLE root
  mutates it (`p175_shared_window_mutates_let`: two reads of a `let frozen`
  yield `hits = 2`, visible through a `&Grid` parameter too). `let`
  immutability is not holding. Independent of design 175 and worth fixing on
  its own; it is also a PREREQUISITE for `#lend_var`, whose shared copy is
  only as trustworthy as this rule.

- **DF-175b — FIXED (design 176 unit 14). A SHARED place window was enforced by
  use-site classification, not by the window's type.** The window's PARAMETER is
  now bound read-only for the shared flavor (`ClosureParam.place_shared_window`,
  honored where the checker defines a closure parameter) while the closure's
  TYPE keeps the one `(&var T)` shape the declaration lowers to — so the flavor
  stays a use-site property and a misclassification became a compile error
  instead of a silent write. Building it turned up TWO live misclassifications,
  both of which let a `let` root be mutated and both fixed here:
  (1) `_method_mutates` asked `kind == STRUCT`, so a `&var self` method on an
  ENUM element (design 145 gave enums method tables) classified as a read —
  `let frozen = build(); frozen[0].flip()` compiled and mutated;
  (2) `_chain_is_exclusive` did not see an already-lowered INNER window, so
  every CONTAINING window of a nested write came out shared —
  `let frozen = Bag(...); frozen[0][1].count += 10` compiled and mutated, and
  what error there was named the synthesized `__p58`. Both verified against
  unmodified `main` before the fix. Tests:
  `examples/errors/place_window_enum_method_let_root.saw`,
  `examples/errors/place_nested_window_let_root.saw`,
  `examples/place_shared_window_readonly.saw`. In-tree migration tail: ZERO
  (one example, `place_shared_accessor_flavors.saw`, changed VERDICT under the
  half-fix and was correct again once the nested-flavor propagation landed).
  Original finding follows. The declaration
  lowering gives every accessor ONE window closure shape,
  `__window: (&var T) sync -> __R` (`place_transform._lower`), so a window
  classified shared still receives a MUTABLE reference to the element;
  soundness rests entirely on `place_uses._chain_is_exclusive` (:653-672).
  Harmless today (`Data.[]` gates unconditionally), but under `#lend_var` it
  becomes the whole safety property of the shared copy: one misclassified use
  site writes through storage a sibling `Data` shares and value semantics
  break silently. Fix is small — give the shared specialization a genuinely
  immutable window `(&T) sync -> __R` — and retroactively hardens every
  existing accessor. THE risk item for design 175; DF-175a is a live instance.

- **DF-175c — OPEN (minor, docs). `--emit-docs` cannot distinguish a
  `&var self` borrows accessor from a plain `&var self` method** — the former
  reports `"self": "borrows-var"`, same as the latter, so window-ness is only
  recoverable from the signature string (`docs_emit.py:425-442`). A `&self`
  borrows receiver correctly reports `"self": "window"`. Cheap fix
  (`"window-var"`); matters more once accessors are flavored.

- **DF-175d — LANDED (design 176 unit 15, folded into units 4/5 as the brief
  directed).** `c.slot(1) = 99` and `v.get(0)?.value = x` both work: a MethodCall
  is an assignment target (the checker refuses one that does not lend a place,
  naming the method), and `_chain_assign_root` walks a place method call as the
  projection it is. The `&var`-argument workaround is retired. Original finding
  follows.
- **DF-175d — OPEN (minor, ergonomics). A NAMED borrows accessor is not an
  assignment target.** `c.slot(1) = 99` is a parse error ("Invalid assignment
  target") while `v[i] = fresh` works, so whole-element replacement is
  available through the subscript spelling only; the workaround is a `&var`
  argument (`set_to(&var c.slot(1), 99)`). Same family as DF-146n
  (`m[k]! = v`) — assignment-target grammar has not caught up with places.
  Fold into the places/optional plumbing batch.

- **Composition pessimization (noted, not filed as a bug): an accessor that
  FORWARDS another accessor's place** (`lend self.inner[i]`, which works —
  `p175_nested_forward`) lowers to `__window(&var X)`, so the inner accessor
  would always select the EXCLUSIVE specialization under `#lend_var`, even
  from the outer accessor's shared copy. Sound but pessimizing (a shared read
  of a nested CoW would separate). Fixable by propagating the enclosing
  copy's flavor into the lend's inner place; state as a v1 limit if deferred.

## Design 179 findings (`#lend_var`, Aug 7 — IMPLEMENTED, six units)

Brief: `designs/179-lend-var-implementation.md`; the SPEC is design 175's
report. The report's architecture claim held in full — the duplication point in
`place_transform` retargeted cleanly, `place_uses` picks the specialization by
NAME, and mangling needed ZERO work (an accessor's symbol key is the window's
result type `__R`, and the flavor was never in it).

- **DF-179a — FIXED (unit 2). A mistake in the part two specializations SHARE
  was reported once per specialization** — same text, same line, twice. A
  flavored accessor is two methods over one piece of source, so this is
  structural rather than incidental. `ErrorReporter.error` now drops an error
  identical in kind, message, hint AND position to one already reported; the
  warning path has deduplicated on the same grounds since design 150.

- **DF-179b — FIXED (unit 2). A `&var self` METHOD CALL on `self` inside a
  `&self` body was unchecked** — the second form DF-175a named, and the half
  design 176 unit 13 did not close (it scoped itself to the direct write). In a
  plain `&self` method the mutation lands in the by-value copy and vanishes; in
  a `&self` BORROWS body the receiver travels by POINTER, so it LANDS — two pure
  reads of a `let frozen` grid left its counter at 2, visible through a `&Grid`
  parameter too. Verified on the pre-179 tree (9d5ce84) with no `#lend_var` in
  the repro, so it was live on main and design 179 did not open it. The rule
  closed here is the DECIDABLE half: the receiver must be `self` ITSELF, where a
  `&var self` method takes the whole receiver exclusively and no design blesses
  doing that through a shared borrow. IN-TREE MIGRATION TAIL: ZERO, measured by
  landing the check as a bare error and building the whole corpus (suite,
  blade-bootstrap, sos both arches, the irdet devtool). Tests:
  `examples/errors/shared_self_var_method_call.saw`,
  `examples/errors/lend_var_ungated_receiver_mutation.saw`. **DF-176b (the FIELD
  receiver) is untouched and still wants its own ruling** — design 149 receives
  a struct holding an `Atomic` by pointer even at `&self`, so interior
  mutability through a field is an idiom, not a bug, and that carve-out is
  exactly what makes the field form a separate question.

- **DF-179c — FIXED (unit 4). A gate written as the LAST thing in a body was not
  pruned.** A block's final expression statement is its `final_expr`, not a
  member of its statement list, and the fold only pruned statements — so a
  constant `if` in tail position kept both branches and the untaken one was
  still CHECKED. That is exactly where an EPILOGUE gate goes, so the shape the
  feature most wants was the one it got wrong. Pruning now handles the tail,
  splicing the taken branch's statements out and adopting its own tail as the
  block's value, which preserves the value and is therefore correct in
  expression position too. Found by `examples/lend_var_epilogue_nesting.saw`.

- **Forwarded inner accessors are always exclusive — STATED v1 LIMIT, not a
  bug.** `lend other[i]` lowers to `__window(&var other[i])`, so a forwarded
  inner accessor is reached exclusively whichever specialization of the OUTER
  one is running: a shared read through a wrapper runs the inner gate, and a
  shared read of a NESTED copy-on-write buffer would copy. Sound, only wasteful.
  The design-175 report predicted it and named the fix — propagate the enclosing
  copy's flavor into the lend's inner place, which `place_uses` has the
  information for. Pinned with its cost printed in
  `examples/lend_var_coro_and_forwarding.saw`.

- **DF-175c stays OPEN** (`--emit-docs` cannot tell a `&var self` borrows
  accessor from a plain `&var self` method). The synthesized twin needed no
  suppression work — its reserved `__` name already falls under `docs_emit`'s
  synthetic-declaration filter — so the flavor note was not the trivial change
  the brief made it conditional on, and 175c is left as filed.

## std.Data findings (Aug 7, user-prompted archaeology) — CLOSED by design 165

**DATA-1 and DATA-2 are both closed BY CONSTRUCTION** (design 165, Aug 7).
`Data` was rebuilt as a copy-on-write value over `Arc`: storage is
`Arc<DataBuf>?` plus an offset and a length, the hand-rolled refcount and its
`unsafe` allocation bookkeeping are gone, and the tier moved NoCopy →
ImplicitCopy. DATA-2 dissolved because every mutation now takes one uniqueness
gate (`Arc.with_unique`), so CoW-everywhere is the only path that exists —
the ratified behavior change is that a byte `set` through a slice-sharing
`Data` no longer writes through. DATA-1 dissolved because `DataIterator` holds
a `Data`, and holding a `Data` is holding a retain
(`examples/data_iter_outlives_source.saw`, also in the Guard Malloc lane).
The two RESOLVED entries below are kept as history.

Findings raised while building it:

- **DF-165a (FIXED at 165 integration, main): the rt cache key now digests the
  WHOLE input set** — the compiler tree (codegen decides layout), builtin.saw
  and all of std, beside the rt sources it already tracked (`rt_build.py`
  `_compiler_and_lang_inputs`, key tag v2). The 164 key lesson applied: a
  curated subset IS the bug class. Cost: single-digit ms per compile + one rt
  rebuild after any compiler/std edit. Original finding follows.
  `.build/rt/`'s cache key did not track
  `sawc/std/*.saw`. Editing any std file leaves the cached hosted runtime
  objects built from the OLD std; the next program links a mismatched runtime
  and HANGS at startup. It presents as a mass failure with no compile error —
  328 to 567 suite tests "timed out at runtime" — and it looks exactly like
  contention or a sibling's codegen regression, which is where the time goes.
  `rm -rf .build/rt` fixes it. Anyone editing std today has to know to do that,
  which is the argument for keying the cache on the std sources (or stamping a
  digest into the cached objects and revalidating). Cost me roughly an hour;
  it will cost the same to every agent that edits std until it is fixed.
- **DF-165b (COMPILER, FIXED in this brief): a bare integer literal assigned
  into an indexed PLACE did not adopt the element's fixed width.**
  `v[0] = 7` on a `Vector<UInt8>` type-checked the literal with no expected
  type in force, so it stayed platform `Int` and reached codegen as a
  `store i64` into an `i8*` — `internal compiler error: cannot store i64 to
  i8*`, on a line with nothing wrong with it. The same gap meant no range check
  ran, so `v[0] = 256` was the ICE rather than a diagnostic naming 256. The
  assignment path had every other expected-type propagation
  (`_apply_literal_expected_type` at a `let`, a `static` write, a tuple
  element) and was missing this one; one call added in
  `statements.py`, covering fixed arrays, pointer element writes and `borrows`
  places alike. Regression tests
  `examples/df165b_place_literal_width.saw` (+ `_range_error`). Predates design
  165 and reproduces on a bare `Vector<UInt8>`.
- **DF-165c evidence, same day:** the strict `&var self` choice for `Data.[]`
  broke real code at 165's own integration — devtools/irdet's `same_bytes`
  read `a[i]` on `let` bindings and stopped compiling; switched to `get(i)!`
  (integration commit). One data point for the `_read`/`_modify` split when
  design 171's probe round runs.
- **DF-165c — CLOSED (design 179). `#lend_var` is the answer**: a compile-time
  constant, legal only in a `borrows` body, naming the specialization being
  compiled, so a CoW type puts its uniqueness gate where only writes reach it.
  `Data.[]` is `&self` again and the gate is ABSENT from the shared copy rather
  than skipped in it (checked in the emitted IR: `Data_[]$1$UInt8` calls only
  the panic seam, `Data___lend_var_[]$1$Void` calls `Data__make_ready`). The
  three sites the strict choice broke are back to what their authors wrote —
  devtools/irdet's `same_bytes` (`a[i] != b[i]`) and both serde169 encoders
  (`self.out.push(bytes[i])`) — and `data_cow_*` stayed green throughout.
  `get(i)` is unaffected: DF-146j's panic-vs-None pairing survives, and the
  accidental "`get` is the only shared read" asymmetry is gone. Original
  finding follows.
- **DF-165c (LANGUAGE, filed): a `borrows` accessor cannot see its window's
  flavor, which forces a copy-on-write type to choose between a copying read
  and a write-through write.** Design 141 decided the use site picks shared vs
  exclusive out of ONE `&self` declaration and the body is polymorphic over
  that choice. A CoW container needs the opposite: it must separate shared
  storage BEFORE lending a place that might be written, and must NOT separate
  for one that will only be read. With no way to branch, `Data.[]` takes the
  strict option — `&var self`, gate in the prologue — so `d[i]` needs a `var`
  binding and the first indexed READ of shared storage copies. `get(i)` covers
  the shared read, so nothing is unreachable, but the ergonomics are worse than
  Swift's, which solves it with a `_read`/`_modify` accessor pair. If a second
  CoW type ever wants a subscript, splitting `borrows` into read and modify
  bodies is the fix; one type does not justify the language change.

## Design 169 part 2 — std.cbor itself (LANDED, Aug 7)

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

- **The contract is already frozen and already tested.** `sawc/std/CBOR.md` is
  the profile note (the rt/ABI.md pattern), and `tests/cbor_vectors/` holds 32
  accept + 19 reject blobs that `tools/sawcbor.py verify` checks against an
  independent `cbor2` reader today. The Saw encoder/decoder is the SECOND
  implementation of a spec that already has a passing first one — write it to
  the vectors, not to the RFC.
- **The seam it plugs into is done.** A concrete encoder conforms to `Encoder`
  and a decoder to `Decoder` (`sawc/std/serde.saw`); both are object-safe and
  travel behind `&var any`. `examples/serde169_hand_written.saw` and
  `examples/serde169_derived.saw` each carry a complete miniature codec written
  against those traits, so they double as worked examples of what `std.cbor`
  must implement.
- **Units 3 and 4 are ONE job, not two.** The limits are not a wrapper over a
  finished decoder: the design decided in this dispatch is that `CborDecoder`
  validates the whole input against `max_depth`/`max_size`/`max_items` in an
  up-front structural scan driven by an EXPLICIT work stack, then typed reads
  run over bytes already known to be well-formed. Depth is the stack's height,
  checked BEFORE descending, so the decoder never recurses on input and a
  hostile blob cannot reach the call stack at all. Build the scan first.
- **Unit 6 should be the blade lock file**, not sosimg (which has a parked M1b
  branch under it). `blade/src/lock.saw` is columnar today (five parallel
  `Vector<String>`); the CBOR shape is a `LockEntry { name, version, source,
  loc, rev }` plus `Vector<LockEntry>`, which the unit-2 derivation already
  covers end to end — `Vector<T>` of a conforming struct is a supported walk.
- **`std.cbor` is import-required**, unlike `std.serde`: add `"cbor"` to
  `IMPORT_REQUIRED_STD_MODULES` in `sawc/sawc.py`. `std.serde` stays out of that
  set on purpose (prelude-visible), because a derived body names `Encoder` and
  `DecodeError` bare and must resolve them however the user wrote their imports.

## Design 169 — DF-findings (Serialize/Deserialize + std.cbor, units 1/2/5 LANDED)

- **DF-169a — `&concrete` did not erase to `&any Trait` in a METHOD argument.
  FIXED** (commit before unit 1). Design 51's call-boundary erasure ran on the
  free-function argument path alone (`_try_existential_arg_coercion` had one
  call site). An instance method, a static method, a trait-required method and
  every overload set holding an existential parameter all rejected a concrete
  reference their signature accepted — the overload case failing during
  CANDIDATE SELECTION, before the argument pass could erase anything, so no
  amount of fixing the argument loops alone would have helped. Found
  immediately: design 169's trait pair is method-based
  (`func serialize(&self, to: &var any Encoder)`), so literally nothing could
  call it. Three argument loops gained the coercion; candidate selection gained
  `_erasure_compatible`, scored so an exact concrete overload still outranks the
  erasing one. Second half: forwarding an ALREADY-erased `&var any T` onward
  (design 106 re-borrow) is a pass-through, not a second erasure — it used to
  reach the conformance lookup with `any T` in the "concrete" slot. Repros:
  `examples/existential_arg_method.saw`,
  `examples/errors/existential_arg_wrong_trait.saw`.
- **DF-169b — `any Deserialize` was accepted, and a static requirement was
  invisible to object safety. FIXED** (unit 1). Two independent holes in
  `_check_object_safety`: (1) it read only the OUTER type kind, so a
  `-> Result<Self, DecodeError>` requirement passed while a bare `-> Self` was
  caught — the vtable thunk would have had to return a value whose size it does
  not know; (2) a requirement declared with no `self` (STATIC — called on the
  type) was not considered at all, though there is no receiver to dispatch on
  and `_trait_slot_fn_type` assumes `param_types[0]` is the self placeholder.
  `_names_self` now walks generic arguments, and `TraitMethodSymbol.is_static`
  is recorded at trait registration and rejected at the existential. Repro:
  `examples/errors/serde169_deserialize_not_any.saw`.
- **Not a bug, recorded — the serde vocabulary cannot live in `builtin.saw`.**
  `--runtime-build` skips std entirely, so an `extension EncodeError: Printable`
  in builtin.saw synthesizes design-56's `to_string` default body against a
  `StringBuilder` that is not loaded, and the runtime build fails with eight
  errors inside builtin.saw itself. The existing `trait Printable` survives only
  because it has no CONFORMERS there. Home is `sawc/std/serde.saw`: a std file
  is skipped in runtime-build, kept in freestanding, and — by staying out of
  `IMPORT_REQUIRED_STD_MODULES` — prelude-visible, which is also what makes a
  derived body's bare `Encoder`/`DecodeError` resolve regardless of how the user
  imported anything.
- **DF-169c — a derived body could not walk a `Vector` until serde went `sync`.
  FIXED by design, not by a workaround** (unit 2). The derived walk reads
  elements as PLACES, and a place window is a `sync` context (design 141), so
  `self.deps[i].serialize(to:)` failed with "cannot suspend in a `sync` closure
  context: a call through `any Encoder` dispatch". Rather than route the walk
  around places, every requirement in `std.serde` now carries the `sync` effect.
  That is the honest contract — serialization writes into a buffer — and it buys
  more than it costs: a value can serialize inside a place window, under a
  `SpinLock`, or in a kernel, and a conformer that wants I/O is pushed to write
  the buffer first and send it afterwards. Worth knowing generally: any trait
  whose implementations are meant to be callable from a place window, a lock
  body or a `Deinit` must declare `sync` on its requirements, because dispatch
  through `any Trait` is assumed suspending otherwise.
- **DF-169d — FIXED (design 176 unit 6), the a-lite shape exactly as decided.**
  EVERY primitive registers an extensible pseudo-struct now (Int, UInt, the
  eight fixed-width integers, Bool, Float, String), so declaration acceptance,
  direct dispatch and generic-BOUND participation are uniform — the wire case
  `<T: MyProto>` at `T = UInt8` included, monomorphized with no vtable. Four
  places had hardcoded the Int/Float/String subset and each now reads one
  table: `_PRIMITIVE_CONFORMANCE_KEYS` (namespace, plus a
  `primitive_conformance_key` accessor), `_PRIMITIVE_EXT_KINDS` (codegen
  receiver types + method base), the checker's method-call receiver mapping,
  and codegen's receiver naming. ERASURE to `&any`/`Box<any>` is ONE clean
  error for every primitive, naming both outs (generic bound / wrapper struct);
  the `String` `i8* != i8**` codegen ICE and the Int/Float "does not conform"
  both fold into it. Boxing stays additive — if it ever lands the error simply
  becomes working code. In-tree migration tail: ZERO. Tests:
  `examples/primitive_conformances.saw`,
  `examples/errors/primitive_erasure_refused.saw`,
  `examples/errors/primitive_box_erasure_refused.saw`. Original finding follows.
- **DF-169d (filed Aug 7, user-prompted full matrix — SUPERSEDES the VERIFY
  note below): primitive user-conformances are broken at three layers.**
  Probed every builtin: `extension T: MyTrait` is ACCEPTED for exactly
  Int/Float/String and REJECTED ("cannot extend undefined struct") for UInt,
  all eight fixed-width ints, and Bool — an arbitrary split. For the accepted
  three, DIRECT calls work but `&any Trait` erasure fails: Int/Float "does
  not conform" (the conformance never registers for existentials), String
  ICEs in codegen (`i8* != i8**`). No Char type exists (by design). Probes:
  .build/scratch/probe_primitive_ext*.saw. **DECIDED (user, Aug 7): a-lite.**
  Uniform declaration acceptance for EVERY primitive + full GENERIC-BOUND
  participation (monomorphized, no vtable — covers the wire-vocabulary case
  `<T: MyProto>` at T=UInt8); `&any`/`Box<any>` erasure of a primitive is a
  uniform CLEAN ERROR naming the two outs (generic bound, or a wrapper
  struct) — never an ICE, never a per-type split. Boxing (full (a)) stays
  additive later if demanded: the clean error would just become working
  code. JOINS THE PLACES/OPTIONAL PLUMBING BATCH (with DF-146j/l/m/n/o).
  `extension Int: SomeTrait { ... }` compiles and runs; `extension Bool: ...`
  is `cannot extend undefined struct `Bool``. Not needed by this brief (the
  derivation dispatches on the field's type and emits the encoder call directly,
  the `_emit_hash` precedent), so it was routed around rather than fixed, but
  the asymmetry is real and worth a probe before anyone relies on either half.
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

`as` between integer types traps on an unrepresentable value; `T.from(x)` is
the `None`-returning twin and `T.from(truncating: x)` the deliberate wrap.
Follow-ups and findings the sweep produced:

- **DF-170a (CLOSED by design 180, Aug 8): `rt_sleep_ms` wrapped past ~35
  minutes.** `usleep` takes microseconds in a 32-bit slot, so
  `sawc/rt/common/sleep.saw` had always truncated `ms &* 1000` into it, and a
  sleep of 2_147_484 ms or more returned early and silently. Closed BY
  CONSTRUCTION rather than by a check: the seam is `__saw_rt_sleep_ns(u64)`
  now and chunks to libc's bound in a clock-corrected loop, so every span the
  type can hold is served in full. The API above it cannot spell an
  unrepresentable request either — `sleep` takes a `Duration`, whose UInt64
  nanosecond backing reaches about 584 years.
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

## std.Data findings (Aug 7, user-prompted archaeology)

The three historical "known issues" in data.saw's header, resolved or filed
(user asked about the line-506 segfault note; probed from the public surface —
push into a sliced Data drove `_reserve_unique` → `_make_unique`):

- **RESOLVED — `_make_unique` CoW "segfaults."** The path is sound today:
  0/50 native + 0/20 Guard Malloc failures, values correct. The crash class
  the old comment described (assign `old_data.inner` to `self.inner`, both
  halves release) matches the compiler defects fixed this week (DF-151h
  assignment-RHS aliasing, DF-151c destination-type glue, design 159 field
  retains). Comment replaced with the real invariant (pre-incremented
  refcount cancelled by the local copy's deinit); regression test
  `examples/data_cow_slice.saw` (also in the gmgate lane).
- **RESOLVED — "memcpy causes segfaults" in `copy()`.** The archived memcpy
  was offset-correct; the crash was compiler-era. `_fill_from` is one
  offset-aware-on-both-sides memcpy again (hot-path win over the per-byte
  get/set loop); the same test pins copy-from-slice and copy-from-whole.
- **DATA-1 (CLOSED, design 165): DataIterator held no reference.** `iter()`
  copied `inner` without bumping the refcount, so an iterator RETURNED past
  its Data's death dangled (use-after-free reachable from safe code). The
  rebuild dissolved it rather than patching it: `DataIterator` holds a `Data`,
  and a `Data` IS a retain. The anticipated complications did not arise — the
  iterator is `ImplicitCopy` (the tier its `Data` field carries), and the
  design-122 `T: Copy` iterator bound is on the ELEMENT (`UInt8`), so for-in is
  untouched.
- **DATA-2 (CLOSED, design 165; user ratified the behavior change): `set()`
  wrote THROUGH a shared buffer while `push()`/`append()` copied on write.**
  Resolved as option (a), CoW everywhere: every mutation takes one uniqueness
  gate, so a byte set through a slice-sharing `Data` is no longer visible to
  the slice. This is a BEHAVIOR CHANGE and was approved as one. Pinned by
  `examples/data_cow_value_semantics.saw`.

## Review sweep (Aug 4) — TRIAGED (user, Aug 4 evening), briefs 122-127
Four reviewer reports in `designs/reviews/2026-08-04-*.md`; probe repros live
there. Triage outcome: **122** fix batch (RS-2/4/5, RC-1/4/5, P2, DF-119b —
wave 1); **123** allocator-failure policy pass, design-19 tiers (RS-1 — wave
2); **124** TaskGroup EAGER teardown (RS-3, user chose scope-not-extender —
wave 2); **125** docs sweep + README catch-up + README joins the docs
convention + soften no-hidden-allocations (P3 — wave 1; the SOFTENING is now
REVERSED, see design 135 below); **126** pre-port trio
R1/R2/R11 incl. the RC-2 substitution bug (wave 1); **127** op-budget loop-
backedge preemption (RC-3, user chose fix-not-soften — wave 2); **128/129
DRAFTS** (Deinit/ExplicitCopy synthesis — LANDED, see below;
newlines-in-brackets) awaiting user
review — DO NOT DISPATCH. Original ranked findings follow for reference.

**146 LANDED (Aug 5-6) — units A-D complete, and the P0 pair with them.** The
Aug-6 continuation closed DF-146e, DF-146f, DF-132a and DF-128c; suite 1275 ->
1283. Read this before the 141 entry below, which it supersedes on the use-site
question.

- **DF-146e / DF-146f closed (commit c943680).** `copy_tier` gained a fifth
  answer, `abstract` — the demands-a-bound tier for a type mentioning a type
  parameter. It joins as the strongest (the unknown may be move-only) and every
  pre-existing consumer treats it exactly as it treated `free`, so the only
  behavior change is the one intended: a place value read asks the BOUNDS
  instead of guessing, and the copy is emitted at the instantiation alongside
  the drop. Two emission-side defects fell out of the same asymmetry:
  `is_implicit_copy_enum` judged a generic enum's payloads UNSUBSTITUTED (so
  every generic enum answered False), and `_get_cleanup_behavior` cached that
  answer under the BASE name, so `Slot<K>` decided for `Slot<Res>`.
- **The Map/Set migration + the front half's re-entry (commit b626a4b).** Map's
  probes match through the slot; Set inherits all of it. That made the place
  re-entry universal (std/map.saw is in every program), which surfaced NINE
  pre-existing latent defects — a program using `v[i]` plus any of these
  features did not compile on main either. All four roots are fixed and pinned
  by `examples/place_reentry_idempotent.saw`. See DF-146g below.
- **The P0 pair (commit f4222fd).** `Vector.get` is `borrows -> T?`;
  `_type_method_base` fills default type arguments. Restoring the drop glue made
  two more live double-frees real, both recorded as DF-146h and DF-146i below.

**DF-146d LANDED (Aug 6), half of it.** The enum-payload place and `Map.[]` are
in; the Set half is blocked on a language gap (DF-146k). Three PRE-EXISTING bugs
came out of the work and are fixed as their own commits — a closure that never
captured a name used in a string interpolation (DF-146q), a place window whose
flavor was always read as shared (DF-146r), and a struct field of enum type that
never dropped its payload (DF-146s). One new P0 is OPEN and needs a decision:
`Map.get` over-releases a move-only value (DF-146j).

- **Unit A DONE.** `_prepare_codegen` re-enters over the ASTs it already parsed
  (`parsed=`: module map, module sources, and the builtin+std AST from before
  `_filter_std_ast` narrows it). Front half on a re-entering program: 451 -> 310
  ms, 503 -> 359 ms, 485 -> 345 ms, 483 -> 320 ms across the sample — 29-34%
  off; a non-re-entering program is unchanged (242 -> 252 ms, noise). Reuse
  means the second pass re-checks objects the first pass touched, which
  surfaced two latent defects, both FIXED here: **DF-146a** (below) and the
  coroutine transform DESTROYING imported std method bodies — a nested
  suspending std method's frame is built by a builder that hoists/ANF/state-
  splits the body IN PLACE, and the code relied on the re-parse to undo it
  ("it re-parses fresh on the recursive pass anyway"). Imported methods now
  build from a copy. Commit 9f7e5dd.
- **Unit B LANDED for UNCONDITIONAL accessors, fenced elsewhere.** A place use
  is recognized by the checker (`typechecker/places.py`: `v[i]` against a `[]`
  accessor, `v.name(...)` against a named one — the window closures are
  compiler-added trailing parameters, so the ordinary arity path would count
  them against the author) and lowered post-typecheck by the new
  `sawc/place_uses.py`. Working, with `examples/place_use_sites.saw` as the
  oracle: both flavors from ONE declaration, window extent = the smallest
  expression that turns the place back into a value, chained windows
  (`b[0][1].count += 10` is two nested windows), `f(&var v[i])` call-spanning
  windows, value reads through the copy-tier table, and the LIFO epilogue
  ordering (which comes free from nesting). `__R` is passed EXPLICITLY as the
  accessor's one type argument, taken from the replaced expression's
  `resolved_type` — nothing about the window has to be inferred. Exclusivity
  needed NO new checker rule: a place use is still syntactically `v[i]` when
  `_build_access_path` runs, so `f(&var v, &v[i])` and the `[&var v]`-capture
  probe are already the existing Law-of-Exclusivity shapes. TWO FENCES, each a
  clean teaching error, each a design question below: DF-146b (exclusive window
  through a `&self` accessor) and DF-146c (calling a conditional lend).
- **Unit C MOSTLY LANDED (commits f068004, 3c2c8d4, plus the docs commit).**
  DF-146b and DF-146c are CLOSED, so every use-site shape design 141 specified
  now works. `Vector.[]` and `Data.[]` are places; libs/toml publishes
  `TomlDoc.section(name) borrows -> TomlSection?` (replacing `get_section`,
  which returned a NoCopy section by value), `index_of` + `section_at(i)`,
  `has_section`, and `TomlSection.table(key)`; blade's call sites migrated.
  Docs landed: the unified spec Places section (with the DF-146b callout), the
  skill, README. **The DF-132a / DF-128c P0 pair landed Aug 6 (commit
  f4222fd)**, after DF-146e and DF-146f cleared the way; the retain oracle is
  unchanged, so trivial and ImplicitCopy callers behave exactly as before.
  Ceremony converted: 8 `if let x = v.get(i)` index-loop reads inside
  libs/toml became place borrows, plus 5 `get_section` call sites in blade and
  2 in examples. ZERO `with_ref`/`with_var_ref` CALL sites were converted: the
  only ones in the tree are taskgroup's 7, and design 141 keeps with_ref as the
  multi-statement/long-window spelling rather than deprecating it — converting
  the most fence-laden file in std for a cosmetic win was not worth the risk to
  the 124/134 fences.
- **Unit D DONE.** See the DF-126b entry below for the strengthened gate and
  its measured cost.

- **DF-146a — FIXED (design 146 unit A). A `@synthesize` type in a program that
  uses concurrency did not compile.** Registration was not idempotent: each
  derivation writes its synthesized `copy`/`equals`/`compare`/`hash` back into
  the extension, and the coroutine transform re-runs the whole front half over
  the entry AST, so the second registration read the compiler's own body as a
  hand-written one and reported "``@synthesize`` on `extension T` derives
  nothing" against a correct program. Live on main since design 128 met design
  44. `_derivation_slot` now separates "an author wrote one" from "we derived
  one already". Regression test:
  `examples/synthesize_across_coro_reentry.saw` (fails before the fix).

- **DF-146b — CLOSED (design 146 unit C, commit f068004).** Option (a) is
  implemented in full. The checker half already existed; the missing half was
  the ABI. A lowered borrows accessor is marked `place_self_by_pointer`, and
  codegen reads it through the new `ast_nodes.self_by_pointer` alongside
  `self_mutable` at the five sites that decide how a receiver travels — so a
  `&self` accessor's receiver arrives as storage and an exclusive window writes
  through it. `noalias` stays keyed on `self_mutable` alone, because two shared
  windows on one root may coexist. The polymorphism is confined to the `lend`:
  its `&var` is marked `from_lend` and is the single exception to a NEW hard
  error, `&var self.<field>` inside a plain `&self` method — which is the
  original finding below, live in the tree since the first `&self` method and
  fixed here. A borrows accessor must also take its receiver BY REFERENCE.
  Oracles: `examples/place_shared_accessor_flavors.saw` (both flavors from one
  `&self` declaration, chained windows, an epilogue, a `let` root for a shared
  window) and `examples/errors/var_ref_into_shared_self.saw` (the general
  fence), which replaced `examples/errors/place_exclusive_shared_accessor.saw`.
  DOCS MANDATE DISCHARGED: the spec's Places section carries the callout as a
  block quote, the saw-lang skill has it as the first Gotcha, and `--emit-docs`
  reports such a receiver as `"self": "window"` rather than `"borrows"`
  (`examples/doc_emit_borrows.saw`). Original decision and finding follow.

  DECIDED (user, Aug 5): OPTION (a), use-site-derived window
  mutability, confined to the lend expression. The rule: a borrows body is
  a `&self` body whose LEND inherits the window's flavor; the general
  `&var self.<field>`-under-`&self` fence stays a hard error everywhere else.
  **DOCS MANDATE [user]: call the inconsistency out VERY clearly** — spec
  Places section gets a prominent callout + the skill a gotcha entry:
  "`borrows` changes what `&self` means: the receiver is borrowed with the
  window's flavor, decided at each use site — the one place a `&self`
  spelling does not mean shared-only" — and `--emit-docs` renders a borrows
  receiver honestly (window-flavored, not `borrows`=shared). Owned by the
  146-C continuation. Original finding follows: `&var self.<field>`
  inside a `&self` method compiles and silently writes to a COPY** (found by
  design 146 unit B, Aug 5; PRE-EXISTING, nothing to do with places). A `&self`
  receiver is passed by value, so every `&var` projection out of it addresses
  the callee's copy. No error, no warning, no write. Repro:

  ```saw
  struct Cell { count: Int }
  struct Bag { slot: Cell, cells: [Cell; 3] }

  extension Bag {
      func shared_field<R>(&self, body: (&var Cell) sync -> R) -> R {
          body(&var self.slot)          // writes a copy
      }
      func shared_elem<R>(&self, i: Int, body: (&var Cell) sync -> R) -> R {
          body(&var self.cells[i])      // writes a copy
      }
      func var_field<R>(&var self, body: (&var Cell) sync -> R) -> R {
          body(&var self.slot)          // writes the real thing
      }
  }

  func main() {
      var b = Bag(slot: Cell(count: 0),
                  cells: [Cell(count: 1), Cell(count: 2), Cell(count: 3)])
      b.shared_field { c in c.count += 10 }
      print("{b.slot.count}")       // 0   -- want 10, or a compile error
      b.var_field   { c in c.count += 10 }
      print("{b.slot.count}")       // 10  -- correct
      b.shared_elem(1) { c in c.count += 10 }
      print("{b.cells[1].count}")   // 2   -- want 12, or a compile error
  }
  ```

  Design 106 already says a `&` may not upgrade to `&var` and gives a clean
  error for a reference PARAM; `self` was never covered. On its own the fix is
  "make it that same error" — but it is load-bearing for design 141 decision 3
  ("mutability comes from the USE SITE, never the declaration — one body serves
  both flavors"), because the shape 141 blesses is exactly
  `func [](&self, i: Int) borrows -> T` with `lend self.buffer![i]`, which
  lowers to `__window(&var self.buffer![i])`. So the landed
  `examples/borrows_declaration_lowers.saw` declares accessors that would
  silently not write. THE DECISION: either (a) an accessor's receiver is
  borrowed per the USE SITE — the checker half of that is already implemented
  (`place_window_exclusive` makes an exclusive window demand a `var` root and
  join the access set as a mutable path), and what is missing is passing the
  receiver by pointer rather than by copy; or (b) retreat from decision 3 and
  let a `borrows` accessor declare `&var self` when it lends writable storage,
  which is what the landed fence already requires and what
  `examples/place_use_sites.saw` is written against. Until it is decided, an
  exclusive window on a `&self` accessor is a clean error naming the `&var
  self` spelling (`examples/errors/place_exclusive_shared_accessor.saw`).

- **DF-146c — CLOSED (design 146 unit C, commit f068004).** Calling a
  conditional lend works, in every shape: the present path through `!` (shared
  and exclusive windows), a value read binding the payload, `&var v.at(i)!` as a
  call-spanning argument, the absent path opening no window, and an epilogue
  that runs only on the lending path. Oracle:
  `examples/place_conditional_lend_uses.saw`. Three type-threading fixes, not
  the one the original diagnosis predicted:
  (1) a `!` applied DIRECTLY to an optional place is CONSUMED by the lowering —
  the window parameter is already the payload, so leaving the `!` on
  force-unwrapped a non-optional;
  (2) a closure body checked against a known function type now takes its RETURN
  CONTEXT from that type, so a bare `None` in tail position learns what it is a
  `None` of AND a tail value auto-wraps into an expected optional, exactly as a
  function body's does — the absent path `{ None }` and the present path
  `{ __p in __p }` both needed it;
  (3) a closure whose body DIVERGES satisfies any expected result type, so the
  `{ panic(...) }` absent closure of a force-unwrapped place is an `-> __R`
  function that never returns rather than an `-> Never` one.
  Fix (2) inserts an `OptionalWrap`, which had no typechecker visitor — see the
  fixes listed under unit C; that gap cost 177 suite failures until found.
  Original finding follows. What blocked it: the absent path's closure takes no
  parameters
  and its `__R` does not survive to codegen — the synthesized `{ None }` body
  reaches the backend with `current_return_type=Void`, so the `None` has
  nothing to be a `None` OF (internal error rather than a wrong answer). The
  present path (`{ __p in __p }`, auto-wrapping into a pinned `__R = T?`) is
  believed right; the parameterless twin is where the type is lost.

- **DF-146f — CLOSED (user decision folded in, Aug 6, commit c943680).** Yes: a
  pattern that BINDS NOTHING is a presence test, and a presence test is a
  BORROW of the place — legal for every tier, emitting no copy and no drop. It
  is implemented as the GENERAL rule rather than a carve-out, so Map/Set use it
  rather than being special-cased: `if let _` / `guard let _` become the plain
  conditional they meant (the window answers `true`, the absent path `false`),
  and a `match` on a place moves INSIDE the window, where an arm that binds
  binds the payload in place. Two shapes keep the value-read path, because a
  window is a closure: an arm that jumps out of the enclosing function, and an
  arm that `move`s one of its own bindings (destructuring, not reading).
  A `_` on a real Optional still drops the payload — the divergence this entry
  anticipated, and the right one: an Optional binding OWNS its payload, a place
  never does. Test: `examples/place_presence_test_borrows.saw`.
  Landing it required fixing a pre-existing over-release the rule would
  otherwise have inherited: `match` through a `&T`/`&var T` binding took design
  61's CONSUME path, so `case Occupied(_)` released a payload the container
  still owned. That reached every `match` inside a `with_ref` body, and is why
  consume mode now requires an OWNED binding. Original finding follows.
  `_` is blessed as an `if let` /
  `guard let` pattern that binds nothing (design 111), so on a place it takes
  nothing out and the container keeps everything — but the copy-tier table is
  applied to the payload regardless, and a `NoCopy` one is refused:

  ```saw
  if let _ = doc.section("package") { ... }
  // error: `doc.section(…)` lends a place of type `TomlSection`, which is
  //        move-only — reading it out as a value would alias storage the
  //        container still owns
  ```

  The workaround is a `Bool` method, which is the better API anyway (design 92
  blesses a genuine boolean question), and libs/toml now publishes
  `has_section`. But the error is arguably wrong: nothing is read. THE
  QUESTION: should a `_` binding on a place (and on an optional generally) be a
  presence test rather than a value read? It is a one-line carve-out in
  `_value_read_ok` / `_check_payload_read` if the answer is yes, and it wants
  the answer before it is written — the same `_` on a real Optional DOES drop
  the payload today, so the two would diverge.

- **DF-146g — FIXED (Aug 6, commit b626a4b). The front half runs TWICE over one
  AST, and the checker's own rewrites were not idempotent** (PRE-EXISTING —
  every one of these broke a program on main that used `v[i]` and the feature
  together; the Map migration only made the re-entry universal and so made them
  unmissable). Four roots, nine tests, one regression file
  (`examples/place_reentry_idempotent.saw`):
  - Driving or spawning a generic REPLACES the callee with its monomorphized
    symbol and clears the type arguments, so a second pass looked up
    `settle$1$Int` — the name the first pass wrote. The authored form is
    recorded once and restored on every later pass, which re-derives the same
    symbol. (`_restore_authored_callee`, 4 sites.)
  - The checker INSERTS `OptionalWrap` / the three `Result` wraps to fit a value
    into its home, and re-checking judged the wrapped form: `let y: OptInt =
    100` became an `Int?` assigned to a distinct alias, which is not the
    literal-into-distinct rule that admitted it. The place lowering now
    UN-CHECKS the tree it hands on (strips those wraps and the first pass's
    `resolved_type` conclusions), and the `let` binding peels its own wrap
    before deciding again — which also fixes the CORO re-entry, where an
    optional type alias plus any driving did not compile at all, places or no.
  - A synthesized instantiation spliced in by the effect pass was re-checked as
    if the author had written it. Every type in a clone arrived by
    substitution, so design 132's "a Void you can SEE" rule read `let result =
    body(n)` at `R = Void` as a binding of nothing. Its errors were suppressed
    where it was built, for exactly this reason; they are suppressed here too.
  A blanket "reset every annotation" walk was tried and rejected: the lowering's
  own output is annotated the same way, so resetting it re-lowers forever. The
  un-check is deliberately narrow — the checker's inserted wraps and its
  resolved types, and nothing the transform produced.

- **DF-146h — FIXED (Aug 6, commit f4222fd). Assigning to a MOVED-FROM `var`
  dropped the value the move gave away, and never re-armed the binding**
  (PRE-EXISTING, masked by DF-128c). `move x` clears the drop flag; the
  assignment then dropped the old value without consulting it, freeing what the
  receiver now owned, and stored the new value without setting the flag back, so
  that one leaked. `var cur = ...; sink.push(move cur); cur = fresh` is the
  language's own accumulate idiom and `TomlDoc.parse` is built on it — this is
  what crashed Blade's manifest reader with zero output. The overwrite-drop is
  now guarded exactly as scope exit guards its own (`_emit_scope_var_drop`), and
  the assignment revives the binding. Test:
  `examples/move_out_then_reassign.saw`.

- **DF-146i — FIXED (Aug 6, commit f4222fd). A place VALUE READ did not retain
  an owning element that declares no copy policy.** A struct whose only field is
  a `String` needs no policy — the compiler handles the transfer — but it still
  OWNS something, so reading one out of a container duplicates it. The old
  by-value accessor retained it INSIDE its own body, where the read was an
  ordinary indexed one; a place moves the read into the caller, where it arrives
  as a window-closure parameter, and the container-slot rule did not follow.
  `std.directory`'s `Path` is exactly this shape, so `Directory.list` +
  `remove_tree` bus-errored. A place read is now marked and gets the container-
  slot rule; `v.get(i)!` with nothing after it counts as one (and gets the tier
  check it was also missing). Test: `examples/place_read_retains_owning.saw`.

- **DF-146d — CLOSED for the Map half, BLOCKED for the Set half (Aug 6).** The
  enum-payload place landed as specified and `Map.[](key) borrows -> V?` with
  it. The Set equivalent did NOT land, and the reason is a language gap rather
  than an implementation one — see DF-146k below, which needs a user decision.
  What the compiler does now: an arm of a BORROWING match may `lend` one of its
  payload bindings. The place transform gained a TAIL mode (in a block whose
  value is the accessor's result, the window call stays an expression instead of
  becoming a `return`, which is what lets `_borrow_match` move the whole match
  into the window — an escaping arm cannot); it CLAIMS the lend on the arm and
  requires the scrutinee to be storage reached through `self`; the checker
  exempts a `from_lend` `&var` from the immutable-binding rule as it already
  does from the `&var`-out-of-`&self` rule; and codegen writes the lent binding
  back into the scrutinee when the window closes.
  The write-back is deliberate, not a shortcut. An enum is
  `{ i32 tag, [N x i8] payload }`, so a pointer INTO the payload carries only the
  tag's alignment and would be under-aligned for whatever the payload holds —
  aliasing it would hand a mis-aligned `&var T` to the window and to everything
  the window calls. Copy-in/copy-out is indistinguishable from aliasing here
  because the window borrows the scrutinee's ROOT for its whole extent, so
  nothing else can read the slot while the payload is out; that is also where
  tag stability comes from, free.
  Tests: `examples/place_enum_payload_lend.saw` (borrow twice with no copy, a
  write that lands in the slot, an epilogue inside the lending arm, a diverging
  arm beside it), `examples/map_subscript_place.saw`,
  `examples/map_subscript_retain_oracle.saw`,
  `examples/errors/lend_payload_not_receiver_storage.saw`,
  `examples/errors/map_subscript_immutable_root.saw`,
  `examples/errors/map_subscript_nocopy_value_read.saw`. Docs: the spec's
  Places chapter gains "Lending an enum payload" and its std-accessor section
  now documents the Map subscript (and why Set has none); skill + README updated.
  Three PRE-EXISTING bugs were found on the way and fixed as their own commits —
  see DF-146q/r/s. Original finding follows:
  **`Map` gets no subscript: a place cannot project into an
  ENUM PAYLOAD** (found by design 146 unit C, Aug 5). Design 141 lists
  `func [](key: K) borrows -> V?` on Map as v1 scope, and it is not expressible
  over the current slot representation. A map's value lives inside
  `MapSlot.Occupied(key: K, value: V)`, and `lend` accepts an
  Identifier/MemberAccess/ArrayIndex/TupleIndex/deref — `Optional`'s `!` is the
  only enum-payload place the language has. Reaching the payload through a
  `match` binds a LOCAL, which is both a copy and immutable:

  ```saw
  enum Slot { case Empty, case Occupied(key: Int, value: Int) }
  struct Table { slots: [Slot; 2] }
  extension Table {
      public func [](&self, i: Int) borrows -> Int? {
          if i < 0 || i >= 2 { return None }
          match self.slots[i] {
              case Occupied(k, v) -> { lend v },   // error: cannot take mutable
              case Empty -> { return None }        // reference to immutable `v`
          }
      }
  }
  ```

  Two ways out, both real work: a general enum-payload place projection (a
  language feature — it would also give `if let` a borrow form), or a Map slot
  representation whose value is nameable storage (parallel state + `Optional<
  (K, V)>` entry vectors, so `slots[b]!.1` is a place). The second re-opens the
  deinit-safety property design 48 deliberately bought with payload-free
  `Empty`/`Tombstone` variants. Not a patch either way. Vector and Data have no
  such problem — their elements are storage already — and both landed.
  (Resolution: the first way out, and it did not need the slot representation to
  change.)

- **DF-146j — FIXED (design 176 unit 3).** `Map.get` is now `borrows -> V?`
  with the same body as `[]` — one conditional lend, two names. The copy-shaped
  `get` (the last copy-shaped exception in the places model) is gone, and with
  it the non-retained alias a move-only value used to come out as. AUDIT of
  `get`-result-fed-to-`&var` across std, blade, libs, sos, devtools and
  examples: ZERO, as the brief expected — the single `&var …get(…)!` in the tree
  is a user-defined `borrows` accessor in `place_conditional_lend_uses.saw` and
  is unaffected. In-tree migration tail: ZERO (suite green with no edits).
  `_get_value` stays: `each`/`each_value` still copy whole slots out under their
  `V: Copy` bound. Tests: `examples/map_get_is_a_place.saw`,
  `examples/errors/map_get_nocopy_value_read.saw`. Original finding follows.
- **DF-146j — OPEN, P0 (found Aug 6 while building DF-146d). `Map.get` hands a
  move-only VALUE back as a NON-RETAINED ALIAS, so every lookup over-releases.**
  DF-132a's shape, for Map. Repro — one `Res`, three deinits:
  ```saw
  struct Res { id: Int }
  extension Res: NoCopy { func deinit(&var self) { print("deinit {self.id}") } }

  var m = Map<String, Res>()
  let _ = m.insert("a", Res(id: 1))
  if let r = m.get("a") { print("got {r.id}") }    // deinit 1
  if let r2 = m.get("a") { print("got {r2.id}") }  // deinit 1
  let _ = move m                                   // deinit 1
  ```
  The read is `_get_value`'s `case Occupied(_, v) -> v`: a match-arm binding read
  out of a generic body where `V` has no Copy bound. DF-146e's rule 1 gates a
  place VALUE READ on the bounds; it does not reach an arm binding, so this one
  emits no copy while the caller's binding drops for real. `each` / `each_value`
  / `Map.keys` / `Set.to_vector` all read through the same helper and have the
  same hole (`keys`/`to_vector` are bounded `T: Copy`, so those are safe).
  Design 141 decision 6 already approved the remedy for the accessor —
  "same conversion for Map's optional accessors" — but it is a DESIGN call now
  that `[]` exists, because the two would be the same function: does `get` become
  a place, or go away in favour of `m["k"]`? And the VISITORS are a separate
  question: bounding `each`/`each_value` on `V: Copy` would make
  `Map<String, Vector<Int>>.each` stop compiling. Not decided unilaterally.
  The sound path exists today: `m["k"]` reaches a move-only value with no copy.

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

- **DF-146q — FIXED (Aug 6, commit dbf4ab9; RENUMBERED from DF-146m by design
  176 unit 12). A closure did not capture a name
  used only inside a string interpolation, a BLOCK match arm, or an arm guard.**
  `{ x in "n={n}" }` has never compiled — `internal compiler error: Undefined
  variable: n`. The capture scan was a hand-written walk over an open set of node
  kinds, and an unlisted kind was skipped in silence; a miss there is a codegen
  failure, not a wrong answer. The chain now ends in a STRUCTURAL walk, which
  cannot be incomplete. Test:
  `examples/closure_captures_block_match_arm.saw`.

- **DF-146r — FIXED (Aug 6, commit 125446f; RENUMBERED from DF-146n by design
  176 unit 12). A place window's FLAVOR was read
  after the chain had been rewritten, so a `&var self` method through a place
  opened a SHARED window.** `_chain_is_exclusive` was evaluated as an argument to
  `_window_call`, i.e. after `_replace_head` had swapped the chain's head for the
  window parameter; a rewritten chain never reaches the place, so the walk fell
  off its own tail and answered "shared" everywhere. Only an assignment came out
  exclusive (that path sets the flag directly). Consequence: `let v` plus
  `v[0].bump()` compiled with no error, and the exclusivity join recorded a
  shared borrow where an exclusive one happened. Test:
  `examples/errors/place_exclusive_window_immutable_root.saw`.

- **DF-146s — FIXED (Aug 6, commit d3bc5ed; RENUMBERED from DF-146o by design
  176 unit 12). A struct FIELD of enum type never
  dropped its payload — a leak in every shape.** Every value-lifecycle dispatch
  in codegen keys on `kind`, and a struct field carries the raw parsed
  annotation, so an enum field arrives tagged STRUCT. `_needs_cleanup` re-tagged
  it for its own answer and then handed the still-mistagged type to
  `_emit_drop_at`, which missed every branch and returned in silence:
  `Holder_deinit` came out empty. Plain field, optional field, two structs deep,
  generic enum, struct-with-enum in a Vector, fully structural chain, fixed-array
  field — all leaked; a bare enum local and an enum as a Vector element are the
  controls that worked (those arrive genuinely ENUM-tagged). `_emit_retain_at`
  and `_emit_release_at` had the same gap and cancelled out, which is why this
  presented as a leak rather than a double free — and why all three had to move
  together. Test: `examples/enum_field_drop_glue.saw`.

- **DF-146e — CLOSED (Aug 6, commit c943680).** All three parts landed as
  decided. Two notes for the record. (1) The claim that bare-`T` reads already
  followed the rule did not hold: an unbounded `T` read was accepted and a
  `T: Copy` one aliased at an ExplicitCopy instantiation. Both now go through
  the same gate, so the rule is uniform rather than aspirational. (2) "Provably
  copyable" resolves to a `Copy`-family bound (`Copy`, `ImplicitCopy`,
  `ExplicitCopy`) — each gives every satisfying type a copy the compiler can
  emit, and writing one is the author's consent to duplication, which is what a
  concrete site spells `.copy()`. No bound says "copies for FREE" (design 148
  hit the same wall), so requiring one would have made every abstract read an
  error and left part (2) with nothing to emit.
  Tests: `examples/place_abstract_value_read.saw`,
  `examples/errors/place_abstract_value_read_unbounded.saw`.
  Original finding follows: **A place VALUE READ whose element type is an
  ENUM WITH ABSTRACT TYPE ARGUMENTS does not retain, but its binding is still
  dropped — so every read over-releases** (found by design 146 unit C, Aug 5).
  This is the ONE thing standing between the tree and the DF-132a / DF-128c
  pair. `Namespace.copy_tier` is computed on the type AS WRITTEN in the generic
  body: `Slot<K>` with an abstract `K` joins its payload tiers, gets `free`, and
  no copy is emitted. The DROP is emitted per INSTANTIATION and is real. The two
  disagree, and the difference is one release per read.

  The old by-value `Vector.get` never hit this, which is why it is only visible
  now: its copy was emitted INSIDE the monomorphized accessor, where the element
  type is concrete. A place moves that read into the CALLER's generic body.
  `MapSlot<K, V>` is exactly this shape, and `Map._slot_state` / `_key_eq` /
  `_get_value` / `_key_at` are the probe paths Set and Map are built on — so
  converting `Vector.get` to a conditional lend triple-freed one element across
  two `contains` calls (`examples/set_owning_key_refcount.saw` printed
  `3, 0` instead of `3, 3, 3, 2, 1, 1`, then aborted).

  A bare type PARAMETER is fine (`first_of<T: Copy>(v) { v.get(0) }` retains at
  the instantiation), so the gap is specifically the structurally-derived tier
  of a composite over abstract arguments. Repro, 45 lines, `deinit a` prints
  THREE times for one element:

  ```saw
  struct Res { name: String }
  extension Res: ImplicitCopy {
      func copy(&self) -> Res { print("copy {self.name}")  Res(name: self.name) }
      func deinit(&var self) { print("deinit {self.name}") }
  }

  enum Slot<K> { case Empty, case Occupied(key: K) }

  struct Holder<K> { slots: Vector<Slot<K>> }
  extension Holder<K>: NoCopy {}

  extension Holder<K> {
      init() -> Holder<K> { let v = Vector<Slot<K>>()  Holder<K>(slots: move v) }
      func tag_at(&self, i: Int) -> Int {
          if let s = self.slots[i] {          // a place VALUE read
              match s { case Empty -> 0, case Occupied(_) -> 1 }
          } else { -1 }
      }
  }

  func main() {
      var h = Holder<Res>()
      h.slots.push(Slot<Res>.Occupied(key: Res(name: "a")))
      print("{h.tag_at(0)}")   // deinit a   <- over-release
      print("{h.tag_at(0)}")   // deinit a   <- again
  }                            // deinit a   <- and the real one
  ```

  THE DESIGN QUESTION, and why this stopped rather than being patched: where is
  a value read's copy emitted, and is the decision made BEFORE or AFTER
  monomorphization? Today it is made before (the checker consults `copy_tier` on
  the written type) and the drop is emitted after. Design 131 already has the
  machinery for the other answer — `payload_needs_copy` is a MARK that codegen
  discharges with `_generate_copy(payload, inner.substitute(type_param_context))`,
  i.e. per instantiation — so the likely fix is to make a place value read use
  that path and to have exactly ONE emitter. That is a change to the
  value-transfer / monomorphization seam, it changes behavior for every
  construct that reads a composite-over-abstract-args value, and it wants a
  decision rather than a patch. Wanted as its own unit, ahead of the P0 pair.
 Units A and B are in: `lend` and
`borrows` are reserved in BOTH lexers (selfhost mirrored, lexdiff clean over
1326 files); `borrows` joins the declaration effect slot in canonical order
`unsafe sync borrows`, matching the type grammar's
`unsafe sync escaping borrows`; `[]` is a declarable method name; `lend <place>`
is a statement; the coverage rule, the conditional-lend absent path, and both v1
fences (no borrows function TYPES, no trait requirements) are enforced with
teaching errors. The brief's `escaping`-on-a-declaration fixit landed with them.

THE LOWERING THAT WORKS, and why. A borrows declaration is rewritten into the
window-closure shape — `func [](&self, i: Int) borrows -> T` becomes
`func [](&self, i: Int, __window: (&var T) sync -> __R) sync -> __R`, with
`lend X` becoming `return __window(&var X)` — so the common case emits exactly
what `with_ref` emits today. An EPILOGUE (statements after the `lend`) is
spliced in AT the lend site rather than left where it was written; that keeps
every prologue local in scope for the epilogue that reads it (the
lock-and-release shape) with no frame struct and no state machine, and
duplicating the tail is sound precisely because the coverage rule forbids a
second lend on that path. The transform runs inside `parse_source`, the one
funnel every compilation path takes, so registration, inference,
monomorphization and codegen all see an ordinary generic method and it costs no
second front-end pass. `tools/dump_ast.py` builds its own parser, so the
parser-stage oracle still dumps the authored form.

**WHY USE SITES STOPPED — two findings, both load-bearing for whoever picks
this up.**

(1) **The address form is not expressible in Saw source.** The obvious use-site
lowering is a prologue returning the place's address
(`__place_addr(&self, i) -> UnsafePointer<T>?`), which would let codegen treat a
place as an ordinary lvalue — no closures, no AST surgery, and the fastest
possible code. It cannot be written: `&var` is *only* legal as a call argument,
so `&var X as UnsafePointer<T>` in return position is rejected, and the `&`
variant is refused too (`can only take reference to a variable, field, or array
element`). This is exactly why `with_ref` takes a closure and why the brief
calls the pair "the lowering vocabulary" — a place can only be handed out AS A
CALL ARGUMENT. So a use site must synthesize a closure call
(`v.[](i) { __p in ... }`), which needs the receiver's type and therefore must
run after type checking.

(2) **The coro transform's "mutate the AST, re-enter the front end" pattern
cannot carry a mutation into std.** `_prepare_codegen` re-resolves and
RE-PARSES every module and every builtin from disk on the recursive
`post_transform=True` pass (`sawc.py:700-772`, `build_builtin_namespace`), so
anything the transform wrote into an imported AST is thrown away. The coro
transform never noticed because it only ever mutates `entry_ast`. Places are
different: `Vector.[]` and `Vector.get` live in std, and so do their use sites
inside std itself.

WANTED, as the first unit of the follow-up: teach `_prepare_codegen` to reuse
already-parsed module ASTs (and a builtin AST) on re-entry instead of re-reading
them, then do use-site rewriting in the transform slot exactly as the coro
transform does. That refactor pays for itself twice — it also removes a full
redundant parse of std from every program that uses concurrency. It is a change
to the most load-bearing function in the driver and was not something to start
at the end of a session, which is why this stopped here rather than half-landing
a second mechanism.

Everything this section listed as NOT DONE is done: use sites of every shape,
root attribution, the exclusivity/LIFO-epilogue work, the std `[]` methods, the
toml/blade migration (design 146 unit C), the DF-132a / DF-128c pair (Aug 6),
and the spec/skill/README docs.
Brief: designs/141-borrows-lend-places.md. [141]

**143 LANDED (Aug 5)** — Blade build-output directories + lockfile policy.
Origin: the SOS M1 review finding that `sos/root/sos-root.sosimg` sat next to
its `Saw.toml` [user]. Blade built IN PLACE, so artifacts lived beside source,
every package grew artifact ignore patterns, and two TARGETS of one package
would have fought over one filename (load-bearing with M1b/arm64 queued).
Decision 1: everything a build produces goes under `<package>/.build/<target>/`
— `<target>` is the sawc `--target` triple with `host` for the default hosted
build (the brief's pin, taken as written). `blade/src/layout.saw` is the one
place that knows the shape (`BuildLayout` + `Path.ensure_dir`/`remove_tree`);
builder and tester both hold one. The up-to-date check is per-target on BOTH
halves (stamp AND artifact), which is what makes a stale in-place artifact from
the old layout unreachable rather than merely unlikely. Riders the layout made
expressible: `blade build --target <triple>`, `blade clean [--target]` (new
command; `.blade/deps/` survives — it is source, not output), Blade creating
its own output directory (sawc does not create one), `blade new` scaffolding a
`.gitignore`. Decision 2: the app/lib distinction has NO manifest field — the
source layout IS the declaration (`src/main.saw`/`main.saw` = application,
`src/lib.saw` alone = library), recorded as `Builder.is_application()`. An
application commits `Saw.lock`; a library does not, so `blade build` no longer
writes one in a library at all (`blade update` still does, the explicit ask)
and `libs/toml` + `libs/semver` carry a one-line `.gitignore` for that case.
Sweep: blade conformant already; selfhost/lexer is application-shaped but has
zero deps and is built by tools/lexdiff.py through sawc directly, so no lock
exists or can appear; `sos/root/Saw.lock` is on the PARKED M1 branch — that
branch should commit it (sos/root is an application). Gates: suite 1174,
lexdiff, irdet, astdiff, bootstrap (three new layout stages), sos (now building
into `.build/riscv32-unknown-none-elf/sos/`). Found and fixed on the way: the
Blade suite was ORDER-DEPENDENT — `dep_build` and `lock_roundtrip` write into
`.build/scratch/` and nothing created it, so whichever ran first failed on a
clean tree. NOT moved (deliberate): `tools/lexdiff.py`'s `.build/sawlex` and
`tools/irdet.py`'s `.build/<stem>.ll` are repo-root scratch for host-only
harnesses, not package output, and the repo root is not a Blade package.
Brief: designs/143-blade-build-dirs.md. [143]

**139 LANDED (Aug 5)** — the enum policy tier; no policy-exempt wrappers.
Closes **DF-131a**. `Namespace.copy_tier` is the single oracle: every type has
exactly one transfer class, and a WRAPPER is never weaker than what it wraps —
`Optional<T>`, tuples, fixed arrays, enum payloads and `Result<T, E>` all JOIN
their parts' tiers, with a declared conformance winning over the join. The move
checkpoint is one lookup into it, which retired the bespoke owning-enum arm.
Owning ENUMS now declare a policy like owning structs (`extension E: NoCopy {}`
/ `@synthesize extension E: ExplicitCopy {}`), a bare one being the same
teaching error; only the two OWNING tiers are demanded, so a trivial/
ImplicitCopy enum stays undeclared. `.copy()` on an optional exists exactly when
the payload's tier provides one, and a refused optional transfer names three
spellings (`.copy()` / `move` / `.take()`) rather than the struct's two.

Migration, whole tree: FIVE enums declared a tier (`Slot` twice, `Crate`,
`Payload`, blade's `BladeCommand`) and ONE struct was hit by the containment
cascade (blade's `Cli`); compiler-synthesized `__Frame_*` structs are exempt
rather than migrated. The brief assumed design 128's enum synthesis already
covered copy — it did not (128 gave enums a payload-deep DEINIT and the
Equatable/Comparable/Hashable derivations), so `_emit_enum_deep_copy` was
written here. The tiers are COMPUTED rather than spelled as bounded
conformances in builtin.saw as the brief sketched: `Optional` is a `TypeKind`,
not an enum or struct, so it cannot carry an extension; and `Result`'s two
parameters make the brief's "bounds are mutually exclusive, so exactly one tier
matches" false — the join over (T, E) is not a rectangle, so no set of bounded
conformances expresses it. Observable behaviour is the brief's.

Five latent defects surfaced and were fixed on the way: the coro transform's
sub-frame `__result` read was unstamped (a retain against a paired
`__saw_forget` — a leak); the `__saw_drive_*` wrapper relied on a retain that
has no analogue for a move-only result, and is now a move; `__Frame_*` structs
lacked the ExplicitCopy containment exemption their NoCopy sibling had; the
derived memberwise struct copy raised on an ENUM field and silently
BITWISE-ALIASED an OPTIONAL field. Filed rather than fixed: **DF-139a** below
(overwriting a binding releases its old value while a live copy exists —
pre-existing, reproduces on a plain `String` field, identical before and after).

**133 LANDED (Aug 5)** — two capability completions. Unit A: `Arc<T>`/`Box<T, A>`
payload-method forwarding reaches a METHOD-GENERIC payload method, closing
**DF-123c**, and `Mutex.lock` then became `lock<R>(body: (&var T) sync -> R) -> R`
— review **M1** closed, a value can be computed under the lock and carried out of
it. The fix was codegen-only: both forwards now share `_forward_target_symbol`,
which substitutes the resolved method type args and requests the monomorph the
way the ordinary call path does. DF-123c's second named cause (the typechecker's
`_resolve_arc_forward` not solving method-level type args) was not real — the
forward hands off to the shared downstream, which already runs the design-93/105
inference. Unit B: the design-120 ANF hoist lifts a NESTED short-circuit, closing
**DF-125a** — `f(a ?? slow())`, `return 1 + (a ?? slow())`, `not (a && slow())`,
`g(f(a ?? slow()))` and the blocking-extern versions all transform, and the RHS
still runs only when the LHS does not decide. The mechanism is the one design 120
already had: hoist the WHOLE conditional to its own statement, which is the
outermost form the branch lowering handles, and recurse.

`lock<R>` keeps `body` in TAIL position (a `LockRelease` scope guard does the
unlock) because binding the result would need a local typed `R`, and `R` is
`Void` for every critical section that computes nothing — **DF-123b**, still
open, and the same reason `Vector.with_ref<R>` is written that way. Found on the
way and filed rather than fixed: **DF-133a** (the stage-1 hoist reorders a
suspending child ahead of a side-effecting sync sibling).

**131 LANDED (Aug 5)** — payload-read ownership. Every payload-extraction form
(`o!`, the `??` left operand, an `if let`/`guard let` binding) is now a PLACE,
governed by the payload's copy tier like every other read, and `Deinit` is
non-declarable so no type can carry a destructor without a transfer rule. Closes
**DF-124b** and **DF-128a** (both detailed below). The consuming reads are
`move o!` (compile-time, retires the whole binding, locals only) and the new
`Optional.take(&var self) -> T?` (runtime, swaps `None` in, reaches a FIELD);
`TaskHandle.join` migrated onto `take()`, retiring the tree's last
`__saw_forget` call site. 108 types migrated off standalone `Deinit`
conformances — 74 of them had no copy policy at all and are now `NoCopy`.

Found and fixed on the way: `??` never checkpointed its DEFAULT operand, so
`let s = opt ?? other` aliased `other` and double-freed it (the ExplicitCopy
repro aborted with SIGTRAP). One related hole is filed rather than fixed —
**DF-131a** below (a whole-optional read of a NoCopy/ExplicitCopy payload).

**130 LANDED (Aug 5)** — the unsafe model is rebuilt and design 81's marking
rules are superseded (that brief now carries a SUPERSEDED header). Marking is
per-DECLARATION: `unsafe struct` for a type (with the `Unsafe*` name enforced),
`unsafe func`/`unsafe init` for a function whose body or signature names, binds,
receives or returns one of its values. Type unsafety is not transitive, closures
are judged on their own body, and calling an unsafe function from safe code
needs no ceremony. The line-level `unsafe` expression marker is GONE from the
grammar — 287 of them deleted, and writing one now gets a parse error that says
the model changed. 250 declarations marked (std 133, rt 47, examples 60, blade
5, sos 5); `libs/` and `selfhost/` needed none. Shipped in six staged commits
per the brief's q4 plan, full suite green at each.

Closed here: **M5** (`Vector.set`/`swap` were silent no-ops out of range — both
panic now, and `examples/vector_set_oob_still_noop.saw`, which asserted the old
contract, is deleted) and **M3** (`String.substring` clamped — it panics on a
reversed or out-of-range range; an empty `substring(i, i)` is still legal). Both
are the accessor rule (brief rule 8); RS-6's part of that rule — the three
genuinely UNCHECKED accessors `with_ref`/`with_var_ref`/`swap_out` — had already
landed in design 122 and is unchanged. The rule's audit of `Data` (the brief's
exit criteria name it alongside Vector and String) found `get`/`slice` already
`get`-shaped and compliant, and one third shape neither M3 nor M5 had named:
`Data.set` returned a `Bool` that NOTHING in the tree read, so an out-of-range
write silently did nothing. It panics now, like `Vector.set`.

Fixed on the way: the trigger-rule verdict runs during teardown, after
`current_method`/`current_function` are cleared, so `_error`'s source-file
auto-detection fell back to the ENTRY module — a blade diagnostic about
`Tester.shell_ok` printed a blank line from `main.saw`. It now names the
declaration's own file. Still open: the oversized-`unsafe`-function
decomposition already filed below.

**136 LANDED (Aug 5) — 130's spelling correction.** `unsafe` moved out of the
declaration prefix and into the post-parameter effect slot beside `sync`
(`func f(...) unsafe -> T`, canonical order `unsafe sync`), so a declaration's
signature reads identically to its function TYPE; `unsafe struct` keeps the
prefix (no parameter list, no slot). All 262 declarations re-spelled tree-wide,
IR unchanged apart from the debug-info column of each moved keyword. The prefix
is now a parse error carrying the mirror of 130's fixit, and so is the reversed
`sync unsafe`. Unit B settled the two things 130 left unstated: the `unsafe`
effect on a function TYPE is well-formed iff the signature names an unsafe type
(both halves error, the spurious one teaching rule 7), checked on the type as
written so generic slots are never re-judged per instantiation; and a closure
INHERITS its enclosing function's unsafe domain — no closure-level marker, its
type derived from its own signature, and body contact beyond that signature
charged to the enclosing declaration. The design-130 variance gates
(closure-into-safe-slot, unsafe-value-into-safe-slot) are deleted: with the
effect derived from the signature, the pair of spellings they compared cannot
exist.

**128 LANDED (Aug 5)** — the P4 structural-synthesis line is closed. Deinit is
implicit (a synthesized memberwise `deinit` for any owning struct/enum, dropping
in reverse declaration order; enums payload-deep on the active variant), the
"does not implement Deinit" containment error is gone, and the copy/equality
derivations are gated on a new `@synthesize` extension attribute — uniformly
across ImplicitCopy/ExplicitCopy/Equatable/Comparable/Hashable, with
auto-conformance untouched. Riders done: the four bad-receiver hints, and
`var self` is now a compile error (the audit found TEN in-tree uses, not the
expected zero — blade, libs/toml and selfhost/lexer among them). Nine
transcribed empty deinits deleted from the real Saw packages.

Four things it did NOT close, each recorded below: **DF-128a** (a `Deinit`-only
type aliases and double-frees — pre-existing, found while probing), **DF-128b**
(a payload-free enum cannot be a Map/Set key despite auto-conforming),
**DF-128c** (the drop half of a mangling miss whose copy half WAS a live
double-free and is fixed here), and **DF-128d** (`print(o)` on any optional is
an ICE). Also worth flagging to the reader of the brief: it describes a
hand-written deinit as REPLACING the field drops. It does not — it prefixes
them, and always has; the spec now documents the real behavior.

**132 LANDED (Aug 5)** — units A-G; suite 1140 -> 1149. Closes DF-122a (with
RS-5's fourth hole), DF-123a, DF-123b, DF-128b, DF-128d, DF-129a, review M15 and
P2. Unit A carried the user's reject-the-write decision and unit C the user's
compile-instantiated-Void decision. Unit H — the flagged risky one — is STOPPED
with findings, per its own stop-if-it-fights rule: its fix is correct but would
introduce a live double-free, because DF-128c's missing drop glue is CANCELLING
a second bug. That second bug is new and filed as **DF-132a** (P0): `Vector.get`
has no `T: Copy` bound, so a NoCopy element is handed out as a non-retained
alias and two lookups free it twice, in safe code, today. The pair must land
together and needs its own brief — fixing `get` breaks libs/toml and blade at
the source level.

**127 LANDED (Aug 5)** — RC-3 closed; the op budget now covers pure-compute
loops, so the README claim holds as written. Nothing left open, but the fix
carries four deliberate bounds (sync callee, collection `for`, closure body,
std's own io loops) — all in LANGUAGE_SPEC + the saw-lang skill.

**124 LANDED (Aug 5)** — RS-3 closed; a group is a scope, not an extender.
Landing it needed a frame-field ownership fix (DF-124a, folded in). Two things
it did NOT close: the general `opt!` read-out-of-optional gap DF-124a's root
cause belongs to (DF-124b, closed by design 131) and the brief's item 3 box
reclamation, unimplementable as written (DF-124c) — **closed by design 134**,
which moved the result and cancel word into group-owned cells so the frame box
could go at Done.

**134 LANDED (Aug 5)** — closes DF-124c. Three moves: group-owned result/cancel
cells, the frame box released at completion, and a generation-counted slot free
list. A group now costs O(live + unjoined-result tasks); measured 200,000 slots
/ 31.0 MB -> 4 slots / 1.5 MB on 200k short tasks through one group. Found and
fixed on the way: writing to a field of a GENERIC struct instance was rejected
outright (the write path resolved the field against the generic symbol and saw
the abstract `T` while the read path substituted) —
`examples/generic_struct_field_assign.saw`.

**122 LANDED (Aug 5)** — units A-I plus the folded-in RS-6, per-item closures
inline below. Two things it did NOT close: RS-5's fourth hole (DF-122a, stopped
for a user decision) and P2's design-92 half-application in
std.file/std.directory.

**123 LANDED (Aug 5)** — units A1-A3, B-J. Closes RS-1 and the report's C1, H2,
H3, H7 and H8. Two things it did NOT close: review M1 (`Mutex.lock`'s result
should be the closure's own type) was blocked on **DF-123c** — both closed by
design 133 — and **DF-123b** is a second ICE found on the way (closed by
design 132 unit C); both are recorded under "Design 123 — DF-findings".
review M15 (`Directory.current` truncates at 1024 bytes) was untouched there —
only its OOM path was separated out — and is **FIXED by design 132 unit F**
(Aug 5): the buffer doubles from 1024 up to a 1 MiB ceiling and getcwd is
retried until the path fits, so a long working directory comes back WHOLE
instead of as a `None` indistinguishable from a real failure. errno is not
readable from std (rt/ABI.md keeps `__saw_rt_last_syserror` runtime-internal,
and getcwd is a bare libc call), so the retry cannot tell ERANGE from EACCES and
does not try — it grows until the path fits or the ceiling is reached, which
costs a handful of doublings on a path that was already failing. The OOM path
stays separate: allocator refusal still panics (design 123). Test
`examples/directory_current_long_path.saw` builds its own ten-component,
200-bytes-each tree by entering one component at a time (a single `mkdir` of the
whole path would hit PATH_MAX — 1024 on macOS, 4096 on Linux), which puts the
working directory past 2000 bytes on either host; it asserts the path comes
back, exceeds the old fixed buffer, and is intact at both ends, then unwinds the
tree and restores the original directory. Measured at 2036 bytes on macOS, where
it returned `None` before.

**P0 — proven memory-safety / correctness (stdlib + runtime):**
- **RS-1 — FIXED (design 123, Aug 5).** std now has ONE answer to "the allocator
  said no", in two tiers, applied to every site below. An infallible signature
  PANICS naming its method (`Vector.push: allocation failed`) through
  `__saw_rt_panic`; each such operation has a `try_`-prefixed twin returning
  `Result<_, AllocError>` that is all-or-nothing — on `Err` the container is
  exactly as it was. `try_` is the one spelling (`Box.make_or` -> `try_make`).
  `AllocError` conforms to `Error`/`Printable` and carries the refused
  size/align. `String` gets no fallible tier: every producer returns a plain
  `String`, so the single allocator behind them panics, which covers the whole
  layer in one place. Original finding follows: `Vector.push` writes past the
  buffer and bumps length when `grow()` fails silently; same shape in
  `StringBuilder.append/append_char`, `Data.push/append/append_bytes`,
  `Command.append_arg`. Root cause is systemic: std has ~9 different answers to
  "the allocator said no" (panic / Err / degrade / corrupt / drop / inert
  object). One design-19-three-tier pass would subsume five other findings.

  **The classification table** (the brief's first task — every allocation-failure
  site in std and in the compiler's own emitted code, its behavior BEFORE, and
  the tier it now sits in). "corrupt" = out-of-bounds write from safe code.

  | Site | Was | Now |
  |---|---|---|
  | `Vector.push` | corrupt (OOB write + length past capacity); dropped the element on the first-alloc path | tier 1 panic; `try_push` |
  | `Vector.grow` | silent no-op | private `_reserve -> Bool` |
  | `Vector.init(capacity:)` | degraded to an EMPTY vector | tier 1 panic; `try_with_capacity` (existed) |
  | `Vector.copy` / `map` | short/empty result vector | tier 1 panic; `try_copy` |
  | (new) | — | `Vector.try_reserve` |
  | `Box.make` | tier 1 panic (already correct) | unchanged; `make_or` renamed `try_make` |
  | `StringBuilder.append` / `append_char` | corrupt | tier 1 panic; `try_append` / `try_append_char` |
  | `StringBuilder.grow` | silent no-op | private `_reserve -> Bool` |
  | `StringBuilder.init(capacity:)` | capacity-0 builder | tier 1 panic; `try_with_capacity` |
  | `StringBuilder.build` / `as_str` | `""` | tier 1 panic (via `__saw_string_alloc`) |
  | `StringBuilder.append_scalar` | corrupt, still returning `Some(1..4)` | tier 1 panic; `None` means invalid scalar only |
  | `Data.push` / `append` / `append_bytes` | corrupt | tier 1 panic; `try_push` / `try_append` / `try_append_bytes` |
  | `Data.ensure_capacity` / `allocate_buffer` / `ensure_unique_capacity` | silent no-op, `public` | private `_reserve` / `_allocate_buffer` / `_reserve_unique`, all `-> Bool` |
  | `Data.copy` | `len() == N` with `capacity() == 0`, every `get` None | tier 1 panic; `try_copy` |
  | `Data.init(capacity:)` | capacity-0 buffer | tier 1 panic; `try_with_capacity` |
  | `Data.make_unique` | silent data loss | private `_make_unique`; tier 1 through `copy` |
  | (new) | — | `Data.try_reserve` |
  | `__saw_string_alloc` (codegen) | NULL -> every String producer degraded to `""` | tier 1 panic; declared non-optional in std |
  | `String._substring` (and `trim`/`trim_start`/`trim_end`/`substring`) | `""` | tier 1 panic |
  | `String.to_uppercase` / `to_lowercase` | returned `self`, UN-cased | tier 1 panic |
  | `String.replace` | returned `self`, NO replacements | tier 1 panic |
  | `String.fromBytes` | `Ok("")` — success reported on failure | tier 1 panic; `Err` means invalid UTF-8 only |
  | `String.split` / `to_data` | short/empty, or corrupt via push | tier 1 panic |
  | `Vector<String>.join` | `""` | tier 1 panic |
  | `Path.join` / `join_path` | returned the UN-JOINED parent path | tier 1 panic |
  | `Map._grow` | first grow: `cap = 8` over an EMPTY vector; later grows: INFINITE LOOP | `_try_grow -> Bool`, reserving the table up front |
  | `Map.insert` | dropped key+value, incremented `count`, returned None | tier 1 panic; `try_insert` |
  | `Map.keys` / `values` | short/empty snapshot | tier 1 panic (via push) |
  | `Set.insert` | dropped the element, counted it, returned `true` | tier 1 panic; `try_insert` |
  | `Set.of` / `init(from:)` / `to_vector` / union / intersection / difference | short/empty | tier 1 panic |
  | `Set.is_subset` / `is_superset` | vacuously `true` | tier 1 panic |
  | `Arc.init(value:)` | INERT: value dropped, `strong_count() == 0`, forwarded calls deref null | tier 1 panic; `try_make` |
  | `Mutex.init(value:)` | INERT: `lock` returned `false` without running the body | tier 1 panic; `try_make` |
  | `Mutex.lock` | `false` collided with the inert case | collision gone (no inert mutex exists); result is the closure's own type since design 133 (M1 closed) |
  | `Mutex.get` | `T?` whose None meant "built by a failed allocation" | returns `T` |
  | `Channel.init` | INERT: `send` swallowed, `recv` panicked on a None unwrap, `receive` hung | tier 1 panic; `try_make` |
  | `Channel.send` | SILENTLY DROPPED the message | tier 1 panic; `try_send` over a reporting `_enqueue` |
  | `Channel.recv` (no block) | `empty!` — a force-unwrap saying nothing | named panic (unreachable) |
  | `TaskGroup.init(threads: N>=2)` | INERT: no task ever ran; `join` unwrapped an unwritten result | tier 1 panic |
  | `TaskGroup.__enqueue` / `__saw_exec_run_root` | corrupt / desynced 4 vectors; root: main's frame dropped, exit 0 | tier 1 panic (through `Vector.push`) |
  | spawn control block (codegen `calls.py`) | stored through NULL -> segfault, no message | tier 1 panic (`_alloc_or_panic`) |
  | escaping closure env (codegen `closures.py`) | stored through NULL -> segfault, no message | tier 1 panic (`_alloc_or_panic`) |
  | `Command.output` read buffer | `Some(CommandOutput(stdout: "", exit_code: real))` | tier 1 panic |
  | `Command.output` grow | corrupt | tier 1 panic |
  | `Command.build_argv` | `None` -> reported as "could not launch process" | tier 1 panic; return non-optional |
  | `Command.arg` | corrupt / dropped an argv element | tier 1 panic (through `Vector.push`) |
  | `File.read` / `File.write` | `None`, colliding with the syscall failure; short reads | tier 1 panic; `None` means the syscall failed |
  | `Directory.current` | `None`, colliding with getcwd failure AND truncation | tier 1 panic; `None` means getcwd failed (M15 truncation FIXED in design 132 unit F) |
  | `Directory.list` | name -> `""`, entry -> the parent dir, entries dropped | tier 1 panic (through String/Path/Vector) |
  | `Env.arg` / `get` / `args` | `Some("")` for a real value; short argv | tier 1 panic (through String/Vector) |
  | `net.net_buffer` | tier 1 panic (already correct) | unchanged |
  | `net.net_read_once` / `read` / `read_into` | `Err(IoError)` + corrupt via `append_bytes` | `Err(IoError)` kept; the corrupt half is tier 1 |
  | `TcpStream.write(String)` | short/empty write reported as `Ok` | tier 1 panic (through `to_data`) |
  | `Allocator.alloc` / `slab_alloc` | `None` (the reporting primitive) | unchanged — this is what the tiers are built on |
- **RS-2 — FIXED (design 122 units A + B, Aug 4; commits 3b68703, b8f9969).**
  `iter()`/`EnumeratedIterator` carry the `T: Copy` bound `each`/`map` already
  had and `next()` yields an explicit `.copy()` (a NoCopy element is reached
  through `with_ref`/`with_var_ref` instead — now a clean bound error naming
  it); `set` routes through `swap_out`, so the overwritten element deinits
  exactly once; `String.byte_at` bounds-checks; `Data.to_string` delegates to
  `String.fromBytes` and returns `Result<String, Utf8Error>`. Original finding
  follows: `Vector.iter()` double-frees owning elements (safe code, no unsafe,
  proven deinit-twice). `set` also leaks the overwritten element;
  `String.byte_at` reads OOB heap from a safe signature; `Data.to_string`
  mints invalid UTF-8.
- **DF-132a — CLOSED (Aug 6, commit f4222fd), with DF-128c, one commit.**
  `Vector.get` is `func get(&self, index: Int) unsafe borrows -> T?` — the
  `None`-returning twin of `[]`, the same lowering — so the read is judged by
  the element's tier where it stops being storage, and a move-only element is
  refused there. The retain oracle
  (`examples/place_value_read_retain_oracle.saw`) is unchanged, and so are its
  expected counts: trivial and ImplicitCopy callers behave exactly as before.
  Regression: `examples/errors/vector_get_nocopy_alias.saw` (the repro below, as
  a teaching error). Original finding follows. `Vector.get` has NO `T: Copy` bound, so a
  NoCopy element
  is handed out BY VALUE as a non-retained alias — proven double-deinit in safe
  code (found by design 132 unit H, Aug 5; PRE-EXISTING).** RS-2's unfinished
  half: design 122 gave the `T: Copy` bound to `iter`/`enumerated`/`each`/`map`
  and routed `set` through `swap_out`, but `get` was never touched. Its
  signature is bare — `public func get(&self, index: Int) unsafe -> T?`
  (`sawc/std/vector.saw:91`) — and the body returns `buf[index]`, a bitwise read
  through the raw pointer with no retain. For an ImplicitCopy element the
  surrounding machinery balances it; for a **NoCopy** element there is no
  `copy()` to call, so the caller receives an alias it then OWNS and DROPS,
  while the vector still holds the same element. Every lookup frees it again:

  ```saw
  struct Item { name: String, payload: Vector<Int> }

  extension Item: NoCopy {
      func deinit(&var self) { print("Item.deinit {self.name}") }
  }

  extension Item {
      init(n: String) -> Item {
          var v = Vector<Int>()
          v.push(41)
          Item(name: n, payload: move v)
      }
  }

  struct Box2 { items: Vector<Item> }
  extension Box2: NoCopy {}

  extension Box2 {
      init() -> Box2 { let v = Vector<Item>()  Box2(items: move v) }
      // `get` on a NoCopy element compiles. It should not.
      func find(&self, want: String) -> Item? {
          var i = 0
          while i < self.items.len() {
              if let e = self.items.get(i) {
                  if e.name.equals(want) { return e }
              }
              i = i + 1
          }
          None
      }
  }

  func main() {
      var b = Box2()
      b.items.push(Item(n: "one{1}"))
      if let first = b.find("one1") { print(first.payload.len()) }
      if let second = b.find("one1") { print(second.payload.len()) }
  }
  // Item.deinit one1   <- the first alias frees the payload buffer
  // Item.deinit one1   <- the second frees it AGAIN; the vector still holds it
  ```

  Two lookups, two frees of one `Vector<Int>` buffer, no `unsafe` anywhere. It
  does not crash today only because the freed block is usually not reused before
  the process exits. libs/toml is built on this alias (`TomlDoc.get_section`,
  `TomlSection.get_table`, `TomlTable.get`) and so is blade's manifest reader.

  This is also what blocks **DF-128c** above: the missing `Vector<T>`-field drop
  glue is the second half of a cancelling pair, and fixing either alone breaks.
  FIX WANTED, as one brief: give `get` the bound the docs already claim it has
  (the saw-lang skill says "`Vector.get(i)` returns a COPY (needs copyable
  element)"), decide what replaces it for NoCopy elements (a `with_ref`-shaped
  scoped borrow, an index-returning lookup, or `ExplicitCopy` on the toml
  types), migrate libs/toml + blade, and land DF-128c's drop-glue fix in the
  same change. Repros: `.build/scratch/p132_h_alias.saw`,
  `.build/scratch/p132_h_uaf.saw` (gitignored; inlined above).
- **RS-3 — FIXED (design 124, Aug 5).** A task's owned values are now released
  when THE TASK completes: the coro transform synthesizes a `__release` per
  frame and calls it at every `return Done` site, dropping params and
  across-suspend locals in the same LIFO order an ordinary scope exit uses
  (including a frame-resident nested `TaskGroup`, whose own children are
  structured-joined first). The result slot is the single exception — `join()`
  moves it out, or the frame drops it once at group teardown. Both proven
  defects are gone and fenced by tests that HANG on the pre-124 compiler:
  `net_sibling_eof_no_deadlock` (the EOF pattern) and
  `net_accept_loop_eager_fd_close` (the README server, client-observed EOF as
  the fd oracle). Resource accounting is covered by
  `taskgroup_eager_teardown{,_live_count,_mt}` (baseline leaked 8, and the MT
  group accumulated across waves) and the double-drop edges by
  `taskgroup_result_{joined,unjoined}_once`. Landing it required making
  frame-field ownership honest — see DF-124a. Six existing deinit-oracle tests
  were re-baselined to the eager ordering. Original finding follows: TaskGroup
  is a lifetime EXTENDER, not a scope. Task-owned values are released at group
  teardown, not task completion — the README's own accept-loop server leaks one
  fd + frame per connection for the group's life, and the sibling reader/writer
  EOF pattern deadlocks (verified hang). Contradicts the
  deterministic-destruction claim. [design-claims #1]
- **RS-4 — FIXED (design 122 unit C, Aug 4; commit facebad).** `Command` holds
  `args: Vector<String>` and spawns a real argv through three additive seams
  (`__saw_rt_proc_spawn`/`_read_stdout`/`_wait`, fork + execvp in
  rt/common/proc.saw, documented in rt/ABI.md). No shell sees the bytes, so
  there are no quoting rules to get wrong; `wait` returns the RAW POSIX status
  so signal death cannot read as exit 0. Original finding follows:
  `std.process.Command` is `system()` string-concat with no quoting —
  `arg("; echo INJECTED")` executes; `arg("one two")` word-splits.
- **RS-6 — FIXED (design 122, Aug 5).** `Vector.with_ref`, `with_var_ref` and
  `swap_out` now check `0 <= index < length` and panic on a miss — the same
  always-on bounds check indexing has, carrying (since unit I) the same
  `panic at FILE:LINE:` prefix. The location names vector.saw rather than the
  caller: Saw has no caller-location facility, so each message names its METHOD
  (`Vector.swap_out: index out of range`) to stay diagnosable. `set` filters the
  index itself before delegating to `swap_out`, so its documented
  no-op-when-out-of-range contract is UNCHANGED — asserted by
  examples/vector_set_oob_still_noop.saw, since a panic leaking through that
  delegation would have been a silent behavior break. `String.byte_at`'s unit-A
  message was re-worded from "out of bounds" to "out of range" so one failure
  class reads one way. Tests
  examples/vector_{with_ref,with_var_ref,swap_out}_oob_panic.saw, each verified
  failing before the fix (the OOB read returned 0 and exited 0, exactly the
  probe). M5's tolerant `set`/`swap` and M3's clamping `substring` were NOT
  covered here and are now CLOSED by design 130's accessor rule (both panic);
  this closed only the three UNCHECKED accessors. Original finding (lead probe, Aug 4; the review under-rated it as
  M5/medium) follows: they checked only that the buffer is non-null, so an
  arbitrary `Int` index reached `buf[index]` through a `public`, non-`unsafe`
  signature — the same shape as the C4 `byte_at` bug filed critical, in the API
  the skill and design 122 unit A both name as the sanctioned way to reach
  `NoCopy` elements. `swap_out` was worse than C4: an out-of-bounds **WRITE**,
  i.e. heap corruption from fully safe code. PROVEN on main
  (`.build/scratch/wr_oob.saw`, 2-element `Vector<Int>`):
  ```
  len = 2
  with_ref(99) = 0            // OOB read, exit 0, silent
  swap_out(99) returned = 0   // OOB WRITE of 7 past the end, exit 0, silent
  ```
- **RS-5 — FIXED (3 of 4 in design 122 unit D, Aug 4, commit 3aabc9f; the
  fourth in design 132 unit A, Aug 5).** A bare `{ }` statement, a builtin
  redefinition and `let n = <Void expr>` are all clean errors now. The FOURTH —
  an escaping closure's captured mutable state resetting per call — is closed
  the way the user decided: the WRITE is rejected, so the silent-wrong-answer is
  gone rather than papered over (see **DF-122a** below). Original
  finding follows: silent-wrong-answer holes (vs the never-hide-errors rule): a
  bare `{ }` statement is a discarded uncalled closure (statements never run, no
  warning); an escaping closure's captured mutable state resets per call
  (`make_counter()` → 1,1,1); a user `func print`/`assert` is silently
  dropped; `let n = <Void expr>` typechecks then ICEs with an empty message.

**P1 — compiler bugs found by review:**
- **RC-1 — FIXED (design 122 unit E, Aug 4; commit a904bcb).** Root cause was
  not a hardcoded name list: the docs path type-checks with `object_only=True`,
  so the whole-program effect FIXPOINT never ran and every `SuspendNode.suspends`
  bit was still False. `finalize_effects()` now runs on the docs path and
  `_effect` consults the program's own graph first (the std sets remain the
  documented fallback for bodies this typechecker never checks). Golden test
  examples/doc_emit_effect.saw covers direct, TRANSITIVE, plain-sync and
  declared-`sync`. Original finding follows: `--emit-docs` labels every
  suspending USER function `"sync"` (only hardcoded std names emit
  `"suspending"`, docs_emit.py) — design 121 bug.
- **RC-2 monomorphization misses grafted types**: `substitute_ast_types` walks
  `dataclasses.fields()` only, so ~10 runtime-grafted `SawType` annotations
  survive un-substituted (compiler-preport hazard 1; live bug).
- **RC-3 — FIXED (design 127, Aug 5).** The coroutine transform charges every
  loop iteration of a task body against a frame-resident counter: each loop gets
  `__saw_loop_budget = __saw_loop_budget &- 1; if __saw_loop_budget <= 0 {
  __saw_loop_budget = 128; yield_now() }` prepended to its body, over a
  `var __saw_loop_budget: Int = 128` at the body top. Ordinary Saw — the existing
  frame-local collection makes the counter a field and the existing splitter
  handles the suspending `if`, so nothing downstream is special-cased. Top of the
  body rather than after the last statement, so a `continue` reaches it. A body
  that used to compile as a straight sync run-to-completion frame becomes
  suspending, which is how it gains a place to yield. Scope: entry-module task
  bodies, the suspending callees the transform embeds, entry-module driven
  methods. Four documented bounds — a SYNC callee is not instrumented; a `for`
  over a non-range iterable is not (nor any loop nested inside it — `_split_for`
  can only state-split a range `for`, and instrumenting one would turn working
  programs into compile errors); a closure body is not; std's io loops keep the
  89-c charge. Cost measured before any tuning, per the brief: 1.53x on 200M
  iterations of an LCG chain in a spawned task (194 ms -> 296 ms, arm64), nearly
  all of it the loop joining the frame's state machine rather than the check;
  the wrapping `&-` instead of a checked `-` is worth 1.74x -> 1.53x. No gating
  on provably-finite loops — the shape that starves (`while i < n`, runtime `n`)
  is exactly what such an analysis cannot prove finite. Tests
  examples/taskgroup_compute_preemption{,_mt}.saw and
  examples/taskgroup_budget_loop_semantics.saw. Original finding follows:
  op-budget does NOT stop a pure-compute spinning task — starves siblings
  completely; README claims otherwise. (Budget counts only I/O-ish ops.)
- **RC-4 — FIXED (design 122 unit I, Aug 5).** Every compiler-raised panic now
  carries the design-69 `panic at FILE:LINE: ` prefix: overflow, division by
  zero, shift range and bounds gained a location they never had, and
  force-unwrap / `try!` gained the file half (their bespoke `... at line N`
  texts are gone). The location folds into the message constant — now interned
  by text through `_raw_bytes_ptr` — so a site still lowers to one constant and
  one `saw_panic` call. LINE is the TRAPPING EXPRESSION's line: threaded from
  the AST node where the check has one (binary/unary ops, index, `!`, `try!`),
  else the line of the statement being lowered, tracked per llvm FUNCTION
  (`_di_stmt_lines`) so a nested body cannot bleed its line onto its parent; a
  closure inherits its enclosing function's basename so the FILE:LINE pair stays
  consistent in a multi-module build. One format in both profiles — a
  freestanding FILE gate was measured and rejected: it saves only
  `len(basename) - 4` bytes per site, because the size cost is per-site LINE
  uniqueness, which the brief keeps unconditionally. Numbers: SOS M0 kernel
  unchanged at 1420 text / 168 rodata (it has no runtime-check panic sites at
  all); a synthetic 30-distinct-site freestanding riscv32 kernel 2224 -> 3181
  text (+957 rodata), of which the FILE half is 482. Tests
  examples/panic_location_{overflow,bounds,divzero,shift}.saw. Original finding
  follows: overflow/bounds/div-zero/shift have no location at all;
  force-unwrap/`try!` lack the file.
- **RC-5 — FIXED (design 122 unit H, Aug 4; commit a5f36c1).** The driver
  refuses `--freestanding` at a Mach-O EFFECTIVE triple up front, before any
  codegen, and names the ELF cross-targets to pass instead — replacing the
  uncaught LLVM abort over design 112's per-function `.text.<name>` sections
  (which Mach-O rejects) and the 0-byte object it left behind. Test
  examples/errors/freestanding_macho_target_rejected.saw names the triple
  explicitly, so it asserts the same thing on every host. Original finding
  follows: `--freestanding` on the Mach-O host dies as an uncaught LLVM ERROR
  abort (ELF cross-targets fine).
- (Re-confirmed, already open: DF-119b `print(UInt)` renders signed.)

**P2 — CLOSED. Portability (SOS-relevant): the two hardcoded numbers were fixed
by design 122 unit F (Aug 4, commit 6c29cfa); the design-92 half-application in
std.file/std.directory is finished by design 132 unit G (Aug 5).**

Unit G's half: `File.open`/`create`/`open_append` -> `Result<File, IoError>`,
`File.read` -> `Result<Data, IoError>` (an empty Ok means the file had nothing
left — distinct from a failure, which used to share `None` with it and with
"the allocation failed"), `File.write` -> `Result<Int, IoError>`,
`File.seek_start`/`seek_current`/`seek_end`/`position` -> `Result<Int, IoError>`,
`Directory.list` -> `Result<Vector<Path>, IoError>`. `Directory.current` stays
`Path?` on purpose: `None` there means getcwd(2) failed, and unit F removed the
truncation that used to share that answer. `File.exists`/`Directory.exists` stay
`Bool` — genuine boolean questions.

That needed new seams, because std had no way to read the CAUSE: `open`, `read`,
`write`, `lseek` and `opendir` were bare libc calls, and rt/ABI.md forbids std
from calling `__saw_rt_last_syserror` after one (errno may already be clobbered).
Five additive `__saw_rt_fs_*` seams now carry it, on the design-117 convention —
the natural non-negative result or `-tag` — with `opendir` taking a status
out-parameter because a `DIR*` cannot fold a tag into its return. ABI.md
documents them and gains an additions-since-v2 table.

Call sites migrated: blade (builder, main, manifest, resolver, lock, tester),
selfhost/lexer, and three examples. Two of them were silently discarding a
failure and no longer can — `write_lock` returned `true` without checking the
write, and blade's build-hash stamp ignored both halves. Note for anyone doing
this again: Saw has no `if let` over a Result, so every site became `match` or
`try`, and a `return` inside a match arm needs its own block.

Unit F's half (design 122): the dirent offset moved behind the host split as
`__saw_rt_fs_dirent_name` (macOS 21 / Linux 19, rt/ABI.md documents the additive
seam) and `Data` uses `sizeof<DataBuffer>()`/`alignof<DataBuffer>()` instead of
a literal 24 — the riscv32 block is 12 bytes, so it had been over-allocating and
then handing the allocator a size that was a lie. Test
examples/directory_list_names_exact.saw round-trips a file it creates itself, so
a wrong offset fails on ANY host.

**P3 — docs debt (20 findings): CLOSED (design 125, Aug 4).** 18 of the 20
were doc fixes and all landed; findings 3 (`--emit-docs` effect field) and 5
(`print(UInt)` renders signed) are compiler bugs the docs describe correctly,
owned by design 122 units E and G. README is current through 121 and now joins
the docs-update convention (CLAUDE.md workflow section); "no hidden
allocations" names its two exceptions. **That softening is CLOSED by design
135 (Aug 6):** the claim is back in guarantee form in both the spec and the
README, enforced by `sawc --no-hidden-alloc`, with the site-by-site audit table
in LANGUAGE_SPEC "No hidden allocations". The audit found a THIRD hidden site
the 125 wording did not know about — single-argument `print` of a user
`Printable`, which renders through a synthesized `to_string()` — and a FOURTH
that was a defect rather than a design choice: a builtin's `format(into:)`
allocated a String per call and never released it, putting an allocation and a
leak inside design 137's alloc-free path (fixed; every case now reaches a
`StringBuilder.append` overload, Float through a frame-resident immortal
String). The sos gate compiles the kernel under the flag permanently. Appendix A picked up two names the
review missed (`deinit`, `Self` were listed reserved and are not). Left
untouched on purpose: the op-budget claim (127) and the `panic at FILE:LINE:`
claim (122 unit I), both being made true rather than softened. Both are now
true; 127 added the qualifying clause that says HOW (loop iterations of a task
body are charged).

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

**~~P4 — element places / generalized accessors~~ PROMOTED to design 141
(user, Aug 5): `borrows` effect-slot keyword + `lend` bodies; queued after
139.** Original entry follows:
**(user question, Aug 5):**
`with_ref`/`with_var_ref` are `_read`/`_modify` accessors spelled as closure
ceremony because indexing yields VALUES, not places. The successor design:
`v[i]` becomes a PLACE backed by the existing scoped-borrow machinery, with
shared-vs-exclusive picked from the USE SITE (`v[i].n += 1` borrows `&var`;
`print(v[i].n)` borrows `&`) — Swift's accessor model, built on design
131's place vocabulary. SUBSUMES the with_ref pair (they become the
lowering) rather than deduplicating it; adjacent to G3 slices (also wants
place semantics). Considered and REJECTED: mutability-generic parameters
(`<M: mut>` — a new generic kind threading through exclusivity/inference/
monomorphization for a handful of std pairs; Rust lived without it, D's
`inout` is a cautionary tale) and name-overloading the pair (unannotated
closure params make the overload solver tie, forcing per-site annotations).
Until then the pair stands as the honest Rust-`_mut`-style convention.

**P4 — coro frame-size optimization (user idea, Aug 5):** today the flat
frame gives every driven CALL SITE its own embedded sub-frame field, so a
task pays the SUM over all sites even though only one nested chain is ever
live at once. Because suspending recursion is banned, the high-water mark
(the deepest simultaneously-live drive chain) is statically computable —
sub-frames with disjoint lifetimes (sequential drives, if/else branches)
can be OVERLAID union-style at fixed offsets, shrinking `sizeof(frame)` to
exactly the high-water mark with zero runtime cost (keeps one-allocation-
at-spawn, zero-alloc suspend, pinned frames — the design-91 wake token and
design-88 interior pointers need frames that never move, which rules out a
DYNAMIC grow/shrink frame stack unless chunked). Companion to design 44's
noted live-range packing of locals; do both in one sizing brief.

- **DF-125a — FIXED (design 133 unit B, Aug 5).** The stage-2 lowering lifts a
  suspension-spanning value-conditional out of a NESTED expression position into
  its own `let __vchN = <conditional>` — the outermost form it already lowered to
  a branch shape — and reads the temp in its place. Laziness survives by
  construction (the temp's own lowering is the guard), nesting recurses because
  the hoist re-enters `_vc_stmt`, and the blocking-extern variant rides along.
  `_anf_children`'s child-position dispatch was factored into
  `_map_uncond_children` so both passes walk the same positions in the same
  order. Tests: `examples/expr_suspend_nested_shortcircuit.saw` (argument,
  operand-in-`return`, under `not`, doubly nested, interpolation, each with the
  RHS-skipped counter assertion) and `examples/expr_suspend_nested_blocking.saw`.
  The spec + skill limitation notes design 125 added are deleted. Original
  finding follows: **design-120 short-circuit nesting limit (found by design
  125, Aug 4).** A suspending call in a `??`/`&&`/`||` operand
  transforms only when the short-circuit operator is the OUTERMOST expression
  of its statement. `let x = a ?? slow()`, `return a ?? slow()` and a tail
  `a ?? slow()` all work; `return 1 + (a ?? slow())`, `f(a ?? slow())` and
  `not (a && slow())` hit "appears in a nested/expression position". Same for a
  blocking extern, with its own diagnostic. Errors cleanly and never blocks
  silently, so this is a capability gap, not a correctness bug — design 125
  documented the limit on both the spec and the skill rather than paper over
  it. Repros: `.build/scratch/d125_120_return.saw`, `d125_120_return2.saw`,
  `d125_120_shortcircuit.saw`, `d125_blocking_sc.saw` (gitignored; the shapes
  are inlined above). Worth a follow-up brief if the ANF hoist can be taught to
  lift a nested short-circuit.

## Design 155 — irdet in Saw, the first devtool port (LANDED, Aug 7)

`designs/155-irdet-in-saw.md` closed. `tools/irdet.py` is deleted; the IR
determinism harness is `devtools/irdet/` — a Saw package, built to
`.build/irdetbin`, and the gate `make irdet` / `make irdet-all` runs. It still
drives the PYTHON sawc: the tool is Saw, the compiler under test is not, and
that stays true for the whole rewrite track.

The port is ~500 lines of Saw and reads like the Python it replaces:
`git ls-files` and the two per-file compiles through `Command`, the negative-test
filter through `std.file`, the byte comparison over `Data`, `TaskGroup(threads:
N)` where the thread pool was, `-n/--all/-v/-j` plus `--only-files`/`--jsonl`
(the design-160 worker contract) and a new `--plan`.

**The `--remote` conflict, resolved.** The brief was written before design 160,
and did not know that `tools/irdet.py` had grown a second job: the client half
of the two-machine split, riding on `worker_client`/`worker_proto`. Deleting it
would have silently retired a landed capability. That orchestration is
`tools/irdet_remote.py` now — the split, the submit, the fallback, and nothing
else; it shells out to the Saw binary for the local share, so there is still
exactly ONE implementation of what determinism MEANS. `--plan` exists for it:
which examples are negative tests is the harness's rule, and a driver that
recomputed it would be a second rule.

### What the port found (the DF product)

- **DF-155d — a struct holding an enum was not `Send`. FIXED** (`namespace.py`,
  `examples/taskgroup_threads_send_enum_field.saw`). A payload-free enum is Send
  on its own, but a FIELD written as a bare name arrives at the derivation with
  the generic STRUCT kind, and the struct lookup for an enum name found nothing.
  Hit on the port's FIRST compile, because a worker result is exactly that shape:
  a verdict enum plus a message.
- **DF-155e — `File.create` did not truncate on macOS, and `File.open_append`
  neither created nor appended. FIXED** (`std/file.saw`, `rt/common/os_ops.saw`,
  `shim.c`, `examples/file_open_modes.saw`). std spelled the `open(2)` flags as
  decimal literals — the LINUX values, on both hosts. Silent data loss on one of
  the two supported platforms, found because the JSONL sink appends. The seam
  takes a PORTABLE open mode now; only C can see `<fcntl.h>`.
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

Also worth recording, though neither is a defect: a multi-line boolean needs
enclosing parentheses (a newline ends a statement outside brackets — design
129), and matching an `Optional` with `case Some`/`case None` is not a thing —
`??`, `if let` and `guard let` are the spellings.

## Design 164 — std compile caching: INVESTIGATION COMPLETE (Aug 7), user picks

`designs/164-std-compile-cache-investigation.md` carries the full report
(per-tier numbers, the cache key, the differential-gate design). Nothing under
`sawc/` was modified; every probe lives in `.build/scratch/` (gitignored). The
implement decision is the user's.

**The premise checks out but the conclusion moved.** Caching std's FRONT half is
real and small — parse is 14.3% of a compile and typecheck 9.8%, and the
re-entry passes can never be served, so tier A is worth ~11% and tier B ~19%.
The compile is dominated by the BACK half: codegen + LLVM is 65%, and **90.1%
of the emitted IR is std** (user code is 1.3%). `hello.saw` — four lines —
emits 27,922 IR lines / 449 defines / a 265 KB object, and ~93% of its compile
is std work. Only tier C touches that.

**Per-tier verdicts** (ceiling / win / effort / risk):

- **Tier A — serialized std ASTs: NOT the low-risk tier, 9.9%.** 14.3% /
  **9.9% measured** (2.22 -> 2.00 s, isolated, 3 runs each) / 1-2 d / MEDIUM.
  Pickles as-is (1.59 MB, no lambdas, no llvmlite, no file handles reachable)
  and the restored AST is **byte-identical to a fresh parse under the
  `ast_dump` oracle**. But the whole-corpus differential returned **RED on run
  1: 1101 identical, 13 divergent, twelve differing in EXIT CODE** — the naive
  cache (restore inside `load_builtins`) MISCOMPILES. `compile_saw` parses the
  entry file first and builds builtins second, pickle preserves `node_id`
  verbatim where `__deepcopy__` deliberately freshens it, so restored std ids
  1..14,321 collide with the entry's and the effect graph merges two functions'
  suspend analysis — std then fails its own type-check
  (`Channel.receive` reported as a sync violation). It also made every
  surviving compile SLOWER (935 vs 369 ms/file) by perturbing the effect
  fixpoint. Fixed as the tier-B audit prescribed — restore before the entry
  parse, seed the counter past the graph via a stored upper bound (O(1), no
  walk). **So tier A needs the same `node_id` restructuring as tier B; its only
  claim to being the cheap option is gone.** Prototype is out of tree
  (`.build/scratch/sawc_cached.py`); see below for why it did not land.
- **Tier B — typechecked namespace: CLEAN, one mandatory fix.** 24% / ~19% /
  2-4 d / MEDIUM. The `(ast, ns)` pair pickles at 2.08 MB (gzip-1 → 0.30 MB),
  works at the default recursion limit, and every identity invariant survives a
  SINGLE-blob round trip — `SawType` aliasing `shared=106 broken=0`,
  `StructSymbol.ast_node` `ok=19 broken=0`, enum singletons `is`-identical;
  9/9 sample examples emit byte-identical IR from a restored namespace. The
  hazard is `node_id`: pickle preserves it, `__deepcopy__` deliberately
  freshens it, and `compile_saw` parses the USER file first — so restored std
  ids collide with user ids (~0.6% per entry extension) and corrupt
  `effects.py:255` and `coro_transform.py:5152` SILENTLY. Fix: restore the blob
  before parsing the entry file and seed the counter past it (free). **Never
  split the pair across two pickles** — that breaks the aliasing above and
  compiles a struct against another struct's layout with no diagnostic.
- **Tier C — precompiled std object: FEASIBLE ON IDENTITY, BLOCKED ON
  EXCLUSIONS.** ~87% of emitted IR / est. 3-5x on `hello` / 8-12 d / HIGH.
  Design 144 delivers what tier C needs and it was VERIFIED, not assumed: 312
  std symbols carry byte-identical mangled names across 12 programs and across
  targets. std bodies are byte-identical across programs once four counters are
  normalized (DF-164c). Non-generic std is 54.5% of std IR; adding the 142
  monomorphizations present in 13/13 binaries (92.3% of the mono weight, all
  arising from std instantiating ITSELF) covers ~96.5% of std IR. **The blocker
  is `compute_std_codegen_exclusions` (`sawc.py:401-469`): 288 distinct
  compiled-std sets over the 2^12 import subsets, and a fixed whole-std object
  re-opens the design-82/84 collision — verified, `struct File` + `import
  std.file` gives `ambiguous struct File` and the symbols hard-collide.**
  Unblocking whole-std means reversing design 144's std type-identity
  exemption — a user decision. Short of that, tier C is a content-keyed
  per-(triple, profile, exclusion-set) object cache in the `.build/rt/<hash>/`
  mould, which still captures most of the win.

**Corrected differential (run 2, prototype fixed, 1114 examples): every
semantically meaningful artifact matched — exit code, stdout, stderr and the
OBJECT FILE, on all 1114.** 43 differ in IR sidecar TEXT only, every one
DF-164a (`__collit_8` vs `__collit_14033`, objects byte-identical). The
mechanism generalizes: any std cache changes the ORDER node ids are allocated
in, so every `node_id`-derived generated name shifts. **GATE: RED on the strict
`.ll` oracle, and that upgrades DF-164a from cosmetic to PREREQUISITE** — no
std cache can pass an IR-level differential until those names are gone.

**Recommended order.** (0) **DF-164a first — it now gates every tier.**
(1) DF-164b dead-strip alone, 0.5 d, 52-76% off every binary, and it is the
precondition that makes any fixed-set std object size-neutral. (2) DF-164c
alongside DF-164a — same fix, six symbol families — clearing the entire
IR-variance obstacle to tier C. (3) Then **tier B, skipping tier A**: the gate
removed A's only advantage (it needs the identical `node_id` restructuring), so
A now differs from B only in payload size and ~8 points of win. Taking A now
and B later pays the hard part twice. (4) Tier C last, after the design-144
decision.

**Tier A did not land as a flag,** though the brief permits it: the gate is RED
on the strict oracle until DF-164a lands, and a default-off flag delivering
9.9% is a path nobody enables and everybody maintains. The prototype is one
commit away if the user wants it.

- **DF-164a — DONE (design 168 unit 3; 45 -> 0 on the whole-corpus re-emit
  differential). `__collit_{node_id}` leaks the process-global node counter into
  emitted IR.** `codegen/collections.py:86`. A process that compiles more than
  once emits different IR TEXT for identical source (`%"__collit_14189"` vs
  `%"__collit_29638"` on `place_paired_literal_fields.saw` and
  `shadow_owning_lifetime.saw`). Objects are byte-identical, so it is IR-only
  today — but `tools/irdet.py`'s one-compile-per-process oracle structurally
  cannot see it, and design 126 R2 introduced `node_id` precisely to make output
  reproducible. Same class at `codegen/match.py:152`, which builds
  `__match_scrutinee.{id(expr)}` from a RAW ADDRESS. Found by the tier-A
  differential, which then exonerated the cache with a fresh-vs-fresh repro.
  **PREREQUISITE for design 164 work**: gate run 2 showed 43/1114 examples
  diverging in IR text for this reason alone (objects byte-identical), because
  any std cache changes node-id allocation order. Fix it and the differential
  goes green on the strict oracle.
- **DF-164b — DONE (design 168 unit 1; 218,216 -> 62,712, both caveats checked).
  The hosted link line has no dead-strip.** `sawc.py:1146` is
  `["clang", obj, *rt_objects, "-o", out]` — no `-dead_strip`, no
  `--gc-sections`, no `-ffunction-sections`; hosted std keeps external linkage
  (0/312 internal, measured) so `-O1`'s `globaldce` cannot reach it either.
  Every Saw binary ships 52-76% dead std: `hello` is 218 KB of which 155 KB is
  unreachable, 534 external symbols of which 84 are live. Relinked with
  `-Wl,-dead_strip` the binaries still run, and `allstd` (every std module
  compiled in) strips to within 16 bytes of `hello`. Re-verified by hand:
  `hello` 218,216 -> 62,712 bytes (71%), output unchanged. One line, highest
  value per unit effort in the whole investigation, independent of every tier.
  ONE caveat before it lands blind: an `@export`ed symbol in a HOSTED
  executable that nothing references from the entry graph is exactly what
  dead-strip removes, so `@export`/`@section` and the design-149
  runtime-provider role need a deliberate keep (`-u`, or
  `__attribute__((used))`-equivalent linkage). `examples/export_roundtrip.saw`
  and the `EXPECT-SYMBOL-UNDEFINED` tests are the oracle. Freestanding and
  `--runtime-build` do not link at all, so they are untouched.
- **DF-164c — DONE (design 168 unit 3; and there were FIVE counters, not four —
  `.str.N` in `_create_string_constant` is the same class). Four
  synthesized-symbol counters make std's IR
  program-dependent for no reason.** `.sawstr.N` (`codegen/core.py:1534`),
  `.rawbytes.N` (`codegen/calls.py:478`), `__closure_N`
  (`codegen/closures.py:126`), `__task_tramp_N` (`codegen/calls.py:1805`) —
  one counter shared by std and user code, so any user string literal
  renumbers every std reference. Normalize all four and **0/312 std bodies
  differ across 12 programs**. Blocks tier C; harmless otherwise.
- **DF-164d — INVESTIGATED (design 168 unit 5), still open: see DF-168b. It is
  now the LARGEST single stage (30.3% of a `hello` compile) and the cheap skip
  does not exist, because std is the program place lowering rewrites.
  The front half re-typechecks std 2-3 times per compile.** The
  place-lowering re-entry (`sawc.py:1005-1024`) and the coro-transform re-entry
  (`:1040-1075`) each re-run `build_builtin_namespace`. Design 146 removed the
  re-PARSE; the re-CHECK remains at ~150 ms a pass and NO cache can serve it,
  since the AST being rechecked is the program's own mutated std. Whether the
  second check is necessary was not established — worth a look, because
  removing one pass is worth about as much as tier A.
- **VERIFY (not a defect, a measurement correction for future gates): the
  linked binary is not a reproducible artifact on macOS.** It carries an N_OSO
  debug-map stab holding the object's path and mtime, so two COLD compiles of
  one file into different directories already differ. Byte-compare the `.ll`,
  the `.o`, and exit/stdout/stderr — not the executable.

## Design 168 — the compile-speed batch: LANDED (Aug 7)

Design 164's four findings, built. Full results in
`designs/168-compile-speed-batch.md`; the headline is that **the profile
INVERTED**. The back half was 64% of a compile and is now under 15%, which
promoted the front half from "worth ~19%" to the dominant cost and made tier B
worth roughly double the investigation's estimate. Every wall-clock figure is an
INTERLEAVED A/B ratio against a sibling worktree (DF-156a method): this box
demotes busy work to efficiency cores, so identical work drifted 2.6x across the
session while load average ranged 3 to 71, and only paired ratios mean anything.

- **Unit 1 (DF-164b) — link dead-strip.** `hello` 218,216 -> 62,712, the
  investigation's number exactly; the flag itself costs nothing (24 ms link
  either way). Both caveats CHECKED: an `@export` nothing references survives
  (`nm` finds it), and the darwin N_OSO debug map coexists with the strip (lldb
  resolves `hello.saw:7` identically stripped and not). Exports are also passed
  as `-Wl,-u` keep-roots, since the ELF lowering of `@llvm.used` cannot be
  verified from this host. Pinned by `examples/link_dead_strip.saw`, which reads
  its own binary back.
- **Unit 2 — the pre-LLVM reachability strip. 2.3x (B/A = 0.433), no cache
  involved.** hello 449 defines -> 17, 27,928 IR lines -> 1,068; over a
  six-program spread -86.0% defines and -84.4% IR lines. Declaration stays
  eager (codegen resolves callees by bare `self.functions[name]` lookup), only
  bodies defer. **Reachability is read off the EMITTED IR, not walked on the
  AST** — an AST walk would have to re-derive overload resolution, trait
  dispatch, drop glue, closure/trampoline synthesis and the coro transform's
  callees, and every gap is an over-strip. The fixpoint owns the
  monomorphization and vtable queues, so vtables PULL their methods.
  `irdet --all` stayed green: the reachable set is deterministic.
- **Unit 3 (DF-164a + DF-164c) — deterministic synthesized names.** Seven sites,
  not six (`.str.N` was a fifth counter the finding missed). New oracle
  `tools/reemitdiff.py` compiles each example twice INSIDE one process, which is
  what irdet structurally cannot see and what the suite's persistent workers
  actually do: **858 identical / 45 divergent before, 903 / 0 after**, every
  divergence `.ll`-only. That 45 is design 164's 43, found independently.
- **Unit 4 — tier B, the front-half cache. 39.4% (B/A = 0.606).** One 2.08 MB
  pickle of the `(ast, ns)` pair, keyed exactly per 164 unit 5. The decision
  that mattered: **the stdlib is built before the entry parse on the COLD path
  too.** Restore-before-parse is required for correctness (pickle preserves
  `node_id`), but making the cold path agree is what makes the cache INVISIBLE
  rather than merely safe — both paths allocate ids in the same order, so warm
  output is byte-identical to cold. Combined with unit 2, 3.8x on a `hello`
  compile.
- **Unit 5 (DF-164d) — measured, not skippable at small cost.** See DF-168b.

**End to end**, against a worktree at the pre-batch commit:

| workload | before | after | |
|---|---|---|---|
| `hello.saw` CLI compile | — | — | **B/A = 0.270, 3.7x** (5 interleaved pairs) |
| suite COMPILE phase | 362.1 s | 138.6 s | **2.6x** (back to back) |
| `blade_bootstrap` | 850.1 s | 264.8 s | **3.2x** (back to back) |
| `hello` binary | 218,216 B | 62,712 B | -71% |

**A note for whoever next reads a red suite here.** Unit 2 makes the compile
phase ~2.6x faster, which CONCENTRATES the runner's execution phase into a much
shorter window. On a box already loaded by sibling agents that is enough to
starve the 40 execution workers: three runs at the tip returned 21, 905 and 567
failures, every one of them a 30-second EXECUTION timeout (never a compile
failure, never a wrong answer), including on programs like `while_simple` that
cannot hang. `-j 4` returned 1367/1367 on the same tree. Read the failure
REASON before believing a red run.

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

`designs/138-readme-docs-pass.md` closed, at the user's expanded scope: a
claim-by-claim pass across LANGUAGE_SPEC.md, the saw-lang skill, README.md and
CLAUDE.md's orientation digest, plus TESTING.md for accuracy. Docs-only; the
compiler was the oracle wherever two sources disagreed, and every README example
was extracted to `.build/scratch` and built. **The discrepancy list IS the
review artifact** — 23 items, grouped by source.

**LANGUAGE_SPEC.md** (commits d9cb1d2, 0a05ac6)
1. Seven sites named the runtime seams `saw_panic` / `saw_alloc` /
   `saw_dealloc`. The frozen ABI has been `__saw_rt_*` since design 113/117 and
   no symbol spelled the old way exists in `sawc/`; the spec used the right
   names in its Profiles and Allocation-failure sections, so it disagreed with
   itself.
2. `Mutex.lock` was documented as returning `Bool` ("the `false` from `lock` is
   the one the closure computed"). It is `lock<R>(body: (&var T) sync -> R) -> R`
   (`std/mutex.saw:84`) — the same shape `SpinLock.lock` had documented
   correctly two sections away.
3. Built-in Functions predated design 137: `print` took "Int family, `Bool`,
   `String`, `Float`", and `panic`/`assert` took a `String`. All three take any
   `Printable` and a `{}` format string.
4. §9 listed invented module paths — `std.option`, `std.vec`, `std.collections`,
   `std.io`, `std.fs`, `std.fmt`, `std.iter`, `std.cmp`, `std.hash` — and called
   the Optional type `Option`. Harmless as sketch in Jul; since design 82 made
   each std FILE a module and design 150 made the leaf name the thing an import
   binds, they read as instructions. Replaced with the 23 real modules.
5. Appendix 0 omitted `--target-features`, `--runtime-provider`, `-W NAME` and
   `--ids`.
6. Appendix A listed `const` as planned though const generics landed in design
   148. It is contextual, not reserved — `let const = 3` compiles (probed).

**saw-lang skill** (commit 056d925)
7. "Still open: `Mutex.lock`'s result is `Bool` rather than the closure's own
   type (M1, blocked on DF-123c — Arc payload forwarding cannot reach a
   method-generic method)." Both halves are stale: M1 landed, and
   `Arc<Mutex<Int>>.lock({ c in c = c + 5  c })` returns 5. **DF-123c is
   CLOSED.**
8. The copy-tier line listed NoCopy as "File, Mutex, Box, Map/Set". `Data`,
   `StringBuilder`, `TcpListener`/`TcpStream`, `Command`, `TaskGroup` and
   `SpinLock` are NoCopy too, and `Vector` is the ONLY ExplicitCopy type in std.
   `Data`'s inherent `copy()` is a plain method, not a policy — the thing that
   misleads.

**README.md** (commits fe3c595, 38129c9). Four examples did not compile:
9. Error Handling with Result: `case Ok(n)` under the `let n = try! …` three
   lines above is design 100's pattern-binding shadow error.
10. Generic Type Inference: `func first<T>(v: &Vector<T>) -> T? { v.get(0) }` is
    design 146's place-read-in-a-generic-body error — needs `T: Copy`.
11. Kernels and Embedded: `UART_BASE` was never declared and the closing
    `print(...)` sat at top level.
12. Cooperative Networking: the accept loop ran at top level and spawned into a
    `group` that did not exist.
13. Current Status had not moved since design 134 — no places, const generics,
    backed enums, import forms, Result-discard, alloc-free formatting,
    `--no-hidden-alloc`, `SpinLock`/`unsafe static var`, or warnings.
14. `--runtime-provider` missing from the options block.
15. Copy tiers stated twice (Key Features + Memory Management) and allocation
    failure stated twice (Memory Management + Kernels), each pair near-verbatim.
16. A heading carried "(design 64)"; saw-docs keeps design numbers out of
    user-facing pages. None remain in README.
17. Audience order put bare metal last; "comprehensive test runner" and an
    exclamation-mark Contributing line were the remaining voice defects.

**CLAUDE.md orientation digest** (commit 8d661be)
18. Claimed "landed through design 136 (Aug 5)" while 137, 139, 141-151, 159 and
    161 had landed. Added the Aug-6 paragraph; also noted which of 152-158 are
    still briefs, since the numbering alone no longer says.
19. Accessor rule said `get`-shaped accessors return `None`; the spec says
    `None`/`Err` and names `Data.slice`. Import-required list omitted `SpinLock`
    and `std.fixedbuf`.

**TESTING.md** (commit ed5bb03)
20. Every invocation was bare `python3 test_runner.py`, which compiles nothing —
    llvmlite is in `.venv`. Same for the "compile manually" debugging step.
21. The Directive Reference listed 8 of 15 directives, missing `EXPECT: object`,
    `EXPECT: docs`, `EXPECT-WARNING-CONTAINS:`, `EXPECT-NO-WARNINGS`,
    `EXPECT-SYMBOL-UNDEFINED:`, `EXPECT-OBJECT-MAX-BYTES:` and
    `COMPILE-FLAGS:`.
22. Example 1 declared `func distance(self)` — a bare `self` receiver, a compile
    error since design 128. The guide's first worked example did not compile.
23. The xfail section framed yellow tests as "expected and deliberate" with a
    `196 passed, 1 xfailed` tally, against a standing zero-xfail bar and an
    `examples/` tree that holds none. The `blade test` example imported
    `src.toml` (really `src.lib`) and called `doc.get_section(...)`, removed by
    DF-132a.

### DF-138a — ICE: a suspending function that is both a task ROOT and a SUB-FRAME

**CLOSED (Aug 7, commits 3104524 + the audit commit below).** Found while
compiling the README's concurrency examples. Each README block compiles alone
and `report()` prints exactly the documented `squared: 25` / `74`; the crash
needs both shapes in one program. Minimal repro (14 lines):

```saw
import std.task.*

func leaf(n: Int) -> Int { yield_now()  n }
func caller() -> Int { return leaf(3) }

func main() {
    var group = TaskGroup()
    let a = group.spawn(leaf(1))     // leaf spawned as a ROOT
    let b = group.spawn(caller())    // and embedded as a SUB-FRAME of caller
    print(a.join() + b.join())
}
```

```
AttributeError: 'NoneType' object has no attribute 'line'
  sawc/typechecker/expressions.py:5115, in _check_struct_init
  <- _check_init_field_value <- _check_erased_box_make (expressions.py:6259)
  <- _check_method_call (expressions.py:6531)
```

Spawning `leaf` alone, `caller` alone, two roots of differing arity, or two
groups all compile — it is specifically one function serving as both a spawnable
root and an embedded callee. The filer's read ("a synthesized frame-init node
built twice under two different lowerings") was close: it is ONE node built for
the WRONG lowering.

**Root cause — two roles are two frame PROTOCOLS, and a function had one frame.**
A spawn root keeps its result and its cancel word in the group-owned CELL it
reaches through `__cellp` (design 134), which is what lets the frame box be
released the instant the task completes. A driven root and an embedded sub-frame
keep both IN the frame: a sub-frame is copied its root's cancel word at every
drive (design 102) and hands its result up to its parent. `_FrameBuilder` took
`is_spawn_root` straight from "is this name a spawn root", so a dual-role
function got the spawn layout in BOTH roles — `_build_frame_init` then emitted
`("__cellp", None)` for the embedded copy, the `None` the second typecheck died
on. Getting past that field would only have moved the failure: the embedded
frame had no `__cancel` to receive the copy-down and would have written its
result through a pointer to nothing. The layout was wrong, not the field.

**Fix — the spawn role gets a frame of its own, when and only when the function
has another role.** `_make_spawn_trampoline` synthesizes

```saw
func f$spawnroot(<params of f>) -> T { return f(<params>) }
```

whose single statement is the ordinary `return g(args)` tail the transform
already lowers. `f$spawnroot` is the spawn root, so ITS frame carries `__cellp`;
`__Frame_f` is embedded below it in the driven flavour, the same shape every
other embedded callee has. The cancel word propagates down the chain and the
result threads back up through the existing machinery, so neither protocol grew
a special case and `f` keeps exactly one frame however many roles it plays. A
spawn-only root is still its own spawn frame and pays nothing — not a field, not
a hop. Design 134's `__saw_drive`+spawn rejection went with it: that was the
same limitation seen from the other side, and the trampoline serves it too, so
`coro_drive_and_spawn_rejected.saw` became `coro_drive_and_spawn.saw`.

**The role matrix was audited end to end. Nothing in it is genuinely illegal —
every shape that failed was a compiler limitation, and all of them now work.**

| shape | before | now |
| --- | --- | --- |
| spawned + embedded as a sub-frame | ICE | works |
| spawned + driven in place (`__saw_drive`) | design-134 rejection | works |
| spawned + driven + embedded, all three | rejection | works |
| driven root + embedded | already worked | unchanged |
| generic: one instantiation a root, ANOTHER embedded | already worked | unchanged |
| generic: the SAME instantiation in both roles | ICE | works |
| method: driven root + embedded | `KeyError` ICE | works (DF-138e) |
| method: `Dual<T>.mix<U>` (design 104 dual-generic keying) | clean rejection | unchanged |

A generic's roles are per INSTANTIATION, because a generic spawn root is keyed
by its mangled symbol (design 70) — which is why the split case never collided
and the same-instantiation case was the identical bug. The design-104
dual-generic keying is untouched and cannot reach this bug at all: `spawn` takes
a free function, so a method is never a spawn root, and a generic-struct or
method-generic method is excluded from sub-frame embedding by the closure walk
and rejected at its call site by `_reject_suspending_method_call`. That
rejection is a pre-existing design-104 limit on embedding generic METHODS, not a
role-tracking failure, and it is a clean anchored diagnostic rather than a crash.

Tests: `coro_spawn_and_embed` (two-deep chain, every link also spawned),
`coro_spawn_and_embed_owning` (move-only param + refcounted result with a
live-count oracle, plus the `Void` twin), `coro_spawn_and_embed_generic`,
`coro_spawn_and_embed_cancel`, `coro_spawn_and_embed_mt`,
`coro_drive_and_spawn`, `coro_method_root_and_embedded`,
`coro_nested_generic_tail`.

No doc claim was wrong because of any of this (the spec's sub-frame-embedding
claim held throughout), so no user-facing prose needed correcting.

### DF-138d — a nested suspending GENERIC call was promoted only from a `let`

**CLOSED (Aug 7, the same audit commit).** Found building DF-138a's role matrix.
`let r = work<A>(x)` inside a driven or spawned body compiled; `return
work<A>(x)` and a trailing `work<A>(x)` did not, failing with

```
cannot suspend in `sync func` method: method `__Frame_caller.resume` calls `work`
```

— a complaint about a `sync` region the user never wrote, naming a method the
compiler had synthesized.

`_classify_call` has always accepted the design-83 tail `return g(args)`, but
`_promote_nested_generic_calls` — the walk that splices a nested generic call's
concrete instantiation and rewrites the site to the mangled symbol — looked only
at `LetStatement` and bare `ExpressionStatement`. A tail-position generic call
was therefore never promoted, reached the embedding machinery still generic, and
left the template as a plain call inside a body that had already become a resume
method. Fixed by teaching the scan the `return` form and a block's `final_expr`
(where the parser parks a bare trailing expression; design 83's tail
normalization would convert it, but that runs inside `prepare`, long after the
promotion). Test: `coro_nested_generic_tail`.

### DF-138e — a driven-root METHOD that is also embedded ICEd with a `KeyError`

**CLOSED (Aug 7, the same audit commit).** DF-138a's shape with the roles
swapped onto a method. A suspending method both `__saw_drive`n directly and
called from another driven body died on `KeyError: 'Counter_climb'` in
`_emit_nested_call`.

The closure walk skipped adding a method to `method_closure` when its frame key
was already a driven method root, on the stated belief that the embedding site
would then be rejected cleanly by `_reject_suspending_method_call`. It is not:
`_classify_method_call` asks only whether the method suspends, so the site was
classified and embedded, and then looked up a frame nobody had built — method
ROOT frames were built in a later loop and never registered in `fbs`.

A driven method root and an embedded method sub-frame are the SAME frame
(neither is a spawn root), exactly as a free function in both roles already
shared one. So the skip is gone and the method joins the closure normally; the
method-root loop now reuses `fbs[frame_key]` when it is already there and emits
only the drivers. Test: `coro_method_root_and_embedded`.

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

## Design 159 — the implicit-tier copy miscompile (LANDED, Aug 6)

`designs/159-implicit-tier-copy-fix.md` closed. The P0 fix for DF-151b and
DF-156b: an undeclared ImplicitCopy composite now copies through the same
machinery a declared one does. Five commits, full suite green each.

**Gate battery, all green.** Suite 1317 (zero xfails, +3 new examples);
lexdiff 0 mismatches over 1460 files (tokens + docs); astdiff stable over
1460; `irdet --all` 863 examples byte-identical; blade_bootstrap ok
(stage0->stage2, 19/19, both libs); sos_runner 3/3; gmgate 12 programs x 20
runs clean.

**The headline validation — the two DF-151b victims, 100 runs each, both
ways.** `blade lock_drift` 0/100 under Guard Malloc and 0/100 native;
`closure_copyable_struct_copied` 0/100 and 0/100. Pre-fix these were 10/10
and 30/30 crashes under Guard Malloc, and 14 and 21 per 100 native. The
bootstrap, which the tracker measured failing about five runs in six, passed
first try.

- **Unit 1 — THE BISECT ANSWER IS SPLIT, and that decides the shape of the
  fix: it is a FROM-SCRATCH repair, not a revert.** The brief asked whether
  this is a regression or ancient. It is BOTH — two transfer sites, two
  different histories, one shared root cause.
  - **Local-to-local (`let b = a`) — a REGRESSION, first bad commit
    `ddafb59`** ("design 147 unit B: a `let` initializer retains what it
    reads (DF-139a)", Aug 5). Bisected over `a5efd7a..7e11853` (440 commits,
    Guard Malloc on `.build/scratch/probe_structcopy.saw` — a `struct P {
    name: String }` with an INTERPOLATED name, `let b = a`, `let c = b`):
    clean 0/10 at design 73 (`a5efd7a`), 120 (`ddb698a`), 141 (`cd02bd5`),
    147-unit-A (`6081181`); 10/10 from `ddafb59` onward. Verified at design
    73 that the clean answer is a real RETAIN and not a leak: `main`'s IR
    carries two inlined `String_copy` (`atomicrmw add` x2) against three
    `String_deinit` (`atomicrmw sub` x3) — rc 1 +2 -3 = 0, balanced.
  - **The irony is exact.** `ddafb59` REPLACED an unconditional
    `isinstance(stmt.value, Identifier)` -> `_generate_copy` in
    `_generate_let_statement` with the shared oracle
    `_transfer_needs_copy`. The old hand-rolled test was WRONG for
    projections (that was DF-139a, correctly fixed) but ACCIDENTALLY RIGHT
    for the whole-binding read, because `_generate_copy` falls through to
    `_deep_copy_value` for any cleanup-owning struct. Routing through the
    shared oracle was the right move; the oracle just could not answer this
    question. So reverting would re-break DF-139a and fix only half of this.
  - **By-value argument (`consume(a)` twice) — ANCIENT, never worked.**
    10/10 under Guard Malloc at `3716961` (design 135) AND at `a5efd7a`
    (design 73), the oldest point tested. `_gen_transfer_value` has always
    used `_transfer_needs_copy`, so this spelling never had the accidental
    retain the `let` path had. This is why the fix must be in the ORACLE:
    it is the one place both spellings meet.
- **The root cause, one line of it.** `Namespace.copy_tier`'s STRUCT branch
  (design 139's oracle) has NO structural join. An ENUM gets one —
  `_enum_structural_copy_tier` joins its payload tiers — but a struct with
  no DECLARED policy falls straight through to `return 'free'` regardless of
  what it owns. `_get_cleanup_behavior` mirrors the same asymmetry: it has an
  `is_implicit_copy_enum` arm and no struct equivalent. So for
  `struct P { name: String }`: `_needs_cleanup` says True (a drop IS
  registered per binding) while `_get_cleanup_behavior` says `"none"` and
  `_transfer_needs_copy` says False (no retain). One allocation, N releases.
  The container-slot arm of `_transfer_needs_copy` explicitly excludes a bare
  `Identifier`, which is why field/element reads were correct throughout and
  only the WHOLE-BINDING read was wrong.
- **The two-path proof.** `struct P { name: String }` copied twice is 10/10
  under Guard Malloc; the byte-identical program with `@synthesize extension
  P: ImplicitCopy {}` added is 0/10. Same shape, same fields, same copies —
  the only difference is which of the two lowering paths the tier arrived by.
  That is the brief's "second, conformance-less path that nothing
  user-visible tested", isolated to a two-line diff.
- **Unit 2 — ONE lowering path.** `copy_tier`'s STRUCT branch got the
  structural join, the exact counterpart of `_enum_structural_copy_tier`
  (cycle guard + type-argument substitution included), and
  `_get_cleanup_behavior`'s enum-only `is_implicit_copy_enum` arm became
  `is_structurally_implicit_copy`, which answers for both kinds. Codegen's
  `_generate_copy` did NOT change: it always knew how to retain a
  cleanup-owning aggregate recursively (`_deep_copy_value`); what was missing
  was the predicate telling it to. One oracle, so both spellings are fixed by
  one edit — which is why the split bisect answer pointed at the oracle rather
  than at a revert.
- **The transfer-site audit, against `Namespace.copy_tier`.** Eleven classes
  probed under Guard Malloc for the undeclared tier
  (`examples/df151b_implicit_tier_transfers.saw` is the probe, promoted):

  | transfer class | before | after |
  |---|---|---|
  | local-to-local `let b = a` | CRASH (regression, ddafb59) | clean |
  | by-value argument | CRASH (ancient) | clean |
  | return (whole binding + field read) | clean | clean |
  | field write `h.p = a` | clean | clean |
  | enum payload (String) | clean | clean |
  | `Optional<P>` wrapper | clean | clean |
  | tuple wrapper | clean | clean |
  | fixed-array repeat `[a; 3]` | REFUSED at compile time | clean |
  | `Vector<P>` element read-out | clean | clean |
  | nested struct (`Nest { p: P }`) | CRASH | clean |
  | closure field | CRASH | clean |

  Struct-literal CONSTRUCTION was clean throughout, as the investigation said.
- **Two more sites found by the audit, both PRE-EXISTING** (verified against
  baseline main `50831ff`, so neither was introduced by unit 2):
  - The REPEAT LITERAL asked a conformance lookup (`_is_implicit_copy_type`)
    instead of the tier oracle, so it could not see the undeclared tier and
    refused `[p; 3]` on a `struct P { name: String }` — with a diagnostic
    naming a policy the type does not have and cannot be given: "a repeat
    literal needs a freely copyable element, and `P` is ExplicitCopy". Now asks
    `copy_tier` and accepts what copies for free. NOTE the containment check
    must keep using the conformance predicate: making
    `_is_implicit_copy_type` structural would demand a policy from every struct
    holding a String, which is precisely the rule the user ratified against.
  - `_emit_copy_value` — the per-ELEMENT path behind array and optional deep
    copies — lacked `_generate_copy`'s cleanup-owning fallthrough, so allowing
    the repeat literal above would have splatted one String into three slots
    with no retain and released it three times. Same recursive retain now.
- **Unit 3 — oracle hardening.** (a) Every string in the new oracles is
  INTERPOLATED; a literal is immortal (rc -1) and cannot fail. (b) The
  refcount-balance oracle counts an `Arc` reached through an undeclared struct
  wrapping an undeclared enum (`Wrap { h: Holder }`) — the only countable shape
  for this tier, since `String` exposes no refcount and an `Arc` FIELD would
  force a declaration. It has teeth: pre-fix it printed
  `balance-struct 1 3 3 218691215664472001`, ran the payload's deinit before
  its owner returned, and died of SIGTRAP. (c) `closure_copyable_struct_copied`
  now carries, in the file, WHY it could not catch this itself —
  `strong_count` reads the ARC, not the ENV, and a dtor fires on the 1 -> 0
  edge and never again, so neither a count assertion nor a deinit-print oracle
  can see a double release. Its real detector is the Guard Malloc lane, which
  the comment now says outright. (d) The stricter NoCopy override is pinned
  both ways (`nocopy_override_implicit_tier.saw` +
  `errors/nocopy_override_implicit_tier_copy.saw`). It was untested: all 45
  bare `NoCopy` declarations in the corpus sit on containment-FORCED structs,
  and the closure-field variant had no coverage at all.
- **Unit 4 — the Guard Malloc lane.** `tools/gmgate.py`, `make gmgate`,
  documented in TESTING.md. Twelve ownership oracles x 10 runs under
  `libgmalloc`. Small on purpose: a page per allocation is far too slow for the
  whole suite, and what it must police is the tests that assert something about
  copies, retains, drops or refcounts. macOS only; SKIPPED (exit 0) elsewhere.
  TESTING.md tells the next author to add to `GATE` when writing such a test.
- **Unit 5 — docs.** The automatic tier is now stated plainly in
  LANGUAGE_SPEC ("The automatic `ImplicitCopy` tier"), the saw-lang skill's
  ownership section, and README. All three say the same three things: such a
  type IS ImplicitCopy with no declaration owed, its copy retains each
  refcounted member, and the stricter `NoCopy` override is legal. The spec and
  skill also correct a real trap the old wording left open — `Arc` is
  ImplicitCopy, but an `Arc` FIELD still owes a declaration; only the members
  the compiler retains for you (String, escaping closure, arrays of those,
  another composite already on the tier) are exempt.

- **DF-159a — CLOSED by design 161 (Aug 6).** `t.0.name` was a lex error: the
  number scanner, started on a tuple index after a member-access dot, ate the
  second `.` as a float. Fixed in both lexers; the `(t.0).name` workaround this
  file used is gone. See the design 161 entry below.

## Design 150 — Rust-style imports (LANDED, Aug 6)

`designs/150-rust-style-imports.md` closed, all seven pins plus the `-W`
surface. The brief called it a deletion and it was one: design 82 Part B's
`_process_std_import` bare-exposed a whole-module std import and supported
neither `.*` nor qualified access, and std now goes through the same three
forms a user module always has.

- `import std.file` binds the qualifier `file` and exposes NOTHING bare;
  `import std.file.*` is the bare opt-in; `import std.file.{A, B as C}`
  selects bare AND binds the qualifier. `as` renames the qualifier.
- The qualifier resolves through a per-std-FILE `StdLeafNamespace` over the
  already-checked builtin namespace, SHARING its symbol objects — one type,
  one identity, one mangling whichever spelling reaches it. Design 82 gave
  each std file its own module identity; this is the namespace half.
  Visibility in the view is membership: std's top-level declarations carry
  no `public` marker (the prelude gate decides who may name one), so an
  ordinary check would refuse every std type through its own qualifier.
- **Pin 4 was load-bearing, not a nicety.** Four examples broke the instant
  `data` became a qualifier, every one a local named after the leaf it
  imports. Resolution now runs local scopes -> module-level declarations ->
  imported bare names -> qualifiers LAST, in typechecker and codegen alike,
  with no shadowing error and a lexical shadow. That was design 82's stated
  reason for never creating the alias; it is a rule now instead of an
  omission.
- Migration: 97 files, 101 whole-module std imports rewritten to `.*`,
  landed as its own commit BEFORE the semantic flip so the flip had no
  in-tree fallout to absorb. No idiom churn.
- `-W <name>` / `-W all`, off by default, never affecting the exit code.
  First category `shadowed-qualifier`, at the declaration. The reporter's
  warning path had zero call sites and needed three fixes before it could
  carry one: invocation-wide enablement + dedup (the pipeline re-enters its
  front half twice with a fresh reporter, so the warning printed twice),
  `print_warnings` on the success path (`print_all` runs only on failure, so
  a warning on a clean compile was collected and dropped), and yellow with a
  `[-W category]` label instead of error red.
- The test runner could not SEE a warning — `EXPECT-ERROR-CONTAINS` is
  consulted only when compilation fails. Added `EXPECT-WARNING-CONTAINS`
  and `EXPECT-NO-WARNINGS`; the latter is what pins the category's silence.
- Suite 1332 -> 1341.

### DF-150 findings (all FIXED in the brief)

- **DF-150a — `&any qual.Trait` did not resolve.** `_resolve_type` had no
  EXISTENTIAL branch, the same shape DF-140c fixed for references one
  composite over. Every downstream consumer compares trait NAMES (method
  dispatch on the erased value, the conformance check at an erasure site,
  vtable selection) and none strips a qualifier, so the spelling travelled
  intact and failed at the far end with "unknown trait `qmod.Named`".
  Resolved to the trait's identity at resolution now. `get_trait_info` also
  gained the visibility-honoring cross-module fallback its struct and enum
  siblings have had since design 40. Repro:
  `examples/import150_qualified_trait.saw`.
- **DF-150b — `<T: qual.Trait>` did not PARSE.** The bound grammar read one
  identifier ("Expected '>' after type parameters" at the dot). Bounds take
  a dotted path now. Second half: a bound is a bare STRING, so
  `_canonicalize_module_types` sent it through `_canonical_type_name`, which
  deliberately leaves dotted names for `_resolve_type`'s module-walk —
  bounds and parent traits get their own resolver. Same repro.
- **DF-150c — the explicit-type-argument bound check used a non-walking
  conformance query.** `get_conformances` reads only the current namespace's
  table while the inference path beside it used the module-WALKING
  `_bound_satisfied`, so `Point` satisfied `Named` under
  `import qmod.{Point, Named}` (the selective form copies conformances in)
  and not under `import qmod`. Design 142 makes a conformance coherent
  program-wide and visible wherever the type and the trait both are — the
  IMPORT FORM must not decide the answer. Both paths walk now.
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

- **DF-163a — FIXED (Aug 7, commit d98d413). `-> &T` escaped the "references
  are parameters only" rule.** Probe: `func dangle() -> &Int { let local = 99
  return &local }` COMPILED and ran, printing 99 out of a dead frame. `return &v`
  (forwarding a `&Int` param) compiled too. Only `return v` was caught, and by
  accident — the reference decays to `Int` on read, so it failed the return-TYPE
  check rather than a positional one. LANGUAGE_SPEC said references are never
  returned or stored and that the Law of Exclusivity's soundness RESTS on that;
  nothing enforced it.
  **Fix:** a return type that NAMES a reference is refused in the PARSER, at the
  return-type token, in every position a return type is written — `func`,
  extension method / `init`, trait requirement, `extern func`, and the function
  TYPE `(Int) sync -> &Int`. Four declaration sites now share
  `parse_return_clause` (`parser/types.py`), which calls the one rule; the
  function-TYPE arrow calls it directly. The walk reads what the type NAMES, not
  its outer spelling — `(Int, &Int)`, `&Int?` and `Vector<&Int>` compiled and ran
  before and are refused now — and stops at a NESTED function type, whose
  parameter list takes references legitimately (`(&T) sync -> R` is
  `Vector.with_ref`'s callback) and whose own return is checked at its own arrow.
  The message names the parameters-only rule and both outs: return the value, or
  lend the storage with a `borrows` accessor. Reliance audit before the change
  found ZERO `.saw` sites in the tree (1511 files) declaring a reference return
  and ZERO compiler sites synthesizing one, so no carve-out was needed;
  `borrows -> T` is spelled with no `&` anywhere and is untouched. Tests:
  `examples/errors/ref_return_{dangles,method,trait_method,extern,function_type,
  var_flavor,nested_in_tuple,suspending_anchored}.saw` (the investigation's
  dangling probe is the first) plus the positive
  `examples/ref_return_alternatives.saw`, which pins what stays legal.
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
- **DF-163c — FIXED (Aug 7, commit d98d413, with 163a).** The driven
  (non-spawn) case of a suspending function returning a reference reported
  ``cannot assign `&Int` to field of type `UnsafeConstPointer<Int>` `` at
  `0:0` with no source anchor — an internal message leaking through the design-74
  (A8) anchoring rule. It was a fence (nothing compiled), just an ugly one.
  Refusing the DECLARATION closes it: the transform never sees the signature, and
  the message is now the same anchored sentence every other position gets.
  `examples/errors/ref_return_suspending_anchored.saw` asserts the exact
  `Parse error at 15:23:` anchor, so a regression to `0:0` fails the suite.

### DF findings from the 163a fix (Aug 7)

- **DF-163d — FIXED (Aug 7), all four positions.** References are
  parameter-only (plus the implicit lend a `borrows` accessor makes, and the
  one unsafe-tier crossing DF-163f rules on). What closed each:
  - **LOCAL BINDING (and every other non-argument expression position)** — the
    `expr.mutable and` guard in `_check_reference_expr` is gone, so the rule
    now covers `&` and `&var` alike: `let r = &x`, an operand, a literal
    element. The message is one sentence for both flavors, anchored at the
    sigil, and it RECOVERS as the written reference type so a misplaced `&`
    does not drag an "undefined variable" cascade behind it. The carve-out
    DF-163f ratifies rides on a `to_pointer_cast` annotation the CAST check
    sets (that is the node that knows the parent).
    `examples/errors/ref_nonarg_binding.saw`,
    `ref_cast_to_int_not_blessed.saw`; `ref_sigil_nonarg_position.saw` (the
    `&var` twin) moved onto the new wording.
  - **struct FIELD** — `parse_struct` refuses a field type that NAMES a
    reference (`reject_reference_field`, `parser/types.py`, on design 163a's
    walk). Refusing the DECLARATION closes the CONSTRUCTION with it: no field
    has a reference type, so `Holder(r: &x)` has nothing to fill, which is why
    the field is the position that must say no (a struct literal is not a call
    argument). `examples/errors/ref_field_type.saw`,
    `ref_field_nested_in_tuple.saw`.
  - **type ARGUMENT** — `_parse_one_type_arg` refuses an argument that names a
    reference, covering both spellings (`let v: Vector<&Int>` and the
    instantiation `idn<&Int>(&x)`), which leaves `v.push(&x)` alone at the call,
    where a reference argument means what it says. The refusal raises
    `ReferenceTypeArgument` under a new `CommittedGenericError` base that the
    speculative generic-vs-comparison lookahead lets through — a plain
    `SyntaxError` there backtracks into a nonsense comparison and buries the
    message. Design 129's trailing comma moved onto the same base. `a < b > c`
    still parses as a comparison. `examples/errors/ref_type_arg_generic_struct.saw`,
    `ref_type_arg_generic_func.saw`.
  - **closure INFERRED return** — `_reject_reference_closure_return` runs at
    closure inference (the declaration-side rule has no return type to read),
    anchored on the body's tail expression and recovering as the VALUE type so
    one mistake yields one message. `{ e in e }` is untouched: reading a
    reference binding yields the value, so `with_ref`'s identity closure infers
    `T`. `examples/errors/ref_closure_return_inferred.saw`.

  Positives pinned in two files. `examples/ref_pointer_cast_blessed.saw` covers
  the DF-163f crossing in every shape std and the runtime use — a local
  binding, a method RETURN, the shared const-pointer flavor, and the chained
  `as UnsafePointer<Int> as Int` token. `examples/ref_parameter_positions.saw`:
  `&`/`&var` arguments to a function and to a method, a forwarded re-borrow, a
  reference argument to a GENERIC call (type argument at the value type — the
  discrimination the type-argument rule has to make), the `with_ref` identity
  closure, and a `borrows` window read + write. Original finding follows.
  With `-> &T` closed, a bare `&` in a
  NON-argument position is the remaining way out, and all three shapes compile
  and RUN today:
  - bound to a local — `let r = &x`, then `read_one(r)` prints;
  - stored in a struct FIELD — `struct Holder { r: &Int }`, built with
    `Holder(r: &x)` and read back;
  - as a TYPE ARGUMENT — `Vector<&Int>` with `v.push(&x)`, and a generic
    instantiated at a reference (`idn<&Int>(&v)`);
  - returned out of a CLOSURE by inference — `let f = { &x }` types `() -> &Int`,
    since a closure literal has no written return type for the declaration-side
    rule to read. (The `with_ref` identity closure `{ e in e }` is NOT this case:
    the reference decays to the value on read, so `R` infers `Int` — probed.)

  `expressions.py:657-665` already rejects the `&var` flavor everywhere but a
  call argument (design 34), and a struct-init argument does NOT count as one —
  `Holder(r: &var x)` is refused today, probed. So dropping the `expr.mutable
  and` guard closes THREE of the four in one edit (the binding, the field
  construction, the closure body), and the design-163a reliance audit found ZERO
  in-tree uses of `&` outside a call argument across 1511 `.saw` files, so the
  blast radius looks empty. The TYPE-ARGUMENT case survives it and needs its own
  rule: `v.push(&x)` into a `Vector<&Int>` is a genuine call argument, so what
  has to be refused there is naming a reference as a type argument or a field
  type at all. Not landed with 163a because it is a language-surface RULING
  rather than a bug fix — it decides whether a reference may ever be named
  outside a call — and it reaches fields, bindings, captures and type arguments
  rather than the one position DF-163a named. (The one claim above that did not
  survive contact: the blast radius was NOT empty. See DF-163f.)
- **DF-163e — CLOSED BY RULING, note for whoever picks up DF-146k.** DF-146k
  floats `shared borrows` *or* `borrows -> &T` as spellings for a shared-flavor
  place. `borrows -> &T` is now a parse error like any other reference return, so
  `shared borrows` (or an equivalent that never names a reference) is the only
  live candidate. Nothing to do unless 146k is taken up.
- **DF-163f — DECIDED (user, Aug 7) and IMPLEMENTED with DF-163d: a reference
  whose IMMEDIATE parent is a cast to `UnsafePointer<T>`/`UnsafeConstPointer<T>`
  is blessed in ANY expression position** — call argument, local binding,
  accessor tail / return expression, and the chained
  `(&self) as UnsafePointer<TaskGroup> as Int` (the reference's immediate parent
  there is the inner pointer cast, so the chain qualifies). Every OTHER
  non-argument bare `&` is refused per DF-163d.
  **Rationale, as ruled:** the cast transfers lifetime responsibility to the
  unsafe tier; the result is unsafe-TYPED, so design 130's signature effect is
  the fence that matters; and policing the expression POSITION would not fence
  escape anyway. Implementation is an annotation (`ReferenceExpr.to_pointer_cast`)
  set by `_check_cast_expr`, read off the target type AS WRITTEN — an alias for
  a pointer type is not blessed (v1 fence, no in-tree use), and `(&x) as Int` is
  refused like any other bare `&`. Pinned by
  `examples/ref_pointer_cast_blessed.saw` (positive, all four shapes) and
  `examples/errors/ref_cast_to_int_not_blessed.saw` (the discriminator).
  What made the ruling necessary, kept for the record: DF-163d prescribed
  dropping the `expr.mutable and` guard in `typechecker/expressions.py`
  (`_check_reference_expr`), which refuses every reference outside argument
  position. Measured, not predicted: with the guard dropped
  `examples/hello.saw` does not compile — 21 errors, all from the STDLIB
  (`std.net` 195, `std.directory` 72, `std.fixedbuf` 44, `std.spinlock` 115,
  `std.taskgroup` 505/516/570/760). About 45 sites across `sawc/std/`,
  `sawc/rt/` and `examples/` write the shape, e.g.
  `(&self) as UnsafePointer<TaskGroup> as Int`, `(&self.value) as
  UnsafePointer<T>`, `(&sa) as UnsafePointer<Int8>`. It is also the FFI idiom
  LANGUAGE_SPEC and the saw-lang skill both bless ("a stack local + `(&sa) as
  UnsafePointer<...>` for the syscall") and the only way to take the address of
  a local, a static or `self`.
  **The DF-163d premise is false for this shape**: "the 163a reliance audit
  found ZERO in-tree uses of `&` outside a call argument across 1511 files" —
  the audit evidently covered declaration positions and missed the cast
  operand, which is where every in-tree non-argument reference lives. The
  alternative the ruling passed over was giving address-of its own spelling (an
  `addr_of` intrinsic) and porting the ~45 sites onto it — bigger, and it puts
  a new name in the unsafe surface for a shape the cast already expresses.

## Design 161 — the tuple-index and number-scanner lex rules (LANDED, Aug 6)

`designs/161-tuple-index-member-lex.md` closed, including its user-approved
addendum. Two rules on one scanner, in `sawc/lexer.py` and the Saw port
`selfhost/lexer/src/lib.saw` in the same commit:

- **LOOKBACK.** A numeric literal whose immediately-preceding emitted token is
  a member-access `.` is a TUPLE INDEX — a bare decimal integer, no second `.`,
  no base prefix, no width suffix. `t.0.name` lexes, and `t.0.1` is two index
  hops rather than the float `0.1`. One-token lookback is the whole mechanism:
  the Python lexer reads `self.tokens[-1]`, the Saw one reads the last element
  of its token vector, and both pass a `tuple_index` flag into `read_number`.
- **LOOKAHEAD** (the addendum). A `.` continues a float only when a DIGIT
  follows it, so the trailing-dot float is gone and `7.to_string()` works. It
  had failed with "undefined function to_string" because `7.` swallowed the
  member dot.

Nothing in the corpus moved: a probe over all 1460 tracked `.saw` files found
zero trailing-dot floats and zero FLOATs after a DOT, so both sweeps of lexdiff
stayed byte-identical apart from the new tests. The one parser change is a
diagnostic — a trailing-dot `7.` now says ``a float literal needs a digit after
the point (write `7.0`)`` instead of "got NEWLINE". Design 116's
`selfhost/lexer/tests/ranges.saw` asserted the old `7.` float-prefix behavior
and was updated; that part of the 116 brief is superseded.

## Design 160 — remote test worker (LANDED, Aug 6)

`designs/160-remote-test-worker.md` closed. A second machine can take a
core-weighted share of the suite, of `irdet --all`, or run the whole battery,
with NO SSH: the worker runs one fixed daemon under `sandbox-exec`, and only
jobs cross the wire. Five commits: A the daemon + profile + wire vocabulary +
client, B `test_runner --remote` + the two job-side flags, C `irdet --remote`
+ `tools/remote_battery.py`, D the self-test, E docs.

**Deployment, for the user (the Studio).** Four steps, all on the worker
machine, nothing inbound to enable:

```bash
git clone <repo> ~/saw-worker && cd ~/saw-worker
python3 -m venv .venv && ./.venv/bin/pip install llvmlite
./.venv/bin/python tools/test_worker.py --init-token   # prints the secret
sandbox-exec -D WORKER_ROOT="$PWD" -f tools/test_worker.sb \
    ./.venv/bin/python tools/test_worker.py --bind 0.0.0.0:8710
```

Copy the printed token to the laptop at `~/.config/saw-worker/token`. The
daemon prints `sandbox: ACTIVE` when the wrapper took effect and the correct
launch line when it did not. Then, from the laptop:
`test_runner.py --remote studio.local:8710`,
`tools/irdet.py --all --remote studio.local:8710`,
`tools/remote_battery.py --remote studio.local:8710`. The worker's own
checkout only supplies the daemon, the profile and the venv — every job runs
the CLIENT's tree, which arrives with the job. Requirements on the worker:
same OS/arch (arm64 macOS), Xcode command line tools, that venv.

**Validation (localhost worker, Aug 6).** Full suite split 700 local / 614
remote: 1314 verdict records, 1314 unique tests, every one `pass`, ZERO judged
twice, matching the local-only baseline of 1314 green; job directory purged
(only `rt-cache` left). Worker killed mid-shard: client returned notes plus
the unanswered tests in under a second, no hang. Wrong token, dead port, busy
worker: each a note and a local completion. `irdet -n 12 --remote` split 3/9,
0 skipped; with the port closed, all 6 files of a second sample checked
locally with an `unreachable` note. Battery round-tripped GREEN in 2002s —
suite 547.7s, lexdiff 25.7s, astdiff 162.2s, `irdet --all` 1265.4s — job
directory purged afterwards, only `rt-cache` left. (Those timings are against
a load average of 50-83: the 159 agent was building on the same machine, and
the "worker" was that machine too. They say nothing about a real Studio.)
Self-test: `tools/remote_worker_selftest.py`, 8 checks, all green.

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
- **DF-160b — seatbelt takes exactly ONE `-D` parameter here.** A second
  `sandbox_set_param` on the same params object corrupts the set: every
  `(param ...)` reference then fails to resolve with "invalid data type of path
  filter; expected pattern, got boolean", including the one that was set first.
  Reproduced in both orders and with one-used/two-set. The profile therefore
  spends its single parameter on `WORKER_ROOT` and derives the job root with
  `(string-append (param "WORKER_ROOT") "/.worker-jobs")`, which does work.
  Consequence for the user: `--job-root` elsewhere needs a profile edit, and
  the daemon refuses to start rather than discovering it on the first job.
- **DF-160c — `http.client` hands the socket to the response and clears
  `conn.sock`.** With `Connection: close`, `getresponse()` calls
  `self.close()`, so a timeout raised on `conn.sock` afterwards silently does
  nothing and the CONNECT timeout stays armed on every read. A streaming
  client whose whole point is to go quiet between verdicts then dies after
  five seconds. Fixed by holding the socket before `getresponse()`. Worth
  remembering for any other streaming client in this repo.
- **Follow-ups, not blocking.** (a) SOS stays local — QEMU on the worker is
  the opt-in the brief deferred. (b) One job at a time; a second client
  degrades rather than queues, which is right for two machines and would want
  revisiting for three. (c) The worker keeps `.build/rt` between jobs keyed by
  a digest of `sawc/`; nothing else survives a job, so a compiler-touching
  brief pays one runtime build per submission.

## Design 151 — discarding a `Result` is an error (LANDED, Aug 6)

`designs/151-result-discard-error.md` closed. A `Result` no construct consumes
is now a compile error; `let _ = expr` is the explicit discard. This was the
last silent drop in the language: `visit_ExpressionStatement` checked a
statement expression and threw the type away, so `stream.write(data)` as a bare
statement dropped its `Result` with no diagnostic.

- **The five discard sites, one rule.** Saw has no `IfStatement`/
  `MatchStatement` node — the parser wraps a statement-position `if`/`if let`/
  `match`/`try` in an `ExpressionStatement`, so those are ONE site, not four.
  The remaining implicit discards are block tails whose caller drops the type:
  a `Void` function body (`_reconcile_return_type`), a `Void` method body
  (`_check_method`), a loop body (`_check_loop_body` — a loop yields only via
  `break v`), and a `guard let ... else` block. All five call
  `_check_result_discard`. The `Void`-body tail is the one that matters most in
  practice: the parser turns a block's LAST expression statement into its
  `final_expr`, so the common `func f() { g() }` shape lands there, not in
  `visit_ExpressionStatement`.
- **The diagnostic anchors on the producer, not the forwarder.**
  `_result_discard_culprits` descends through `if`/`if let`/`match` to the
  branch tails that actually produce the value, so a statement-position `match`
  reports each arm at its own line instead of pointing at a `match` line with
  nothing wrong on it. A diverging branch (`panic(...)`, type `Never`) drops out
  on its own. A compiler-inserted `ResultOkWrap`/`ResultErrWrap` is skipped —
  the author wrote a non-Result there and the return-type auto-wrap made it one,
  so naming it would describe code nobody wrote.
- **Keyed on the checked type**, resolved through a `type R = Result<...>`
  alias. An erased `Result<T, Box<any Error>>` and a suspending call therefore
  need no special case, and `try!`/`try` need no exemption: they consume, and
  the `T` they yield is ordinary unless it is itself a `Result`.
- **AUDIT: zero genuine bugs, zero deliberate discards, zero deferred sites.**
  Every tree site was checked and the new error fires on NONE of them: the full
  1298-example suite, every std module (a probe importing all 23 importable
  ones, `map.saw`/`set.saw` included — so nothing was deferred for the
  concurrent places agent), `sawc/rt/` (the cached runtime rebuilt clean),
  blade and libs (every one of blade's 19 tests still COMPILES; the one that
  fails does so at run time, and predates this work — DF-151b), and the SOS
  kernel. This is a real result rather than a
  gap in the check: probes confirm it fires on the brief's canonical
  `stream.write(data)`, on a mid-block `File.write`, and on a discard inside a
  closure body. The tree was already clean because designs 92, 123 and 132 swept
  std to return `Result` AND to handle it, and the examples `try!` what they
  call. The rule is now what keeps it that way.
  - One shape needed no new site: a closure whose BODY TAIL is a `Result`,
    passed where `(T) -> Void` is expected, was already a clean type error
    (``argument `body` expects `(Int) -> Void` but got
    `(Int) -> Result<Int, IoError>` ``), not a silent drop.
- **DF-151a — FIXED Aug 6.** Filed as "a `match` arm's payload binding reads 0
  when a LATER local shares its name". The audit found that shape was one of
  EIGHT, and the root cause one layer deeper than filed.
  **ROOT CAUSE — the REWRITE is name-keyed, not just the layout.** The filed
  diagnosis (`_collect_frame_locals` dedups frame fields by bare name) is real
  but secondary: `_rewrite_expr` turns EVERY `Identifier` whose name is in
  `encmap` into a read of that frame field, with no idea which BINDING the
  identifier meant. So any two distinct bindings sharing a name in a driven body
  interfere, in BOTH directions — an inner binding's reads are redirected OUT to
  the outer field (the filed `arm sees: 0`), and an inner binding's WRITES leak
  out into it (a nested `let n = n + 10` left the outer `n` reading 13 after the
  block). Where the two bindings have different types the frame gets one field of
  the wrong type and a LEGAL program is rejected, sometimes at 0:0.
  **FIX — `CoroFrameBuilder._uniquify_bindings`** (`sawc/coro_transform.py`), a
  scope-correct alpha-rename that runs FIRST in `prepare`: every binding in the
  body gets a body-unique name, so a name IS a binding identity for every
  downstream by-name keying and no other pass had to change. An initializer is
  walked BEFORE its own binding enters scope, which is what keeps a design-100/107
  DERIVED shadow (`let data = parse(move data)`, `if let x = x`,
  `for n in n..n + 2`) reading the OLD binding. Only a COLLIDING name is renamed
  (to `__saw_u<N>_<name>` — the lexer-reserved compiler prefix, so it can never
  hit a user name), so a body that reuses no name comes out byte-identical and
  the IR-determinism corpus is undisturbed. Binding kinds covered: `let`/`var`,
  tuple-destructuring leaves, `if let`/`guard let` (name and pattern forms),
  `match` arm bindings (both the classic `bindings` list and design-63
  `pattern` leaves, kept in sync), `for` variables, closure parameters, and
  closure capture lists. Two name channels that an identifier walk alone would
  miss are handled explicitly: a CALL to a closure-typed local carries the name
  in `FunctionCall.name` (design 77 item 4), and a catch block's implicit
  `error` binding is shielded from an outer rename.
  **AUDIT — every shape, measured before and after.** Five silent miscompiles,
  three bogus rejections of correct code:
  | shape (suspending body) | before | after |
  |---|---|---|
  | `match` arm binding + later local, same name (AS FILED) | `arm sees: 0` | `6` |
  | nested non-spanning block, `let n = n + 10` | outer `n` became `13` | `3` |
  | non-spanning `if let n = maybe(n)` | inner read `3` | `30` |
  | non-spanning `guard let n = maybe(n)` | inner read `3` | `30` |
  | derived `for n in n..n + 2` | outer `n` became `5` | `3` |
  | local derived from a PARAM (`let n = n + 10`) | `field \`n\` is defined multiple times in struct \`__Frame_driven\`` | `15` |
  | sibling scopes, same name, different types | `cannot assign \`String\` to field of type \`Int\`` | both branches run |
  | two arms of one `match`, same name, different payload types | `cannot assign \`Int\` to field of type \`Bool\`` at 0:0 | both arms run |
  Same-name arms with the SAME payload type worked by luck before (one arm runs
  per match, so the shared slot happened to hold the right value) and still work.
  NOT affected, and not by accident: a closure param or a `for` var shadowing an
  ENCLOSING local is already a design-100 error, so those never reached a frame.
  **RESTRICTION LIFTED.** Design 104's "a suspension-spanning `if let`/`guard
  let` whose body RE-BINDS the bound name is not supported" existed only because
  the split renamed its binding by walking the scope blindly, which an inner
  binding of the same name would have made unsound. With every binding already
  unique that error cannot fire, and the shape compiles and runs (r5 in
  `examples/coro_bind_id_shadow_regressions.saw`). The TUPLE-pattern rejection is
  untouched and still fires cleanly. LANGUAGE_SPEC.md and the saw-lang skill
  updated on both counts.
  **TESTS — `examples/coro_bind_id_*.saw`, 11 of them**, one per shape, each
  asserting VALUES with the same shape in sync code beside it as a control.
  Ten of the eleven FAIL on the pre-fix compiler; the eleventh
  (`coro_bind_id_shadow_regressions`) is the regression floor and passes on both.
  `coro_bind_id_scopes_stress` is the interaction test — a `while` body's `v`
  against a frame-resident `v` after the loop with a `match` arm in between, plus
  a catch block's implicit `error` still resolving to the CAUGHT error while an
  outer local of that name is renamed (the walk shields the catch boundary).
  `examples/result_discard_legal.saw`'s `got` local (named to dodge this bug) can
  go back to `v` whenever someone touches that file.
  **GATES** (all via the venv interpreter, on `d6b8ae1`): suite 1328 green, zero
  xfails; `lexdiff` 0 mismatches over 1470 files (tokens + docs); `astdiff` OK;
  `irdet --all` OK — 873 examples compiled twice under differing
  `PYTHONHASHSEED`, byte-identical (the rename is confined to colliding names, so
  the corpus's IR is untouched); `blade_bootstrap` ok through stage2 (19 tests,
  libs/toml 4, libs/semver 4); `sos_runner` 3/3; `gmgate` 12 programs x 10 runs,
  0 failing.
- **DF-151b — FIXED Aug 6 by design 159** (see that section above for the
  bisect, the audit table and the gate results; the root cause was
  `Namespace.copy_tier`'s missing STRUCT structural join, which left an
  undeclared all-trivial/ImplicitCopy struct reporting tier 'free' while its
  per-binding drop was still registered). Both victims are now 100/100 clean
  under Guard Malloc and native. The investigation record follows as filed.
  **It is ONE compiler bug, it has nothing to do with machine load, and
  it is far broader than the two victims: A STRUCT COPY DOES NOT RETAIN ITS
  REFCOUNTED FIELDS, BUT EVERY BINDING'S SCOPE-EXIT DROP RELEASES THEM.** One
  allocation, N releases. The surplus releases write into an already-freed
  malloc block; libmalloc trips over the damage at whatever unrelated
  allocation comes next, which is why the signal and the crash site look
  random. See the evidence, the rates and the reproduction below.
  - **The IR, from a 10-line repro** (`.build/scratch/probe_structcopy.saw`:
    `struct P { name: String }`, a heap `name` from interpolation, `let b = a`,
    `let c = b`, three uses). `let b = a` compiles to a bare
    `load %P` / `store %P` — **no `String_copy` anywhere** — and then `drop.c`,
    `drop.b`, `drop.a` each call `String_deinit` on the same `interp_buf`
    pointer. `examples/closure_copyable_struct_copied` is the same defect on a
    closure field: the env is allocated with `store i64 1, i64* %env_refcount`,
    `let h2 = h` and `let h3 = h2` copy the `{fn, env, dtor}` triple without
    touching the count, and the epilogue runs three `atomicrmw sub` on it —
    the first frees the env, the other two decrement freed memory to -1 and -2.
  - **A literal-valued field hides it.** String literals are immortal (rc -1),
    so `String_deinit` on them is a no-op and the same probe is clean. Every
    string in a repro must come from interpolation or the test is vacuous —
    this cost the investigation two false negatives.
  - **Both spellings of "copy" are affected**: local-to-local (`let b = a`) and
    a BY-VALUE ARGUMENT (`consume(a)` twice, where the callee's epilogue drops
    the parameter's fields — `blade/src/lock.saw`'s
    `manifest_deps_hash(m: Manifest)` is exactly this, called twice on the same
    `m`). Field-wise construction is NOT affected — a struct LITERAL does emit
    the per-field copy (`Arc$1$Res_copy` in the closure env). Also clean, and
    therefore not the surface: `StringBuilder.build`, `Vector<String>` +
    `sort`, `for e in v.iter()`, and enum String-payload binding out of a
    `match`.
  - **What the crash actually is.** macOS crash reports (readable at
    `~/Library/Logs/DiagnosticReports/*.ips`, and far more useful than a core —
    lldb cannot attach from the agent sandbox, `attach failed ((os/kern)
    invalid address)`) name it outright:
    `libsystem_malloc.dylib: "BUG IN CLIENT OF LIBMALLOC: memory corruption of
    free block"`, `EXC_BREAKPOINT/SIGTRAP` in
    `_xzm_xzone_malloc_freelist_outlined`. The SIGBUS face is the same damage
    read a moment later: `EXC_BAD_ACCESS`/`KERN_PROTECTION_FAILURE` inside
    `mfm_alloc`, reached from `String_split` / `Vector.reserve`. malloc is
    always the VICTIM, never the culprit; the Saw frame under it is just
    whoever allocated next.
  - **Guard Malloc turns it deterministic** — `DYLD_INSERT_LIBRARIES=
    /usr/lib/libgmalloc.dylib` unmaps a block on free, so the surplus release
    faults AT the offending instruction. 100% reproduction on every affected
    program, with the fault landing in the function epilogue (attributed to the
    last source line at a large symbol offset). This is the tool the fix brief
    should gate on; a native run cannot see a latent double-release at all
    (`probe_structcopy` is 0/100 native and 10/10 under gmalloc).
  Historical note: the entry below was filed believing this was environmental.
  It is not. Two confirmed victims, measured by running a FIXED, already-built
  binary in a loop, which is what ruled out every compiler pass at the time:
  - `blade/tests/lock_drift` — **11 crashes / 30 runs** built with this
    brief's compiler, **6 / 30** built from the stashed baseline. The
    bootstrap gate failed on the baseline compiler too
    (`BOOTSTRAP FAILED: stage1 test`), and the failing stage MOVES between
    runs (stage1 one run, stage2 the next), which is the flake signature.
  - `examples/closure_copyable_struct_copied` — **6 crashes / 40 runs**,
    SIGTRAP, no output at all. It passed in one full-suite run and failed in
    the next against the same compiler and the same source.
  - Why it stayed hidden: at a ~15-35% per-run crash rate, a single suite run
    clears easily and a 4-stage bootstrap clears about a sixth of the time.
    The suite has been reported green on runs that were simply lucky. **Do
    not bisect the compiler first** — reproduce on a built artifact.
  ```
  ./.venv/bin/python tools/blade_bootstrap.py          # fails ~5 runs in 6
  # or, on built artifacts:
  #   blade/.build/host/tests/lock_drift               # ~1 crash in 3
  #   .build/closure_copyable_struct_copied            # ~1 crash in 7
  ```
  **Measured Aug 6 on a deliberately quiet machine, one thing at a time**
  (`.build/scratch/run_batch.sh`, fixed pre-built binaries, `ulimit -c
  unlimited`; per-run PID/signal/seconds/loadavg in
  `.build/scratch/logs/*.tsv`, crashed runs listed in `*.crashes.txt`):

  | phase | loadavg | binary | crashes/100 | signal | secs in |
  |-------|---------|--------|-------------|--------|---------|
  | quiet | 0.91 | `closure_copyable_struct_copied` | **21** | SIGTRAP ×21 | 0.001-0.002 |
  | quiet | 0.83 | `blade lock_drift` | **14** | SIGTRAP ×14 | 0.001-0.002 |
  | saturated (`irdet --all` beside it) | 8.28 | `closure_copyable_struct_copied` | **15** | SIGTRAP ×15 | 0.003-0.007 |
  | saturated (`irdet --all` beside it) | 8.28 | `blade lock_drift` | **11** | SIGTRAP ×11 | 0.003-0.007 |

  **Load is not a factor.** 21% and 14% at loadavg <1 against 15% and 11% at
  loadavg 8+ — if anything slightly lower under load, which is noise. The
  saturation theory that DF-151b and DF-156b were both filed under is DEAD:
  these crash on an idle machine at the same rate. Earlier smaller batches the
  same afternoon also produced the SIGBUS face on `lock_drift`, so the signal
  spread is not phase-of-the-moon either — it is which allocation trips over
  the damage first.

  Under Guard Malloc, every one of these is 100%: `closure_copyable_struct_
  copied` 30/30, `lock_drift` 10/10, and the minimal probes
  `probe_closurecopy` (struct with a closure field, copied) 10/10,
  `probe_structcopy` (struct with a heap String field, copied) 10/10,
  `probe_argpass` (same struct passed by value twice) 10/10.

  **Design 73's residual gap is NOT closed.** `examples/closure_copyable_
  struct_copied` exists to prove that copying a struct holding a closure
  retains the env exactly once, and it passes ~79% of the time — but it checks
  `Arc.strong_count()`, which reads correctly while the env is merely
  double-released rather than wrong. The test has been passing for the wrong
  reason since design 73. Whatever fixes this should assert on the ENV
  refcount, and the brief's gate should run the affected examples under
  `libgmalloc`, because that is the only configuration in which a latent
  double-release is visible at all.
- **DF-151c — FIXED Aug 6.** Filed as "a suspending `match` arm binding a
  REFCOUNTED payload is an ICE (`Type of #1 arg mismatch: i8* != i8`)". The filed
  diagnosis was exactly right; the filed SCOPE was one site out of six. The
  hazard belongs to the DESTINATION, not to coroutines — the frame store was
  merely the one shape somebody happened to write.
  **ROOT CAUSE.** Retain and drop glue are driven off the type they are HANDED,
  so that type must describe the value IN HAND. Every transfer site has only the
  DESTINATION's type conveniently available, and at each of them the destination
  may be opt-encoded (`T?`) while the value is still the bare payload `T` — the
  optional wrap happens AFTER the copy. Driving the glue with `T?` walks Optional
  layout over a value that has no tag word: it reads a payload out of the payload
  itself and hands `T.copy`/`T.deinit` garbage.
  **THE AUDIT FOUND FIVE MORE, EVERY ONE OF THEM REACHABLE FROM PLAIN SYNC
  SOURCE.** None of these needs a coroutine, a `match`, or a suspension:
  ```saw
  var o: String? = None
  o = s                    // statements.py:405 — local assignment
  h.o = s                  // statements.py:482 — field (the site as filed)
  r = v                    // statements.py:665 — `&var` referent / `self = v`
  Holder(o: s)             // structs.py:108    — struct-literal field
  x?.y = s                 // optionals.py:520  — chained assignment
  let _: String? = s       // statements.py:150 — discard, BOTH copy and drop
  ```
  The discard is the interesting one: it has no destination SLOT, so nothing
  wraps, and the annotation misled the retain AND the immediately-following drop
  registration — the same defect mirrored onto the release side.
  `structs.py` already carried a PARTIAL patch of this exact bug, keyed on design
  124's `frame_owning_read` alone; that is the special case that missed the rule.
  **THE FIX — one named rule, `sawc/codegen/resources.py:_transfer_type_for`.**
  It answers "what type actually describes this value at a transfer into that
  destination", by unwrapping `T?` to `T` in exactly the case the wrap will
  fire. Keyed on the LLVM shape rather than on the source expression for two
  reasons: it is the same test the wrap itself uses, and it holds for the
  synthesized frame stores that carry no `resolved_type` to consult.
  `_generate_copy_for_dest` is the copy-site wrapper over it; the discard path
  calls it directly, because there both the retain and the drop need the answer.
  **NOTHING COULD HAVE MISCOMPILED SILENTLY.** The class is loud everywhere: a
  refcounted payload ICEs, and a trivial one needs no glue at all
  (`_needs_cleanup(Int?)` is false, so the bad type was never walked). These
  shapes were uncompilable, not miswritten — which is exactly why the suite
  stayed green through all six.
  **An `Arc` payload is the same defect** (the filer flagged it as worth
  re-probing): it arrives as `internal compiler error: tuple index out of range`
  instead, because the value handed to the glue is struct-shaped rather than a
  pointer. Fixed by the same change.
  `examples/df151c_optional_dest_copy.saw` covers the filed repro, its sync
  control, all six sites, and three `Arc.strong_count()` balance oracles — the
  field write measured in place (retain on write, release on overwrite), and the
  struct-literal init and the suspending arm measured across a frame that has
  DIED, so `after == alone` is the balance. Every string in it is interpolated
  (design 159's lesson: a literal is immortal and cannot fail).
  **Follow-up DONE Aug 6** (with DF-151d): the example is in the Guard Malloc
  lane (`tools/gmgate.py`), as design 159 did with
  `df151b_implicit_tier_transfers`. The counts prove the retains HAPPEN; only
  Guard Malloc proves no SURPLUS release happens, since an over-release reads
  correct until the freed block is reused. Clean at 10 runs.
- **DF-151d — FIXED Aug 6.** Filed as "a `match` whose SCRUTINEE is a TEMPORARY
  never releases it". The filed diagnosis was exact — the named local is
  registered for cleanup and the temporary is not — and the fix follows the
  filed workaround: make the two spellings differ only in whether the value has
  a name.
  **TWO LOWERINGS, TWO ANSWERS, because they own their scrutinee differently.**
  The CLASSIC enum switch CONSUMES (the arm's bindings take the payload), so a
  temporary is spilled into the storage a named local would have had and run
  through that same consume model. The spill is also what makes the release
  addressable at all: every drop needs a pointer and a temporary has none.
  The GENERAL if-chain (a guard, a tuple, a literal or range arm) BORROWS — every
  binding it hands an arm is an alias — so there the temporary gets a cleanup
  SCOPE spanning the match: dropped once at the merge block, which dominates
  every falling-through arm, and via `_cleanup_all_scopes` on an arm that
  returns. A scope rather than `_register_stmt_temp` (which the filing suggested,
  and which was tried first) because a match is an EXPRESSION and can be a
  function body's TAIL, where `statement_temps` is None and registering one
  silently does nothing — `guarded_let` balanced and `guarded_tail` did not.
  **THE GENERAL LOWERING ALSO HAD A LIVE OVER-RELEASE, on a NAMED local.** It
  read an arm's result raw, so a binding that ESCAPES came out non-retained and
  the scrutinee's drop then freed it: `case A(x) if k > 0 -> x` returned a
  handle to a dead block (`strong_count` on the caller's own Arc read 3 after the
  object was freed and its page reused). Fixed by routing the arm result through
  `_gen_transfer_value`, the DF12 rule the enum switch already had.
  **A THIRD HOLE SURFACED WITH THEM: an arm that CLAIMS NOTHING.** `case _` over
  an owning variant leaked on BOTH spellings and for a NAMED local too — the
  consume model suppresses the scrutinee's own drop on the strength of bindings
  that arm does not have. Such an arm now drops the scrutinee itself and the
  enum's own tag switch picks the payload, which is the only thing that can: the
  catching arm may name a different variant entirely (`match Two.Right(r) { case
  Left(_) -> 1, case _ -> 8 }`).
  **`_is_owned_temporary` gained the aggregate literals.** Every one builds its
  elements through `_gen_transfer_value`, so a `(f(), k)` tuple, an `[s0, s1]`
  array and a `{k: v}` map hold references they took themselves — that makes the
  literal an OWNER, and an unclaimed one leaked exactly as an unclaimed call
  result did (`[mk(a), mk(a)].len()` was one; that path is `calls.py:1408`).
  `examples/df151d_match_temporary_scrutinee.saw` counts live `Res` values behind
  an `Arc`, so the count returns to zero only when the last reference goes AND
  the destructor runs — a released refcount alone does not move it. Twelve
  shapes: the filed repro, both wildcard forms, the named control, return / break
  / diverging arms, a retained and a `move`d-out escaping binding, the general
  lowering's escaping binding, nesting, and the whole thing inside a coroutine
  frame. On the pre-fix compiler its five sync shapes read 1, 2, 2, 3, 4 instead
  of 0. It is in the Guard Malloc lane, together with `df151c_optional_dest_copy`
  (that finding's follow-up, done here) and the DF-151e example — a leak inverts
  to an over-release under a fix that drops one time too many, so the counts and
  that lane police opposite failures of one change.
  **The filing's two open questions, answered.** A temporary STRUCT scrutinee is
  not a thing (a struct has no patterns to match); a temporary TUPLE one leaks
  still, but for an unrelated reason — see DF-151f. `if let f()` was already
  correct.
- **DF-151e — FIXED Aug 6.** Filed as "a fixed array of optionals `[T?; N]`
  cannot be constructed AT ALL". The filed through-line was right and the filed
  LOCATION was one layer too low: the array literal never pushes the element type
  into its elements, but it is the TYPECHECKER that never reads the annotation,
  not codegen that fails to wrap.
  **ONE MISSING STEP, THREE ICEs.** `_check_array_literal` took its element type
  from element 0 and consulted `expected` only for a Vector. So `[None, None]`
  left the literal `inner_type=None` (`_generate_none_literal` fails loud), and
  `[1, 2]` / `[s0, s1]` stored the payload UNWRAPPED — laid out `[T x N]` while
  the storage, the element drop and every read believed `[{i1,T} x N]`. The
  repeat form `[None; 4]` / `[7; 4]` is the same gap in `_check_repeat_literal`.
  **THE FIX.** Read the element type off the EXPECTED array — the job `vec_elem`
  already did for a Vector — and check each element against it through
  `_element_fits`, which routes an optional slot to `_arg_type_ok`. That is the
  same one-level `T -> T?` auto-wrap a call argument and a struct-literal field
  take, so a `None` gets its payload type and a bare `T` records the wrap codegen
  builds `Some(x)` from; the wrap lands AFTER the copy, so the existing
  `_gen_transfer_value` retain is already driven by the payload's type
  (DF-151c's rule, unchanged). `_apply_literal_expected_type` now stamps the
  array expectation on the literal and not only its element type, which is what
  makes nesting compose — `[[Int?; 2]; 2]` reaches the inner literals through the
  same recursion.
  **The filing's prediction about the assignment sites was exactly right.**
  `statements.py`'s two array-element transfer sites carried the DF-151c copy
  rule but had never been reachable, and reaching them showed the WRAP was
  missing there: `b[0] = s` on a `[String?; 2]` stored a bare `i8*` into a
  `{i1, i8*}` slot. That is the one codegen line this needed.
  **Design 139's wrapper-tier rule holds on the new shapes** without any work:
  `[Vector<Int>?; 3]` is ExplicitCopy (a repeat literal is refused by name,
  `let b = a` demands `.copy()`), and a NoCopy payload behind a `?` is refused
  naming NoCopy — the diagnostic reads `` `Handle?` is NoCopy ``, i.e. the
  wrapper's tier IS the payload's.
  Two examples: `df151e_optional_element_array.saw` (both initializer forms at
  Int/String/Arc payloads, mixed presence, nesting, element writes, and Arc
  balance oracles in a sync AND a suspending context; in the Guard Malloc lane)
  and `df151e_optional_element_repeat_error.saw` for the tier refusal.
- **DF-151f — FIXED Aug 7.** Filed as "a TUPLE has no drop glue, so an owning
  element is never destroyed", and that was exactly right: `_needs_cleanup` had
  arms for a struct's fields, an enum's active payload, an `Optional`'s payload
  and a `[T; N]`'s elements, and none for a tuple, so `let t = (res(), k)`
  registered nothing and `_emit_drop_at` fell through to the struct-field path,
  which finds no fields on a structural type.
  **FOUR WALKERS, NOT TWO.** Drop, retain, release and copy each needed the arm.
  Elements drop in REVERSE position order (the LIFO rule fields already follow);
  a tuple has no `deinit` of its own and can never have one, so the glue is
  purely structural and every container that already had glue composes for free
  — a tuple struct FIELD, a tuple enum PAYLOAD, a `Vector` element, a
  `[(Arc, Int); 2]` array, an `Optional` payload and a coroutine frame slot all
  reach it through their own walkers. `_tuple_elements` substitutes the
  monomorphization context, so a `(T, Int)` local in a generic body is judged on
  the instantiation's element types rather than on an opaque `T`.
  **THE FILING'S "AUDIT THE COPY SIDE" WAS THE LOAD-BEARING HALF.** `copy_tier`
  was already correct (the typechecker has had the tuple join since design 139);
  CODEGEN was not. `_generate_copy`, `_emit_copy_value` and the three fallbacks
  that decide a read-out-of-storage retain (`_transfer_needs_copy`'s
  container-slot arm, `_slot_read_needs_copy`, `_frame_read_needs_copy`) all
  listed STRUCT/ENUM/OPTIONAL and not TUPLE. Bitwise copy plus no drop is a leak;
  bitwise copy plus a real drop is a DOUBLE FREE — landing the drop arm alone
  crashed `let u = t` and every coroutine-frame tuple read. There is no
  `_get_cleanup_behavior` answer for a tuple to catch it earlier (a structural
  type has no name to look a conformance up under), so those kind lists are the
  whole decision.
  **AUDIT of the other composite arms, as the brief asked:** a fixed array of
  owning elements had its glue from design 33 and balanced BEFORE this change —
  `owning_array` in the example is the control that keeps it that way, and
  `array_of_tuples` is the composition that did not work. Optionals, enums,
  closures and erased boxes were all already covered. TUPLE was the only missing
  kind, and it was missing in every walker at once.
  One example, `df151f_tuple_drop_glue.saw`: eighteen shapes (named local, field
  names, nesting, tuple-in-struct, tuple-in-enum, destructuring, the DF-151d
  temporary scrutinee, whole-tuple copy, by-value argument, return, element
  read, `Vector` element, fixed array, optional payload, reassignment, and two
  across a suspension) against an Arc-behind-deinit counter; in the Guard Malloc
  lane, where the over-release this fix could invert to is the failure nothing
  else can see.
- **DF-151h — FIXED Aug 7 (codegen; found while fixing DF-151f).**
  **An assignment RHS did not retain what it read out of storage.** DF-139a
  retired the question "is the initializer a bare Identifier?" at the `let`
  path — it retained a whole-binding read and bitwise-aliased every PROJECTION
  beside it. The ASSIGNMENT path, one statement kind over, still asked exactly
  that question:
  ```saw
  var a = res(200)
  a = h.r          // `h` keeps owning it; the alias was not retained
  ```
  so both halves released one reference: one allocation, two frees. Latent
  rather than loud — the surplus release lands in a block libmalloc has freed
  but not unmapped, so `strong_count` read one low and nothing faulted until an
  unrelated allocation tripped over the damage (the DF-151b failure mode).
  All five assignment targets now ask the shared transfer oracle
  (`_transfer_site_needs_copy`, renamed from `_let_init_needs_copy` since it is
  no longer a `let`-only question): a local, a struct field, a fixed-array
  element, a nested-array element, and a design-110 `&var` referent replacement
  — a projection RHS reaches every one. The design-124 frame-read branch is
  checked FIRST and keeps its own type source, so its copy stays driven by the
  VALUE's type rather than the destination's.
  Surfaced because DF-151f's drop glue turned it into a hard crash on
  `a = t.0`: the tuple's missing drop had been masking the missing retain.
  Example `df151h_assign_rhs_retain.saw` (six shapes + the Identifier control),
  in the Guard Malloc lane.
- **DF-151i — FIXED Aug 7.** Filed as "`.copy()` does not exist on a tuple, and
  the transfer refusal recommends it anyway", and the filing was right in every
  particular — including its prediction of the fix. Design 139 names three
  wrappers that carry the tier of what they wrap (`Optional<T>`, `[T; N]`, the
  tuple) and the tuple was the one that never got the tier's operation, so the
  two diagnostics contradicted each other: `let u = t` refused an ExplicitCopy
  tuple with "use .copy() for an explicit deep copy", and `t.copy()` refused the
  same tuple as "not Copy", while `copy_tier` reported it as 'explicit' —
  precisely the tier the second message claimed to require. Following the hint
  led into the refusal, so an ExplicitCopy tuple was MOVE-ONLY in practice: a
  `move` retires the binding, so a program needing the original AND a duplicate
  had no spelling at all.
  **ONE TYPECHECKER ARM, exactly as filed.** `_check_copy_call` gains a TUPLE
  arm beside its OPTIONAL one; codegen was already ready, so nothing about the
  copy ITSELF had to be built. The one codegen line is a DISPATCH arm, not
  machinery: the `.copy()` interception in `calls.py` keys on the receiver's
  kind, and a tuple has no `struct_name` for the copy-method mangling below it,
  so without the arm the call fell through to the bitwise "auto-Copy" return —
  which would have aliased every owned element while DF-151f's drop glue
  released it twice. Both halves route to `_emit_tuple_deep_copy`, so each
  element copies at ITS OWN tier (a `String`/`Arc` retains, a `Vector<Int>`
  duplicates its buffer, a trivial one is bitwise, a nested tuple recurses).
  **GATED LIKE THE OPTIONAL, NOT LIKE THE ARRAY**, per the filing:
  `copy_tier != 'nocopy'`. The array arm asks `type_satisfies_copy_bound`, which
  is the stricter predicate, and the difference is visible — a `(T, Int)` in a
  generic body keeps its `.copy()` and settles at the instantiation, exactly as
  `T?.copy()` already did. A `(Res, Int)` with a NoCopy element stays refused,
  naming the offending element by POSITION and TYPE (``element 0 of type `Res`
  is NoCopy``) rather than only the tuple, since the wide printed tuple type is
  not the thing the author has to change; the hint names `move` and the
  destructuring that takes the result apart, which was verified to compile.
  Three examples. `df151i_tuple_copy.saw` (deep-copy INDEPENDENCE, element
  retains counted against an `Arc`, String/Arc/mixed tiers, nesting,
  destructuring, named tuples, an Optional-of-tuple, a generic tuple, a
  container read, and a copy across a suspension — in the Guard Malloc lane,
  since an aliasing copy reads correct and exits 0); plus the two error tests
  that pin the agreement the finding was about —
  `df151i_tuple_copy_nocopy_error.saw` for the move-only refusal and
  `df151i_tuple_transfer_hint_agrees.saw` for the recommendation itself. The
  last pair is deliberate: silencing either one without the other re-opens the
  contradiction.
  Two findings came OUT of this unit — DF-151j (tuple-element mutation is a
  silent no-op) and DF-151k (`type_satisfies_copy_bound` has no wrapper arms).
- **DF-151j — FIXED (Aug 7, three units).** **A tuple index is now a PLACE on
  the write side, uniform with a struct field.** Filed as "a `&var self` method
  on a tuple element mutates a copy"; the audit the finding asked for confirmed
  the hole was the whole write side, not one receiver path.
  Three spellings of one write gave three different answers, and the one that
  compiled was the one that lied: `t.0 = fresh` and `t.0 += 1` were refused by
  the PARSER (a tuple index was not in the assignable-target list), `pair.x = v`
  died in the typechecker on "cannot access field on non-struct type", and
  `t.0.push(99)` / `t.0.n = 42` compiled to a write into a temporary that died
  at the end of the statement. Design 161 had made the projection READ
  correctly, which is what left the asymmetry visible.
  - **Unit A (540c815) — the address arm.** `_get_lvalue_pointer` and the
    `is_mutable_self` receiver chain in `_generate_method_call` both dispatched
    on node shape with a `MemberAccess` arm and no `TupleIndex` one, so a tuple
    receiver fell to the materialize-a-temporary fallback. A tuple lowers to an
    LLVM literal struct, so an element slot is the same two-index GEP a field
    takes; `_tuple_slot_pointer` composes it through `_get_lvalue_pointer`, so
    `t.0`, `h.pair.0`, `a[i].0` and a coroutine frame's `self.t!.0` all address
    real storage. Named-tuple `pair.x` needed its own arm in
    `_get_member_pointer`: it is a MemberAccess carrying `tuple_field_index`,
    and the `struct_types` lookup there has no entry for an anonymous literal
    struct — worse, its string-comparison fallback could match a user struct of
    identical layout and GEP by ITS field order. Also `_atomic_cell_pointer`
    and `_is_chain_lvalue`.
  - **Unit B (5e54df2) — assignment.** Parser admits the target; the
    typechecker grew a `TupleIndex` arm plus a tuple-base branch on the
    MemberAccess arm for the named spelling, both routed through one
    `_check_tuple_element_assign` (transfer checkpoint against the ELEMENT's
    type, so an ExplicitCopy/NoCopy RHS must `move`/`.copy()`); codegen's
    `_store_into_tuple_slot` mirrors the field path step for step, so the
    overwritten element's drop glue runs BEFORE the store and it deinits
    exactly once.
  - **Unit C (c597d80) — `&var t.0`.** `_is_lvalue` gained the node and
    `_generate_reference_expr` lends the element GEP instead of spilling a copy.
  **Mutability and exclusivity both landed on the STRUCT-FIELD answer, which was
  the decision this brief actually had to make.** Mutability is the root's: the
  immutable-root walk now hops a tuple index, so `let t = (v, 7)` rejects every
  shape above with the message `let h` then `h.v.push(x)` already gave. That
  walk also replaced the compound-assign path's ad-hoc "is the base an
  Identifier" test, which any hop at all had defeated — so `p.inner.x += 1` on a
  `let` root is checked now too, and agrees with `p.inner.x = v`.
  Exclusivity is PATH-precise, charged at the ELEMENT and not the tuple root:
  `f(&var t.0, &t.1)` compiles, `f(&var t.0, &t.0)` is the violation naming
  `t.0`. No code implements that — `_build_access_path` already recorded a
  `('tuple', i)` projection and `_paths_overlap` already told two indices apart;
  nothing could reach it because the operand was rejected as a non-lvalue first.
  Root-charging is the PLACE rule (design 141 charges `&v[i]` to `v` wholesale
  because a dynamic index cannot be told apart); a tuple index is a static
  projection like a field name, so it takes the field rule. The two shapes ARE
  the same shape, and consistency decided it.
  Five examples. `df151j_tuple_element_mutate.saw` (the filed repro verbatim,
  the named spelling, nesting, a user `&var self` method, a tuple in a struct
  field, one rooted at `self`, one in a fixed array, one across a suspend, and
  destructuring unchanged); `df151j_tuple_element_write.saw` (whole-element
  replacement with the live count at 1 while the tuple is in scope, a heap
  buffer replaced, field and compound writes through an element, the named and
  nested spellings, an optional element, an ImplicitCopy RHS retained, across a
  suspend — in the gmgate lane, since the element drop is new code on a live
  slot and running it twice reads correct until the freed block is reused);
  `df151j_tuple_element_ref.saw` (both disjoint pairs, an owning element, a
  forwarded re-borrow, a reference held across a suspend); and the three error
  tests `errors/df151j_tuple_let_root.saw`,
  `errors/df151j_tuple_let_root_assign.saw` and
  `errors/df151j_tuple_element_exclusivity.saw`.
  The `df151i_tuple_copy.saw` comment that pointed here is updated.
  Two findings came out of the unit: DF-151l (fixed here) and DF-151m (filed).
- **DF-151l — FIXED (Aug 7, 03d33fb; found while testing DF-151j).** **A tuple
  LITERAL ignored its expected type, so an annotated optional element ICEd both
  ways.**
  ```saw
  var t: (Int?, Int) = (None, 0)   // ICE: None literal has no type information
  var t: (Int?, Int) = (1, 0)      // ICE: Can't index at [0] in i64 — stored
                                   // UNWRAPPED, laid out {i64,i64} while the
                                   // storage and every read believed
                                   // {{i1,i64}, i64}
  ```
  Independent of DF-151j and older: the read-only shape reproduces on its parent
  commit. `_check_tuple_literal` took each element's OWN type and never consulted
  `expected_type`, which is DF-151e's array-literal bug one container over, and
  it took the same fix — check each element against the DECLARED element type
  through `_element_fits`, the helper that records the one-level `T -> T?` wrap
  for codegen to build `Some(x)` from. The expectation reaches the literal
  because `_apply_literal_expected_type` now stamps the tuple type on it, the
  same stamp the array/Vector branch already made, which is also what makes a
  nested `((Int?, Int), Int)` annotation work.
  Two things fall out of checking against the declaration: design 87's
  fixed-width adoption at a tuple element position now lands
  (`let t: (Int8, Int) = (5, 1)`), and a declared NAMED tuple keeps its labels
  when the literal is written positionally. Unannotated literals are untouched.
  `df151l_tuple_literal_expected_type.saw`.
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

Closes **DF-140g** (originally filed on the parked SOS M1 branch; refiled here
at landing, as design 147 did with DF-140e). A freestanding package can now BE
its own runtime: it holds compound global state, declares zero regions that cost
nothing, locks state several cores share, and implements the `__saw_rt_*` seams
under a checked contract. Five commits, full suite green each.

- **DF-149a — FOUND AND FIXED here, before unit (a).** An `Atomic` field mutated
  through a plain `&self` method incremented the callee's COPY and threw it away
  at the return. Silent: no error anywhere, the count just stayed 0
  (`struct Counter { n: Atomic<Int> }`, `bump(&self)`, two calls, `get()` → 0).
  A `&self` receiver is passed BY VALUE, so the atomic RMW addressed a copy of
  the cell. Interior mutability is mutation THROUGH a shared borrow, so a
  receiver carrying an `Atomic` now arrives as the caller's storage —
  `_self_by_pointer_for(struct_name, method)`, a third spelling beside `&var
  self` and design 146's `borrows`, read at BOTH the declaration and the body so
  the two always agree. Call sites read the convention off the emitted signature;
  the vtable thunk asks the impl's own first parameter type. Two gaps closed
  with it: a module static as the receiver of a by-pointer method passes the
  global instead of a spilled temporary, and a monomorphized receiver resolves
  its cell through the template. std had been working around this by writing
  slab's bookkeeping as free functions over a `&SlabHead` parameter rather than
  as methods; `SpinLock` could not have existed without the fix.
- **Unit (a) — `unsafe static var`.** Compound state Atomics cannot express: a
  handle table of multi-word slots, a bitmap paired with its queues, an arena
  region. NOT an Atomic replacement, and the diagnostics say so. Design 130's
  trigger rule extends to NAMING one (the type is usually safe — the unsafety is
  the DECLARATION's), so every touching function is `unsafe` and reviewed. `var`
  and `unsafe` come as a pair, each half alone a clean error, so there is one way
  to declare global mutable state. Prefix position, like `unsafe struct`, for the
  same reason: no parameter list, no effect slot.
  - Two static rules restated honestly. An `unsafe static var` is EXEMPT from
    Sync (Sync is the claim it is already making by hand, and the state this
    exists for is structurally non-Sync exactly where it is most wanted). And
    immortality now asks whether a destructor would have done work — a
    hand-written `deinit`, or a field owning a resource — rather than whether a
    copy POLICY was declared. `NoCopy` says "do not duplicate me", which has
    nothing to say about a value that is never duplicated; that is also what lets
    `static LOCK: SpinLock<T>` be declared with no initializer.
- **Unit (b) — zero statics cost no image bytes.** Two separate causes. Hosted:
  LLVM deliberately keeps a CONSTANT zero global in a readonly section so it can
  be shared, so `global_constant` was exactly what kept zeros out of .bss.
  Freestanding — the profile where it matters most — was ours: design 113's
  per-symbol `.data.<name>` placement suppresses LLVM's zerofill classification,
  so every zero global in a kernel image carried its zeros. Zero globals go to
  `.bss.<name>` now, a name LLVM recognizes as SHT_NOBITS, keeping both the
  `--gc-sections` granularity and the zerofill. **Measured: 330488-byte object
  before, 2804 after**, on a test declaring 320 KiB of zero regions. New
  `EXPECT-OBJECT-MAX-BYTES` test directive — proven by SIZE, so a regression
  fails by the width of the region rather than by a rounding error.
- **Unit (c) — runtime-provider packages. RATIFIED (user, Aug 6: "149c seems
  fine to me") — `runtime = true` is now public Blade manifest contract.**
  `[package] runtime = true` (blade passes `--runtime-provider`) permits the seam
  exports on `--runtime-build`'s terms, links no runtime of ours beside the
  package, and otherwise builds an ordinary package (std available, output
  links). The value-add: an exported seam's signature is CHECKED against
  rt/ABI.md, whose signatures are PARSED OUT OF THE DOCUMENT rather than
  transcribed, so the document is the contract and cannot drift from what is
  enforced. Arity and machine width are compared; pointer-vs-integer is not (the
  C ABI does not distinguish them at this width, and ABI.md itself spells the
  same handle `ptr` in one place and `word` in another). The check runs under
  `--runtime-build` too, so it validates OUR runtime — all 12 objects and ~50
  seams of sawc/rt build clean under it. `make abidoc` checks the other
  direction: the document describes exactly the frozen symbol set.
  **Nothing else in the design depends on this unit** — (a), (b) and (d) stand
  alone if the user vetoes it.
- **Unit (d) — `SpinLock<T>`** (std/spinlock.saw, `import std.spinlock`). NoCopy,
  Sync when `T: Send`, Mutex-shaped `lock`/`try_lock` returning the body's own
  result. The point is where it can LIVE: `Mutex<T>` keeps a pthread_mutex_t in
  an allocated block, so it cannot be a static and a freestanding target has no
  libc to give it one. A `SpinLock` static is declared with NO initializer — zero
  is unlocked over a zeroed payload — so it is const-initializable and, with unit
  (b), free of image bytes. Two constraints ENFORCED: the body is `sync` (a
  suspended task keeps the lock while the executor runs the task waiting for it),
  and the target must have real atomics (rv32i gets a teaching error naming
  `--target-features +a`, never a silent fallback into a C runtime the target
  does not have). A second payoff of the sync rule: `lock` and its body are both
  `sync`, so a task cannot be interrupted holding the lock — two tasks on one
  thread never contend, and contention always means another thread or core.

**The `__saw_reactor` getter did NOT migrate, and should not.** The brief's
payoff list expected the compiler-synthesized getter to become a plain unsafe
static. It was already retired — design 118 stage 3 moved it into Saw as
`__saw_host_reactor()` in std/taskgroup.saw. What remains is
`static __saw_reactor_instance: Atomic<Int>`, a lazy singleton published by
`compare_exchange` from racing threads: single-word state updated independently,
which is precisely the case this design's own settled rule keeps on `Atomic`.
Converting it would delete the atomicity that makes the singleton race-safe.

- **DF-149b — CLOSED (design 156, Aug 6).** Three things landed, in the order
  the brief pinned them. (1) **Two stages.** `test_runner.py` compiles every
  test before it executes any binary, so the rest of the compile sweep now sits
  between a write and its exec instead of microseconds. (2) **Write elsewhere,
  rename in.** A compile writes to a unique `.tmp-<pid>-<n>-<name>` path and
  renames its products into place, so the path a test execs is always a vnode
  the kernel has never judged — this is what kills the stale-signature-cache
  case, and it is what protects a filtered `-f one_test` run, which has no
  settle window to speak of. (3) **Retry once on a SILENT signal death.**
  `run_executable` re-runs a child that was killed by a signal having written
  nothing on either stream, and REPORTS the retry in the test's output line
  and in a `RE-RAN:` summary section — on a pass as well as a failure, because
  a silent retry is exactly how a real crash would hide. The window is narrow
  by construction: every failure the suite asserts on speaks before it dies (a
  Saw panic prints `panic at FILE:LINE:` first), so a panic test is never
  retried. `tools/test_runner_selftest.py` covers all three halves of the rule
  — a retry that recovers, a retry that fails again, and a talkative failure
  that must not be retried. Validated by running the full suite beside
  `irdet --all`, the saturation that reproduced the crash ~1 in 12, with no
  spurious signal death.
  The original report follows.
  A test fails intermittently — roughly 1 run in 12 — under the
  IN-PROCESS path when the machine is saturated (it surfaced while
  `irdet --all` ran beside the suite; `closure_copyable_struct_copied` is
  where it landed, but nothing about it is specific to that test).
  **The child dies of SIGTRAP on exec, having written nothing.** That is the
  macOS/arm64 signature of executing a Mach-O whose pages or ad-hoc signature
  the kernel has not finished settling — the in-process path writes the binary
  and execs it almost immediately, while `--subprocess` spends a second
  spawning a fresh `sawc.py` first and never trips it.
  Ruled out: the compiler and the program. The binary is stable over 300 runs
  compiled by the CLI and over another 300 compiled through
  `compile_saw_in_process` itself, same test and same tree; only the
  write-then-immediately-exec sequence fails.
  Worth fixing because an intermittent red on a refcount test is
  indistinguishable at a glance from a real double-free, which is the bug that
  test exists to catch (design 73) — a false alarm there costs somebody an
  afternoon. A retry-once-on-signal-death in `run_executable` would do it, but
  it must report the retry rather than paper over a genuine crash, which is
  why this is filed rather than patched in passing.
  **Fixed here in passing:** the report itself. `Execution failed:` was
  followed by a blank line, because the failure branch prints only the child's
  stderr and a signal death writes none — the runner now reports the exit
  status and names the signal, which is how the cause above was identified at
  all.

- **DF-156a — LANDED (option (b), pipelined settle lag); wall-clock verdict
  FINAL Aug 6: PASS. Pipelining stays; the reversion was NOT exercised.**
  The stages now OVERLAP. A compiled binary goes into a
  `SettleQueue` in `test_runner.py` and becomes eligible for execution
  `SETTLE_LAG_SECS` (5.0s) after it is renamed into place; the execution
  workers start BEFORE the compile sweep and park on that queue, so the
  kernel-assessment stall runs underneath the compile stream again, which is
  what the strict split had given up. Both DF-149b backstops are unchanged
  underneath it (unique-temp-write-then-rename; the
  retry-once-on-silent-signal-death that REPORTS itself), so the lag is
  margin, not the guarantee. `--settle-lag SECS` tunes it and `0` disables it.
  `--sequential` drains after the compiles but still honours the deadline,
  which is how a filtered `-f two_tests` run gets a settle window it never had
  before.
  **The mechanism is elapsed TIME, not "N further compiles".** The hazard is a
  wall-clock one: the kernel assessing a file it has never run. A compile count
  is only a proxy for that, and one that drifts the wrong way under load — a
  loaded machine compiles slower AND settles slower, yet the count asks for
  less waiting — and it has no answer at either end of a run, since the last
  compiles have no successors and a two-test filtered run has no window at all.
  A deadline works everywhere and costs a short run the lag exactly once.
  **DF-149b holds under its reproduction condition.** Full suite beside a
  running `irdet --all`, loadavg ~50-60: 1298 green with ZERO retries reported
  across the 856 executed binaries. That run also shows the pipeline doing its
  job — compile 779.4s + 4.3s draining, 852 of the 856 binaries already
  executed before compilation finished. When the machine is busy the compile
  stage is the bottleneck and execution hides completely underneath it, leaving
  a drain tail that is just the settle lag on the last few binaries.
  **The wall-clock comparison is now DECIDED, on the quiet machine it was
  deferred to.** Eight full-suite runs, strictly sequential, nothing else on
  the box (`.build/scratch/abba.sh` + `baab.sh`, logs in
  `.build/scratch/logs/`). Two drift-cancelled blocks in complementary orders,
  so each balances both runners at mean sequence position 2.5 and linear drift
  cancels within the block:

  | block | run | runner | loadavg before | wall | result |
  |-------|-----|--------|---------------|------|--------|
  | ABBA | A1 | interleaved | 1.80 | 212.6s | 1314 green |
  | ABBA | B1 | pipelined | 13.27 | 272.1s | 1314 green |
  | ABBA | B2 | pipelined | 17.10 | 281.2s | 1314 green |
  | ABBA | A2 | interleaved | 17.89 | 291.6s | 1314 green |
  | BAAB | B3 | pipelined | 6.18 | 274.9s | 1314 green |
  | BAAB | A3 | interleaved | 23.40 | 298.8s | **1313 + 1 RED** (see below) |
  | BAAB | A4 | interleaved | 12.79 | 301.0s | 1314 green |
  | BAAB | B4 | pipelined | 14.28 | 301.3s | 1314 green |

  Block 1 alone: interleaved 252.1s, pipelined 276.7s — pipelined **+9.7%**.
  Block 2 alone: interleaved 299.9s, pipelined 288.1s — pipelined **-3.9%**.
  All eight: interleaved 276.0s, pipelined 282.4s — pipelined **+2.3%**.
  **Comfortably inside the user's ~15% bar on every reading**, so option (b)
  stands and the pre-authorized single-stage reversion (option (c)) is
  **UNEXERCISED**.
  The two blocks disagree in sign, and the reason is A1: it is the only run
  that started on a genuinely cold machine (loadavg 1.80) and it is 60-90s
  faster than everything after it. Once the box reaches steady state — runs
  2-8, all 272-301s — the runners are indistinguishable, with the pipelined
  mean 282.4s against interleaved 297.1s, i.e. pipelined slightly AHEAD. Note
  the loadavg column is residue from the preceding run, not competing work;
  nothing else ran. Running one block only, in the ABBA order, would have
  handed the cold-start bonus to the interleaved runner and reported a 9.7%
  loss that is mostly an artifact of going first.
  **The interleaved runner went RED during its own defence**, which is the
  other half of the answer. A3 lost `closure_copyable_struct_copied` to
  `killed by signal 5` **having written nothing** — the DF-149b exec-time
  signature, distinct from DF-151b's mid-run crash (which always prints its
  first five lines before dying; see DF-151b for how the two are told apart).
  That is the pre-149b runner reproducing the exact bug the settle machinery
  was built to kill, once in four runs, while the pipelined runner did not do
  it once in four. So the choice is not "equal speed, pick either": the
  interleaved runner is both no faster and measurably less safe.
  **Original finding:** The
  two-stage runner costs wall clock, and the reason is worth writing down
  because it is a property of the machine, not of the runner. **The first exec
  of a freshly written binary costs macOS ~0.4s**; a re-exec of the same file
  costs ~0.007s. That is the kernel assessing a file it has never run —
  our binaries carry `com.apple.provenance` — and it is the same mechanism
  DF-149b's SIGTRAP came out of. It barely parallelises. Measured over the
  suite's 856 executed binaries: width 10 -> 375s, width 20 -> 272s, width
  40 -> 219s. Nothing pays it early: reading the whole file, `xattr -c` and
  `codesign -v` before the exec all leave it exactly where it was.
  The old interleaved runner **hid all of it** — a worker blocked in kernel
  assessment burns no CPU, so the other nine workers' compiles filled the
  cores. Splitting the phases exposes it as a second serial stretch:
  compile ~420s THEN execute, where before the whole run was compile-bound at
  ~400s. Phase 2 therefore runs at 4x the worker count (~219s here), which
  recovers about 40% of the loss; the rest is structural.
  **The options as put to the user were:** (a) keep strict two stages and
  accept it; (b) pipeline them, holding each binary back so the settle window
  DF-149b needs survives the restored overlap; (c) drop back to one stage and
  rest on the rename + retry backstops alone. The user chose (b) on Aug 6
  ("re-adds the parallelism while still allowing the binaries to settle"),
  pre-authorizing (c) as a fallback if (b) could not come within ~15% of the
  interleaved baseline back-to-back under comparable load.

- **DF-156b — FIXED Aug 6 by design 159, as DF-151b.** `lock_drift` is
  0/100 under Guard Malloc and 0/100 native on the fixed compiler, and the
  bootstrap that failed about five runs in six passes. The original answer,
  which located the cause, follows.
  **ANSWERED Aug 6: it is DF-151b, and it was never about
  saturation.** The deliberate reproduction this entry asked for was run.
  `lock_drift` crashes **14 times per 100** on an IDLE machine (loadavg 0.83)
  and **11 per 100** under `irdet --all` (loadavg 8.28) — the same rate, so
  `blade test` needs no backstop and BLADE's runner is not the surface. The
  cause is the missing struct-copy retain in DF-151b above, reached here
  through `manifest_deps_hash(m: Manifest)`, which is called twice on the same
  by-value `m` while its own epilogue `String_deinit`s that `m`'s three String
  fields. Under `libgmalloc` it is 10/10.
  **The "nine seconds in" reading was wrong, and the arithmetic is worth
  keeping**: `blade test` reports COMPILE + RUN as one duration
  (`tester.saw run_one`), and the compile is nearly all of it. The binary
  itself runs in about 2 ms and dies in about 2 ms. So the SIGBUS was never
  nine seconds into execution, and nothing about it argued against an
  exec-adjacent cause the way this entry claimed. The original report follows.
  During the DF-156a gate battery (loadavg ~50-60, the compiler suite and
  `irdet --all` both running), `blade_bootstrap` failed its stage1 sweep:
  `.build/host/tests/lock_drift` died of `Bus error: 10` roughly 9s in, with
  the other 18 of 19 tests passing around it. It did NOT reproduce — the same
  bootstrap on the same tree at loadavg ~3 passed 19/19, and the design-156
  agent's own run earlier the same day was green. Filed rather than chased
  because the surface is BLADE's test runner, not `test_runner.py`: `blade
  test` builds a binary and runs it directly, carrying neither DF-149b backstop
  the Python runner now has (no write-then-rename, no reported retry on a
  silent signal death). Whether this is that same family or a genuine fault is
  undetermined, and the evidence points away from the easy answer: SIGBUS NINE
  SECONDS into a test that does real git work is not DF-149b's exec-time
  signature, which is what a fresh-image assessment failure looks like. Worth
  one deliberate reproduction attempt under load before deciding which it is.

**Not in v1:** a non-trivially-destructible static (statics stay deinit-free);
relaxed/acquire-release orderings on `Atomic` or `SpinLock` (everything is
seq_cst); a `SpinLockIrq` for the same-core ISR case, which the brief assigns to
sos-side composition when M2-era interrupt work lands.

## Design 135 — `--no-hidden-alloc` (LANDED, Aug 6)

Restores the no-hidden-allocations claim to guarantee form; closes the design
125 softening (P3, above). Four units, full suite green each.

- **Unit A — the audit.** Every allocation `sawc` emits, classified against the
  named-in-source line; the table is in LANGUAGE_SPEC "No hidden allocations".
  Hidden: escaping-closure environment, string-interpolation buffer, the
  `to_string()` a one-argument `print` of a user `Printable` synthesizes. Named:
  spawn/TaskGroup machinery (including a spawned closure's env — starting a task
  is the named allocation), the erased-error box (the `Box` is in the WRITTEN
  signature), `Box.make`, collection literals, an ImplicitCopy transfer, an
  explicit `to_string()`. Verified non-allocating: `&any Trait` erasure (static
  vtable), Optional/Result auto-wrap, place windows, loop desugaring, literals
  and statics (immortal, rc `-1`), the design-137 format-argument path, and
  runtime-check panic messages.
  - **One defect found and fixed.** `_emit_format` — a builtin's
    `format(into:)` — rendered through `_emit_to_string`: a heap String per call,
    appended and never released. An allocation AND a leak inside design 137's
    alloc-free path, reached by the natural `self.n.format(into: &var into)`
    spelling in a user `format` body, which fed the fixed STACK builder
    `print("{}", tag)` hands it from the heap. Every case now reaches a
    `StringBuilder.append` overload; Float renders into a frame-resident
    IMMORTAL String (`_stack_string`, rc `-1`). Test
    `format_into_builtin_alloc_free` proves it under
    `__saw_rt_alloc_deny_after(0)` and fails on the old lowering.
- **Unit B — the flag.** `--no-hidden-alloc`, per invocation, diagnostics only
  (no codegen path changes). The three hidden sites become compile errors naming
  the alloc-free spelling. Interpolation is banned UNIFORMLY — no carve-out for
  `panic`/`assert` message arguments (user decision; the allocator being out is
  when a panic matters most). The escaping-closure check follows codegen's own
  condition, so a capture-less escaping closure and any non-escaping one stay
  legal. Gate judges user source on the first pass: std's bodies are already
  alloc-free (the audit found no interpolation anywhere under `sawc/std/` or in
  `builtin.saw`) and coroutine-transform output is compiler-authored.
- **Unit C — SOS dogfood.** The sos gate compiles every kernel source with the
  flag, permanently. The kernel was already CLEAN (137's dogfood); non-vacuity
  checked by confirming the exact gate flag set rejects `print("ram {r}")` and
  `print(r)` in a riscv32 freestanding build.
- **Unit D — docs.** Spec principle #4 and the README bullet are back in
  guarantee form; the audit table, the error text and the orthogonality note
  (`--freestanding` does NOT imply the flag) live in LANGUAGE_SPEC "No hidden
  allocations". Skill + README + Appendix 0 flag list updated.

**Deliberate conservatism worth knowing:** `print(v)` on a `T: Printable` inside
a generic is rejected at the TEMPLATE, where `T` is unknown — an `Int`
instantiation would not have allocated. The format-argument spelling covers
every instantiation, so the check does not wait for one; spec says so.

**Found while running the gate battery, fixed here:** `tools/irdet.py` counted a
compile FAILURE as a skip, so an interpreter without llvmlite skipped the whole
corpus and printed `irdet: OK`. `make irdet-all` calls bare `python3`, which is
exactly that interpreter — the brief's named final gate was reporting success
having verified nothing. It now fails when `checked == 0` and names the venv
invocation; CLAUDE.md's testing note says to run `./.venv/bin/python
tools/irdet.py --all`.

**Explicitly NOT this brief:** a per-function `@no_hidden_alloc` attribute
(named in the brief as a possible later one).

## Design 147 — DF-findings (the soundness batch)

- **DF-140e — FIXED here (unit A). Originally filed on the parked SOS M1
  branch's tracker; refiled in main's tracker as found-and-fixed, same as
  DF-140f/DF-140h/DF-140i before it.** A tail `match` in a Result-returning
  function, with one arm that diverged and one that yielded a bare error value,
  dropped the auto-wrap into `Err` and returned the RAW error:
  `ret %"Oops" %"match_result"` from a function whose result type is
  `{ i32, [8 x i8] }`. Caught only because the LLVM IR verifier rejected the
  size mismatch — a pairing whose sizes happened to agree would have
  miscompiled silently.

  ```saw
  func tail_match(flag: Bool) -> Result<Void, Oops> {
      match source(flag) {
          case Ok(v) -> {
              if v < 0 { return Oops(m: "negative") }
              return
          },
          case Err(e) -> e
      }
  }
  ```

  Cause — and it is NOT the wrap PLACEMENT the brief predicted. Divergence
  reaches `_reconcile_match_arm_types` under two spellings: a `panic(...)` arm,
  which types NEVER (design 49), and an arm whose block has no final expression
  because every path already returned, which `_check_block` reports as a plain
  `None`. The result-type selection loop skipped NEVER but BROKE on `None`,
  adopting it as the match's own type — so the match typed NEVER, NEVER is
  compatible with every return type (`_types_compatible`, the bottom rule), and
  `_reconcile_return_type` therefore saw a compatible body and wrapped nothing.
  The per-arm wrap machinery the brief asked for already existed (it is what
  handles a mixed Ok/Err match); it was never reached because the arm types
  were wrong before it ran. `_reconcile_optional_arms` already used the
  "`None` means no value" convention — the sibling loops simply disagreed
  with it.

  Fix: one predicate, `_arm_yields_no_value(arm_type)` (`None` or NEVER —
  neither reaches the phi at the merge), applied at all three sites that
  previously tested NEVER alone: result-type selection, the compatibility
  loop, and the per-arm Result-wrap loop. Fixing the arm TYPES rather than the
  wrap placement also repairs a shape tail-only wrapping could not have
  reached: a `let`-bound match (`let e = match … { case Ok(v) -> { return },
  case Err(er) -> er }` then `return e`) miscompiled identically, since the
  binding inherited the bogus NEVER.

  Swept siblings, all now correct and all pinned by
  `examples/autowrap_diverging_arm.saw` (22 assertions): the `Result<Void, E>`
  repro, the `Result<Int, E>` variant, an erased `Box<any Error>` return, the
  Optional auto-wrap (`-> Int?` with a `{ return None }` arm), the non-tail
  `let`-bound match, the diverging arm placed SECOND, a `panic(...)` arm
  (design 49, unchanged), a Void arm beside an Err arm (per-arm `Ok(())`/`Err`
  wrap, unchanged), a tail `if` diverging on either side, and the method path
  (which carries its own copy of the return-type reconciliation). A match whose
  arms all yield Void in a value-returning function still reports "body has no
  value" rather than silently returning undef.

- **DF-139a — FIXED here (unit B).** Overwriting a binding released a value a
  live copy still owned, leaving the copy dangling (`let c = h.s` then
  `h.s = build(2)` printed `c=c= h=val-`). Filed as affecting "both the
  field-assignment path and the whole-binding path"; re-probing on current main
  narrowed it — the whole-binding shapes (`var s = build(1); let c = s;
  s = build(2)` and the owning-enum `var d = Dep.Path(...); let e = d;
  d = Dep.Ver(n: 3)`) both behave correctly now. What remained broken was every
  PROJECTION.

  Root cause, and it is neither half the tracker suspected: the marked retain
  reaches codegen fine, and the assignment's release is correct. The `let`
  initializer simply never consults either. `_generate_let_statement` bypasses
  `_gen_transfer_value` — the shared transfer path every OTHER site uses (call
  argument, return, aggregate element) — and hand-rolls its own copy decision:

  ```python
  if var_type and isinstance(stmt.value, Identifier) and not isinstance(stmt.value, MoveExpr):
      value = self._generate_copy(value, var_type)
  ```

  A bare `Identifier` initializer retained; a `MemberAccess`, `TupleIndex` or
  `ArrayIndex` initializer fell straight through to a bitwise alias, even though
  the typechecker had stamped `needs_copy = True` on it at the transfer
  checkpoint (`statements.py:1173`) and `_transfer_needs_copy` would have
  answered True for all three. The IR shows it exactly: `let c = s` emits
  `call i8* @"String_copy"`, `let c = h.s` emits an `extractvalue` and nothing
  else. The source then still owned the storage, so `h.s = build(2)`'s
  `String_deinit` freed the buffer under the live copy — and the copy's own
  scope-exit drop freed it a second time.

  Fix: the initializer asks the shared oracle. ONE carve-out, found by the
  Map/Set refcount-balance oracles going unbalanced: indexing a RAW POINTER
  (`self.buffer[i]` in Vector/Map) is the unsafe domain's manual bookkeeping,
  not a read out of compiler-tracked storage. std takes a bare alias there on
  purpose and decides the retain at the subsequent use — `Vector.get` retains
  when it RETURNS the element, `Vector.swap_out` overwrites the slot and `move`s
  the alias out at exactly one reference. Retaining the read itself left every
  `swap_out` result over-retained. A fixed-array (`[T; N]`) index is not that
  case and retains like a field.

  Regression: `examples/df139a_copy_then_overwrite.saw` — String field, String?
  field, owning enum, whole-binding local, tuple element, fixed-array element
  and a two-hop nested field all print both values correctly, plus a drop-count
  ORACLE (a hand-written ImplicitCopy `copy`/`deinit` pair that prints every
  retain and release: one `copy 1`, two balanced `drop 1`s — before the fix the
  copy line was absent and tag 1 was dropped twice), plus a 500-iteration churn
  loop so a double free meets a reused block.

- **DF-133a — FIXED here (unit C), fork (i) as decided.** The stage-1 ANF hoist
  reordered a suspending child ahead of a side-effecting SYNC sibling to its
  left: `add(noisy(1), slow(3))` printed "slow" then "noisy", contradicting the
  design-120 promise in LANGUAGE_SPEC that a hoisted statement gets the
  evaluation order, intermediate deinit timing and ownership rules of the
  hand-unchained spelling.

  Fix: `_anf_children` now makes two passes. `_uncond_children` collects the
  unconditional child positions in evaluation order (by running
  `_map_uncond_children` with an identity mapper, so the position set can never
  drift from the rewriting walk), the index of the LAST child that will be
  lifted is computed, and every impure child to its left is lifted into its own
  temp ahead of it. Children to the RIGHT need nothing — the residual expression
  still evaluates after every hoist, which is why `add(slow(4), noisy(2))` was
  already correct.

  The purity filter is `_anf_is_pure`, conservative as decided: a literal and a
  plain read of a name / field / tuple element / index are exempt, and anything
  containing a call or a `&var` borrow is lifted. Two deliberate exemptions
  beyond the decided line, both because lifting would CHANGE meaning rather than
  preserve it: a `move v` operand (retiring a binding is compile-time
  bookkeeping with nothing to observe, and lifting would relocate the transfer
  checkpoint it carries) and a closure LITERAL (creating one runs none of its
  body, and binding it to a temp would flip its escaping classification under
  design 16/29 — a closure passed directly to a non-escaping parameter is
  non-escaping, one bound to a `let` is not). `_anf_lift` already stamped each
  temp with its subexpression's own line/column, so transfer checkpoints and
  diagnostics keep source positions with no further work.

  CHURN SCOPE — far narrower than the finding predicted ("changes emitted IR for
  a large slice of the suite"). All 156 coroutine-bearing examples were compiled
  to IR before and after: **byte-identical, zero files changed.** No example in
  the corpus had a side-effecting left sibling of a hoisted suspending child, so
  the fix is a pure no-op on existing code and only the new tests exercise it.
  `make irdet-all` confirms determinism corpus-wide.

  Regressions: `examples/coro_hoist_evaluation_order.saw` — the print-order
  repro, the mirror shape (suspension first, which must stay put), a three-arg
  call with siblings on both sides, the STATE shape (`add(v.pop()!,
  slow(v.len()))` yields 7, where evaluating the suspension first gave 9), an
  operand position and a string interpolation.
  `examples/coro_hoist_move_diagnostic.saw` pins the positions: an ExplicitCopy
  argument and a use-after-move beside a suspending sibling both report at the
  line AND column the author wrote, not at a synthesized temp.

- **DF-134a — FIXED here (unit D). `__saw_rt_reactor_unregister` joins the
  frozen ABI**, as approved. The design-91 token is the ADDRESS of the root
  frame's `__wake` word, and nothing ever de-registered: a park loop that exited
  WITHOUT its event firing (the cancellation path) left the kevent/epoll interest
  armed with that address attached. Harmless while the task owns the fd, because
  closing it drops the registration; a use-after-free vector when the fd OUTLIVES
  the frame (the task returns its stream as its RESULT), since design 134 frees
  the frame box at task completion.

  The seam: `__saw_rt_reactor_unregister(r, fd, write)` — `EV_DELETE` in
  `rt/host_macos/reactor.saw`, `EPOLL_CTL_DEL` in `rt/host_linux/reactor.saw`,
  both authored in Saw with no C shim, both idempotent (an already-fired
  one-shot, a closed fd, and an unarmed fd all give ENOENT/EBADF, which is the
  state the caller wanted, so the result is ignored exactly as the register path
  ignores its own). Added to `runtime_abi.py`'s frozen name set — the compiler
  enforces that list, so an unapproved export is refused; this is the first
  widening since v2. rt/ABI.md carries the section and the v1→v2 table row.

  Reaching it from Saw: the `Reactor` trait gains `unregister`, `SystemReactor`
  implements it over the seam, and `__saw_exec_io_unregister` is the executor
  entry point. Because std.net is its own module (design 82) it cannot call that
  wrapper directly, so the disarm gets the same treatment `io_wait` already has —
  a builtin intrinsic, `io_unwait(fd, dir)`. It is NOT a suspension source (it
  neither parks nor yields, so a `sync` caller may use it), and unlike `io_wait`
  it needs no in-frame/outside-frame split: one lowering to
  `__saw_exec_io_unregister` is correct in both, and the coro transform treats it
  as ordinary body code.

  Two callers, as specified. (1) All six of std.net's park-loop cancellation
  exits — accept, connect, read, read_into, and both write overloads — disarm
  before returning; connect disarms before `tcp_close`, so the fd is still valid.
  (2) A coroutine frame's synthesized `__release` disarms the last `(fd, dir)` the
  frame armed. The frame records the pair in new `__io_fd`/`__io_dir` fields at
  the `io_wait` lowering (and registers FROM those fields, so the arm and the
  later disarm cannot describe different things), and `__release` runs the disarm
  FIRST, ahead of its own field drops — the fd is then still open and still the
  frame's, where disarming after an owning `TcpStream` field closed it could drop
  whatever reused the number. Both fields and the release call are gated on
  `_body_arms_io`, a scan of the untouched body for a literal `io_wait`: a frame
  that merely embeds a suspending callee arms nothing (the callee's own frame
  carries its registration), so every non-IO frame — the whole freestanding
  profile included — is byte-identical and takes on no dependency on the
  executor wrapper.

  Regression: `examples/net_cancel_unregisters_token.saw` runs the reported
  shape — park on an fd, cancel while parked, escape the fd through `join()`,
  then churn the group so fresh frames reuse the released box's memory, and only
  then poke the escaped fd. The churned tasks' results are the assertion (a
  latched wake word shows up as a task resuming with the wrong value), and a
  final round trip on the recovered stream proves the disarm dropped the
  registration and not the fd.

- **DF-137d + DF-140a — FIXED here (unit E). Literal range checks are
  target-width-aware, and `static` initializers are checked at all.** DF-137d was
  filed on main's tracker, DF-140a on the parked SOS M1 branch's; they are the
  same bug seen twice, refiled together.

  Platform `Int`/`UInt` are pointer-width (design 47), so `0x80000000` fits a
  64-bit `Int` and does not fit a 32-bit one. The literal check knew every
  FIXED-width type and skipped the platform pair entirely, so on riscv32 the
  literal wrapped to -2147483648 in silence — and the same source meant a
  different number on the arm64 profile, which is exactly the two-profile
  portability the fixed-width discipline exists to protect. Surfaced when the SOS
  kernel's first formatted log line printed its RAM base as a negative number.

  The blocker was structural: only CODEGEN knew the effective triple. New
  `sawc/target_info.py` derives the platform width from the triple's LLVM data
  layout — the same `p0:` parse `CodeGenerator._pointer_size_bits` uses, kept
  deliberately identical so the front end and back end cannot disagree about what
  `Int` is — and `--target` is threaded into both TypeChecker constructions (the
  entry one and the builtin/std one). One trap worth recording: LLVM registers no
  targets until asked, and the front end runs before `CodeGenerator` does it, so
  `Target.from_triple` raised "no targets are registered" and the fallback
  silently returned 64 — the check appeared to work while doing nothing.
  `platform_int_width` registers targets itself and caches per triple.

  `_int_range_for(kind)` replaces the direct `_FIXED_INT_RANGES` lookups at every
  RANGE-CHECK site (the central design-87 literal propagation and its unary-minus
  arm, `_check_fixed_width_literal`, and the raw-backed-enum `_int_fits_kind`,
  which judged the platform pair at a hardcoded 64). The literal-ADOPTION sites
  are untouched: `Int`/`UInt` are not fixed-width and a bare literal must not
  adopt them.

  DF-140a's second half: `_register_static` type-checked its initializer but never
  routed it through `_apply_literal_expected_type`, so `static B: UInt8 = 256`
  compiled clean while the `let` spelling was already a clean error. Statics now
  take the same treatment as every other typed slot.

  Regressions: `examples/df137d_literal_width_riscv32.saw` (riscv32 via
  COMPILE-FLAGS; the signed RAM-base constant, an out-of-range `UInt`, and the
  `UInt8` static all rejected) and `examples/df137d_literal_width_riscv32_ok.saw`
  (the exact boundary values — `UInt` 0x80000000, Int32 min and max, UInt32 max —
  still compile, so the check rejects only what the target cannot represent). The
  test runner's builtin-namespace cache is keyed on the triple now: what std
  type-checks to is target-dependent since this change. `make sos-test` passes,
  which is the real riscv32 build.

- **DF-140b — FIXED here (unit F). An import symbol list wraps across lines.**
  `import kcore.{\n console, pmp_reset,\n}` was `Parse error: Expected symbol
  name in import`. Design 129 left `{}` newline-significant because a block or a
  closure is a statement container; an import list is not one — it is a delimited
  list exactly like an argument list. The allowance is LOCAL to the import braces
  (three `skip_newlines()` calls in the one parse loop), so `{}` everywhere else
  keeps design 129's rule; a trailing comma already worked and now has newlines
  to go with it. Regression: `examples/df140b_import_wrap.saw` wraps four import
  lists (including a leading-comma spelling) and pins in the same file that a
  closure body's statements still end at end-of-line. Spec's line-break section
  and the saw-lang skill both carry the exception.

- **DF-140c — FIXED here (unit F). A module-qualified type resolves in TYPE
  position.** Root cause is narrower than the finding could see: `_resolve_type`
  recursed into every composite it knew — optionals, tuples, enum and function
  type args — and had NO `REFERENCE` branch. So `qual.Section` by value and as a
  local annotation always worked, and only `&qual.Section` / `&var qual.Section`
  kept the qualified spelling as an unresolved nominal name. The parameter then
  matched nothing, which is why the three reported errors were all downstream:
  the method lookup failed, a `guard let` over an unresolvable method reports the
  BINDING as undefined (`undefined variable raw`), and a call site was told
  `&qual.Section` and `&Section` were different types. One branch fixes it.

  The diagnostic half is fixed separately, since resolution succeeding does not
  help the case where the name is genuinely wrong. A dotted spelling is
  unambiguous — no generic parameter, `Self` or forward reference can survive
  resolution still carrying a dot — so a parameter type that does is now reported
  at the SIGNATURE naming the qualified name, ahead of whatever the unusable
  parameter breaks below. Noted while doing it: an unknown SIMPLE type in
  parameter position (`&Missing`) is equally undiagnosed, and that is a wider
  pre-existing gap (parameter type names are never validated) left alone here.
  Regression: `examples/df140c_qualified_type_position.saw` (+ the
  `examples/modules/qualtype_dep` fixture) covers `&`, `&var`, by-value, a local
  annotation and an optional of a qualified type.

- **DF-140d — FIXED here (unit F). `Result<T?, E>` auto-wraps in both
  directions.** The shape needs a DOUBLE wrap, into the Optional then into the
  Result, and neither direction performed it. `return Cfg(v: 1)` reached the Ok
  wrap with the bare payload (`Can only insert {i1, %Cfg} at [0] in {{i1, %Cfg}}:
  got %Cfg`); `return None` never reached the auto-wrap chain AT ALL, because a
  bare `None` is compatible with every type by the none-literal rule, so
  `not _types_compatible(value_type, expected)` was False and codegen met a raw
  None (`None literal has no type information`).

  Fix: `_prepare_ok_payload` makes an expression a well-formed Ok payload when
  the Ok type is an Optional — a bare `None` is stamped with the Ok type (codegen
  reads that stamp to size the `{i1, T}`), a bare `T` is wrapped in
  `OptionalWrap`, an already-optional expression is untouched — applied at all
  three Ok-wrap sites (explicit `return`, the function tail, the method tail).
  The none-literal case gets an explicit branch ahead of the compatibility test,
  with a clean error when the Ok type is NOT an optional rather than a wrap that
  could not work. Regression:
  `examples/df140d_result_optional_autowrap.saw` — both directions plus the error
  arm, in `return` and tail position, with a `Box<any Error>` erased error type
  and through a method.

## Design 145 — DF-findings (enum methods; the std private-symbol reach)

- **DF-140h — FIXED here (unit A). Originally filed on the parked SOS M1
  branch's tracker during the round-3 module-system stress; refiled in main's
  tracker as found-and-fixed, same as DF-140f before it.** A module-PRIVATE
  `static` inside a std FILE reserved its simple name for every Saw program.
  A five-line hello-world declaring `static ASCII_ZERO` was rejected with
  "static `ASCII_ZERO` is defined multiple times" — against a private constant
  in `sawc/std/stringbuilder.saw` the author cannot see, import, or find. No
  dependency involved.

  A sweep found the blast radius is the whole set, not one name: every private
  std static tested was reserved — `ASCII_ZERO`, `MINUS_SIGN`, `MARKER_LEN`,
  `MIN_FIXED_CAPACITY` (stringbuilder), `SEEK_SET`/`SEEK_CUR`/`SEEK_END`,
  `O_RDONLY`, `MODE_RW_R_R` (file), `AF_UNIX`, `SOCK_STREAM`, `READ_CHUNK`,
  `INVALID_FD`, `NET_ERROR` (net), `GETCWD_MAX_BYTES` (directory),
  `EXEC_FAILED_CODE`, `PROC_READ_CHUNK` (process). Exactly the names a systems
  program wants for its own constants.

  Cause — and it is NOT the one the brief predicted. Private std statics already
  carried DF-140f's module-qualified codegen symbol (`saw.static.ASCII_ZERO$m$
  std_stringbuilder`), so the LLVM half was never broken. The break was the
  NAMESPACE half: `Namespace.statics` is one flat dict keyed by simple name, and
  std is merged wholesale into every module's namespace, so a private std static
  occupied the shared slot and `_register_static`'s duplicate check hit it.
  Design 82 gives each std file its own module identity; the namespace had not
  been taught to use it.

  Fix: private statics of a non-root module live in a per-module overlay
  (`Namespace.module_statics`, keyed by defining module then name) instead of
  the shared `statics` slot, and every lookup is asked FROM a module
  (`get_static(name, module)` / `has_static(name, module)`, threaded through the
  five typechecker call sites via `_accessor_vis_module()`). The accessor
  module's own privates win, so std keeps reading its own constants — the
  non-regression the tests pin. Public and root-module statics are untouched, so
  a genuine cross-module public ambiguity is still reported. Regressions:
  `examples/df140h_std_private_static.saw` (the repro, plus digit rendering
  through std's own `ASCII_ZERO`),
  `examples/df140h_std_private_static_two_files.saw` (three std files' privates
  in one program, with `std.net` imported and exercised). The design-142
  collision tests are unchanged.

- **DF-140i — FIXED here (unit B). Originally filed on the parked SOS M1
  branch's tracker; refiled in main's tracker as found-and-fixed, same as
  DF-140f/DF-140h.** USER enums could not carry methods. `extension SysError {
  func describe(&self) -> String }` was rejected with "cannot extend enum
  `SysError`: only an empty `extension SysError:
  Equatable|Comparable|Hashable|NoCopy|ImplicitCopy|ExplicitCopy {}` is
  supported", so an enum could not conform to `Error`/`Printable` with a
  hand-written body. Every error type in the tree became a struct to compensate
  — the language steering authors off the better-fitting type.

  Fix: an extension on an enum IS an extension on a struct. `EnumSymbol` grew
  the same method tables as `StructSymbol` (`methods`, `method_overloads`,
  `conformances`, `specialized_methods`), so every lookup, overload resolver and
  visibility gate written against a struct symbol works against an enum symbol
  unchanged; `_register_extension` routes an enum through the ordinary
  registration path, keeping the EMPTY derivable/copy-policy opt-ins on their
  own inline-synthesis path (designs 32/48/139, which mint no method symbol).
  Codegen names an enum receiver from the typechecker-stamped SawType, exactly
  as design 57 does for `Int` — a payload-free enum's LLVM type is a bare `i32`,
  indistinguishable from `Int32`, so the struct_types scan could never do it.

  Landed: instance methods (`&self`/`&var self`, `match self`, `self = Case`
  whole replacement per design 110), static methods, hand-written trait bodies
  (Printable + Error + `@synthesize`d Equatable coexisting on one type), generic
  enum methods monomorphized per instantiation, and design 142's import scoping
  + orphan rule applying unchanged. `init` in an enum extension is a teaching
  error ("an enum's cases are its constructors") naming a static method as the
  way to compute which case to build.

  The brief's verify-or-record item is CLOSED, not recorded: a hand-written
  `deinit` inside an enum's copy-policy conformance (design 131's rule) works,
  and works only because a policy conformance on an enum may now carry methods
  (`examples/enum145_policy_deinit.saw`).

  Two second-order bugs found and fixed on the way, both pre-existing shapes
  that only an enum receiver could reach:
  - A method call on a `&Enum` REFERENCE parameter typed as `None` with NO
    diagnostic at all. A bare type name parses STRUCT-kinded, and a reference
    parameter can reach method resolution still carrying that tag for what is
    really an enum; `get_struct_info` missed, and the call silently produced no
    type ("function `shout_here` should return `String` but body has no value").
    Both the typechecker and codegen now re-tag, matching design 61's
    `_canonicalize_type_kind`.
  - `match` on a generic enum inside a monomorphized method fell through to a
    fallback that scans for an enum with a MATCHING LLVM TYPE. Every payload-free
    enum is a bare `i32`, so that scan can silently pick a wrong enum and read
    its variant tags. The extension context now names the concrete
    instantiation first (`self_type_context`, which the monomorphized-body path
    was never setting).

  Tests: `examples/enum145_methods.saw`, `enum145_traits.saw`,
  `enum145_generic_methods.saw`, `enum145_policy_deinit.saw`,
  `enum145_init_rejected.saw`, `enum145_import_scope.saw`,
  `enum145_import_scope_error.saw` (+ three module fixtures).

- **Unit B2 (raw-backed enums) — LANDED.** Not a DF-finding; the brief's third
  unit, recorded here for the trail. `enum SysError: UInt8 { case Ok = 0, ... }`
  parses off the existing COLON token, so BOTH lexers are untouched and lexdiff
  stays at zero mismatches over the corpus — the colon-backing syntax needed
  only the parser, as the brief predicted.

  The three pins landed as confirmed: payload-free only; explicit values
  REQUIRED under a declared backing (duplicates, omissions and out-of-range
  values are each their own clean error); total `as` plus the synthesized
  `E.from(raw: U) -> E?` returning `None` on an unknown value — a lookup, not an
  init, so unit B's no-inits-on-enums rule stands. An enum WITHOUT a backing is
  not castable at all, and the diagnostic says why (its ordinals are not part of
  the type, so reordering its cases must stay a free edit).

  Representation: a backed enum IS its tag at the declared width, so
  `sizeof<SysError>() == 1` for a `UInt8` backing and the tag values are the
  ones written in source rather than declaration ordinals. Three enum sites
  assumed an i32 tag (`_generate_enum_init`, the match switch, the general
  match's tag compare) and now take the enum's own width; ordinary enums keep
  i32, so existing IR is byte-identical and `make irdet-all` is unaffected.
  That is what makes a backed enum legal as a field of a `static_assert`-pinned
  struct read through `UnsafeMemory` — the imgformat `flags` byte can be a typed
  enum (`examples/enum145_raw_wire_struct.saw` pins `SegHeader` at 12 bytes and
  reads the flags byte back raw at offset 4 to prove it).

  Equatable/Hashable auto-conformance and match exhaustiveness are unchanged; a
  raw-ordered Comparable `@synthesize` stays deferred. Tests:
  `examples/enum145_raw_backed.saw` (round trip incl. the None path),
  `enum145_raw_wire_struct.saw`, `enum145_raw_missing_value_error.saw`,
  `enum145_raw_duplicate_value_error.saw`, `enum145_raw_payload_error.saw`,
  `enum145_raw_unbacked_cast_error.saw`.

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

## Design 142 — findings (import-scoped extensions; conformance coherence)

- **DF-142-leak — FIXED by design 142 (the brief's own proving repro).** Any
  module in the link injected its `public` extension methods onto a type for the
  whole program. `main` imported `amod` only; `bmod` (reached transitively
  through `amod`) declared `public extension Data { func u16_at }`; `main`
  compiled AND RAN `d.u16_at(0)`, printing `leaked: 4660`. One module could
  monkey-patch a type for every consumer, with silent cross-dependency
  collisions and an add-a-dependency-changes-resolution hazard behind it.
  Lookup now consults the current module, the file's DIRECT imports, and the
  receiver type's own module; the transitive case is a clean error naming the
  module to import. Regression: `examples/ext142_transitive_leak_error.saw`
  (plus `ext142_direct_import` for the positive side).

- **Sweep result (Aug 5): ZERO migration**, as the brief predicted. All 416
  conformances across `blade/`, `libs/`, `selfhost/`, `sos/`, `examples/`,
  `sawc/std/` and `builtin.saw` were checked: no orphans (412 declare the type
  locally; the other 4 declare the trait locally — `extension Int/Float:
  Fooable` in the file declaring `Fooable`). Only 13 of 601 extensions target a
  foreign type, and the single user-code cross-package case, blade's
  `public extension Path { public func ensure_dir }`
  (`blade/src/layout.saw:35`), is called only inside its own module. Two notes
  for anyone touching this again: `Allocator` lives in `sawc/std/alloc.saw`,
  NOT `builtin.saw`; and a type-declaration grep must accept the `unsafe`
  prefix (`unsafe struct UnsafeMmioReg`) or it reports false orphans.

- **std is ONE scoping domain, deliberately.** Design 82 makes each std file its
  own module, but std files extend each other's types on purpose —
  `sawc/std/string.saw:932` defines `join` on `Vector<String>`, whose type lives
  in `sawc/std/vector.saw`. A literal reading of rules 1-3 would have demanded
  `import std.string` to call `v.join(", ")`. The scope predicate exempts
  `("<std>", *)`; the prelude rules already govern which std NAMES a file may
  write unimported.

- **DF-140f — FIXED here (originally filed on a parked SOS branch; refiled in
  main's tracker as found-and-fixed).** A module-PRIVATE `static` in a
  dependency collided with a same-named static in the importer —
  "ambiguous static `PT_LOAD`: defined in both `dep` and `<entry>`" — even
  though neither module can see the other's. Private extension methods stayed
  correctly invisible, so the hole was in top-level declarations. A fresh sweep
  found private FUNCTIONS had it too. Every private constant (and helper) in a
  dependency was a reserved word for its consumers.

  Cause: the typechecker resolves against the importing module's own namespace,
  which never received the private symbol, so name resolution was always right.
  Codegen works from ONE merged namespace keyed by simple name, so the two
  definitions landed on one key, and the merge reported that to the author as
  their ambiguity. Fix: private statics and private free functions in non-root
  modules take a module-qualified codegen symbol (`$m$<module>`), the merge stops
  flagging a collision it no longer has, and identifier references carry the
  resolved static symbol so codegen loads the right global. Public declarations
  are untouched — they are importable by simple name, so two under one name is a
  real ambiguity and still reported. Regression:
  `examples/df140f_private_static_collision.saw`; the public-collision tests
  (`test_static_collision`, `module_import_collision`) still pass.

- **DF-142a — CLOSED by design 144 (Aug 6).** Type identity is
  `(defining module, name)` end to end, carried as one fused string in the
  existing name slots (`Header$m$dep`, reusing design 142's `$m$` delimiter and
  module tag). Declaration name slots keep what the author wrote and carry the
  identity alongside; type REFERENCE slots hold the identity, so the layout
  registry, monomorphization keys, method mangling, the `@synthesize`
  derivation sets and the conformance table all inherit it. Root (the entry
  file and the whole single-file path) and std do not qualify, so single-file
  IR is untouched. Private enums, traits and type aliases are covered along
  with structs. The merge no longer refuses two modules' PUBLIC same-name
  types either — they coexist under `import x as` aliasing, and a bare
  reference is the design-142 use-site ambiguity error naming both modules.
  Diagnostics and docs render short names (the reporter scrubs the qualifier;
  `--emit-docs` went to schema_version 2 with a `module` field). Regressions:
  `examples/d144_private_type_identity.saw` (three `Header`s, `sizeof`
  asserted pairwise distinct, three `Vector<Header>` sums, three backed-enum
  tag tables), `d144_public_same_name_alias.saw`, `d144_bare_ambiguity_error.saw`,
  `d144_docs_module_field.saw`. Original finding follows:
  **Private TYPES still collide across modules.**
  Two modules each declaring a private `struct Header` is still
  "ambiguous struct `Header`: defined in both `dep` and `<entry>`", the same
  shape as DF-140f. It was left out of that fix deliberately: a static's or
  function's codegen identity is a symbol NAME, which is why module-qualifying
  it was contained. A type's identity is threaded through `SawType.struct_name`,
  `Codegen.struct_types`, monomorphization keys and method mangling
  (`Struct_method`), so module-qualifying it is a structural change. Suppressing
  the report WITHOUT that change would be worse than the error: codegen would
  emit one layout under the shared name and silently miscompile the other
  module's code against it. The error stays until the identity change is done.
  Repro (two files):

  ```saw
  // dep.saw
  struct Header { kind: Int }
  public func dep_kind() -> Int { 1 }

  // main.saw
  import dep.{dep_kind}
  struct Header { kind: Int }
  func main() { print(dep_kind()) }
  // error: ambiguous struct `Header`: defined in both `dep` and `<entry>`
  ```

  Same hole for private enums, traits and type aliases (the merge treats all
  five categories alike). Wants its own brief.

## Design 137 — DF-findings (fixed-capacity formatting)

**Deny window REMOVED.** Design 123's `__saw_rt_alloc_deny_after(allow, deny)`
lost its second parameter: the bounded window existed only because a panic
assembled its message into a fresh allocation, so blanket denial swallowed every
panic message. Panic messages come off the stack now
(`alloc_panic_under_full_denial` is the test 123 could not write), and the four
OOM-panic tests that used the window run under blanket denial and still report
their real messages. Denial is a plain MODE; a test that keeps running past its
failure calls `deny_after(-1)`. ABI.md and `sawc/rt/common/mem.saw` updated.

**Storage mechanism chosen: a caller-provided pointer + a compiler-allocated
scratch.** `StringBuilder(bytes: UnsafePointer<Int8>, capacity: Int)` is the Saw
surface, and `print`/`panic`/`assert` alloca their scratch in CODEGEN. Both of
the brief's nicer options are unwritable today — see DF-137a and DF-137b — and a
shared `static` scratch was excluded by the brief (MT groups exist; the panic
path must be per-stack). The generics model was not touched.

**148 LANDED (Aug 6) — const generics + repeat literals; DF-137a/b closed.**
Three units as briefed. Notes worth keeping:

- **The brief's inference claim was wrong, and the work was real.** It said "the
  design-93 solver already unifies array lengths; verify" — it does not. The
  ARRAY arm of `_unify_infer` matched the ELEMENT type only, and structurally it
  could not have done more: `array_size` was a plain `int`, not a position a
  pattern could name. The `[T; N]` case is net-new in three places (parser
  accepts a length expression, `SawType` carries a symbolic one, the unifier
  binds it).
- **ONE constant evaluator, extracted rather than duplicated.** `_const_eval`
  was a codegen method (it needs LLVM layout for `sizeof`), but array lengths
  and repeat counts must be known during type checking. Its core moved to
  `sawc/const_eval.py`, parameterized by a name->value env, an optional layout
  oracle, and the platform int width. `static_assert`'s grammar and messages are
  unchanged; the `Int.max` table is now shared with the runtime path too.
- **THREE pre-existing bugs surfaced and were fixed** (none design-148's doing;
  all three blocked the acceptance shape):
  1. Writing an element of a fixed-array FIELD (`self.data[i] = b`) was an
     internal compiler error — the container was evaluated as a VALUE and an
     array value is not a pointer to index through. It addresses real storage
     now, with the same bounds check and live-slot release a local array gets.
     (`array_field_element_write.saw`)
  2. Overloaded methods in a GENERIC extension were not callable, also an ICE.
     The typechecker stamps an overload's symbol against the generic type's
     name; monomorphization built its symbol from the specialized name and
     dropped the signature, so two overloads declared ONE symbol between them.
     Both sides compose the same way now. (`generic_extension_overload.saw`)
  3. A generic with a DEFAULT parameter could not be constructed through its own
     extension's init — two faults: the compatibility chokepoint default-FILLED
     both sides before comparing, turning a genuinely bare `Box2` into
     `Box2<Int>` so it disagreed with the abstract `Box2<T>`; and a generic
     named with no arguments reached codegen bare ("Undefined struct"). A
     defaulted TYPE parameter hit each identically. (`generic_default_init.saw`)
- **`_types_compatible` had no ARRAY branch at all**, so `[Int; 3]` passed for
  `[Int; 5]` (and `[Int; 3]` for `[String; 3]`) in silence. Added; a length only
  one side knows stays compatible, since that is the abstract half of a generic
  body.
- `std.fixedbuf` is import-required (design 82), so a user `FixedBuf` still
  compiles. `FixedStringBuilder<N>` re-aims its buffer pointer before every use,
  which is what makes a struct holding a pointer into its own storage survive a
  move; `StringBuilder.rebind` is the small public seam that allows it.

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

- **DF-137a — FIXED (design 148, units A + C).** Const generics exist:
  `struct FixedBuf<const N: Int> { data: [UInt8; N] }`, `FixedBuf<256>`, `N`
  readable as an Int in the body, the value part of the type identity and the
  monomorphization key (`$C$` arm in `mangle.py`). Both halves closed — unit A
  landed the declaration-time bound check first, so `<N: Int>` now says "`Int`
  is a type, not a trait" and its fixit names `const N: Int`. Original report:

- **DF-137b — FIXED (design 148 unit B).** `[0; 256]` is the repeat literal; an
  all-zero one lowers to a single zeroinitializer store, and a static takes one
  (`static SCRATCH: [Int8; 4096] = [0; 4096]`). Original report below. The
  bare-local half of the finding (`var scratch: [Int8; 256]` with no
  initializer) was NOT done — the repeat literal is the spelling.

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

- **DF-137a original report (found probing design 137's storage question,
  Aug 5). There are no VALUE (const) generics, so a capacity-generic
  `FixedStringBuilder<N>` is unwritable — and the near-miss spelling is accepted
  in SILENCE.** `struct FixedBuf<N: Int> { len: Int }` compiles: the parser reads
  `N` as an ordinary type parameter and `Int` as its bound, and a bound naming a
  non-trait is never checked. The declaration is then unusable from both sides:

  ```saw
  struct FixedBuf<N: Int> { len: Int }
  extension FixedBuf<N> {
      func cap(&self) -> Int { N }     // error: undefined variable `N`
  }
  func main() {
      let f = FixedBuf<16>(len: 0)     // error: undefined variable `FixedBuf`
      print(f.cap())
  }
  ```

  Two gaps, one cheap and one not. (1) No const generics — the feature. (2) A
  type-parameter BOUND naming a non-trait is silently accepted, so the diagnosis
  surfaces at the use site as "undefined variable" instead of at the declaration
  as "`Int` is not a trait". (2) is what makes (1) read as a compiler bug rather
  than a missing feature, and is worth fixing on its own.

- **DF-137b original report (same probe). A LOCAL fixed array cannot be
  zero-initialized, so caller-provided stack scratch is only writable at tiny
  sizes.** A `static` may be declared bare and lands zero-initialized in .bss
  (LANGUAGE_SPEC.md:3360), but a local may not, and there is no repeat literal:

  ```saw
  func main() unsafe {
      var scratch: [Int8; 256]              // Parse error: Expected '=' in
                                            //   variable declaration
      var other: [Int8; 256] = [0; 256]     // Parse error: Expected ']' after
                                            //   array elements
  }
  ```

  The only spelling that works is 256 literal zeros. This is why
  `StringBuilder(bytes:capacity:)` takes an `UnsafePointer<Int8>` rather than a
  `&var [Int8; N]`, and why the panic/print scratch is allocated by the COMPILER
  rather than in Saw: a stack buffer of a useful size is not writable in the
  language today. A `static` is not the answer — the panic path must be MT-safe.
  Either half would close it: bare local declarations (matching statics), or a
  `[0; N]` repeat literal.

- **DF-137c — FIXED here (found writing `StringBuilder.append(value: UInt)`).
  A platform `Int`/`UInt` overload pair was ambiguous at EVERY call site.**
  Platform `Int` and `UInt` are mutually compatible in `_types_compatible` so an
  unsuffixed literal can initialize either (design 53). Overload ranking had no
  exactness tiebreak, so both candidates scored equally even where one was an
  exact match:

  ```saw
  func take(value: Int) -> String { "int" }
  func take(value: UInt) -> String { "uint" }
  let i: Int = 5
  take(i)   // was: ambiguous call to `take`: multiple overloads match (Int)
  ```

  Free functions and methods alike; the pair was simply unwritable, which
  blocked the unsigned append overload the alloc-free path needs (the signed one
  cannot represent the top half of `UInt`). Fixed with a penalty in
  `_resolve_overload` limited to the platform `Int`/`UInt` pair. Deliberately
  narrow: a bare literal's WIDTH stays flexible, so `h(Int)` vs `h(Int8)` called
  `h(5)` remains the design-55 ambiguity (`overload_call_ambiguous_error` still
  passes — 5 really could be either). Test: `overload_int_uint_exact`.

- **DF-137d — FIXED by design 147 unit E** (with DF-140a, its parked-branch
  twin; see the design 147 section for the fix). Original finding follows:
  **FILED, not fixed (found dogfooding the SOS kernel, Aug 5). An
  integer literal is NOT range-checked against a 32-bit platform `Int`.**
  LANGUAGE_SPEC promises a bare literal is range-checked at the literal against
  its expected fixed-width type, and design 47 makes platform `Int` 32-bit on
  riscv32. `0x80000000` exceeds `Int.max` there and is accepted anyway, wrapping
  to `-2147483648`:

  ```saw
  static BIG_STATIC: Int = 0x80000000     // accepted; wraps negative
  @export("kmain")
  func kmain() {
      let big_local: Int = 0x80000000     // accepted; wraps negative
      print("{} {}", BIG_STATIC, big_local)   // -2147483648 -2147483648
  }
  ```

  Built with `--freestanding --target riscv32-unknown-none-elf`. This bites the
  exact audience the freestanding profile is for: an address constant is the
  most ordinary thing a kernel writes, and `0x80000000` is QEMU `virt`'s RAM
  base. Surfaced because the SOS kernel's first formatted log line printed its
  RAM base as a negative number. Worked around correctly rather than papered
  over — `Region` holds `UInt`, which is what an address is — but the literal
  check should reject the signed spelling instead of wrapping it. The likely
  cause is that the literal range check does not know the target's platform
  width. Repro: `.build/scratch/probe_range32.saw` (gitignored; inlined above).

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

- **`--target-features` added (not a finding, a gap closed).** sawc passed only a
  triple, which names an architecture but not which optional extensions the part
  has. The SOS kernel built its C half `-march=rv32imac` and its Saw half as base
  rv32i, where there is no divide instruction — so the first kernel log line
  carrying a number failed to link on `__divsi3`/`__modsi3`/`__udivsi3`, libcalls
  the freestanding profile has no library to satisfy. The flag is explicit rather
  than a riscv32 default: which extensions a part has is the board's fact.
  `tools/sos_runner.py` passes `+m,+a,+c`, derived from the `-march` it already
  used for clang.

## Design 133 — DF-findings (capability completions)

- **DF-133a — FIXED by design 147 unit C** (fork (i) as decided; see the design
  147 section). Decision and original finding follow: **DECIDED (user, Aug 5):
  FIX THE TRANSFORM (fork i) — design 147 owns it.** The hoist preserves source evaluation order by lifting
  side-effecting left siblings into temps, bounded by a conservative purity
  filter (literals/plain reads exempt; anything containing a call or `&var`
  use hoists); transfer checkpoints and diagnostics KEEP source positions
  (the 120 temp machinery's discipline). Fork (ii) — documenting the reorder
  — rejected: it poisons the `v.pop()!`/`v.len()` class forever. Original
  finding follows: **(found while implementing design 133 unit B, Aug
  5; PRE-EXISTING, design 120). The stage-1 ANF hoist reorders a suspending child
  ahead of a side-effecting SYNC sibling to its left.** `_anf_children` walks
  child positions left to right and lifts only the children that span a
  suspension; a sync sibling stays in place, so the lifted `let __anfN = ...`
  lands ahead of side effects that source order puts first:

  ```saw
  func slow(n: Int) -> Int { yield_now()  print("slow")  n * 2 }
  func noisy(n: Int) sync -> Int { print("noisy")  n }
  func add(a: Int, b: Int) sync -> Int { a + b }

  func body() -> Int {
      let r = add(noisy(1), slow(3))     // prints "slow" then "noisy"
      r
  }                                      // spawned; the hand-unchained spelling
                                         // prints "noisy" then "slow"
  ```

  This contradicts what LANGUAGE_SPEC.md claims for design 120 ("evaluation
  order, the deinit timing of the intermediates, and the ownership rules are the
  ones the hand-unchained spelling gets"), so either the transform or the
  sentence is wrong. Silent, not diagnosed.

  NOT fixed here because the repair is out of unit B's scope and has a real blast
  radius: preserving order means hoisting every side-effecting sibling to the LEFT
  of a lifted child into its own temp, which changes emitted IR for a large slice
  of the suite (the irdet/astdiff gates), and hoisting an owned operand into a
  temp moves the transfer checkpoint — a `move v` or an ExplicitCopy argument
  would be checked at a different point than the user wrote it. Deciding which
  siblings are "side-effecting" enough to hoist is the design question. Design
  133 unit B inherits the behavior rather than adding to it: a nested
  short-circuit is lifted on the same terms as the calls stage 1 already lifts.
  Repro: `.build/scratch/d133_order.saw` (gitignored; inlined above).

## Design 139 — DF-findings (the enum policy tier)

- **DF-139a — FIXED by design 147 unit B** (the `let` initializer bypassed the
  shared transfer path; see the design 147 section — the whole-binding shapes
  below had stopped reproducing by then, the projections had not). Original
  finding follows: **FILED, not fixed (found while implementing design 139, Aug 5;
  PRE-EXISTING and INDEPENDENT of the copy tier). Overwriting a binding
  RELEASES its old value even when a live copy of it exists**, so the copy is
  left dangling. The copy tier is not involved: it reproduces on a plain
  `String` field, on a `String?` field, and on an undeclared owning enum, and
  it reproduces IDENTICALLY before and after design 139 (only the flavour of
  garbage differs — a stale buffer before, an empty string after).

  ```saw
  func build(n: Int) -> String {
      var b = StringBuilder()
      b.append("val-")
      b.append(n)
      b.build()
  }

  struct Plain { s: String }

  func main() {
      var h = Plain(s: build(1))
      let c = h.s              // a retain IS marked here
      h.s = build(2)
      print("c={c} h={h.s}")   // prints `c=c= h=val-` — c dangles
  }
  ```

  The same shape one level up, with an enum: `var d = Dep.Path(name: build())`,
  `let e = d`, then `d = Dep.Ver(n: 3)` — `e`'s String is gone. Reading is fine
  (a copy that outlives nothing prints correctly); it is the ASSIGNMENT over the
  source that releases a payload the copy still owns. Both the field-assignment
  path and the whole-binding path are affected.

  Suspected: the assignment's release of the old value runs without consulting
  the retain the transfer checkpoint marked at the read, or the marked retain is
  not reaching codegen on this path. Wants its own brief — it is a
  memory-safety bug on the ImplicitCopy tier, where design 139 changed nothing.
  Repro: `.build/scratch/o_field_retain.saw` (gitignored; inlined above).

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

**The count, before and after.** Raw lines move with the reason comments the
brief asks for, so CODE lines (non-blank, non-comment) are the honest number:

| file | before | after |
|---|---|---|
| `sos/hal/arm64/kernel/sink.c` | 170 | 47 |
| `sos/hal/riscv32/kernel/sink.c` | 75 | 22 |
| `sos/hal/arm64/user/syscall.c` | 32 | 32 |
| `sos/hal/riscv32/user/syscall.c` | 31 | 31 |
| `sos/rt/common_c/support.c` | 75 | 75 |
| **total** | **383** | **207** (-46%) |

The two kernel HALs took all of it, which is the shape the brief predicted: the
kernel side had arithmetic wearing C's clothes, and the process side is a
syscall instruction plus a family of seams blocked on DF-172e. Units 1, 3 and 4
landed; unit 2 stopped on the language and unit 5 filed. Every surviving line
states its reason in its own file, and sos/spec.md §5c states the three reasons
there are.

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

- **DF-172e — CLOSED (design 177). Saw types a diverging loop as `Never` now,
  so the language half of "172 part 2" is gone and unit 2 (the arena +
  `__saw_rt_panic` in Saw) IS DISPATCHABLE.** The finding's own smallest-first
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

## Design 140 — DF-findings (SOS M1)

- **DF-140l — FIXED here (the M1 review round, Aug 7). A raw-backed enum's case
  was not a compile-time constant, so a wire table could not be
  `static_assert`ed against its own declaration.** Design 145 unit B2 makes a
  declared backing mean the case values are ABI — pinned, not ordinals the
  compiler may renumber — which is exactly the property an assertion wants to
  read. The evaluator had no case for a `CastExpr` or an enum member, so:

  ```saw
  enum SysOp: UInt { case DebugPrint = 0, case Shutdown = 1 }
  static_assert((SysOp.Shutdown as UInt) == 1, "op 1")
  // error: static_assert condition is not a compile-time constant:
  //        CastExpr is not allowed here
  ```

  The only way to assert anything about the table was to transcribe its numbers
  into the assertion, where the copy drifts silently in precisely the case the
  assert exists to catch. The typechecker now stamps a payload-free case with its
  raw value — ONLY under a declared backing, so an unbacked enum's ordinals stay
  non-constant and reordering it stays a free edit — and the evaluator folds that
  plus an `as` between integer types, refusing (not wrapping) a value that does
  not fit its target. One evaluator, so an array length and a repeat count gain
  the same grammar. Test: `examples/static_assert_backed_enum.saw`.

- **DF-140m — FIXED here (the M1 review round, Aug 7). A distinct `type` alias
  had no constructor, so an alias over an unsigned or fixed-width underlying
  could not be given a value at all.** LANGUAGE_SPEC documented `UserId(42)` as
  implemented and the `42 as UserId` diagnostic named it as the sanctioned form;
  it was an `undefined function` error. The one working spelling was an
  annotated `let`, which accepts an underlying of just the four primitive kinds
  (`Int`, `Float`, `Bool`, `String`), so `type Handle = UInt` was undeclarable in
  practice:

  ```saw
  type Handle = UInt
  let h: Handle = 7      // error: cannot assign `Int` to variable of type `Handle`
  let h = Handle(7)      // error: undefined function `Handle`
  ```

  Now a construction taking one unlabeled argument, checked against the
  underlying with that type pushed down so a bare literal adopts it and is
  range-checked there. Representationally free — codegen emits the operand.
  Tests: `examples/type_alias_construction.saw` + two error cases.

- **DF-140n — FIXED here (the M1 review round, Aug 7). Two distinct aliases over
  one underlying type flowed into each other, in assignment and argument
  position.** Only the sibling CAST was rejected, so `type` was enforced in
  exactly one position and was a comment everywhere else:

  ```saw
  type UserId = Int
  type OrderId = Int
  func lookup(o: OrderId) -> Int { o as Int }
  let user: UserId = 42
  let order: OrderId = user   // compiled
  lookup(user)                // compiled
  ```

  This is the one that mattered for SOS: a typed handle is a safety property
  exactly to the extent that another kind's handle cannot land in it. Compat now
  asks what the cast already asked — an alias satisfies another alias by BEING
  it or by having it on its own definition chain (`type Super = Mid` still flows
  to `Mid`), and siblings do not. The chain walk was duplicated across the two
  sites and now lives in one helper the cast calls, so the rule cannot drift from
  itself. Blast radius was nil: no distinct alias appears in std, blade, libs,
  sos or selfhost. Tests: `examples/type_alias_sibling_no_flow_error.saw`,
  `examples/type_alias_sibling_arg_error.saw`.

  A fourth gap surfaced while fixing this: **an IMPORTED alias was not treated as
  an alias.** `get_type_alias_info` looked only in the current namespace, so
  across a module boundary the name resolved as a TYPE (an annotation or field
  using it checked fine) while every rule asking "is this an alias?" answered no
  — it neither flowed to its underlying nor accepted its constructor, one module
  away from the declaration. The deep lookup already existed and
  `is_trivially_copyable` already used it. Tests:
  `examples/type_alias_cross_module.saw` + the cross-module sibling error.

- **DF-140j — FIXED here (the M1 adoption pass, Aug 6). A place use inside a
  struct or map literal reached codegen unlowered.** See the adoption-pass
  section above for the walk gap and the fix; test
  `examples/place_paired_literal_fields.saw`.

- **DF-140k — FIXED here (the M1 adoption pass, Aug 6). An extension method's
  parameter types were never resolved, so a backed enum parameter could not be
  cast.** See above; test `examples/backed_enum_extension_param.saw`.

- **DF-140a — OPEN. A bare integer literal outside the TARGET's platform-`Int`
  range silently wraps; the same source means a different number per profile.**
  The documented rule is that a bare literal adopting an expected type is
  range-checked at the literal, and for FIXED-width types it is
  (`let b: UInt8 = 256` is a clean error). Platform-width `Int`/`UInt` are never
  checked against the target width:

  ```saw
  @export("probe")
  func probe() -> Int {
      let x: Int = 2149580800      // 0x8020_0000
      x
  }
  ```

  `--target riscv32-unknown-none-elf` emits `ret i32 -2145386496`;
  `--target aarch64-unknown-none-elf` emits `ret i64 2149580800`. No diagnostic
  from either. This is squarely in SOS's path: every riscv32 kernel address at
  or above 0x8000_0000 written as a plain `Int` is silently a negative number,
  and it means something else again on the arm64 Profile B (§5b) — exactly the
  two-profile portability the fixed-width discipline exists to protect. The M1
  kernel dodges it by using `UInt` for every address and machine word, which is
  the honest type anyway, but nothing makes that choice for the next author.
  SEPARATELY: `static B: UInt8 = 256` compiles clean, so the fixed-width check
  that catches the `let` is not applied to `static` initializers at all.

- **DF-140b — OPEN. An import symbol list cannot be wrapped across lines.**

  ```saw
  import kcore.{
      console, pmp_reset, pmp_region,
  }
  ```

  is `Parse error: Expected symbol name in import`. Design 129 made newlines
  insignificant inside `(`/`[` and committed `<...>` but left `{}`
  newline-significant on the grounds that a block or closure is a statement
  container — which an import list is not. It is a delimited list exactly like
  an argument list. `sos/tests/umode.saw` imports eleven names and has to run
  them onto one 120-column line.

- **DF-140c — OPEN. A module-qualified type does not resolve in TYPE position**
  (it resolves fine in expression position — `toml.TomlDoc.parse(...)` works).

  ```saw
  // src/lib.saw of module `qual`
  public struct Section { name: String }
  public extension Section {
      public func value(&self, key: String) -> String? { None }
  }
  ```
  ```saw
  import qual
  func take(s: &qual.Section, key: String) -> Int {
      guard let raw = s.value(key) else { return 0 }
      raw.len()
  }
  ```

  Three errors, all downstream of the unresolved parameter type: `undefined
  variable raw` (the method does not resolve, so the `guard let` binds
  nothing), then `function take should return Int but body has no value`, then
  at any call site `argument s expects &qual.Section but got &Section` — the
  qualified spelling is treated as a distinct nominal type from the imported
  one. The silent part is the worst of it: a `guard let` over an unresolvable
  method reports the BINDING as undefined rather than the method. Workaround:
  import the type bare (`import toml.{TomlSection}`) and write `&TomlSection`,
  which is what `blade/src/sosimg.saw` does.

- **DF-140d — OPEN. `Result<T?, E>` cannot be auto-wrapped in either
  direction; both spellings are internal compiler errors.**

  ```saw
  struct Cfg { v: Int }
  struct Oops { m: String }
  extension Oops: Error {
      func format(&self, into: &var StringBuilder) { into.append(self.m) }
  }

  func f(flag: Bool) -> Result<Cfg?, Oops> {
      if flag {
          return None            // ICE (typechecker)
      }
      return Cfg(v: 1)           // ICE (codegen)
  }
  ```

  `return None` gives `internal compiler error: None literal at line N has no
  type information. resolved_type=OPTIONAL, current_return_type=Result<Cfg?,
  Oops>`; the value return gives `Can only insert {i1, %"Cfg"} at [0] in
  {{i1, %"Cfg"}}: got %"Cfg"` — the double wrap (into the Optional, then into
  the Result) is not performed. Independent of error erasure: a `Box<any
  Error>` error type behaves identically. MATCHING a `Result<T?, E>` and
  binding through `if let` both work, so the shape is only broken at the
  auto-wrap boundary. Workaround: an explicitly typed local
  (`let absent: Cfg? = None; return absent`), used in `load_sos_config`.
  `Result<T?, E>` is the right signature for "it failed, or there is/isn't
  one", so this is worth fixing rather than designing around.

- **DF-140e — OPEN, and a MISCOMPILE rather than a clean error. A tail `match`
  in a Result-returning function, with one arm that diverges and one that
  yields a bare error value, drops the auto-wrap into `Err`.**

  ```saw
  func tail_match(flag: Bool) -> Result<Void, Oops> {
      match source(flag) {
          case Ok(v) -> {
              if v < 0 { return Oops(m: "negative") }
              return
          },
          case Err(e) -> e
      }
  }
  ```

  The arms unify to `Oops` (the Ok arm's type is Never), and the match's value
  is returned RAW: `ret %"Oops" %"match_result"` from a function whose result
  type is `{ i32, [8 x i8] }`. Caught here only because the LLVM IR verifier
  rejected it — a pairing whose sizes happened to agree would have compiled to
  a wrong value. The same shape with a non-diverging Ok arm is fine, and the
  `if`/`else` spelling of it is fine, so this is specific to a diverging arm
  suppressing the wrap. Workaround: make both arms statements and `return`
  below the match (`blade/src/builder.saw`'s `run_tool`).

- **DF-140f — OPEN. A module-PRIVATE `static` collides across a selective
  import.** Found stressing the module system with the shared `imgformat`
  package (design 140 revision). `blade/src/sosimg.saw` declares
  `static PT_LOAD: UInt = 1` with no `public`. A test module doing
  `import src.sosimg.{elf_to_sosimg}` — one function, by name — cannot then
  declare its own `PT_LOAD`:

  ```
  error: ambiguous static `PT_LOAD`: defined in both `src.sosimg` and `<entry>`
  ```

  So a private static in an imported module reserves its NAME in every importer
  while remaining inaccessible to them, which is the worst of both rules. The
  contrast in the same file is sharp: `src/sosimg.saw`'s module-private
  `extension Data { func u32_at ... }` is correctly invisible to the same test
  (`method u32_at of Data is private and not accessible from this module`), so
  extension methods get the design-80/82 treatment and statics do not.
  Workaround: prefix the importer's constants (`ELF_PT_LOAD`). Blast radius
  grows with package count — every private constant in every dependency is a
  reserved word for its consumers.

- **DF-140h — OPEN. DF-140f's fix does not cover STD. A module-private `static`
  in a PRELUDE std module still reserves its name for every user module.**
  `sawc/std/stringbuilder.saw` declares `static ASCII_ZERO: Int = 48` with no
  `public`, and StringBuilder is prelude, so it is compiled into everything:

  ```saw
  static ASCII_ZERO: UInt = 48        // error: static `ASCII_ZERO` is
                                      // defined multiple times
  @export("probe")
  func probe(n: UInt) -> UInt { ASCII_ZERO + n }
  ```

  Five lines, no dependency, `--freestanding --target riscv32-unknown-none-elf`.
  DF-140f fixed the dependency case (a private declaration in a package no
  longer reserves its name downstream); the implicitly-compiled prelude modules
  were not covered by that sweep, so every private constant in std is still a
  reserved word for user code. Worse than the dependency case in one way: a user
  cannot see the colliding name without reading std, and the diagnostic does not
  say where the other definition is. `sos/rt/common/`'s hex constants carry a
  `HEX_` prefix to route around it.

- **DF-140i — OPEN. An enum cannot carry ANY methods, so a tagged error type
  cannot be given behavior or made Printable.** Found giving the `sos` module a
  `SysError` (design 140 round 3). `extension SysError { func from_status(...) }`
  is rejected:

  ```
  error: cannot extend enum `SysError`: only an empty
  `extension SysError: Equatable|Comparable|Hashable|NoCopy|ImplicitCopy|ExplicitCopy {}`
  is supported
  ```

  The consequences compound for exactly the shape an enum is best at. A closed
  tag set is the right type for a syscall status, but it cannot have a
  `from_status` constructor (that becomes a free function, so the conversion
  reads `sys_error(s)` instead of `SysError.from_status(s)`), and — the real
  cost — it cannot conform to `Error` or `Printable`, so a `SysError` cannot be
  interpolated into a message and cannot flow through the erased
  `Result<T, Box<any Error>>` that the rest of the language treats as the
  error idiom. Every other error type in the tree is a struct for this reason,
  which is the language pushing authors away from the better-fitting type.
  Deliberate today (the diagnostic is clear and names what IS allowed), but it
  is worth a brief: enums are already payload-carrying and matchable, and
  methods on them are the one thing keeping them second-class.

- **DF-140g — OPEN, a capability gap rather than a bug: a freestanding runtime
  cannot be written in Saw.** Design 140's revision moved every arch-free,
  role-free runtime helper it could into `sos/rt/common/` (Saw). Three things
  could not go, and together they are why `sos/rt/common_c/support.c` still
  exists:
  1. **No mutable module state.** A bump allocator needs a cursor that survives
     between calls. `static` is const-initialized and immortal, and the only
     mutable static is `Atomic`, so there is no way to write one.
  2. **No way to reserve a region.** The arena needs N bytes of `.bss`. A Saw
     `static` cannot declare uninitialized backing storage, and `UnsafeMemory`
     needs an address the program does not have a way to obtain.
  3. **The seams cannot be exported.** `__saw_rt_alloc` / `__saw_rt_panic` /
     `__saw_rt_write` are reserved names that only `--runtime-build` may
     `@export` (design 113b), and that mode is scoped to authoring `sawc/rt/`
     — an object-only, sync-only build of the host runtime, not a kernel or a
     process image.

  Consequence: every freestanding Saw target — kernel, process, and any
  embedded program — must carry a C file to be a complete program at all. That
  is a real limit on the "kernels and embedded first" claim, and it is worth a
  brief: either a sanctioned way for a non-`sawc/rt` build to supply the seams,
  or `static var` plus a `.bss` reservation so the arena can be Saw. (1) and
  (2) would also close the F5 singleton-driver gap.

## Design 131 — DF-findings (payload-read ownership)

- **DF-131a — FIXED (design 139, Aug 5).** A WHOLE-optional read of a NoCopy or
  ExplicitCopy payload aliased and double-dropped. Closed by giving every type
  exactly one copy tier: `Namespace.copy_tier` joins a wrapper's tier from its
  parts, so `Optional<T>`, tuples, fixed arrays, enum payloads and `Result<T, E>`
  are each no weaker than what they wrap, and the move checkpoint is one lookup
  into it. The original filing follows.

  Design 131 made the PAYLOAD read policy-driven, but
  the optional ITSELF still has no tier: `_is_no_copy_type` / `_is_explicit_copy_type`
  key off a struct/enum name, and `Optional<T>` has neither, so the checkpoint
  falls through to the default bitwise path:

  ```saw
  struct Res { id: Int }
  extension Res: NoCopy {
      func deinit(&var self) { print("drop res {self.id}") }
  }

  func main() {
      let o: Res? = Res(id: 1)
      let p = o                 // no move required, no copy performed
      print("ok")
  }                             // prints "drop res 1" TWICE
  ```

  This is DF-128a's disease one wrapper out. The brief said whole-optional
  operations were unchanged because `let y = x` "already retains via the
  owning-enum arm" — true for an ImplicitCopy payload (`is_implicit_copy_enum`
  covers it, and codegen's `_transfer_needs_copy` retains an owning OPTIONAL read
  out of a container slot), but there is no corresponding arm that REFUSES when
  the payload is move-only. An `Optional<Vector<Int>>` behaves the same way.

  NOT fixed here because the natural fix — an `Optional<T>` inherits T's copy
  policy at the checkpoint — has a blast radius the brief did not scope. It makes
  `let y = x` on a `Vector<Int>?` demand `move x`, and `.copy()` on an optional is
  currently rejected outright ("type `Vector<Int, GlobalAllocator>?` is not
  Copy"), so the only spelling left would be `move`. Whether containment should
  follow (does `struct H { r: Res? }` become move-only?) is the same design
  question one level up. Worth a small brief; the repro above is five lines.
  Repro: `.build/scratch/p131_e.saw` (gitignored; inlined above).

## Design 124 — DF-findings (TaskGroup eager teardown)

- **DF-124a — FIXED (design 124, Aug 5).** Frame-field reads had no ownership
  discipline. A coroutine frame holds an owned local in a `T?`-encoded field and
  reads it as `self.name!`; the ForceUnwrap hid the underlying field access from
  BOTH the typechecker's transfer checkpoint and every codegen copy predicate
  (they match bare place expressions — Identifier / MemberAccess / ArrayIndex /
  TupleIndex). So a transfer out of the frame took a non-retaining alias AND left
  the field's drop flag set: neither the retain branch nor the move branch ran.
  Latent before eager teardown (the frame outlived every reader, and a joined
  task's take cleared `__result`, so the stale flag cost one late drop), it
  became an immediate use-after-free once the field was released at task
  completion — `func w() -> Wrap { let s = "v{n}"; yield_now(); Wrap(s: s) }`
  handed back a `Wrap` whose String the frame then freed. Fix: `_read_field`
  marks a non-`move` whole-binding read `frame_owning_read`, and codegen applies
  the same read-out-of-storage retain the closure-capture materialization already
  spells with `.copy()` — at call/return transfers (`_transfer_needs_copy`),
  struct-literal fields (`_needs_copy_for_struct_init`) and both assignment paths
  (`statements.py`). A `move` read is deliberately unmarked: it keeps
  transferring the frame's own reference via `__saw_forget`. Retains are typed
  against the VALUE's type, not the destination field's, since an opt-encoded
  destination is `T?` while the read is the bare payload.

- **DF-128a — FIXED (design 131, Aug 5).** `Deinit` is non-declarable:
  `extension T: Deinit {...}` is a compile error naming the three copy policies,
  and a hand-written `deinit` body lives inside the policy conformance (the
  requirement is inherited). That makes the unpoliced state unreachable rather
  than diagnosed — a type with a destructor now always has a transfer rule, so
  the checkpoint's missing arm cannot be entered; it was added anyway as an
  internal-error tripwire. Containment follows for free: the migrated `Res` is
  `NoCopy`, so `struct Pair { a: Res }` hits the existing NoCopy containment
  error. Migration was 108 types — 74 with no policy at all became `NoCopy` (the
  semantic the fallthrough should have had), 34 folded into a policy they already
  declared; `Vector` was the one judgment call, keeping its `deinit` on the plain
  unconditional extension because its destruction covers every `T` while its
  `ExplicitCopy` conformance is bounded `<T: Copy>`. Tests:
  `errors/deinit_needs_copy_policy`, `errors/deinit_policy_migration_moves`,
  `deinit_policy_containment`. `T: Deinit` as a generic BOUND is untouched.
  Original finding follows: **a `Deinit`-only type aliases and
  double-frees (found while probing for design 128, Aug 5; PRE-EXISTING —
  reproduces with design 128 reverted).** A type whose only resource conformance
  is `Deinit` falls through every arm of the value-transfer checkpoint, so a
  plain `let s = r` bitwise-aliases it and both copies run `deinit`:

  ```saw
  struct Res { id: Int }
  extension Res: Deinit {
      func deinit(&var self) { print("drop res {self.id}") }
  }

  func main() {
      let r = Res(id: 7)
      let s = r                 // no move required, no copy performed
      print("alive {r.id} {s.id}")
  }                             // prints "drop res 7" TWICE
  ```

  `_check_transfer` (typechecker/types.py) branches on NoCopy / ExplicitCopy /
  ImplicitCopy / owning-enum and has no arm for "carries a deinit but declared no
  copy policy", so the transfer takes the default path — a bitwise move that
  never retires the source. It also reaches one level up: `struct Pair { a: Res }`
  behaves the same, and today `extension Pair: Deinit { ... }` satisfies the
  containment rule without making `Pair` move-only.

  NOT fixed here because it is a language-semantics call, not a patch. The sound
  answer is that `Deinit` alone implies move-only (Rust's model): a value that
  owns a resource and has no copy policy can only be moved. That is a one-line
  change at the checkpoint, but it retires an accepted spelling — roughly fifteen
  in-tree examples declare a bare `extension X: Deinit` on a type they then copy
  freely, and each would need `move` or a policy. Design 128 explicitly left the
  copy-policy containment rule unchanged, so widening it was out of scope. What
  128 DID change is reachability: with the Deinit containment error gone, a
  struct holding a `Deinit`-only field now compiles with no declaration at all,
  so the hole is easier to fall into than it was. Repro:
  `.build/scratch/p5_deinit_alias.saw` (gitignored; inlined above).

- **DF-128c — CLOSED (Aug 6, commit f4222fd), with DF-132a, one commit.**
  `_type_method_base` fills default type arguments before mangling, through the
  same `_fill_default_type_args` chokepoint every other mangling of a named type
  uses. A `Vector`/`Map`/`Set`/`Box` FIELD runs its own deinit again.
  Regression: `examples/vector_field_drop_glue.saw`.
  Restoring the glue made two more live double-frees real — both had been
  cancelled by it, both are fixed here, and both are recorded as DF-146h and
  DF-146i below. Original finding follows.
  **`_type_method_base` did not fill
  default type arguments, so a struct FIELD's generic type mangled to a symbol
  that does not exist (found by design 128, Aug 5; PRE-EXISTING).** A field
  written `Vector<Int>` denotes `Vector<Int, GlobalAllocator>`, and the
  monomorphized methods are registered under the full form
  (`Vector$2$Int$GlobalAllocator_copy`). `_type_method_base` calls `mangle_type`
  on the written form directly, producing `Vector$1$Int`, and every consumer
  treats the resulting miss as "this type has no copy/deinit of its own" and
  falls back to structural glue. generics.py:131-154 documents exactly this
  chokepoint ("every mangling of a named type funnels through
  `_fill_default_type_args` ... the dual-identity hazard is closed") — this
  caller skips it. It bites only types with a DEFAULTED type param, i.e.
  Vector/Map/Set/Box.

  The copy half was a live memory-safety bug and IS fixed here, narrowly: a
  derived memberwise `copy()` over a `Vector` field bitwise-aliased the buffer,
  so `let b = a.copy()` gave two holders sharing one allocation, mutations were
  visible through both, and both freed it. `_field_copy_fn` (codegen/methods.py)
  now fills the defaults before the lookup and RAISES rather than silently
  aliasing if the symbol is still missing. Test:
  `examples/synthesize_explicit_copy_holder.saw` (fails before, passes after).

  The DROP half is **STILL STOPPED after design 146 unit C (Aug 5)**, for the
  same reason it always was: it must land with the `Vector.get` conversion, and
  that is blocked on DF-146e. The fix was written and exercised during unit C
  (fill the defaults in `_type_method_base`, exactly as `_field_copy_fn` does)
  and reverted with its partner — it is confirmed correct and confirmed a live
  double-free without the partner. Originally diagnosed by design 132 unit H per
  the brief's stop-if-it-fights rule. What blocks it
  is the OTHER path: **DF-132a below — `Vector.get` has no
  `T: Copy` bound, so it hands out a non-retained bitwise ALIAS of a NoCopy
  element.** libs/toml's `TomlDoc.get_section` / `TomlSection.get_table` and
  blade's manifest reader are built on that alias. The two bugs currently
  CANCEL: the alias runs the element's deinit at scope exit, and the container's
  `Vector<T>` field drop glue never runs, so each element is freed once and the
  program looks correct. Fixing the drop glue alone makes the container free the
  element a SECOND time — which is the stage1 SIGSEGV.

  Proven both directions on a 60-line repro (`.build/scratch/p132_h_alias.saw`,
  inlined under DF-132a): with the drop-glue fix `Item.deinit` prints twice for
  one element, without it exactly once. Localized from the bootstrap down to a
  single test by bisection: `blade tree` and `blade/tests/manifest_dependencies`
  both SIGSEGV with zero output, and a probe showed the crash inside
  `Manifest.load_from`, at `doc.get_section("package")` — a `TomlSection?`
  returned by value out of a `Vector<TomlSection>` whose element type is
  `NoCopy`. Instrumenting `_emit_drop_at` listed exactly the 13 fields that
  newly acquire drop glue: `TaskGroup`'s three vectors, `Command`, `DepList`,
  `GitTags`, `LockData`, `ReqList`, `Resolution`, `TomlDoc`, `TomlSection` (x2),
  `TomlTable`.

  **These two must land together, and the pairing is a DESIGN QUESTION, not a
  patch.** Giving `Vector.get` the bound the docs already claim it has breaks
  libs/toml and blade at the source level: `get_section`/`get_table` cannot
  return a NoCopy element by value at all, so they need a redesign (a
  `with_ref`-shaped scoped borrow, an index-returning lookup, or making the toml
  types `ExplicitCopy`), and blade's callers move with them. That is a std API
  change plus two package migrations — RS-2's unfinished half (design 122 gave
  the bound to `iter`/`enumerated`/`each`/`map` and to `set`, but never to
  `get`). Wants its own brief with the API shape decided up front.

  THE MIGRATION HALF IS DONE (design 146 unit C, Aug 5): libs/toml and blade no
  longer hand a NoCopy `TomlSection`/`TomlTable` out by value at all.
  `TomlDoc.get_section` is GONE, replaced by
  `section(name) borrows -> TomlSection?` plus the index-returning
  `index_of`/`section_at` pair and a `has_section` presence question;
  `TomlSection.table(key)` is the inline-table place. So when DF-146e clears,
  the remaining work is the two-line `_type_method_base` fix and the `get`
  conversion itself — the source-level breakage this entry warned about has
  already been absorbed.

- **DF-141a — FIXED in place (design 141 unit B, Aug 5). `move x` on a local
  whose type INSTANTIATED to `Void` raised `internal compiler error: Undefined
  variable: x`.** Design 132 unit C made a Void-instantiated binding a
  zero-sized one — no alloca, and `visit_Identifier` reads it back as no value —
  but only taught the READ path. `_generate_move_expr` still went looking for
  storage and raised, so a generic body that type-checked fine produced an
  internal error at one instantiation, which is precisely what unit C's
  instantiation-uniformity rule ("a body that type-checks generically compiles
  for every instantiation") exists to prevent. Moving a zero-sized binding
  transfers nothing: it yields no value and suppresses no deinit. Found while
  looking for a lowering for a borrows epilogue's `let __wr = __window(...); ...;
  return move __wr`, where `__R` is unbounded and Void is an ordinary
  instantiation. Test `examples/generic_local_move_at_void.saw` covers `R` =
  Void, Int, String and a NoCopy type (the last asserting exactly one deinit, at
  the CALLER's scope exit). The transform itself ended up not needing `move` —
  a plain return of a local at its last use is already a transfer and stays
  sound for a NoCopy `R`, proven by probe — but the ICE was real either way.

- **DF-128b — FIXED (design 132 unit E, Aug 5).** `Namespace.is_trivially_copyable`
  gained the ENUM branch it never had: a payload-free enum that declares no
  resource trait is a bare tag, so it copies bitwise and has no deinit to
  double-run. The gate is `is_equatable`'s auto-conformance gate verbatim,
  which is what the spec promises — the auto-Copy set and the auto-Equatable set
  are one set. An enum WITH a payload keeps its old classification (derived
  structurally by `is_implicit_copy_enum`); widening triviality to "all payloads
  trivial" would change copy tiers for `enum Msg { case Move(x: Int, y: Int) }`
  and is a separate question, not needed here. Test
  `examples/enum_payload_free_as_key.saw`: Set element by insertion and by
  collection literal, Map key by literal and by `insert`, plus `contains` /
  `contains_key` / `get` round-trips. Original finding follows.
  `Set<Color>` on a payload-free enum is rejected with "set
  element type `Color` must be copyable ... owns a Deinit without a copy (it is
  move-only, not retainable)", which is false — the enum owns nothing.

  ```saw
  enum Color { case Red, case Green }

  func main() {
      var palette: Set<Color> = Set<Color>()   // error: must be copyable
      palette.insert(Color.Red)
      print(palette.len())
  }
  ```

  `Namespace.is_trivially_copyable` handles STRUCT, tuple, optional and array
  kinds and falls off the end returning False for `TypeKind.ENUM` — unconditionally,
  payload or not. `_key_copyable_reason` then reads that False as "owns a Deinit"
  and reports the misleading reason. The gap is visible in the docs too: `Color`
  is documented as auto-`Hashable`, and `examples/map_each_string_enum.saw` uses a
  payload-free enum only as a VALUE, never a key. Fixing it means teaching
  triviality about enums (payload-free, or all payloads trivial), which touches
  copy classification everywhere and wants its own unit rather than a drive-by in
  128. Repro inlined above.

- **DF-128d — FIXED (design 132 unit D, Aug 5), together with its duplicate
  DF-129a.** `print` now asks the renderability question interpolation asks:
  both call `_check_renderable_operand` (typechecker/expressions.py), which
  passes a builtin kind or a `Printable` conformance (a `T: Printable` bound
  included) and otherwise reports at the argument. `print(o)` on an `Int?` gives
  `cannot print value of type `Int?`: it is not `Printable``, with the same
  `extension Int?: Printable` hint interpolation already gave; the verb is the
  only difference between the two messages, so the interpolation text is
  unchanged. The open design question — whether `T?` should BE Printable at all
  (Swift renders `Optional(5)` / `nil`) — is untouched and still open; this only
  makes the refusal a diagnostic instead of a crash. Test
  `examples/errors/print_optional_not_printable.saw` covers the bare optional,
  the `v.get(0)` shape both findings hit, and the interpolation twin.
  Original finding follows: three lines, no generics:

  ```saw
  func main() {
      let o: Int? = 5
      print(o)          // error: internal compiler error: Cannot print type: {i1, i64}
  }
  ```

  An ICE is never the right answer. What the right answer IS is a small design
  question, which is why it is filed rather than patched: either `T?` is not
  Printable and this is a clean "does not conform to `Printable`" error at the
  call site, or optionals render (Swift prints `Optional(5)` / `nil`) and the
  formatter grows a case. Hit while writing a test that printed
  `v.get(0)` — `Vector.get` returns `T?`, so this is easy to reach by accident.

- **DF-124b — FIXED (design 131, Aug 5).** Every payload-extraction form — `o!`,
  the `??` left operand, an `if let`/`guard let` binding — now denotes a PLACE,
  and the Copy family governs the read exactly as it governs every other read.
  `_is_aliasing_expr` sees through a force-unwrap (`o!` aliases iff `o` does, so
  `f()!` stays a fresh temporary), and the retain lands AT the extraction rather
  than at the enclosing transfer site, because a `let` initializer never reaches
  the transfer-site copy path. `??` also gained a checkpoint on its DEFAULT
  operand, which had never been checked at all — `let s = opt ?? other` aliased
  `other` and double-freed it (found while implementing; the ExplicitCopy repro
  aborted with SIGTRAP). The consuming forms are `move o!` (compile-time, retires
  the whole binding, locals only) and `Optional.take(&var self) -> T?` (runtime,
  swaps `None` into the place, reaches a FIELD). `TaskHandle.join` — which
  EXPLOITED the non-retaining read via `let r = ptr[0]!` + `__saw_forget` —
  migrated onto `self.result_ptr[0].take()!`; no .saw file calls `__saw_forget`
  any more, though it stays a builtin for the unsafe domain. The coroutine
  transform's frame reads are exempt (`frame_place_read`): the transform runs
  after the type-check that already judged those reads un-projected, and the
  whole program is then re-checked, so weighing in again would double-retain an
  ImplicitCopy payload and reject a NoCopy one the frame is moving out.
  Original finding follows.
  DF-124a's root cause is not confined to coroutine frames: reading a payload out
  of ANY optional with `!` neither retains it nor clears the source's ownership,
  so the reader gets a non-owning alias. Five lines, no coroutines, no unsafe:

  ```saw
  func main() {
      var o: String? = "v{1}"     // interpolation => a heap-allocated String
      let a = o!                  // reads the payload WITHOUT retaining it
      o = None                    // releases the payload
      print(a)                    // `a` dangles: prints NUL bytes
  }
  ```

  Same for a `T?` STRUCT FIELD (`let b = h.s!`, then `h.s = None`), for an
  `if let` binding out of a field, and for `??`. `_generate_force_unwrap` is a
  bare `extract_value` and `_ALIASING_EXPR_TYPES` does not include `ForceUnwrap`,
  so nothing along the path accounts for the payload.

  NOT fixed here because the obvious fix (teach `_is_aliasing_expr` to see through
  `ForceUnwrap`) would break an idiom the executor itself depends on:
  `TaskHandle.join` does `let r = self.result_ptr[0]!` followed by
  `__saw_forget(self.result_ptr[0])` — a deliberate MOVE out of a container,
  which only works because `!` does not retain today. So the question is a design
  one, not a patch: does `opt!` COPY the payload (and how is a move-out then
  spelled — a `take()` on Optional? `move o!`?), or does it MOVE (and then `o`
  must be marked moved-from, which the checker does not do either)? Either answer
  needs the NoCopy case decided too: `let g = f!` on a `File?` is currently
  accepted and silently duplicates. Design 124 scoped itself to the frame
  encoding it owns; this wants its own brief. Repro:
  `.build/scratch/probe_df124b.saw` (gitignored; inlined above).

- **DF-124c — CLOSED (design 134, Aug 5).** Mechanism, as the brief specified it:
  `__result` and `__cancel` moved OUT of the coroutine frame into a per-task CELL
  the group owns, allocated at spawn beside the slot (`__ResultCell<T>` /
  `__VoidCell`, held erased as `Box<any __TaskCell>` so the group never names
  `T` and the box teardown still runs the right destructor). A spawn-root frame
  carries only a `__cellp` pointer to it, so NOTHING outside the frame points
  into it and `TaskGroup.__complete` releases the frame box at Done — design 124
  item 3, now implementable. The slot then goes on a free list, and handles
  became `(slot, generation)` pairs so a stale handle is a defined outcome rather
  than a read of its successor: `TaskHandle.join` panics ("this task's result was
  already joined"), `VoidTaskHandle.join` returns, `cancel` no-ops.
  `cancel_addr()` — the case that motivated the finding — PINS its slot: the raw
  address it hands a peer must outlive the task and carries no generation to
  check, so that one slot keeps its cell and gives up reuse. Measured on 200k
  short tasks through one group: 200,000 slots / 31.0 MB peak RSS before,
  4 slots / 1.5 MB after. Fences: `taskgroup_slot_reuse_o_live`,
  `taskgroup_slot_reuse_mt`, `taskgroup_stale_handle_join`,
  `taskgroup_stale_handle_cancel`, with the design-124 fences green throughout.
  Original finding follows: **design 124
  item 3 was NOT implemented as written; the frame box is retained (Aug 5).** The brief asked
  that "the `tasks` vector slot become reclaimable at Done (drop the Box
  eagerly)". That is unimplementable alongside the brief's own items 1-2, which
  require the never-joined `__result` to survive until group teardown: `__result`
  lives INSIDE the frame, and `TaskHandle`'s `result_ptr` and `cancel_ptr` are
  raw pointers into it. Freeing the box at Done would dangle both — and
  `cancel_addr()` hands a raw frame address to a peer task precisely so it can
  write the cancel word LATER, which no done-check can guard. What design 124
  does deliver is that every RESOURCE the frame held is released at Done; what
  the slot keeps afterward is the frame allocation itself (the result slot plus
  the scheduler words). For a long-lived accept-loop server that is still O(tasks
  ever spawned) memory, bounded by frame size — the bookkeeping vectors are
  already O(tasks ever spawned) by the brief's own "do NOT compact, indices are
  handles" rule. Reclaiming the box needs `__result` and `__cancel` relocated out
  of the frame into group-owned, type-aware cells (the erased `Box<any Resumable>`
  cannot free a payload it no longer describes), which is a protocol change
  across the spawn lowering, `TaskHandle`, and design-102's `__is_cancelled`.
  Worth a follow-up brief; not a correctness bug.

## Design 134 — DF-findings

- **DF-134a — FIXED by design 147 unit D** (the seam is in the frozen ABI; see
  the design 147 section). Decision and original finding follow: **APPROVED
  (user, Aug 5): the `__saw_rt_reactor_unregister` seam joins the frozen ABI —
  design 147 owns it** (kqueue EV_DELETE / epoll
  EPOLL_CTL_DEL in the Saw reactors; called on the park loop's cancellation
  exit + belt-and-braces at frame `__release` for registered-unfired tokens;
  regression: park, cancel, escape the fd via the result, poke it. Post-134
  severity note: the frame box frees at Done, so a stale one-shot's token is
  a POINTER INTO FREED MEMORY — this is a use-after-free vector, not a
  leak). Original finding follows: **(reactor-token lifetime vs fd
  lifetime; found landing design 134, Aug 5).** The design-91 reactor token is
  the ADDRESS of the root frame's `__wake` word: `io_wait` arms
  `EV_ADD|EV_ONESHOT` with `udata = &frame.__wake`
  (`sawc/rt/host_macos/reactor.saw:85`) and the poll writes the latch through it.
  Nothing ever DE-registers. A park loop that exits WITHOUT its event firing —
  the cancellation path, `std/net.saw:438` `if cancelled() { ... }` at the loop
  top — therefore leaves the kevent armed. Normally that is harmless because the
  task's own `TcpStream` deinits at completion and closing the fd drops the
  kevent with it. It is NOT harmless when the fd OUTLIVES the frame, which
  happens when the task returns its stream as its RESULT: the fd stays open, the
  kevent stays armed, and the next readiness event writes into memory the frame
  used to occupy.
  This is pre-existing (design 91), not introduced here, but design 134 narrows
  the safe window: the frame box used to live until group teardown, and now it is
  released at task completion. Exposure is narrow — it needs cancel-while-parked
  AND the fd escaping through the result — and the write is a single word into a
  freed block, so it is silent rather than crashing (the repro below runs clean;
  that is not evidence of safety).
  The fix belongs to the runtime ABI, not to the slot lifecycle: a
  `__saw_rt_reactor_unregister(r, fd, dir)` seam the frame's `__release` calls
  for any fd it armed and did not consume. rt/ABI.md freezes the seam set, so
  adding one is a user decision — hence stopped here rather than patched.
  Repro (`.build/scratch/probe_stale_token.saw`, gitignored; inlined):
  ```saw
  func reader(s: TcpStream) -> TcpStream {
      match s.read() {            // parks, armed EV_ONESHOT on s.fd
          case Ok(_) -> print("reader-read"),
          case Err(_) -> print("reader-cancelled")
      }
      return move s               // the fd leaves with the RESULT, kevent armed
  }
  func canceller(addr: Int) unsafe { let p = addr as UnsafePointer<Bool>  p[0] = true }
  func writer(s: TcpStream) { try! s.write("hello") }
  func run() {
      let (a, b) = TcpStream.pair()
      var group = TaskGroup()
      let hr = group.spawn(reader(move a))
      let addr = hr.cancel_addr()
      let _ = group.spawn(canceller(addr))
      var back = hr.join()        // frame box freed here; token still armed
      // ... churn the group so new frames reuse that memory ...
      let w = group.spawn(writer(move b))   // makes the old fd readable
      w.join()                              // stale kevent fires -> latch write
      let _ = move back
  }
  ```

## Design 116 — DF-findings (self-hosting lexer pilot, IN PROGRESS)
The lexer port (`selfhost/lexer`) is the pilot's measurement instrument;
language pain hit while writing it is the explicit product. Policy (user, Aug 4):
NO workarounds — an unambiguous compiler bug STOPS the affected unit + is
recorded here; a limitation is recorded with the wanted spelling. Repros are
inlined (the `.build/scratch` probes are gitignored).

- **DF-116a — FIXED (lead, Aug 4, same-day).** Root cause:
  `_needs_copy_for_struct_init` (codegen/resources.py) gated copy-on-init on
  the field type's LEAF conformance being ImplicitCopy, so an owning AGGREGATE
  with no whole-type copy() (`Optional<String>`, owning tuples/structs/enums)
  fell through to a bitwise copy with no payload retain. Fix: the gate now also
  fires when `_needs_cleanup(field_type)` (excluding NoCopy — typechecker-gated
  to `move` anyway); `_generate_copy` already dispatched such aggregates to the
  design-65 `_deep_copy_value` retain path. Regression test
  examples/optional_field_store_retain.saw covers the struct-field shape, the
  bare `v.push(opt)` call-path shape, and local-still-valid-after-copy. Suite
  999 green, bootstrap ok. FOLLOW-UP DONE (design 119 Part D, Aug 4): the
  `suffix` field is restored on selfhost/lexer's `Token` (populated from
  `try_read_int_suffix`, None elsewhere) and the canonical dump's 4th column is
  emitted by BOTH dumpers (tools/dump_tokens.py + `format_token` in lib.saw) —
  `255u8` dumps `INT<TAB>1:1<TAB>255<TAB>u8`; README format section updated;
  `make lexdiff` re-swept 0 mismatches; tests/literals.saw asserts the suffix
  column. Original finding follows:
  **MISCOMPILE (headline): an `Optional<String>` held in a named
  local loses its payload when copied into a struct field whose struct is pushed
  into a `Vector`.** The stored copy is not retained; the local's end-of-scope
  release then frees the buffer → the Vector element reads empty/garbage (often
  aliasing a later allocation). A PLAIN `String` local in the same position is
  fine, and an INLINE `sb.build()` (fresh temp) is fine — the bug is specific to
  an `Optional`-of-ImplicitCopy value that is (a) a named local and (b) copied
  (not moved) into the aggregate. Minimal repro:
  ```saw
  struct Tok { value: String, suffix: String? }
  func lexy() -> Vector<Tok> {
      var v = Vector<Tok>()
      var sb = StringBuilder(); sb.append("u8")
      let opt: String? = sb.build()          // Optional<String> local
      v.push(Tok(value: "x", suffix: opt))    // copied into a struct-in-Vector
      move v
  }
  func main() -> Int {
      let toks = lexy()
      if let b = toks.get(0) { if let s = b.suffix { print("suffix=[{s}]") } }
      0                                        // prints "suffix=[]" (should be [u8])
  }
  ```
  Contrast (both correct): `let plain: String = sb.build(); Tok(value: plain,...)`
  works; `Tok(value: "x", suffix: sb.build())` (inline, moved) works. Likely the
  copy-into-aggregate path for an `Optional<ImplicitCopy>` field emits a bitwise
  copy without the payload retain (compare the design-67 read-out-of-container
  double-free class). IMPACT ON THE PILOT: this is exactly the shape of the
  integer-literal-suffix path (`let suffix = self.try_read_int_suffix()` → stored
  in the `Token`). Per the no-workaround policy the suffix-in-the-token unit is
  STOPPED: the Saw `Token` omits the `suffix` field and the canonical dump omits
  the 4th suffix column (both dumpers), so suffixed literals are still lexed as a
  single INT token with the correct boundary/value and range-checked, but the
  suffix attribute is not surfaced until this is fixed. Token positions/kinds/
  boundaries (the lexer's core) are unaffected.

- **DF-116b — CLOSED (design 119 Part A, Aug 4).** Added the checked unsigned
  parse `String.to_uint() -> UInt?` / `to_uint(radix: Int) -> UInt?`
  (sawc/std/string.saw): whole-string, no-trimming, panic-free, overflow past
  `UInt.max` → `None`, detected with wrapping arithmetic + divide-back (multiply)
  and carry (add) checks — the unsigned mirror of the existing `_parse_int`. The
  integer bounds the WANTED note asked for already exist as compiler builtins
  (`UInt.max`, `Int8.max` … `UInt64.max`, design 53); no new bounds surface was
  needed. selfhost/lexer's `literal_fits` now parses with `to_uint(base)` and
  compares against the width's unsigned max — the digit-count + lexicographic
  `fits_u64`/`capped_fits`/`str_greater`/`strip_leading_zeros` workaround is
  deleted. Landing this required fixing an unrelated codegen bug (unsigned `<`/
  `>`/`<=`/`>=` used `icmp_signed`; see DF-119 below). Tests:
  examples/int_parse_to_uint.saw (radixes 2/8/10/16, the u64 ceiling + overflow,
  rejections) and the lexer's tests/literals.saw + `make lexdiff` (0 mismatches).
  Original finding follows:
  **no bignum and no checked integer parse forces digit-string
  magnitude comparison for literal range checks.** `sawc/lexer.py` computes
  `int(digit_str, base)` (arbitrary precision) and compares to `2**64-1` /
  `2**width-1`. Saw `Int`/`UInt` are 64-bit and arithmetic PANICS on overflow, so
  the widest legal literal (`UInt64.max == 2**64-1`) cannot be accumulated to be
  compared. The port instead range-checks by digit COUNT + an equal-length
  lexicographic compare at the boundary (and a capped accumulation for the small
  8/16/32-bit widths). WANTED: a checked/overflow-returning parse in std, e.g.
  `UInt64.parse(s: String, radix: Int) -> UInt64?` (None on overflow) or checked
  arithmetic (`a.checked_mul(b) -> Int?`), plus a `UInt.max` constant. Non-
  blocking (the magnitude approach is correct), but it is a hand-roll the obvious
  spelling can't replace.

- **DF-116c — CLOSED (design 119 Part B, Aug 4).** Added
  `StringBuilder.append_scalar(scalar: Int) -> Int?` (sawc/std/stringbuilder.saw):
  UTF-8-encodes one Unicode scalar and appends it, returning the byte count
  (1..4); an invalid scalar (negative, surrogate 0xD800..0xDFFF, or > 0x10FFFF)
  returns None and appends nothing (never a silent drop — the failure surface is
  an Optional per the never-hide-errors rule; the byte count is the Some payload).
  It is the encoding inverse of chars(), so an encode/decode round-trip is the
  identity on valid scalars. selfhost/lexer's hand-rolled `encode_utf8` is deleted
  in favor of it. Docs: LANGUAGE_SPEC String section + saw-lang skill. Test:
  examples/string_append_scalar.saw (the length-transition boundaries 0x7F/0x80/
  0x7FF/0x800/0xFFFF/0x10000/0x10FFFF via round-trip + byte count, plus the
  invalid cases). Original finding follows:
  **no scalar→UTF-8 / `StringBuilder.append_scalar` affordance.**
  `String.chars()` DECODES UTF-8 to `Int` scalars, but there is no inverse:
  nothing appends a Unicode scalar (an `Int` code point) to a `StringBuilder` or
  builds a String from one. A `\u{...}` escape whose scalar is >= 0x80 therefore
  needs a hand-rolled UTF-8 encoder in the lexer (`encode_utf8` in lib.saw).
  WANTED: `sb.append_scalar(cp: Int)` (or `String.from_scalar(cp) -> String?`,
  None on an invalid scalar) as the mirror of `chars()`. Non-blocking (encoding a
  code point is arguably lexer work), but the asymmetry is a real std gap the
  pilot surfaces.

- **DF-116d — CLOSED (design 119 Part C, Aug 4).** Both lexers now track the
  first interpolation-open `{` position in a string literal and, when the string
  fails to terminate (the interpolation runs to EOF, or a later `}` was consumed
  as its close and the string then runs off the end), report AT that brace —
  "unterminated interpolation in string literal, opened at this `{` (write `\{`
  for a literal brace)" — instead of "Unterminated string" at EOF. Landed in
  sawc/lexer.py AND selfhost/lexer/src/lib.saw in one commit (error positions are
  the lexdiff parity contract). Error positions match byte-for-byte; `make
  lexdiff` stays at 0 mismatches. Tests: selfhost/lexer/tests/errors.saw (the
  brace-position case), examples/lexer_unterminated_interpolation.saw (the
  compiler-level message). Original finding follows:
  **diagnostic quality: an unbalanced interpolation `{` in a string
  literal reports "Unterminated string" at EOF, not at the offending brace.**
  Writing `"...{..."` (a stray `{`, meaning interpolation, with no matching `}`)
  makes the lexer consume the rest of the file — the error surfaces as
  `Lexer error at <lastline+1>:1: Unterminated string`, pointing at EOF with no
  hint of where the `{` was. Hit while writing an error-message string literal
  that contained a bare `{`. (A literal brace is spelled `\{`, which works
  correctly and does NOT leak the internal 0x01 marker into the runtime string —
  verified. So this is purely a diagnostic-locality nit, not a correctness bug.)
  WANTED: track the interpolation-open position and report there ("unterminated
  interpolation, opened at L:C").

- **DF-116e — FIXED (lead, Aug 4, same-day):** sawc/lexer.py now captures
  `start_line` before `read_string()` and stamps the STRING/INTERP_STRING
  token with it (probe: a multi-line interpolated string dumps at its start
  line; lexdiff parity with the Saw port holds, 0 mismatches). Original
  finding follows:
  **sawc/lexer.py BUG (spec-vs-implementation disagreement): a
  MULTI-LINE string token gets the END line with the START column.** In
  `Lexer.tokenize` the `"` arm captures `start_col` BEFORE `read_string()` but
  builds the token with `self.line` AFTER it — and `read_string`/the
  interpolation copy advance `self.line` over every newline they consume. So a
  string literal that spans lines (a literal newline in the content, or a
  multi-line interpolation) is emitted at `(end_line, start_col)` — an
  inconsistent position. Minimal repro (`a` / `"{` / `}"` / `b` on four lines):
  the Python lexer reports the INTERP_STRING at `3:1`; the `"` is on line 2. The
  spec (LANGUAGE_SPEC.md: "`#line` → the 1-based line of the token") makes a
  token's line its START, so the Saw port uses the start line (`2:1`) — it is
  CORRECT where Python is buggy. Per the brief this is flagged rather than
  silently matched: the port does NOT reproduce the bug. The whole tracked corpus
  (1109 files) has zero multi-line string literals, so lexdiff stays green; the
  disagreement only manifests on a constructed multi-line string. FIX (in sawc):
  use the pre-read line for the string token (capture `start_line` alongside
  `start_col`). Until then the two lexers differ on this one rare construct by
  design.

## Design 123 — DF-findings

- **DF-123a — FIXED (design 132 unit B, Aug 5).** Both halves the finding asked
  for. (1) `calls.py::_generate_static_method_call` now substitutes the written
  type arguments against `type_param_context` before
  `_ensure_monomorphized_struct`, exactly as the constructor path
  (`structs.py::_generate_struct_init`) always did — which is the whole reason
  `Holder<T>(v: v)` survived where `Holder<T>.make(...)` did not. (2)
  `types.py::_get_llvm_type` now REFUSES a self-mapping type-param binding
  (`T -> T`) with a named error instead of recursing: an unsubstituted parameter
  reaching codegen is a bounded, diagnosable failure of the one construct at
  fault rather than `maximum recursion depth exceeded` failing the entire
  compilation unit. Test `examples/generic_static_call_own_type_params.saw`
  covers the static call from an instance method and from another static method,
  two instantiations of the same struct, a two-parameter struct, and a static
  call that flips its parameters. Original finding follows. Writing
  `Vector<T, A>.try_with_capacity(n)` inside a `Vector<T, A>` extension body
  compiles to `internal compiler error: maximum recursion depth exceeded` and
  takes the WHOLE compilation unit with it: because std is merged in, every
  program in the suite then fails to compile, including `hello.saw`. The
  constructor spelling of the same thing (`Vector<T, A>(capacity: n)`, used by
  `copy`/`map` for years) is fine — only the STATIC-METHOD path is affected.
  Minimal repro (`.build/scratch/probe_static_self.saw`):
  ```saw
  struct Holder<T> { v: T }
  extension Holder<T> {
      public func make(v: T) -> Holder<T> { Holder<T>(v: v) }
      public func remake(&self) -> Holder<T> { Holder<T>.make(self.v) }  // ICE
  }
  func main() { let h = Holder<Int>.make(3)  print(h.remake().v) }
  ```
  Diagnosis from the traceback: `calls.py::_generate_static_method_call` calls
  `generics.py::_ensure_monomorphized_struct("Holder", [T])` with the type
  ARGUMENT still being the type PARAMETER `T`, and `types.py::_get_llvm_type`
  line 136 resolves `T` through `self.type_param_context["T"]`, which maps `T` to
  itself — an unbounded self-recursion. The constructor path never reaches
  `_ensure_monomorphized_struct` with an unsubstituted parameter, which is why it
  survives. Two things to fix: substitute through `type_param_context` before
  monomorphizing, and give `_get_llvm_type` a self-mapping guard so any future
  variant is a clean error rather than an ICE that fails every compilation.
  design 123 did NOT code around this — `Vector.try_copy` reserves through the
  instance method `try_reserve` instead, which is the better implementation
  anyway (one allocation, no intermediate) and never needed the static spelling.

- **DF-123b — FIXED (design 132 unit C, Aug 5): it COMPILES, rather than being
  rejected.** USER DECISION (Aug 5) on the brief's either/or, and the rule it
  sets: **syntactic Void errors, instantiated Void compiles.** A `Void` you can
  SEE in the source is a visible mistake and stays the design-122 D3 error; a
  `Void` that arrives by INSTANTIATION is a legitimate use and becomes a
  zero-sized binding — no storage, and reading the name yields no value. The
  point is that generic code stays INSTANTIATION-UNIFORM: a body that
  type-checks generically compiles for every instantiation, so no call site ever
  produces a post-monomorphization error at a distance from the definition. This
  is how a unit type binds in Rust and Swift, and it is what unblocks the
  `lock<R>` shape M1 wants. Three changes, all in codegen. (1)
  `statements.py::_generate_let_statement` skips the alloca when the value's
  LLVM type is void and records the name in the new `void_variables` set, which
  `core.py::visit_Identifier` reads back as no value (the block-tail and return
  paths already treat a valueless result as `ret void`). (2)
  `methods.py::_generate_function` decides void-vs-value from the EMITTED
  signature rather than `func.return_type`: for a generic instantiation the
  declared type is still the type PARAMETER, so an `R = Void` free function took
  the value branch and asserted building an `undef` of void. The generic METHOD
  path (`generics.py`) already substituted its return type and needed nothing.
  (3) A `Void`-instantiated local that the coroutine transform gives a frame
  field hit two more `{i1, void}` producers, both fixed at the source: the None
  literal now lowers the OPTIONAL type through `_get_llvm_type` instead of
  assembling `{i1, payload}` around it, so design 111's `Void?` i8-placeholder
  rule applies; and `_wrap_in_optional` sets the is_some flag and stops when the
  payload is void, since there is no payload to insert.
  The typechecker is untouched — the design-122 error for a CONCRETE
  `let n = <Void expr>` still stands; only the per-instantiation case, which the
  abstract body check cannot see, now lowers. Test
  `examples/generic_local_at_void.saw`: a generic method at `R = Void` and at
  `R = Int`, statements on both sides of the void binding, an inferred `R`, a
  free generic function whose void-valued local is read twice, a NoCopy guard
  whose deinit runs between the binding and the tail read at BOTH instantiations
  (the `lock<R>` shape), and the same binding inside a SUSPENDING body spawned
  into a TaskGroup. `examples/errors/let_void_expression_rejected.saw` keeps
  asserting the syntactic half. The decision line is recorded in LANGUAGE_SPEC
  beside the design-122 statement rules and in the saw-lang skill. design 133's
  `lock<R>` is NOT rewritten here — this only proves the shape compiles.
  Original finding follows.
  `Mutex.lock<R>`'s natural body binds the closure result so the unlock can
  run before the return:
  ```saw
  public func lock<R>(&self, body: (&var T) sync -> R) -> R {
      pthread_mutex_lock(block)
      let result = body(payload_ptr)     // R = Void -> ICE
      pthread_mutex_unlock(block)
      result
  }
  ```
  At `R = Void` — a critical section that computes nothing, i.e. the common case
  — codegen reaches `statements.py::_generate_let_statement` ->
  `_entry_alloca(VoidType)` and llvmlite asserts, surfacing as
  `internal compiler error:` with an EMPTY message. The typechecker accepts the
  body (R is a type parameter there), so nothing catches it earlier.
  `Vector.with_ref<R>`/`with_var_ref<R>` survive only because their `body(...)`
  call is in tail position with no binding. Two things to fix: a `let` bound to a
  `Void`-instantiated generic should be the same clean design-122 error a
  concrete `let n = <Void expr>` already gets, and codegen should not build an
  alloca for a zero-sized/void local.

- **DF-123c — FIXED (design 133 unit A, Aug 5).** `_generate_arc_forward_call`
  and `_generate_box_forward_call` share `_forward_target_symbol`, which
  substitutes the resolved method type args against the active monomorphization
  context, requests the monomorph through `_ensure_monomorphized_generic_method`,
  and composes the symbol from them — what the ordinary method-call path already
  did. `Mutex.lock<R>` shipped on top of it (M1). The finding named a second
  cause that was not real: `_resolve_arc_forward` does not need to solve
  method-level type args itself, because it returns the payload method and its
  struct substitution to the SHARED downstream, which runs the design-93/105
  inference and the bound checks for the forward site as for any other call.
  Verified across inferred and explicit type args, generic and non-generic
  payload structs, both wrappers, and a forward whose method type argument is the
  enclosing generic's own parameter (`examples/arc_forward_generic_method.saw`).
  Original finding follows: **`Arc<T>` payload-method forwarding cannot
  reach a METHOD-GENERIC payload method (found by design 123 unit G, Aug 5).** Making `Mutex.lock`
  generic over the closure's result (review M1, "you cannot compute a value under
  the lock") is a one-line signature change that compiles fine on its own and
  then breaks every `Arc<Mutex<T>>` user with
  `internal compiler error: 'Mutex$1$Int_lock'`. Cause:
  `calls.py::_generate_arc_forward_call` mangles the payload method with
  `_mangle_method_name(base, name)`, the NON-generic form, so it looks up a
  symbol the method-generic monomorphizer never emits (`..._lock$1$Void` etc.);
  the typechecker's `_resolve_arc_forward` likewise does not solve method-level
  type arguments at a forward site. Reproduced by `examples/mutex_counter.saw`,
  `task_join_on_deinit.saw` and `net_budget_fairness.saw`, all of which lock
  through an `Arc<Mutex<Int>>`.
  design 123 did NOT code around this: `lock` KEEPS its `Bool` result and the
  brief's actual non-negotiable is met a different way — the `false` collision is
  gone because the INERT mutex that produced the second meaning cannot be
  constructed any more (`Mutex(value:)` panics). **M1 stays open and is blocked
  on this**: forwarding needs to solve and monomorphize method-level type args
  before `lock<R>` (or any other generic payload method) can ship.

## Design 122 — DF-findings

- **DF-122a — FIXED (design 132 unit A, Aug 5), closing RS-5's fourth hole.**
  The write is now a compile error: `cannot assign to `n`: it is captured by
  value, so the write would be discarded when the closure returns`, hinting
  `[&var n]` and `Arc<Mutex<T>>`. The checker keeps a stack of the scopes closure
  bodies open (`TypeChecker._closure_scopes`); an assignment target whose ROOT
  binding resolves past the innermost entry arrived by value capture, and
  `_capture_write_root` (typechecker/statements.py) reports it from both
  `_check_assign_statement` and `_check_compound_assign_statement`. Three things
  it deliberately does NOT flag, because each write reaches real storage: a
  borrow capture (defined right in the closure scope, so it never resolves past
  the boundary), a capture whose TYPE is already a reference (the env copies the
  pointer), and an index into a heap-backed container (`v[i] = x` on a captured
  `Vector` shares the buffer). It DOES cover the in-storage path — `x = v`,
  `x += v`, `x.f = v`, `x.0 = v`, a fixed-array element — which matters beyond
  the lost write: `x.f = v` on a captured struct also drops the OLD field value
  the env copy still points at, i.e. a double free. Blast radius was zero as
  measured: the suite, blade, libs and SOS all stayed green with no source edit.
  Riders: a REJECTED `[&var x]` borrow capture now still binds the name (error
  recovery), so the borrow diagnostic stays the only complaint instead of being
  buried under one capture-write error per mutation. Tests
  `examples/errors/capture_assign_escaping.saw` (the `make_counter` shape),
  `examples/errors/capture_assign_non_escaping.saw` (the `each3` shape plus
  `+=`), `examples/capture_write_allowed_forms.saw` (the forms that still work).
  A future opt-in `[box n]` capture mode stays open as a separate brief.
  Original finding follows:
  **(design 122 unit D4, Aug 4.)**
  Mutating a BY-VALUE closure capture is accepted and silently does nothing
  observable. The brief's D4 said fix it if it is a contained codegen bug and
  STOP if it opens a semantics question. It opens one; the diagnosis:

  **Model.** `codegen/closures.py::_generate_closure` builds an *env of values*
  for every capture mode except `ref`/`ref_var`. At closure-body entry each such
  capture is LOADED out of the env into a fresh local alloca
  (`cap_value = load(field_ptr); alloca; store`), and the name is bound to that
  alloca. So every write inside the body hits a PER-CALL copy that is discarded
  when the call returns; the env field is never written back. Two consequences,
  both silent:
  ```saw
  func make_counter() -> () -> Int {
      var n = 0
      { n = n + 1
        n = n + 10
        n }                  // escaping closure, plain capture of `n`
  }
  // c() three times -> 11, 11, 11   (mutation visible WITHIN a call, lost after)

  func each3(body: (Int) -> Bool) { body(1) body(2) body(3) }
  var sum = 0
  each3({ n in sum = sum + n  true })
  print(sum)                 // 0 — the real `sum` never moves
  // `each3({ [&var sum] n in ... })` prints 6 — the borrow capture is correct
  ```

  **Why the named "contained codegen fix" is NOT available.** Binding the name
  straight to the env field (so writes persist) contradicts a RATIFIED property:
  LANGUAGE_SPEC.md (designs 71/73) states an escaping closure is `ImplicitCopy`
  over a refcounted env that "is immutable and shared … there is no observable
  mutation through a shared env, so the sharing is semantically invisible."
  Persisting writes makes `let g = f` (a refcount bump) share MUTABLE state, and
  an MT `TaskGroup`/`spawn` copy would share it across threads with no
  synchronization — the Send audit checks capture TYPES, not env aliasing. So
  "persist" is a new capture semantics (a boxed/shared capture mode + Send
  rules), not a bug fix.

  **The two candidate semantics.**
  1. REJECT (recommended): assigning to a by-value capture is a compile error
     pointing at `[&var x]` (non-escaping) or `Arc<Mutex<T>>` (escaping). This
     ENFORCES the immutable-env model the spec already ratifies rather than
     deciding anything new. **Measured blast radius: ZERO** — an instrumented
     build that flags assignment to a plain/move/copy capture reports no hit in
     the 1041-test suite, blade + libs/toml + libs/semver, the selfhost lexer, or
     the SOS kernel. Cost: the counter-closure idiom stays unwritable without an
     `Arc<Mutex<Int>>` (and `Box` has no mutable access path today — stdlib M2).
  2. PERSIST via a new capture mode (e.g. `[box n]`): a per-closure mutable cell
     in the env. Needs a Send story for copies and an answer for what two copies
     of one closure observe. A design brief, not a fix.
  Whichever is chosen, the current behavior (accept the write, discard it) is the
  one option the reviewer called "the worst of the three".

## Design 119 — DF-findings (lexer-pilot follow-ups)

- **DF-119a — FIXED (design 119 Part A, Aug 4).** Unsigned integer relational
  comparisons (`<` `>` `<=` `>=`) lowered with `icmp_signed`, so a `UInt` with
  the high bit set read as negative: `UInt.max > 1` was `false`, and any
  magnitude check against a `UInt` bound was wrong above `2^63`. codegen bug in
  `_generate_binary_op` (codegen/operators.py): the integer-compare path always
  used `icmp_signed`. Fix: split on operand signedness via `_int_is_signed`
  (`icmp_unsigned` for the `UINT*` kinds), mirroring the udiv/sdiv split already
  present for `/` and `%`; `Int` and raw pointers stay signed. Test
  examples/int_parse_unsigned_compare.saw. (Blocker for Part A — the ported
  lexer's `literal_fits` and `to_uint`'s overflow check both need unsigned
  compares. Note for integration: this touches codegen/operators.py, which
  overlaps design 120's declared area; the change is a single call site.)

- **DF-119b — FIXED (design 122 unit G, Aug 4).** `print` now selects its
  formatter by the operand's KIND: codegen emits two width-parametric itoa
  bodies — `__saw_print_int` (unchanged) and `__saw_print_uint` (the same body
  with the sign logic dropped; the digit loop was already unsigned udiv/urem) —
  and the print call site (codegen/calls.py) picks the unsigned one for the
  `UINT*` kinds. The interpolation path (`_value_to_string`, codegen/core.py) was
  already correct (`%llu`), which is exactly why the two disagreed; the test
  asserts print, interpolation and `to_string()` agree. Signed printing is
  untouched, `Int.min` included. Test
  examples/print_unsigned_full_width.saw. Original finding follows:
  A
  full-width `UInt`/`UInt64` value with the high bit set (`>= 2^63`) misformats
  under `print` / string interpolation: `print(UInt.max)` emits `-1`, not
  `18446744073709551615`. `__saw_print_int` (codegen/core.py) formats every
  integer as SIGNED (`neg = icmp_signed('<', n, 0)` then a `-` prefix); the
  print/interpolation call site only zero-extends narrower-than-word unsigned
  values, so a same-width `UInt64` reaches the signed formatter unchanged. Values
  below `2^63` (incl. every narrower unsigned type after zext) print correctly,
  so this surfaced only now that `to_uint`/`UInt.max` make `2^63..2^64-1` values
  routine. Repro:
  ```saw
  func main() { print(UInt.max) }   // prints -1; want 18446744073709551615
  ```
  WANTED: an unsigned formatting path — either a second `__saw_print_int`-shaped
  runtime that skips the sign logic (magnitude = the value, unsigned udiv/urem
  digits) selected when the operand kind is one of the `UINT*` kinds, threaded
  through BOTH the `print` call site (codegen/calls.py) and the interpolation
  `_value_to_string` path (codegen/core.py). NOT fixed here: it lives in
  codegen/core.py + calls.py (design 120's concurrent area) and is orthogonal to
  the pilot (the lexer never prints a `UInt`; design 119's tests assert through
  comparisons). Non-blocking.

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

## Design 121 — DF-findings (doc comments + --emit-docs)

- **DF-121a — CLOSED by design 129 (Aug 5).** A call's argument list could not
  span lines: a newline anywhere inside the parentheses was a parse error, so a
  long call had to be split into extra bindings or run past any line-width
  convention. Hit while writing the `selfhost/lexer` doc-comment test (an
  `assert(cond, "message")` whose two arguments did not fit on one line). Repro,
  which now compiles and prints `3` (`examples/newline_wrapped_call.saw`):
  ```saw
  func add(a: Int, b: Int) -> Int { a + b }

  func main() {
      let x = add(
          a: 1,
          b: 2)
      print(x)
  }
  ```
  Design 129 took the question in one pass, as the finding asked: a parser-side
  bracket-depth discipline suppresses NEWLINE inside `(`/`[` and inside a
  COMMITTED generic `<...>`, `{}` stays newline-significant, a trailing comma is
  allowed in the `()`/`[]` forms and rejected in `<>`, and an unclosed bracket is
  reported at its opener. The lexer is untouched, so lexdiff parity with
  `selfhost/lexer` was never in play.

## Design 129 — DF-findings (newlines in brackets)

- **DF-129a — FIXED (design 132 unit D, Aug 5).** Same bug as DF-128d, found
  independently; see that entry for the fix. Original finding follows.
  `print(x)` where `x` is an Optional ICEs instead of producing the clean
  "not `Printable`" error that string interpolation of the same value gives.
  Reproduced identically on the pre-129 parser, so it is not a regression:
  ```saw
  func main() {
      let v: Vector<Int> = [1, 2, 3]
      print(v.get(0))            // v.get(i) returns `Int?`
  }
  // error: internal compiler error: Cannot print type: {i1, i64}
  ```
  Interpolating the same value is already clean — `"{v.get(0)}"` reports
  "cannot interpolate value of type `Int?` in a string: it is not `Printable`",
  with the `extension T?: Printable` hint. WANTED: the builtin `print` checks its
  argument for `Printable` the way interpolation does and reports the same
  anchored error. Easy for a user to hit, since `Vector.get` returning `T?` is
  the common source of a stray Optional. Not fixed inside design 129 — it is a
  typechecker/codegen issue with no bearing on the bracket rule, and the brief's
  gate battery was the priority. [needs a small brief or a fix-on-discovery pass]

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
- **Design 119 — lexer-pilot follow-ups (queued; dispatch AFTER 118
  integrates; user-authorized Aug 4).** Closes the remaining 116 findings:
  (A) radix-aware overflow-checked string->int parse unified with to_int() +
  integer min/max bounds (DF-116b); (B) StringBuilder.append_scalar UTF-8
  encoding (DF-116c); (C) unbalanced-interpolation-brace diagnostic at the
  brace, BOTH lexers same commit — error positions are lexdiff contract
  (DF-116d); (D) restore Token.suffix + the dump's 4th column in both dumpers
  (the DF-116a stopped unit; 116a itself fixed Aug 4). Brief:
  designs/119-lexer-pilot-followups.md. [119]
- **Design 121 — doc comments + --emit-docs. LANDED (Aug 4).** The sawlang.com
  pipeline foundation. Per-unit commits, full suite green each:
  (A) `///`/`//!` captured as TRIVIA in both lexers — the default token dump is
  byte-identical, a new `--docs` dump emits `DOC<TAB>line:col<TAB>kind<TAB>text`
  from `tools/dump_tokens.py --docs` and `sawlex --docs`, and `tools/lexdiff.py`
  runs both sweeps (`--mode tokens|docs|both`, default both);
  (B) parser attachment — a `doc` field on every documentable node,
  `Program.module_doc`, blocks keyed by the first real token after them (so a
  `public` prefix or `@export` line between changes nothing), and a clean
  "doc comment is not followed by a documentable declaration" for any block
  nobody claims;
  (C) `--emit-docs` / `--emit-docs-all` JSON (schema_version 1) from the checked
  program — rendered signatures off resolved types, conformances off the
  namespace, effect (suspending|sync) off the effect graph, self
  borrows/borrows-var/consumes + `&var` params; entry module plus every imported
  module, std included, so a driver file selects what to document. Members
  follow the design-80 gate; top-level items are not gated by the compiler so
  they are all listed with their declared visibility. Test runner gained
  `// EXPECT: docs` (golden: examples/doc_emit_json.saw);
  (D) std.task + std.time docstringed end to end.
  Brief: designs/121-doc-comments.md. NOT done here (out of scope, see the
  Milestones entry): the `sawdoc` HTML generator, the full std docstring pass,
  Markdown validation / doc-example testing, doc comments in blade/libs. [121]
- **Design 117 — runtime ABI v2 minimization. LANDED (Aug 4).** Errno
  accessors DELETED; the reactor is INSTANCE-based and relocated to Saw
  (DF-113d dissolved); the thread surface is spawn/join. Per-unit commits:
  thread_spawn/join; instance reactor (rt/host_*/reactor.saw kqueue/epoll,
  compiler `__saw_reactor` singleton getter injected at seam call sites);
  errno→SysError (net, then file/dir/env). Full suite 998 + bootstrap + sos
  green each. `sawc/rt/ABI.md` rewritten as v2 (minimization principle,
  SysError tag table, instance-reactor contract, v1→v2 deprecation table).
  - **SysError tag space (pinned, ABI.md):** 0=Ok, 1=WouldBlock, 2=InProgress,
    3=IsConnected, 4=Interrupted, 5=ConnReset, 6=ConnRefused, 7=ConnAborted,
    8=BrokenPipe, 9=NotConnected, 10=NotFound, 11=PermissionDenied, 12=Exists,
    13=AddrInUse, 14=Invalid, 15=Exhausted, 16=Other. A failing op returns the
    NEGATED tag (Linux `-errno` convention → 1:1 with the SOS (status,value)
    pair). The errno→tag mapping is the ONE host-divergent seam
    `__saw_rt_last_syserror()`; the status-carrying OS ops (tcp/fs/env) call it
    right after a failing syscall, so std never sees a raw errno.
  - **Pin deviation (recorded):** the brief's `Other(errno)` — preserve the raw
    hosted errno for diagnostics — is NOT done. A single negated-word return
    cannot carry a tag AND a raw errno, and SOS has no errno; `Other` is tagless
    and diagnostics come from mapping the common failure errnos to named tags.
    `__saw_rt_last_syserror` is a runtime-INTERNAL seam (common os_ops → host
    net_os), not a std-facing errno accessor, so the errno CHANNEL still dies.
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
- **Design 118 — the executor in Saw (queued; dispatch AFTER 117).** The last
  synthesized runtime layer (cooperative executor/scheduler, MT engine,
  offload parking) relocates to Saw consuming a `Reactor` trait (per-host
  kqueue/epoll types; future SOS-hosted impl over the Waiter) + minimal
  thread surface; compiler keeps frames + a small documented entry-point
  boundary. Staged (map/carve → ST core → reactor trait → threads/MT/
  offload), each stage suite-green, clean stop at a boundary acceptable.
  Resolves the deferred design-114 io_wait gating (white-box reactor tests
  become reactor-impl unit tests). Brief: designs/118-executor-in-saw.md.
  [118]
- **Design 113 — runtime extraction. IN PROGRESS (Aug 4).**
  - **LANDED — ABI freeze + rename (the time-critical, irreversible piece).**
    Both symbol tiers renamed to the uniform scheme: `__saw_rt_*` =
    runtime-implemented (reactor register/poll/wake, pthread create/join/
    mutex_init/cond_init, offload start/done/pipe_fd/take + blocking_sleep,
    clocks, sleep, errno family, set_nonblocking, sin_set_family, op-budget,
    alloc/dealloc/write/panic, get_argc/argv); `__saw_*` = compiler-internal
    (string, atomic, print_int — unchanged). Renamed across codegen, stdlib
    `.saw`, and the offload example tests; LLVM module id → `__saw_module`.
    Full suite green (993). The full symbol contract is documented in
    `sawc/rt/ABI.md` (reactor one-shot rearm, design-91 token = parked frame
    wake-word addr, design-102 cancel-wake, poll timeout, offload discipline,
    the four intended implementations). CLAUDE.md repo map updated.
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
- **Design 113b — runtime layer in Saw. LANDED (Aug 4)** except the reactor.
  Runtime-build mode (`--runtime-build`: reservation loosening for the exact
  frozen ABI set with a typo-checked valid-name error, seam-declaration
  suppression via the design-58 unify, sync-only via the `@export`-is-sync-
  context check, builtin-only load, internalize+globaldce) + error tests.
  Relocated to `sawc/rt/` (Saw) + `shim.c` (the 3 sanctioned DF bodies):
  alloc/dealloc/sleep/clocks, errno family, sin_set_family, op-budget, pthread
  mutex/cond/join, the blocking-extern offload (start/done/pipe_fd/take +
  blocking_sleep); shim.c holds write/panic (DF-113a), pthread_create + the
  offload thread thunk (DF-113b), set_nonblocking (DF-113c). rt build/cache/link
  machinery (`.build/rt/<hash>/`, flock-guarded, auto-linked, `-v` lists them,
  hard error on rt build failure). Freestanding negative test via a new
  `EXPECT: object` + `EXPECT-SYMBOL-UNDEFINED:` harness directive. Full suite
  (997) + bootstrap + sos green at every commit.
  - **The IO reactor — RELOCATED TO SAW by design 117 (Aug 4).** **DF-113d
    (per-call stack event buffer) is DISSOLVED, not fixed:** making the reactor
    INSTANCE-based (a `create`d instance owns its fd + wake pipe) let `poll`
    allocate its 64-element `kevent`/`epoll_event` buffer as a per-call HEAP
    `malloc`/`free` — which Saw CAN express — so `rt/host_*/reactor.saw` (kqueue/
    epoll) replaced the last synthesized seam. The heap alloc preserves v1's
    concurrent-poll independence exactly (each MT poller gets its own buffer, no
    shared buffer, no poll mutex). The array-repeat/uninitialized-local language
    nicety remains a future convenience but is no longer load-bearing. [113b/117]
- **Future designs — language gaps blocking a pure-Saw runtime** (each removes a
  113b shim body or unblocks the reactor when it lands): (1) extern C globals
  (`extern static stdout: ...`) — DF-113a, shrinks shim.c; (2) a bare C
  function-pointer type (closures are fat pointers; thread_spawn/offload thunk
  need thin ones) — DF-113b; (3) variadic extern declarations (fcntl-class arm64
  ABI requirement) — DF-113c. (DF-113d — the array-repeat/uninitialized-local
  poll-buffer gap — is no longer load-bearing: design 117 dissolved it with the
  instance reactor's per-call heap buffer; the language nicety is optional now.)
  General C-interop / low-level value beyond the runtime. [113/113b/117]
- ~~**DECIDED (user, Aug 7): a conditionless no-`break` `while { }` types as
  `Never`; the literal `while true { }` does NOT join it (the conditionless
  form is the blessed infinite idiom — constant-folding a `true` literal
  into typing is Rust's line too); the `NEVER` diagnostic spelling fixed in
  the same unit. Queued in the soundness/semantics batch.~~ **DONE (design
  177), exactly as decided.** Divergence is judged per loop off the loop's own
  break-tracking frame, so a `break` in a NESTED loop leaves the outer one
  diverging and a `return` is not a break. The three consequences are
  `panic(...)`'s, reused rather than reimplemented: a block whose last
  STATEMENT is such a loop types `Never`, a diverging loop is a valid `guard`
  exit, and codegen terminates the loop's predecessor-less exit block with
  `unreachable`. Two pre-existing `-> Never` bugs fell out and are fixed with
  it — a call to a `-> Never` function in VALUE position emitted its void
  result into the caller's `ret` and took the compiler down inside the LLVM IR
  parser, and `let x = panic("m")` crashed the pass on the None value. Tests:
  `while_never_diverges`, `while_never_break_forms`,
  `while_never_freestanding`, `while_never_sync_context`, and three error
  pins (`while_true_not_never`, `while_break_not_never`,
  `while_never_unreachable_after`). **Original:**
  `func f() -> Never` is satisfiable ONLY by ending in a Never-typed
  EXPRESSION (`panic(...)` / a Never call); a no-`break` infinite loop —
  `while { }` conditionless AND `while true { }` — is rejected with
  "should return `NEVER` but body has no value" (probe
  .build/scratch/probe_never_spin.saw). Bare-metal spin/WFI/hang idioms
  (design 112's exit_pass/exit_qemu, kernel idle loops) therefore cannot be
  typed honestly and fall back to Void + a comment. Proposed rule: a
  conditionless no-`break` `while { }` types as `Never` (Rust: `loop {}`
  is `!`); whether the literal `while true { }` joins it is part of the
  call. Rider: the diagnostic leaks the internal kind spelling `NEVER`
  (should say `Never`). [49, 58, 112]
- **Design 114 — intrinsic scoping + naming. Part A LANDED (Aug 4); Part B
  LANDED (Aug 4); io_wait gating DEFERRED (see FLAG).**
  - **Part A (yield_now) — LANDED.** `std/task.saw` gained a public
    `func yield_now()`; `import std.task` (already an import-required module —
    it owns `Task`) un-gates it. The bare `yield_now` name stays the
    compiler-recognized cooperative-yield intrinsic but is GATED: allowed only
    in std bodies (`_checking_builtins`), synthesized coro output,
    `--runtime-build` (no std loaded), or when `std.task` has been imported
    (name in `directly_accessible`). A bare un-imported call is a clean
    `UNDEFINED_FUNCTION` error naming the import.
    - **WRAPPER MECHANISM (decision recorded per brief):** chose the
      *intrinsic-preserving gate* (brief's fallback: "typechecker-recognizing
      the qualified name") over the *real suspending wrapper the embedding
      machinery drives* (brief's primary). Reason: the real-suspension effect
      LABEL and the coro-closure / main-suspend detection are recorded at the
      DIRECT call site under the ENTRY typechecker, which never analyzes std
      bodies (this is exactly why `_std_suspending_methods` has to be
      cross-carried for methods). Routing yield_now through a std free-function
      wrapper would drop the real-suspension signal at the entry boundary
      (main wouldn't auto-wrap; nested embedding wouldn't trigger). The gate
      keeps the user call site the exact same intrinsic node it is today, so
      lowering is byte-identical and every embedding position (statement,
      nested if/loop, MT TaskGroup, spawned+nested) works unchanged. The
      `public func yield_now()` body is a transparent `{ yield_now() }` — it
      exists solely as the importable name anchor (never actually called: the
      recognizer intercepts the call before function resolution).
    - Migration: 43 example files gained `import std.task`
      (`source_location_suspending` EXPECT-OUTPUT line numbers bumped +1).
      New negative test `examples/errors/yield_now_bare_gated.saw`.
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
  - **Part B (__saw_ rename) — LANDED.** See the Part B commit.
- **Design 115 — test runner: persistent compile workers. LANDED (Aug 4).**
  Amortize the measured ~250 ms/test fixed compiler-bootstrap overhead (python
  + llvmlite/sawc imports + builtin namespace) via N long-lived worker
  processes compiling in-process; binaries still run as isolated
  subprocesses; identical pass/fail/xfail set both modes (997 passed each).
  Merged-binary consolidation REJECTED (user, Aug 4) — breaks error tests,
  abort tests, per-test EXPECT/COMPILE-FLAGS, attribution. Builtin namespace
  built once/worker, deep-copied per compile (62 ms vs 147 ms rebuild). Pool
  is Process + Pipe (`connection.wait`), NOT `multiprocessing.Pool`, which
  needs POSIX named semaphores a locked-down sandbox refuses (`sem_open`
  EPERM). Error tests run in-process (reporter text has no isatty color
  gating → byte-identical to CLI capture). Old spawn-per-test path kept
  behind `--subprocess`.
  - **DF-115a — codegen relied on llvmlite's process-global context.**
    The re-entrancy audit found (and this design FIXED) two latent
    dependencies on `ir.context.global_context` that would also bite a future
    compile-server/LSP: (1) `ir.Module` defaults to the global context, whose
    `identified_types` registry persists across compiles → a 2nd in-process
    compile raised "`<Struct>` is already defined"; fixed by a fresh
    `ir.Context()` per `CodeGenerator`. (2) `ir.Type.get_abi_size/alignment`
    render a throwaway module in the global context, so once (1) moved a
    compile's identified types into a private context the size probe rendered
    an undefined-type reference; fixed by routing every ABI query through
    `_abi_size`/`_abi_align`, which pass `context=self.module.context`. The
    broader audit found NO other module-level mutable leaks (counters/caches
    are per-`CodeGenerator`; type-ids are a deterministic hash; llvmlite
    `initialize_*` is idempotent).

## Design 120 — suspension in expression position (LANDED, Aug 4)
Brief: designs/120-expression-suspension.md. A suspending call may now sit
anywhere an expression may. Stage 0 landed the known-unsupported matrix as XFAIL
tests first (`examples/expr_suspend_*`); every marker is flipped, zero XPASS, and
the carve-outs below are the only survivors.
- **Mechanism (coro_transform.py).** `_anf_hoist` rewrites a statement whose
  expression tree contains a suspension source into evaluation-ordered
  `let __anfN = …` temps, so each suspending call lands in a top-level statement
  the existing 96/101/104 embedding machinery drives unchanged. Sync code is
  untouched. `_lower_value_conditionals` runs first and turns a suspension-
  spanning CONDITIONAL construct into the branch shape (value `if`/`match`, `??`,
  `&&`/`||`, a `?.` chain, a chained assignment), so a conditional position keeps
  its short-circuit: an arm that is not taken never runs its suspension or its
  side effects.
- **Composition.** `_vc_head_hoist` lifts a conditional nested in another
  conditional's unconditionally-evaluated head (a `??` LHS, an `if` condition, a
  `match` scrutinee, an `&&`/`||` left operand) into its own statement first, and
  `_vc_chain_prefix_hoist` peels a multi-hop `?.` chain one hop at a time. Both
  exist because an `if let` nested inside an `if let` is a shape the state split
  cannot express; as statements they lower fine. `o?.susp() ?? -1` is the case
  that needs both.
- **Rides along.** Blocking `extern` calls (design 103) and cooperative
  `Channel.receive()` (design 62 G3) hoist for free — their statement-bound
  restriction existed for the same buried-suspension reason. Tests
  `expr_suspend_blocking`, `expr_suspend_channel_recv`.
- **Closes:** the design-104 buried-in-a-larger-expression rejection list, the
  design-111 suspending-hop/suspending-chain carve-out, and the
  suspension-mid-chain future-work item. `examples/errors/
  optional_chain_suspend_method.saw` moved to `examples/` as the positive case;
  `errors/coro_reject_anchored.saw` re-pointed at suspending recursion (the
  shape it asserted now compiles).
- **CARVE-OUT (recorded): multi-hop chained assignment with a suspending RHS.**
  `a?.b?.c = stream.read()` still rejects cleanly; the single-hop
  `a?.c = stream.read()` works. The lowering is a None-guarded
  read-modify-writeback of ONE payload (`var __wp = a!; __wp.c = rhs; a = __wp`);
  more than one hop needs the writeback nested per level. Wanted spelling: the
  multi-hop form lowering the same way. Workaround: `if let` the inner optional
  first. [120, 111]
- **DF-120a — ICE: spawn + join a task whose function returns an Optional.**
  PRE-EXISTING (reproduces at the design-118 tip, before any 120 commit), so it
  is recorded rather than fixed here. `internal compiler error: cannot store
  {i1, i64} to {i1, {i1, i64}}*` — an `Optional<T>`-typed value stored into a
  frame slot typed `Optional<Optional<T>>`. The optional-wrap-on-store heuristic
  in `_generate_assign_statement` (codegen/statements.py, the MemberAccess
  branch) wraps only when the VALUE is not already an optional, so a genuinely
  optional value going into an opt-encoded slot is stored raw. Repro:
  ```saw
  import std.task
  func run(n: Int) -> Int? { yield_now(); n }
  func main() {
      var g = TaskGroup()
      let h = g.spawn(run(5))
      print(h.join() ?? -1)     // ICE
  }
  ```
  `__saw_drive(run(5))` on the same function is fine; only the spawn/join path
  hits it. Wanted fix: compare the value's type against the slot's PAYLOAD type
  rather than asking whether the value is optional at all. [120, 52b]
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
- **LANDED (design 110): plain assignment through `&var` — unified permissive.**
  Whole-referent replacement `x = v` through a `&var T` function/method param and
  `self = v` in a `&var self` method are now legal (RHS `move` + `self = v` both
  in, per the Aug-3 scope call), matching closures and Swift `inout`: RHS takes
  the ordinary transfer checkpoint, old referent deinits once, new value installs,
  caller stays valid. Immutable `&T` assignment and `move` out of a ref stay
  banned (own diagnostics); a `&var any Trait` ERASED referent is excluded with a
  specific Box-level diagnostic; `&var Box<any Trait>` payload swap works; generic
  `&var T` works per instantiation (deinit-once verified). Rider fixed: a bare
  trait name behind a ref (`&Shape`/`&var Shape`) was an ICE, now a clean
  unsized-trait error naming `&any Shape`/`&var any Shape`. Spec/skill/README
  caveats reverted to the uniform rule. [110, 34, 88, 106]
- **LANDED (design 111): full optional chaining.** Brief at
  designs/111-optional-chaining.md. Swift-style `?.` reads (multi-hop
  `?.field`/`?.method()`, call-result heads, arbitrary length, one short-circuit
  skips the rest of the postfix chain INCLUDING skipped-call args, flattening
  never `U??`, final field must be copyable); chained assignment `x?.y = v` writes
  the payload field in place (RHS skipped on short-circuit, ordinary transfer +
  deinit-once of the old value, `Void?` result discardable / consumed via the
  `_`-blessed `if let`/`guard let`); a suspending hop or a suspending CHAIN was a
  clean buried-suspension error (CLOSED by design 120 — both now lower). Parser: OptionalEvalExpr +
  BindOptional spine, OptionalChainAssign. Codegen: address-based short-circuit
  walk reusing `_generate_method_call(receiver_ptr=…)`; `Void?` = `{i1, i8}`.
  Tests under examples/optional_chain_*, optional_binding_underscore, and
  examples/errors/optional_chain_*. Docs: spec Optionals + Argument Evaluation
  Order, skill, README, this digest.
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
- **Future work: suspension mid-chain — CLOSED by design 120 (Aug 4).** The
  compiler unchains the statement for you; a suspending hop inside a postfix or
  `?.` chain lowers. [111, 104, 120]
- **FLAG (minor, design 111 discovery): buried-suspend diagnostic wording —
  MOOT (Aug 4).** The message's "an `if let`/`guard let` body" clause no longer
  reaches the chain case: design 120 lowers suspending chains instead of
  rejecting them. The clause is accurate for the design-104 shapes that still
  reject. [111, 104, 101, 120]

## Design 109 — silently unchecked trait bounds for primitive type args (LANDED)
- **Root cause (typechecker + one namespace gap).** The free-function bound-check
  loop in `_check_function_call` (expressions.py) derived a `concrete_type_name`
  only for STRUCT/ENUM type args and special-cased Copy/Send/Sync/Equatable; a
  Comparable/Hashable/Printable/user-trait bound on a PRIMITIVE (or tuple/Optional/
  closure/existential — anything with no struct/enum name) fell through its final
  `elif concrete_type_name:` UNCHECKED, silently accepting an invalid program (both
  explicit and inferred args). The generic-METHOD path (`_check_type_param_bounds`)
  already routed every non-Copy bound through `_bound_satisfied` uniformly, so only
  the free-fn loop had the hole.
- **Fix 1 (the loop): an `else` safety net** — a type arg with no struct/enum name
  is routed through the SAME `_bound_satisfied`/conformance registry (the diagnostic
  is the design-93/105/108 "type `X` does not satisfy the `B` bound", anchored at the
  call, naming the INFERRED type for inferred args). Structural traits pass where the
  primitive structurally conforms; a user trait passes only via a registered
  `extension Int: T`.
- **Fix 2 (namespace): primitive → pseudo-struct conformance key.**
  `type_satisfies_bound` derived a conformance NAME only for STRUCT/ENUM/STRING, so
  `extension Int: Fooable` (keyed under `"Int"`, the same key trait-method dispatch
  uses) was invisible — a satisfied primitive user-trait bound would have FALSELY
  failed. Added `_PRIMITIVE_CONFORMANCE_KEYS` (INT→`"Int"`, FLOAT→`"Float"`; only
  these register as extensible pseudo-structs) so a primitive user-trait conformance
  is honored (fixes the method path's latent false-negative too).
- **Fix 3 (codegen, in scope for the satisfied-via-extension test): substitute the
  monomorphized receiver.** Calling a type-param trait method whose `T` resolves to a
  primitive (`run<Int>` with `extension Int: Fooable`) ICE'd ("Cannot determine struct
  type for method call") — in a mono'd generic body the receiver's stamped type is
  still the abstract `T`, so the design-57 primitive-pseudo-struct detection missed.
  `_generate_method_call` (calls.py) now substitutes `recv_saw` against the active
  `type_param_context` before naming the `Int`/`Float` pseudo-struct. Pre-existing
  (independent of the typecheck change), but blocked the required item-4 test, so
  fixed here to deliver it end-to-end (`run<Int>` / `run(5)` → 105).
- **AUDIT: ZERO latent violations.** The full suite + std + blade + libs were already
  clean of silently-accepted primitive user-trait bounds (mirrors the design 100/107
  sweeps) — no missing conformance to add, no bound to correct.
- Tests: `generic_primitive_bounds` (user trait satisfied via `extension Int/Float:
  Fooable`, explicit + INFERRED; prelude Comparable/Printable/Equatable over Int/
  Float/String; tuple arg via Equatable recursion), `errors/generic_primitive_bound_
  explicit` + `errors/generic_primitive_bound_inferred` (Int violates a user trait,
  explicit + inferred naming the inferred type), `errors/generic_tuple_bound_violation`
  (tuple type arg checked). Suite 964 (960 + 4), zero xfails; bootstrap ok (blade
  17+17, libs toml 4 + semver 4). Docs: NONE beyond this tracker — the RULE was always
  "bounds are checked"; this fixes the implementation to match (no user-visible rule
  statement changed). [109, 108, 93, 105, 57, 32, 48]

## Design 108 — ICE: generic parameter with a default VALUE (LANDED)
- **Root cause (codegen, post-typecheck).** `func f<T>(a: Int, b: T = 0)` called
  with the default OMITTED (`f<Int>(1)`, and after this fix also `f(1)`) emitted
  the LLVM call with too FEW args → llvmlite `IndexError: list index out of range`.
  A generic instantiation registers its defaults under the MANGLED name
  (`f$1$Int`), but the free-fn call-site default-fill keyed by the PLAIN name
  (`expr.name`), so the lookup missed and no default was materialized; a generic
  METHOD mono (`_declare_monomorphized_method`) never registered `method_defaults`
  at ALL. Both paths ICE'd. Fixes: calls.py keys the generic free-fn fill by the
  mangled instantiation name; generics.py registers `method_defaults` in
  `_declare_monomorphized_method`.
- **Semantics — DEFAULT-DRIVES-INFERENCE landed (the preferred branch, not the
  clean-error fallback).** `_solve_call_type_args` gained a default-driven phase
  (threaded a new `default_values` arg at the free-fn / method / design-105
  overload solve sites): an OMITTED default-valued parameter drives inference from
  the default's own type when the parameter is otherwise undetermined — `f(1)`
  infers `T = Int` from `b: T = 0`. Consulted only AFTER argument-driven solving
  (a supplied argument always wins — `f(1, 2.0)` infers `Float`), inside the
  inference snapshot (the default's moves/effects roll back — they already tainted
  the callee at its declaration).
- **Per-call default type check.** `_check_generic_call_defaults` validates each
  omitted default against the INSTANTIATED parameter type at every generic call
  (the design-53 declaration check runs against abstract `T` and is a no-op). A
  bare integer literal adopts an integer instantiation (range-checked) and is
  cleanly REJECTED against a non-integer one — `f<Float>(1)` with `b: T = 0` is a
  clean call-anchored error (bare `0` doesn't adopt `Float`), never an ICE. An
  inferred default that violates a bound (`b: T = Widget()` → `T = Widget`, not
  `Fooable`) is caught by the existing bound check naming the inferred type. Every
  failure mode is a clean anchored diagnostic; no path ICEs.
- **Design-105 overload sets compose.** A defaulted generic overload in a mixed
  set binds `g(1)` by filling `b` and infers its `T` from the default
  (`_try_infer_overload_candidate` now passes `default_values`); the concrete
  sibling `g("hi")` still wins by exact match.
- **FLAG (pre-existing, orthogonal — CLOSED by design 109).** A generic
  bound of a USER trait against a PRIMITIVE type argument was silently UNCHECKED —
  `func f<T: Fooable>(...)` accepts `f<Int>(1, 5)` even though `Int` has no `foo`.
  The bound-check loop in `_check_function_call` derives a `concrete_type_name`
  only for STRUCT/ENUM args (a primitive has none) and only special-cases
  Copy/Send/Sync/Equatable, so Comparable/Hashable/Printable/user-trait bounds on
  a primitive fall through unchecked. Affects EXPLICIT calls too (not a design-108
  regression; design 108's default-inference mirrors the explicit behavior
  consistently). The brief's "Int doesn't satisfy SomeTrait" bound test therefore
  uses a STRUCT default (`Widget`) to exercise the bound check that DOES fire. Fix
  is a route of the primitive case through `_bound_satisfied`/structural checks —
  broad, own change.
- Tests: `generic_default_value` (default used / overridden / explicit Int8
  adoption / generic method / defaulted generic overload in a design-105 set —
  output proves the default value flows), `errors/generic_default_value_float`
  (bare `0` vs `Float`), `errors/generic_default_value_bound` (inferred `Widget`
  default violates `Fooable`). Suite 960 (957 + 3), zero xfails; bootstrap ok
  (blade 17+17, libs toml 4 + semver 4). Docs: spec generics/inference paragraph +
  saw-lang skill inference bullet. [108, 93, 105, 53, 37, 55, 66]

## Design 107 — shadowing follow-ups: same-scope derived redefinition + for-loop vars (LANDED)
- **Item 1 (same-scope derived redefinition) — LANDED.** `var data = read();
  let data = parse(move data)` in ONE scope is now legal iff the initializer
  MENTIONS the binding being replaced (the design-100 mentions-rule extended from
  across-scope to same-scope); a non-deriving `let data = fresh()` after a
  `let data = …` stays the pre-existing DUPLICATE_VARIABLE error (message
  unchanged). let->let / var->var / let<->var all legal (new binding's mutability
  its own). Typechecker (statements.py `_check_let_statement`): the same-scope
  duplicate check is deferred until AFTER the initializer is checked, then gated on
  `_init_mentions_name`; a derived redefinition overwrites the scope entry directly
  (fresh VariableInfo id -> clean move state). Codegen: the old value drops AT the
  redefinition point — `_drop_redefined_same_scope` (resources.py) retires the old
  binding's innermost-scope cleanup entry and emits a flag-guarded drop (a
  `.copy()`-derived old value drops here; a `move`-derived one already cleared its
  flag -> no-op), extending design 100's captured-alloca cleanup to same-scope so
  there is no double-free. `_cleanup_scope`'s per-entry drop factored into
  `_emit_scope_var_drop` (shared). Tests: `shadow_redef_same_scope` (deinit oracle
  proves old drops at redefinition + new at scope exit, all mutability
  transitions, clean under libgmalloc), `errors/shadow_redef_nonderived`.
- **Item 2 (for-loop variables join the rule) — LANDED.** A for-loop var that
  shadows an enclosing binding is a rename error UNLESS the SEQUENCE (iterable)
  references the shadowed name (the initializer analog) — `for x in x.iter()` /
  `for i in 0..i` legal, `for x in ys` under an outer `x` an error; an enclosing
  LOOP VAR is an enclosing binding (nested inner same-name loop var non-derived =
  error). Typechecker: both `_check_for_loop` + `_check_for_loop_as_expression`
  call `_check_shadowing(variable, iterable, …)` with the loop scope active.
  Codegen (loops.py): the loop var is now shadow-safe — both generators snapshot
  the name->storage maps and `_restore_shadow_snapshot` after, so a derived
  `for x in x.iter()` no longer lets the post-loop `del` drop the OUTER binding's
  entry (the design-100 block-shadow hazard applied to loops); the outer binding
  (incl. an owning Vector, deinit-once) is restored + usable after the loop.
  Tuple-pattern loop bindings (`for (a,b) in pairs`) are NOT a parseable form (the
  parser binds a single IDENT) -> any tuple for-loop is a PARSE error before the
  shadow check, so the brief's "flat error" is satisfied at parse time (no for-loop
  pattern path to guard). Tests: `shadow_for_derived` (range + owning-Vector-iter +
  nested-loop-var, clean under libgmalloc), `errors/shadow_for_nonderived`,
  `errors/shadow_for_nested_loop` (exact positions), `errors/shadow_for_tuple_pattern`.
  Cross-cut: `shadow_redef_nested_owning` (a same-scope owning redefinition nested
  inside an across-scope derived shadow — the double-free hazard class — all three
  values deinit exactly once, clean under libgmalloc).
- **MIGRATION: ZERO** newly-illegal for-loop shadows across std + blade + libs +
  examples (the whole corpus was already clean — mirrors design 100's audit).
  Same-scope item only ADDS legality (no migration).
- **Both design-100 flags CLOSED:** (a) the headline `var data = read();
  let data = parse(move data)` now works in ONE scope; (b) for-loop iteration
  variables are covered by the rule.
- Suite 957 (950 + 7), zero xfails; bootstrap ok (blade 17+17, libs toml 4 +
  semver 4). Docs: spec bindings section + saw-lang skill (rule + gotcha). [107, 100, 42, 65, 99]

## Design 106 — reference forwarding: pass a received `&T`/`&var T` onward (LANDED)
- **Largely ALREADY WORKED; one real gap fixed + acceptance + tests + docs.** The
  design-96 flag (inside `f(r: &var Data)`, `g(&var r)` impossible → read_into
  routed through inlined helper bodies) was STALE: the design-56 `&var ref`
  re-borrow acceptance (`is_mut_ref_binding`, typechecker/expressions.py) + the
  codegen re-borrow (operators.py `_generate_reference_expr`: an Identifier bound
  to a REFERENCE type LOADs the held pointer, not `&alloca`) + design 88's
  frame-resident ref pointer already delivered forwarding end-to-end. VERIFIED at
  runtime across every brief shape: 1- and 2-level (f->g->h) for `&` and `&var`,
  mutation through a twice-forwarded `&var` visible at the root, `&var`->`&`
  downgrade, exclusivity-by-root-path (`&var r` + `&r` in one call → clean
  EXCLUSIVITY_VIOLATION at exact position via the Identifier-root access path), and
  a held ref forwarded ACROSS a suspend in a driven (nested-spawned) callee (value
  visible after resume). **PROJECTION-FORWARDING VERDICT: IN scope, works** —
  `g(&var self.field)` / deeper `&var self.a.b` fall straight out of the existing
  MemberAccess path machinery (`_build_access_path` / `_get_member_pointer`), no
  new code.
- **The ONE real gap (fixed): whole-`&var self` forwarding.** `g(&var self)` in a
  `&var self` method was rejected ("cannot take mutable reference to immutable
  `self`") — `self`'s VariableInfo is always registered `mutable=False`
  (self-mutability lives on `method.self_mutable`, not the binding), and the
  SelfExpr branch of `_check_reference_expr` only checked `self_info.mutable`. Fix:
  consult `self.current_method.self_mutable` — a `&var self` receiver is a mutable
  reference binding, so re-borrowing the whole self is sound (mirrors the `&var
  ref` param case); a `&self` method still cleanly rejects `&var self` (no upgrade).
- **Upgrade rejection message improved** (fix-on-discovery, clean-not-generic): an
  immutable reference param `r: &T` forwarded as `&var r` now gets a
  forwarding-specific diagnostic ("cannot forward `&` reference `r` as `&var`: a
  shared `&` reference cannot be upgraded to `&var`" + hint) instead of the
  misleading generic "declare with `var`" (the referent is not the caller's to
  re-var). Upgrade was already REJECTED; only the message was wrong.
- **ACCEPTANCE (design-96 flag CLOSED):** `std/net.saw` `read_into` re-simplified
  from the inlined-`net_read_once`-body workaround (manual scratch buffer alloc +
  `tcp_try_read` + `append_bytes` + free) to direct helper forwarding — the park
  loop now calls `net_read_once(self.fd, &var into)`, forwarding the held `&var
  into` onward across the internal io_wait park (net_read_once owns the scratch
  buffer + append). Same `while { … break }` shape as value `read()`; net_read_into
  + coro_spawn_nested_ref still green over real sockets.
- Tests: `ref_forwarding` (1-/2-level `&`+`&var`, twice-forwarded mutation,
  downgrade, whole-`self` + `self.field`/`self.a.b` projection), `ref_forwarding_
  suspend` (held ref forwarded across a suspend in a spawned worker's nested driven
  callee → 40), `errors/ref_forwarding_upgrade` (`&`-param → `&var`),
  `errors/ref_forwarding_self_upgrade` (`&self` method → `&var self`),
  `errors/ref_forwarding_exclusivity` (`&var r` + `&r` overlap), `ref_forwarding_
  suspend_nested` (forward a held ref INTO a suspending nested callee — the 106x88
  sub-frame ref-seeding path → 40). Suite 950 (944 + 6), zero xfails; bootstrap ok
  (blade 17+17, libs toml 4 + semver 4). [106, 96, 88, 56, 42, 34, 16]

## Design 104 — coro embedding: if-let/guard-let bodies + remaining generic shapes (IN PROGRESS)
- **Item 1 (suspending calls in `if let`/`guard let` bodies) — LANDED.** The
  design-101 clean-error residue: an optional-binding branch could not be CFG-split.
  Fix (coro_transform.py): `_mark_optional_binding_splits` (new prepare pre-pass,
  after the condition/try/match hoists) marks every `if let`/`guard let` whose body
  spans a suspension and renames its binding to a UNIQUE frame field (`__obN`),
  rewriting body uses — so design-100's `if let x = x` keeps inner `x: T` and outer
  `x: T?` in DISTINCT fields (a nested re-bind of the name, or a tuple pattern, is a
  clean anchored error, not a miscompile). `_collect_frame_locals` + `_collect_calls`
  gained IfLetExpr/GuardLetStatement branches (binding→frame field; recurse into the
  bodies so nested suspending calls embed). CFG split (`_split_if_let`/
  `_split_guard_let` via one `_optbind_dispatch`): emits the dispatch as an ordinary
  `if let` whose branches ONLY set `__state` (reuses codegen's has-value test+unwrap
  over `T?` — no synthesized Some/None match, which the parser rejects for `None`),
  stores the unwrapped binding into its frame field, then re-dispatches to the body
  states; guard-let's Some path flows to the continuation (the enclosing stmt loop
  lowers the rest into it), None path lowers the else-exit. IR-verified: nested
  `work()`/`s.read()` drive as `__Frame_*_resume`, zero plain `@work`/`@TcpStream_read`
  calls. Incidental: a statement-position blocking-extern (design 103) in a spanning
  if-let/guard body now offloads too (the branch is split). Tests: `net_iflet_guardlet_bodies`
  (socketpair recirc in an if-let then-body, a guard-let continuation, a guard-let
  else-body, and the `if let ok = ok` shadow — exact per-shape recirc counts); the
  two `errors/coro_suspending_method_in_{iflet,guardlet}_body` tests removed (shapes
  flipped ERROR→EMBED). Suite 940 (941 −2 err +1), bootstrap 17+17 + libs 4+4. [104, 101, 100, 84, 74]
- **Item 3 (struct-generic AND method-generic suspending methods) — LANDED.**
  `Dual<T> { func mix<U>(&var self, ...) }` where `mix` suspends was a clean design-74
  A5-rest error; now it drives. The `__drive` dispatcher routes a method that is BOTH
  struct-generic and method-generic to the generic-STRUCT path (was: any `inner.type_args`
  went to the method-only path, which has no template for a generic-struct method →
  the old rejection). `_drive_generic_struct_method` (expressions.py) resolves the
  method's OWN type args from the call, keys the mono by `mangle_named(method, struct_args
  + method_args)`, and threads `method_args` through `_effect_queue_generic_struct_method_mono`
  → `_build_generic_struct_method_mono` (effects.py), which now applies a COMBINED
  substitution (struct type params T→Int for `self`'s fields + the method's own
  params U→Bool for its params/locals) before + after the effect re-check.
  **Frame-key shape:** `_method_frame_key(struct, mangle_named(method, struct_args +
  method_args))` = `Dual_mix$2$<T>$<U>` — design 95's resolved-signature key extended
  with the method's type args. Test `coro_generic_struct_and_method` (2 struct × 2
  method = 4 distinct `__Frame_Dual_mix$2$*$*` frames, IR-verified; each combines a
  frame-resident `self.value.tag()` across a `yield_now` with the U arg → 11/12/21/22,
  so a collision would misprint); `errors/coro_generic_struct_and_method_generic_unsupported`
  removed. Suite 940, bootstrap 17+17 + libs 4+4. [104, 95, 74, 70]
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

## Design 105 — generic inference: overloads, later-arg solve, labeled args (LANDED)
- **Extends design 93 past its three explicit-args boundaries.** One feature
  commit + docs. Suite 944 (941 + 3), zero xfails; bootstrap ok (blade 17+17,
  libs toml 4 + semver 4). Bootstrap wall unchanged (baseline ~71.4s / 62.1 user;
  after ~71.1s / 61.9 user — within noise; generic overloaded calls are absent
  from the bootstrap corpus so the per-candidate sandbox adds ~0).
- **Overload sets.** `_resolve_overload` (all four callers: free/module fn +
  instance/static method) gained `expr`/`base_subst`. When no concrete (or
  explicit-type-arg generic) candidate matches, inference runs PER generic
  candidate via `_try_infer_overload_candidate` -> `_solve_call_type_args(...,
  silent=True, known_arg_types=...)` (each fully sandboxed; `known_arg_types`
  reuses the already-checked `_overload_arg_types` so no double `move`/effect —
  a failed candidate leaves ZERO residue). Exactly one solving-and-type-matching
  candidate is picked (solved args stamped on `expr.type_args`); >=2 -> clean
  ambiguity error listing candidates + solved type args (`<T=Int>`) + explicit-
  args/labels hint; 0 -> the existing no-match diagnostic. Concrete beats generic
  is untouched (design 55) — an inferred overload never changes a call that
  already resolved.
- **Later-arg solve.** `_solve_call_type_args` fixpoints over the arg list
  (bounded by param count): phase-1 non-closure args unify against `base_subst`
  ONLY (so a two-args-one-param conflict is still detected), phase-2 closures
  improve as `out` grows — a param gated by an arg to its RIGHT (incl. a closure
  before the value that fixes its `T`) now solves.
- **Labeled args.** `_infer_label_mapping` pairs args to params BY LABEL (design
  66 binding) before unifying; the per-candidate label FILTER also disambiguates
  a label-distinguished generic overload. NOTE: under Saw's trailing-defaults +
  forward-only-binding rules a *legal* labeled call cannot actually reorder a
  type-param-carrying argument, so the design-93 "mis-map" was latent-only; the
  mapping is threaded for the general model and for the overload type-match.
- **Codegen (the real enabler).** Two+ GENERIC overloads of one name previously
  collided (both -> `name$<args>`; the clean tree mis-resolved them even with
  EXPLICIT args — pre-existing, verified by probe). Registration now stamps each
  a distinct `$OL$` base (declared param-type sig; `$LB$` labels when they share
  a sig); codegen `generic_functions` + typechecker `_pristine_generics` + the
  call/spawn/`__drive` mono sites key by that base via `resolved_symbol`. A lone
  generic in a set keeps its plain name (byte-identical) -> inert for all existing
  code (no std/blade/libs set has 2+ generic overloads). Inferred args are marked
  `type_args_inferred` so a spawn/drive/coro RE-CHECK re-infers instead of
  mistaking the stamped args for an explicit-generic selection (`_has_explicit_
  type_args`). Inferred + explicit generic-overload args are now bound-checked.
- **FLAG (scoped limitation, clean not silent):** a driven/spawned generic
  *METHOD* OVERLOAD (2+ generic method overloads of one name, suspending) is NOT
  supported — only free-function generic overloads carry the per-overload codegen
  symbol; the coro/method-mono path still resolves a generic method template by
  `(struct, name)`. Free-fn generic overloads spawn/drive per resolved candidate
  (tested). Two generic overloads that BOTH solve at a call are an ambiguity
  error by design (give `<...>`).
- Tests: `infer_overload` (unique-solve generic-fallback + concrete; two-generic
  container-shape Wrap/Vector both instantiated; label-distinguished; later-arg
  closure-first; explicit selects the generic), `infer_overload_driven` (two
  suspending generic overloads spawned -> own bodies; a driven inferred generic),
  `errors/infer_overload_ambiguous`. Design-93 suite stays green. [105, 93, 55,
  66, 38, 95, 70, 74]

## Design 102 — runtime edge bugs: spawn-Void ICE + cancel wakes an io-parked task (LANDED)
- **Item 2 (cancel wakes an ALREADY-io-parked task — A3 remainder) — LANDED.** A task
  parked in `io_wait` on a permanently-idle fd, cancelled by a peer, never observed the
  cancel (the landed model only checked BEFORE parking; a blocked reactor poll never
  returned). FIX, layered + precise (no herd wake):
  1. Reactor self-wake pipe (portable self-pipe on kqueue/epoll; codegen/core.py):
     `saw_reactor_wake()` writes one byte to a process-global self-pipe whose read end
     `saw_reactor_poll` registers (one-shot, token 0 -> the latch loop skips it) each
     cycle and drains on return. `handle.cancel()` / `VoidTaskHandle.cancel()` call it,
     so a blocked poll returns promptly.
  2. Precise wake by cancel flag: a new `Resumable.__is_cancelled()` frame reader (reads
     `__cancel`); `__ambient_wake_io` + the MT worker wake scan now make an io-parked
     frame runnable when `__wake_reason() >= 0 OR __is_cancelled()` — so ONLY the
     reactor-latched frame(s) and the cancelled frame(s) wake; a non-cancelled sibling
     parked on another idle fd stays parked (net_precise_* unaffected).
  3. ST liveness for a `cancel_addr` peer cancel (which sets the flag WITHOUT a
     self-wake): `__ambient_run` scans (`__ambient_any_cancelled_io`) BEFORE blocking in
     poll and wakes a cancelled parked frame instead of polling an idle fd forever.
  4. Cancel propagation down the frame chain: the nested-sub-frame drive now copies the
     root's `__cancel` into the sub-frame each drive (mirroring the design-91 `__io_tok`
     propagation), so a `cancelled()` check INSIDE a nested `stream.read()` sub-frame
     observes a cancel set on the ROOT frame the handle points at. Without this the
     parked reader re-parked forever.
  5. net.saw: `read`/`read_into`/`write` (both overloads)/`connect` now re-check
     `cancelled()` at their park-loop top (accept already did) and return `Err(IoError)`.
  Tests (time-bounded; a hang -> runner failure): `net_cancel_parked_read` (ST parked
  reader peer-cancelled via cancel_addr; deinit-once oracle), `net_cancel_precise`
  (cancelled reader wakes while a sibling on another idle fd stays parked until its own
  data arrives -> `-1 2`), `net_cancel_parked_mt` (`TaskGroup(threads: 2)`, stable 5x).
  Closes the design-76 A3-remainder flag. Suite 937, bootstrap 17+17, libs 4+4. [76, 18, 90, 91, 89-b]
- **Item 1 (spawn-Void ICE — cooperative TaskGroup) — LANDED.** `group.spawn(void_body)`
  ICE'd: the frame correctly omits `__result` for a Void body (a `{..., void}` struct
  field is illegal LLVM), but the `__spawn_<f>` helper still built `__rp =
  &__fp[0].__result` and the handle was `TaskHandle<Void>` (join force-unwraps a
  zero-size `T?`). FIX (proper omission, no placeholder): a Void spawn now yields a
  dedicated non-generic `VoidTaskHandle` (cancel_ptr + group_ptr + slot, no
  result_ptr) whose `join()` drives to completion and returns Void; the spawn helper
  skips the `__rp` capture entirely for a Void frame. Typechecker `_check_taskgroup_spawn`
  returns `VoidTaskHandle` when the body is Void. SWEEP: `__drive_<f>` had the same
  hazard (read `__f.__result` unconditionally) — now returns Void with no result read
  for a Void driven body. The design-75 executor return-Int workaround is now DEAD and
  removed: `__tg_worker` returns `Void` (21b `spawn { void }` works since design 77) and
  `__drain_mt` holds `Vector<Task<Void>>`. Channels of Void are not a void-slot hazard
  (the type constructs; there's just no Void literal to `send` — a front-end value gap,
  orthogonal). Tests `taskgroup_spawn_void` (single- + multi-threaded, explicit-join +
  drop-drain, sum oracle 60), `coro_drive_void_body`. Closes the design-75 spawn-Void
  flag. Suite 934, bootstrap 17+17, libs 4+4. [75, 77, 21b]

## Design 103 — A6 runtime offload: `extern blocking` calls RUN in tasks (LANDED)
- **The last A6 half.** A blocking FFI call inside a suspending body (driven /
  spawned / a suspending `main`) no longer REJECTS — it OFFLOADS to a worker thread
  and PARKS on the job's pipe like any socket read, so siblings keep running while
  it blocks and the single cooperative reactor thread is never wedged. Closes the
  design-76 A6 remainder (thread-per-call v1 in place of the ledgered "pool").
- **Runtime shims** (`codegen/core.py _declare_io_runtime`, hosted-only weak seams).
  `saw_offload_start(fn, arg) -> job` mallocs a job record `{ fn, arg, result, done,
  pipe_r, pipe_w, thread }`, pipes it, and `pthread_create`s a worker running
  `__saw_offload_thread`: it calls the extern via the raw fnptr (`i64(i64)` thunk),
  stores the result, PUBLISHES `done` (atomic release), then writes one byte to the
  job's self-pipe. `saw_offload_done` (acquire-load the flag), `saw_offload_pipe_fd`
  (the readable fd), `saw_offload_take` (pthread_join = full barrier -> read result
  -> close pipe -> free). HAZARD discipline: the worker touches ONLY its own job +
  pipe write end; ALL wake routing stays in the reactor; the pipe byte + the join
  are the release/acquire boundary, so the result transfers single-owner with no
  data race (start owns -> thread fills -> take transfers). `saw_blocking_sleep(ms)
  -> ms` is the reference blocking primitive the tests drive via a `blocking func`.
- **Lowering** (`coro_transform.py`). A top-level blocking-extern call boundary
  (`let x = slow(arg)`, a bare/`let _` discard, or a design-83 tail `return
  slow(arg)`) is classified (`_classify_blk`) BEFORE frame layout and desugars in
  `_emit_blk_call` to `self.__blkjobN = __blk_start(slow(arg))` -> park loop
  `while __blk_done(job)==0 { saw_reactor_register(__blk_pipe_fd(job), read);
  suspend(IO_PARK) }` -> `<x> = __blk_take(job)`. `__blk_start` is a CODEGEN
  intrinsic (calls.py) that resolves the extern's `ir.Function` (a function address
  is not expressible in Saw) and bitcasts it to i64 + evaluates the Int arg; the
  three wrappers thin over the shims. The blocking-extern call is now a suspension
  point for `_spans_suspension` (its result local becomes frame-resident) and gets a
  frame-resident `__blkjobN: Int` handle (+ `_build_frame_init` seeds it 0). The
  typechecker (`__blk_start`/`__blk_done`/`__blk_pipe_fd`/`__blk_take` handlers)
  types them as Int and — crucially — `__blk_start` does NOT re-record the blocking
  effect (the offload REPLACES the direct call), so the synthesized `resume` stays
  suspension-free of the blocking source. Precise wake tokens + budget reset-on-park
  apply unchanged (the park reuses the design-91 `__io_tok` routing).
- **Cancel compose (design 102).** The park loop re-checks `__cancel` at its loop
  top and BAILS — a peer cancel writes the reactor self-pipe (design 102 item 1) or
  is caught by the pre-poll cancelled scan (item 3), which rouses the poll; the
  re-check exits the loop. The in-flight blocking call cannot be aborted, so take()
  still joins its worker on the cancel path (documented v1 limit: no leak, no race).
- **Anchor fix (item 3).** A blocking-extern call in a position the desugar cannot
  occupy (buried in an expression, a `try!`, an `if let`/`guard` body) is rejected
  in the transform ANCHORED AT THE USER CALL SITE (source_file threaded), never left
  to lower as a direct call and trip the synthesized `resume`'s sync check anchored
  at `__Frame_*.resume`. v1 also rejects a non-`(Int) -> Int` blocking extern
  (`_check_blk_whitelist`, anchored) — the offload thunk is `i64(i64)`; multi-arg +
  non-Int + a real pool are future work. The `sync`-context + freestanding
  rejections are UNCHANGED (correct).
- **Tests.** `offload_spawn_interleave` (a spawned task blocks on a real offload
  call while main's sleep-loop provably runs — 0,1,2 then 61; the 60 -> 61
  round-trip proves the Int flowed into the worker and back; a plain block would
  hang -> runner-timeout FAILURE; stable 8x), `offload_cancel_parked` (a task parked
  on an offload job is peer-cancelled via `cancel_addr`, wakes, observes cancel ->
  -1, deinit-once oracle; stable 8x), `errors/offload_buried_reject` (buried call ->
  user-anchored error, asserts the source basename), `errors/offload_freestanding_
  reject` (`--freestanding` COMPILE-FLAGS). Suite 941 (937 + 4), bootstrap 17+17,
  libs toml 4 + semver 4, zero xfails. [103, 76, 18, 22, 58, 102, 90, 91, 89-b]

## Design 101 — DF7: no silent blocking for suspending method calls in nested/trailing positions (LANDED)
- **Root cause (precise boundary).** The coro transform's wrapper hoists
  (`_hoist_suspending_conditions`/`_hoist_suspending_try`/`_hoist_suspending_match`)
  and the collect/reject walk key on `block.statements` and never look at
  `block.final_expr`. The parser parks a block's LAST bare expression there, so a
  suspending METHOD call buried in a TRAILING `if`/`else`/`match`/nested-`if` (the
  loop body's `final_expr`, e.g. `while going { …; if c { let x = try! s.read() } }`)
  was never statementized in time for the try/condition/match hoist to see it —
  it stayed wrapped in a `TryExpr` `_collect_calls` could not classify, slipped past
  every rejection, and lowered as a PLAIN blocking call (`call @TcpStream_read`), the
  silent DF7 miscompile (cooperative park a no-op). `_normalize_suspending_tails`
  (design 83) lifts trailing exprs to statements but ran AFTER two of the three hoists.
- **Fix (one canonical structural pass).** (1) Run `_normalize_suspending_tails`
  FIRST in `prepare`, before all three wrapper hoists — every suspending call then
  sits in statement position within some block, so the hoists + collect/split walk
  are exhaustive by construction. (2) `_split_match`: preserve the design-63
  `pattern` + `guard` (and carry pattern-derived binding names via a new
  `_pattern_binding_names`) — reconstructing arms from `variant_name`/`bindings`
  alone DROPPED literal/range/tuple patterns, so a suspension-spanning `match` over
  literal/range arms lost its patterns → spurious "match is not exhaustive" at 0:0.
  (3) `_reject_buried_suspend_call`: also flag suspending METHOD calls (not only
  free-fn/`receive()`) — a buried method call in an `if let`/`guard let` body
  (branches the split does NOT CFG-split) slipped through here and lowered plain;
  now a clean anchored rejection. Split-capable containers (if/while/for/match)
  never reach that method, so no over-rejection.
- **Shape matrix — every position now EMBEDS or ERRORS cleanly; no silent third
  outcome.** top-level stmt / trailing if / trailing else / trailing match arm
  (literal+range) / if-in-if depth 2 / if-in-while → EMBED (`net_nested_shape_matrix`,
  exact per-shape recirc counts). `if let` body / `guard let` body → clean anchored
  ERROR (`errors/coro_suspending_method_in_{iflet,guardlet}_body`). Closure body
  capturing a stream → clean NoCopy-capture ERROR. Verified with IR
  (`@__Frame_TcpStream_read_resume` drive, not `call @TcpStream_read`), not just exit
  codes.
- **Acceptance.** `net_budget_fairness` re-simplified from the DF7 workaround
  (read/write hoisted to the loop top level) back to the natural nested form (under a
  trailing `if`); still prints 5, still cedes to the sibling on the op-count budget
  (IR: driven sub-frames — a plain block would hang). Suite 932 (929 + 3); bootstrap
  ok (blade 17+17, libs toml 4 + semver 4); zero xfails. Docs: saw-lang skill's
  supported-shape story corrected (nested/trailing control-flow method calls now
  work; only if-let/guard BODIES reject). [101, 96, 84, 83, 74, 89-c, 92]

## Design 100 — shadowing: error unless derived from the shadowed binding (LANDED)
- **Rule.** A `let`/`var`/pattern/param binding that SHADOWS an enclosing binding
  (an outer local/param/capture in a parent scope, or an accessible module
  `static`) is a compile error UNLESS it is a visible refinement. Typechecker
  helpers in `statements.py` (`_shadowed_binding_pos` walks the current scope's
  PARENT chain + `namespace.get_static`; `_init_mentions_name` is a generic
  dataclass walk for any `Identifier`/`MoveExpr` use of the name; `_check_shadowing`
  the entry, `site=binding|pattern|param`). Wired at every binding-introduction
  site: let/var (`_check_let_statement`, main rule on the initializer), destructuring
  let (per bound name), single-name if-let/guard-let (main rule on the scrutinee —
  so `if let x = x` / `guard let x = x` stay legal), tuple/match PATTERN bindings
  (flat error — patterns bind, not compare; the hint says so), function/method
  params vs module statics, closure params vs enclosing locals. Same-scope
  redefinition is unchanged (still the pre-existing DUPLICATE_VARIABLE error);
  prelude/std names are not bindings. Diagnostic: `` `x` shadows the binding
  declared at FILE:L:C `` + a rename/derive (or patterns-bind) hint; positions
  exact (design 99).
- **MIGRATION AUDIT: only 1 illegal shadow in the ENTIRE corpus** (std + blade +
  libs + examples all compiled green; only `examples/use_after_move_shadow.saw`,
  a test that DELIBERATELY shadowed a moved-from binding to prove move-state is
  per-identity — migrated to a distinct inner name, intent preserved). Accidental
  shadowing was effectively nonexistent — the codebase was already clean.
- **CODEGEN double-free FIXED (pre-existing, fix-on-discovery).** Design 100 makes
  a derived SAME-name shadow of an OWNING binding idiomatic (`let nums = nums.copy()`,
  `if let x = x`), which exposed a latent codegen bug: scope-exit cleanup and the
  if-let path resolved a binding's storage/drop-flag by NAME, so a shadowing inner
  binding redirected the OUTER scope's cleanup to the inner (already-dropped)
  storage → double-free (SIGABRT/SIGTRAP), and `if let x = x` deleted the outer
  binding outright (ICE on later use). Repro'd on the clean tree (not my change —
  typecheck-only). Fix: (1) `_register_cleanup`/`_cleanup_scope` (resources.py) +
  the guard-let producer (conditionals.py) now CAPTURE the alloca+flag at
  registration and `_emit_drop_at` the captured pointer (never re-resolve by name);
  (2) if-let restores the shadowed enclosing binding instead of deleting it
  (conditionals.py); (3) `_generate_block` (methods.py) snapshots + restores the
  name→storage maps at block exit so a use of the outer name after a shadowing
  block is sound. Tests: `shadow_owning_lifetime` (derived owning shadow + outer
  reused; `if let x = x` + outer reused).
- **FLAG for the user — CLOSED by design 107 (both halves).** (a) The design
  brief's headline example `var data = read(); let data = parse(move data)` in ONE
  scope was left as the pre-existing "already defined in this scope" error (the
  dispatch scope pinned "same-scope redefinition: if already an error, unchanged").
  Design 107 item 1 opened same-scope redefinition under the SAME mentions-rule —
  it is now legal when derived. (b) For-loop iteration variables were DEFERRED by
  scope (the design-100 brief enumerated let/var/patterns/params, not for-loop
  vars). Design 107 item 2 brought them under the rule (sequence = initializer
  analog). See the design 107 tracker entry.
- Tests (OK): `shadow_derived` (derived let bare/move/call-wrapped/`.copy()`, var,
  if-let, guard-let unwrap — all run). Tests (ERROR, exact positions on both the
  shadowed decl and the shadow site): `errors/shadow_inner_let`,
  `errors/shadow_match_pattern`, `errors/shadow_param`, `errors/shadow_closure_param`.
  Docs: LANGUAGE_SPEC bindings section + saw-lang skill (rule bullet + gotcha).
  Suite 928 (922 + 6), bootstrap ok (blade 17+17, libs 4+4). [100, 99, 15, 42]

## Design 98 — `#file`/`#line`/`#function` source-location literals (LANDED)
- Magic literals expanding at their DEFINITION site to compile-time constants
  (zero runtime cost, freestanding-safe): `#file` → source basename (String,
  matches the design-69 panic prefix), `#line` → 1-based token line (Int),
  `#function` → enclosing fn/method BARE name (String; module scope → `<module>`).
  Lexer reads `#`-directives (unknown `#foo` = clean lex error); parser emits a
  `SourceLocationLiteral` atom carrying the file (stamped from the parser's
  source_file; interpolation sub-parser now inherits it) + token line; typechecker
  `visit_SourceLocationLiteral` freezes the value ONCE (idempotent — the post-coro
  re-check must not re-resolve, so `#line`/`#function` in a suspending body report
  the ORIGINAL source, not the frame method), returns String/Int; codegen emits a
  plain Int/String literal; `#line` is const-init-able (`_is_const_init` +
  `_const_from_expr`) so a top-level `static X: Int = #line` works. Generics report
  the generic's own file/line identically across instantiations; defaults report
  the default's definition site. Builds on design 99 (interpolation position
  rebasing) so `#line` inside `{...}` reports the real line. Tests:
  source_location_literals (method/generic×2/closure/default/top-static/main, exact
  pinned lines), source_location_suspending (spawned worker straddling two suspends
  → original line + bare name), errors/unknown_directive. Docs: spec Source-location
  literals section + skill debug-print idiom. Suite 922 (919+3), bootstrap ok. [98, 99, 69]

## Design 96 — nested suspending reactor methods at any depth (LANDED)
- The depth-2+ hang was NOT the design-91 wake token (token threading is correct
  at every depth). ROOT CAUSE: the effect fixpoint cannot see suspension arising
  SOLELY from a nested std METHOD call (a std method's effect node is absent — the
  gap `_scan_method_callees` works around), so a FREE fn whose only suspension
  source is a buried `stream.read()` was left `suspends=False`; the driven-closure
  walk skipped the caller→callee edge, the fn never joined the closure or got a
  frame, and it was emitted as a PLAIN blocking call whose buried `io_wait` wedged
  the single thread. 1-deep worked only because `_scan_method_callees` sees a
  method call directly in the root body. FIX (coro_transform.py): compute
  `structurally_susp_fns` (a free fn structurally suspends if its body calls a
  suspending method or reaches — via free-fn edges — one that does; transitive
  fixpoint) and follow such edges in the closure walk even when `suspends=False`.
- SECOND gap fixed same area: a suspending call in a `match <call> { … }`
  SCRUTINEE was never hoisted (hung even at DEPTH 1) — added
  `_hoist_suspending_match` mirroring the if-let/try hoists.
- DF6 (break/continue in a non-spanning if inside a spanning loop) root-caused +
  fixed here — see the DF6 entry below (now CLOSED).
- read_into: design-88-deferred `TcpStream.read_into(&var Data) -> Result<Int,
  IoError>` now works (the depth limit was the blocker) — OFFERED alongside value
  `read()` (accumulate into one buffer, no per-chunk alloc). Value read() NOT
  migrated.
- Tests: net_nested_method_two_deep / _three_deep (spawned worker → free fn(s) →
  read(), socketpair, deterministic), net_read_into, coro_break_reentered_in_loop.
  Suite 919 (was 915 + 4); bootstrap ok.

## Design 97 — libs/semver + libs/toml `blade test` harness fix (LANDED)
- Root cause of the recurring "libs blade test fail on a clean tree" flag
  (noted by designs 84/88/92): candidate (a). `blade test` compiles each test
  with `sawc` unless SAWC overrides it; the tester ran that compile through
  `system()` with `> /dev/null 2>&1`, so on a clean tree (no SAWC, no installed
  `sawc`) the "command not found" was swallowed and all tests reported FAILED.
  The tests + `import src.lib.*` self-path were always fine — the invocation hid a
  missing compiler.
- Fix (tester.saw, never-hide-errors): loud preflight — SAWC unset AND no `sawc`
  on PATH → one clear actionable error, stop (not N silent FAILEDs); compile+run
  via `shell_ok_loud` which suppresses only stdout and lets stderr through (sawc
  writes success to stdout, diagnostics to stderr; panic/failed-assert aborts to
  stderr) → a passing run stays clean, a compile error or a test's failure reason
  is surfaced.
- Coverage gap closed (blade_bootstrap.py): `libs/toml` + `libs/semver`
  `blade test` now run as a standard bar (SAWC set via ENV, as the main build
  already does), green (toml 4, semver 4); their gitignored `.blade/` cleaned
  after. TESTING.md updated. A user runs a lib's tests with nothing but
  `blade test` when `sawc` is installed / SAWC is set; on a clean tree the
  bootstrap sets SAWC for them.
- Suite 919 / 0 xfail; bootstrap ok incl. both lib suites.

## Design 93 — generic type-argument inference (LANDED)
- **NOTE:** no `designs/93-*.md` brief file exists on disk (the dispatch brief was
  the authoritative spec; recorded here). Retired the "type inference is not yet
  supported" rejection for generic free functions AND methods. `v.map({ $0.to_
  string() })` / `v.fold(0){...}` / `wrap(5)` / `first(7,"hi")` now infer their
  `<...>` from argument types; a method's own `<U>` is solved from the closure's
  inferred RETURN type (closure params come from the struct + phase-1 arg
  solutions). Commit 1 (feature + tests): unify abstract param types against
  actual arg types (`_unify_infer`, structural over function/optional/ref/ptr/
  array/tuple/struct-enum-args); a sandboxed pre-pass (`_infer_snapshot`/`_infer_
  restore` roll back moves + per-instantiation mono queues + `_poly_call_edges`,
  a throwaway suspend node catches enclosing-node effect edges) discovers arg
  types, then the SOLVED args are stamped onto `expr.type_args` (default-filled)
  so the existing explicit-path machinery (bounds, effect-poly recording, codegen
  monomorphization, coro-transform driven/spawned rewrite) runs BYTE-IDENTICALLY
  to an explicit call. Explicit `<...>` always allowed + wins; a partial explicit
  prefix pins its leading params and the rest infer; an unconstrained trailing
  param with a default type fills from the default. Clean diagnosable failure:
  underdetermined ("cannot infer type argument `T`" + explicit-args hint) and
  conflict ("required to be both `Int` and `String`") — never a silent wrong pick.
  Inferred args are bound-checked naming the inferred type; the generic-METHOD
  path previously did NO bound checking at all — added `_check_type_param_bounds`
  (Copy structural + `_bound_satisfied` for the rest), run on BOTH explicit and
  inferred method calls (fix-on-discovery). Driven (`__drive(run(move s))`) +
  spawned (`group.spawn(work(x))`) inferred generics monomorphize per INFERRED
  instantiation identically to explicit (the `__drive`/`spawn` handlers check the
  inner call first, so inference stamps `inner.type_args` before the mono
  rewrite). BOUNDARY (for the skill/spec): inference is single-pass left-to-right
  (non-closure args, then closures) — a param determinable only by a LATER arg
  than one it gates is not solved (give it explicitly); labeled + out-of-order +
  inferred is treated positionally (rare; give explicit args if it mis-maps).
  Overloaded-call generic inference (design-55 `_check_overloaded_*` paths) NOT
  wired — those still require explicit `<...>` on a generic overload (the design-55
  concrete-beats-generic model is unchanged; inference there would risk new
  cross-overload ambiguity — deferred). Retired obsolete
  `generic_method_requires_explicit_args` test. Tests: `infer_type_args` (free
  single/multi, method map/fold, mixed explicit+inferred, defaults, explicit-wins),
  `errors/infer_underdetermined`, `errors/infer_conflict`,
  `errors/infer_bound_violation`, `infer_generic_driven`, `infer_generic_spawned`.
  Suite 915 (910 −1 obsolete +6), bootstrap ok. [93, 36, 55, 70, 74, 37]

## Design 82 — per-file std visibility + prelude discipline (IN PROGRESS)
- **Part A (per-file std visibility) — LANDED.** Retired design 80's std-as-one-
  module deviation: `_vis_module_for_source` now keys each std/builtin file to its
  OWN member-gate module `("<std>", "<leaf>")` (was the single `("<std>",)`), so a
  private field/method of one std file is invisible to another — same rule as user
  modules. `_member_gate_allows` roots the package at `("<std>",)` for std-defined
  members so `public(package)` shares across std files (and excludes user code).
  Synthesized-provenance exemption unchanged; codegen/compiler-known-ness untouched
  (ACCESS check only). ABUSE AUDIT: **ZERO restructures / zero new `public(package)`
  needed** — design 80's public sweep already exposed every legitimate cross-std-
  file surface, so per-file gating is a pure tightening with no code churn. Gate
  verified live: temporarily un-`public`-ing `Vector.push` makes the builtin check
  reject its cross-file callers (directory.saw/env.saw/…) with a clean member-
  visibility error naming both std files; restored. Suite 905 (unchanged), bootstrap
  17+17 green. [82, 80]

## Design 82 Part B — prelude discipline (LANDED)
- **The prelude is now a CURATED ALLOWLIST, not "all std auto-merged".** Defined
  by its complement in sawc.py: `IMPORT_REQUIRED_STD_MODULES` (file, directory,
  path, data, channel, mutex, time, net, process, env, task — whole modules) +
  `IMPORT_REQUIRED_STD_SYMBOLS` (`Utf8Error` from string). `build_builtin_namespace`
  makes ONLY prelude symbols `directly_accessible`; the rest stay registered
  (compiler-known) but hidden. `import std.<mod>[.{A,B}|.*]` is a PRELUDE import —
  resolution is SKIPPED in the resolver (`imp.path[0]=='std'` → `continue`, symbols
  already in builtins) and `_process_std_import` un-gates the requested names (no
  `mod.Name` module alias — it would shadow common locals like `data`).
- **Gate + hint.** A bare source reference to a hidden std symbol (static call,
  struct init, free-fn call) errors: "`X` is not in the prelude and must be
  imported" + hint `add import std.<owner>.{X}`. `_std_name_gated` is exempt for
  std's own bodies (`_checking_builtins`) and synthesized coro output. A std-
  sourced method/function body re-checked in a user compile (design-84 spliced
  suspending std method) is checked permissively (`_decl_is_std_sourced` →
  allow_all_access) so it reaches its own internals.
- **No codegen collision (the design-84 IoError clash CLOSED).** Non-imported
  import-required std modules are EXCLUDED from codegen: `compute_std_codegen_exclusions`
  computes the compiled set = prelude ∪ imported ∪ transitive-dep-closure (comment-
  stripped source scan; `string`→`data`, `taskgroup`→`task` stay), `_filter_std_ast`
  drops excluded decls, and the merged-ns collision check skips them (`merge_into`
  `exclude=`). So a user may define its own `struct IoError`/`File`; `_shadows_hidden_std`
  lets the user decl replace the (uncompiled) merged builtin without a "defined
  multiple times" error. StringBuilder VERDICT: KEPT in prelude (borderline, common).
- **Migration.** 56 examples + 8 blade/src + 15 blade/tests gained `import std.X.{...}`
  for the non-prelude types they use (libs/sos needed none). New suite tests:
  `prelude_user_ioerror` (user IoError+File compiles/runs), `errors/prelude_tcp_needs_import`
  (bare TcpStream → clean import error), `prelude_import_makes_visible` (import
  un-gates Duration; Vector bare works). Suite 908 (905→+3), bootstrap 17+17. [82, 84, 80]

## Design 88 — references across suspension points (implement D6) (IN PROGRESS)
- **Core LANDED (commit 1).** A reference PARAM/LOCAL of a suspending function
  is now a frame-resident RAW POINTER across suspensions (`_enc_of` REFERENCE ->
  "ref"; field `UnsafePointer<T>`, pointer mut mirrors the ref; read rewritten to
  `self.name[0]` — the `__recv[0]` mechanism of 45-0c generalized). Drive site
  casts `&x`/`&var x` -> `UnsafePointer<T>` (`_ref_arg_to_ptr`), driver param is
  the pointer, frame seeds it directly. Re-typecheck ACCEPTS it (member access /
  mutation / method calls flow through the deref lvalue); synthesized resume is
  exempt from the design-81 `unsafe` marker. Ref field is NON-owning — exempt from
  drop flags, never dropped (deinit stays exactly-once). Both `&T`/`&var T` and
  `&var self`. Frame kinds allowing held refs: **DRIVEN-in-place = YES;
  SPAWNED-cross-task = NO** (`_reject_spawn_frame_refs` — a spawned frame with a
  ref param/across-suspend ref local is a hard error for BOTH single- and
  multi-threaded groups, confinement not merely Send). Tests:
  coro_ref_param_read/_mut/_self_method/_deinit_once + coro_spawn_ref_rejected.
  Suite 904 (was 899); bootstrap green.
- **Item 5 (nested ref + capability) LANDED (commit 2).** A NESTED suspending
  call's reference argument is seeded into the callee sub-frame as a pointer into
  the TASK frame (`_build_sub_frame` casts `&self.<field>` -> `UnsafePointer<T>`);
  a reference to a task-CONFINED local inside a spawned body is sound and allowed.
  The spawn rejection now fires ONLY on the spawn ROOT's own ref params/locals
  (its referent is the dead spawner stack) — NOT on embedded callees (refs can't
  escape owned values, so a nested callee can only get a task-frame pointer once
  the root carries none). Tests: coro_spawn_nested_ref (read_into-shaped helper
  holding a `&var` across a `yield_now` in a spawned worker, through the real
  multi-task scheduler). NET `read_into` over a real socket is BLOCKED by an
  orthogonal PRE-EXISTING limit: a suspending `stream.read()` buried TWO frames
  deep (spawn-root -> nested free fn -> nested method) HANGS — reactor token
  propagation reaches only one nesting level (value-based control hangs
  identically; NOT a design-88 issue). VERDICT: keep the value-based `read()`;
  defer a `&var Data` net read until that depth limit is fixed. Suite 905.
- **Items 4 + 7 LANDED (commit 3).** Item 4 VERDICT: KEEP the `sync`-body
  restriction on `Vector.with_ref`/`with_var_ref` — unlike a D6 held reference
  (task-confined stack/frame referent unreachable by other tasks), a container
  borrow projects into shared reachable storage a concurrent task could realloc
  across a suspension (iterator invalidation); confinement does not cover it.
  Documented in vector.saw. Item 7: spec concurrency updated (D6 implemented +
  driven/spawned boundary + with_ref caveat); saw-lang skill concurrency note
  added (references-across-suspend capability + spawn-root rejection + net stays
  value-based). **Design 88 COMPLETE** (scope items 1-7 all addressed).
- **FLAG (pre-existing, unrelated) — CLOSED by design 97.** `libs/semver` +
  `libs/toml` `blade test` suites fail on a CLEAN tree. Root cause: the tester ran
  the compile through `system()` with `> /dev/null 2>&1`, so with no SAWC set it
  silently fell back to a `sawc` that isn't on a clean PATH and swallowed the
  "command not found" — every test reported a mysterious FAILED. Not the
  `import src.lib.*` self-path (fine). See the design 97 entry.

## Design 94 — enum/Result payload sizing + temp-drop-at-merge (IN PROGRESS)
- **Codegen chain LANDED (commit 1).** Two frame-layout-sensitive bugs, both
  root-caused with a deterministic `-O0` repro (`blade build --force` 12/12
  SIGBUS at -O0; ~40% at -O1) + the design-85/86 discipline. (1) enum/Result
  CREATE paths (`_create_result_ok/err_for_return`, `_wrap_error_in_union`,
  `_generate_enum_init`) alloca'd the SMALLER variant struct but bitcast-LOADED
  the FULL `[N x i8]` payload — an OOB stack read past the slot; fixed to alloca
  the full payload (align 8), store the variant struct into its front, load the
  whole array. (2) The create-fix shifted the frame and exposed the real
  `Builder_build` crash: a statement TEMP created in a block's `final_expr` (an
  unbound method receiver — here `read_file(".blade/build-hash")` in the inner
  `if …equals(hash)`, itself the tail-expr of the outer `if not force` body) was
  registered in the ENCLOSING statement's temp list and dropped at the outer
  `if`'s MERGE block — reachable from the not-taken `else` where the temp was
  never initialized → `String_deinit` released an uninitialized (garbage) pointer
  → EXC_ARM_DA_ALIGN on the refcount atomic. Fix: `_generate_block` now drains
  the statement temps created during its `final_expr` at block end, on the paths
  that create them, before the merge. Suite 897 green; bootstrap green; `blade
  build`/`--force` reliable 15x + under libgmalloc (0 faults, O1 and O0).
- **Process module LANDED (commit 2 — the acceptance).** `Command.run() ->
  Result<Int32, ProcessError>`: Ok(code)=the command launched and exited with
  `code` (signal death still decodes to 128+signum via decode_wait_status);
  Err(ProcessError)=could not launch (`system()` returned -1, or the shell
  reported 127 "command not found"). `ProcessError` conforms to `Error`
  (Printable), names the failed program. Callers migrated: blade `builder.build`/
  `builder.run` (match; a launch failure → BuildError), `git` clone/checkout
  (Err → false). Forced-failure test `examples/process_error_surfaced.saw`
  (nonexistent command → Err, error names the program). Suite 898; bootstrap
  green; blade `build`/`--force` reliable 10x + gmalloc 6x at O1 AND O0, zero
  faults — that reliability WITH the process module back in build()'s frame (the
  original design-92 trigger) is the proof the codegen chain is fixed. The
  design-92 `write(s: String)` overloaded-suspending-method fix stays deferred
  (design 95).

## Design 92 — failable calls return Result: no silent swallow (IN PROGRESS)
- **net module LANDED** (commit 1): `TcpStream.write(bytes: Data)`,
  `read() -> Result<Data, IoError>`, `TcpListener.accept() -> Result<TcpStream,
  IoError>` all surface failure; the swallowing `write_all`/`write_all_str`
  removed. read's EOF is `Ok(empty)`, DISTINCT from `Err` (was: empty Data meant
  both). Forced-failure test `net_error_surfaced` (connect-to-closed-port → Err;
  peer-closed read → Ok empty). Enabling compiler work: `Result<Void, E>` support
  (enum void-payload filter + Ok/void create/extract + bare `return`→Ok(Void) +
  match `Ok(_)` on void); `ResultOkWrap`/`ResultErrWrap` re-typecheck visitors (the
  post-coro-transform re-check was skipping their rewritten inner expr → ICE);
  coro-transform TRY-HOIST (a `try! recv.m()` in a driven body now hoists to a
  driven temp + `try move __t` — the tried suspending call was hidden inside a
  `TryExpr` the nested-call scan couldn't see, so its `io_wait` park never
  integrated with the executor → hang; the `move` consumes the temp so its owning
  payload is not double-dropped/closed).
- **CLOSED by design 95 — coro-transform now drives OVERLOADED suspending
  methods.** Driven/embedded suspending-method frames are keyed by the design-55
  RESOLVED SIGNATURE (the overload-mangled `$OL$`/`$LB$` symbol the typechecker
  stamps: `mangled_symbol` on the method AST, `resolved_symbol` on the MethodCall)
  via one canonical `_method_frame_key` helper — a non-overloaded method has no
  symbol and keeps its plain `{struct}_{method}` key (unchanged). `write(s: String)`
  is re-added as the text overload of `write(bytes: Data)`; the `.to_data()` call-
  site workarounds are reverted (httpd/echo/net examples).
- **file/directory/env LANDED** (TIER 2, Bool→`Result<Void, IoError>`): `file`
  {`remove`,`rename`}, `directory` {`create`,`remove`,`set_current`}, `env`
  {`set`,`unset`,`set_cwd`} now surface the errno; `exists`/`contains` stay
  genuine boolean questions, `list`/`current`/`get` stay `T?`. Public
  `IoError.from_errno(syscall)` factory added (net.saw) as the cross-std-module
  constructor. blade callers migrated (`match`/`let _` on the Result). Forced-
  failure tests: file/directory/env `_error_surfaced`.
- **codegen LANDED (design-92 dogfood):** enum/Result payload SCRATCH allocas are
  now 8-aligned (`_entry_alloca(..., align=8)` on the extract byte-arrays). The
  payload is `[N x i8]` (ABI align 1) but is bitcast-and-loaded as the variant's
  field struct (8-aligned pointers/i64); the 1-aligned slot faulted on arm64
  depending on frame layout — a heisenbug the added Result monomorphizations
  tipped (`blade build --force` SIGBUS ~1/3; deterministic under MallocScribble).
  This alone made the bootstrap reliably green again.
- **process DEFERRED — a SECOND, DEEPER latent codegen bug.** `Command.run() ->
  Result<Int32, ProcessError>` is implemented + all callers migrated (blade
  git/builder, process examples + `process_error_surfaced`) and the full suite
  passes 898 — BUT it re-tips a distinct crash in blade's large `build` frame (a
  garbage-POINTER read / translation fault at teardown, ~40% normal). ROOT (found,
  NOT yet safely fixed): the enum/Result CREATE paths (`_create_result_ok/err`,
  `_wrap_error_in_union`, `_generate_enum_init`) alloc the (smaller) VARIANT struct
  but bitcast-load the FULL `[N x i8]` payload → an out-of-bounds stack read past
  the slot. The obvious fix (alloc the full payload, store the variant into its
  front) is suite-green but shifts the frame and tips YET ANOTHER latent issue in
  `Builder_build` (blade went 8→20/20) — so it needs a focused codegen
  investigation, not a design-92 rider. Process change is reverted; std stays at
  `run() -> Int32` until the codegen bug is fixed. (Evidence: crash reports show
  `Builder_build` garbage/alignment reads at teardown; masked under lldb + normal
  heaps; MallocScribble makes it deterministic.)
- **TODO:** land process once the codegen OOB/uninit bug is fixed; borderline
  `file.write`/`seek` `Int?`→Result (report); the overloaded-suspending-method
  fix that restored `write(s: String)` is DONE (design 95, below).

## Design 95 — driven-method frames keyed by resolved signature (LANDED)
- Coroutine transform keyed a driven suspending METHOD's frame by
  `(struct, method-name)`, so two OVERLOADS of one name collapsed to a single
  frame (design 92's deferred `write(s: String)`). Fix: one canonical
  `_method_frame_key(struct, name, resolved_symbol)` helper keys every driven/
  embedded/direct-drive method frame by the design-55 resolved-signature symbol
  (`mangled_symbol` on the method AST at the definition side; `resolved_symbol` on
  the MethodCall at call sites); non-overloaded methods carry no symbol → plain
  key, byte-for-byte unchanged (coro_*/taskgroup_*/net_* families untouched).
  `_driven_method_roots` re-keyed by frame key so a directly-driven overload also
  gets its own frame; `_find_method` disambiguates by symbol. `net.TcpStream`
  re-gains `write(s: String)` (whole-string bytes) alongside `write(bytes: Data)`;
  `.to_data()` workarounds reverted at the net examples. New regression test
  `net_write_overloads` (spawned worker calls BOTH overloads back to back).
  Suite 899 (+1), bootstrap green, libs (toml/semver) green.

## Design 90 — reactor lost-wakeup on the 2nd sequential connection (LANDED)
- **Root cause (VERIFIED with an instrumented repro, NOT the brief's guessed
  suspects).** It was NOT one-shot re-registration, wake-all clearing the wrong
  frame, an fd-map collision on a reused fd, or a poll/deadline skip. The reactor
  wakes ALL io-parked frames on ANY readiness event (coarse level-triggered
  retry), so EVERY parking op must re-verify its OWN fd and re-park on a spurious
  wake. `read`/`write`/`accept` already loop on would-block; **`TcpStream.connect`
  did NOT** — it parked ONCE on `io_wait(fd, 1)` then called `tcp_connect_check`,
  a v1 STUB that unconditionally returned 0 (success). In a multi-connection
  workload a client's connect-park was spuriously roused by the reactor's wake-all
  on a DIFFERENT fd's event (the listener becoming readable) BEFORE its own socket
  was writable; it trusted the wake, wrote on the still-unconnected socket →
  ENOTCONN (errno 57, confirmed via instrumentation), and `write_all_str` silently
  bailed on the hard error. The request was never sent, so the accepting server
  parked forever on the read of that connection. Single-connection round-trips
  (`net_accept_roundtrip`) work because no other fd triggers an early spurious wake.
- **Fix.** `connect` now LOOPS like the other ops: after each `io_wait(fd, 1)` it
  RE-VERIFIES completion by re-issuing the nonblocking `connect()` and classifying
  the result — connected (`EISCONN`/0), still-connecting (`EINPROGRESS`/`EALREADY`
  → re-park), or a real failure. Classification lives in a new compiler shim
  `saw_errno_connect_state()` (OS-divergent errno values stay in the compiler,
  mirroring `saw_errno_would_block`); `tcp_connect_check(fd, port)` gained the port
  arg to rebuild the sockaddr for the re-connect. This makes an arbitrary SEQUENCE
  of io-parks across multiple accepted fds (incl. fd-number reuse across connection
  turnover) each get their wakeup; the never-block invariant + earliest-deadline
  poll are untouched (no scheduler change).
- **FLAG (pre-existing, orthogonal — NOT fixed here, API-change scope):**
  `TcpStream.write_all`/`write_all_str` SILENTLY bail on a hard write error
  (`w < 0` -> `going = false`, no signal) — this is exactly what MASKED the connect
  bug (the ENOTCONN write vanished with no error). Their return type is `Void`, so
  surfacing the error means changing the signature to `Result<Void, IoError>` (a
  public-API change touching every call site) — deferred as a genuine design
  decision rather than silently widened here. With connect fixed the socket is
  connected before any write, so this path no longer fires in practice, but a real
  broken-pipe mid-stream would still be swallowed. [90, 84]
- **Result.** `probe_loopdiag` (server serves N=2 + 2 clients, one group) now
  round-trips fully (both connections read+write; result 2,1,1). Tests (all
  deterministic on content, time-bounded — the design-86 runner timeout catches a
  regression as a FAILURE not a wedge): `net_serve_two_connections` (N=2),
  `net_serve_three_connections` (N=3), `net_fd_reuse_across_connections` (one
  client, two strictly-sequential connections reusing the freed fd number on both
  ends), `net_two_concurrent_parked_reads` (two readers parked on different
  socketpair fds both wake). Updated `examples/net_loopback_echo.saw` to the new
  `tcp_connect_check(fd, port)` re-verify loop. Docs: saw-lang skill net note
  rewritten (multi-connection accept-loop now works; the per-op re-check is
  internal). Suite 888 (from 884), all net_*/coro_*/taskgroup_* green, bootstrap +
  libs green. [90, 76, 84, 89]

## Design 91 — precise reactor wakeup (retire wake-all) (IN PROGRESS)
- **Core landed.** The reactor no longer wakes ALL io-parked frames on any
  readiness event. `saw_reactor_register(fd, write, token)` carries a udata
  pointer (kevent.udata / epoll_event.data) = the parked frame's `__wake`-word
  address; `saw_reactor_poll` reads back each ready event's udata and LATCHES
  that word to 0 (ready), so only the frame(s) whose (fd, direction) fired wake.
  The latch is a persistent word (not an edge) → a fire that races the park is
  caught on the next scan (no lost wakeup, ST or MT). The scheduler
  (`__ambient_wake_io` + MT `__tg_worker`) wakes an io-parked frame only when its
  `__wake_reason()` has become >= 0. Nested-call routing: a new frame field
  `__io_tok` holds the ROOT frame's `__wake` address (a driven root sets it on
  first resume; each nested drive propagates it down), so an `io_wait` buried in a
  sub-frame routes its wakeup to the top-level frame the scheduler schedules.
  design-90 connect re-verify KEPT (belt-and-suspenders). Many-frames-one-fd:
  different directions = independent registrations (both precise); same direction
  = last-registrant-wins (documented, unsupported pattern). [91, 76, 90, 89b]

## Design 89 — executor unification: one ambient scheduler (IN PROGRESS)
- **Prep — LANDED (612e53d).** Coro-transform **static-visibility fix**: a
  suspending std method that names a module-private `static` (e.g.
  `TcpListener.accept` -> `INVALID_FD`) now compiles when spawned/driven — the
  const initializer is inlined at the reference site during the transform
  (`_inline_static_refs`). Before this, `accept()` could not be embedded at all,
  so NO accept-loop program compiled (`net_fd_leak` never exercised `accept()`,
  masking it). `read`/`write` reference only free functions, hence unaffected.
  Test: `net_accept_roundtrip.saw` (spawned server accepts ONE loopback conn +
  serves a GET; deterministic). Suite 884, bootstrap 17+17, libs 4+4. [89, 84]
- **Core unification (items 1-6) — DEFERRED to a follow-on (design 89-b),
  re-ledgered with analysis.** Evidence-based risk call (the brief's "defer if
  large/risky" escape). PROVEN this session: (1) the gap is real — `probe_gap`:
  a spawned child runs ONLY at `join`, never while main parks (today's split
  executors). (2) A SECOND, INDEPENDENT blocker gates the accept-loop
  acceptance: a **design-76 reactor lost-wakeup** in the multi-connection
  accept-loop — `probe_loopdiag` (server serves N=2 + 2 clients, ONE group)
  accepts conn#0, serves it, accepts conn#1, then the **read on the 2nd
  connection never wakes** (hangs at marker 911). A SINGLE accept round-trip
  works. Unifying the executor does NOT fix this — the accept-loop acceptance
  needs BOTH the unification AND the reactor fix. **The reactor lost-wakeup is
  now CLOSED (design 90, LANDED — see below); it unblocks the 89-b accept-loop
  acceptance, which now only needs the executor unification.** Why the core is large/risky + the recommended per-commit
  plan (ambient heap-singleton via a `static Atomic<Int>` addr, per-frame
  group-id membership, active-frame reentrancy skip, deinit-exactly-once box
  hand-off, MT bifurcation, then the reactor fix, then the op-count budget):
  see the STATUS section of `designs/89-executor-unification.md`. Repro files
  under `.build/scratch/` (`probe_gap`, `probe_loopdiag`, `probe_accept*`).
  [89, 45, 52b, 76, 75, 86]

## Design 89-b — executor unification core (WORKTREE, IN PROGRESS)
- **Steps a+b+c — LANDED (worktree).** The ambient cooperative scheduler:
  ONE per-thread sweep over an intrusive list of every live single-threaded
  TaskGroup (`static __saw_exec_head`, threaded through a new group `next`/
  `registered` field pair). Realized the design-89 "one shared run queue" as a
  registry-of-group-queues (each group keeps owning its boxes) — this keeps the
  battle-tested per-group deinit-exactly-once machinery intact and DISSOLVES the
  flat-queue box-ownership-hand-off hazard the STATUS flagged, while being
  behaviorally the pinned model (eager spawn, structured join, nested groups,
  reentrancy). One parameterized sweep `__ambient_run(term_group, term_slot)`
  reused verbatim at all three drive points: ALL (entry), GROUP (Deinit),
  FRAME (join); each SKIPS frames `active` on the C stack (reentrancy guard —
  task-joins-task yields to the one scheduler, never re-enters a live coroutine).
  A suspending `main` that also spawns is boxed as the ROOT member and driven by
  the shared sweep (`__exec_run_root`), so a spawned sibling runs whenever main
  parks (the core gap: `probe_gap` now INTERLEAVES `0,100,101,1,102,2,7` instead
  of `0,1,2,100,101,102,7`). Design-45 single-task main (no spawn) keeps the
  lighter single-frame executor; MT groups (workers>=2, design 75) keep their own
  worker pool + queue and never join the ambient list (bifurcation preserved).
  Bars green: suite 888, bootstrap 17+17, libs toml 4/4 + semver 4/4. NOTE: one
  non-reproducible `dep_build` SIGABRT flake observed under load (that test shells
  out to compile+run subprocesses; its path uses no concurrency, so unrelated to
  this change — baseline + reruns all green). [89, 45, 52b, 76, 75]
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

## Design 89-c — cooperative op-count budget (LANDED — CLOSES the 89 family)
- **The fairness backstop.** A task that keeps completing suspending io ops WITHOUT
  ever parking (an always-ready socket) can no longer monopolize the single-threaded
  ambient scheduler — the design-89 item-6 starvation caveat. Op-count, not
  wall-clock (kernel-friendly, deterministic); no preemption, no language surface,
  purely at existing suspension points.
- **Mechanism (codegen/core.py `_declare_io_runtime`).** A process-global op counter
  `__saw_op_budget` (default 128) + two weak/monotonic-atomic seams: `saw_op_budget_
  tick()` decrements and returns non-zero (self-resetting to the default) when
  exhausted; `saw_op_budget_reset()` restores it. Each net io primitive
  (accept/connect/read/read_into/write×2), on its NON-parking success path, ticks and
  force-`yield_now()`s when the tick fires (park-and-immediately-reschedule → cede to
  siblings), and calls reset after a genuine `io_wait` park (already ceded). The
  counter is self-resetting on exhaustion, so it works uniformly under the
  ambient/MT/single-task/`__drive` executors with NO scheduler or synthesized-executor
  edits; monotonic-atomic keeps MT workers race-free (shared budget there, benign).
- **Zero overhead for sync code.** Only a suspending io primitive ever charges the
  counter — code that makes no such calls never touches it. Well-behaved tasks (<128
  non-parking ops between parks, which reset the budget) never hit the forced yield,
  so existing coro_*/taskgroup_*/net_* interleavings are UNCHANGED (suite green, no
  interleaving test needed adjustment). Channel receive was deliberately NOT
  instrumented: in the ST cooperative runtime a channel consumer that outruns its
  producer DRAINS the channel and then parks on empty (the producer only runs when
  the consumer cedes), so an always-ready channel monopoly is impossible — only io,
  fed by the kernel/peer independent of the local scheduler, is the real vector.
- **Test `net_budget_fairness`.** A `recirc` task reads one socketpair end and writes
  the bytes back into the OTHER (refilling the read side) → every read is always-ready
  and never parks, an endless io loop whose only exit is a stop flag a sibling sets
  after its own turns. Without the budget `recirc` never cedes → the program hangs
  (the design-86 runner timeout turns that into a FAILURE); with it, `recirc`
  force-yields every 128 ops, the sibling completes and sets stop, and it prints 5.
  Deterministic (pure op-count) + time-bounded. Verified discriminating: neutering
  the tick makes it hang (SIGKILL 137), the real budget prints 5.
- ~~**DF7 (pre-existing coro-transform silent miscompile).**~~ CLOSED (design 101). A
  suspending METHOD call buried under a nested/TRAILING `if`/`else`/`match` in a
  driven/spawned body lowered as a PLAIN blocking call (cooperative park a no-op).
  Root cause: the wrapper hoists + collect/reject walk ignored `block.final_expr`
  and ran before `_normalize_suspending_tails`, so a call in a trailing-expression
  position was never statementized in time to be hoisted/classified/rejected.
  Fixed by running tail normalization FIRST; also preserved match `pattern`/`guard`
  in `_split_match` and taught `_reject_buried_suspend_call` to flag buried
  suspending METHOD calls (if-let/guard bodies now reject cleanly). See the design
  101 section above. [101, 96, 84, 83, 74, 89-c]
- Suite 929 (928 + `net_budget_fairness`); bootstrap ok (blade 17+17, libs toml 4 +
  semver 4); zero xfails. Docs: saw-lang skill concurrency caveat replaced with the
  landed backstop + residual pure-compute limit; LANGUAGE_SPEC concurrency gained an
  implicit-yield + op-count-budget bullet. **The design-89 executor-unification family
  (89 / 89-b / 89-c) is now COMPLETE.** [89-c, 89, 89-b, 45, 52b, 76]

## Design 87 — consolidate literal coercion + stable type-ids (IN PROGRESS)
- **Item 1 (ONE literal-coercion pass) — LANDED.** Integer-literal fixed-width
  typing now routes through the EXISTING expected-type propagation
  (`_apply_literal_expected_type`), which became the single recursive pass that
  pushes a fixed-width expectation to a bare literal AND through the transparent
  constructs that forward a value: unary minus (range-checks the FOLDED value so
  Int32.min's magnitude is admitted), if/match/block arm results, and
  array/tuple/map/set element positions. `visit_IntLiteral` (typechecker) adopts
  the expectation; codegen `visit_IntLiteral` materializes at the resolved
  fixed-width width. AUDIT (all were BROKEN pre-87): array-literal elements into
  `[IntN;M]` (stored platform-wide, no range check), tuple elements (same),
  if/match arm results (narrowed but NO range check), compound-assign RHS
  (`x += 1`, Int8 → i8-vs-i64 ICE), default parameter values (silently wrapped),
  Map/Set literal keys+values (unchecked) — now all coerce + range-check
  uniformly. DELETED the per-position `_check_fixed_width_literal` calls the
  central pass subsumes: method/func tail-return, `return <expr>`, regular +
  overloaded call args, struct-field + custom-init args, enum payload. KEPT
  `_check_fixed_width_literal` + `_fixed_width_binop_type` for the two
  SIBLING-OPERAND positions (comparison `b < 200`, arithmetic `b + 0`) — the
  expectation there is the other operand's type, discovered only AFTER checking,
  so it genuinely can't route through a declared-slot expected type. INVARIANT
  held: no fixed-width expectation ⇒ platform Int (`let x = 5`, Int/Int
  arithmetic byte-identical); full suite is the oracle. Tests:
  `literal_coercion_positions` (all positions round-trip) +
  `array_element/tuple_element/compound_assign/if_arm/default_param/map_literal_key`
  `_..._out_of_range_error` (6 clean range errors). Suite 883 (from 876),
  bootstrap 17+17, libs 4+4. [87, 65, 53, 77, 81, 54, 29]
- **Item 2 (stable erased-error type-ids) — LANDED.** Replaced design-72's
  per-compilation MONOTONIC COUNTER (memoized by mangled name, order-dependent)
  with a deterministic FNV-1a 64-bit hash of the mangled type name (same
  constants as the runtime Hasher in builtin.saw), masked to the platform word so
  it fits the vtable's `int_type` type_id slot. The id is now a pure function of
  the type NAME, so the SAME concrete type gets the SAME id in EVERY compilation —
  a future separate-compilation boundary would agree on `is<T>()`/`take<T>()`, not
  just the current whole-program build. `is<T>`/`take<T>` behavior identical (both
  the vtable bake and the downcast compare call the one `_type_id_for`); existing
  downcast tests green. COLLISION POSTURE (documented in `_type_id_for`): a 64-bit
  FNV space over distinct mangled names makes an accidental clash negligible (a
  birthday clash needs ~2^32 conformers in one program); ids are compared only for
  EQUALITY (never as a sentinel), so `0` is now a legal id (the old counter
  reserved it). Test: `tools/test_stable_type_id.py` (IR-level, in the
  `test_debug_info.py` family) — compiles two programs that conform `Circle: Shape`
  in DIFFERENT declaration positions among DIFFERENT companion types, extracts the
  type_id baked into Circle's vtable from `-O0` IR, and asserts (a) the two are
  IDENTICAL (the old counter would give Circle id 1 vs id 3 → order-dependent, and
  this test would fail) and (b) it equals FNV-1a("Circle") (pins the scheme).
  Docs: spec Integer-Types section (a bare literal adopts a fixed-width expected
  type everywhere) + saw-lang skill literal note. Suite 883, bootstrap 17+17,
  libs 4+4. [87, 72, 51, 48]

## Design 86 — httpd-runtime cleanup (IN PROGRESS)
- **Item 3 (`&var self` mutation on an opt-encoded frame-local across a suspend)
  — LANDED.** ROOT CAUSE: in `_generate_method_call` (codegen/calls.py), the
  `is_mutable_self` receiver-addressing chain handled `Identifier`/`SelfExpr`/
  `MemberAccess`/`ArrayIndex` but NOT `ForceUnwrap`. A `Data`/`StringBuilder`
  frame-local accumulated across a suspend is opt-encoded (design 62), and the
  transform rewrites a bare receiver `acc` → `self.acc!` (`_rewrite_node` →
  `ForceUnwrap`). That `ForceUnwrap` receiver fell through to the `else` branch
  that STORES a loaded copy into a fresh `self_temp` alloca and mutates the copy —
  so `acc.push(...)` / `req.append(move chunk)` across a park wrote to a discarded
  temporary and the real frame slot never changed. Silent in a pure loop (probe
  printed 0 instead of 3); a HANG in net_http_roundtrip (the empty `req` never
  matched the request terminator, so the handler re-`read()`s forever while the
  peer waits for a response → deadlock). FIX: add a `ForceUnwrap` branch that
  addresses the optional payload IN PLACE via `_generate_reference_expr(Reference
  Expr(mutable=True))` — the design-84 `&(opt!)` addressing (None-checked GEP to
  the payload slot) — so the `&var self` mutation lands on the real frame field
  and survives the suspend. Safe: `ForceUnwrap` is not an owned-temporary, so no
  stmt-temp double-free. TESTS: `net_accumulate_across_reads` (server appends 5
  lock-step "abc" chunks into a frame-resident Data across read+ack parks, asserts
  the FULL "abcabcabcabcabc" buffer + len 15) and the UN-QUARANTINED
  `net_http_roundtrip` (moved scratch → examples/; a socketpair read→build→write
  HTTP round-trip, now RUNS 5/1). Suite 876 (from 874), bootstrap 17+17, libs 4+4,
  zero xfails. [86, 84, 62, 44]
  - **httpd acceptance = the socketpair-reduced suite test (net_http_roundtrip).**
    The live `.build/scratch/httpd_sw.saw` now COMPILES + its `handle_connection`
    (`req.append(move chunk)` across `read()`) is unblocked, but the infinite
    `accept`-loop server as written does NOT serve a live GET — verified: it binds
    + prints "Serving …", but a `curl` GET returns empty. FLAG (separate
    architectural gap, NOT item 3): the loop does `let _ = group.spawn(handle…)`
    and NEVER `join()`s, so the spawned handlers only run at the group's Deinit
    (never, the loop is infinite); main's `accept`-park entry-executor does not
    drive a sibling group's run queue. net_http_roundtrip works because it
    `join()`s (which drives the group to completion). The fix is executor
    unification (main's park should drive spawned siblings) — a real concurrency-
    architecture design, out of scope here; the brief explicitly accepts the
    socketpair-reduced form as the acceptance. Skill runtime-limit note rewritten. [86]
- **Item 2 (variadic libc declaration audit) — LANDED (CLEAN, no fix needed).**
  Swept every libc declaration the compiler/std makes: all `_libc_func` call
  sites + all direct `ir.Function` decls in `sawc/codegen/*.py`, and every
  `extern "C"` func across `sawc/std/*.saw`. Cross-referenced each name against
  its C prototype. The COMPLETE set of variadic-in-C functions the toolchain
  declares is exactly FOUR — all ALREADY declared variadic:
  - `printf` — codegen core.py:336, `var_arg=True` ✓ (Float print path; Saw
    Float is f64 so no float→double promotion gap).
  - `snprintf` — codegen core.py:348, `var_arg=True` ✓ (int/float→string; ints
    promoted to i64 for `%lld`/`%llu`).
  - `fcntl` — codegen core.py:1354, `var_arg=True` ✓ (fixed in design 85 — the
    bug that motivated this audit).
  - `open` — std/file.saw:13, declared `func open(path, flags: Int32, ...)` ✓
    (variadic since introduction f6ebd80; called with the variadic mode arg by
    File.create/append `open(ptr, 577, 420)`).
  Every OTHER extern is genuinely fixed-arity in C and correctly declared
  non-variadic (malloc/free/fwrite/fflush/usleep/clock_gettime/memcpy/pthread_*/
  close/kqueue/epoll_*/kevent/strlen/strcpy/strcat/abort/socket/bind/listen/
  accept/connect/read/write/lseek/access/unlink/rename/mkdir/rmdir/opendir/
  readdir/getenv/setenv/system/popen/fread/strlcpy/strlcat/fabs/… + the saw_*
  seams). NO mis-declared variadic function remains after the design-85 fcntl
  fix — nothing to change. Behavioral variadic coverage already in the suite:
  the design-85 net tests (fcntl→O_NONBLOCK, the load-bearing case),
  `file_simple` (open-with-mode create→write→reopen→read-back roundtrip), and
  the float print/format tests (printf/snprintf varargs). Suite 874 unchanged. [86, 85]
- **Item 1 (test-runner run-phase timeout) — LANDED.** `run_executable` now
  runs each test's binary under a hard, process-GROUP-aware wall-clock cap
  (`RUN_TIMEOUT_SECS = 30`): `subprocess.Popen(..., start_new_session=True)` +
  `communicate(timeout=)`, and on expiry `os.killpg(SIGKILL)` the whole group
  (not just the child) then reap. This closes the wedge where a hung test that
  spawned OS threads / a grandchild holding the inherited stdout pipe would
  block the post-timeout reaper forever — a live hazard for every concurrency
  brief. A timed-out test is recorded FAILED (timeout), the runner never hangs.
  Proof: `tools/test_runner_selftest.py` (NOT globbed by the .saw suite) — 4
  cases incl. the grandchild-inherited-pipe wedge, all return < 10s under a 2s
  cap; plain hang + nonzero-exit + normal-exit paths covered. Suite 874,
  bootstrap 17+17, libs 4+4. [86]

## Design 84 — Safe net API: TcpListener/TcpStream owning types (IN PROGRESS)
- **Coro lift landed (commit 1):** nested suspending METHOD call embedded
  as a sub-frame in a driven/spawned body (`let s = recv.m()`, bare
  `recv.m(...)`, tail `return recv.m(...)`), driven across the caller's
  resumes exactly like a nested free-function call. Method frame keyed
  `{struct}_{method}`, `__recv` points at the receiver's caller-frame
  storage; `&self`/`&var self` both work; result threading + Deinit-once
  verified. CLOSES design 74 A5-rest shape 1 (the old `examples/errors/
  coro_buried_suspending_method.saw` rejection became the positive
  `examples/coro_nested_suspend_method.saw`, value 1012). Enabler: `&(opt!)`
  is now an addressable lvalue (address of the optional payload, None-checked)
  — a general language addition (typechecker `_is_lvalue` + codegen
  `_generate_reference_expr`) that lets an opt-encoded owning receiver in a
  frame be addressed.
- **Cross-module std method embedding landed (commit 2):** `TcpStream.read` /
  `TcpListener.accept` etc. live in std.net (imported), which is checked under a
  SEPARATE builtin typechecker — so the main one cannot infer their suspendability
  or reach their effect nodes. Fixes: (a) `build_builtin_namespace` computes the
  suspending (struct, method) set from the builtin typechecker's finalized graph
  and carries it forward (`typechecker._std_suspending_methods`); (b) the transform
  scans the MERGED extensions (not just entry_ast) for method ASTs + a structural
  body-scan (`_iter_method_calls`) discovers std method callees the edge-walk can't
  reach; (c) the std method frame + resume splice into entry_ast; the original std
  method stays as harmless dead code. Verified: a spawned worker's `stream.read()`
  parks on io_wait internally and wakes via the reactor (single-nested-call
  round-trip `examples/net_owning_echo.saw` — reliable, 5/5).
- **std.net owning types landed:** `TcpListener` (listen/local_port/accept) +
  `TcpStream` (connect/pair/read/write_all/write_all_str), both NoCopy with
  Deinit-closes-once; `IoError: Error` (errno via a new `saw_errno` seam). fd is a
  private `Int32`; the public surface has ZERO raw fds/pointers. Raw `tcp_*`/`net_*`
  layer kept as the private impl. `Data.append_bytes(ptr,len)` + `Data.byte_ptr()`
  added (pointer-signature = design-81 marked domain) for the socket read/write path.
- **DEVIATION from the pinned read/write signatures (flag):** `read(&self) -> Data`
  (empty = peer closed) + `write_all(&self, bytes: Data)` by move +
  `write_all_str(&self, s: String)`, NOT the brief's `read(&self, into: &var Data)
  -> Int` / `write_all(&self, bytes: &Data)`. Reason: a `&`/`&var`-reference PARAM
  cannot yet live in a coroutine frame (references opt-encode to a struct field of
  reference type, which the re-typecheck rejects). Reference-params-across-suspend
  is a separate, larger coro lift; deferred. The value API meets the GOAL.
- **⚠ PRE-EXISTING coroutine bug BLOCKS a true echo / the httpd runtime (FLAG,
  fix-on-discovery deferred with analysis):** a driven/SPAWNED worker whose body
  makes a SECOND nested suspending call AFTER the FIRST one PARKS on io_wait hangs
  at runtime (heisenbug — a `print` in the worker body perturbs it away). CONFIRMED
  PRE-EXISTING and NOT design-84: it reproduces with plain suspending FREE functions
  (`.build/scratch/probe_freefn.saw`) and hangs on the tree BEFORE this brief's first
  commit (checked out HEAD~1). Two nested calls where neither parks work
  (`probe_two_write`), and TWO nested yield_now calls work (`probe_two_nested`); the
  failing combination is specifically first-call-parks-then-second-call under the
  TaskGroup executor + reactor. Almost certainly an uninitialized frame field / run-
  queue re-entry issue (design 52b/76 territory). Effect: the socketpair ECHO
  (server: read→write) and the httpd worker (read_request→write) hang at RUNTIME; the
  deterministic suite test is therefore a single-nested-call-per-worker send+verify
  round-trip (reliable). Needs a dedicated fix pass.
- **httpd migrated (commit 3):** `.build/scratch/httpd_sw.saw` rewritten to the
  owning API — accept-and-`group.spawn`-per-connection, handler reads the request +
  writes the response over `TcpStream` methods. Compiles + reaches codegen with ZERO
  `unsafe`, ZERO raw fds, ZERO pointers (acceptance met). Kept in scratch (not
  examples/): it is an infinite accept-loop server AND its handler hits the
  read→write two-nested-call runtime bug, so it is not a suite smoke.
- **Tests landed:** `examples/net_owning_echo.saw` (single-nested-call send+verify
  round-trip in a TaskGroup, reliable) + `examples/net_fd_leak.saw` (Deinit-closes-
  exactly-once probe: 600 open+drop with no fd exhaustion). Suite 870.
- Deferred tests (blocked by structure / the pre-existing bug): peer-close→read 0
  (a completed child's fd only closes at group teardown, so a parked reader can't
  observe EOF in-flight); connect-failure→IoError (design-76 `tcp_connect_check` is
  a v1 stub that never reports failure); full echo (read→write = the two-nested-call
  bug). IoError:Error is exercised by the httpd's `{e}` interpolation (compiles).
- Docs: LANGUAGE_SPEC net section rewritten to the owning API (raw layer = private);
  saw-lang skill net section rewritten (+ the runtime-limit warning). CLAUDE.md not
  touched (it never documented std.net).

## Design 81 — Unsafe surface (`unsafe` marker + escape rules + with_ref) (IN PROGRESS)
- **String-escape rider (silent backslash-drop) — LANDED.** `"\r\n"` mis-lexed as
  `"r\n"` (len 2, bytes 114/10): the lexer dropped the backslash on any UNKNOWN
  escape and kept the raw char. Fixed in `read_string`: added `\r` (CR 13) and
  `\0` (NUL 0, counted by len — interior NULs are representable), and any OTHER
  unknown escape is now a clean lex error (``unknown escape `\d` ``) — never a
  silent drop. Supported set is exactly `\\ \" \n \t \r \0 \u{...}` + `\{ \}`.
  CRLF-in-SOURCE already lexes cleanly (a `\r` between tokens is skip_whitespace);
  verified (a real-CRLF .saw compiles + runs). Tests: `string_escapes` (\r\n =
  13/10, \0 counted, \t = 9), `errors/string_unknown_escape`. Docs: spec string
  section + saw-lang skill escape list. Suite 856, bootstrap 17+17, libs 4+4. [81, 07]
- **Fixed-width arithmetic literal-coercion rider — LANDED.** Arithmetic mixing a
  fixed-width local with a bare int literal (`b + 0` for `b: Int32`; suffix locals
  too) ICE'd "i32 != i64" (the checked-arith intrinsic saw i32 vs the platform i64
  literal). Design-77 item 9 covered COMPARISON position only; now extended to
  general ARITHMETIC (`+ - * / %`, both operand orders, all fixed-width kinds): the
  literal adopts the fixed-width operand's type (typechecker `_fixed_width_binop_type`
  range-checks it + types the result as the fixed-width type; codegen reconciles the
  literal's width via the existing `_reconcile_int_width`). Out-of-range literal =
  clean error; Int/Int mixing unchanged. Tests: `fixed_width_arith_literal` (5 ops,
  both orders, suffix local, Int/Int untouched), `errors/fixed_width_arith_literal_
  out_of_range`. Un-flags the design-77 item-8 note. Suite 858, bootstrap 17+17,
  libs 4+4. [77, 65, 53, 81]
- **CORE (marker + escape rules + with_ref) + std/example sweep — LANDED** (commit
  da64eb0). `unsafe <expr>` marks a raw-pointer op whose pointer flows INVISIBLY
  (deref/index/write, pointer arith, binding a pointer produced by a call) in a
  function whose own signature carries no `Unsafe*` type; a cast naming
  `UnsafePointer<T>` (and any op transitively inside it), a pointer field/param/arg
  are already VISIBLE (no marker). Marked domain = signature carries a raw pointer
  OR a `self`-receiver method of a struct with a raw-pointer field (field decl is
  the marker → container access methods stay marker-free; a no-`self` factory like
  Box.make shows the marker). `unsafe`-on-nothing = clean error. Grammar: `unsafe`
  just below assignment, looser than every operator; `unsafe p[0] = 5` marks the
  whole store (parser lifts off the lvalue). `Vector.with_ref`/`with_var_ref`
  (generic-R, `sync` body, non-escaping lend) REPLACE the removed `ref_at`;
  taskgroup executor migrated (returns a `__ResumeOutcome` struct out of the
  borrow). Synthesized coro code exempt by provenance. TESTS (commit follows):
  unsafe_surface_ok + errors/unsafe_{deref,write,arith,binding}_no_marker +
  unsafe_marker_on_nothing (rule rows), vector_with_ref + errors/
  with_var_ref_invalidation + vector_ref_at_removed. DOCS: spec Unsafe Code
  section rewritten (visibility rule + table; the `poke` example now marks its
  store), saw-lang skill unsafe section + ref_at gotcha, CLAUDE.md digest.
  DEVIATION (documented + defensible): the `self`-method-of-a-pointer-field-struct
  domain rule is a faithful reading of "the field decl is the visible marker" that
  keeps the sweep proportionate (container ACCESS methods marker-free, factories
  marked) — it matches the brief's item-3 list exactly (Box.make marked; Vector/
  Arc access not). Suite 867, bootstrap 17+17, libs 4+4. [81, 80, 46, 42, 29]
- **CI rider (Linux `_NSGetArgc`/`_NSGetArgv` link failure) — LANDED.** The first
  GitHub Actions run failed on ubuntu: `std/env.saw` used Apple-only crt_externs
  `_NSGetArgc`/`_NSGetArgv`, so every Linux link died with "undefined reference to
  `_NSGetArgc`". Fixed by UNIFYING (not forking per-OS): the C entry `main` is now
  declared `main(i32 argc, i8** argv)` and its codegen prologue stashes both into
  private module globals `@__saw_argc`/`@__saw_argv` at startup; two seam functions
  `__saw_get_argc()`/`__saw_get_argv()` (in `_declare_argv_runtime`) read them on
  EVERY platform. env.saw's `argc`/`arg` read those seams; the `_NSGet*` externs are
  deleted. Verified: env_simple + an args probe run correctly on macOS (argc/argv +
  argv[i] strings); `--target x86_64-unknown-linux-gnu --emit-ir` shows ZERO
  `_NSGet*` references and `main(i32, ptr)` + the argv globals. Suite 854, bootstrap
  17+17, libs 4+4 green (macOS). Remaining CI verdict awaits the next Actions run
  (Linux link). [81, 41]

## Design 80 — Member visibility (fields + methods) + std under the gate (LANDED)
- **Commit 1 (feature + std/libs/blade sweep + tests) — LANDED.** Struct FIELDS
  and extension METHODS (incl. init/static) are now private-by-default OUTSIDE
  the defining module, same modifier family as top-level (`public`/
  `public(package)`/`public(parent)` per member); same-module unrestricted.
  **Probe verdict: the hole was REAL** — on baseline `v.length = 1000` was
  accepted and a bounds-checked `v.get(500)` read OOB through safe code
  (returned garbage, exit 0). Now a clean compile error (headline lock
  `vis80_vector_length_invariant`). Mechanics: parser/AST visibility on
  StructField + Method; namespace StructSymbol.field_visibility+def_module,
  FunctionSymbol.def_module+satisfies_trait; typechecker gate at field read
  (`_check_member_access`), field WRITE (assignment lvalue in statements.py —
  the headline), memberwise struct literal (after design-66 reinterpretation),
  and method/static/init calls. Module identity keyed on SOURCE FILE so the
  merged prelude is distinguishable: std/builtin = one module `("<std>",)`,
  user code keeps its module_path — kills the prelude bypass for the ACCESS
  check only (codegen compiler-known-ness untouched). Trait-conformance methods
  exempt (satisfies_trait). SYNTHESIZED-ACCESS EXEMPTION BY PROVENANCE:
  coro-transform output (spawn/drive wrappers, synthesized main, frame
  resume/__wake_reason) carries `is_synthesized`; its member access skips the
  gate (reaches std/frame internals by construction — this cleared ALL the
  taskgroup/coro/net breakage: 66× TaskGroup.__enqueue + 66× TaskHandle.result_ptr
  were the tell). **Bypass audit (worked only via the prelude bypass before):**
  every std public method (Vector/Map/Set/String/StringBuilder/Data/Path/Arc/
  Box/Channel/Mutex/Task/TaskGroup/numeric/net/…, 231 methods annotated
  `public`), plus public error/result FIELDS that user code reads — AllocError
  (size/align), Utf8Error (offset), CommandOutput (stdout/exit_code), SlabHead
  (bump/free), Range/RangeInclusive; and cross-module fields in libs+blade —
  semver Version (major/minor/patch), toml TomlError (message/line), blade
  Dependency/Manifest.root_dir/Cli/BuildError/ParseError/LockData.manifest_hash.
  **DEVIATION (documented):** std is ONE module for its internal boundary — the
  user↔std boundary is what closes the hole; std-internal cross-file access
  stays unrestricted rather than per-file-gated (per-file surfaced 182 mostly
  public-API cross-references; the single-module choice is lower churn/risk with
  the identical security guarantee). NOTE: Saw has no struct-destructuring
  patterns, so the brief's "pattern" case reduces to enum-variant matching
  (follows enum visibility, unchanged). Tests: vis80_field_read/write/literal
  _error, vis80_method/static_private_error, vis80_public_members_ok
  (public field/method/static/init + public(package) + trait-conformance),
  vis80_same_module_ok, vis80_vector_length_invariant. Suite 851 (from 843),
  bootstrap 17+17, libs 4+4. [80, 66, 44, 52b]

## Design 77 — Generics & closures completion + accumulated riders (LANDED, subset)
**Status:** items 1 (spawn-Void), 2 (generic-bound propagation), 3 (DF-C2 closures
satisfy Copy) + its get-UAF follow-up, 4 (DF-C1 closures in frames), 7 (Global
rename), 8 (unary minus fixed-width), 9 (comparison literal coercion), 10 (tuple/
destructure across suspend) — **LANDED**. Items 5 (buried suspending method
sub-frame) and 6 (cross-module generic driven) — **RE-LEDGERED** (central
transform surgery, budget spent on item 4; rejections stay clean + anchored).
Item 11 (docs) — spec + skill limits updated below. Two pre-existing bugs FLAGGED
(not regressions): `__drive(f(move owning_arc))` double-frees the moved param
(gmalloc-only; item 4 note); a bare-literal fixed-width LOCAL stores at platform
width (item 8 note). Suite 843 (from 825 baseline), bootstrap 17+17, libs 4+4,
zero xfails throughout.
- **Item 7 RIDER (rename `Global` -> `GlobalAllocator`) — LANDED.** TRUE rename
  (not a `type` alias — that would shatter allocator identity). Swept all `.saw`
  (std alloc.saw struct + `Allocator` conformance, every `= GlobalAllocator`
  default and `GlobalAllocator()` construction across vector/map/set/box/arc/
  channel/mutex/task/taskgroup/stringbuilder/data/net, blade/manifest, libs,
  examples) and the compiler's hardcoded `struct_name="Global"` sites
  (existentials/results/generics/expressions/statements) -> `"GlobalAllocator"`.
  Mangled names shift `$Global` -> `$GlobalAllocator` uniformly (nothing external
  links them; registration + lookup agree since the mangler keys on the struct
  name). `Global` no longer resolves (clean `undefined function` /
  does-not-conform error). Spec + saw-lang skill updated (CLAUDE.md on disk
  carries no `Global` mention). Test `errors/global_renamed_unknown`. Suite 835,
  bootstrap 17+17, libs 4+4. Standing policy oracle: whole suite green.
- **Item 8 RIDER (unary minus on fixed-width ints) — LANDED.** `_check_unary_op`
  now accepts signed fixed-width `Int8`..`Int64` (was `Int`/`Float` only);
  unsigned negation is a clean error ("an unsigned integer has no negation").
  Codegen negates via the existing checked subtract at the operand's WIDTH, so
  `-Int8.min` panics ("integer overflow") like `Int`. A negated integer LITERAL
  const-folds to the negated constant at width (`-128i8` = Int8.min directly,
  not a runtime negation of the bit pattern), and the typechecker range-checks
  the FOLDED value (`-200i8` is a clean error). Un-dodged the platform-Int
  `0 - 1` sites (map/taskgroup) and `0.0 - mantissa` (string) to `-1`/`-mantissa`.
  Tests: `unary_minus_fixed_width`, `unary_minus_int8_min_panics`,
  `errors/unary_minus_unsigned`, `errors/unary_minus_literal_out_of_range`.
  - **FIXED (design 80 run, rider):** a fixed-width int LOCAL from a BARE literal
    is now NARROWED to its annotated storage width. `_generate_let_statement`
    coerces the RHS int value to the annotation's LLVM width before the alloca
    (trunc/sext/zext by signedness); the typechecker already range-checked the
    literal, so it is value-preserving. `-a` on a bare-literal Int32.min local now
    overflow-panics at i32; a wire-format struct built from narrowed locals
    round-trips. Tests fixed_width_let_narrow, fixed_width_let_negate_panic. STILL
    FLAGGED (separate pre-existing): arithmetic mixing a fixed-width local with a
    bare literal (`b + 0` for `b: Int32`) ICEs "i32 != i64" — reproduces with a
    suffix local too; belongs with a fixed-width arithmetic-coercion pass. [53, 65, 80]
  Suite 839, bootstrap 17+17, libs 4+4. [59, 76, 53]
- **Item 9 RIDER (comparison-position literal coercion) — LANDED.** Codegen
  already coerced a bare literal to the other comparison operand's fixed-width
  type, but WITHOUT a range check — `fd < 200` for `fd: Int8` silently compared
  against the wrapped value -56. The comparison typecheck now runs the design-65
  `_check_fixed_width_literal` range check on both operands (a no-op unless one
  side is a bare literal and the other a fixed-width int), so an out-of-range
  literal is a clean error. Un-dodged the seven `(0 as Int32)` comparison casts in
  std/net.saw (`fd < 0`, `!= 0`, `>= 0`, `== 0`). Tests
  `comparison_literal_coercion`, `errors/comparison_literal_out_of_range`. Suite
  841, bootstrap 17+17, libs 4+4. [65, 76]
- **Item 10 RIDER (tuple / destructuring across a suspend) — LANDED.** Two frame
  opt-encoding gaps from design 76: (a) a TUPLE local held across a suspend ICE'd
  ("cannot store {i64,i64} to {i1,{i64,i64}}*") — already fixed incidentally by
  item 4's `_is_optional_type` optional-wrap change (a tuple is a
  LiteralStructType the old "not a struct" guard skipped); locked by
  `coro_tuple_across_suspend`. (b) `let (a,b) = f()` destructuring across a
  suspend DROPPED the bindings ("undefined variable a") — the transform's
  `_collect_frame_locals` only saw plain `let name`, not `DestructuringLet`.
  Now each tuple-pattern leaf is collected as a frame local (typed from the
  source tuple's position) and `let (a,b)=v` lowers to a fresh temp +
  `self.a = __t.0; self.b = __t.1` (auto-wrapping opt-encoded fields). Wildcards,
  nested patterns, and direct-tuple sources all work. Test
  `coro_destructure_across_suspend`. Suite 843, bootstrap 17+17, libs 4+4. [44, 62, 76]
- **Item 5 (A5-rest shape 1: buried suspending method sub-frame) — RE-LEDGERED
  (per the brief's escape hatch; rejection stays clean + anchored).** The FEATURE
  (embed a nested suspending METHOD call `let r = c.step()` as a sub-frame — the
  Part-0b method twin) still needs the design-74 triad: (a) make the phase-1
  frame-prep a FIXPOINT that discovers method callees while preparing (today
  `_collect_calls`/`closure` is a fixed set of free-function names; method
  sub-frames aren't in `fbs`), (b) receiver addressing — `__recv = (&var
  self.recv) as UnsafePointer<Struct>` into the CALLER frame's field (only a
  simple frame-local receiver is addressable; `foo().m()` / `self.f.m()` need
  spilling), (c) build the method frame + thread it into `fbs` so
  `_build_sub_frame`/`_emit_nested_call` (which already accept a `recv_value`)
  drive it. `_build_frame_init` already supports a method `__recv`. Bounded but
  it touches the central transform flow — and item 4's closure-in-frame surgery
  (this same territory) surfaced several subtle exactly-once/UAF hazards that took
  the bulk of this brief's budget, so bundling shape 1 too risks the 834-test bar.
  Workaround is exact and the rejection names it (drive the method directly, or
  wrap in a nested free fn). [74, 44, 45]
- **Item 6 (A5-rest shape 4: cross-module generic driven) — RE-LEDGERED (per the
  escape hatch; rejection stays clean + anchored).** `_pristine_generics` /
  `_pristine_generic_methods` capture ENTRY-module templates only, so
  `_build_fn_mono` / `_splice_fn_mono` return False for an imported template and
  the nested/driven generic call is rejected (anchored) by `_classify_call`.
  Lifting needs: (a) snapshot imported-module generic templates into the pristine
  maps (keyed to avoid cross-module name clashes), (b) design-68 canonicalization
  — the mangled instantiation key computed in the transform must agree
  byte-for-byte with codegen's cross-module monomorphization symbol, or the
  frame's callee and codegen's mono double-define / mismatch. The
  mangling-agreement surface is exactly design-68 territory and risky against
  bootstrap (blade is generic- and multi-module-heavy). Deferred with the same
  budget reasoning as shape 1. [74, 68]
- **Item 1 (spawn-Void ICE) — LANDED.** `spawn { void_body }` ICE'd building the
  `{i8*, i8*, void}` control block (a `void` struct field is illegal LLVM). The
  result slot becomes a 1-byte placeholder for a Void body (never stored/read in
  the trampoline); `UnsafePointer<Void>` now lowers to `i8*` (C `void*`) and
  `sizeof<Void>()` folds to 0, so the GENERIC `Task<Void>.join`/`deinit` stdlib
  paths (result cast/load/dealloc-size) monomorphize cleanly. Both explicit-join
  and drop-joins-it exercised. Test `spawn_void_body`. Suite 826, bootstrap 17+17,
  libs 4+4. [75]
- **Item 2 (generic-bound propagation) — LANDED.** A generic forwarding its own
  bounded type param to another generic's bound (`inner<T>(w)` inside
  `middle<T: Seed>`) errored "type `T` does not implement trait `Seed`". Fix:
  the general-trait bound check in `_check_generic_call` now routes an ABSTRACT
  type-param argument through `_bound_satisfied` (bounds-environment lookup —
  satisfied iff the enclosing signature declares the bound), matching the
  existing Send/Sync/Equatable handling. Codegen twin: a generic call inside a
  generic body substitutes its type args through the monomorphization context
  before instantiating (else it recursed over the abstract `T`). Negative case
  (forward without declaring the bound) still a clean anchored error. Tests
  `generic_bound_propagation`, `errors/generic_bound_propagation_unmet`. Note:
  un-dodging design-74 shape-3 tests to forward a type param into the coro
  promotion path is left to items 5/6 (that combines with the promotion surface,
  not the standalone bound check fixed here). Suite 828, bootstrap 17+17, libs
  4+4. [74]
- **Item 3 (DF-C2: closures satisfy `Copy`) — LANDED.** An escaping closure is
  ImplicitCopy (design 73) and now satisfies the umbrella `Copy` bound
  (`type_satisfies_copy_bound` accepts `TypeKind.FUNCTION`), so
  `Vector<() -> Int>` is ExplicitCopy and its `.copy()`/`.get()` work. Three
  wiring fixes to make it BALANCED (the naive enable exit-133'd): (a) codegen
  `.copy()` on a closure receiver emits the env retain (`_emit_closure_env_retain`)
  instead of a bitwise alias; (b) the ROOT cause of the leak/double-free — the
  `escaping` bit is not part of the mangling and was lost when a container's
  closure type arg was reconstructed from the mangled key, so `_needs_cleanup`
  and the Copy-bound predicate (both gate on `func_is_escaping`) treated the
  element as non-owning. `_ensure_monomorphized_struct` now re-marks a stored
  closure type arg escaping (`_mark_stored_closure_escaping`, recursing through
  Optional/array/tuple), which is safe (a function type reaching a container
  type-param slot is always a stored value, never a borrowed param). Exact-count
  Arc-capture probe: deinit runs exactly ONCE through copy+get. Tests
  `closure_vector_copy_get`, `closure_vector_deinit_once`,
  `closure_satisfies_copy_bound`. Suite 831, bootstrap 17+17, libs 4+4. [73, 54]
- **Item 3 follow-up (get use-after-free) — LANDED.** The item-3 commit had a
  latent flake: `Vector<() -> Int>.get` returned a closure element WITHOUT
  retaining its env, because `_transfer_needs_copy`'s copy-with-retain branch
  only covered ImplicitCopy STRUCT/ENUM/OPTIONAL — a closure (no conformance
  name, so `_get_cleanup_behavior` = "none") fell through to bitwise. The
  read-out copy's teardown released an env it never retained: a use-after-free
  that intermittently crashed (exit 133 under load; deterministic under
  libgmalloc). Fix: `_transfer_needs_copy` retains an escaping-closure element
  read out of a container slot (ArrayIndex/MemberAccess/TupleIndex), mirroring
  the design-65 aggregate copy-with-retain; a bare Identifier closure
  (move/borrow-lend) is untouched. Verified deterministic-clean under
  libgmalloc + MallocScribble (20x). Suite 831, bootstrap 17+17, libs 4+4. [73]
- **Item 4 (DF-C1: closures in coroutine frames) — LANDED.** A closure created in
  a driven body is now supported: (1) closure-typed frame field via a new
  `opt_closure` encoding (Optional-wrapped, drop-flag = None/Some, forced `sync`
  since a stored closure cannot be driven; frame re-registration no longer trips
  "redundant escaping" — `_clear_escaping` clears the bit on the field type so
  re-stamping is clean); (2) a CALL `f(args)` on a frame closure local rewrites to
  an indirect field call `self.f(args)` (typechecker force-unwraps the opt field
  on a `__Frame_*` struct; codegen extracts the inner closure); (3) captured frame
  locals are MATERIALIZED as real locals before the closure (`let x = self.x!.copy()`
  + a `move` capture) so the closure captures by value — crucially `move`, not a
  persistent function-local, because a resume state machine would re-drop an owning
  local on every re-entry. Codegen `MemberAccess`-to-optional wrap now uses
  `_is_optional_type` so a struct/closure inner wraps to Some. Tests
  `coro_closure_local_call`, `coro_closure_deinit_once` (exact deinit-once,
  gmalloc-clean), `coro_closure_taskgroup` (spawned frames own closures). All 3
  verified clean under libgmalloc. Suite 834, bootstrap 17+17, libs 4+4. [73, 74, 44, 52b]
  - **FIXED (design 80 run, rider): `__drive(f(move owning_arc))` no longer
    double-frees the moved param.** The `__drive_<f>`/`__spawn_<f>` wrapper now
    `move`s each non-reference param into the frame (`_frame_param_arg`), so the
    frame is the sole owner (dropped once at teardown) and the wrapper param's drop
    flag is cleared. Exact-count lock coro_moved_arc_param_deinit_once (3 refs, no
    UB); single-ref case verified clean under libgmalloc. Original note follows.
  - **FOUND (pre-existing, FLAGGED): `__drive(f(move owning_arc))` double-frees the
    moved param.** A driven function taking an owning ImplicitCopy value (Arc) as a
    param, moved in at the drive site, DOUBLE-DROPS it: the synthesized
    `__drive_<f>` wrapper builds the frame from the param `Identifier` WITHOUT
    retaining into the opt-encoded field (`_needs_copy_for_struct_init` sees the
    field type `Arc?` = Optional -> `_get_cleanup_behavior` = "none", so no retain),
    yet the param binding keeps its drop flag AND the frame drops its field. Benign
    under the normal/scribble allocator (the 2nd Arc deinit reads a freed-but-mapped
    strong word and no-ops), but a real read-after-free (deterministic SIGSEGV under
    libgmalloc). Repro: `func run(a: Arc<Res>){...__suspend()...}; __drive(run(move a))`
    — NO closure needed. Reproduces at HEAD (pre-item-77-4). An owning value created
    as a frame LOCAL (not a moved param) is clean. Fix belongs with the frame-init
    retain path (opt-encoded ImplicitCopy field construction must retain, or the
    driver must move-clear the param). Deferred from item 4 (orthogonal to closures;
    the deinit-once test uses a frame-local Arc to stay clean). [44, 52b]

## Design 76 — A4 IO reactor + A6 extern-blocking + A3 remainder (IN PROGRESS)
- **Commit 1 (A4 reactor + std.net + A3 io-cancel; ST + entry executor):** A
  process-global **kqueue (macOS) / epoll (Linux)** reactor (compiler seams in
  codegen/core.py, `_declare_io_runtime`): a single lazily-created, race-safe
  (atomic cmpxchg) reactor fd; `saw_reactor_register(fd, write)` arms ONE-SHOT
  read/write interest; `saw_reactor_poll(timeout_ms)` blocks in kevent/epoll_wait
  (< 0 = forever) and returns the ready count — the kernel owns the interest set,
  so register/poll are each ONE syscall (why kqueue/epoll beats poll(2) for a
  global reactor). OS-divergent socket bits stay in shims (`saw_set_nonblocking`,
  `saw_errno_would_block`, `saw_sin_set_family`); hosted-only (freestanding: extern
  decls, net never loaded). **`io_wait(fd, write)`** is a new suspend INTRINSIC
  (like `yield_now`): the coro transform lowers it to `saw_reactor_register` +
  suspend with a NEGATIVE (io-park) wake reason; codegen fallback (outside a frame)
  is register + blocking poll. The ST group executor (`__run_all_st`) + the entry
  executor gained an io phase: when nothing is runnable, poll the reactor with the
  earliest sleep deadline as the timeout (never busy-wait, never block while a
  frame is runnable), wake ALL io-parked tasks on return (coarse level-triggered
  retry — a still-not-ready task re-registers via oneshot), advance sleepers only
  when the poll TIMED OUT (events==0). **std/net.saw**: minimal nonblocking TCP as
  the channel-style idiom (NON-suspending `tcp_try_read`/`tcp_try_write`/
  `tcp_try_accept` + `io_wait` in the caller task body — a suspending std free fn
  CANNOT embed as a sub-frame since the transform is entry-module-only, same reason
  `Channel.receive()` is inline-lowered); `tcp_listen`/`tcp_local_port`/
  `tcp_connect_start`/`tcp_connect_check`/`tcp_socketpair`/`tcp_close`/
  `net_buffer`/`net_bytes_to_string`. Zero per-call heap in the socket paths: a
  typed `SockAddrIn` stack struct (design-58 natural layout) + `(&sa) as
  UnsafePointer` (design-42), htons/ntohs in Saw. A3: cancellation observed at the
  io suspension point via the cancel-check-before-`io_wait` idiom (mirrors the
  channel cancellation-aware receive). Tests (loopback/socketpair only,
  deterministic on counts/contents, time-bounded): `net_socketpair_echo`,
  `net_loopback_echo` (listen/accept/connect/read/write), `net_io_sleep_interleave`
  (never-block: sleeper honored while an fd is idle + io wake), `net_io_main_entry`
  (entry-executor reactor path), `net_io_cancel` (A3 + deinit oracle). Suite 823,
  bootstrap 17+17, libs 4+4.
  - **FOUND (pre-existing, flagged): a TUPLE local held across a suspend ICEs**
    ("cannot store {i64,i64} to {i1,{i64,i64}}*") — the coro frame opt-encodes the
    tuple slot but the store site doesn't wrap it; reproduces with plain
    `yield_now` (NO io). `let (a,b) = f()` DESTRUCTURING across a suspend also
    drops bindings. Orthogonal to design 76 (frame opt-encoding of non-POD-but-
    cleanup-free locals). Worked around in tests (keep only `Int` across the
    suspend; confine tuples to non-suspending helpers). Fix belongs with the coro
    frame-encoding work. [44, 76]
  - **DEFERRED (A4 remainder, re-ledgered): first-class inline-lowered
    `tcp_read`/`tcp_accept`/`tcp_write`/`tcp_connect`** (receive()-style, so the
    park loop is not hand-written in the task body). The transform being
    entry-module-only forces the channel-idiom shape today; the ergonomic lift is a
    `recv_by_id`-style recognition + `_emit_io_call` inline lowering. [62, 76]
  - **DEFERRED (A3 remainder): waking an ALREADY-io-parked task on cancel.** A task
    parked in `io_wait` on a permanently-idle fd, cancelled by a peer, won't observe
    `cancelled()` until the reactor poll returns (needs a self-pipe/eventfd wake).
    Same liveness class as the design's "join on a task that never observes
    cancellation blocks"; the landed model observes cancel at the check BEFORE
    parking. [18, 76]
    - **CLOSED** by design 102 item 2 (reactor self-wake pipe + `__is_cancelled()`
      precise wake + pre-poll cancelled scan + cancel propagation into sub-frames).
- **Commit 3 (A6 honest subset: `extern blocking` sync-reject + freestanding
  reject):** the A6 FRONT-END was already wired (parse `extern "C" { blocking func
  ... }`, `is_blocking` on the AST, blocking-extern as an effect suspension
  source). This commit closes the two type-system halves: (1) a blocking-extern
  call in a `sync` context is rejected by the effect checker, anchored, naming the
  extern + suspension path (locked by `errors/blocking_extern_sync_reject`); (2)
  declaring an `extern blocking func` in the FREESTANDING profile is a clean
  registration-time error (no hosted pool). Suite 825, bootstrap 17+17, libs 4+4.
  - **CLOSED by design 103** (thread-per-call offload + coro lowering; see the design
    103 entry). The worked-out design below is what landed (thread-per-call v1 in
    place of a pool; `__blk_start` codegen intrinsic + pre-frame-builder classify).
  - **DEFERRED (A6 runtime offload — re-ledgered with the worked-out design):** the
    hosted pool + coro lowering that makes a blocking call actually RUN in a task.
    Today a blocking call inside a driven/spawned body is REJECTED (the synthesized
    `resume` is `sync`, so the blocking suspension source trips the sync check — an
    honest rejection, not a miscompile, though the message points at
    `__Frame_*.resume`). Design (reuses ALL the A4 infra): C shims
    `saw_offload_start(fnptr, arg) -> job` / `saw_offload_done(job)` /
    `saw_offload_pipe_fd(job)` / `saw_offload_take(job)` — start spawns a
    thread-per-call that runs the extern, stores the result, and writes a byte to
    the job's pipe; the call site desugars (BEFORE typecheck, so the frame builder
    sees the new locals) to `let j = __blk_start(slow(arg)); while __blk_done(j)==0
    { io_wait(__blk_fd(j), 0) }; let r = __blk_take(j)`. The two frictions that make
    it non-trivial: (a) function-address is NOT expressible in Saw (`slow as Int`
    errors), so `__blk_start` must be a CODEGEN intrinsic that resolves the extern's
    ir.Function and bitcasts it to i64; (b) the desugar must run pre-typecheck (or
    register `__job` with the frame builder) so the offload locals are
    frame-resident. v1 restriction: blocking externs typed `(Int) -> Int` (the
    offload thunk is `i64(*)(i64)`); multi-arg is future. [18, 22, 76]
- **Commit 2 (MT reactor integration + std.net named constants):** the design-75
  multi-threaded worker (`__tg_worker`) gained the io phase. CHOICE (reported):
  **poll on an idle worker with a BOUNDED timeout** (earliest sleep deadline, else
  a 50 ms cap) — bounded because with EV_ONESHOT + concurrent pollers only one
  worker receives each event, so a worker that missed it must retry rather than
  block forever (no lost-wakeup hang). The scan tracks io-parked (`remaining < 0`)
  separately from sleepers; when nothing is runnable and no peer is resuming, an
  idle worker polls the reactor OUTSIDE the lock, then (idempotently) wakes ALL
  io-parked tasks and advances sleepers only if the poll timed out. Redundant
  concurrent polls are harmless (wake-all is idempotent); a dedicated single poller
  thread is a future refinement. NOTE: the Send-on-frames gate poisons
  `UnsafePointer`, so an MT-spawned frame cannot hold a read buffer across a
  suspension — MT io parks on write-readiness (Int-only frame). std.net magic
  numbers are now named module statics (`AF_INET`/`SOCK_STREAM`/`WOULD_BLOCK`/
  `LOOPBACK_BE`/...); std-module statics are NOT visible cross-module (a known
  export gap), so the `io_wait` direction stays a literal 0/1 in user code. Test:
  `net_threads_io` (`TaskGroup(threads: 2)`, two io-parked frames woken; stable
  25x). Suite 824, bootstrap 17+17, libs 4+4.

## Design 75 — A2: multi-threaded work-stealing executor + Send-on-frames (LANDED)
- **Commit 1 (surface + Send-on-frames gate; execution still single-threaded):**
  `TaskGroup(threads: N)` labeled init landed (a second `init(threads: Int)`; the
  default `TaskGroup()` and `threads: 1` stay the byte-identical single-threaded
  engine — `workers` field clamps to >=1). The Send-on-frames gate: a `let/var
  group = TaskGroup(threads: ...)` binding is flagged `is_mt_group` in the
  typechecker (`_check_let_statement` via `_is_multithreaded_taskgroup_init`,
  handles the `StructInit [resolved: init(threads)]` form); `group.spawn(f(...))`
  into such a binding records `f` in `typechecker._mt_spawn_roots`; the coroutine
  transform (`_check_spawn_frame_send`) then walks the spawn root frame's params +
  across-suspend locals + embedded callee sub-frames and rejects the FIRST non-Send
  value, naming it + its type, anchored at the function (design 74 A8). Reuses the
  same structural `namespace.is_send` as the 21b `spawn { }` capture audit
  (`UnsafePointer`/bare `Vector` poison; Int/Bool/Float/String/Arc/Mutex/Channel
  pass). Single-threaded groups skip the gate entirely. DEVIATION (documented):
  mt-ness is tracked on the group's local binding, so a `TaskGroup(threads:)`
  spawned into DIRECTLY is gated; passing the group through an opaque helper before
  spawning is not yet traced (spawn directly for the gate — future interprocedural
  lift). Tests: `taskgroup_threads_send_accept` (Int/String/Channel accepted, sum
  oracle), `errors/taskgroup_threads_nonsend_reject` (Vector param named). Suite
  813, bootstrap 17+17, libs 4+4.
- **Commit 2 (the multi-threaded fork-join executor):** `TaskGroup(threads: N)`
  with N>=2 now really runs on N OS threads. CHOICE (reported): the sanctioned
  simpler shape — ONE mutex-protected SHARED run queue (injector) drained by N
  workers, NOT per-worker lock-free deques (simplicity/soundness over throughput
  v1). Model = FORK-JOIN: a drain is triggered lazily by `join()`/Deinit (via
  `__run_all` -> `__drain_mt` when workers>=2 && lock present), spawns N `Task<Int>`
  workers through the 21b engine (each running the free fn `__tg_worker(addr: Int)`;
  the group's own address crosses the `spawn` boundary as a Send `Int`), then joins
  them all — pthread_join is a full barrier making every `__result` visible before
  `join()` force-unwraps. Each worker LOCKS, claims the first runnable (not-done,
  not-active, remaining==0) frame by setting an `active[i]` flag, UNLOCKS, calls
  `resume()` outside the lock, then re-locks to record Pending(remaining=wake) /
  Done. D6 confinement holds: `active[i]` guarantees one worker per frame; `tasks`
  is read-only during a drain (enqueue is main-thread-only, main is blocked joining
  workers, so the queue never resizes) — only done/remaining/active are mutated,
  always under the lock; frames live at stable heap addresses inside their boxes.
  Sleep: when no frame is runnable and none active, ONE worker advances the clock by
  the earliest deadline UNDER the lock and subtracts it from all sleepers (shared
  timer, no per-worker wheel); when a peer is mid-resume, free workers spin+nap 1ms
  (no cond var -> no lost-wakeup class). Cancellation across tasks:
  `TaskHandle.cancel_addr() -> Int` hands the `__cancel` word's address (Send) to a
  canceller task, which sets it; the victim observes via `cancelled()` (set-once
  monotonic byte -> race-free, eventually consistent). The default `TaskGroup()` and
  `threads: 1` still route to `__run_all_st` (the byte-identical pre-75 loop, no
  threads/lock). Send gate extended to the spawn root's RETURN type (it crosses
  worker->main via join). Battery (all deterministic on counts/sums, time-bounded,
  each verified stable 30-50x): `taskgroup_threads_parallel_sum` (100 tasks/4
  workers, sum 4950 — stress), `_producer_consumer` (channel receive across
  workers), `_sleep` (cross-worker earliest-deadline), `_cancel` (cancel from
  another task), `_deinit_once` (result dropped exactly once under stealing, static
  atomic count = 6). Suite 818, bootstrap 17+17, libs 4+4, -O0 spot-checked.
- **FOUND (pre-existing, flagged): `spawn { void_body }` ICEs.** A 21b `spawn { }`
  whose closure returns `Void` builds a task control block `{i8*, i8*, void}` — an
  invalid LLVM struct ("void type only allowed for function results"). Worked
  around in the executor (worker bodies return `Int`); a proper fix is to omit the
  result slot for a Void spawn body. [21b, 75]
  - **CLOSED** — 21b `spawn { void }` fixed by design 77 item 1; the cooperative
    `group.spawn(void)` + the executor return-Int workaround closed by design 102 item 1.

## Design 74 — A5-rest: finish effect-polymorphism shapes + A8 anchors (IN PROGRESS)
- **Commit 1 (A8 — diagnostic anchoring):** A coroutine-transform rejection
  (`CoroTransformError`) now anchors at the user's `file:line:col` with a source
  snippet through the shared `ErrorReporter`, exactly like a type error — it was
  a bare message pointing nowhere. `CoroTransformError` carries `source_file`;
  `_FrameBuilder` stashes `self.src_file` from its function; sawc.py surfaces the
  rejection via `reporter.error(...)` (falling back to the entry file for a
  single-file program). Locked by `examples/errors/coro_reject_anchored.saw`
  (asserts the `file:line:col` anchor on a buried-suspend rejection). Suite 808,
  bootstrap 17+17, libs 4+4. [74, 69]
- **Commit 2 (shape 2 — driven method on a GENERIC struct):** `__drive(b.run())`
  for `b: Holder<Int>` now works. The typechecker monomorphizes the method over
  the STRUCT's type params (T->Int): pristine generic-struct-extension methods are
  snapshotted (`_pristine_generic_struct_methods`), the drive site queues a
  clone+substitute+re-check (deferred to `_process_effect_monos` so it never
  clobbers the mid-body scope), and records the concrete driven method carrying
  the concrete receiver SawType (`Holder<Int>`). The coro transform reads that
  table, builds the frame with `__recv: UnsafePointer<Holder<Int>>` (new
  `recv_saw_type` param on `_FrameBuilder`), and `_rewrite_drive_sites` casts to
  the type-arg-preserving pointer. Two instantiations coexist (Int + Bool). A
  general fix fell out: member access on a concrete instantiation of a generic
  struct whose `struct_info` is the generic symbol now substitutes the field type
  by the receiver's type args (`self.value: T` -> `Int`) — normal instantiations
  keep their monomorphized symbol and skip it. Combined struct-generic AND
  method-generic driven methods stay a clean, anchored rejection (still A5-rest).
  Tests: `coro_generic_struct_method` (both instantiations),
  `errors/coro_generic_struct_and_method_generic_unsupported`. Suite 809,
  bootstrap 17+17, libs 4+4. [74, 70]
- **Commit 3 (shape 3 — nested suspending generic calls):** A driven body can now
  make NESTED suspending generic calls (`let a = leaf<Slow>(...)`). A new
  transform pre-pass `_promote_nested_generic_calls` runs after the effect fixpoint
  (so per-instantiation `.suspends` is known): it walks each driven body (and,
  transitively, spliced instantiation bodies) for a drivable-position generic call
  whose instantiation suspends, splices the concrete instantiation via a new
  typechecker helper `_splice_fn_mono` (clone+substitute+register+re-check under
  the stashed entry-module namespace `_entry_module_ns`, so locals get resolved
  types), rewrites the call site to the mangled symbol, and seeds it into the
  driven closure. The existing Part-0b sub-frame embedding then handles it. The
  closure walk now SKIPS a template reached via an effect edge (its suspending
  instantiations were promoted + seeded); an un-promotable nested generic call
  (cross-module = shape 4) keeps its generic call and is rejected — with a
  workaround + user-anchored line — by `_classify_call`. Multiple instantiations of
  one generic coexist; non-suspending nested generic calls are left for codegen.
  Tests: `coro_nested_generic_call` (two instantiations + a non-suspending generic
  left alone), `coro_nested_generic_deep` (two-deep nesting). Suite 810,
  bootstrap 17+17, libs 4+4. [74, 44]
- **DISCOVERED (pre-existing, NOT shape 3): generic-bound propagation gap.** A
  generic fn forwarding its own type param to another generic (`func middle<T:
  Seed>(w: T) { inner<T>(w) }`) errors "type `T` does not implement trait `Seed`"
  even though the bound is declared — reproduces with NO driving (orthogonal to
  coroutines; a typechecker generics issue). Nested shape-3 tests use concrete type
  args at each level to avoid it. Fix is disproportionate to design 74 — flagged
  for a generics brief. [74]
- **Commit 4 (shape 1 rejection + A8 for methods + docs):** A BURIED suspending
  METHOD call in a driven body (`let r = c.step()`, `Counter.step` suspends) is now
  a CLEAN, user-anchored rejection at the exact call site naming the workaround
  (`__drive(recv.step())` directly, or wrap in a nested free fn) — it previously
  lowered in place and tripped a confusing sync-violation on the synthesized
  `__Frame_*.resume`. The transform builds a (struct, method) suspend set from the
  effect nodes and `_collect_calls` detects the buried call. Docs: spec concurrency
  limits + saw-lang skill limits updated for shapes 2/3 landed and shapes 1/4 (+
  combined struct-and-method-generic) remaining. Test:
  `errors/coro_buried_suspending_method` (asserts message + `file:line:col`). [74]

## Design 74 — RE-LEDGERED remainder (attempted, deferred with analysis)
- **Shape 1 FEATURE (method sub-frame embedding) — DEFERRED.** The rejection is now
  clean + anchored (commit 4). The FEATURE (embed a nested suspending method call
  as a sub-frame, the Part-0b method twin) needs: (a) making the phase-1 frame-prep
  a FIXPOINT that discovers method callees while preparing (today `closure` is a
  fixed set of free-function names; method sub-frames aren't in `fbs`), (b)
  receiver addressing — `__recv = (&var self.recv) as UnsafePointer<Struct>` into
  the CALLER frame's field for the receiver (only a simple frame-local-identifier
  receiver is addressable; `foo().m()` / `self.f.m()` need spilling), (c) building
  the method frame + threading it into `fbs` so `_build_sub_frame`/`_emit_nested_
  call` (which already accept a `recv_value`, see `_build_frame_init`) drive it.
  `_build_frame_init` already supports a method `__recv`; the missing piece is the
  discovery/prep fixpoint + receiver addressing. Bounded but touches the central
  transform flow — deferred to keep the 810-test bar safe; workaround is exact and
  the rejection names it. [74, 44, 45]
- **Shape 4 (cross-module generic driven templates) — DEFERRED.** `_pristine_
  generics` / `_pristine_generic_methods` capture ENTRY-module templates only, so
  `_build_fn_mono` / `_splice_fn_mono` return False for an imported template and the
  nested/driven generic call is rejected (anchored) by `_classify_call`. Lifting
  needs: (a) snapshot imported-module generic templates into the pristine maps
  (keyed to avoid cross-module name clashes), (b) design-68 canonicalization — the
  mangled instantiation key computed in the transform must agree byte-for-byte with
  codegen's cross-module monomorphization symbol, or the frame's callee and
  codegen's mono double-define / mismatch. Deferred: the mangling-agreement surface
  is exactly design-68 territory and risky against bootstrap (blade is generic- and
  multi-module-heavy). Rejection stands with a workaround. [74, 68]
- **Rider DF-C1 (closures inside driven/suspending frames) — DEFERRED (attempted).**
  Confirmed both shapes still error on this tree (as design 73 flagged): a closure
  local CALLED in a driven body errors "undefined function `f`" (the resume method
  doesn't rewrite `f(n)` on a frame-local closure to an indirect `self.f(n)` call),
  and a closure HELD across a suspend errors "redundant `escaping`" (the frame
  struct field for a closure trips the typechecker's "closure types outside
  parameter position are always escaping" check). The fix is a genuine multi-part
  feature: (1) type the closure frame field without tripping the escaping check,
  (2) rewrite a frame-local-closure CALL to an indirect closure call on `self.f`,
  (3) closure env retain/release exactly-once across the suspend + at frame drop.
  This is closure-in-frame representation surgery in both the typechecker and the
  transform — disproportionate to bundle safely here; re-ledgered per the rider's
  own escape clause. Blocks a TaskGroup frame that OWNS a closure. [73, 74, 44, 52b]
- **Rider DF-C2 (`Vector<closure>` satisfies the generic `Copy` bound) — DEFERRED.**
  Unchanged from design 73: the container element-copy path must route through the
  closure-env retain (a naive enable crashed exit 133). Independent of the coroutine
  transform work in this brief; belongs with the container-Copy-glue work. [73, 54]

## Design 72 — Small fixes: L12/M1, L9, erased-error downcasting (LANDED)
- **Commit 1 (L12/M1 — fixed-array builtins):** Fixed arrays `[T; N]` gained two
  builtin members and only these two: `.len()` (folds to the compile-time
  constant N as `Int`) and `.swap(i, j)` (the M1 escape hatch — bounds-checked
  in-place element swap, mirroring `Vector.swap`; requires a `var` receiver). The
  typechecker intercepts array-typed method calls (`_check_array_method`) before
  the old "non-struct type" error: `len`/`swap` typed + tagged, anything else a
  clean "fixed array has no method X; only .len()/.swap are available, user
  extensions on array types are not supported" error. Constant `swap` index OOB is
  a compile error (mirrors `a[const]`); dynamic index gets the always-on runtime
  bounds check. Parser: `extension [Int; N]` now emits "extension methods on array
  types are not supported" instead of the generic "Expected type name". Codegen
  `_generate_array_builtin`: `len` -> const; `swap` addresses the array in place
  via `_get_lvalue_pointer` + GEP, loads/stores the two slots (no element copy).
  Spec fixed-array section updated; `.len()` de-illustrativized. Tests:
  `array_len_builtin`, `array_swap_builtin`, `array_swap_immutable_error`,
  `array_no_extension_error`, `array_unknown_method_error`,
  `array_swap_const_oob_error`, `array_swap_dynamic_oob_panic`. Suite 796,
  bootstrap 17+17, libs 4+4. [72]
- **Commit 2 (L9 — Equatable over Optional/array members):** The synthesis
  widening was ALREADY landed (commit e60d189: `is_equatable` holds for `T?` iff
  `T` is and `[T; N]` iff its element is; codegen `_emit_optional_equals` /
  `_emit_array_equals` wired into the recursive `_emit_equals`, so struct-field,
  tuple, and direct comparisons all reach them; tests
  equatable_optional_field/_direct/_string_synth/_array_field). Design 72 closes
  the remaining brief case — an enum whose payload is an Optional — with
  `equatable_enum_optional_payload` (`Filled(value: Int?)`: Some==Some,
  Some!=Some-diff, None==None, None vs Some). Suite 797. [72]
- **Commit 3 (erased-error downcasting via type-ids):** Every vtable gains a
  `type_id` HEADER slot (layout now `[dtor, size, align, type_id, methods…]`;
  dispatch base 3->4). Type-id scheme: a monotonic counter memoized by MANGLED
  NAME (`_type_id_for`), so the id the vtable bakes in matches the id `is`/`take`
  compute for the same concrete type in this module (simplest stable scheme; no
  reflection surface). Builtins on `Box<any Trait>` (explicit type arg, no
  inference): `b.is<T>() -> Bool` (loads/compares the vtable type-id; a borrow)
  and `b.take<T>() -> T?` — CONSUMES the box: on an id hit it moves the payload
  out and frees the shell WITHOUT the dtor, `Some(T)`; on a miss it runs the full
  box drop, `None`. take-on-miss CHOICE: consumes UNCONDITIONALLY (leave-intact
  fights the move checkpoint), so `is<T>()` first is the branch-without-consume
  path — the typechecker marks the receiver moved, codegen clears its drop flag.
  Deinit is exactly-once on both paths (hit: at the moved-out value's scope; miss:
  in take). T must be a concrete conforming type (clean error otherwise). Codegen
  drop refactored into `_erased_run_dtor` + `_erased_dealloc_shell`. Catch-side
  match-on-concrete sugar OUT (future). Tests: erased_downcast_is_take,
  _deinit_once (hit+miss balance), _error_retry (Box<any Error> from an erased
  Result — the motivated case), _generic (downcast in a monomorphized body),
  _nonconforming_error, _use_after_take_error. Spec existentials + error sections
  + saw-lang skill updated. Suite 803, bootstrap 17+17, libs 4+4. [72, 51, 56]

## Design 73 — Closures become ImplicitCopy (refcounted env) (LANDED)
- **Commit 1 (core + tests):** An escaping closure's heap env now leads with an
  atomic refcount word (platform-width, String-style monotonic retain / release
  ordering + acquire fence at zero). Closures joined the **ImplicitCopy** family:
  `_is_no_copy_type(FUNCTION)` -> False, `_is_implicit_copy_type`/`_check_*_containment`
  treat an escaping closure like `String`. `let g = f` is legal again (retired
  71's NoCopy binding rejection + `closure_copy_requires_move_error`). Retain
  (`_generate_copy`/`_emit_retain_at` FUNCTION) bumps the env refcount; drop
  (`_emit_closure_drop_at`, now via `_emit_closure_env_release`) decrements and
  runs the dtor (captures release + free) only at zero; the spawn trampoline uses
  the SAME release (frame owns +1, exactly-once across the thread boundary). Null
  env (capture-less) => no refcount word, trivially copyable (retain/drop null-
  guarded). **RESIDUAL GAP CLOSED:** an owning closure in a copyable struct copied
  N times -> dtor once at the last owner (positive test). Also fixed a pre-existing
  leak the model surfaced: an escaping closure LENT into a non-escaping param must
  not clear the caller's drop flag (`closure_lend` marker). Tests:
  `closure_copy_binding`, `closure_copyable_struct_copied`, `closure_spawn_arc_balance`,
  `closure_captureless_copyable`, `closure_borrow_lend_balance`; 71's battery
  updated to refcounted expectations (all exactly-once). Suite 807, bootstrap
  17+17, libs 4+4. [73, 71]
- **Commit 2 (docs):** spec closures section rewritten (ImplicitCopy, refcounted
  env, exactly-once teardown, lend, null-env fast path); saw-lang skill Copy-tier
  table + gotcha updated. [73]
- **Findings (flagged, NOT fixed — out of design-73 scope):**
  - **DF-C1 (pre-existing coro-transform gap).** A closure LOCAL called inside a
    driven/suspending function (`let f = {...}; ... f()`) errors "undefined
    function f"; a closure held across a suspend in a frame errors "redundant
    `escaping`". Both fail identically on baseline (confirmed via stash) — a
    coroutine-transform frame-building limitation, unrelated to refcounting. Blocks
    expressing a TaskGroup frame that OWNS a closure; the thread-`spawn` balance
    test covers the cross-boundary exactly-once claim instead. [44, 45, 52b, 73]
  - **DF-C2 (deferred).** Closures deliberately do NOT satisfy the umbrella `Copy`
    bound yet: `Vector<() -> Int>.copy()`/`.get()`, Set/Map with closure elements
    need the container element-copy path routed through the refcount retain (a
    naive enable crashed exit 133). Clean compile error until wired. [54, 73]

## Design 71 — Closure Deinit (LANDED)
- **Commit 1 (core):** Closures now carry their own env destructor
  (`{fn_ptr, env_ptr, dtor_ptr}`, design 71). An escaping closure binding is an
  OWNING value: `_needs_cleanup(FUNCTION-escaping)` + `_emit_closure_drop_at`
  (null-dtor no-op) run the env destructor at the closure's own drop (LIFO +
  drop flags), releasing owned captures exactly once and freeing the heap env.
  Removed the creating-frame EARLY RELEASE: a `move` capture now clears the
  source binding's drop flag (this ALSO fixed a latent thread-`spawn`
  double-free of a move-captured NoCopy — deinit ran at frame exit AND in the
  trampoline). Copy class: escaping closures are NoCopy (move-only) — a bitwise
  copy aliased the heap env (double free, exit 133); forwarding an escaping
  closure into a NON-escaping/borrowing slot stays a lend (no move). Closure
  FIELDS excluded from NoCopy CONTAINMENT so capture-less-closure structs stay
  copyable. Exact-count battery: `closure_deinit_{drop_order,arc_balance,
  struct_field,vector,returned,dropped_uncalled,called_then_dropped,
  conditional_move}` + `closure_copy_requires_move_error`. Suite 789, bootstrap
  17+17, libs 4+4 green. RESIDUAL GAP (was: an owning closure in a COPYABLE
  struct that is then copied double-freed) — **CLOSED by design 73**: closures
  became ImplicitCopy (refcounted env), so the struct copy retains the env and the
  dtor runs once at the last owner. The NoCopy binding rejection above was retired
  in the same move. [71, 73]

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
