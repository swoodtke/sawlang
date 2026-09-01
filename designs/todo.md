# Saw — Open Work Tracker

OPEN WORK ONLY, plus the two pointer sections directly below. Landed
work lives in `designs/NN-*.md` + the done files + git history.
Conventions: cite source designs in [brackets]; VERIFY items need a
probe before being treated as real work.

TRACKER FLOW (user, Aug 18). An IMPLEMENTING AGENT closes its entry IN
PLACE here — the status line plus what landed — and never touches a done
file. The LEAD does the moving, at INTEGRATION and only after
review/approval: an entry with nothing open left inside it is cut
VERBATIM into the current week's done file, in the same pass that accepts
the work. An entry with ANY open item stays here WHOLE — a partially
closed entry is never split, and a closed finding that lives as a bullet
inside a still-open section travels with its section, not on its own.

ARCHIVE. A new done file starts each week: done_aug1-aug9.md (split
Aug 9), done_aug10-aug17.md (Aug 17), done_aug18-aug25.md (Aug 18), then
done_aug26-sep1.md, and so on — each getting its designs/INDEX.md line
when it is created (INDEX.md is the navigation, one line per brief plus
one per done file). Done files are VERBATIM moves, never rewritten (ruled
Aug 15): an old tracker entry is often the SOLE record of a DF mechanism,
a ruling or a correction, so grep the archive before concluding a thing
was never written down, and fix a stale line where it is stale rather
than by editing history. Older history is in this file's git log (pruned
Jul 30).

[QUEUE] and [BACKLOG] are POINTERS ONLY — one line per item, naming the
entry below or the brief that carries it, never restating either. What
is scheduled and in what order is the whole of what they say.

## [QUEUE] — scheduled, in order (user-approved)

- Design 218 unit 1.5 — monomorphization becomes a pre-codegen transform (RULED Aug 13; ~~SCHEDULED Aug 24, user: MOVED UP, BEFORE the 238 split~~ ORDERING SUPERSEDED Aug 28, user: 238 goes FIRST — the freestanding suite is the cross-target gate 1.5 lands under, and sawos's first pin bump follows 1.5's landing; rationale in 238's Aug-28 rulings section). Process per the 218 ruling: a FABLE SPEC AGENT authors the census first (every `_ensure_monomorphized_*` call site, the instance-re-check design, error attribution, the per-(template, type-args) cache), lead reviews, user rules, Opus implements. Expected closures ride it: DF-217i/j/k, S1 row p08a, plausibly DF-247a. Brief section: designs/218-enforcement-architecture.md unit 1.5. **SPEC AUTHORED Aug 25 (`designs/218c-monomorphization-spec.md`) and LEAD-RATIFIED same night under the overnight authorization — all six section-8 questions resolved as recommended (rationale in the spec's status header); none touched a user ruling. Probes: DF-247a NOT dissolved (own dispatch after 1.5, OQ5); two new findings (DF-258a: a nested unconditionally-suspending generic silently loses its yield — pinned at stage 0, flips stage 4; DF-258b: recursive instantiation growth HANGS the compiler — fixed by stage 1's depth limit). IMPLEMENTATION HELD (user, Aug 25 morning): the pipeline STOPS after the 234 flip integrates — 1.5's build dispatches on the user's go, against the ratified spec** **GO (user, Aug 31: "we should finally work on 218/1.5"): DISPATCHES NEXT — immediately after designs 256/257 integrate (same typechecker surface; two agents on it concurrently would collide), Opus against the ratified 218c spec. The "first pin bump follows 1.5" clause is SUPERSEDED BY EVENTS: bumps 0.2.0/0.2.1 already shipped for the sos findings batch** **STAGES 0, 1 AND 2 LANDED Sep 1 (branch `worktree-agent-aef37a0f71731cc39`); STAGES 3-5 OPEN. The perf pause is LIFTED (measurement below); stage 2's last step is HELD on DF-284c, a cross-unit blocker — see its entry.** Stage 2: the four `del self.reporter.errors` sites in effects.py are GONE (the charter's "type-stamping device"), §3's attribution note is a `CompilerError.note` field rendered between the caret and the hint, two §1c provenance skips land at their own rules (design 132's visible-Void — the one the instance mark is load-bearing for — and the design-150 warning categories at the `_warning` funnel), and abstract-first is ENFORCED rather than assumed: an instance reports only in a compile the abstract layer accepted. One real bug fixed on the way, invisible while the diagnostics were deleted — `_add_associated_type_bindings`, since a clone has no bounds left and a body naming a bound's associated type kept it unsubstituted (`examples/generic_instance_associated_type_binding.saw`; codegen has bound the same associated types since brief 36). The spec's grep gate joins `citations` as CHECK 3 (a `del` against a reporter's own list, over every tracked `sawc/**.py`, with its own recogniser self-test) — it belongs there because every other gate observes BEHAVIOUR and a check whose diagnostics are deleted behaves exactly like no check at all. **STAGE 2 LANDED Sep 1: `INSTANCE_ERRORS_ARE_REAL` is True.** **USER RULING (Sep 1): the unit-3 primitive-conformance desugar pulled forward into 1.5 to unblock DF-284c; the rest of unit 3 stays its own unit.** The slice is `_builtin_requirement_call` — it stamps design 239's own `comparison_dispatch` for a CONCRETE receiver whose conformance body lives in codegen, so the requirement lowers through `_emit_equals`/`_emit_compare`, the emitters `==` and `<` already use; no body moved and no symbol was minted, which is how behavioural identity is a property of the code rather than a claim. DF-284c CLOSED, with a scope correction the entry records (the set is a predicate with three members, not the two the ruling named — `@synthesize`d ENUMS and String's requirement spelling walked past the first fence) Stage 0: the two pre-registered pins land XFAIL, corodiff gains the `nested_generic_susp` axis value, DF-258a/DF-258b file, and two HARNESS findings were repaired on the way (DF-284a/b — corodiff had been scoring 2408 identically-refusing pairs as clean). Stage 1: `sawc/monomorphize.py` (the demand fixpoint, the registry, the depth limit) + `sawc/mono_identity.py` (the identity funnel, which codegen now delegates to) + four shadow hooks in `codegen/generics.py`. **The registry-completeness proof is DONE and is stage 1's whole point: the full suite passes under `SAWC_MONO_SHADOW=strict` (2318 passed / 8 xfailed, 2326 verdicts, ZERO misses), and so does the freestanding suite (33, both arches).** DF-258b CLOSED by the depth limit. **PERF: WITHIN the spec's §5 envelope — the tripwire never fired** (measured to §5's own instrument on the lead's instruction, Sep 1: uncontended, same machine, under the suite lock, 3-run median, both trees). Full-suite COMPILE median **604.1s baseline → 606.2s branch, +0.35%**; BOOTSTRAP median **158.4s → 164.1s, +3.6%** (envelope +10% on both); peak RSS on §5's three probes **hello 94.9→104.3 MB (+9.9%), a generic-heavy example 122.1→124.1 MB (+1.6%), blade's entry 532.9→532.0 MB (-0.2%)** (envelope +25%). The earlier +27%/+12% readings were CONTENTION, exactly as the lead suspected — a lightly-loaded baseline run against heavily-loaded branch runs; the honest instrument shows the two trees inside each other's run-to-run spread. Applied on the way, none of it speculative: §5 remedy 1 (the phase runs once per SETTLED front half rather than once per place-lowering re-entry), a per-class field cache and a scalar filter in the collection walk (the phase's per-compile cost 0.69s → 0.24s by profile), and one genuine algorithmic bug — an exponential (2^depth) argument descent the 64-deep depth-limit test exposed. §5 remedies 2 and 3 are NOT needed and were not built; the design-168 narrowing of the type closure (bodies deferred to a call demand) is NOT authorized — it changes the instance set for a hosted `-c` object, which is a link-surface question **STAGE 3 IS HELD, Sep 1, on §5's own rule and on two findings the stage-1 registry made measurable for the first time — DF-285b (the pristine template store §1c/§4 write the instance check against is EMPTY in an entry compile: 0/0/0 on hello.saw, against 111 demanded instances, every one of them std's, because std bodies belong to the cached builtin typechecker) and DF-285c (the splice-all costs +83% per compile before any checking — 0.94 s on a 1.13 s compile, 81% of it `copy.deepcopy` over 306 (type instance, method) pairs, and near-CONSTANT across programs because it is std's type closure — against an envelope of +10%, with remedy 1 already applied, remedy 2 able to remove only 0.09 s of it, and remedy 3 plus the design-168 narrowing unauthorized; and the check itself reports ~30 diagnostics per compile against std's own bodies, two of the largest classes verified as refusals of code that compiles and RUNS today).** Stage 3 is ATOMIC by the spec's own argument, so none of it landed. WHAT DID LAND on the way: **DF-285a, a regression stage 2 introduced and the whole battery is blind to** — `substitute_ast_types` cannot reach a type parameter spelled in CALL-NAME position (`A()`, design 37's allocator construction, which `Vector._reserve` and `Box.make` are written around), so a spliced instance named a function that does not exist; main compiles the repro and prints `8` and the branch refused it. Fixed at the funnel, pinned by `examples/generic_instance_constructs_type_param.saw`, full suite 2321 passed / 8 xfailed and freestanding 33 both arches. The two constructive directions DF-285c names, neither of them an agent's to choose: a purpose-built substituting AST copier in place of deepcopy-then-rewrite, and LAZY BODY MATERIALIZATION (the registry still decides every instance; only the instances the coroutine transform must see are spliced eagerly, the rest materialize at design 168's body demand). Stages 4 and 5 are downstream of 3 and were not started **USER RULINGS (Sep 1 evening): (1) the DF-284c scope widening is RATIFIED (recorded in its entry); (2) stages 0-2 + the DF-285a fix INTEGRATE to main NOW (done — main `466812fe`, fast-forward of the terminal-battery-green tip; worktree/branch removed); (3) stage 3 proceeds AMEND-FIRST — the lead authored `designs/218c-monomorphization-spec.md` **Amendment A** (A1 std template-store capture, A2 the two ruled perf remedies — substituting copier + lazy body materialization, BOTH user-ruled — A3 the ~30-diagnostic triage plan, A4 stage 3 restaged as 3a/3b/3c with the envelope binding at 3c). **AMENDMENT A IS USER-RATIFIED (Sep 1), in full — including the one flagged semantic cell, A2(b)'s checked-equals-materialized alignment (an instance demanded but never emitted in an EXECUTABLE build is registered and depth/effect-validated but never instance-checked, so a diagnostic living only there surfaces in `-c` and not in `-o`). Ratified together with a new **A5**, which the user's reversibility question earned and which is what makes the cell ratifiable: (a) a forced-eager mode `SAWC_MONO_MATERIALIZE=all` — sibling to `SAWC_MONO_SHADOW`, off by default, landing with 3c — plus ONE battery lane running the suite under it, so the strict answer stays computable, the corpus is PROVED to carry no latent errors in never-emitted instances (the lax→strict ratchet never accumulates), and a later flip has its evidence already in the gate rather than owed as a migration; the reversal itself is a PREDICATE (widen the eager set from transform-relevant to all-registered — the registry decides every instance either way, and G3/M6/the codegen template stores that 3c deletes are the OLD path, not the eager one); and (b) THE MEASUREMENT DECIDES THE DEFAULT — the +83% that bought laziness was measured with `copy.deepcopy` and 81% of it WAS the deepcopy, which A2(a) removes, so §5's instrument re-measures splice-all at 3b's boundary: inside the +10% envelope and laziness is NOT bought (eager set = everything, the cell is MOOT and never ships, the switch drops and the lane stays as the pin), over it and A2(b) stands as ratified. The 3b landing note records the number and names the branch; the lead confirms the branch before 3c dispatches. Stage 3 DISPATCHES against the amended spec (fresh Opus, fresh worktree, DF range DF-286a+)**
- Design 258 — field visibility inherits the type's, amending design 80 (designs/258-field-visibility-inheritance.md; RULED Aug 31 by the user after reading the sos code, three cells pinned: ALL TIERS inherit, FIELDS ONLY — extension members keep per-member marking — and a contextual `private` keyword for narrowing; SCHEDULED after 218 unit 1.5). The consumer sweep IS the migration: every bare field of a visible struct in std/libs/blade gets `private`, surface-preserving; conformance B rows update first (obligation 3)
- Design 245 v1 — `Scalar` + `scalars()`, `chars()` and `append_scalar` REMOVED (designs/245-unicode-scalar-type.md §6; ruled Aug 27 — no literals in v1, prelude placement). The Aug-27 dispatch NEVER LANDED and is presumed STALE (no Scalar in the tree, Aug-28 check); RESCHEDULED AFTER design 238 (user, Aug 28: sos does not depend on string/character work). Re-dispatch then. Literals + patterns stay open as later units

## [BACKLOG] — filed, not scheduled

- Cooperative BRACE sugar (`Task.spawn { }` / `group.spawn { }`) — design 242's last piece, HELD for the user: blocked on the lifted function's return-type inference, two candidate shapes in the 242 brief's landing section (designs/242-thread-task-split.md). Everything else in 242 landed Aug 22-25; the entry and its queue record are in done_aug18-aug25.md
- `public(package) import` — should the scoped re-export form exist? Refused today (design 229). Real use case: an INTERNAL PRELUDE, one sibling aggregating names for the others (Rust's `pub(crate) use`). Against: siblings can already import each other directly, so it buys convenience, not capability — and kcore, the biggest multi-file package and the one that motivated the tier, does NOT want it (its `public import` block is the EXTERNAL facade). Wait for a package that feels the pain (entry: the re-narrowing rider section)
- ~~DF-242b — a cross-module OVERLOAD SET is bound BARE as a single overload~~ **CLOSED Aug 27 by design 249 unit 1**, the expected closure: every import arm binds the whole overload set a name stands for. Entry below
- DF-242c — a SUFFIXED (exact-typed) literal argument does not disambiguate an `Int`-vs-narrow overload set; same-module and cross-module alike (entry below, found probing DF-238a's fix). RE-PROBED against design 249 Aug 27 and SURVIVES verbatim, as the entry predicted — the matcher's own question, not the registry's
- DF-226b/c — FuncPointer v1 gaps (entries below, under design 226)
- DF-225o — reemit divergence under load (entry below)
- Design 231 — native-compiler readiness ledger (designs/231-native-compiler.md). ELEVATED to a V1.0 GATE (user, Aug 24): the self-hosted story lands BEFORE v1.0 — a compiled compiler is what retires the D-b install/version simplifications
- Design 243 — trailing-brace call syntax (designs/243-trailing-brace.md; BACKLOGGED by user Aug 24, "a nice usability win, maybe not right now") — the scope ruling (spawn-family-only vs general) is the first question when pulled
- Design 248 — a Saw linter, SCOPING brief drafted both shapes (designs/248-saw-linter.md, authored Aug 27 on the user's request, unruled) — the split ruling (semantics as `-W` categories vs a standalone `sawlint` devtool for style with a CI exit code) is Q1 of six on its ruling sheet
- Blade out-of-tree target plugins — moves `sosimg.saw` + `imgformat` out of sawlang entirely and SUPERSEDES 238's D-a; user Aug 19: "probably the way forward in the future". NOT a dependency of 238 (entry: designs/238-sawos-split.md, D-a alternatives)
- M4 seeds — IPC/pipes (renamed from channels Aug 20 — ratified record in spec §2.1 + the done file), dynamic loading, IOMMU, SMP (references in designs/232-sos-m3-sketch.md)
- ESP32 path — P4 + TCP/IP stack ultimate goal; S3 via FreeRTOS-fakery stage 2 (HARDWARE PATH entry below)
- DF-223b — existential dispatch of a suspending trait method, owed a DESIGN (entry below, under design 223)
- DF-218t — a value-position loop at a non-integer result type is a codegen ICE (the `None` sentinel is built for an integer); entry below, found by 218b stage 0's probes
- DF-242a — a DRIVEN `try { } catch { }` releases the try body's frame fields at frame teardown, where the sync twin releases them at the error edge (entry below, filed by DF-218v's fix; DF-218w/DF-218s's family — the transform cannot see a codegen-owned edge)
- DF-218w RESIDUE — the MIXED `case Both(v, _)` shape keeps statement-end timing (entry below, pinned XFAIL; the rest of DF-218w closed Aug 21)
- DF-247a — a function that is a `group.spawn` ROOT is `undefined function` at every other call of it in the same module (entry below, filed by design 242 unit 0's census; PRE-EXISTING, stash-verified). The fix owes the ROOT MATRIX its mechanism reaches, not the one probed cell
- DF-248b RESIDUE — a HAND-WRITTEN closure nested inside another still captures the outer one's `&var` PARAMETER by value, so a write through it is silently lost; the place-window half closed Aug 22. Entry below, pinned XFAIL; wants a borrow marker on `VariableInfo`
- DF-248c RESIDUE (the XFAIL-CHARACTER face) — an XFAIL that starts failing for a WORSE reason than the one cited is still invisible to every gate; it wants the `XFAIL-EXPECT: error`/`output` discriminator the entry names, in the RUNNER, not in a lint. The CITATION face closed Aug 24 (branch `harness-doctrine`, commit 2) as the `citations` battery lane, `tools/check_citations.py`: done-file membership is closure full stop, a todo.md entry's status decides the rest, and an OPEN entry WINS over every closure — which is what keeps a partly-closed finding's pin (DF-218w, DF-248b, and this entry itself) from being flagged. Undecidable rows are info, never failures. The lane also carries the COMMITTED-CONFLICT-MARKER check the lead's Aug-24 incident asked for (three blocks found on main, repaired at e414a8fb; one had sat in todo.md since Aug 22) — same blind spot, same lane: nothing gates the files nothing compiles. Clean on the current tree (4 citations all open, 0 markers); the historical DF-232n row and the INDEX.md nested block are its negative controls. Entry below
- DF-250a — a COLLECTION LITERAL does not shape through a `Result`'s Ok payload, where the bare `-> Vector<Int>` twin compiles (entry below, filed by DF-245c's sweep; PRE-EXISTING and spawn-independent). The fix is a third peel beside DF-226e's and DF-140d's, at one funnel
- DF-250b — a `??` whose DEFAULT is a bare `None` at a NON-optional peeled type is an LLVM ICE where the documented behaviour is a clean refusal (entry below, filed by DF-245c's sweep; PRE-EXISTING). Wants the refusal first, the funnel guard beside it
- DF-255a — an ESCAPING closure whose body consumes its `move` capture double-frees; the non-escaping half closed Aug 24 as DF-218h, and its answer does not port (entry below, pinned XFAIL). Owes a ruling on whether a closure body may consume a capture at all
- DF-251b — a GENERIC extension's `init` registers no param cleanups (an un-moved owning param leaks), populates no `variable_types` and sets no ICE breadcrumb, where the non-generic twin does all three. Entry below, filed by DF-251a's fix; one function, three faces
- DF-251c — DF-216h's extension-parameter RENAME does not reach an `init`'s parameters at the construction site, so `Pair<Int>(three: 11)` under `extension Pair<U>` is refused; the METHOD half works. Entry below, with the mechanism and the data the fix needs
- DF-251d — an `init` BODY that suspends is an internal compiler error; the coro transform scans init bodies but a construction is a `StructInit`, not a `MethodCall`, so nothing can name the frame. Entry below; either transform it or refuse it at the declaration
- DF-252a — calling a `FuncPointer` value BY NAME inside a driven body is an internal compiler error (entry below, filed by design 242 unit 4; PRE-EXISTING, and invisible until ruling 8 refused the vacuous test that claimed to cover it). Pinned XFAIL, seven-cell matrix with three green controls
- DF-256b — the thread control block is DEALLOCATED at a size std computes by hand, and the two do not agree with the one codegen allocated (entry below, filed Aug 25 by design 242 unit 3b; PRE-EXISTING and inert on both hosted allocators, which free by pointer)
- DF-257a — the two construction checkers SELECT an init differently, so an init with a defaulted parameter resolves at the bare spelling and is `no matching initializer` at the module-qualified one (entry below, filed Aug 25 by design 234 unit 3's hazard sweep; PRE-EXISTING, probe-refuted in both directions)
- DF-257b — design 234 §5 keeps the `copy()` hook infallible, which leaves `Vector.try_copy` as the one alloc `try_` twin the flip cannot retire; owes a naming ruling (entry below, filed Aug 25 by design 234 unit 3)
- ~~DF-257c~~ — CLOSED Aug 27 by design 246 unit B: the by-LLVM-type fallback stopped being ambiguous when a payload-carrying enum became an IDENTIFIED struct. Entry below; the pin is no longer an XFAIL
- DF-257d — the `$0` closure shorthand is invisible to the implicit-parameter scan inside a `try` operand, so the closure infers arity 0 (entry below, filed Aug 25 by design 234 unit 3; PRE-EXISTING). Pinned XFAIL; the flip meets it because `try!` is the corpus migration spelling
- DF-259a — `Box<any Trait>.make` sits outside design 234's flip, so one method name has two fallibilities and the erased one panics with a bare `allocation failed` (entry below, filed Aug 25 by the design-138 doc-sync sweep). This IS the 234 census's `existentials.py:402` hold, which never became a tracker entry — it owes the user ruling that brief deferred
- DF-259b — a reserved word in any declaration-name position gives a bare "Expected X name" that never says the word is reserved; five slots, one shared report (entry below, filed Aug 25 by the design-138 doc-sync sweep; PRE-EXISTING). Diagnostic-only, so no XFAIL pin
- DF-259c — a TRAILING closure is not recognized inside a `try`/`try!`/`try?` operand, so `try! v.map { … }` collapses to a field access; the parenthesized argument is the workaround (entry below, filed Aug 25 by the design-138 doc-sync sweep; PRE-EXISTING, and the 234 flip is what makes it reachable from ordinary code). Pinned XFAIL, three cells and one control
- DF-215g — a bare `None` compared `==` against a CALL expression's determined optional refuses to infer, where the annotated-local twin compiles (entry below, Aug 26)
- DF-262b — a suspending interpolation piece + `Task.spawn` at the same NoCopy result type + optional auto-wrap of the joined value is an LLVM-verifier ICE (filed Aug 27 by the DF-215f sweep; repro preserved verbatim in the 247 brief's appendix). NOT dissolved by design 247 — re-probed Aug 27 post-migration and it reproduces verbatim (`ret {i1, %"Res"} %"autowrap_val"` against `%Res = type { ptr }`), which is what places it in the ANF/auto-wrap machinery rather than the scrutinee-temp family
- DF-264a — the `Copy` tier's conformance check skips the deinit-signature validation its ExplicitCopy/NoCopy siblings both have, so a `deinit(&self)` inside a `@synthesize Copy` reaches codegen and ICEs (entry below, filed Aug 27 from the user's scratch example)
- DF-266a — a bare leading-minus TAIL expression after a preceding `if { return }` block is an ICE at a BinaryOp node; the same tail after a `let` compiles (entry below, filed Aug 27 by the std.json build, lead-verified both cells)
- DF-267a — an Optional method called DIRECTLY on a `borrows -> T?` lend's result resolves against the unwrapped payload type, contradicting DF-218a's tier-independent presence promise; `if let` is the working spelling (entry below, filed Aug 27 by std.json unit 1)
- ~~DF-267b — `Map.keys()` through an enum MATCH BINDING leaves the defaulted allocator parameter unresolved where the struct-field twin resolves~~ **FIXED Aug 28** (entry below carries the sweep matrix and the funnel)
- DF-267c — a hand-written `borrows` accessor cannot `lend` a place indexed FURTHER into a match-bound payload, though the docs' own field-projection twin works — blocks JsonValue's combined member/element accessors (entry below, same filer)
- ~~DF-267d — a SELF-RECURSIVE function under sawc/std that transitively reaches a maybe-suspending closure API fails the builtins pre-check~~ **DISSOLVED-PENDING-CONFIRMATION Aug 27** (lead re-probe post-247/249: all three filed minimal shapes now compile under sawc/std — entry below has the cells; the Object-serialization landing is the confirming probe and closes this)
- DF-270a — the alias literal rule differs by SLOT: `static X: Byte = 45` adopts, `static X: Byte = Byte(45)` is refused as non-constant, `let x: Byte = 45` is refused — 250 §5 Q1's assumption was wrong in BOTH directions (filed Aug 28 by design 250; repros in its report + the brief's §8). Wants ONE rule over the three slots
- DF-270b — `G<Alias>` at a `G<Underlying>` slot: ICE at argument/return/field positions, SILENTLY ACCEPTED at a `let` — every monomorphized generic, not just Vector; two wrongs in opposite directions (filed Aug 28 by design 250)
- DF-270c — a conformance body naming the UNDERLYING where the trait requirement names the ALIAS is accepted silently, and the call through `any Trait` is a codegen ICE — met live when `Decoder.read_byte` flipped (filed Aug 28 by design 250)
- DF-270e — a primitive type name as a ZERO-ARG call (`UInt8()`, `Int()`, `String()`, …) is an ICE; with an argument it is clean. Fuzz-found by 250's battery, pre-existing; its three obligations (pin `examples/errors/primitive_type_called_as_a_function.saw`, `sawfuzz_known.txt` row, report) all landed with 250 — this line completes the DF filing
- DF-273a — a module-QUALIFIED static call on an ENUM type (`json.JsonValue.parse(text: …)`) is refused ``` `parse` is a static method of `JsonValue` and cannot be called on a value``` while the STRUCT twin (`time.Instant.now()`) resolves in the same file — the qualifier.Type.static path misses enums (design 145 gave enums statics; design 150 promises qualifiers work at every position a name appears). Observed by the DF-267b fix agent, lead-probed + narrowed Aug 28 (`.build/scratch/probe_qual_static.saw`); the bare spelling works. No entry below, this line is the record
- DF-275a — a distinct alias over a primitive satisfies a trait bound through a std extension's RECEIVER type argument (`Vector<Handle>.sort()` discharges Comparable at `T = Handle`) but NOT through a free generic function's own bound (`rank<T: Comparable>(Handle(1), Handle(2))` is refused), and the refusal's fixit is UNWRITABLE (`extension Handle: Comparable` is orphan-refused pointing at std.builtin) — the alias resolves to its underlying for the ORPHAN question but not the BOUND question, two readings in opposite directions that strand user aliases (filed Aug 28 by design 252; pre-existing, bound discharge not lowering; repro was `.build/scratch/probe_alias_bound3.saw`, essentials here — `examples/unsigned_handle_ordering.saw` carries the `as UInt` workaround spelling with a comment). No entry below, this line is the record
- DF-277a — the synthesized `E.from(raw:)` does not adopt a bare integer literal (`Tag.from(raw: 9)` refused expecting the backing `UInt8`, while an ordinary `takes(9)` at a `UInt8` param adopts in the same file) — a dedicated check branch compares the argument's inferred type against the backing DIRECTLY, bypassing the literal-adoption funnel every other call argument uses (filed Aug 28 by design 238 unit 2; mechanism per obligation 4, siblings to probe at fix time: the other compiler-synthesized statics with declared parameter types — `Float.from(bits:)`, `Deserialize.deserialize`, the `T.from(...)`/`from(truncating:)` family). Workaround in-tree: one suffixed literal in `libs/imgformat/tests/header_rules.saw` with a comment. No entry below, this line is the record
- DF-271a — the builtins pre-check refuses a `try` STATEMENT inside a match arm inside a while loop inside a GENERIC method (``` `try` cannot propagate errors from a closure returning `Never` (must return Result)``` + `builtins failed to type-check`), sawc/std ONLY — the identical shape compiles as a user file (probe recorded by design 251's report). THIRD member of the builtins-vs-user-file checking-divergence family: DF-257c (closed — generic-body `try` reuse across instantiations) and DF-267d (dissolved) are the siblings; std code routes around it with the `match`-instead-of-`try` idiom map.saw already carries for 257c. The family's standing question: why does the builtins pass check differently from user-file checking AT ALL — a fix brief should target that divergence, not the face. Filed Aug 27 by design 251; no entry below, this line is the record
- std.serde derived `Map` encoding — neither cbor nor json derive `Map<K, V>` through `@synthesize` (the field walk does not cover Map; both format landings record the scope note), so a Map on the wire is a hand-written `Serialize`/`Deserialize` today. Wants a design when the appetite arrives; pairs with the seam's missing Float story (design-215 section). Recorded Aug 27 while checking cbor for DF-267 siblings — no entry below, this line is the record
- DF-269a — a LABEL-selected overload loses bare-literal width adoption: `report(byte: 65)` against `{report(value: Int), report(byte: UInt8)}` errors `expects UInt8 but got Int`, while the same labeled call against the SINGLETON declaration adopts and runs — the label face of DF-242c's family (overload resolution defeats literal adoption; 242c is the suffix face). Lead-probed Aug 27 (`.build/scratch/probe_append_overload{,2,3}.saw`, cells recorded here) while ruling design 244's naming rider; the bare positional call is a correct ambiguity error naming both candidates. The DF-242c re-probe note on its entry applies to this face too: module identity (249) moved which candidates are seen, not how a literal adopts once one is selected
- DF-215h — stdout has no newline-free write, so incremental output (`--stream` deltas) prints one line per piece; wants a surface ruling (entry below, Aug 26)
- DF-215i — no boolean `guard cond else { }`, only `guard let`; wants a ruling on whether the omission is deliberate (entry below, Aug 26)
- DF-215j — `return` inside a VALUE match arm is a bare "Unexpected token: RETURN" with no arms-are-expressions hint; diagnostic-only (entry below, Aug 26)
- DF-242d — conformance row K90's bounded GO spin re-opens its output race under suite load; flaky, seen once Aug 26 (entry below; oracle choice is a ruling)
- DF-261c — `==` on an ENUM ignores a hand-written `Equatable.equals` and does the structural payload compare instead; the STRUCT arm one line above does ask (entry below, filed Aug 27 by design 246; PRE-EXISTING). No pin — the shape needs a non-Equatable payload to reach
- DF-261d — `Box` payload-method forwarding reaches a STRUCT payload's methods and NOT an ENUM payload's, so a box-linked recursive enum has no Saw-level traversal (entry below, filed Aug 27 by design 246; PRE-EXISTING)
- DF-261e — an optional chain through a `Box<T>?` FIELD is `BindOptional lowered outside an optional chain`, with no recursion involved (entry below, filed Aug 27 by design 246; PRE-EXISTING)
- DF-261f — a directly recursive SUSPENDING function makes the coroutine transform recurse forever, and escapes the ICE funnel as a raw Python traceback (entry below, filed Aug 27 by design 246; PRE-EXISTING, verified against main). Two halves: wrap the transform, then refuse the shape
- DF-272a — an enum VARIANT construction does not push its declared payload type into a closure-literal argument, so `Holder.Handler(f: { c in c + 1 })` is "Cannot infer type for closure parameter `c`" while the struct-init twin `FnField(f: { c in c + 1 })` infers and runs (entry below, filed Aug 28 by the DF-267b sweep; PRE-EXISTING)
- DF-272b — `_resolve_type` skips design 37's default fill entirely when a written type has NO type arguments, so a BARE reference to a generic whose every parameter is defaulted never gets one; the explicit spelling works and the bare one does not (entry below, same filer; PRE-EXISTING). Same design-37 family as DF-267b, different gap, and it moves type IDENTITY — wants a ruling before a fix
- DF-272c — a maybe-suspending call made INSIDE a place window (`&m.get(k)!`, a `borrows` lend) is refused under `sawc/std/` with `cannot suspend in a sync closure context`, while the identical shape compiles and RUNS as a user file (entry below, same filer). FOURTH member of the builtins-vs-user-file divergence family with DF-257c (closed), DF-267d (dissolved) and DF-271a (open) — and the one that blocks stage 2's natural Object-walk spelling
- DF-276a — an UNREPRESENTABLE FLOAT LITERAL degrades silently (entry below, filed Aug 28 by design 253; PRE-EXISTING). `let over = 1<400 zeros>.0` compiles clean and is `inf`; `let under = 0.<400 zeros>1` compiles clean and is `0.0`. The integer literal beside it is checked — `let n: UInt8 = 300` is a clean located error — so this is the one literal kind whose conversion has no representability check. "Never hide errors", at the position a value enters the program
- DF-276b — there is NO `Int` -> `Float` conversion in ANY spelling (entry below, same filer; PRE-EXISTING). `let a: Float = n`, `n as Float`, `Float.from(n)` and `Float(n)` are all errors. Design 170 promises `from`/`from(truncating:)` for "every source/target pair" and means the INTEGER pairs; the float axis is absent entirely. Costs already paid in the tree: `std.string` carried a ten-branch `_digit_to_float` for it (deleted by 253), `JsonValue` can have no combined `as_number()`, and no float parser can have a small-integer fast path. Wants a design, not a patch — the rounding mode of a wide `Int` -> `Float` is a ruling
- DF-276c — a VALUE `if`/`match` whose arms are bare literals does not adopt the width of the operand it sits BESIDE (entry below, same filer; PRE-EXISTING). `wide + (if up { 1 } else { 0 })` on a `UInt64` is ``operator `+` requires both operands to have the same type … the right is `Int` ``, while `wide + 1` and `wide + (1 + 1)` both adopt (the second is DF-243a's fix). Probed siblings all WORK — an argument, an annotated `let`, a `return`, a compound-assign RHS — so the gap is exactly DF-243a's position with a branch construct in it rather than a const expression
- DF-280b — a collision with a PRELUDE type name is recorded and then not REPORTED at the construction site, so `import mine.{Duration}` fails with ``no matching initializer for `Duration` with parameters: tag`` instead of naming the collision (filed Aug 30 by design 255 unit 0's sweep; PRE-EXISTING). The prelude tier is reserved in both directions — a local declaration is "defined multiple times" (conformance B12) and an import is refused too — so nothing that compiled stopped compiling; what is missing is the SENTENCE. `ambiguous_types` holds the entry and `_report_type_ambiguity` is only reached from `get_struct_info`/`get_enum_info`, which the struct-init path does not go through. Now that both sides carry real labels the report would read ``ambiguous struct `Duration`: defined in both `std.duration (prelude)` and `modules.mine` ``, which is the whole fix. Pinned by `examples/shadow255_prelude_name_reserved_error.saw`, which asserts only the refusal. No entry below, this line is the record
- DF-283c — a const expression whose operands are ALREADY unsigned-typed still folds in the SIGNED platform-`Int` domain, so `~(0 as UInt)` is refused (filed Aug 31 by design 257's corpus sweep; the FIXED-WIDTH twin `~(0 as UInt32)` has behaved this way since DF-235a/b and is PRE-EXISTING). Design 257 §1 put platform slots on the adoption ladder, and the brief's ruling covers the outcome explicitly ("a negative fold into a `UInt` is the same clean `does not fit`"), so the refusal is INTENDED and landed — but it is the dispatch's one works→refusal, against obligation 2's expectation that the pair was refusal→works throughout. The in-tree casualty was `examples/shift_signed_unsigned.saw`'s all-ones `UInt`, now `UInt.max` with the reason in its header; nothing else in the corpus, blade, libs or the freestanding suite used the shape. THE OPEN QUESTION, for the user: an expression whose operand carries an explicit unsigned type has said what domain it means, and folding it signed reads past that. Either the fold honours the operand's own signedness (a design-185 amendment) or the language keeps one domain and `UInt.max` / a written mask is the spelling — the second is the status quo at every fixed width, which is why it is what landed. This line is the record
- DF-284b — `{ ... }()`, the spelling BOTH the spec and the diagnostic name as the fix, does not exist (entry below, filed Aug 31 by design 218 unit 1.5's agent while repairing DF-284a; PRE-EXISTING and never once tested — no `examples/` file contains the form). The postfix call is never applied to a closure literal in ANY position: statement position is the bogus refusal whose own hint names it, argument position is a parse error, and `let x = { 1 }()` SILENTLY binds the closure and drops the `()`. Not this unit's to fix (it is a parser question with a trailing-closure interaction); corodiff's `nested_block_tail` wrapper, which was written around the form and had therefore never compiled, moved to a nested `if true` scope
- ~~DF-285a — a type parameter CONSTRUCTED in the template (`A()`) survives substitution unrewritten, so a spliced instance names a function that does not exist~~ **FILED + FIXED Sep 1 (design 218 unit 1.5's stage-3 agent, fix-on-discovery)**: a REGRESSION THIS BRANCH INTRODUCED at stage 2 and invisible to the whole battery — main compiles the repro and prints `8`, the branch refused it with ``undefined function `M` `` carrying §3's own instantiation note. MECHANISM (obligation 4): `substitute_ast_types` rewrites `SawType`s, and a call's name is a `str`, so the one position where a type parameter is spelled OUTSIDE a type annotation — design 37's zero-argument construction `A()`, which `Vector._reserve` and `Box.make` are written around — is unreachable however completely the walker walks. While an instance's diagnostics were deleted this cost nothing (codegen re-derived the body from the template under `type_param_context`, reading the SUBSTITUTED `resolved_type` rather than the name); stage 2 made them real and turned it into a refusal of a legal program. POSITION MATRIX: the two neighbouring spellings are refused ABSTRACTLY, in the template, on this tree and on main alike — `M.seed()` (a static call on a parameter) is ``undefined variable `M` `` with no instance involved, and an enum-case spelling the same — so the mechanism has exactly one position. FIX: the funnel rewrites the call's NAME to the concrete type, which makes the clone an ordinary concrete program (`_check_function_call` then takes its struct-construction branch and stamps `resolved_type_identity`, and codegen lowers it as it lowers a hand-written `GlobalAllocator()`); gated on the argument list, since a construction takes none and function lookup wins over the type-param arm anyway. Pinned by `examples/generic_instance_constructs_type_param.saw`, which puts the spliced (spawned) instance and the ordinary codegen path side by side. This line is the record
- DF-285b — the PRISTINE TEMPLATE STORE design 218c T1 names as the monomorphization phase's template source is EMPTY in an entry compile (entry below, filed Sep 1 by design 218 unit 1.5's stage-3 agent; PRE-EXISTING, and load-bearing for stage 3). Measured on `examples/hello.saw`: the three stores are 0 / 0 / 0 and `_module_scope_by_file` holds ONE entry, while the same compile demands 111 instances — every one of them std's
- DF-285c — design 218c stage 3's splice-all fails §5's OWN acceptance test before it is built, by ~8x, and the instance check at type-closure granularity is not zero-delta (entry below, same filer). §5's rule for exactly this outcome is that the staging PAUSES for the lead, which is what stages 3-5 have done
- DF-287a — a `move` inside a DIVERGING catch poisons the fall-through path (entry below, filed Sep 1 by the lead from an sos-relayed repro; PRE-EXISTING). Every non-catch diverging construct — `if`, `match` arm, `guard else` — already restores; catch is the one outside the rule, in all three of its forms
- DF-287b — bare-literal ADOPTION never runs at an OVERLOADED call site (entry below, same filing; PRE-EXISTING; DF-242c's matcher family). `solo(len: 1)` adopts at a lone `UInt` param and `b.put(len: 1)` is refused ``expects `UInt` but got `Int` `` although every `put` candidate agrees the slot is `UInt` — with a hint teaching the `as UInt` conversion adoption should have made unnecessary
- ~~DF-284a — the corodiff PRELUDE stopped compiling, so all 2408 pairs refused on both twins and the lane scored them CLEAN~~ **FILED + FIXED Aug 31 (design 218 unit 1.5's agent, stage 0, fix-on-discovery)**: design 234's fallible `Arc(value:)` left the harness's `mk_tag`/`mk_tag_s`/`derive_tag` building a `Tag` out of a `Result<Arc<Res>, AllocError>`, so EVERY generated program refused identically and check 2 exempts exactly that. `corodiff --quick` was green in the battery while testing nothing. MECHANISM (obligation 4): the corpus is GENERATED, so nothing else in the tree ever compiles the shared declarations, and the one oracle that could notice ("both twins refuse") is the one deliberately turned off. Not one-off — it is the SECOND time (commit 2e62f55d, "the corodiff harness survives the rename (its lane had gone dead)", design 219 wave B), and the sibling harnesses do not admit it: sawfuzz mutates the tracked `examples/` corpus, which the suite gates, and irdet compiles that same corpus, so only corodiff owns a corpus nothing else compiles. FIX, both halves in the same commit: `try!` on the three `Arc<Res>(value:)` sites, and a COMPILE FLOOR — `check_prelude` compiles `PRELUDE + func main() { }` before any combo is judged and fails the run outright with the compiler's own output, which is the assertion the refusal exemption was missing. Baselined by the stage-0 `corodiff --all`; this line is the record


## DF-285b — the PRISTINE TEMPLATE STORE is EMPTY in an entry compile, so the
## artifact design 218c T1 hands the monomorphization phase does not exist for
## the library that supplies almost every instance (filed Sep 1 by design 218
## unit 1.5's stage-3 agent; PRE-EXISTING)

MEASURED, `examples/hello.saw`, at the end of the entry module's check:

```
PRISTINE generics               : 0
PRISTINE generic methods        : 0
PRISTINE generic-struct methods : 0
_module_scope_by_file entries   : 1        (the entry file)
registry                        : 111 instances
```

Every one of those 111 instances is a std instantiation — `Vector<Int,
GlobalAllocator>`, `Optional<Box<any Resumable>>`, `Result<…>` — and there is
no template in the store for any of them, nor a home-module scope to check one
in.

MECHANISM (obligation 4). The pristine snapshot is taken by `check_module`, and
`check_module` is run by the ENTRY typechecker over the entry file and the
user modules it imports. std bodies are checked exactly once, by a DIFFERENT
typechecker inside `build_builtin_namespace`, whose result is cached; the entry
compile receives a namespace and an AST, never that typechecker. So the store
spans every module the entry typechecker checks, which is what T1 says, and
that set excludes std, which is where the instances are. `_module_scope_by_file`
is the same fact in its second costume — `_home_module_scope`'s docstring
already records "a std template … falls back to the current scope", which is
the fallback rather than the scope.

NOT ONE-OFF, and the siblings are already in the tree: `_build_fn_mono` returns
False when `pristine is None` with the comment "Cross-module generic template:
not supported for effect re-inference here (design 68 territory)" — i.e. the
existing per-instantiation effect re-inference has never covered a std generic
either, and could not have. This finding is that limitation seen from the
other side, at the moment a stage wanted to depend on the store being complete.

WHAT IT COSTS 218c. §7 stage 3 splices every demanded instance as a CHECKED
concrete declaration and §1c/§4 write that check against a clone of the
PRISTINE template — an artifact captured before any body check mutates an
annotation, which is what §4's "invalidation: none" argument is about. For a
std instance there is no such artifact, so stage 3 has to clone the CHECKED
template out of the merged AST instead. That is viable — probed: 276 of 306
substituted std method clones check clean in the merged namespace — but it is
a different artifact with a different invalidation story, and §4 is written
about the other one. A lead/user correction to T1 and §4, not an
implementation detail. [218c T1/§1c/§4]

## DF-287a — a `move` inside a DIVERGING catch poisons the fall-through path
## (filed Sep 1 by the lead from an sos-relayed repro; PRE-EXISTING)

```saw
var owned = move r                      // Res, NoCopy
try might(x) catch {
    let back: (Int, Res) = (error, move owned)
    return move back                    // the catch DIVERGES
}
owned.n = 0        // error: use of moved variable `owned` — WRONG: this line
                   // is reachable only when the catch never ran
```

MECHANISM (obligation 4): the guard-else checker
(`typechecker/statements.py:1912-1925`) snapshots `moved_bindings` before the
else branch and RESTORES when the branch diverges — its comment names the
protected idiom. `_check_try_catch_expr` (`typechecker/expressions.py:13628`)
checks the catch block with NO snapshot, and the guard-form catch has the same
gap, so catch-body moves flow into the fall-through unconditionally. THE
MATRIX, all lead-probed Sep 1 (`.build/scratch/mv_*.saw`, ephemeral — cells
recorded here): REFUSED in all three catch forms (statement guard-form, value
guard-form `let v = try f() catch { }`, and the `try { } catch { }` block) and
for both divergence kinds (`return`, `panic`); COMPILES AND RUNS for the same
move in a diverging `if` branch, a diverging `match` arm, and a `guard let
... else` — catch is the ONE diverging construct outside the rule, so the
enumeration is closed. Wrong-refusal tier, never unsound. FIX SHAPE: the
guard-else pattern conditioned on divergence — snapshot before the catch,
restore iff the catch block diverges; a NON-diverging (fallback) catch keeps
the poison, correctly, because fall-through then follows both paths. Also a
design-259 CLASS 2 member: a Saw parser's error paths are exactly
catch-and-diverge over move-only nodes.

## DF-287b — bare-literal adoption never runs at an OVERLOADED call site
## (filed Sep 1 by the lead from an sos-relayed repro; PRE-EXISTING;
## DF-242c's matcher family)

```saw
extension Bag {
    func put(&self, len: UInt) -> UInt { len }
    func put(&self, len: UInt, extra: Int) -> UInt { len + (extra as UInt) }
}
func solo(len: UInt) -> UInt { len }
solo(len: 1)        // adopts: one candidate
b.put(len: 1)       // error: argument 1 expects `UInt` but got `Int`
```

MECHANISM (obligation 4): with 2+ candidates the overload matcher types the
bare literal at platform `Int` and requires an exact match, so the adoption
ladder (designs 195/205/257) never runs — the refusal fires even though every
candidate agrees the slot is `UInt` and labels/arity select exactly one, and
its hint teaches the `as UInt` conversion adoption exists to make unnecessary.
The single-candidate path checks against the declared parameter and adopts.
THE MATRIX (`.build/scratch/adopt_overload.saw`, lead-probed Sep 1): refused
at the overloaded METHOD (both arities) and the overloaded FREE FUNCTION;
adopts at the single free function and the single method; `1 as UInt`
compiles. The documented `h(Int)`/`h(Int8)` ambiguity at `h(5)` shows the
literal is MEANT to stay width-flexible across candidates — the intended
shape is: a bare literal matches any integer-width slot during candidate
filtering, adopts against the winner, and 2+ surviving widths stay the
documented ambiguity error. Sweep owed at fix time: the static-method and
init overload faces of the same funnel (unprobed), and DF-242c's suffixed
face, which this mechanism plausibly explains too.
## before it is built, by ~8x, and the instance check at type-closure
## granularity is not zero-delta (filed Sep 1 by design 218 unit 1.5's
## stage-3 agent)

THE INSTRUMENT is the stage-1 registry, which is what makes the number
measurable for the first time: for every registered type instance, clone each
applicable extension method (the same three rules `_applicable_extensions`
already applies), `substitute_ast_types` it under the instance's binding, and
`_check_method` it. That IS stage 3's per-compile work, run against the
registry the branch already computes.

`examples/hello.saw` — a four-line program; total compile 1.13 s:

```
registry                       111 instances
(type instance, method) pairs  306
deepcopy                       0.76 s
substitute_ast_types           0.08 s
_check_method                  0.09 s
                               ------
TOTAL                          0.94 s   =  +83% on the compile
```

`examples/serde169_derived.saw` (119 instances / 323 pairs) and
`examples/json_value_object_serialize.saw` (119 / 306) both land within a few
percent of the same ABSOLUTE second, because the cost is std's type closure and
every program drags the same one in. So this is ~1 s added to EVERY compile in
the corpus, not a proportion of it. §5's envelope is +10% on suite and
bootstrap wall time; §5 remedy 1 is already applied (the phase runs once per
settled front half), remedy 2 can only remove the 0.09 s check, and remedy 3
plus the design-168 narrowing of the type closure are both unauthorized. §5's
own instruction for exceeding the envelope is that the staging PAUSES for the
lead rather than growing an optimization inside the migration.

THE COST IS `copy.deepcopy`, 81% of the total and 8x the whole budget on its
own. Two constructive directions, neither of them this agent's to choose:
(a) a purpose-built substituting AST copier in place of deepcopy-then-rewrite
— plausibly several times faster, and the one lever that could bring the
splice back toward the envelope; (b) LAZY BODY MATERIALIZATION — the registry
still DECIDES every instance (the unit's thesis is about deciding, not about
when an AST is built), splices eagerly only the instances the coroutine
transform must see, and materializes the rest at design 168's body demand,
which for an executable is a small fraction of 306. (b) preserves "no abstract
body reaches the transform" and costs the `-c` hosted object the full bill,
which is the case §1b already says the registry over-approximates for.

THE SECOND HALF, and the reason the perf number is not the only question. With
the check on at type-closure granularity, hello.saw reports ~30 diagnostics
over std's OWN bodies (276 of 306 clean). Sampled and verified against running
programs, two of the largest classes are diagnostics against CORRECT code:

  * `Vector<String>.copy` — ``type `String` is not Copy; `.copy()` requires a
    trivially-copyable, Copy, or ExplicitCopy type``, while
    `Vector<String>().copy()` compiles and runs today;
  * `Vector<Item>.push` for an `@synthesize`d ExplicitCopy `Item` — ``cannot
    copy value of type `Item` which implements ExplicitCopy``, while the same
    program compiles and prints its element.

Both are the abstract judgment failing to survive substitution — §3's "a rule
that should migrate up" class, one per rule, each owing a ruling. §7 stage 2's
gate rule ("any new diagnostic is a triaged finding … kept and pinned, or moved
to the skip list with the lead's sign-off") applies to every one of them, and
the per-program floor is ~30 before the corpus is considered. The count is
approximate — the probe checks in the merged namespace without
`current_type_params` — but its floor is not: two verified false positives are
two rules the §1c list does not yet name. [218c §1c/§3/§5/§7]

## ~~DF-284c — a trait REQUIREMENT has no callable method on a PRIMITIVE
## receiver, so a bound-resolved call stops resolving the moment the type
## argument is concrete~~ (filed Sep 1 by design 218 unit 1.5 stage 2, the
## first thing ever to look at an instance's diagnostics; PRE-EXISTING)
## **CLOSED Sep 1 by the minimal unit-3 slice the USER RULED forward into 1.5**
## — `_builtin_requirement_call` (typechecker/expressions.py) stamps the SAME
## `comparison_dispatch` design 239 built for the bound, so a concrete receiver
## lowers through `_emit_equals`/`_emit_compare`, the emitters `==` and `<`
## already use. No symbol is minted and no body moves, which is what makes
## behavioural identity a property of the code rather than a claim.
## EVIDENCE: the four formerly-refused corpus tests pass with the flip on —
## `unsigned_comparable_compare`, `unsigned_ordered_comparison`,
## `unsigned_handle_ordering`, `comparison_requirement_call_through_bound` —
## and `examples/comparison_requirement_concrete_receiver.saw` puts the
## operator, the requirement and the bound side by side at design 252's own
## boundary values (255 vs 127 at `UInt8`, `UInt.max` vs 1), where a signed
## lowering answers wrongly; all three columns agree. Full suite 2320 passed /
## 8 xfailed, freestanding 33 both arches, bench checksums unmoved.
## **SCOPE CORRECTION, USER-RATIFIED Sep 1.** The ruling
## scoped the slice to "the integer family, Float, Bool", which is what THIS
## entry's original matrix probed. Two of the four blocked tests walked past
## that fence, so the set is a PREDICATE — "the conformance has no callable
## method here" — and it has three members, each probed: primitives and any
## distinct ALIAS over one (`type_satisfies_bound` resolves aliases — design
## 252's lesson restated); `@synthesize`d ENUM conformances, derived by
## `_emit_enum_compare` and equally method-less (a `@synthesize`d STRUCT is
## NOT — it gets a real method and never reaches the arm); and `String`, the
## one member that HAS a same-named method, whose `equals`/`compare` take
## `other` BY VALUE and are therefore a different function from the
## requirement. String's own API is untouched at every spelling that works
## today: the arm requires the `&`, so `s.equals(t)` still resolves to
## String's method. `hash` is deliberately NOT in the slice — it has the same
## shape but is not part of the blocker (`k.hash(&var h)` through a
## `T: Hashable` bound compiles AND lowers at a primitive today, probed), so
## it stays with the rest of unit 3. Reversing the widening is one predicate.
## Kept below as the record.

```saw
let a: Int = 3
let b: Int = 9
a.compare(&b)            // error: type `Int` has no method `compare`
                         // hint: available methods: abs, clamp, is_even, …
a.equals(&b)             // error: type `Int` has no method `equals`
```

THE MATRIX, probed cell by cell (`.build/scratch/spec218c/p11_matrix.saw`):
`equals`, `compare` and `hash` are ALL missing on `Int`, `UInt8`, `Float` and
`Bool` — and by the same mechanism on every other fixed-width integer.
`String` is the exception and has them, because they are its OWN API rather
than a conformance (design 239 records that asymmetry deliberately). A USER
type is unaffected in both spellings: a hand-written conformance has a real
method, and a `@synthesize`d one has a synthesized real method, so
`p.equals(&q)` compiles on a concrete receiver.

MECHANISM (obligation 4): a primitive conforms to Equatable/Comparable/
Hashable BUILTIN, and the bodies for those conformances are synthesized in
CODEGEN (`_emit_equals` / `_emit_compare`) with no AST call node and no
checker-visible method — design 218's own charter names this as one of the
three shapes it exists to end ("Codegen decides"). The ABSTRACT path never
notices, because `<T: Comparable>` resolves the call against the TRAIT's
requirement signature rather than against the receiver; the concrete path has
only the receiver. So the gap is invisible in every position except one: a
generic body whose bound-resolved call is re-checked with the type argument
substituted in.

WHY IT SURFACED NOW. Design 218 unit 1.5 stage 2 makes a monomorphized
instance's diagnostics real (they were deleted, unread, by four sites in
effects.py). The instance clone has no type parameters and therefore no
bounds, so `rank<T: Comparable>`'s `a.compare(&b)` at `T = UInt8` is refused —
in a program that compiles and runs correctly today, because codegen supplies
the body the checker cannot see. FOUR corpus tests are exactly this:
`unsigned_comparable_compare`, `unsigned_ordered_comparison`,
`unsigned_handle_ordering`, `comparison_requirement_call_through_bound`.

NOT 1.5's TO FIX, and the reason is a SEQUENCING fact worth having: moving
those bodies out of codegen and into checked AST synthesis IS design 218 unit
3 in its own words ("`a > b` becomes `a.compare(b)` as an AST rewrite BEFORE
checking … Memberwise/enum/tuple equality synthesis moves from codegen
emitters to synthesized AST bodies checked like any `@synthesize` output").
1.5's instance check needs unit 3's desugar underneath it — the brief ordered
1.5 before 3 because 1.5 "defines the validated form", and this is the one
place that ordering costs something.

STATUS: stage 2's machinery is BUILT AND LANDED — the four deletion sites are
gone, §3's attribution note is attached, the §1c provenance skips are named
per rule — with the last step held behind `INSTANCE_ERRORS_ARE_REAL` in
typechecker/core.py, a module constant whose comment names this finding.
Flipping it to True is stage 2's landing, and it is a one-line change once
this closes. Held rather than pinned: an XFAIL here would be a brief xfailing
breakage IT introduced, which the policy forbids. [218, 218c §1c/§3, 239]

## DF-284b — the immediately-invoked closure `{ ... }()` does not parse, in any
## position (filed Aug 31 by design 218 unit 1.5's agent, stage 0; PRE-EXISTING,
## and never covered — `grep '}()' examples/` comes back empty)

Three faces, one mechanism, and the middle one is the loudest:

```saw
{ print("hi") }()          // error: closure literal is never called: `{ ... }`
                           //   in statement position ... builds a closure and
                           //   discards it — hint: call it — `{ ... }()`
print({ 2 }())             // Parse error: Expected RPAREN, got LPAREN
let x = { 1 }()            // SILENT: binds the CLOSURE; the `()` is dropped
```

The statement-position diagnostic (design 122 unit D, typechecker/statements.py
`visit_ExpressionStatement`) fires on `isinstance(stmt.expression, ClosureExpr)`
and its fixit names `{ ... }()` — which is refused by the same rule, because the
parser never built a call node. LANGUAGE_SPEC says the same thing in the same
words ("that is a compile error naming the two real spellings (call it,
`{ ... }()`, or bind it)").

MECHANISM (obligation 4): the postfix loop is not applied to a closure literal
`parse_primary` returns (parser/expressions.py, the `LBRACE` arm) — so every
postfix operator is lost after a `{ ... }`, not just the call. The positions the
mechanism reaches are therefore all of them, and the three probes above are the
three distinct OUTCOMES (refusal / parse error / silent drop) rather than three
separate bugs. The `let` face is the one that hides: it type-checks, binds a
`() escaping -> Int` and only surfaces at whatever the value is used for.

NOT FIXED HERE. The repair is a parser change with a real interaction to settle
— a statement-initial `{` versus the trailing-closure rule, and the design-129
newline significance of `}` followed by `(` — so it is a ruling, not a patch.
The only in-tree consumer was corodiff's `nested_block_tail` wrapper, which had
consequently never compiled a single pair; it now uses a nested `if true` scope,
which is what that row was measuring anyway. Either the form is made to work or
the two documents stop offering it; the status quo promises a spelling the
language does not have. [122, 129]

## DF-258a — a NESTED call to an unconditionally-suspending GENERIC silently
## loses its yield (filed Aug 25 by the 218c spec's probes P3/P3b; PRE-EXISTING
## — pinned at 218 unit 1.5 stage 0, flips at stage 4)

```saw
func hop<T>(x: T) -> T { yield_now()  x }
func nested(tag: String) -> Int {
    var i = 0
    while i < 2 { let v = hop<Int>(i)  print("{tag} {v}")  i = i + 1 }
    0
}
// two of these spawned into one TaskGroup print `A 0 / A 1 / B 0 / B 1`
```

Both tasks run to completion in turn instead of interleaving: the cooperative
contract is dropped, silently, with no diagnostic. The direct-`yield_now()`
twin interleaves, so the scheduler is not the variable. The emitted
`hop$1$Int` is `ret i64 %x` — the yield is not merely unobserved, it is gone.

MECHANISM: 218b's landing note (c), which found the hole while proving
consumption symmetry sound. Promotion DECLINES for a template that suspends
unconditionally WITHOUT calling a type-parameter method — such a template is
not `poly_candidate`, so no per-instantiation effect node is built and the
coroutine transform has nothing to classify — and codegen's late
monomorphization is then what serves the call. Codegen has no frame machinery,
so it emits the body as a plain function. The documented behaviour promises a
refusal at worst ("suspending calls embed at any nesting depth … or error
cleanly — never silently block"), and LANGUAGE_SPEC + the saw-lang skill both
still carry the sentence that calls this shape a clean error.

Pinned by `examples/coro_nested_generic_call_parks.saw` (cited XFAIL, the
interleaving oracle) and carried as a corodiff axis value
(`nested_generic_susp`), which is the ownership half the parity oracle can see.

CLOSES AT 218 unit 1.5 stage 4, structurally: phase 2 splices the instantiation
as an ordinary concrete function whose own effect node says it suspends, so the
transform's classifier sees an ordinary concrete suspending callee and embeds a
sub-frame — and the path that produced this ("codegen instantiates a suspending
body late, outside the transform") is unrepresentable once codegen can only look
instances up. [218c §6a]

## ~~DF-258b — unbounded RECURSIVE INSTANTIATION has no diagnostic~~ (filed
## Aug 25 by the 218c spec's probe P4; PRE-EXISTING, fuzz-oracle class)
## **CLOSED Sep 1 by design 218 unit 1.5 stage 1**, exactly as the spec staged
## it: the demand fixpoint records `depth = demander's depth + 1` and refuses
## past 64 per CHAIN at the DEMANDING call site, naming the chain in SOURCE
## spelling with the middle elided. Refusal test:
## `examples/errors/generic_instantiation_depth_limit.saw` (ships WITH the fix
## — a hang cannot sit in the corpus as an XFAIL), and it earned its keep
## immediately: a 64-deep `Wrap` chain is what exposed an exponential descent in
## the walk's own argument closure, which had hung a suite worker. Kept below as
## the record.

```saw
struct Wrap<T> { inner: T }
func deepen<T>(x: T, n: Int) -> Int {
    if n <= 0 { return 0 }
    deepen(Wrap<T>(inner: x), n - 1)
}
```

A template that demands ITSELF at a grown argument makes the instance set
infinite. At filing the compiler produced no output in 120 s and was killed;
re-probed Aug 31 it now dies as `internal compiler error … maximum recursion
depth exceeded` at the recursive call, which is Python's own limit arriving
first — an ICE rather than a hang, and the same finding either way. No corpus
pin is legal for a hang, so the refusal test ships WITH the fix.

MECHANISM: `_instantiate_generic_function` recurses through
`_generate_function_call`, building `deepen$1$Wrap$1$…` forever. Nothing counts
depth, because nothing decides the instance set as a whole — codegen discovers
instances lazily and one at a time, so there is no place a chain length exists
to be bounded.

CLOSES AT 218 unit 1.5 stage 1: the demand fixpoint records `depth = demander's
depth + 1` (roots at 0) and refuses past 64 per CHAIN with a clean error at the
DEMANDING call site naming the elided chain. Per-chain, so wide-but-shallow
programs are untouched, and it refuses only what today cannot finish.
[218c §1d, §6b]

## DF-276a..c — filed Aug 28 by design 253 (the Float↔text build); all three
## PRE-EXISTING and probe-verified by direct compile/run

**DF-276a — an unrepresentable float literal degrades silently.** Repro,
compiles clean and prints `inf` then `0.0`:

```saw
func main() {
    let over = 1000…000.0        // 1 followed by 400 zeros
    let under = 0.000…0001       // a point, 400 zeros, a 1
    print(over.to_string())      // inf
    print(under.to_string())     // 0.0
}
```

MECHANISM: the decimal→binary64 conversion the lexer performs on a float
literal has no representability check. The integer literal path does have one
and reports it at the literal (`let n: UInt8 = 300` -> ``integer literal 300
does not fit in `UInt8` (range 0..=255)``), so the two literal kinds disagree
about whether a value that cannot be represented is an error.

CLASS: one funnel, so every position a float literal can appear inherits it —
a `let`, a `static`, a field, an argument, an arm. Two faces (overflow to an
infinity, underflow to a zero), and the underflow one is the more dangerous:
`inf` at least propagates visibly.

Worth noting the lexer's conversion is otherwise CORRECTLY ROUNDED, verified
by design 253's probes at both extremes (a 324-character literal for the min
subnormal lexes to bits `1`). Only the range check is missing.

**DF-276b — no `Int` -> `Float` conversion exists, in any spelling.**

```saw
let n = 7
let a: Float = n      // error: cannot assign `Int` to variable of type `Float`
let b = n as Float    // error: cannot cast `Int` to `Float`
let c = Float.from(n) // error (and `Float(n)` is a struct-init error)
```

MECHANISM: design 170's conversion family is defined over the INTEGER
source/target pairs; the float axis was never added. Not a defect in a check —
an absent capability, which is why it reads as four different errors.

CLASS: the whole axis, both directions. `Float` -> `Int` is equally absent
(`f as Int` is `cannot cast`), and that half has the sharper question: a
truncation, a round, and a floor are three different operations and Saw's
naming rules would want three names.

COSTS ALREADY PAID: `std.string` carried a ten-branch `_digit_to_float` purely
to convert 0..9 (design 253 deleted it); `JsonValue` can offer no combined
`as_number() -> Float?` over its two number cases; and a float parser can have
no small-integer fast path (design 253's builds its results from BITS instead,
which works but is the long way round). Wants a design rather than a patch:
the rounding mode of an `Int` too wide for a `Float`'s 53 bits is a ruling,
and so is whether the conversion is `as`, `from`, or both.

**DF-276c — a value `if`/`match` does not adopt the width of the operand it
sits beside.**

```saw
let wide: UInt64 = 40
let a = wide + 1                        // fine: a bare literal adopts
let b = wide + (1 + 1)                  // fine: DF-243a's fix
let c = wide + (if up { 1 } else { 0 })
// error: operator `+` requires both operands to have the same type,
//        but the left is `UInt64` and the right is `Int`
```

MECHANISM: DF-243a threaded the expected type from a typed operand into a
mixed-binop CONST expression. A value `if`/`match` is not a const expression,
so nothing carries the width into its arms, and they type as platform `Int`.

CLASS: probed siblings all WORK — an argument (`takes(if up { 1 } else { 0 })`
at a `UInt64` parameter), an annotated `let`, a `return` at a `UInt64` return
type, and a compound-assign RHS (`n += if up { 1 } else { 0 }`). So this is
narrow: exactly DF-243a's position, with a branch construct where the const
expression was. Design 253's code hit it four times and worked around it by
binding the branch to an annotated `let` first, which is also the fixit the
diagnostic should suggest.


## DF-264a — the Copy tier's checker misses the deinit-signature validation
## (filed Aug 27, lead-probed from the user's scratch example)

- `@synthesize extension T: Copy { func deinit(&self) }` — receiver should be
  `&var self` — is not diagnosed and reaches codegen, which dies with
  `internal compiler error: Type of #1 arg mismatch: %"T" != %"T"*` on ANY
  program declaring the type (no copy, no container needed). The SAME wrong
  signature under ExplicitCopy or NoCopy gets the clean located
  ``method `deinit` should take `&var self` to conform`` — so the matrix is
  one missing cell: the validation is duplicated PER TIER and the Copy path
  lacks its copy. With `&var self` the Copy-with-deinit shape works exactly
  as the spec's Ticket example promises (probed: runs, one deinit per live
  copy). Mechanism named (obligation 4): a per-tier duplicated check instead
  of a funnel — the fix puts the signature validation at one chokepoint over
  all three tiers, and probes the NON-`@synthesize` Copy-with-body row (the
  spec's hand-written-copy Ticket shape) the lead did not reach. Owes a
  cited XFAIL pin when dispatched. Probes were
  `.build/scratch/probe_copy_deinit_m1-m7` (ephemeral; the matrix above is
  the record).

## DF-266a — a leading-minus tail after an `if { return }` block is an ICE
## (filed Aug 27 by the std.json build; lead-verified)

- `func h(b: Int) -> Int { if b >= 48 { return b - 48 }` newline `-1 }` dies
  `internal compiler error at FILE:5:5 (BinaryOp): 'NoneType' object has no
  attribute 'type'` — the breadcrumb names a BinaryOp AT the `-`, so the
  tail's leading minus is being parsed/typed as a BINARY operator whose LHS
  is the preceding block statement (which has no type). The same `-1` tail
  after a plain `let` compiles and runs, so the boundary is a BLOCK
  statement (at least `if`-with-`return`) preceding the sign. `return -1`
  is the trivial spelling that avoids it. Probes
  `.build/scratch/probe_negtail{,2}.saw` (ephemeral; cells recorded here).
  Fix wants the design-129/161 newline-and-token rules consulted: a
  statement-start `-` after a closed block should open a new expression,
  and whichever answer is ruled, the ICE becomes a clean parse/type error.

## DF-267a..d — filed Aug 27 by std.json unit 1 (the JsonValue build); all
## probe-verified by direct compile/run, repros in the entry

**DF-267a — OPEN.** `v.get(0).is_some()` on a `Vector<Int>` errors ``type
`Int` has no method `is_some``` (plus a `__window` signature mismatch) — an
Optional-only method called directly on a `borrows -> T?` accessor's result,
with no `!` or binding between, resolves against the unwrapped `T`.
Identical on `Map.get`. Contradicts DF-218a's documented "presence is
tier-independent at every spelling"; `if let _ = <lend>` is the working
presence test. Suspect: the conditional-lend spelling commits to opening the
window before the member lookup ever sees `Optional`.

**DF-267b — FIXED Aug 28** (commit "DF-267b: an enum case's declared payload
types get the design-37 default fill"; stage 1 of the queue item — stage 2,
`Object` serialization, remains QUEUED). MECHANISM: an enum case's payload
types are one of the three RAW declaration slots, and `enum_info.variants`
hands them out AS WRITTEN. The struct-field twin resolved because
`_check_member_access` ends in `_resolve_type`, which is where design 37's
fill lives; the match arm's payload binding read the raw list and never
resolved, so `Map<String, Int>` reached the binding with two arguments where
the type has three parameters and `keys()` answered `Vector<String, A>`.
FUNNEL (obligation 1): `_variant_payload_types`
(`sawc/typechecker/expressions.py:11609`) is now the one read, substitution
then `_resolve_type`, docstring naming its four entry points — the classic
enum-switch arm bindings + their consume gate, `_pattern_enum_variants` (the
general pattern path), a variant CONSTRUCTION's expected argument types, and
the `try(as Enum.Case)` routing payload (that last one already resolved on
its own and now shares the funnel instead of keeping a private copy).
SWEEP MATRIX (obligation 4) — ten rows failed pre-fix, all pass post-fix,
carried by `examples/match_payload_binding_fills_default_type_args.saw` and
`examples/payload_derived_binding_fills_default_type_args.saw`: the classic
switch arm (the filed cell), the general path a guard routes to, a match
nested in a match, a tuple-typed payload, a generic enum's own parameter, and
— all DERIVED from a payload binding, so all fixed by the one funnel —
`if let` / `guard let` / `while let` payloads, a closure PARAMETER, a tuple
destructuring, and a `for` binding over a generic container. CONTROLS that
already resolved and stay green: a struct FIELD, a function PARAMETER, an
annotated LOCAL, and each derived form fed by one of those. TERRAIN
re-verified: all three DF-267d dissolution shapes compile AND RUN in std with
the fix. cbor CHECKED Aug 27: needs no sibling fix — zero keys/each/match-
binding Map use in cbor.saw and no tree type; the fix being compiler-wide
covers cbor USERS' hand-written Serialize code for free.

**DF-267c — OPEN.** In a hand-written `borrows` accessor, `lend items[at]`
where `items` is a MATCH-BOUND payload fails ``cannot open an exclusive place
window on immutable variable `items``` — the docs' own `Grid.[]` example
lends `self.cells[i]` (field projection) and works. Same for `Map`'s
subscript, so not about conditionality: a match binding is not a lendable
place ROOT for deeper projection, only whole-payload lend works (DF-146d's
arm-lend). This is why JsonValue ships `as_array()`/`as_object()` +
caller-side indexing instead of `element(at:)`/`member(key:)`.

**DF-267d — CONFIRMED-CLOSED Aug 28** (the Object-serialization landing —
`examples/json_value_object_serialize.saw` et al., `JsonValue._write`'s
`Object` arm — is the confirming probe the Aug-27 dissolution note asked for;
see the queue entry above for the commit. ONE REFINEMENT the confirmation
surfaced: dissolution is shape-sensitive, not unconditional. The three
Aug-27 probe shapes below were right, INCLUDING the third one's own detail —
"Object arm via a param-routed keys helper, **Array arm recursing inside
`Vector.each`'s closure**" — that Array-via-closure detail is LOAD-BEARING,
not incidental: the landing's first attempt kept `Array`'s original `while`
loop (a DIRECT self-call) and routed only `Object` through `Map.each` (a
CLOSURE self-call), and that MIXED shape reproduced the original failure
verbatim, anchored on the untouched `Array` arm's line
(`cannot suspend in a sync closure context: closure calls JsonValue._write →
Map.each → a call through a non-sync function value`). Converting `Array` to
recurse through `Vector.each`'s closure too — so `_write` self-recurses via a
CLOSURE at every call site, never a direct one — is what actually compiles,
exactly matching shape 3 as originally probed. So the mechanism is
unconditionally dissolved for "self-recursive + reaches a non-sync closure
API," but a function with BOTH a direct and a closure-mediated self-call site
still needs every self-call site to agree on closure-mediation. Original
filing follows, lightly re-punctuated for the closed tense.) A self-recursive
function under `sawc/std/` that also transitively reaches a maybe-suspending
closure API (`Map.keys`/`each_key`/`Vector.each` beside a second closure
dependency — any closure param without `sync`, deliberate per design 216)
used to fail sawc's builtins pre-check with `internal compiler error:
builtins failed to type-check` / `cannot suspend in a sync closure context` —
while the IDENTICAL shape compiled and ran as an ordinary user file (even
importing the real JsonEncoder). Decisive isolation by the filer: recursion
alone in std fine; recursion + `Vector.each` fine; recursion + `Map.keys`/
`each_key` broke, and the reported line shifted between call sites across
otherwise-identical edits (misattribution). Mechanism (obligation 4, as
filed): the builtins pass computes ONE effect signature per function, and its
fixed-point for a self-recursive function depending on a non-sync leaf API
was unsound — reaches any recursive std type enumerating a Map, not JSON.
Consequence while open: `to_json_string` answered `EncodeFault.Unsupported`
for any tree containing an `Object` (parse was full — parsing only ever
called `Map.insert`). The fix closes JSON.md's Object serialization cell.

## DF-272a..c — filed Aug 28 by the DF-267b fix's obligation-4 sweep; all
## three PRE-EXISTING and probe-verified by direct compile/run

**DF-272a — OPEN.** An enum VARIANT construction does not push its declared
payload type into a closure-literal argument, so the closure's parameter type
is never inferred — while the struct-init twin does, through
`_check_init_field_value`. Same file, side by side:

```saw
struct FnField { f: (Int) -> Int }
enum Holder { case Handler(f: (Int) -> Int) }

let s = FnField(f: { c in return c + 1 })          // infers, runs
let h = Holder.Handler(f: { c in return c + 1 })   // Cannot infer type for
                                                   // closure parameter `c`
```

Mechanism, as far as the sweep took it: `_check_enum_init` checks each
argument against `expected_params` but has no equivalent of the struct path's
"if the value is a ClosureExpr and the expected type is a FUNCTION, check the
closure AT that type" step. Probe `.build/scratch/probe_enuminit_closure.saw`
(ephemeral; the four lines above are the whole of it). Reached while probing
whether a closure parameter is one of the positions DF-267b's missing fill
touched — it is not, and the fill does not change this cell either way.

**DF-272b — OPEN.** `_resolve_type` (`sawc/typechecker/types.py:1707`) fills
design-37 defaults only when the written type ALREADY has type arguments —
`if saw_type.type_args:` guards the whole arm — so a BARE reference to a
generic whose every parameter is defaulted never gets a fill at all. Written
out it works; written bare it does not:

```saw
struct Drain<A: Allocator = GlobalAllocator> { left: Int }
extension Drain<A: Allocator>: Iterator {
    type Item = Vector<Int, A>
    public func next(&var self) -> Vector<Int, A>? { … }
}
struct Explicit { d: Drain<GlobalAllocator> }   // for v in e.d { v.len() } OK
struct Bare     { d: Drain }                    // `Vector<Int, A>` has no
                                                // method `len`
```

Not the DF-267b mechanism — the struct-FIELD control fails here too, which is
what separates them. Same design-37 family, and the fix moves type IDENTITY
for a whole class of types (a bare `Drain` and a `Drain<GlobalAllocator>`
would collapse to one mangled name), so it wants a ruling rather than a
drive-by. Probe `.build/scratch/probe_bare_default.saw` (ephemeral; the
snippet above is the whole of it). No pin: the shape needs an
all-parameters-defaulted generic, which nothing in the corpus has.

**DF-272c — OPEN.** A maybe-suspending call made INSIDE a place window is
refused under `sawc/std/` and accepted in a user file. `Map.get` is a
`borrows` accessor, so `&kids.get(k)!` opens a window whose body is a `sync`
closure; a recursive callee that transitively reaches `Map.keys` (a closure
parameter without `sync`, deliberate per design 216) is then
``cannot suspend in a `sync` closure context: closure calls `count` →
`Map.keys` → `Map.each_key` → a call through a non-`sync` function value``.
The identical enum/`Map`/recursion shape as an ordinary source file compiles
and RUNS (probe `.build/scratch/probe_window_suspend.saw`, ephemeral); the
in-std twin was probed by temporarily adding it to `sawc/std/json.saw`,
reverted after. FOURTH member of the builtins-vs-user-file divergence family
— DF-257c (closed), DF-267d (dissolved), DF-271a (open) — and it carries that
family's standing question unchanged: why does the builtins pass check
differently from user-file checking AT ALL. CONSEQUENCE FOR THE QUEUE: stage
2's natural Object-walk spelling is `fields.get(k)!._write(enc:)`, which is
exactly this shape, so stage 2 either routes through `each_value` (which
works in std today — it is DF-267d's shape 2) or waits on this.

## DF-261a..f — filed Aug 27 by design 246's implementer; a/b FIXED in that
## landing, c/d/e/f OPEN

**DF-261a — FIXED (design 246 unit A).** `Namespace._has_abstract_type_arg` was
the one recursion into `copy_tier` that started a FRESH `_visiting` set, so the
guard the two structural joins carry could never fire on a cycle running through
a user generic. `struct Pair<T> { a: T }` beside `enum E { case K(p: Pair<E>) }`
recursed until Python's stack ran out (`internal compiler error: maximum
recursion depth exceeded`). Fix: thread `_visiting`.

**DF-261b — FIXED (design 246 unit B).** The SAME mechanism, second site:
`Namespace._satisfies_thread_bound` re-entered `_send_sync` with `set()`. Every
LEGAL recursive shape reaches it — `enum Json { case Items(items: Vector<Json>) }`
asks whether `Vector<Json>` is Send, `Vector`'s conditional
`extension Vector<T: Send, A: Send>: UnsafeSend` header asks whether `Json` is,
and the walk starts over. Fix: thread `visiting`, with `want_sync` added to the
key so one set serves both questions. THE MECHANISM SWEEP (obligation 4) found
exactly these two: the three guarded structural walks in `namespace.py` are
`copy_tier`, `_send_sync` and `is_cell_carrying`; the third threads its guard
through every helper it has.

**DF-261c — OPEN.** `==` on an ENUM ignores a hand-written `Equatable.equals`
and does the structural payload compare instead, so a body that answers `true`
loses to an `==` that answers `false`. PRE-EXISTING and nothing to do with
recursion — probed on the unmodified compiler:

```saw
enum Bag { case Empty, case Full(k: Vector<Int>) }
@synthesize
extension Bag: ExplicitCopy {}
extension Bag { func size(&self) -> Int { match self { case Empty -> 0, case Full(k) -> k.len() } } }
extension Bag: Equatable { func equals(&self, other: &Self) -> Bool { self.size() == other.size() } }
// a = Full([1,2]); b = a.copy()
// "equal? {a == b}"        -> false      <- the structural compare
// "direct? {a.equals(&b)}" -> true       <- the body
```

`_emit_equals`'s ENUM arm goes straight to `_emit_enum_deep_equals` and never
asks whether the type has its own `equals`; the STRUCT arm one line above does
ask. Reached only when a payload is not itself Equatable (a `Vector` here),
because `@synthesize` refuses that case and a hand-written body is the only way
in. Cost: design 246's row 7 could not pin the `Equatable` half of its brief.

**DF-261d — OPEN.** `Box` payload-method forwarding (design 42 item 1) reaches
a STRUCT payload's extension methods and NOT an ENUM payload's, so a
`Box`-linked recursive enum has no Saw-level traversal:

```saw
enum Tag { case One, case Two }
extension Tag { func rank(&self) -> Int { match self { case One -> 1, case Two -> 2 } } }
let t = try! Box<Tag>.make(value: Tag.Two)
t.rank()   // error: … hint: available methods: deinit, make, value
```

The struct twin (`b.twice()` on a `Box<Leafy>`) works. Design 145 gave enums a
method surface and the forwarding resolver was never widened to it.

**DF-261e — OPEN.** An optional chain through a `Box<T>?` FIELD is an internal
compiler error, with no recursion in sight:

```saw
struct Holder { slot: Box<Leafy>? }
extension Holder { func total(&self) -> Int { self.slot?.twice() ?? 0 } }
// internal compiler error at …:11:18 (BindOptional):
//   BindOptional lowered outside an optional chain
```

Together d and e are why design 246's rows 2 and 3 use the DEINIT order as the
depth oracle rather than a written walk.

**DF-261f — OPEN, pre-existing (verified by running the same probe against the
main checkout's compiler).** A directly RECURSIVE suspending function makes the
coroutine transform recurse forever building the embedded sub-frame, and it
escapes the internal-compiler-error funnel as a RAW Python traceback — the
transform is not wrapped the way the typechecker and codegen are:

```saw
import std.task.*
func countdown(n: Int) -> Int {
    if n <= 0 { return 0 }
    yield_now()
    countdown(n - 1)      // embeds its own frame by value
}
// RecursionError: maximum recursion depth exceeded, in
// coro_transform.py:_build_frame_init -> _zeroed_value -> _zero_of
```

A suspending frame embeds its callee's frame BY VALUE, so a self-call is the
same infinite-size shape design 246 unit A refuses for nominal types — but the
frames are synthesized after that check runs, so it does not see them. Two
halves owed: the transform under the ICE funnel (so this is a located refusal
rather than a traceback), and the refusal itself, which should say what the
nominal one says.

## DF-247a — a function that is a `group.spawn` ROOT is `undefined function`
## at every OTHER call of it in the same module (filed Aug 22 by design 242
## unit 0's census probes; PRE-EXISTING, verified by stash against the branch
## point 361ea0bf)

```saw
func work(n: Int) -> Int { n * n }

func main() {
    print(work(2))                    // error: undefined function `work`
    var group = TaskGroup()
    let h = group.spawn(work(5))
    print(h.join())
}
```

Reordering the two does not help, and the error anchors on the ORDINARY call,
which is the one line that has nothing wrong with it. `examples/` has no
program that spawns a function and also calls it, which is why the shape has
sat unnoticed; it is easy to reach the moment a body is worth both running
inline and running as a task.

MECHANISM (obligation 4): the coroutine transform's spawn-root rewrite. A
`group.spawn(f(...))` records `f` a spawn root, and the transform replaces the
authored `f` with the frame machinery (`__Frame_f`, `f$spawnroot`,
`__spawn_f`) before the entry module is re-typechecked — so the ordinary call,
which was never rewritten, resolves against a function table the original name
has left. The mechanism reaches every ROOT KIND the transform substitutes, so
the sweep the fix owes is the root matrix: `group.spawn`, `__saw_drive` /
`__saw_drive_steps`, a `Thread.spawn { }` closure body naming a spawned
function, and a spawn root that is also called from a THIRD function rather
than from the spawner. Only the first cell is probed so far (the two spellings
above); the rest are unprobed and presumed to be the same cell.

Not pinned yet — a pin belongs with the sweep, and design 242 stopped at
recording the shape rather than growing an unrelated fix. [52b, 242]

## DF-251b — a generic extension's `init` REGISTERS no param cleanups, where
## the non-generic twin does (filed Aug 24 by DF-251a's fix; PRE-EXISTING)

DF-217m gave `_generate_init_method` a param cleanup scope: an `init`'s
by-value owning param that no path moves into the built value is the
initializer's to release. `_generate_init_method_generic` never grew one — it
pushes no scope and calls `_register_cleanup` for nothing — so the same
un-moved owning param leaks in a GENERIC extension's init. DF-251a's fix
isolates the state (which is the miscompile) and deliberately leaves the
registration alone, because turning drops on is a behavior change that wants
the placement-move tracking checked first, exactly as design 65 had to for
instance methods. Same function also never populates `variable_types` for its
params or sets the design-192 `_current_decl` breadcrumb, so an ICE inside a
generic init body names no declaration. One fix, three faces. [234]

## DF-251c — DF-216h's extension-parameter RENAME does not reach an `init`'s
## parameters at the construction site (filed Aug 24 while writing DF-245a's
## receiver-spelling control; PRE-EXISTING)

```saw
struct Pair<A> { first: Int, second: A }
extension Pair<U> {
    init(three: U) -> Pair<U> { Pair<U>(first: 3, second: three) }
    func peek(&self) -> U { self.second }
}
let p = Pair<Int>(three: 11)
// error: parameter `three` expects type `U` but got `Int`
```
The METHOD half works (DF-216h landed Aug 21). MECHANISM: `_check_struct_init`
builds its `type_mapping` from the STRUCT's own parameters (`A` -> `Int`) and
substitutes the init symbol's `param_types` with it, but those types are
written in the EXTENSION's names (`U`), so nothing maps. The method path routes
through `_receiver_type_subst`, which reads `owner_type_params` — the
extension's own names, already recorded on every method symbol including an
init's. So the fix is to ask the same question at the construction site; the
data is there. The RETURN spelling is unaffected: DF-245a's declaration check
accepts `Pair<U>` and reports nothing here. Boundary recorded in
`examples/init_receiver_return_spellings.saw`. [216]

## DF-251d — an `init` BODY that suspends is an internal compiler error
## (filed Aug 24 by DF-245a's suspending-init probe; PRE-EXISTING)

```saw
extension Other { init(seed: Int) -> Other { Other(m: slow(seed)) } }
// slow() calls yield_now()
// internal compiler error at f.saw:18:13 (StructInit): 'Other_init_seed'
```
The identical NON-suspending init compiles, so the suspension is the cause.
MECHANISM: `coro_transform` enumerates `ext.methods` with no `is_init` filter
anywhere in the file, so an init body IS scanned and IS transformed — but a
construction is a `StructInit` (or a labelled `FunctionCall`), never a
`MethodCall`, so `_scan_method_callees` can never name the frame and the plain
mangled symbol the call site looks up is gone. Either end is a fix: teach the
scan the construction node kinds, or refuse a suspending `init` at the
declaration the way design 141 refuses a `borrows` one. This is the BOUNDARY
DF-245a's brief was asked to record: a fallible `init` may not suspend today,
and the failure is an ICE rather than a diagnostic. No XFAIL pin — an
ICE-producing example is a fuzz-oracle finding by construction and would need a
`sawfuzz_known.txt` entry to sit in the corpus; the repro is above. [234, 120]

## DF-250a — a COLLECTION LITERAL does not shape through a `Result`'s Ok
## payload (filed Aug 22 by DF-245c's return-position sweep)

`func row() -> Result<Vector<Int>, Stop> { return [1, 2, 3] }` is ``expected
return type `Result<Vector<Int, GlobalAllocator>, Stop>` but got `[Int; 3]`
(doesn't match Ok type `Vector<Int, GlobalAllocator>` or Err type `Stop`)``, and
the TAIL spelling gives the same refusal in `_reconcile_return_type`'s words. The
bare `-> Vector<Int>` twin compiles and runs. Pre-existing and spawn-independent
(both cells of the sweep row failed identically), so it is not the transform.

MECHANISM (obligation 4): `_apply_literal_expected_type` is the design-54
shaping funnel and it is handed the DECLARED return type, which here is a
`Result` — it has no Result arm, so the literal is never told it is a `Vector`
and stays a `[Int; 3]`. The auto-wrap ladder then runs on an already-wrong type
and reports the mismatch. Two payload peels already exist for this exact
position and neither is shaping: `_apply_literal_expected_type` case (0d) peels
to the unique payload that can take a bare INTEGER literal (DF-226e), and
`_prepare_ok_payload` peels the Ok OPTIONAL (DF-140d). SIBLINGS the mechanism
reaches, unprobed: every literal kind case (0) shapes — Map, Set, the repeat
literal, a tuple — at an Ok payload, and the same at the `T?` layer
(`Result<Vector<Int>?, E>`). The fix is a third peel at the same place, so the
sweep's grid is (literal kind) x (Result / Result-of-optional) x (return, tail,
argument, `let`). Workaround: bind the literal to an annotated local first.
[54, 226, 234]

## DF-250b — a `??` whose DEFAULT is a bare `None` at a NON-optional peeled
## type is an LLVM ICE, not a refusal (filed Aug 22 by DF-245c's sweep)

```saw
func row() -> Int? {
    let a: Int? = None
    return a ?? None
}
// internal compiler error: LLVM IR parsing error
//   '%.6' defined with type '{ i1, i64 }' but expected 'i64'
//   %"coalesced" = phi i64 [%"some_value", %"some"], [%".6", %"none"]
```

`??` peels ONE layer, so on an `Int?` left operand the default owes an `Int` —
and a bare `None` is not one. The documented behaviour is a clean error naming
both types (the skill's `v.get(9) ?? v.get(0)` row); what happens is a verifier
failure. Pre-existing and spawn-independent. The two-layer twin
`v.get(9) ?? None` on a `Vector<Int?>` (peeled type `Int?`) works, which is what
makes this the missing REFUSAL rather than a broken adoption.

MECHANISM (obligation 4): `_check_nil_coalesce` pushes the PEELED type into the
default through `_propagate_optional_type`, which stamps whatever it is handed
onto a `NoneLiteral` without asking whether it is an optional at all — so the
`None` is annotated `Int`, codegen reads no `inner_type` off it, falls back to
the enclosing function's `Int?` return and builds a `{i1, i64}` for a slot the
phi types `i64`. So the funnel has one unguarded stamp and the type check never
fires. SIBLINGS the mechanism reaches, unprobed: every other caller that peels
before propagating, and every position where the resulting non-optional stamp
could reach codegen. The fix wants the refusal FIRST (a bare `None` at a
non-optional expected type is a type error, wherever it lands), with the funnel
guard beside it — DF-245c's commit guards only the durable `expected_type`
stamp it added, deliberately, so as not to change this shape's fallout before it
is decided. [111, 234]

## DF-252a — calling a `FuncPointer` value BY NAME inside a driven body is an
## internal compiler error (filed Aug 24 by design 242 unit 4)

```saw
func doubled(n: Int) sync -> Int { n * 2 }
func worker() -> Int {
    let p: FuncPointer<(Int) sync -> Int> = doubled
    yield_now()
    p(4)
}
// group.spawn(worker())
// internal compiler error at f.saw:5:5 (FunctionCall): Undefined function: p
```

Design 226 says a `FuncPointer<F>` is an ORDINARY value that travels through
every composite, and designs 210/223 say a suspending body is ordinary code with
a frame under it. Where the two meet, the compiler dies. PRE-EXISTING; invisible
until design 242 ruling 8 refused `Thread.spawn { worker() }`, the spelling
`funcpointer226_composites.saw` used to make this claim with — a thread body is
not driven, so its `yield_now()`s were no-ops and no frame was ever built, and
the section passed while checking nothing.

MECHANISM (obligation 4): `_frame_field_encoding` (coro_transform.py ~560)
classifies a frame field by TYPE KIND, and `_rewrite_expr_node`'s call rewrite —
the one that turns a call to a frame-resident callable `f(args)` into the
indirect field call `self.f(args)` — is keyed on the `opt_closure` encoding,
which only a `TypeKind.FUNCTION` field gets. A `FuncPointer<F>` is a one-word POD
STRUCT, so it lands on `plain`, no rewrite fires, and the call reaches codegen as
a bare `FunctionCall(name="p")` — which `_generate_function_call` resolves
against `self.variables`, where a frame field is not.

MATRIX (probed Aug 24, four failing cells + three green controls):

| cell | shape | result |
|------|-------|--------|
| A | a `FuncPointer` LOCAL, suspension between the binding and the call | ICE |
| B | the same local, suspension AFTER the call | ICE |
| C | a `FuncPointer` PARAMETER of the driven body | ICE |
| D | a `FuncPointer` FIELD read into a local, then called | ICE |
| E | control: a plain CLOSURE local called in a driven body | works — the `opt_closure` rewrite |
| F | control: the same `FuncPointer` local called in a SYNC body | works |
| G | control: a `FuncPointer` field called DIRECTLY (`t.run(4)`) | works — the MemberAccess path never consults `self.variables` |

B is the sharp one: the call needs no suspension near it, so this is not about
the value crossing a state boundary — it is about the BINDING being frame-
resident at all. G is the workaround (keep the pointer in a struct field and call
it through the field) and is also the shape a dispatch table already has, which
is why design 226's own tests never hit this.

The fix is a third encoding arm or a widened rewrite predicate — "a frame field
whose type is CALLABLE", which today means `TypeKind.FUNCTION` or a
`FuncPointer<F>` struct — and it belongs with the DF-226b/c FuncPointer batch
rather than with design 242. Pinned XFAIL:
`examples/funcpointer_call_in_a_driven_body.saw`. [226, 242]

## DF-256b — the thread control block's DEALLOCATION SIZE is computed by hand
## in std and disagrees with the one codegen allocated (filed Aug 25 by
## design 242 unit 3b; PRE-EXISTING)

Spawn codegen allocates `_abi_size({ i8* tid, i8* env, word state, T result })`
and `Thread<T>.join` frees with the hand-written `24 + sizeof<T>()`
(`std/task.saw`); `VoidThread.join` frees with a bare literal. The two agree
only when `T` needs no padding: for a `Void` body the real ABI size is 32 (a
1-byte placeholder rounded to the block's 8-byte alignment) against the
literal's 24, and for a `T` whose alignment exceeds the word the arithmetic
misses the padding LLVM inserts. The pre-242 numbers had the same shape (16 vs
a real 24), so this is not new — unit 3b moved both constants and left the
approximation exactly as it found it.

INERT ON BOTH HOSTED ALLOCATORS, which is why it has never been seen:
`__saw_rt_dealloc` is `free()` there and the size argument is ignored. It is
NOT inert for a freestanding runtime with a sized-free allocator, which is the
profile the seam's size argument exists for at all.

The fix wants the size to stop being computed twice. The block already carries
it — unit 3b's handshake word holds the block's own size until one of the two
parties takes it — so `join` could read it rather than recompute it, which
would also make the `Void` and non-`Void` paths one. That reading is what
`__saw_rt_thread_detach`'s C body already does. Not pinned: an XFAIL wants a
behaviour that differs, and on both hosted allocators nothing does. [123, 242]

## DF-257a — the two construction checkers SELECT an init differently, so a
## DEFAULTED parameter resolves at the bare spelling and not the qualified one
## (filed Aug 25 by design 234 unit 3's hazard sweep; PRE-EXISTING)

DF-245a's landing named this as one of two things unit 3 would meet. Probed both
directions:

```saw
// hz/lib.saw
public struct Plain { value: Int }
extension Plain { public init(n: Int = 5) -> Plain { Plain(value: n) } }
```
```saw
import hz.lib.{Plain}     func main() { let p = Plain()      }   // compiles, n = 5
import hz.lib             func main() { let p = lib.Plain()  }   // refused
// error: no matching initializer for `Plain` with parameters:
//   hint: field init expects: value; available init methods: [['n']]
```

MECHANISM (obligation 4): `_check_struct_init` matches an init by "the provided
names are a SUBSET of the parameters and every omitted one has a default"
(design 53); `_check_module_struct_init` matches by SET EQUALITY
(`provided_params == init_param_names`), so a defaulted parameter the caller
omits removes the match instead of being filled. One rule, two implementations,
and only one of them learned about defaults. The mechanism reaches every
construction the qualified path serves — a defaulted init is the found cell, and
the sibling cells are anything else the subset rule accepts that equality does
not.

THE FALLIBLE FORM MAKES IT WORSE, which is how design 234 met it: the qualified
path returns the RECEIVER type on a failed match, so `try! lib.Holder()` then
reports a SECOND error about the caller's own `try` (``try` requires a Result
type, got `Holder``) — the caller is told its spelling is wrong when the callee's
signature is what was never read. The non-fallible twin above reports once.

NOT REACHED BY DESIGN 234's FLIP: every constructor the flip touches
(`Vector(capacity:)`, `Data(capacity:)`, `Arc(value:)`, `Channel()`,
`StringBuilder(capacity:)`, `TaskGroup(threads:)`) has no defaulted parameter,
and the one std init that does — `cbor.CborEncoder(max_depth: Int = 64)` — does
not become fallible. So the flip records this rather than fixing it: the fix is a
selection rule moving to ONE predicate both checkers ask, which is its own
funnel-extraction commit. [53, 234, 245]

## DF-257b — §5 keeps the `copy()` hook infallible, so `Vector.try_copy` is the
## one alloc `try_` twin the flip cannot retire (filed Aug 25 by design 234
## unit 3)

Design 234 §4 narrows the `try_` prefix to ONE meaning, non-blocking, and unit 0
counted `try_copy` in the retiring family with `copy` as its infallible partner.
§5 rules the other way for that pair: "the compiler-inserted `copy()` hook stays
infallible (design 219's contract)". `Vector.copy` IS that hook — its signature
is `ExplicitCopy`'s (`func copy(&self) -> Self`), the compiler emits calls to it,
and a `Result` return would have to change the TRAIT. So the merge unit 0
planned is refused by the brief's own boundary, and after the flip `try_copy` is
the only `try_` in std that still means "can fail to allocate".

Three ways out, none of them the implementing agent's to pick:
1. **Rename** — `Vector.duplicate() -> Result<Vector<T, A>, AllocError>` beside
   the infallible `copy()`. New public API, so a naming ruling.
2. **Delete** — the all-or-nothing reporting duplicate stops existing; a caller
   who needs one writes `reserve` + a `push` loop, which is what the body does.
   Loses a capability the flip is supposed to be adding, not removing.
3. **Keep the name** — the prefix keeps two meanings at exactly one site, with
   the exception written down. Cheapest, and contradicts §4.

HELD at 3 for now: unit 3 left `try_copy`'s NAME alone and flipped only its body
(its `try_reserve` call became `reserve`, its `push` calls propagate). Nothing
else in std spells the prefix for allocation. Conformance row A17 pins the
boundary that creates this — `Vector.copy()` still panics on refusal — so the
residue is visible from the ledger rather than only from here. [219, 234]

## DF-257c — CLOSED Aug 27 by design 246 unit B — a propagating `try` inside a
## GENERIC body is resolved ONCE and reused across monomorphizations (filed
## Aug 25 by design 234 unit 3; PRE-EXISTING)

CLOSED, and by the REPRESENTATION rather than by the annotation the mechanism
note below asks for. Design 246 unit B makes a payload-carrying enum an LLVM
IDENTIFIED struct, and identified types compare by NAME, so
`Result$Cell$Int$AllocError` and `Result$Cell$String$AllocError` are two types
where they used to be one literal `{i32, [N x i8]}`. The by-LLVM-type fallback
therefore lands on the right instantiation and the second monomorphization
extracts through its own Result. The pin
`examples/generic_body_try_survives_a_second_instantiation.saw` keeps its
explanation and lost its XFAIL marker in the same commit.

THE PER-INSTANTIATION ANNOTATION IS STILL OWED, and this closure does not
supply it — it removes the ambiguity the fallback was resolving, not the
fallback. If a later change re-introduces two same-named-and-shaped Result
instantiations, the pin is what catches it. The two design-234 spellings the
note below records (`Map.insert`'s direct return, `Map.keys`/`values`'s
`Vector()` + `reserve`) may revert whenever someone wants to; nothing forces it.

```saw
extension Cell<T> {
    static func make(seed: T) -> Result<Cell<T>, AllocError> { return Cell<T>(v: seed) }
}
extension Holder<U> {
    func build(&self, x: U) -> Result<Int, AllocError> {
        let c = try Cell<U>.make(seed: x)      // <- the one `try`
        return self.tag
    }
}
func main() {
    let h  = Holder<Int>(tag: 7)     print("{try! h.build(3)}")
    let h2 = Holder<String>(tag: 9)  let n2 = try! h2.build("s")  print("{n2}")
}
// internal compiler error at std/alloc.saw:20:9 (ReturnStatement):
//   Type of #1 arg mismatch: i8** != {i1, i8*}*
```

EITHER instantiation ALONE compiles and runs; the second is the whole delta.
No `init` is involved — the callee above is a static factory — so the shape has
been writable since Result generics landed and this predates DF-245a.

MECHANISM (obligation 4): `_generate_try_expr` prefers the typechecker's
`expr.result_enum_type` annotation and FALLS BACK to matching a registered
`Result$…` enum BY LLVM TYPE, a fallback whose own comment
(`sawc/codegen/results.py:38-58`) records that distinct instantiations share
layouts and that the match is therefore ambiguous. In a generic body the
annotation names the TEMPLATE's Result, so the second monomorphization reaches
the fallback and takes whichever same-layout instantiation was registered first
— the first one. The extraction then reads a payload of the wrong type, which
surfaces as an IR-verifier failure when the two payloads differ enough and would
be a silent miscompile when they do not. The fix owes the PER-INSTANTIATION
annotation (substituted at monomorphization like every other `SawType` on the
node), not a cleverer fallback; the fallback should arguably become a refusal
once nothing needs it.

TWO FACES, both found by design 234's flip and both this mechanism: the probe
above, and `Map.insert`'s `return try self.insert(...)` recursion, which reached
for `Result<Arc<DataBuf>, AllocError>` (`Can only insert {i1, i64} at [0] in
{{i1, i64}}: got %"Arc$1$DataBuf$m$std_data"`) in any program that used a `Map`
and a `Data` at once — a same-layout sibling the flip had just created.

WHAT DESIGN 234 DID ABOUT IT. Nothing structural: the flip multiplies this shape
(a generic container body propagating a now-fallible allocation), but every site
it needed has an equivalent spelling that resolves at the call — `Map.insert`
returns the recursive call directly instead of peeling and re-wrapping it, and
`Map.keys`/`values` spell `Vector<K, A>()` + `match … reserve` instead of
`try Vector<K, A>(capacity:)`. Both carry the citation at the line, so the
spelling is not mistaken for taste and both revert when this closes. Pin:
`examples/generic_body_try_survives_a_second_instantiation.saw` (XFAIL). [234, 92]

## DF-257d — the `$0` SHORTHAND is invisible to the implicit-parameter scan
## inside a `try` operand (filed Aug 25 by design 234 unit 3; PRE-EXISTING)

```saw
func fallible(n: Int) -> Result<Int, AllocError> { return n * 2 }
func run(body: (Int) -> Void) { body(21) }

run({ print("plain {$0}") })                      // fine
run({ print("forced {try! fallible($0)}") })      // undefined variable `$0`
// error: argument `body` expects `(Int) -> Void` but got `() -> Void`
```

MECHANISM (obligation 4): the walk that counts a closure's shorthand parameters
— what turns `{ $0 * 2 }` into a one-argument closure — does not descend into a
`TryExpr`'s operand, so a `$0` under `try`/`try!`/`try?` is neither counted nor
bound. The closure is then built with NO parameters and refused at the argument
position, with a second error at the `$0` itself. The control in the pin is the
same `$0` with no `try` around it, so the `try` is the whole delta. The other
expression forms that WRAP an operand are the siblings a fix should sweep
(`move`, a cast, `?.`) — each is a node the same walk has to enter.

WHY DESIGN 234 MET IT: `try!` is the corpus's migration spelling and `$0`
closures are everywhere, so `v.each { [&var out] in out.push($0 * 2) }` becomes
`v.each { [&var out] in try! out.push($0 * 2) }` and the shorthand disappears.
Two corpus sites take the named-parameter spelling meanwhile
(`{ [&var out] n in try! out.push(n * 2) }`), each citing this entry. Pin:
`examples/closure_shorthand_parameter_inside_a_try.saw` (XFAIL). [234, 19]

## DF-259a — `Box<any Trait>.make` is outside design 234's flip, so ONE method
## name has two fallibilities (filed Aug 25 by the design-138 doc-sync sweep;
## the 234 census HELD this site for a ruling that never reached the tracker)

```saw
func typed()  -> Result<Box<Circle>, AllocError> { Box<Circle>.make(Circle(r: 2)) }
func erased() -> Box<any Shape>                  { Box<any Shape>.make(Circle(r: 2)) }
```

Both compile. The typed factory reports its refusal, as design 234 §1 says every
allocating std operation does; the erased one hands back the box and panics on
refusal with a bare `allocation failed` — no method name, no size, no align, so
it is the one allocation panic in the tree that says less than design 122's
format rule asks and less than the `AllocError` it replaced carried.

MECHANISM (obligation 4): the erased construction is COMPILER-SYNTHESIZED, not
resolved. `_check_erased_box_make` (`sawc/typechecker/expressions.py:8990`)
BUILDS the result type by hand — `SawType(STRUCT, "Box", [existential, alloc])` —
instead of reading `Box.make`'s declared signature, and codegen's counterpart
(`sawc/codegen/existentials.py:401`) emits the failure arm as a panic whose
comment still says "(`Box<T>.make` parity)" — the parity that moved out from
under it on Aug 25. A signature-level flip is invisible to any construction the
typechecker types for itself.

THE SIBLINGS that mechanism reaches, probed: a collection literal (design 234
unit 3.1 taught it to consume the `Result`, and its panic NAMES itself —
`collection literal: allocation of N bytes (align M) failed`); the erased-error
auto-wrap into `Box<any Error>` (a documented boundary, LANGUAGE_SPEC "Where a
refusal still panics"); the coroutine frame, the spawned task's control block
and an escaping closure's environment (the same documented list,
`--no-hidden-alloc` being the opt-out). Four of the five are written down. This
is the fifth and is not, which is why a reader of that list believes
`Box<any Shape>.make` reports.

RESIDUE beside it: the path still refuses `Box<any Trait>.try_make` by name
("use `Box<any Trait>.make(...)` — the fallible erased factory is deferred"),
naming a method design 234 retired, in a message whose premise is now backwards.

NOT A DOC EDIT. Design 234's census row for `existentials.py:402` reads "its
stated rationale is `Box<T>.make` parity; that parity moves under unit 3, so
this site needs a ruling the brief does not give — HELD for the user". The hold
was never lifted and never became a tracker entry when the 234 entry moved to
the done file, so this entry is the hold, restated where it can be found. The
docs were left describing HEAD (no `try!` on the erased spelling). No XFAIL pin
either — the ruling decides whether today's behaviour is the bug. [234, 51]

## DF-259b — a RESERVED WORD in any declaration-name position gives a bare
## "Expected X name" that never says the word is reserved (filed Aug 25 by the
## design-138 doc-sync sweep; PRE-EXISTING)

```saw
enum Chosen { case Picked(n: Int), case None }   // Parse error: Expected variant name
struct None { n: Int }                            // Parse error: Expected struct name
func None() -> Int { 1 }                          // Parse error: Expected function name
struct Box2 { None: Int }                         // Parse error: Expected field name
enum G { case true, case Other }                  // Parse error: Expected variant name
```

Each refusal is correct and each is unreadable: nothing in it says `None` (or
`true`) is a keyword rather than a misspelling, and none offers the one-word
fix. An author writing an optional-shaped enum meets the first line and has
nothing to go on.

MECHANISM (obligation 4): every declaration-name slot asks the parser for an
IDENT token and reports `Expected <thing> name` when it does not get one. A
reserved word lexes as its own token, so it fails that test exactly as a `{` or
a number would, and the message is the same for all three. This is a CLASS, not
a `None` problem — the five lines above are five different slots reached by one
rule, and the fix belongs at the shared "expected an identifier here" report,
which can see the token it actually got and say "`None` is a keyword".

WHAT IS NOT AFFECTED, probed: `Some`, `Ok`, `Err`, `Any`, `True`, `Falsey`,
`Self2` and `Move2` are ordinary identifiers and compile in every one of those
slots, so the reserved set really is small and the diagnostic is the whole
finding. No XFAIL pin: the refusal is the intended behaviour and only its
wording is wrong, so there is no XPASS flip for a pin to validate.

FOUND BY: `LANGUAGE_SPEC.md`'s qualified-import example declared
`case None` and had never compiled; fixed in the same sweep (the variant is
`Nothing` now). [138]

## DF-259c — a TRAILING closure is not recognized inside a `try` operand, so
## `try! v.map { … }` is a field access (filed Aug 25 by the design-138
## doc-sync sweep; PRE-EXISTING). Pinned XFAIL

```saw
let a = jobs.map { j in j.label() }                 // fine
let b = try! jobs.map<String>({ j in j.label() })   // fine — parenthesized
let c = try! jobs.map { j in j.label() }
// error: struct `Vector` has no field `map`     hint: available fields: buffer, length, capacity
// error: closure literal is never called: `{ ... }` in statement position …
```

MECHANISM (obligation 4): `parse_try_expression`
(`sawc/parser/expressions.py:1352`) saves `allow_trailing_closure`, sets it to
False, and parses the WHOLE operand under it — the comment says "so `{` doesn't
get consumed as a trailing closure", protecting the inline
`try <expr> catch { … }` form. The suppression is correct in principle and too
wide in extent: a `{` that opens a catch block is always preceded by the `catch`
KEYWORD, so the two forms are distinguishable by one token of lookahead and
nothing about a trailing closure is actually ambiguous with a catch. What the
flag costs is every trailing closure anywhere in the operand.

THE MATRIX, probed (`examples/trailing_closure_inside_a_try_operand.saw`): all
three variants fail — `try!`, `try?` and the propagating `try` — and the
parenthesized argument is the control that compiles in each. `try!` DOES take an
inline `catch` at HEAD (probed), so the suppression is not `try`-only and cannot
be narrowed by variant; it has to be narrowed by POSITION.

THE SIBLINGS that mechanism reaches, probed and CORRECT: `if`/`while`/`for`
conditions and ranges, `guard`, a `match` scrutinee, an `if let`/`guard let`
subject, and a `match` arm's guard all clear the same flag, and in every one of
those the following `{` really is the construct's own block, with no keyword
between. The `try` operand is the only site where a keyword separates the two
readings, which is why it is the only one that is wrong.

FOUND BY: `LANGUAGE_SPEC.md`'s Vector-closure-methods block, whose `map` line
needed a `try!` after design 234 and could then no longer be written with the
trailing closure the block exists to show. The doc uses the parenthesized
spelling and says why, citing this entry. [234, 216, 129]

## DF-243a — a const EXPRESSION does not adopt the other operand's width in a
## mixed COMPARISON, where a bare literal does (filed Aug 21, the sos riders
## remainder; found respelling the abi rights asserts)
## — CLOSED Aug 22 (branch `diag-batch`, commit 4)

`static_assert((SystemRight.Debug as UInt32) >= 256, …)` compiles — a bare
literal adopts the other operand's type in a mixed binop (design 195). Respell
the same bit as the ruled shift and it is refused:

```saw
static_assert((SystemRight.Debug as UInt32) >= (1 << 8), …)
// error: operator `>=` requires both operands to have the same type, but the
//        left is `UInt32` and the right is `Int`
```

WHAT THE MECHANISM IS. DF-235a/b made a CONST EXPRESSION adopt a slot's width
wherever a bare literal does — annotation, field, argument, return, arm, the
assignment targets, a raw-backed case value (DF-232c). A mixed-binop OPERAND is
a position where a bare literal adopts and that ladder did NOT reach, so the
two literal forms disagree at exactly one place. Probed (`.build/scratch/
probe_const_operand.saw`): bare `== 1` and `>= 256` compile; `== (1u32 << 0)`
and `>= ((1 as UInt32) << 8)` compile; only the unsuffixed const expression is
refused. So the suffix is the documented out (the skill's "a SUBEXPRESSION no
expected type reaches" rule) and nothing is blocked — what is wrong is that one
file now spells one bit two ways, `case Debug = 1 << 8` in the slot and
`(1u32 << 8)` in the assert that checks it, for no reason a reader can see.
CONSEQUENCE FOR THE Aug-17 BIT-FLAG RULING: it reads as "spell a bit as a
shift", and today that costs a width suffix in every operand position. Worth
deciding whether the adoption ladder should cover the mixed binop, which would
retire the suffix here. [235, 232c, 195, 185]

LANDED Aug 22 — the ladder covers the mixed binop, so the suffix is retired.
TWO EDITS AT THE FUNNEL, both in `_check_operand_agreement`'s neighbourhood:
its CARVE-OUT (rule 1's "only a bare literal promotes") now asks
`_adopting_const_operand` instead of `_bare_int_literal`, and
`_adopt_bare_literal_operand` asks the same question so the operand actually
takes the peer's width. `_adopting_const_operand` is `_adopting_int_source` with
two deliberate differences, both because it decides ADOPTION rather than
overload ambiguity: it supplies the names a constant may read first
(`_stamp_const_names`, DF-240a's walk — that is what makes `flag >= (1 << SHIFT)`
work), and it EXCLUDES an expression naming a const generic parameter, exactly
as `_fold_const_expression_into` does, since an abstract body has no value to
fold. Adoption itself goes through the DF-235a/b fold, so the value is
materialized AT the peer's width and range-checked there; a PLATFORM peer needs
no fold (the expression already IS platform `Int`), and a CONST position takes
none either (design 185's signed platform-`Int` domain is the fold's, so pinning
a width there would check against a width the fold does not use — the carve-out
alone is what that position needed).
MATRIX (probed, `.build/scratch/df243a_*.saw`) — the mechanism reaches every
entry point of the agreement funnel that takes two numeric PEERS, which is four
more positions than the filing named: the const-position comparison (the filed
repro), a runtime comparison, arithmetic `+`, the bitwise `&`, and a constant
naming a module `static`. Compound assignment was already covered by DF-235a/b
(its RHS is pre-stamped by the adoption ladder) and is pinned here anyway to
keep the entry points in one file. A `for`-range's bounds cannot be exercised —
a range start must be `Int`, which is a separate pre-existing restriction. The
SHIFT COUNT stays exempt (design 195 matrix row 6). FENCES: a folded value the
peer cannot hold is the same "does not fit" error a bare literal gives, and a
RUNTIME operand of a different width is still refused.
PINS: `examples/const_expression_adopts_an_operand_width.saw` and
`examples/errors/const_operand_does_not_fit_error.saw`.
SOS RIDER: `sos/kernel/abi/src/lib.saw`'s 40 `(1u32 << n)` assert operands are
now `(1 << n)`, so one bit is spelled one way — as a shift, in the case value
and in the assert that checks it — and the comment that explained the suffix now
records that it is gone. PROVED VALUE-IDENTICAL: the same consuming program
compiled against the committed (suffixed) and working (un-suffixed) module trees
emits byte-identical IR (`.build/scratch/probe_sosabi_identity.py` — IDENTICAL).
Spec's operand-agreement section and the skill's const-expression bullet both
carry the rule.

## DF-243b — an error inside a `--module-path` DEPENDENCY is reported under the
## ENTRY file's path, carrying the DEPENDENCY's line numbers (filed Aug 21,
## same session; the DF-243a failure is the repro)
## — CLOSED Aug 22 (branch `diag-batch`, commit 5)

Every one of the 39 errors above printed
`--> .build/scratch/abi_values.saw:230:48` … `:500:45` for an entry file that
is 202 LINES LONG. The line numbers are `sos/kernel/abi/src/lib.saw`'s — the
dependency's — and the path is the entry's, so a reader following the
diagnostic opens the wrong file at a line that does not exist. Nothing in the
message names the module the error is really in.

Same family as the DF-232g residue (a dependency location reported with NO file
at all), and worse in one way: a missing file is visibly missing, while a wrong
one looks authoritative. Repro is cheap and stands on its own — any type error
in a `--module-path` module, reached from an entry file shorter than the
dependency. [232g, 140]

LANDED Aug 22, WITH the DF-232g residue — one family, one commit, two layers.
MECHANISM: the reporter's file came from `_get_current_source_file`, which reads
the current FUNCTION or METHOD, and a module-level declaration is inside
neither — so it answered None and the reporter fell back to the entry. The
typechecker now carries `current_module_source` (set and restored beside
`current_module_path` in `check_module`, at both restore points), and
`_diagnostic_source_file` is the reporting fallback: the declaration first, the
module second. It is deliberately a SECOND method rather than a widening of
`_get_current_source_file`, because that one also answers the member-VISIBILITY
gate (`_accessor_vis_module`), where the module path is already right at module
level and a std file's source would re-key the accessor — reporting and access
control ask the same-sounding question for different reasons.
MATRIX (probed, `.build/scratch/df243b_entry.saw` + `m243b/dep/`): a
module-level `static_assert` in a dependency (the finding) now names the
dependency; a FUNCTION-BODY error in the same dependency was already right and
is unchanged; the single-file entry path is unchanged (the entry IS the module).
PIN: `examples/dependency_error_names_its_own_file_error.saw` over
`examples/modules/depdiag/`, whose padding puts the refusal at a line the
six-line entry cannot have — with an `EXPECT-ERROR-ABSENT` on the entry's own
path at that line, so a regression to the old fallback fails the test rather
than merely looking odd.

## DF-242b — a cross-module OVERLOAD SET is bound BARE as ONE overload (filed
## Aug 21, probing DF-238a's fix)
## **CLOSED Aug 27 — designs/249-module-keyed-functions.md unit 1**

A module declaring three `public func pick` overloads (`Int`, `String`,
`UInt8`) is reached two ways from one file, and the two ways see different
sets. Through the QUALIFIER, `m.pick(...)` resolves against all three —
`m.pick("s")` compiles. Bare, under EITHER `import m.*` or
`import m.{pick}`, only the FIRST-registered overload is in scope, so
`pick("s")` is ``argument `n` expects `Int` but got `String` `` — a diagnostic
about a candidate the author did not mean, with the one they did mean
unmentioned. Evidence: `.build/scratch/p238b.saw` (qualified),
`p238b_bare.saw` (glob) and `p238b_sel.saw` (selective), one module
(`.build/scratch/mods238b/`), all three compiled.

MECHANISM (obligation 4, named not swept): import binding registers ONE symbol
per name, and `StructSymbol`/module namespaces keep the overload list beside
the representative (`method_overloads`, and its free-function twin) — the
qualified path reads the list because it resolves through the module's
namespace, and the bare binding copies the representative alone. So the sibling
positions to probe are every bare-binding form for every overloadable kind: a
free function (found), a static method, an `init`, and a re-export
(`public import m.{pick}`). NOT probed further here — this is DF-238a's
neighbour rather than its mechanism, and it wants its own dispatch.

**LANDED Aug 27, design 249 unit 1.** The mechanism named above was right and
the fix is at the binding site: each import arm — glob, selective, and the
parent-module inherit — now binds every member of the set the name stands for,
judged by that member's own visibility, through `register_bare_function`
(idempotent by declaration, so an aliasing copy binds once). Regression tests
`examples/d249_glob_import_binds_whole_overload_set.saw` and
`d249_selective_import_binds_whole_overload_set.saw`; the `pick("s")` call the
finding reported now resolves under both forms and the qualified spelling is
unchanged. The sibling positions the entry lists (static method, `init`,
re-export) were NOT swept here — the free-function face was the one this brief
owned; a re-export travels through the same two arms, and the two member kinds
keep their own `method_overloads` binding.

## DF-242c — a SUFFIXED literal does not disambiguate an `Int`-vs-narrow
## overload set (filed Aug 21, probing DF-238a's fix)

`pick(200u8)` against `pick(n: Int)` + `pick(b: UInt8)` is ``ambiguous call to
`pick`: multiple overloads match the argument types (UInt8)``, naming both. A
suffixed literal is EXACT-TYPED (design 47), so `UInt8` should win outright;
design 137's documented ambiguity is for a BARE literal, whose width is
deliberately still flexible (`h(5)` between `h(Int)` and `h(Int8)`), and the
workaround it names is the suffix — which does not work. SAME-MODULE and
cross-module alike (`.build/scratch/p238c.saw` is the same-module control), so
this is the overload matcher's own question and not an import or qualifier one:
the candidate filter is admitting `Int` for a `UInt8` argument somewhere it
should not. One line, no pin — the shape is a two-overload file.

RE-PROBED Aug 27 against design 249 and it SURVIVES, verbatim, as this entry
predicted. Post-fix behaviour on record: `pick(200u8)` against `pick(n: Int)` +
`pick(b: UInt8)` is still ``ambiguous call to `pick`: multiple overloads match
the argument types (UInt8)`` with both named, same-module and cross-module
alike. Module identity moved WHICH candidates a call sees; it does not touch
how the matcher scores the ones it sees, and the cross-module cell now reaches
the same tie by a shorter road (a bare `pick(3)` across two modules ties for
exactly this reason). Probes: `.build/scratch/p249_242c.saw` (same-module
control) and `p249_242b_glob.saw` before its `let n: Int` was added to route
around this finding.

## DF-242d — conformance row K90's GO gate is a BOUNDED spin, so suite load
## re-opens the output race the gate exists to close (filed Aug 26, seen once
## in the design-215 integration gate)

`K90_thread_detach_is_a_fate.saw` holds its two detached threads behind a
`GO` Atomic so "ticket released" cannot print before the `detached`/`chained`
markers — the file's own comment says that order "is not a property of the
language and must not be pinned as one", and the ordered CONTAINS directives
DO pin it, on the strength of the gate. But the gate spin is bounded
(`SPIN_LIMIT` = 200M iterations, ~0.2s) so a thread that outlives it while a
40-worker suite has main descheduled constructs and releases its ticket with
the gate still shut: "'ticket released' — out of order (it appears earlier)".
Observed once under the full suite, Aug 26; passes twice consecutively in
isolation. The bound exists so a gate that never opens ends the thread
instead of pinning a core — the fix must keep that property while making
early release impossible (print both markers before either spawn, or skip
ticket construction when the gate never opened — the latter converts the
flake into the missing-line failure the bound intends). A conformance row's
oracle is a ruling surface, so the choice parks here rather than landing on
discovery.

## DF-238b — `print`'s `{}` format argument renders a wider-than-word integer
## as its LOW WORD on a 32-bit target (filed Aug 21, design 238 unit 1)
## — CLOSED Aug 22 (branch `diag-batch`, commit 2)

`print("{}", v)` at `v: Int64 = 0x1234_0000_5678` writes `22136` — 0x5678 — on
`riscv32-unknown-none-elf`, and `20014547621496` on
`aarch64-unknown-none-elf`. `UInt64` renders the same way. A value NARROWER
than the platform word (`Int32`, a small `Int64`) is correct on both, so the
argument is being narrowed to the platform word on its way into the renderer
rather than being rendered wrong.

Minimal repro: ONE module, no imports, no cross-module call — so DF-238a is not
in play — four `print` lines and an exit. Reproduced on both targets from the
same source, which is what makes it a target property rather than a value one.

MECHANISM (obligation 4): the alloc-free `{}` path renders an integer through
the compiler's `__saw_print_int` / `__saw_print_uint` helpers, which take a
PLATFORM `Int`; a `T` wider than that word is truncated at the call. Same class
as DF-158c (an `@export`ed `Int64`-returning seam came out `i32` on a 32-bit
target): a fixed-width-versus-platform-word confusion that is invisible on a
64-bit host, where the two coincide. The sibling positions to sweep when this
is fixed are every other integer rendering — `"{x}"` interpolation,
`Int64.to_string()`, `StringBuilder.append`, a `panic`/`assert` format
argument. THE FIRST TWO ARE NOT REACHABLE from a freestanding build to confirm:
both pull `snprintf`/`strlen`/`strcat` into the link, which is a second finding
in waiting rather than evidence about this one, and it is why `--no-hidden-alloc`
exists. `panic`/`assert` share `print`'s lowering and are presumed to share the
defect.

PINNED as `tests/freestanding/cases/wide_value_rendering.saw`, marked xfail
against this DF and scoped `arches: ["riscv32"]` — the expectation states the
INTENDED rendering (the whole number), so the fix XPASSes it. It cannot be
pinned in `examples/`: `test_runner.py` builds for the 64-bit host, where the
platform word already is 64 bits and the defect does not exist. That is the
first thing the freestanding suite has caught that no other lane could. [238,
158, 137, 47]

LANDED Aug 22. The rendering width is now `max(platform word, value width)`
rather than the platform word: `_render_int_value` extends a narrower value as
it always did and stops TRUNCATING a wider one, and `_fmt_int_fn` is the new
one-line funnel that answers "which itoa renders this width" — up to the word,
the pair `_declare_print_runtime` always emits; above it, a second pair at the
value's own width, emitted LAZILY on first use. Lazy because the wide digit loop
lowers to `__udivdi3`/`__umoddi3` on a 32-bit target: a program that never
renders a wide value should not acquire that link dependency (both in-tree
freestanding floors already carry the two — `tests/freestanding/hal/support.c`
and `sos/rt/common_c/support.c`). `_emit_fmt_int_fn` grew a `value_width`
parameter, which forced the VALUE's width apart from the LENGTH's — the returned
length stays platform-width (design 47), and the two were one variable only
because they coincide on a 64-bit target.
FUNNEL + MATRIX (obligations 1 and 4): the mechanism is "an integer rendering
narrows to the platform word on its way into the formatter". Census of the
positions — `_render_int_value`'s three callers (`_render_argument`, i.e. every
`{}` argument on `print`/`panic`/`assert`; the CHECKED-CAST panic
`_emit_cast_range_check`, which had the same truncation and is fixed by the same
funnel; and `print`'s wide arm) plus `_generate_print`'s integer arm, which
called `__saw_print_int` at platform width and now routes through the funnel so
`print(v)` and `print("{}", v)` stay byte-identical. The two positions the entry
listed as UNCHECKABLE are checked and CLEAN: `"{x}"` interpolation and
`to_string()` both go through `_value_to_string`, which extends to i64 and never
narrowed. `StringBuilder.append` takes a platform `Int` in Saw, so a wide value
there needs a written conversion (design 205) rather than truncating silently.
PIN: `tests/freestanding/cases/wide_value_rendering.saw`, XFAIL removed and
grown from two rows to four — a positive `Int64`, the same bits as `UInt64`, a
NEGATIVE `Int64` (the wide itoa's sign path) and `UInt64.max` (above
`Int64.max`, so a signed formatter would print -1 — DF-119b at 64 bits). All
four pass on riscv32; arm64 is unaffected and untouched (`arches: ["riscv32"]`).
CONFORMANCE: no row owed — `examples/conformance/` covers safety guarantees, and
this is output correctness on a target the host suite cannot reach; the
freestanding suite IS its ledger.

## DF-238c — a conformance declared in the TRAIT's module for a foreign type is
## carried by the SELECTIVE import form and lost by the GLOB one (filed Aug 21,
## design 238 unit 1)
## — CLOSED Aug 22 (branch `diag-batch`, commit 3)

`extension Rec: Summary` declared in `Summary`'s module, `Rec` declared in
another — the orphan rule's second half, legal in exactly that one place. A
third module that reaches the trait with `import m.{Summary, outside}` can
instantiate a generic bound on it at `Rec`; the same file with `import m.*`
cannot, and reports ``type `Rec` does not implement trait `Summary` `` with a
hint to add the extension that is already there. Design 142's rule is that a
conformance declared under the orphan rule is coherent PROGRAM-WIDE and needs
no import at all, so neither form should be able to lose it — and a glob is
documented as every public name of the module, which the trait plainly is.

MECHANISM (obligation 4): the conformance IS registered — the same
instantiation made INSIDE the declaring module compiles and answers — so what
is missing is the publication across one import FORM, not the conformance. The
selective arm and the glob arm of import binding are two code paths, and only
one of them carries whatever the bound check consults. POSITION MATRIX, probed
hosted:

| the entry's import of the TRAIT's module | the bound at the foreign type |
|---|---|
| `import m.{Summary, outside}` selective | resolves |
| `import m.*` glob | **NOT FOUND** |
| `import m` qualified, `m.outside(&r)` | never reached — inference fails first, DF-238a's third face |
| conformance beside the TYPE, `import t.*` glob | resolves (control) |

The control is what says the glob machinery is not simply blind to
conformances: the orphan rule's OTHER half survives a glob, so the asymmetry is
between the two halves of the rule and not between the two import forms alone.
Pinned XFAIL: `examples/conformance_in_the_traits_module_is_program_wide.saw`
(+ `examples/modules/orphan238c_type/`, `examples/modules/orphan238c_trait/`),
which carries the control beside the finding. [238, 142, 150]

LANDED Aug 22. WHERE THE TWO ARMS DIVERGE, exactly: a glob binds no QUALIFIER
(design 150 pin 1), so `check_module`'s glob arm appends to `ns.glob_sources`
and never touches `ns.modules` — and `type_conforms_to` walked `ns.modules`
alone. The selective and whole-module forms both bind a qualifier, which is the
whole of why they carried the conformance; `_import_conformances` (the
struct/enum copy) never entered into it, because `Rec` is not one of the trait
module's own declarations to copy. FIX: `Namespace.coherence_search_namespaces`,
one generator over both lists, with the two queries as its declared entry
points. Name lookups (`_lookup_struct_deep` and its twins, the trait-parent
walk) are deliberately NOT routed through it — those are VISIBILITY questions,
where the glob's copy already answers and widening the search would reach a
globbed module's private declarations. That is the line the fix draws: a
conformance is program-wide, a NAME is not.
SWEEP (obligation 4) — the mechanism is "a query about a type reaches an
imported module through `ns.modules`, which a glob never populates". Census of
`self.modules.values()` walks: `type_conforms_to` (the finding),
`_lookup_thread_assertion` (A SECOND FACE, probed — a globbed
`extension Shared: UnsafeSync {}` is invisible, so `static SLOT: Shared` is
refused as non-Sync while the selective import of the same module compiles),
and the four NAME lookups, which are correct as they stand for the reason above.
MATRIX (probed, `.build/scratch/df238c_*.saw`): the glob form now resolves, and
so do a PARENT trait's conformance under the same bound, the generic declared
in the trait's module and instantiated from the entry, the selective form, the
QUALIFIED form (which the entry recorded as "never reached — inference fails
first"; DF-238a's Aug-21 fix cleared that, so it is a real row now), and the
control beside the TYPE.
PINS: `examples/conformance_in_the_traits_module_is_program_wide.saw`
un-XFAIL'd and grown to six rows over four fixture modules
(`orphan238c_type/`, `orphan238c_trait/` — which gained the parent trait —
plus the new `orphan238c_sel/` and `orphan238c_qual/`, one per import form,
because one file can spell only one form per module), and
`examples/thread_assertion_survives_a_glob_import.saw` over
`examples/modules/globassert/` for the second face.
CONFORMANCE: row B23 added — "a conformance declared under the orphan rule is
coherent program-wide, carried by every import form", covered by both files.
The skill's orphan-rule bullet carries the suspect-in-older-builds note; the
SPEC needed no change, since it already stated the rule the compiler now keeps.

## DF-232g — a LOCAL static DERIVED from an imported const stops being a
## compile-time constant, though the same expression folds INLINE (filed Aug 17,
## the kcore split)
## — CLOSED Aug 21, design 240 item 8 (branch `design-240`); the
## diagnostic-FILE residue at the end CLOSED Aug 22 (branch `diag-batch`)

`static N: Int = A + B` with `A`/`B` imported is refused wherever a compile-time
length is required — `repeat count is not a compile-time constant: the computed
static `N` is not allowed here` — while `[0; A + B]` spelled INLINE at the use
site folds fine. The same arithmetic is constant or not depending on whether it
was given a NAME.
MATRIX (probed, obligation 4). FOLDS: a literal; an imported const named directly
as a length (`[T; A]`); arithmetic over imported consts inline (`[T; A * B]`,
`[T; A + 1]`); a local static derived from LOCAL statics (`static S = L1 + L2`,
recursively); a const derived in its OWN module and imported whole. DOES NOT
FOLD, in every form probed: a local static that NAMES an imported const — the
pure alias `static S = A`, the mixed sum `L1 + A`, the all-imported sum
`A + B`.
MECHANISM: the length folder resolves a static's initializer recursively through
the CURRENT module's symbol table only, so an imported name ends the recursion
and the static is reported as "computed" — a word that is simply wrong for the
alias, which computes nothing. The inline path resolves the same names through
the ordinary import machinery, which is why it succeeds.
THE DIAGNOSTIC ALSO NAMES THE WRONG FILE: it is reported against the ENTRY
source with the DEFINING module's line/column, so it points at a line number the
named file does not have (probe: an error on `main.saw:23` in a 5-line
main.saw).
WHAT IT COST THE SPLIT: `MAX_ATTACHMENTS = MAX_EVENTS + MAX_INTERRUPTS +
MAX_TIMERS` cannot be declared apart from ANY of its three operands, so every
slab size stays in one module (`limits.saw`) — which is how lib.saw already had
them, one adjacent block, so the constraint cost the cut nothing this time. It
would cost a differently-shaped kernel a real seam. [232, design 148/185/186]

LANDED Aug 21 (design 240 item 8). `_fold_static_decl`'s leaf stamper gained
the import fallback: a name the local declaration table does not hold is
looked up as an IMPORT — `_const_static_lookup` for the bare spelling,
`_stamp_qualified_const` for `dep.A` — and the symbol carries the answer its
own module already computed, which is why a const derived in its defining
module and imported whole always folded. This is that same value, one hop
earlier. The pass runs after the import handling in `check_module`, so a
dependency's statics are symbols by then (modules are checked in dependency
order). MATRIX (probed, the entry's own fold list): the pure alias
`static S = A`, the mixed `L1 + A`, the all-imported `A + B`, both spellings
of each, `1 << dep.A`, and a `static_assert` over one — all fold; the
already-folding rows are unchanged; a static derived from an `unsafe static
var` is still refused NAMING it (its value is a fact about the running
program, not about the source).
PIN: `examples/static_derived_from_imported_const.saw` over the new fixture
`examples/modules/constdep.saw`; the refusal rows cite
`array_length_nonconst_error.saw` / `array_length_nonint_static_error.saw`
rather than duplicating them. Spec's static-initializer tier 2 and the
skill's size-in-one-place section both name the imported case now.

RESIDUE — CLOSED Aug 22 (branch `diag-batch`, commit 5), beside DF-243b, which
is the same question asked one layer up. `Expression` declares a `source_file`
annotation now (design 126's contract — a graft would have been invisible to
`dataclasses.fields()`), stamped by `_stamp_declared_type_sources`: one walk
beside the fold's, over the same `_walk_declared_types`, so the stamp cannot
drift from the fold's coverage. `codegen/types.py` already asked the expression
for a file and now gets one, so the dependency's `[UInt8; MUT]` reports
`--> <dep>/lib.saw:9:27` instead of `--> line 9:27`.
PIN: `examples/declared_length_error_names_its_file_error.saw` over
`examples/modules/lengthdep/`, with an `EXPECT-ERROR-ABSENT: --> line` that is
what pins the fileless shape as gone. — the entry's OTHER half, as filed:
Re-probed Aug 21: the TYPECHECKER path is correct now (a length that fails to
fold in a dependency's function body reports against that dependency's file
and line). What remains is the CODEGEN path, which owns the rule for a
DECLARED length that never folded — a struct FIELD's `[UInt8; MUT]` in a
dependency reports `--> line 14:46` with NO FILE at all, so the reader gets a
line number and nothing to open. `codegen/types.py` already passes
`source_file=getattr(expr, 'source_file', None)`; the expression simply never
has one, because `Expression` carries no such field (only
`SourceLocationLiteral` declares one, structurally). The fix is a declared
annotation stamped where the length-folding pass walks a module's types —
small, but a new field on the expression base, so it is recorded here rather
than folded into a batch item whose named fix was the resolution.

## DF-232f — a package has NO INTERNAL VISIBILITY, so splitting one file into
## several PUBLISHES everything they share (filed Aug 17, the kcore split's
## unit-0 probe; the finding the split's tracker entry anticipated)
## — FIX LANDED Aug 20 (branch df-232f); the re-narrowing rider is still OPEN

`public` is the only way one file of a package can reach another's decl, and
`public` means EVERY importer — there is no `public(package)`/`internal` tier
between "this file" and "the world". So a file split is also a publication: the
kcore split turned ~150 kernel-internal names (every slab, every slot struct AND
ITS FIELDS, every table helper) into surface any consumer of `kcore` can name and
write, and design 80's gate now protects nothing inside the package it was
protecting the kernel with. Nothing about the IMAGE changes — the widening is a
compile-time visibility fact — which is why the split proceeded, but the
encapsulation loss is real and is the argument for the tier: an `unsafe static
var THREADS` that the scheduler and the teardown share is exactly the thing that
should be reachable from a sibling file and from nowhere else.
WHAT THE TIER WOULD COST is small on today's model: package identity already
exists (a `--module-path` name / a Blade dependency), and design 144 already
makes TYPE identity `(defining module, name)` — so `internal` is a third answer
in the same visibility check, not a new concept.
RULED Aug 17 (user): **`--module-path` packages JOIN the design-80 package
relation, package root = the mapped directory** — files under one mapped dir
are one package (siblings see each other's `public(package)`); the entry
file and other consumers are OUTSIDE it. No new keyword: `public(package)`
is the spelling. Fix shape: package-root plumbing for --module-path modules
into the existing visibility check + tests both ways; then a mechanical
RE-NARROWING rider flips kcore's 199 publics to `public(package)` wherever
no consumer needs the name (target: back near the original 15). One check
owed by the fix: `imgformat` is consumed by Blade as a path dependency AND
by the kernel via --module-path — the two mechanisms must agree on package
identity for the same directory. [232, design 80/82/204]
LANDED Aug 20 — the fix half only. It was one more answer in the existing
check, as predicted: `_visibility_relation_allows` (typechecker/core.py) already
rooted std at `("<std>",)` off the DEFINING module, and a mapped package now
roots at `(name,)` the same way, so `name`/`name.sub`/`name.a.b` prefix-match
and the entry file (never a mapped name) does not. The mapped-name set rides in
on `TypeChecker(mapped_packages=…)` from `module_paths`. No keyword, no grammar,
no new concept — `Visibility.PACKAGE` and `public(package)` already existed.
ROOT CAUSE of the silence: `check_visibility` (namespace.py:2725-2732) had a
fail-OPEN arm, `if not package_root: return True`, and nothing ever gave these
modules a root — so the tier degraded to plain `public` for exactly the packages
that wanted it. Pins both ways: `examples/module_path_package_visibility.saw`
(sibling reaches `public(package)`, the over-refusal guard) and
`…_error.saw` (entry file refused; asserts the message SHAPE — tier + defining
module at the import, the fix, and what IS exported).
THE OWED CHECK, RESOLVED: Blade drives every resolved dependency as
`--module-path <name>=<checkout>/src` (blade/src/builder.saw:5, arg sites :379
and :531), so a Blade path dependency IS a mapped package — `imgformat` roots at
`("imgformat",)` by either route and the two mechanisms cannot disagree.
BLAST RADIUS measured before gating: ZERO `public(package)` sites in sos/, libs/,
blade/, selfhost/, devtools/ — only examples/ uses the tier today, which is why
enforcement could land without a migration. Gates: full suite 2018 passed /16
pre-existing cited xfails, sos_runner 80 passed across riscv32 + arm64.
THE RE-NARROWING RIDER LANDED Aug 20 (see its section below): kcore went 119
`public` -> 11, so design 80's gate protects the kernel's tables again. What
remains open there is sosabi (2), hal-arm64 (2), toml/semver (1 each), and the
~179 public MEMBERS no pass has audited.
NOTE for design 238 unit 2: imgformat moving to `libs/imgformat` does not
disturb this — package identity is the MAPPED NAME, not the directory path.

## RE-NARROWING RIDER — scoped Aug 20 by survey (queue item 7; the half of
## DF-232f that actually recovers the encapsulation)

Survey of every mapped package, asking which `public` decls no consumer outside
the package names. Result by package (top-level decls; public MEMBERS —
methods and struct fields — are a further ~179 not yet audited):

- **kcore** (sos/kernel/core) — 103 unique public names, ~15 genuinely reachable
  from outside: `ktrap`, `start_process`, `start_tick`, `load_root_and_enter`,
  `Console`, `timer_ticks`, `fatal_image`, `fatal`, `deliver_attachment`,
  `WaitableKind`, `Waitable`, `SystemObject`, `SyscallResult`, `HandleEntry`,
  `ExitCode`. THE PRIZE, and it independently lands on this entry's stated
  "back near the original 15" by a different method.
- **sosabi** — 2: `PROCESS_STATUS_KIND_SHIFT`, `PROCESS_STATUS_CODE_MASK`.
- **hal-arm64** — 2: `mair_value`, `page_tables_build`. hal-riscv32, sosrt and
  imgformat are already tight (0 candidates).
- **toml** — `TomlTable`; **semver** — `ReqKind`. Worth a look; Blade's deps.

THE TRAP, and why this rider is not "narrow everything unused": **"never named
outside" is NOT "should be narrowed."** sysapi (the `sos` module) shows 22
unused `sos_*` wrappers — and they must STAY `public`. That package's PURPOSE is
to export the kernel's userspace API (spec §5.7); those wrappers exist for
processes not yet written. A mechanical unused-sweep would delete the kernel's
public API. Same protection for imgformat, toml and semver as API packages.
kcore and the HALs are the opposite case — internal implementation, where an
unused `public` is the accidental widening DF-232f described.

METHOD RULED: drive it from the COMPILER, not from grep. The survey that
produced the numbers above had a regex artifact (`public unsafe static var X`
parsed as declaring a symbol named `var`, which then "matched" 1131 files) and
common-word collisions (`console`, `accumulate`, `align_up`) — any grep-based
pass will have the same class of error. The oracle procedure: flip EVERY kcore
`public` to `public(package)` in one mechanical pass, compile, and promote back
exactly the symbols the errors name — DF-232f's refusal names the tier, the
defining module and what IS exported, so each error is self-describing. No
guessing, and the survivor set is discovered rather than asserted. [232, 80]

KCORE LANDED Aug 20 — 119 public -> 11 (108 narrowed), the method exactly as
ruled. THE SURVIVOR SET WAS ALREADY WRITTEN DOWN: it is precisely `lib.saw`'s
`public import` block — align_up, Console, ExitCode, console, fatal,
fatal_image, start_tick, start_process, timer_ticks, ktrap,
load_root_and_enter. The facade had documented the intended API all along, and
the compiler independently rediscovered it. (My grep survey's "~15" was the
same set plus its own false positives; the oracle is what settled it — further
evidence for the ruled method.) Gate: `battery.sh suite sos` GREEN, both
stages, 578s; sos_runner 80 passed across riscv32 + arm64.

TWO PROPERTIES THE ORACLE TAUGHT — both about `public import`, both worth
keeping:
1. `public(package) import` is REFUSED (design 229: "`public import` is the
   only re-export form — a scoped visibility is not supported on an import").
   kcore's 7 re-exports stay `public import`. Whether the scoped form SHOULD
   exist is a live question — see [BACKLOG].
2. ~~`public import` does NOT widen a `public(package)` symbol.~~ **WRONG —
   CORRECTED Aug 20, see DF-232j (FIXED same day; entry in
   done_aug18-aug25.md).** Writing the pin the claim asked for
   DISPROVED it: a `public import` re-export DOES widen, and the probe compiles
   and prints 7. The claim was inferred from the kcore flip erroring on 6 names
   rather than passing silently; the better explanation is that those 6 are
   reached DIRECTLY by consumers (the HALs import `kcore.mem` and friends), not
   through the facade — which also explains why only 6 of the facade's 11
   errored. The other 5 were most likely leaking through the re-export and were
   masked when the promote-back made them genuinely `public`. Lesson worth
   keeping: "the gate went red in a way consistent with my theory" is not
   evidence FOR the theory when a second mechanism produces the same redness.

REMAINING — AUDITED Aug 20 (sweep agent, compile evidence; full report +
the exact 84-site list: designs/renarrow-audit-aug20.md). Verdict: of the
86 candidates, 84 NARROWABLE and 2 CONSUMED (`Console.write_str` — 25
outside sites — and `.write_hex` — 4; both are the console API the facade
implies, keep `public`). The "~179" reconciled EXACTLY: it was the
all-packages member sum; kcore's own share is 80 (78 narrowable). 78 of
the 84 are file-local (`private` would do); the package-tier six are
listed in the report. sysapi/imgformat/toml-rest/semver-rest stay wide BY
DESIGN and were counted, not audited. The narrowing unit is now
DISPATCH-READY: apply the report's site list, iterate to a clean build
(the report warns one batch pass under-counts refusals), gate sos + blade
lanes. Oracle-dense mechanical work — a mech-agent candidate if the user
approves; Opus otherwise. The audit also filed DF-232n/o/p and one ruling
question (entries below).

LANDED Aug 20 (mech agent, branch `renarrow-232f`, commit `0cac7deb`): all 84
sites narrowed — 78 `public(package)`, 6 private, the 2 CONSUMED left `public`,
zero reverts, zero OPEN. THE AUDIT'S SPLIT WAS INVERTED and is corrected here:
it called 78 file-local and six package-tier; the compiler says 78 need the
package tier and only six are file-local (`Console.write_byte`,
`PROCESS_STATUS_KIND_SHIFT`, `PROCESS_STATUS_CODE_MASK`, `mair_value`,
`page_tables_build`, `ReqKind`). The 72 extra widenings surfaced in THREE
waves, each masked by the previous one: `process.saw` (33), `irq.saw` (2), then
`dispatch.saw` and siblings (37) — all kcore sibling files, so `public(package)`
(design 80's siblings-only tier) is the right answer for each; reshaping
who-constructs-what is kernel architecture for a future brief, not this unit.
Filed as DF-232q below. Six doc comments justifying a field with "`public`
because …" now say `public(package)`. Gates: sos_runner 80/80 across
riscv32 + arm64 before the commit; terminal `battery.sh suite bootstrap sos`
green. The lead corrects designs/renarrow-audit-aug20.md at integration.

## SOS M3 — scoping session RATIFIED (designs/232), unit 1 BUILT

M2 integrated + verified on main Aug 16. designs/232-sos-m3-sketch.md
is the plan of record: option A (the multiprocess kernel), the unit
ladder 0-7 with 1.5 and 5.5 in place. The Aug-16 seed rounds in
designs/178 are RULINGS the session does not reopen.
Unit 0 (the M2 spec recap) and **unit 1 (the Clock and Timer objects)**
are BUILT — and INTEGRATED (staleness corrected Aug 28: the "PARKED"
status here outlived the review; no such branches exist, the Clock/Timer
objects and their 40-case harnesses are in the tree the split carried to
sawos, and the Aug-21 riders landed against them). M3 units 1.5+ run in
the sawos repo (design 238's Aug-28 reorder).
Unit 1 in one line: **a process can sleep** — eight object kinds where
M2 had six, the per-arch timer seam reshaped from periodic to ABSOLUTE
so the tick and Timer deadlines share one comparator with §7 inviolate,
the copy-IN funnel built as copy-out's mirror twin (M4 IPC inherits
it), and the idle/deadlock rule generalized so an armed Timer counts
like a bound IRQ line. 40 harness cases per architecture. The
as-built decisions — op/right numbering, the record layouts, and the
disarm/re-arm semantics the brief delegated — are recorded in 232's
"UNIT 1 AS BUILT" section, together with the review riders: the
Aug-17 rulings that an EVENT'S WORD IS CONSUMED ON DELIVERY (two
doors onto one value, `receive` unchanged as the poll), that a
Timer's verbs are METHODS ON ITS SLOT (the `unsafe` effect retreating
to the slab indexing), and that the hardware CLOCK IS A GLOBAL
SINGLETON per `ClockType`, kernel-eternal and freed by no teardown.
Two findings filed rather than worked around: DF-232a and DF-232b,
above.
NEXT: unit 1.5 (kernel interruptibility, pin 1's ruling) before
CreateProcess, so the image-copy loop is born with its preemption
points. [178, 232]

M2 integrated + verified on main Aug 16. designs/232-sos-m3-sketch.md
is the session's agenda: option A (the multiprocess kernel — Clock/
Timer, CreateProcess, give/boot_handles, the ruled Memory/IoMemory
surface, hard quotas; money shot = the echo driver as a CHILD launched
from config) recommended over IPC-first; twelve agenda items, five
lifted from 178's seed flags. The Aug-16 seed rounds in designs/178
are RULINGS the session does not reopen. Unit 0 (the deferred M2
spec-recap) is BUILT, branch PARKED for user review per SOS policy:
§11 is now the built/remaining ledger plus an M2 milestone entry, and
the pre-M2 status text is flipped in §§2, 2.2, 3, 5.7, 5c, 7, 8, 9b
and 12 — each verified against the code first. [178, 232]

## KCORE SPLIT — BUILT Aug 17, branch PARKED for user review (SOS policy).
## sos/kernel/core/lib.saw into seam files (user-approved Aug 17)

AS BUILT: 3946 lines in one file became 4394 across FIFTEEN — thirteen
seam modules, the `lib.saw` facade, and no change to any kernel code.
The +448 is thirteen module docstrings, the per-file imports and
`public`; a code-line multiset check against the pre-split file (1852
lines, run at every commit) is what proves the rest is a text move.
FILES, in dependency order — a file may import only those above it,
because DF-232e makes a cycle silent — with line counts:
`limits` 121, `mem` 44, `diag` 150, `result` 68, `objects` 235,
`threads` 225, `time` 404, `waitables` 489, `process` 564, `wake` 132,
`irq` 341, `sched` 123, `dispatch` 1137, `loader` 293, `lib` 68.
THREE SEAMS OF THE SKETCH CAME IN TWO, and the rule is the same each
time: the STATE of a thing sits below the process teardown that frees
it, and ACTING on it sits above — the teardown touches every slab, and
answering a wait goes through the copy door that can end a process. So
`threads` (table, frame arena, ready queue) is not `sched` (the switch
point), `time` (the slabs, the comparator funnel) is not `irq` (tick,
expiry, device lines, idle), and `waitables` (the tables and the whole
per-kind matrix) is not `wake` (the delivery funnels). `limits` is the
fourteenth file DF-232g forced: a derived size cannot be declared apart
from its operands, which is how lib.saw already had them.
WHAT WIDENED (DF-232f, the cost): every name two seams share, plus most
fields of every slot struct — the slabs are read and written by the
seams that own the operations. Each was named by a compiler error and
applied by a loop that stops when the compiler does; nothing was widened
on suspicion. Still private: `THREAD_FRAMES`, `handle_index`,
`fires_word`, `stays_running`, `SyscallResult`'s status/value, and
`ClockSlot`'s neighbours in each file.
Gates: `battery.sh sos` GREEN (80 tests, riscv32 + arm64) at EVERY one
of the four code commits, plus the terminal `suite sos`.
[232, design 82/150/204]

ORIGINAL SCOPE, for the record: ~4000 lines splits along the FUNNEL seams, not just topics — the M2
finale engineered "one table, per-kind matches in ONE place"
(waitable_slot) and one dispatch door, and the cut must keep each
funnel whole: time.saw (Clock + Timer), waitables.saw (Event, Waiter,
attachments, ALL the per-kind matches together), process.saw (process
+ thread lifecycle, teardown), sched.saw (run queue, tick),
dispatch.saw (handle table, object-op dispatch, syscall entry),
loader.saw (sosimg), diag.saw (console, fault reporting, selftest).
UNIT 0 (the language probe) IS DONE and the split IS EXPRESSIBLE with
no compiler change: a `public unsafe static var` is readable AND
writable from a sibling file of the same mapped package, as ONE
instance, through a bare import (`import kcore.threads.{THREADS}`);
imported consts fold in `[T; N]` and `static_assert`; and
`public import` re-export makes `lib.saw` a FACADE, so main.saw and
every `sos/tests/` entry keep their `import kcore.{console, …}` lines
unchanged — extensions travel with a re-exported type and an
`@export`'d symbol in a facade-reached module still lands in the
image. THREE FINDINGS came out of it, none blocking: DF-232d
(assignment through a module qualifier), DF-232e (import cycles are
undiagnosed), DF-232f (no package-internal visibility — the split
publishes what the files share, which is the cost the entry below
predicted).
THE CUT IS LAYERED, and that is forced rather than chosen: DF-232e
means the seams must form a DAG, and the kernel's own call graph
(teardown touches every slab; `fault_process` is reached from the copy
door; `pick_next` reaches the idle poll which reaches the wake path)
puts the STATE of a seam below the process teardown and the SERVICE of
it above — so three of the sketch's seams split in two.
Thirteen files + the facade, in dependency order: `mem` (addresses and
byte moves), `diag` (console + the fatal reports), `result` (the
syscall answer + `write_result`), `objects` (handle table + the typed
object wrappers), `threads` (thread table, frame arena, ready queue),
`time` (Clock/Timer slabs + the comparator funnel), `waitables`
(Event/Waiter/attachments + ALL the per-kind matrix), `process`
(teardown, faults, the copy doors, `start_process`), `wake` (delivery:
`deliver_attachment`/`wake_one_waiter`/`notify_ready`), `irq` (the
tick, timer expiry, device lines, the idle path), `sched` (the switch
point + `exit_thread`), `dispatch` (every object-op + `ktrap`),
`loader` (sosimg). Behavior-neutral; sos-only gates.
[232, design 82/150/204]

## HARDWARE PATH — the ultimate goal: ESP32-P4 + a small TCP/IP stack
## in Saw (user-ruled direction, Aug 16; post-M3 track)

The destination: SOS on real silicon — the ESP32-P4 (dual-core rv32,
PMP for the protected build, the "minimal MMU" 178's memory notes
already name as the HAL bonus behind the same seam) — running a Saw
TCP/IP stack. The P4 is RADIO-LESS, which dissolves the FreeRTOS
binary-blob entanglement: connectivity is a companion chip (C6 over
SDIO/SPI, ESP-Hosted — an OPEN protocol reimplementable in Saw), so
the radio becomes exactly what SOS's model wants — a window + IRQ + a
driver process, and on protected SOS a WiFi driver crash kills the
driver, not the system. The ladder as discussed:

1. NET STACK PHASE 1 (post-M3; consumes Timer + device grant + the
   driver pattern): wire vocabulary, ARP/IPv4/ICMP + a VIRTIO-NET
   driver on QEMU virt — no hardware needed, doubles as M3's second
   real driver, ping is the hello-world. ~2-3 dispatches.
2. UDP + DHCP + DNS stub (~1-2 dispatches), then TCP — the hard 60%
   (state machine, RTO, flow control; the test harness matters more
   than the code: packet-level goldens + a QEMU harness conversing
   with a real Linux peer as the differential oracle). ~3-5
   dispatches. API mirrors std.net's TcpListener/TcpStream so hosted
   code ports unchanged. Whole stack ~8-15k lines Saw (smoltcp/uIP
   are the calibration points).
3. FIRST SILICON: ESP32-C6 — cheapest bring-up (rv32 objects straight
   from sawc, only the LINK uses IDF pieces; a new BOARD HAL under
   the existing riscv32 arch: interrupt matrix + SYSTIMER + Espressif
   UART swap in behind the seams). Optionally as the FLAT PROFILE
   first: `[sos] profile = "flat"` — syscalls become direct calls by
   swapping ONLY the bottom sysapi altitude (the vDSO discipline
   makes this surgical); one source, two builds; faults degrade to
   halt; the whole image is one trust domain, stated.
4. THE GOAL: P4 + the net stack + ESP-Hosted driver to a C6
   companion. Protected build once the P4 HAL exists.

STAGE 2 (user-approved Aug 16): SINGLE-CHIP WIFI VIA THE OSI-TABLE
SHIM — the "FreeRTOS fakery" route, with an OPEN-SOURCE EXEMPLAR to
pull from. Espressif's closed WiFi/BT blobs (static .a archives:
libnet80211/libpp/libphy/libcoexist) call the OS through an
`osi_funcs` table of ~100 function pointers (tasks, semaphores,
queues, timers, DMA-capable alloc) plus a residue of direct externs
(esp_timer_*, NVS for phy calibration, esp_fill_random, logging).
esp-rs's `esp-wifi` crate IS this shim built for bare-metal Rust — no
FreeRTOS, working WiFi+BLE, open source — so we reimplement known
semantics over SOS primitives (tasks -> SOS threads, semaphores ->
Events, queues -> M4 channels, timers -> M3 Timer, DMA alloc -> the
alloc_memory attr), not reverse-engineer blob expectations. The blobs
are STATICALLY LINKED, so step one is the UNDEFINED-SYMBOL HARVEST:
link the blobs against our objects, and the undefined list — 
partitioned osi-table vs direct-extern — IS the complete work spec
before a line is written. Honest core risk: the blob's internal tasks
assume priority-preemptive scheduling at ms-scale fidelity (SOS's
scheduler is the structural advantage here — esp-rs had to build one
from nothing), and timing bugs against closed code are slow to debug.
Gnarly-bring-up work, not fan-out agent work.

STAGE 3 (the stretch, and the payoff for the user's drawer of S3
boards): ESP32-S3. The shim TRANSFERS (osi semantics are
chip-agnostic; esp-wifi covers Xtensa), but the S3 additionally needs
the two things that kept it off stage 1: the XTENSA CODEGEN SEAM
(sawc emits .ll with the xtensa triple + hand-supplied datalayout;
Espressif's LLVM fork lowers it — llvmlite never will) and an XTENSA
HAL (windowed-register trap entry, PMS/World-Controller protection or
the flat profile). Build the shim ONCE on the C6 where the toolchain
already works; the S3 port then reuses it wholesale.

Explicitly later: BLE host stack (GATT-peripheral-only is ~4-8k lines
over HCI to the companion; SMP/crypto is the hard center — shim
AES-CMAC/P-256 through C per the support.c precedent, never dogfood
constant-time crypto in Saw first; developable HOSTED against BlueZ's
virtual controller with zero hardware). No dispatches
before M3 lands; net phase 1 is the natural first post-M3 brief.

## DF-225o — `reemit` reported three DIVERGENT files under heavy load and none
## on a quiet machine (observed Aug 16 by the design-225 terminal battery; the
## compiler emitted different bytes twice in one process, so this is a
## nondeterminism report, not a harness complaint)

**What happened.** `tools/battery.sh reemit` over the whole corpus, running while
another session's full battery had the machine at load 25-30, reported
`identical: 1213  skipped: 468  DIVERGENT: 3` — `erased_downcast_error_retry`,
`enum_policy_explicit_copy_deep` and `equatable_optional_string_synth`, one in
each of shards 2, 4 and 6, all on the `.ll` artifact. Re-run immediately
afterwards on the same tree: the three files alone are identical, shard 2 alone
reports zero diffs, and the WHOLE corpus on a quiet machine reports
`identical: 1216  DIVERGENT: 0`.

**Why this is a finding and not a flake to wave off.** reemit's oracle is that
compiling one file twice IN ONE PROCESS emits the same bytes. Load does not
change what LLVM prints. What load changes is Python object ADDRESSES, and an
address is what `id()`-based hashing keys on — so a `set` or `dict` of objects
that do not define `__hash__`, iterated anywhere on the emission path, has an
order that shifts with allocation history and memory pressure. That is exactly
the class design 141 found twice and design 164/220 chased through the id
allocators, and it is real nondeterminism in the compiler however rarely it
shows.

**What the fix owes.** Reproduce it deliberately rather than waiting for another
loaded machine: run reemit under memory pressure, or instrument the emission
walks to assert that every set/dict they iterate is either sorted or keyed on a
stable value. The three files above are the starting sample and they have
nothing obvious in common (an erased downcast, an enum copy policy, a
synthesized Optional `equals`), which is itself informative — a shared
mechanism upstream of all three is more likely than three bugs.

**Not caused by design 225** as far as the evidence goes: the same tree is clean
on a quiet machine, and 225's own change to `std/taskgroup.saw` is merged into
every compile, so a determinism bug it introduced would not be load-sensitive.
Filed by that brief because it observed it, not because it owns it.
LEAD NOTE at integration: the queued set-of-str mech lane's scope WIDENS
to cover `id()`-keyed object sets on emission paths — this finding is
that lint's second customer.

## Design 178 M2 unit 1 — trap/timer/interrupt-controller HAL (BUILT Aug 15,
branch PARKED for user review per SOS policy)

`designs/178-sos-m2-sketch.md` carries what landed. In one line: both HALs
grew a periodic timer and their board's interrupt controller behind ONE
seam, `ktrap` grew an interrupt arm ahead of the fault/syscall ones, and
`sos/kernel/core/` grew the two arch-free hooks the scheduler and the
Interrupt object will fill. `make sos-test` is 38 cases (19 per machine).
D2 is enforced by the two machines rather than intended by the kernel, so
`IntrSpinLock` (spec §9b) is still unbuilt and still not needed. C floor
135 -> 140 code lines, every added line an instruction with no Saw
spelling. Out of scope and NOT built: Thread/Process, the scheduler,
Event/Waiter, the Interrupt object.

Findings the unit produced:

- **DF-178a — a `///` doc comment cannot document an `extern` declaration.**
  Inside `extern "C" { ... }` it is ``doc comment is not followed by a
  documentable declaration``, so a C seam's contract has to be written as a
  plain `//` comment beside the declaration it describes. The documentable
  list (LANGUAGE_SPEC "Doc comments") covers func/struct/enum/trait/
  extension/type/static, fields, cases, methods and inits — an `extern` func
  is none of them. It is exactly the position a HAL wants documented: the
  arm64 kernel HAL now declares four timer seams whose docstrings had to be
  demoted, and `--emit-docs` cannot see them at all. Small, clean-error,
  not blocking; the fix is adding `extern` functions to the attachable set.

- **DF-178b — FIXED (user-approved rider, same branch). User mode on Profile A
  ran ~2000x slower under QEMU than on Profile B, and the cause was one
  missing round-up in a linker script.** Found while sizing the M2 payloads,
  fixed by page-aligning the END of `.payload` in
  `sos/hal/riscv32/kernel/virt.ld` — the START already was, and Profile B's
  script already rounded both.

  MECHANISM, and it is worth stating precisely because the number invites the
  wrong conclusion: QEMU's softmmu caches address translations one PAGE at a
  time. A PMP region that covers only part of a page cannot be cached as a
  page, so every access to that page takes the slow path — a full walk plus a
  PMP check per instruction fetch. The kernel's grant ran from a page-aligned
  start to `align_up(payload_end, 4)`, so the payload's LAST page was always
  partial and the loop always ran there. This is a TCG softmmu artifact and
  nothing else: real silicon checks PMP in the pipeline at no per-access cost,
  and hardware never had this penalty.

  MEASURED, one payload (a two-instruction user-mode register loop, 20M
  iterations), same kernel, same grant code, only the linker line differing:
  **62.6s before, 0.03s after** (~0.3M iterations/s to ~1.4G). The three M2
  interrupt cases went from ~0.95s each to 0.06-0.07s, and both profiles'
  payloads now spin the SAME 100M count at the same order of speed
  (0.06-0.07s riscv32, 0.10-0.12s arm64, whole case including startup).

  WHAT DID NOT CHANGE: the byte-tight PMP capability. This aligns one section
  and removes no check — a grant still says exactly [base, top) at four-byte
  granularity, the loader still validates every segment, and the pages between
  `_payload_start` and `_payload_end` belong to `.payload` alone (`.data` ends
  before the section's opening ALIGN, `.bss` starts after the new closing one),
  so granting the whole span reaches nothing else. Cost: under 4 KiB of zero
  padding in a kernel image.

- **DF-172d, third sighting.** A binary expression still cannot wrap across
  lines unless brackets already enclose it, and the shapes that hit it here
  are the ones the finding predicts: OR-ing named descriptor bits, and
  composing a 64-bit value out of two 32-bit halves. Same family, worth
  recording because it is now the third independent brief to pay it: a
  postfix `.method()` on the line AFTER a closing `)` does not parse either
  (`UnsafeMemory<...>(\n  addr)\n  .write(v)`), since the newline after the
  bracket ends the statement — the fix is a `let` for the receiver, which
  reads better anyway, but it is the same "wrapping a long expression is
  where Saw's newline rule bites" story.

## Design 178 M2 unit 2 — Thread/Process objects + the scheduler (BUILT Aug 15,
branch PARKED for user review per SOS policy)

`designs/178-sos-m2-sketch.md` carries what landed. In one line: the trap frame
became the THREAD CONTEXT, so a context switch is `ktrap` returning a different
frame address and there is no second path; `kcore.start_process` is the one way
into user mode; Thread and Process are real objects with op tables, rights and
the ratified teardown; the scheduler is round-robin over a ready queue with the
timeslice charged in unit 1's tick hook; and design 178's faults ruling landed
whole, so BadHandle/BadOp/AccessDenied are `FaultReason` tags rather than
statuses. `make sos-test` is 44 cases (22 per machine). Native floor: assembly
342 -> 268 code lines (a context built in Saw needs no register-clearing
prologue), C 140 -> 166 (one `sos_syscall3` per profile, for the ops that answer
with a value). Out of scope and NOT built: Event/Waiter (the wait/wake substrate
is in, the objects are not), the Interrupt object, priorities, an idle loop.

Findings the unit produced:

- **DF-178c — a process cannot name a function's address, so it cannot give a
  thread an entry point.** `Process.thread_create(entry:stack_top:arg:)` wants
  a code address and Saw has no way to produce one: a named function is not a
  value (``undefined variable `worker` `` for `let f: () sync -> Void = worker`),
  an `extern`-declared symbol is not either (same error), and `@export` on a
  static emits a definition rather than a reference. This is design 172's
  REASON 3 (DF-172a, "the only open language gap") reaching a USER-FACING
  kernel API rather than four HAL accessor bodies — every SOS process that
  wants a second thread hits it, not just the runtime authors.

  WHAT M2 DOES ABOUT IT: a second `thread_create(stack_top:arg:)` overload that
  starts the thread at the process's own IMAGE ENTRY, which is the one entry a
  Saw process can name because the kernel already knows it. The entry then has
  to work out which thread it is running as; the harness's two thread images do
  it with a parked handle that doubles as a "have I run yet" witness. That is a
  real API, not a workaround — a spawn-at-entry model is what several small
  systems use — but it is narrower than the op, and the op keeps the address
  form for a process with a C leaf.

  THE FIX IS DF-172a's: some way to name a linker symbol's address. A function
  pointer type would do it for this case (`let f: () sync -> Void = worker`,
  then `(f) as UInt`), and would also close the four HAL accessors.

- **DF-178d — FIXED, `designs/228-never-contract.md` (BUILT Aug 16).** A
  `-> Never` CALL was not accepted everywhere a diverging tail is, and in some
  value positions emitted malformed IR. One mechanism with four faces; the
  isolation sweep found the trigger axis the standalone repros missed — WHICH
  codegen call path the site takes, so it broke for an OVERLOADED or a
  MODULE-PRIVATE-called-in-module callee and not for a plain one. Hosted vs
  freestanding was never an axis (58 cells x 2 profiles, 100% agreement).

  All six legs landed, each as a funnel with its entry points named: one
  TYPE-based divergence predicate (`ast_nodes.expr_diverges`), the one
  call-emitting chokepoint (`_emit_call`, which asks about a diverging ARGUMENT
  before the call and a `-> Never` callee after it), the one declaration
  lowering (`_lower_declared_return`, which `_declare_extension_methods` had no
  arm in at all), plus the `return` site and the `??` default. The gate is
  `examples/conformance/` rows D01-D19 — the sweep's 12-position x 6-callee
  matrix over both profiles, plus the method, static-method, generic, closure,
  vtable and trait-default callee kinds.

  Two boundaries the probes drew, both recorded in the code: a function TYPE is
  a representation, not a declaration, so `Never` stays the i8 placeholder
  inside one; and a `borrows` accessor's call type is the WINDOW's result, so
  `resolved_type == Never` is not a sound divergence proxy at a place call.

  Retired in tree: the three `sos` fault wrappers (`fault_result`, `fault_slot`,
  `fault_waitable`), the `if let` where a `guard` belonged, and the three
  cosmetic `Never`->`Never` loops. `sos/kernel/core/lib.saw` cites this number
  nowhere now.

  ONE RULING THE USER MAY WANT TO REVISIT (unit 5): `suspending -> Never` is
  REFUSED in v1 at all three task-start positions (`group.spawn`, `spawn { }`,
  `__saw_drive`). It used to be accepted and minted a `TaskHandle<Never>` whose
  type argument reached the mangler's escape hatch as `$Unknown$NEVER`, with a
  `join` that could not return. Blessing the never-Done frame as an honest
  forever-server type forecloses nothing and stays re-proposable; it owes a
  `NEVER` mangle case, a `Slot<Never>`/zero-size story (the DF-221a Void census
  family) and a ruling on what `join` means.

- **DF-178e — a bare literal does not adopt an annotated type through a
  `match`.** `let ra: UInt = match a.join() { case Ok(v) -> v, case Err(_) -> 0 }`
  is ``the match arms have no common type: `UInt` and `Int` `` — the annotation
  does not reach the arms, so the `0` stays platform `Int` and the merge fails.
  Design 195 says a bare literal adopts a fixed-width EXPECTED type "wherever
  one is in force" and lists if/match arms; an annotation on the BINDING is
  evidently not one of the places that force propagates from. The workaround is
  a named `UInt` constant per default value, which is what the two thread images
  do. Small, clean-error, and it lands on the most ordinary shape there is:
  reading a Result with a fallback.

## Design 178 M2 unit 3 — Event and Waiter (BUILT Aug 15, branch PARKED for
user review per SOS policy)

`designs/178-sos-m2-sketch.md` carries what landed. In one line: D5 as ratified
— an Event that accumulates by OR or by saturating sum and never blocks, a
Waiter whose level-triggered readiness is a SCAN rather than a maintained queue,
both as ordinary §2 rows with op tables, kind-scoped rights, dispatch arms and
the ratified teardown; creation authority answers spec §12's open pin by living
on the Process handle; and `Waiter.Wait` answers with a RECORD the kernel copies
into a caller-supplied buffer through the kernel's one validated copy-out door.
`Waiter.remove` names an attachment by its KEY (never the waitable), which
forces keys to be unique per Waiter and makes a duplicate `add` a fault.
`make sos-test` is 56 cases (28 per machine). Native floor UNCHANGED — 268
assembly and 166 C code lines, a net-zero delta for the whole unit. Out of scope
and NOT built: the Interrupt object and the userspace UART echo proof, which is
also what turns the scheduler's deadlock report into an idle loop.

Two known findings were re-encountered and cited in place rather than refiled:
DF-178d cost one more `-> Never` wrapper (`fault_slot`, beside `fault_result`),
and DF-178e was avoided ahead of time by naming two `UInt` constants for the
`match` default values.

- **DF-178f — `sizeof<T>()` does not fold in a static initializer.** Design 186
  ruled a static initializer to be a CONSTANT EXPRESSION over "literals,
  arithmetic and bitwise over them, `sizeof`/`alignof`, the integer limits, a
  raw-backed enum case, an earlier module `static`" — and that list is the
  compiler's OWN error hint, printed verbatim when it refuses one. But
  `sizeof` is not in the folder:

  ```saw
  static WORDS: Int = 3
  static A: Int = sizeof<UInt>()          // error: not a compile-time constant
  static B: Int = 3 * sizeof<UInt>()      // error
  static C: Int = WORDS * 8               // fine — an earlier static folds
  static D: Int = WORDS * sizeof<UInt>()  // error
  ```

  So three of the four fail, the one that works is the one NOT naming `sizeof`,
  and the diagnostic names `sizeof` as permitted while refusing it. The same
  expression folds perfectly well in an ordinary body and in a `static_assert`
  (`static_assert(sizeof<TrapFrame>() == FRAME_BYTES, ...)` is in the tree), so
  this is the STATIC-INITIALIZER const evaluator missing a case the general one
  has, not a limit on `sizeof`.

  Where it bites: any size that is `N * word` — a wire record measured in
  machine words, an alignment, a per-word stride. SOS unit 3 wanted two
  (`wait_record_bytes`, `word_bytes`) and both became small functions with the
  reason written beside them. Cheap to work around, and misleading precisely
  because the error text says the opposite.

## Design 178 M2 unit 4 — the Interrupt object + the userspace UART echo
(BUILT Aug 16, branch PARKED for user review per SOS policy) — M2 COMPLETE

`designs/178-sos-m2-sketch.md` carries what landed, with both transcripts. In
one line: D6 plus the five ruled finale constraints — an Interrupt object that
binds an IRQ line to a waitable and acks through the handle, a device MMIO
window the driver's own image DECLARES and the board authorizes, a stated
console handover protocol (now spec §9a), and the milestone's proof: a
userspace UART echo driver on both machines, with no driver code in the kernel.

Four things worth knowing without opening the brief:

- **The second waitable kind moved the attachment into a table of its own.** A
  Waiter's set has to be one list, so per-kind lists would have made both `add`
  and `remove` a matrix over kinds; what stays per-kind is four exhaustive
  matches in one place, and a fifth waitable fails all four to compile.
- **"Nothing runnable" stopped meaning deadlock**, and the kernel idles by
  PARKING THE CORE AND POLLING rather than by taking the trap — so design 178's
  D2 is exactly as it was and there is one service path with two ways in.
- **`irq_raise_selftest_line` STAYS**, against unit 1's expectation: a line
  raised in kernel mode and a line bound to NO Interrupt object are two kernel
  behaviours reachable through nothing else.
- **The harness delay is the test.** Feeding the whole string at once proves the
  echo and not the interrupt path, since a polling driver would pass; one byte
  at a time forces the park, the idle, and one wake per byte.

`make sos-test` is 64 cases (32 per machine). NATIVE FLOOR: +1 C line per
profile (`sos_wait_for_irq` — `wfi` is an instruction), assembly unchanged.

NO NEW LANGUAGE FINDINGS. Three known ones were re-encountered and cited in
place rather than refiled: DF-178d cost a third `-> Never` wrapper
(`fault_waitable`, beside `fault_result` and `fault_slot`); DF-178f kept
`wait_record_bytes` a function; and DF-172d (a binary expression does not wrap
across a newline unless brackets already enclose it) turned a long
`[UInt64; a + b + c]` static into a named descriptor count, which is the
SIZE-IN-ONE-PLACE idiom and is better anyway.

  SWEPT (obligation 4), and the class is exactly two items wide. The mechanism
  is "the static initializer's const evaluator implements a SUBSET of the const
  expression grammar", so the whole of design 186's ruled list was put against a
  static. Everything else on it folds:

  | initializer | folds |
  |---|---|
  | a literal; arithmetic; bitwise `(1 << 12) - 1` | yes |
  | an earlier module `static`, alone or under arithmetic | yes |
  | `Int.max`, `UInt.max` | yes |
  | a raw-backed enum case, and `Perm.Read \| Perm.Write` | yes |
  | `sizeof<T>()` | **NO** |
  | `alignof<T>()` | **NO** |

  So the gap is the two SIZE OPERATORS and nothing else — a bounded fix (teach
  the static-initializer evaluator the case the general const evaluator already
  has) with a two-row test plan, not an open-ended audit.

RIDER (ruled Aug 16, user): an ARGUMENT ENCODING IS API. `event_create(mode:)`
replaces the method-per-mode pair — a method per mode stops scaling at M3's
Mapping, where the modes multiply — and the `sos` module docstring now carries
the line for Mapping to inherit: the vDSO discipline is about OP NUMBERS, not
argument encodings, so an enum a process CHOOSES and passes is public
single-declaration API while op numbers, rights bits, `ObjType` and
`FaultReason` stay kernel-internal. One declaration serves both halves because
Saw's imports RE-EXPORT. Two properties established by probe rather than
assumption, both in the brief: the re-export is INDISCRIMINATE (so the split is
held by what userspace is told to write, not by a wall — and `sosabi` was
already on a process's module path transitively), and the enum cannot move the
other way, because a kernel importing `sos` is a duplicate-`@export` error on
the two runtime hooks both sides define.

## Design 220 — recorded-seed suite compiles, per-run artifacts, irdet reuse
(AUTHORED + RULED Aug 14, queued behind 218 stages 1-2 integration)

`designs/220-suite-ir-reuse.md`. Suite workers get random RECORDED
`PYTHONHASHSEED`s (per-worker — design 115 makes compiles in-process, so
per-compile is impossible), making hash-order flakes replayable for the
first time; the runner writes per-run output dirs published by atomic
symlink flip (`test_runner_last`), pruned to K=3; artifacts carry an
mtime staleness stamp with the three known holes closed (deletions via
dir mtimes, the llvmlite dist-info, test_runner.py itself); irdet --all
reuses fresh suite IR and compiles only the second side (~half its
measured 755s), with a three-way verify on any mismatch that reports a
stale/divergent artifact as its OWN failure — no silent healing, no
false green possible. Five units, unit 0 is the obligation-2 consumer
sweep of the `.build/<stem>` layout flip. All decisions ruled; the units
execute, they do not re-decide.

**INTEGRATED Aug 14 (`7230b049..a858b74e`, eight commits) after the hold
resolved: design 221 fixed both blockers, the branch was rebased and
RE-GATED (battery 20/20; the brief's Re-gate section carries the full
numbers), and the post-integration suite is green at 1854/25. Measured
payoff: irdet --all 429s with reuse vs 796s without (46.1% saving, 99.1%
reuse, 0 mismatch/0 invariant); unchanged-tree suite compile stage
324s→25.6s; N=20 recorded-seed replay 20/20 byte-identical. Two
composition fixes rode the re-gate: irdet_verdict.py learned the
`invariant` status, and `manifest_eligible` excludes subprocess-fallback
and warning-asserting tests from reuse (the 1.3% whose reuse cost
coverage). Historical hold record follows.**

BUILT Aug 14, then HELD (user ruling): all five units complete and
battery-gated (18/18) on branch `worktree-agent-a347ef517d8ff1a2e`
(five commits, `67b880e2..62c5db34`, based on `44537555`; worktree kept).
NOT integrated until DF-220a and DF-220b below are fixed. The
mechanism is proven — unchanged-tree suite compile stage 219.7s→22.3s at
100% reuse; irdet's clean-reuse slice byte-identical — but 84.4% of
artifacts fail the three-way verify on DF-220a, which makes reuse a net
slowdown until it lands. Unit-0 sweep + measurements and both findings'
full write-ups are in the BRANCH's copy of this brief.

- **DF-220a — `compile_saw()` is not self-reproducible across calls in
  ONE process** (seed-independent; 6-line repro in the branch brief).
  **SWEEP RUN (Aug 14, `.build/scratch/sweep220a/RESULTS.md`, GITIGNORED):
  the `_NEXT_NODE_ID` hypothesis is REFUTED (reset probe is a no-op) and
  the real mechanism is PINNED: LLVM's process-global `LLVMContext`
  named-struct uniquing.** Every `binding.parse_assembly` at
  codegen/core.py:3132/:3148 omits `context=` and lands in the global
  context; llvmlite's ABI-size queries (core.py:2091-2096 →
  `_get_ll_global_value_type`) parse a throwaway module carrying the
  compile's WHOLE identified-type table into that same context — 92
  parses × ~45 types ≈ 4150 uniquings per compile — so compile 2's
  struct names get `.NNNN` suffixes from `NamedStructTypesUniqueID`.
  SCOPE IS TEXT-ONLY AND BENIGN: unoptimized sidecar `.ll` and `.o`
  bytes are IDENTICAL across in-process compiles; the whole optimized-IR
  diff normalizes away by stripping `\.\d+`; the 33-byte exe delta is
  the known design-164 N_OSO mtime artifact, not this. Design 115's
  bit-identity HOLDS for compile 1 (byte-equal to fresh CLI) and breaks
  from compile 2 on. Nothing in today's tree is miscompiled — the bug
  bites exactly design 220's optimized-IR reuse compare (the "84.4%
  VIOLATED" backlog is suffix churn). Obligation-4 census: every
  Python-side counter/cache/id() site enumerated and cleared with probe
  evidence (unopt IR byte-identical across advanced counters); the
  LLVMContext is the ONE mechanism. **FIX A MEASURED TO WORK: route
  every parse through a per-compile `binding.create_context()` — three
  compiles in one process, unopt/opt/obj all identical AND equal to
  today's fresh-process output, i.e. ZERO corpus churn.** Brief snags:
  llvmlite's `Type.get_abi_size` hard-codes the global context (sawc
  must own that query or compute layout from the data-layout string);
  the context must outlive every ModuleRef/target-machine use. The
  fix's gate needs a NEW LANE: compile one file TWICE in one process,
  compare OPTIMIZED IR — today's `tools/reemitdiff.py` compares only
  the stable artifacts (green and blind) and is NOT in battery STAGES.
  Perf rider for the brief: each compile permanently leaks ~45 types /
  ~4200 uniquings into a design-115 worker's global context. Not
  probed: --freestanding/--runtime-build/--target/-O0/--module-path
  paths (mechanism is triple-independent but unevidenced there);
  suffix-only-ness verified for 2 of 12 diverging files.
- **DF-220b — a suspending `main() -> Int` never propagates its return
  value to the process exit status** (12-line repro; confirmed against
  the unmodified pre-220 irdet binary). USER-FACING language bug: every
  driven program exits 0. Consequence found live: the battery's irdet
  lane trusts `$?` and so HAS NEVER BEEN ABLE TO FAIL — this brief's own
  terminal battery printed "969 file(s) VIOLATED THE REUSE INVARIANT"
  three lines above `irdet: ok`. Fix-on-discovery, queued directly after
  218 stage 3 (the coro drive path is stage 3's surface). Obligation 4
  sweep first: is it only `main`, or every driven root's return value /
  every exit path (panic codes, spawn results)? The fix's landing ALSO
  flips `battery.sh run_irdet` to parse irdet's structured output —
  never `$?` — closing the vacuous-green gate hole.

  **SWEEP RUN (Aug 14, obligation 4 — full matrix + probes p1-p27 in
  `.build/scratch/sweep220b/RESULTS.md`, GITIGNORED, promote the matrix
  rows to conformance rows at fix time). MECHANISM CONFIRMED, a CLASS of
  exactly two:** the value reaches the frame's `__result` slot and both
  synthesized ENTRY EXECUTORS declare themselves Void and drop it —
  `_make_entry_executor` (coro_transform.py:6275-6278) and
  `_make_ambient_entry_executor` (:6298-6302, whose root rides
  `__saw_exec_run_root(Box<any Resumable>)` + a `__VoidCell`, so the
  ambient half is an rt/ABI.md seam question). `_make_driver`
  (:6356-6398) — every NON-main driven root — already does the correct
  `take`/`move __res` read; spawned `work() -> Int` returns fine
  (proven). Panics UNAFFECTED (rc 134 everywhere incl. MT);
  suspending `-> Void` clean; `--freestanding` has the SAME bug (entry
  synthesis is target-independent). Fix shape: give both executors the
  driver's result plumbing at the shared point, then ONE i32
  narrow/convert in codegen for every main (obligation-1 funnel).
  Blast radius: `blade/src/tester.saw:52-108` and `test_runner.py:687`
  both judge by rc==0 and WOULD falsely pass a suspending nonzero-return
  test, but are INERT today — all 43 test mains across
  blade/libs/selfhost/bench are Void + panic-based (verified by
  compile). Live consumers: only irdet (battery.sh:103-106,
  Makefile:72-77) — plus a CORRECTION to the branch brief:
  `irdet_remote.py:59`'s `--plan` returncode guard is ALSO vacuous
  (check_here itself is sound). Only workaround today: libc `exit()`,
  which blade already uses (blade/src/main.saw:19-21). std has no
  process.exit.

- **DF-220c (NEW, found by the 220b sweep) — `main`'s return type is
  entirely unconstrained.** typechecker/core.py:1680+2461 check only
  that `main` EXISTS; codegen/core.py:2396-2400 overrides the LLVM
  return type to i32 ONLY for Void and emits everything else as
  declared. Measured: `main() -> String` exits 192 (the low byte of a
  heap POINTER); `main() -> Result<Int, Oops>` emits a struct-return
  `@main` against a C ABI expecting int (exit 138); `-> Int` works by
  ABI accident (i64 vs i32) on arm64/x86-64. LANGUAGE_SPEC.md documents
  no `main` rule at all. **RULED (user, Aug 14): `main` may return
  exactly `Void`, `Int`, `Result<Void, E>`, or `Result<Int, E>`;
  every other return type is a compile error naming the four.** Exit
  mapping at ONE codegen funnel (with DF-220b's fix): Void → 0, Int →
  the value (POSIX & 0xff), Ok(Void) → 0, Ok(n) → n, Err(e) → print
  the error, exit 1. The diagnostic and the funnel land in the
  DF-220a/b fix brief; LANGUAGE_SPEC gains the `main` rule.

**DF-220a, DF-220b and DF-220c ARE FIXED — `designs/221-main-exit-and-compile-context.md`
is BUILT** (Aug 14, branch `worktree-agent-af68e30d247888405`, seven commits
`d943f2c8..`, based on `4b3efa0d`; awaiting user review). Each compile owns
its `LLVMContext` (zero corpus churn, measured); both entry executors
return main's result, the ambient one through a group-owned
`__ResultCell<Int>` and `__saw_exec_run_root_status`; `main`'s return type
is held to the four; ONE codegen funnel maps every shape to the C entry's
`i32`, and its return-site sweep found a third door (`try` inside `main`
emitted a struct out of an `i32` function — a `Result` main with a `try`
did not compile at all). The battery gained a `reemit` lane (two compiles
in one process, byte-comparing the OPTIMIZED IR) and the irdet lane reads
`--jsonl` records instead of `$?`. Conformance rows G01-G18.

Post-fix path: rebase the branch onto fixed main, re-run unit-2's N=20
replay leg (was blocked on DF-220a), re-gate (expect reuse GREEN
and the irdet lane honestly red-capable), then integrate.

- **DF-221a (NEW, found writing design 221's conformance row G11) — a
  `Result` whose BOTH payloads are zero-sized is an ICE at the Err wrap.**
  `struct Unreadable {}` + `func attempt() -> Result<Void, Unreadable> {
  return Unreadable() }` (sync, no coroutine anywhere) reports
  `internal compiler error ... (ResultErrWrap): Can't index at [0] in i32`.
  Mechanism: the monomorphized Result enum lowers to the TAG ALONE when the
  widest variant payload is 0 bytes, so `llvm_enum_type.elements[1]`
  (results.py:470) does not exist. `_create_result_ok_for_return` already
  has the guard it needs (`_is_void_payload`, results.py:505) but that test
  asks whether each field is `VoidType`, and an EMPTY STRUCT is `{}`, not
  void — so the Ok arm of this same Result is fine and only the Err arm
  ICEs. Give the error type one field and everything works
  (`.build/scratch/probe221_rvoid_sync.saw`, verified both ways).
  Unrelated to design 221's mechanism: it is the zero-sized-payload enum
  lowering, and it reaches `_extract_result_err_value` too. Row G11 uses a
  one-field error on purpose; a fix wants its own sweep of the tag-only
  enum path (create + extract, Ok + Err, every arity).

## Design 222 — the safe async rewrite (PROTOTYPE BUILT Aug 14, awaiting review)

`designs/222-safe-async-rewrite.md` carries the per-unit records. All four
units built on a worktree branch; E2 is DELETED and the corpus compiles with
zero reads of it. The headline: unit 0 measured E2's surviving coverage at
166 files and THREE constructs, all of them a pointer cast the transform
spliced into somebody else's body (the spawn site was 158 of them, not the
drive site the stage-3 commit named), and the cell/latch the brief predicted
were never E2's at all. Unit 2 moved those three crossings into the
generated driver / spawn helper — the call sites write `&group` and `&c` —
which emptied the flag. Unit 1 gave the spawn cell the `UnsafeRef` treatment
(the result WRITE stays raw, deferred to FAM_WINDOW_MOVE with measured
evidence); unit 3 built the wake-latch wrapper, ran it, and REFUSED it for
laundering the obligation, so the latch is a core entry with a four-part
traced argument. Trusted list: item 4 (the drive-site cast) retires, item 2
narrows, item 3 gains the argument. **Landing is the lead's call** — the two
things to scrutinize are unit 2's shared-vs-`&var` reference choice at the
drive/spawn site and unit 1's deferred cell write.

**INTEGRATED to main (user go, Aug 14)** — seven commits cherry-picked,
suite-verified. The unit-1 cell-write deferral is RATIFIED as
FAM_WINDOW_MOVE/DF-218h family work. The unit-2 reference choice spun off
as its own question:

- **DQ-222a (RULED + CLOSED, user, Aug 15) — generated call sites keep
  `&`; `spawn`'s mode is now a stated position, not an accident.** The
  ruling session established: `spawn` is COMPILER SYNTAX with no
  declaration, so the language had never taken a position on its mode.
  Ruled: `spawn` works through a shared reference. The justification was
  refined mid-ruling by the user's Sync question — TaskGroup is NOT in
  the Sync class with Channel/Mutex/SpinLock (all UnsafeSync,
  parallelism-safe by synchronization): it is NoCopy + NoMove and not
  Send, so its `&self` surface cannot race because it is PINNED to its
  owning thread (default engine has `lock: None`; the `threads: N`
  run-queue mutex serves only the internal worker handoff). Two
  different reasons `&`-mutation is safe, one class of "cannot race" —
  and for a thread-pinned type, `&var`-tightening polices a hazard that
  structurally cannot exist. LANGUAGE_SPEC's TaskGroup section now
  states the mode and its reason. Optional internal-consistency cleanup
  (generated sites mirroring a method's declared self-mode) noted as
  riding any future transform touch.
  **Follow-up probes (Aug 15, `.build/scratch/probe_arc_tg*.saw`,
  gitignored): `Arc<Box<TaskGroup>>` WORKS same-thread** — NoMove permits
  in-place construction into the Box ("build the value where it has to
  live"), Box/Arc handles move freely, ran at strong=2 — and the
  `threads: N` spawn gate REFUSES it crossing (clean diagnostic: not
  `Send`, structural through Box). So thread-pinning is enforced by
  Send/Sync propagation + the MT spawn gate, NOT by NoMove/Arc
  unreachability (an earlier claim here, corrected). CONFORMANCE ROWS
  OWED (ride the next conformance batch): (a) the same-thread
  `Arc<Box<TaskGroup>>` ACCEPT row — pins the capability so a future
  change cannot silently take it; (b) the MT-crossing refusal with the
  real diagnostic; (c) `static` TaskGroup refusal; (d) the Mutex tower
  `Arc<Mutex<Box<TaskGroup>>>` refusal (probe_arc_tg9 — Mutex's
  `T: Send` bound correctly computed, conformance withheld, refused).
  ANNOTATION: DF-219c (spawn capture audit not bound-aware) is
  LOAD-BEARING for this whole story — the MT spawn gate is the one
  fence; its bound-blindness is now a soundness-adjacent gap, priority
  up a notch. NARROWED Aug 15: probe_arc_tg9 shows the
  conditional-conformance bound IS consulted for a typed PARAMETER on
  the MT spawn path (this cell is green) — 219c's gap is elsewhere
  (its filed shape: generic-bounded captures). Diagnostics-batch rider:
  the MT refusal's hint suggests "Arc (and Mutex for mutation)" even
  when refusing an `Arc<Mutex<...>>` — for a non-Send payload no
  wrapper helps and the hint should say the payload itself must be
  Send.

- **DQ-222b (RULED + CLOSED, user, Aug 15) — a heap-owned TaskGroup is
  INTENDED; the scope a group defines is its OWNERSHIP EXTENT, not a
  lexical block.** The ruling session reduced the question to its true
  residue before ruling: heap ownership changes neither whether the
  join happens (guaranteed), nor whether it can hang (a stack group's
  scope-end join already blocks on a never-completing task — deinit
  DRIVES to completion, taskgroup.saw:913-925, cancellation is
  handle-driven not automatic), nor determinism (the Arc is non-Send,
  all handles on one thread, last release is a fixed deterministic
  program point) — only the LEGIBILITY of where the join-and-drive
  runs (dataflow-determined, not readable off block structure).
  Ruled working-as-intended; the legibility cost is a documentation
  problem and LANGUAGE_SPEC's TaskGroup section now carries the
  paragraph (ownership-extent reading, last-release drives remaining
  tasks, cancel() as the early-out). Row (a) of the owed conformance
  rows doubles as the capability pin. The "scope-pinned" fence stays
  available behind a real finding if dogfooding ever shows the
  wandering join point biting.

## Design 223 — suspending-method positions (AUTHORED Aug 14, two user questions open)

`designs/223-suspending-method-positions.md`, from the DF-218k/l/m
obligation-4 sweep (probes `.build/scratch/sweep218klm/`, gitignored).
The trio is TWO mechanisms and a ~10-cell class, SEVEN cells silently
sync: `_method_call_owner` is a two-valued name-keyed classifier whose
None means both "not suspending" and "inexpressible", and all seven
consumers incl. both rejectors read it as the former; the closure walk's
definition-side skip misaligns with it (four symptom shapes from one
hole); DF-218k is the method-table strip vs the conformance re-check.
The typechecker's effect graph is EXACT throughout — only the transform
disagrees. Blast radius zero WITH the reason: every existing enum/generic
coro test drives from the ROOT position, which works; the embedded
position had zero corpus coverage. Fix = a three-valued funnel
(UNSUPPORTED raises, never degrades), gsm-table keying reused, matrix ×
three properties (compiles / frame symbol in IR / interleave) as the
test plan. AWAITING: the cell policy confirmation + the closure-body
axis disposition (brief §Open questions). Also filed by the sweep:
DF-218o (qualified yield lost in generic clone), DF-218p (cross-module
generic literal doesn't substitute — plain mono bug; **WIDENED Aug 15:
also reaches std/prelude types through ANY qualifier** —
`arc.Arc<Int>(value: 5)` → "argument `value` expects `T` but got
`Int`", probe_diag_b — so the blast radius is every qualified generic
construction, not an obscure cross-module case), DF-218q
(unanchored &any refusal in spawned body); cell K falsifies DF-206d's
"not live" in the over-inclusion direction (a std name collision forces
a frame onto sync user code).

**UNIT 0 LANDED (rows first, obligation 3).** The matrix is
`examples/conformance/` rows K33-K39, each asserting THREE properties —
compiles, `__Frame_<owner>_<method>` in the emitted IR, and a two-task
interleave (`A1 B1 A2 B2`) — all seven under cited XFAILs. The IR half
needed a directive, so `test_runner.py` gained
`// EXPECT-IR-CONTAINS:` / `// EXPECT-IR-ABSENT:` over the `.ll` sidecar
a compile already leaves beside its binary: the cooperative contract is a
claim about EMITTED CODE, and every runtime assertion is blind to it (a
silently-sync call site computes the same value in the same order). Two
findings the rows filed: DF-223a (cell G's unanchored KeyError) and
DF-223b (cell C2/C3 — the existential dispatch design 223 refuses, with
the design it is owed written out).

**UNITS 1-3 LANDED (Aug 15).** Unit 1 = the three-valued
`_suspending_method_target` + `_promote_nested_generic_methods` (the
method twin of design 74 shape 3) + M2's definition-side alignment, one
commit. Unit 2 = `_strip_driven_method`, which refuses to remove a
method a conformance requires and builds that frame from a copy — the
same answer cross-module already gave. Unit 3 = the diagnostics: an ICE
breadcrumb naming the classifier/closure-walk agreement invariant, the
closure-body message that stops naming `if let`, the `&any Trait`
parameter refused at the parameter, and DF-223b's anchored refusal.
All seven rows pass, DF-218k/l/m, DF-206d, DF-218q and DF-223a closed,
DF-223b open as a DESIGN. One thing the sweep did not predict: the
suspending-method set is the CONSERVATIVE one, so UNSUPPORTED and
promotion had to be gated on design 206's `really_suspending` or an
ordinary `v.map({ n in slow(n) })` is refused.

## DF-224a/b — silent hangs on the MAIN task's wake path (filed Aug 15,
## found by the docs dispatch's cookbook probes; design 224 = the
## unauthored fix-family brief)

**SWEEP RUN (Aug 15, `.build/scratch/sweep224/RESULTS.md` + probes,
GITIGNORED): both hypotheses FALSIFIED as stated — TWO briefs, not one
class.** Neither is main-specific. Repros ck13/ck15 + the full
matrices in the scratch dir; promote to cited pins at fix time.

- **DF-224a — CLOSED by design 224 (landed Aug 15). All four gaps, one
  landing; every cell of the 135-probe matrix works, none refuses. Rider
  DF-217f closed with it (a suspending call in a constructor that IS a match
  scrutinee was the head gap under another name). The only boundary left is a
  VALUE-position `while` whose condition suspends, refused cleanly and pinned
  in `examples/errors/coro_value_while_suspending_condition.saw` — a value
  `while` yields through `break <value>`, which a suspension-spanning loop
  does not support, so the refusal is that limit's and not the head rule's.
  Original finding below.** FOUR independent coverage gaps in coro_transform,
  six SILENT-HANG cells. A `Channel.receive()` in a match SCRUTINEE, an
  if/while CONDITION, a for RANGE, or an `&&`/`||` condition RHS is
  neither embedded nor refused — it lowers as a plain call whose
  `yield_now` no-ops → 100%-CPU spin (measured; identical in main and
  spawned bodies). The same cells with a free fn/method are codegen
  ICEs (loud, same mechanism). Gaps: G1 `_collect_calls` never visits
  container HEAD expressions (:3732-3798 — its own docstring asserts
  the opposite invariant); G2 the narrow-hoist predicate
  `_call_suspends_expr` (:2005) OMITS `is_chan_recv` while its ANF
  twin `_is_suspending_call_node` (:2377) includes it — two
  disagreeing suspension predicates in one file; G3
  CompoundAssignStatement missing from `_anf_stmt` (:2138); G4
  `_classify_recv` lacks the ReturnStatement arm its free-fn twin
  has (:4210 vs :4121). Fix brief (design 224, unauthored, NO ruling
  needed): ONE suspension predicate for all three kinds with named
  entry points + a head-slot enumeration beside the container list
  (obligation 1); test plan = the sweep's position matrix × three
  suspension kinds × main+spawned. Riders: the compound-assign
  refusal blames `if let` the author never wrote (:4463); five
  matrix cells (if let/guard let/try!/try/try?) UNKNOWN, blocked by
  DF-224c. G3 RIDER (design 227): the compound optional-chain assignment
  `x?.n += s.read()` reaches the same missing arm through the transform's
  read-modify-writeback, and is pinned as a clean refusal in
  `examples/errors/optional_chain_compound_assign_suspending_rhs.saw` —
  the fix converts that file into the success twin of
  `expr_suspend_optchain_assign.saw`.
- **DF-224b — RULED (user, Aug 15): design 225, the LIVE POOL — see
  `designs/225-taskgroup-live-pool.md` (direction ruled on the
  api-expected-not-easy doctrine + the family-consistency and
  fresh-writer evidence; sub-decision agenda D-a..D-f pending a ruling
  session; sequenced AFTER design 224's transform fix). Original
  finding: NOT a wake bug — `TaskGroup(threads: N)` is FORK-JOIN by
  construction (design 75) and has NO workers outside a join/Deinit
  drain.** MT groups never register with the ambient scheduler
  (taskgroup.saw:457-460, :588-591 says so outright); `__drain_mt`
  spawns AND joins its workers inside one call (:661-700). The general
  invariant (wake matrix, 15 cells): NOTHING outside join/Deinit makes
  an MT group run — main receiving, an ST-group task receiving, main
  sleeping all see zero MT progress; same-MT-group receive/send works
  (both inside the drain); the 21b `spawn{}` thread engine in the same
  position works (the live-pool precedent). RULING OWED (design 225):
  fork-join is the CONTRACT (fix = diagnostic on a cooperative park
  that cannot be satisfied + docs caveat) vs live pool (workers start
  at first spawn; the drain-time invariants at :50-53 and the unlocked
  slot trio at :492-505 must be re-derived — much larger).
- **DF-224c — CLOSED (design 237 unit 3, Aug 21).** `Channel<T?>.send(v: T)`
  call-site auto-wrap (design 176) was a codegen ICE inside a
  frame-transformed body (`Type of #2 arg mismatch: {i1, i64} != i64`), fine
  in main; the `Result` payload twin was the same. MECHANISM: the wrap is an
  ANNOTATION the typechecker stamps on the argument expression, and the
  transform SUBSTITUTES a different node into that position (a hoisted temp, a
  frame-field read). In ordinary code the post-transform pass re-derives it; in
  a driven body design 210 marks the user's call `embed_preserved` and the
  re-check skips the subtree whole, so the answer that travelled with the node
  was the only one there was. `_substitute` now MOVES the marks and clears the
  source — exactly once, since the old node becomes a `let` initializer that
  would wrap a second time. PIN:
  `examples/coro_autowrap_argument_in_driven_body.saw` (10 rows).
- Also from the sweep: `devtools/dogfood/programs/` is compiled by NO
  battery stage (swept clean by hand this once — all 7 run);
  `w1_limiter.saw:18-26`'s hazard comment documents a bug design 206
  closed (does not reproduce, four shapes probed) and its workaround
  is now misinformation — comment cleanup owed.

## Design 226 — FuncPointer<F> — BUILT (Aug 16), all four units

The DF-178c fix: entry points and C callbacks have a typed function
pointer, and functions are still not first-class values (DF-172a stays
open). See `designs/226-funcpointer.md` for the brief and the rulings
it records; the tree is the rest.

What landed beyond the brief's text, as decisions a reader may need:
- **Form 2 requires a `sync` CONTEXT** — a declared `sync` effect slot
  or `@export`, never a body that merely happens not to suspend. The
  closure form needs no marker because a coerced literal is checked
  against `F` at the coercion.
- **An overload set is selected BY `F`**, which is what the ruling's
  "annotate to select" asks for: the FuncPointer annotation is the only
  way to write `F` down, and every position that coerces has one.
- **`FuncPointer` joined the `@export` / `extern blocking` C-ABI
  whitelist** — it is one word and C-callable, so an exported Saw
  function may RECEIVE a callback.
- Two positions the brief did not enumerate and the type wanted: a
  **`static`** initializer (a link-time constant, so a dispatch table is
  a static) and a **field call** (`TABLE.run(x)`, how a table is read).
- Kernel adoption (`thread_create`) is still deferred to M3 unit 2 per
  the brief; nothing under `sos/` was touched.

- ~~**DF-226a — a closure body's TAIL never receives the expected RETURN
  type**~~ — **FIXED Aug 17 (`dd8a5c45`).** `_check_closure` pinned the
  expected return onto the body for exactly two shapes (a bare-`None` tail,
  a `Never` tail) and never called `_apply_literal_expected_type`, so the
  tail was missing every literal rule at once: a fixed-width return ICEd
  (`ret i64` from an `i32` function) and an array literal never learned it
  was a `Vector`. The body now goes through `_stamp_return_literal_types`,
  the SAME chokepoint `_check_function`/`_check_method` call, whose
  docstring names all three entry points. The XFAIL flipped;
  `examples/closure_tail_adopts_expected_return_type.saw` is the matrix
  (tail, `if` and `match` arm results, `return`, collection shaping, the two
  no-regression shapes), and `examples/funcpointer226_ffi_qsort.saw` dropped
  the `i32` suffixes it carried meanwhile — the C `qsort` callback where the
  finding surfaced now round-trips on bare literals.

- ~~**DF-226d — a bare literal never adopts an OPTIONAL slot's PAYLOAD
  width**~~ — **FIXED Aug 17 (`aa69ee24`)**, found by DF-226a's sibling
  sweep. One layer in from DF-226a: that was a caller that never reached the
  funnel, this was `_apply_literal_expected_type` itself judging the
  expectation by its own kind, so an `Int32?` slot left the literal at
  platform width and built a `{i1, i64}` where a `{i1, i32}` was owed — an
  ICE at EVERY position the funnel serves (annotated `let`, argument, field,
  return tail and `return`, array and `Vector` element, closure tail), which
  is what made one peel the whole fix. Two bonus effects: an out-of-range
  literal in an optional slot is now the ordinary clean range error, and
  `let v: Vector<Int>? = [1, 2, 3]` shapes instead of refusing. Regression
  test `examples/optional_slot_literal_adopts_payload_width.saw`.

- ~~**DF-226e — the `Result` half of DF-226d**~~ — **FIXED Aug 17**, to the
  Aug-17 ruling. `_apply_literal_expected_type` grew case (0d) beside the
  optional peel: a `Result` expectation over an integer literal peels to the
  UNIQUE payload that could adopt it, which also SELECTS the variant, since the
  auto-wrap picks `Ok`/`Err` by testing the value's type against each payload.
  `Result<Int32, Bad>` peels to the Ok side, `Result<String, Int32>` to the ERR
  side. Where both could (`Result<Int32, Int8>`) nothing is peeled and the
  refusal is `_result_autowrap_ambiguous` — which already owned design 30's
  `T == E` rule and now distinguishes the two cases in its wording, since
  "has the same Ok and Err type" was simply false for distinct payloads that
  both accept a widthless literal. One refusal, in the place that already owned
  ambiguity, rather than a second one inside the propagation funnel emitting a
  duplicate diagnostic for the same line.
  Tests: `examples/result_slot_literal_adopts_payload_width.saw` (XFAIL
  flipped — named `return` and tail, the Err side, a negative literal, an
  optional Ok payload that peels twice, a platform-`Int` payload unchanged, a
  method tail, a closure `return`, an abstract generic body that peels nothing)
  and `examples/result_slot_literal_ambiguous_payloads.saw` for the refusal.
  CORRECTION to the filing: the entry said named and closure bodies "have it
  identically". True of a closure's `return` (it shares the named funnel, and
  it is fixed here); NOT true of a closure's TAIL, which never reached the
  Result wrap at all — filed separately as DF-232h.

## The next queue — designs 195-202 + 153 (ALL RULED Aug 10, awaiting dispatch)

Every open ruling from the overnight run plus the parked backlog was
settled in the Aug-10 morning review; each has an authored brief.
Order (soundness → capability → consistency; typechecker briefs serial,
disjoint surfaces parallel):

1. ~~**195 integer width agreement**~~ — **LANDED Aug 10**, all five units,
   tracked battery green. DF-192f and DF-192g closed; DF-195a (an implicit
   widening extending by the TARGET's signedness — a second wrong answer,
   found by unit 1's probes) closed with them. Four findings filed:
   DF-195b/c (transfer-position narrowing and sign flip through the
   platform pair — a CONVERSION question, owed a ruling), DF-195d (may an
   integer literal adopt `Float`?), DF-195e (two widening positions with no
   source type threaded to them). See `designs/195-*.md` for the four
   decisions the units needed beyond the brief's text.
2. ~~**198 duplicate match arms are errors**~~ — **LANDED Aug 10**, all three
   units, tracked battery green. DF-192d closed: one chokepoint judges an
   exact duplicate arm, both lowerings behind it, ranges and guards exempt.
   The corpus sweep found ZERO duplicate arms outside the pin itself (1882
   .saw files). One finding filed: DF-198a (a guarded or tuple-nested match
   over an all-payload-free enum is a codegen ICE — the general pattern path
   reads a tag out of a shape that enum does not have). Two spellings the
   brief expected to behave otherwise are recorded in `designs/198-*.md`.
3. ~~**199 nested-call refs join the Law**~~ — **LANDED Aug 10**, all four
   units, tracked battery green. DF-188j closed: a nested call's `&`/`&var`
   arguments join the outer call's access set and meet the unchanged path
   test, so overlapping paths error on every tier and disjoint ones are
   untouched. Two answers the units produced: the receiver-position variant
   was NOT already caught (`p.total(reset(&var p))` compiled and read the
   receiver at its pre-reset value), and the consumer sweep over all 1890
   tracked `.saw` files found ZERO offenders — the rule landed without
   changing any existing program. No findings filed. Sweep record in
   `designs/199-*.md`.
4. ~~**200 receiver-copy place write**~~ — **LANDED Aug 10**, all three
   units, tracked battery green. DF-176c closes: the fourth vanishing-write
   spelling (an EXCLUSIVE place window on storage inside a `&self` receiver)
   is the design-176 error, judged in the place lowering; the borrows-body
   half is ratified as intended. Telling the refusal from the carve-out needed
   a new fact — WHERE an accessor lends from — so `place_transform` records
   each lending path's shape and `place_uses` walks it against the receiver's
   real type, which extends design 176's inline-vs-indirect walk by the one
   hop it could not take. The consumer sweep found ZERO exclusive windows on
   inline fields in `&self` methods across std, blade, libs, sos and devtools
   (fifteen grep hits over the write and call forms, none of them a place).
   One finding filed: DF-200a. Sweep record and the two answers the units
   produced in `designs/200-*.md`.
   ∥ **153 statics→enums sweep** (place lowering vs std .saw — disjoint).
5. **196 coro × erased errors + captures** (DF-193a, DF-192b/c,
   DF-191a) — solo (coro_transform + result cells).
6. ~~**201 spawn reference parameters** (design-88 relaxation, 189 u4,
   ratified)~~ — **LANDED Aug 10** (in a worktree), all four units, tracked
   battery green. DF-201a closes. Two answers: the declared-after-group case
   does NOT fall out of design 188's rule (188 walks capture lists only, and
   the argument shape was a silent use-after-free), and the DF-138a dual-role
   trampoline had to forward a reference parameter rather than pass its name.
   See `designs/201-*.md`.
7. ~~**202 Atomic move-only** (DF-186a, ruled GO by census) — after 153
   (both touch std .saw).~~ LANDED Aug 10. The census held: five holders
   flushed, nothing else. Units 2 and 3 landed SWAPPED — a tier flip
   without its cascade fails builtins for every program, so the
   declarations had to go first.
8. **197 declaration-position names** (DF-194a + rule-7 parse_type
   bypasses) — last; UX debt, feeds the parser port.

~~**204 std type identity**~~ — **LANDED Aug 10** (dispatched beside 196, in a
worktree), all four units, tracked battery green. DF-153b and DF-153a close
together: design 144's `(defining module, name)` reaches std, where each FILE
is a module, so a std type declared without `public` is that file's alone. What
it cost: std's public type surface is now DECLARED — 40 `public` markers,
sorted by hand against the prelude gate and the documented API, which is the
design-80/82 gate finishing the job for types. Counted afterwards from the
compiler's own view: 101 type declarations (29 in `builtin.saw`, 72 in `std/`),
48 declared public, 24 file-private. Two design-144-era bugs surfaced on the way and
are fixed: `name.split('$')[0]` at seven sites read a MODULE QUALIFIER as a
monomorphization suffix (one helper, `type_identity.declaration_base`, replaces
all seven), and a coroutine FRAME struct must never be qualified since the
compiler names it by string (`Struct.is_synthesized`). Two findings filed:
DF-204a (four std internals the compiler spells by string still reserve their
names) and DF-204b (a closure's symbol carries its source LINE). See
`designs/204-*.md`.

Also ratified Aug 10 with no work owed: design 183's two
implementation decisions (blocking-conflict = error not upgrade; Float
in the offload set) stand as landed.

Design 195 detail: all typed operands of an operation must be the SAME
type (implicit promotion from bare literals only — no promotion
ladder); value-branch arms are TRANSFERS through the existing
checkpoint (lossless widening legal, like `return`). 12-row position
matrix; conformance rows first; consumer sweep owed.

## FUTURE WORK — design 214, Raft under deterministic simulation (Aug 12)

**Not scheduled, not ruled, no units authored.** Brief:
`designs/214-raft-simulation-dogfood.md`, written from a live
investigation of the tree so the ruling session starts from facts.

Raft as a pure I/O-free state machine behind three seams (Clock /
Transport / Storage) over a simulated backend — virtual clock, scripted
network faults, seeded RNG — asserting the paper's four safety
invariants across replayable seeds. The first dogfood target to load
ownership-without-lifetimes, cancellation, existential dispatch and the
error surface at once, and the first with a correctness oracle stronger
than "it ran".

Enabling work the investigation found missing, each its own future
brief: a seeded RNG (there is none in the tree), `File.sync` (crosses
the frozen `rt/ABI.md`), a virtual-clock executor mode, a `TcpStream`
read deadline, and two VERIFY probes (single-threaded scheduler
determinism, `Map` iteration order). The RNG, `fsync` and **the `select`
/ receive-with-timeout ruling** are each dispatchable ahead of and
independent of any Raft code — `select` is a language question worth
answering either way.

## Design 216 — lifting `T: Copy` off Vector's closure and sort APIs (PROPOSAL)

**Not scheduled, not ruled.** Brief: `designs/216-vector-copy-bounds.md`.

`map`, `each`, `each_indexed`, `fold` and `sort` carry a `T: Copy` bound their
algorithms do not need — inherited from `iter`/`enumerated`, which do. The
effect is that a `Vector` of move-only elements cannot be mapped, folded or
sorted at all. Four probes in the brief show the bound comes off: `&T` element
closures for the first four (and the transform need not be `sync`, so
suspending transforms survive), and `swap` plus borrowed comparison for `sort`.
A NoCopy `Vector` sorts end to end today, written from outside std.

**The `sort` half is UNBLOCKED as of Aug 20**: it was gated on DF-216b, whose
fix (design 239 — `Comparable`/`Equatable` take `other: &Self`) landed, so a
borrowed comparison is legitimate rather than standing on the hole. The closure
half already landed. What remains is `_greater_at` and the `sort`/`sort_by`
extension's bound.

- **DF-216a — ICE: any closure naming `self` inside a method** — **FIXED**
  (design 216 unit 1). A closure body may name `self`, captured BY BORROW like
  the reference a receiver is, non-escaping only. Ruling, the DF-216d hole it
  uncovered, and the one gap left open are in the brief.
- **DF-216d — an escaping closure capturing a `&T`/`&var T` PARAMETER dangled
  silently** — **FIXED** with 216a, by the same predicate. Found by the DF-216a
  ruling probes: it compiled to a raw pointer into a dead frame with no
  diagnostic, at the one site not enforcing the spec's own no-escape rule.
- **DF-216g — a closure naming `self` inside a SUSPENDING method ICEd** —
  **FIXED** (design 218 stage 3). It needed the ruling it asked for: `__recv`
  holds a POINTER to the receiver, the closure wants to BORROW through it, and
  Saw has no local reference binding to materialize a borrow into — so the
  transform's value-snapshot answer contradicted design 216's borrow ruling and
  could not work for a NoCopy receiver at all. The frame vocabulary's
  `UnsafeRef<T>` is the value that carries a receiver borrow into an env: the
  frame holds one as `__recv`, the capture mints a second with `copy()`, and
  `deref()` lends the referent as a place. `[&self]` / `[&var self]` is the
  spelling a user writes for the same capture. Pin flipped:
  `examples/closure_captures_self_suspending.saw`; conformance rows R38-R42.
- **DF-216f — CLOSED (Aug 17), and the filing's axis was wrong.** It read as
  parameter-versus-return (`other: &Self` fails, `-> Self` works). The real
  axis is TOP-LEVEL versus NESTED: every site that substituted `Self` tested
  `t.kind == TypeKind.SELF` at the ROOT and nowhere else, so a bare `Self`
  resolved in EITHER position and a `Self` under any constructor resolved in
  NEITHER — `-> Self?` and `-> (Self, Int)` were broken on the side the filing
  called working, which the matrix probe caught before the fix was written.
  `_substitute_self_type` is the one recursive substitution, its docstring
  naming its five entry points (registered parameter types and return type; the
  body-side binding and expected return; a parameter default's expected type).
  Non-mutating, rebuilding through `dataclasses.replace` so a reference's
  mutability, a tuple's field names and an array's length ride along. The
  body-side sites also WRITE BACK, as the module-qualifier case beside them
  does, because codegen mangles the parameter off the AST — without it
  `&Vector<Self>` emitted `Vector$2$$Self$GlobalAllocator` against the caller's
  `Vector$2$Counter$GlobalAllocator`. Matrix:
  `examples/self_type_signature_positions.saw` (12 rows: bare/`&`/`&var`/
  optional/`Vector<>`/tuple/array parameters, bare and nested returns, a static
  method's parameters, and an ENUM extension), plus
  `examples/trait_self_parameter_conformance.saw` for the thing a substitution
  fix can break — a requirement written with `Self` and an impl written either
  way still match. PIN flipped:
  `examples/self_type_in_extension_parameter.saw`. Gated on suite +
  `sos_runner` both arches.
- **DF-216r — CLOSED (Aug 17): a generic extension has TWO `Self`s, and
  DF-216f only had one.** The filing framed it as "the `self_type_context`
  question", and the answer turned out smaller: nothing about substitution or
  codegen changes, only what `Self` DENOTES in a WRITTEN position.
  `_ext_self_type` answers for the RECEIVER and is deliberately argument-free
  on a generic extension (`Wrap`, not `Wrap<T>`) — naming the extension's own
  parameters as arguments makes a payload binding and a `T` parameter resolve
  through different routes to two `T`s that do not unify, and codegen names the
  concrete monomorphization from `self_type_context`. `_ext_written_self_type`
  (typechecker/registration.py) is the second answer: the extension APPLIED TO
  ITS OWN PARAMETERS, built and resolved exactly as the hand-written `Wrap<T>`
  annotation is (a bare name with bare-name arguments through `_resolve_type`,
  so design 144's identity rewrite and the type-parameter classification both
  run — composing the SawType by hand instead produced a type that PRINTED
  `Wrap<T>` and compared unequal to the one a constructor yields). Written
  positions take it; the receiver keeps the old spelling; the receiver's type
  arguments then substitute it at the call site through machinery that already
  existed. `_self_type_is_substitutable` survives as the BACKSTOP for the one
  shape the helper declines — an extension with a CONST parameter, where a
  parameter is a value and not a type argument this can spell abstractly.
  One thing the fix had to add beyond the denotation: a top-level written
  `Self` is now WRITTEN BACK onto the AST (parameter and return alike) when the
  two `Self`s differ. The nested case already did, for the reason recorded
  beside it — codegen mangles the annotation off the AST — and a top-level one
  needed no write-back while extensions were non-generic, because codegen
  resolves a bare `Self` through `self_type_context`. Inside a generic
  extension it does not, and `-> Self` left a `Self` in the monomorphized
  signature that surfaced at the CALL SITE as `internal compiler error: Self
  type used outside of extension context`. Tests: PIN
  `examples/self_type_in_generic_extension.saw` FLIPPED, plus the matrix
  `examples/self_type_generic_extension_positions.saw` (`&Self`, `Self` by
  value, `Self?`, a bare `-> Self` returning a constructed value, `-> Self?`,
  and an ENUM extension). `examples/trait_self_parameter_conformance.saw` — the
  named thing a substitution fix can break — stays green, as do
  `self_type_signature_positions.saw` and `self_type_in_extension_parameter.saw`.
- **DF-216h (COMPILER, filed Aug 17 by DF-216r's matrix; NOT a `Self` bug): an
  extension that RENAMES its struct's type parameter never substitutes it.**
  `struct Pair<A>` + `extension Pair<U> { func agree(&self, other: &Pair<U>) }`
  reports ``argument `other` expects `&Pair<U>` but got `&Pair<String>``. The
  HAND-WRITTEN spelling is the repro — `Self` behaves identically because
  DF-216r's fix makes it mean exactly that spelling — so this is not about
  `Self` at all: the call site builds its substitution map by zipping the
  STRUCT's declared parameter names against the receiver's type arguments
  (`expressions.py` `_check_method_call`, `type_subst`), and a renamed
  extension parameter appears under no key in it. Everything works as long as
  the extension repeats the struct's own parameter NAMES, which is why this has
  gone unnoticed. Mechanism (obligation 4): the same zip appears at several
  call-shape sites (instance, overloaded instance, static, overloaded static),
  so a fix is a funnel over "what does this receiver bind the extension's
  parameters to" rather than a patch at one arm. No pin filed — the matrix
  records the row it does not cover, with this number at the line.
  ASSESSED Aug 20 (design 239 unit 1a's rider check, re-probed
  `.build/scratch/p216h.saw`): NOT DF-239a's mechanism and not a substitution
  WALK at all. `_substitute_self_type` and `SawType.substitute` both rebuild a
  reference correctly; what is wrong is the MAP they are handed —
  `expressions.py:9223-9226` keys `type_subst` by `struct_info.type_params`, the
  STRUCT's declared names, so a renamed extension parameter is a key that was
  never inserted. Fixing it means plumbing the owning EXTENSION's parameter
  names onto the method symbol and agreeing with codegen's mangling, which is
  where the design surface is (does a renamed parameter participate in the
  monomorphization key?) — so it stays its own dispatch.
  **STATUS: CLOSED Aug 21 (small-fix batch).** The design question answered
  itself: a renamed parameter does NOT enter the monomorphization key, because
  an extension re-declares its type's parameters POSITIONALLY — the alias and
  the declared name denote the same position, so the key stays the type's and
  the alias is a second binding of it. `ast_nodes.ext_param_aliases` is the ONE
  definition of which positions rename (beside `specialization_key`, and for
  its reason: the typechecker and codegen have to agree or a signature that
  type-checks fails to monomorphize). Four consumers, named in its docstring:
  the typechecker's definition-side rename (`_ext_rename_subst`, so the BODY
  reads the type's storage in the extension's names — the half the filing did
  not have, and the reason `func firstval(&self) -> U { self.first }` reported
  ``should return `U` but returns `A` `` before any call site was involved);
  the call-side `_receiver_type_subst`, the funnel over all four call shapes
  the entry asked for, carried on a new `FunctionSymbol.owner_type_params`; and
  codegen's two monomorphization sites
  (`_monomorphize_single_extension`, `_ensure_monomorphized_generic_method`).
  OBLIGATION-4 PROBE, all compiled + run: `Self` in a renamed extension at
  every position (`&Self`, by value via the hand-written `&Pair<U>`, `Self?`, a
  bare `-> Self`, a static's `-> Self`) — the DF-216f/r work HOLDS, and what
  was broken was the map it was handed, exactly as the assessment said — plus a
  field read typed by the renamed parameter, a method-level generic beside it,
  a PARTIAL rename (position 0 renamed, position 1 kept), a BOUNDED rename, and
  a generic ENUM extension. PIN: `examples/renamed_extension_type_param.saw`
  (ten rows); `examples/self_type_generic_extension_positions.saw`'s
  "NOT a row" note now points at it. Docs: LANGUAGE_SPEC extensions section +
  the saw-lang skill's `Self` bullet. Gated suite (2132 pass / 11 xfail) +
  freestanding both arches.
- **DF-216e — CLOSED (Aug 17), and it needed no new type: the ESCAPING BIT was
  missing at two positions.** The filing read the acceptance as a position
  heuristic that could not tell "the callee RUNS this closure" from "the callee
  STORES it", and concluded it wanted the non-escaping parameter TYPE design 21
  lists as future work. The language already has that type — a function type is
  non-escaping only at the TOP LEVEL of a parameter and escaping everywhere
  else — and `_check_closure` already reads it (`target_escaping`). What was
  wrong was the stamp: `_stamp_escaping_roles` walked OPTIONAL/TUPLE/ARRAY/
  STRUCT and **not REFERENCE**, so nothing under a `&var Vector<() sync -> Int>`
  parameter was ever visited; and a CONSTRUCTOR writes its generic arguments in
  an expression, which no declared-type walk reaches, so
  `Vector<() sync -> Int>()` bound an element type reading non-escaping by a
  second route. Both stamp now (`types.py` `_stamp_escaping_roles`,
  `expressions.py` `_check_struct_init`). Sweep (obligation 4) probed the five
  storage positions design 216 names: returned, `let`-bound, struct-literal
  field and `&var`-field store already refused; the two ELEMENT stores were the
  hole, and they are the two the fix closes. Consumer sweep: over 1997 tests the
  contract flip changed exactly one thing, a DIAGNOSTIC rendering — K02's
  non-Send local is now `Vector<() sync escaping -> Int, GlobalAllocator>`,
  which is what the annotation spelling always printed. Pin flipped:
  `examples/escaping_closure_borrow_capture_stored.saw`; companion
  `examples/escaping_closure_borrow_capture_local_container.saw`; conformance
  rows R43-R44.
- **DF-216b — SOUNDNESS: the comparison operators bypass the transfer
  checkpoint.** `a.compare(b)` on a NoCopy type is correctly refused; `a > b`,
  the same call, COMPILES. The operator passes the by-value `other` as a
  borrow, so a conformance that exercises its declared right to `move other`
  deinits a value the caller still owns — three comparisons of a two-element
  vector print FIVE deinits, from fully safe code with no `unsafe` at the call
  site. The DF-132a shape at the operator lowering. Two fixes wanted together:
  the missing check (one rule, two entry points — obligation 1), and
  `Comparable`/`Equatable` taking `other: &Self`, which closes it by
  construction and is what makes NoCopy comparison legitimate. **Blocks 216's
  `sort` half; the `map`/`each`/`fold` half is independent.** Core trait
  signature change, so its own brief.
  **STOPGAP LANDED** (design 216 units 1-2): the operator is refused where the
  operand is ExplicitCopy/NoCopy AND the comparison transitively reaches a
  hand-written body — six of the seven positions, conformance rows C01-C06 +
  C11, consumer sweep clean. STILL OPEN: the `other: &Self` brief, and with it
  TWO positions the stopgap does not reach, both pinned XFAIL — row C07 (a
  generic body, checked once with `T` abstract, so the operand never reaches
  the gate) and row C12, an EIGHTH position the class sweep missed: an
  **ImplicitCopy** operand is over-released too (the sweep probed NoCopy
  throughout, and the tier carve-out rests on a retain the lowering does not
  actually perform — 200 comparisons SIGTRAP on a heap String). See the brief.
  (C07 was later FIXED by design 219's wave C; C12 remains the live hole.)
  **RULED Aug 20 (user): `other: &Self`** — the by-construction closure, over
  retain-at-lowering and blanket refusal. Design 239's brief
  (designs/239-comparable-by-reference.md) is the plan of record; queue slot
  after 236 lands, before 235.
  **STATUS: CLOSED Aug 20**, design 239 units 1c+2, branch `design-239`.
  `Equatable.equals(&self, other: &Self)` and
  `Comparable.compare(&self, other: &Self)` landed; the stopgap is DELETED
  (`_consuming_comparison_conformer` and its transitive walk,
  `_refuse_consuming_comparison`, `_report_consuming_comparison`,
  `_comparison_type_name`, design 219 wave C's `_tier_cmp_acc` accumulator with
  its propagate/discharge arms, and the `comparison_requirements` AST
  annotation), because no transfer exists for any of it to guard. A conformance
  must now mirror the requirement's borrows (general rule, both directions,
  `&`/`&var`; rows C13/C14) and `move other` is the ordinary "cannot move out of
  reference". C01-C08 and C11-C12 flipped to positive rows; C09/C10 were the
  controls. Corpus migration was the four example types the sweep predicted plus
  one call site — `String.equals`/`compare` stayed by value, and the brief's
  *What the build found* says why. See that section for the two other
  corrections: DF-239a was misdiagnosed (entry above), and closing the
  requirement-call path fixed a pre-existing `Undefined method: Int.equals` ICE.

**Class sweeps run Aug 13 (obligation 4's first exercise; matrices + mechanism
anchors in the brief).** DF-216b IS a class: SEVEN unsound positions
(`>`-family, `==`/`!=`, match guards, `@synthesize` memberwise, enum payload,
tuple, generic bodies under bounds) — one mechanism, the operator path never
builds a call node, so the stopgap funnel is `_check_binary_op`'s trait gating
and the `&Self` signature change closes the whole matrix by construction.
DF-216a is NOT a class: one missing `SelfExpr` arm in the closure-capture
funnel (`collect_names`), every other binding kind probed green; a second small
entry point at the capture-list grammar. **Corrected by the landing:** the arm
had a second CONSUMER the sweep did not look for — place lowering hoists a place
write's RHS into a synthesized closure, so DF-169f was the same missing arm
reached from the compiler's own side, and fixing 216a flipped its pin to XPASS.
The lesson for obligation 4: enumerate a funnel's CALLERS, not only the source
spellings that reach it. The sweep also found:

- **DF-216c — REFRAMED Aug 18: a generic STATIC never instantiates its type
  parameter; generic INSTANCE methods work on every spelling.** The original
  filing ("generic METHOD inference fails") was probed with self-less
  methods — which are STATICS, called through an instance, a spelling
  DF-217q has since ruled a refusal. Probed with `&self` written: labeled,
  positional, explicit and two-param inference all PASS — the instance half
  was fixed somewhere in the DF-217e/q call-path work, and
  `examples/generic_method_type_arg_inference.saw` is now the PASSING
  regression test for it. The static half remains broken and is the real
  finding: every type-spelled generic static call refuses with an
  UNSUBSTITUTED `U` (``argument `other` expects `U` but got `Int64``) —
  neither inference nor an explicit `<Int64>` substitutes on the static
  path — and the defaulted zero-arg face ICEs (DF-217d's re-spelled pin,
  `Undefined static method`). PIN:
  `examples/generic_static_type_arg_inference.saw` (XFAIL, all four call
  shapes). Design 236 (the required `static` keyword) names this path but
  does not fix it.
  ASSESSED Aug 20 (design 239 unit 1a's rider check, re-probed): NOT DF-239a's
  mechanism. Located precisely, both halves. TYPECHECKER:
  `_check_static_method_call` (expressions.py:9918-9930) builds its `type_map`
  from the RECEIVER's explicit type args and the STRUCT's type params ONLY —
  the instance path's method-type-param block (`_solve_call_type_args` +
  `_check_type_param_bounds`, expressions.py:9435-9488) has no counterpart
  there, so the method's own `U` is never bound by inference OR by an explicit
  `<Int64>`. CODEGEN: `_generate_static_method_call` (calls.py:2511-2557)
  monomorphizes the STRUCT for `Vector<Int>.f(...)` and stops — no
  `_ensure_monomorphized_generic_method`, no `method_type_args` in the mangle,
  which is the `Undefined static method` DF-217d reports. So the fix is a
  monomorphization path that does not exist rather than a check that was
  skipped, and it wants its own dispatch. DF-217d rides it unchanged.
  **STATUS: CLOSED Aug 21 (small-fix batch), and DF-217d closed with it.**
  Both halves landed as the assessment named. TYPECHECKER: the instance
  path's method-type-param block became a FUNNEL,
  `_fold_method_type_args(expr, method_info, type_subst, self_offset)`
  (expressions.py), whose docstring names its two entry points —
  `_check_method_call` at `self_offset=1` and `_check_static_method_call` at
  `self_offset=0` (a static has no `self` slot) — and says why the overloaded
  twins are not among them (they bind theirs inside `_resolve_overload`). The
  instance path is now a three-line call to it, so the two arms cannot drift.
  CODEGEN: `_generate_static_method_call` (calls.py) requests
  `_ensure_monomorphized_generic_method` for `expr.type_args`, rebuilding the
  receiver SawType from the PRE-monomorphization struct name plus its
  substituted type args, and mangles with `method_type_args`; the instance
  path's `_compose_overload_suffix` fallback came along so a generic
  overloaded static resolves to its specialized symbol. SWEEP (obligation 4),
  all compiled + run: a bounded `<U: Named>` static, a two-param static
  (inferred and explicit), a `-> U` static, a generic static on a GENERIC
  struct (`Holder<Int>.mix<U>`), a non-generic static on a generic struct
  (control), and an ENUM static. Negatives are clean at the call: bound
  violation, `is not generic but was called with type arguments`, and
  too-many-type-arguments. PINS FLIPPED:
  `examples/generic_static_type_arg_inference.saw` (all four call shapes) and
  `examples/generic_method_default_type_and_value_param.saw` (DF-217d).
  Gated suite (2131 pass / 11 xfail) + freestanding both arches.

## Design 219 — generic tier requirements (LANDED Aug 14; the DF-217i fix)

Brief: `designs/219-generic-tier-requirements.md`.

**WAVE C LANDED (Aug 14) — the DF-217i fix itself.** Requirement inference at
the definition, discharge at the call, the two per-instance declaration
derivations, and the public-declaration rule taken as HARD-REQUIRE. Suite
1794/31 -> 1813/27: fourteen conformance rows, five pins flipped —
**DF-217i, DF-217j, DF-217k, DF-217q and C07 (DF-216b's seventh position) are
FIXED**, and 218's DF-217j enforcement dependency is discharged
(`Slot<TaskGroup>` is a compile error). The public-generic fix list came back
EMPTY. Details, including the C5 Sync verdict (no finding) and the false
positive the public rule found in C1's own return handling, in the brief's
WAVE C LANDED note.

**WAVE A LANDED (Aug 13) — the two self-contained ratified rules, ahead of the
collapse/inference waves.** A1: a copy-policy `copy()` must be `sync`, checked
once at the conformance (**DF-217r FIXED at the conformance**; the ALLOC half
stays documentation + an optional `-W`, per the ruling). "Provably sync"
counts — `sync` is a declared negative effect, so std's unmarked hooks pass
unchanged. A2: `move ptr[i]`, the pointer-place transfer spelling — the
carve-out lives in the place machinery keyed on the place's ROOT kind, design
35 intact for every safe place, and the unspelled owning read now names the
spelling in its fixit. std's five pointer-read transfer sites spell it (census:
46 reads, 41 trivial, ZERO peeks). Conformance rows K27, U28, U29, V31.
**DF-219a (LEAK) — `Vector.pop` leaked one reference per popped refcounted
element**: its read sat in Optional-tail position, where the checkpoint judged
it a copy and stamped a retain while the vector released nothing. Found by
A/B'ing the sweep's IR, FIXED by the spelling, pinned by
`examples/vector_pop_refcount_exact.saw`.

**DF-219b (found by wave B, pre-existing, unfiled until now) — a suspending
call in a nested/expression position INSIDE A CLOSURE BODY is refused**
(`yield_now()` directly in a `map` transform closure; the ANF hoist does not
descend into closure literals). Confirmed pre-B1 by stash-and-reproduce.
Workaround: a suspending helper (documented in
`examples/vector_closure_suspending_transform.saw`). A new POSITION FAMILY
for the design-120 matrix — the S2 sweep never probed inside closure bodies;
joins the 120-matrix fix brief (DF-217f/g family) as its own row set.

**DF-219c (BOGUS-REFUSAL, found by wave C's C5 probe; pre-existing) — the
spawn CAPTURE audit is not bound-aware, so a `<T: Send>` bound does not let a
generic body spawn a closure capturing a value of type `T`.**
`spawn { ... a1 ... }` where `a1: Arc<T>` inside `fan_out<T: Send>` is refused
`cannot `spawn`: captured `a1` of type `Arc<T>` is not `Send``, identically
with and without the bound: the capture audit falls through `is_send`'s
opaque-type-parameter path, which returns False for any unresolved `T`. The
spawn RESULT position has a `_names_type_param` bypass for exactly this reason
(`expressions.py`); captures have none. Not a soundness hole — it over-rejects
— but it makes `Send`-bounded generic fan-out unwritable, and the asymmetry
between two positions of one rule is the obligation-1 shape. Evidence:
`.build/scratch/wavec/probeA3`/`probeA4`. Adjacent, not filed as its own DF:
the diagnostic for a non-Sync `Arc` payload says "not `Send`" (true, via
`Arc<T: Send + Sync>`) where the actionable fact is "not `Sync`" — recorded in
conformance row K31.
**STATUS: CLOSED Aug 21 (small-fix batch), adjacent diagnostic included.**
`namespace.send_check` takes the enclosing generic's DECLARED bounds as the
`assume` pair `_send_sync` already consulted for design 186's conditional
headers — no new mechanism, the existing one reached from a second caller. The
typechecker builds it in `_bounds_assumption` (None outside a generic, so every
non-generic query stays byte-identical) and the spawn capture audit passes it.
An UNBOUNDED `T` still refuses, and the bound is enforced at the CALL by
`_check_type_param_bounds` — probed on BOTH soundness axes: `<T: Send + Sync>`
at a Send-but-not-Sync `Cell` and `<T: Send>` at a pointer-carrying `Raw` are
each refused at the call site, naming the bound. POSITION MATRIX, compiled and
run: closure-capture spelling at a bare `T`, `Arc<T>`, `Vector<T>` (`[move v1]`)
and `T?`; the ARGUMENT spelling is UNREACHABLE from a generic body by an
earlier gate (``group.spawn(...)` of a generic function requires concrete type
arguments``), which is the same fact K31 already records, so it is a row with
an answer rather than a gap. ADJACENT DIAGNOSTIC FIXED at the funnel, so all
five SEND_POSITIONS get it: `namespace.unmet_conditional_bound` names the first
CONDITIONAL-assertion bound an instantiation fails and `thread_safety_note`
appends it, then recurses into the payload — K31's message now reads
``... `Arc` is `Send` only when its payload is `Sync`, and `Cell` is not — that
is the bound to satisfy. `Cell` carries an interior cell ...`` and the row
asserts the new sentence. CONFORMANCE (obligation 3): row K74 owed and added
(authored as K72; renumbered at integration — the parallel 218s/218w branch
claimed K72/K73 first) —
the accept file plus TWO refusal files, since a refusal is a whole compilation
and the soundness of the relaxation lives in them. Docs: LANGUAGE_SPEC's spawn
entry + the saw-lang skill's spawn bullet. Gated suite (2135 pass / 11 xfail) +
freestanding both arches.

**WAVE B LANDED (Aug 13) — the tier collapse and the vocabulary, ahead of
wave C's inference/discharge.** B1: design 216's closure rework (`&T`
elements, no copy bound). B2: `Copy` becomes the merged silent tier and only
that, bounds asking the tier rather than a declaration. B3: the trait
declarations, the effect-matching rule and the bounds. B4: the corpus-wide
`ImplicitCopy` -> `Copy` rename, `trait ImplicitCopy` deleted, a teaching hint
at every unknown-trait position, docs on three words. B5: prefix `*`, the
pointer place spelled. Details in the brief's WAVE B LANDED note.

The ruling (SIMPLIFIED
Aug 13): BINARY requirement inference — a body either copies `T` silently
(requires trivial/ImplicitCopy, inferred) or does not (move-only, any tier);
`.copy()` is NEVER inferred — it requires a declared `<T: ExplicitCopy>`
(rare by design); the legacy `T: Copy` bound RETIRES from generic signatures
(it admits ExplicitCopy args into silently-copying bodies — the 9d
miscompile). Call-site DISCHARGE rejection + definition-time
declaration-coverage checking. **VOCABULARY UNIT RULED (Aug 13): the tier
system's final form is Copy / NoCopy / ExplicitCopy-the-TRAIT** — `Copy`
merges trivial+ImplicitCopy (the word `ImplicitCopy` retires); a declared
Copy conformance is an assertion (empty) or the retain hook (with body —
the visible-stdlib mechanism Arc is built on, kept by ruling: a heavy
user `copy()` is a declared-and-documented performance choice, not banned);
ExplicitCopy's tier dissolves into move-only, its trait + `@synthesize`
derivation survive unchanged, blanket-satisfied by Copy types. Tier-aware bounds unify with
tier derivation (probe-found gap: today `T: ImplicitCopy` rejects Int AND
auto-tier structs). THE NAMED TRADE: body edits can tighten an inferred
requirement — mitigated by declared bounds as the contract, with a
public-generics-must-declare ruling wanted at dispatch. S1 row 9d's
ExplicitCopy miscompile becomes a clean refusal; C07's funnel falls out of
discharge; DF-217j/k get the per-instance declaration-derivation extension
(unit 3), which also discharges 218's Slot<TaskGroup> dependency. Owes its
obligation-2 consumer sweep before dispatch. Gates 218 stages 1-2.

- **DF-218a FIXED (Aug 13) — presence is TIER-INDEPENDENT at every
  spelling.** `if let _`/`guard let _` over an UNCONDITIONAL lend of an
  optional-TYPED place (`Slot<T?>.value()`) was judged a value read, so a
  NoCopy payload could not be presence-tested at all there and a Copy tier
  paid a retain. Fixed as design 218's ELABORATION PRINCIPLE asked — an AST
  desugar to `is_some()`, not a classification patch — in three commits:
  `Optional.is_some()`/`is_none()` as compiler-implemented tag-only reads,
  the desugar in `place_uses._presence_condition`, then the matrix and docs.
  Scope was decided by probe and is SPLIT; the conditional lend keeps its own
  lowering because the desugared spelling is not expressible there at all.
  The split, the placement decision and the probe evidence are in the design
  218 brief's DF-218a section.
  PIN: `examples/conformance/O14_presence_test_is_tier_independent.saw`
  (row O14) + `examples/optional_presence_unconditional_lend.saw` +
  `examples/optional_presence_tag_only.saw`

- **DF-218b (BOGUS-REFUSAL, found probing DF-218a, pre-existing and
  unrelated to its fix). `<place>.take()` on an optional-typed place is
  refused, and the diagnostic names a synthesized binding.**
  `s.value().take()` on a `Slot<Res?>` reports ``cannot call `take()` on
  immutable variable `__p76` `` — a compiler-internal window parameter in a
  user-facing message, with a `let`-vs-`var` hint pointing at nothing the
  author wrote. MECHANISM: `place_uses._method_mutates` picks the window
  flavor by looking the method up on the receiver's owning STRUCT
  (`_method_owner_name` -> `ns.lookup_method`), and an OPTIONAL receiver has
  no struct owner, so every `Optional` method reads as non-mutating and the
  window opens SHARED. `take` is `&var self` and needs an exclusive one.
  SIBLINGS (obligation 4): the mechanism reaches exactly the
  compiler-implemented `Optional` methods, since those are the ones with no
  struct owner to look up — `take` is the only mutating member today, and
  `is_some`/`is_none` are `&self` so a shared window is correct for them.
  Any future `&var self` addition to `Optional` lands in the same hole. Two
  fixes are owed and they are separable: teach the flavor decision about
  `Optional`'s own methods, and stop synthesized binding names reaching a
  diagnostic. Not scheduled; moving a payload out of a slot's optional
  element has the `Slot.take()`/`Optional.take` spellings meanwhile.

- **DF-218c — the driven-path channel refusal is channel-blind and anchored
  at 0:0.** S10's probe (218a ruling 11a): ExplicitCopy/NoCopy channel
  elements are REFUSED on the driven receive path (`cannot copy value of
  type Vector<Int...>` at `file:0:0`, no mention of channels; blocking
  `recv()` works) — safe-by-accident, but a live diagnostic bug and an
  expressiveness hole until 218 stage 1's S10 feature flip. No rescue
  spelling exists (`move ch.receive()` misfires with a wrong noun).
- **DF-218d (ICE, sawfuzz-oracle class) — a value-`if` statement followed by
  a line beginning with `-`** dies `internal compiler error (BinaryOp):
  'NoneType' object has no attribute 'type'` (the value-if binding parsed
  as a subtraction LHS). Repro `.build/scratch/probe_s10/ice1.saw`; a `let`
  in the same position works. Pin + sawfuzz_known entry owed at the next
  pin batch. Sibling wart, same parse family: `move <method call>` in
  argument position is a parse error rather than a `move` diagnostic.
- **DF-218e (BOGUS-REFUSAL, pre-existing) — a GENERIC function driven as a
  root cannot contain a nested suspending call.** `g.spawn(gworker(7))`
  where `gworker<T>` calls a suspending `mk()` reports `undefined function
  mk` at the author's own line, then an undefined-variable cascade for the
  binding it feeds.
  **RE-FILED Aug 21 by design 237's unit-1 census, which EXITED it from that
  brief.** It is not the ANF hoist's entry set reached through a monomorphized
  body. MECHANISM, with compile evidence: the error is emitted by the
  POST-TRANSFORM RE-CHECK (`-v` places it after "Applied coroutine transform;
  re-checking…"); a suspending nested callee is CONSUMED by the transform
  (frame + driver, and `program.functions` drops the plain function), which is
  why the non-generic twin compiles — its own body became a frame, so nothing
  names `mk` any more; a GENERIC declaration also leaves its un-transformed
  TEMPLATE in the program, and that template still names it. It is the
  template and not the instantiations: driving one generic at TWO type
  arguments produces exactly ONE `undefined function` error.
  **The boundary is WIDER than the original filing said** — the AMBIENT-entry
  cell fails identically now, so this is not the spawn path's handling of a
  generic root but every driven generic body with a nested suspending call.
  Still working: a generic body whose only suspension is `yield_now()` (sweep
  S1 row p08c), and the non-generic twin.
  Obligation 4 sweep owed at fix time: generic roots that are METHODS, MT
  spawn, a generic root whose nested callee is itself generic, and any other
  way a surviving template can name a declaration the transform consumed.
  **CLOSED Aug 21 (design 218 unit 2 stage E, branch `design-218-u2`) —
  CONSUMPTION SYMMETRY, per 218b ruling 5.** A generic TEMPLATE whose body
  names a consumed callee is itself consumed at the splice, to a fixpoint.
  Sound because every instantiation of such a template is unconditionally
  suspending and every driven use was promoted to a concrete function before
  the transform ran, so no sync instantiation survives for codegen's late
  monomorphization to ask for; a template that suspends only CONDITIONALLY
  (through a type-parameter method) names no consumed callee and is
  untouched. Obligation-4 sweep RAN, all cells compiled and run: spawn root,
  ambient entry, nested callee itself generic, two type arguments, a generic
  METHOD root, MT `threads: 2`, plus the two controls (a `yield_now()`-only
  template and one with a purely sync instantiation).
  PIN FLIPPED: `examples/coro_generic_spawn_root_nested_suspending_call.saw`;
  the `DF-218e-2026-08-14` row retired from `tools/corodiff_known.txt`

- **DF-218r — CLOSED (Aug 21, design 218 unit 2 stage 0).** A sync loop-body
  local was never released on the `break` or `continue` edge (`return` inside
  the loop released correctly). Mechanism, probes and the class statement:
  designs/218b-scope-end-spec.md. FIX: `_cleanup_to_loop_boundary`
  (codegen/loops.py), a funnel naming its two entry points, over a fourth
  `loop_stack` element — the cleanup-stack depth recorded at loop entry,
  BEFORE the loop's own bindings register, so a `for`'s design-65 owning loop
  variable is inside the unwind. `break` also drains its own statement
  temporaries, as `return` does. PIN FLIPPED:
  `examples/loop_exit_releases_body_local.saw` (five cells) + conformance row
  K71. Gated suite + freestanding both arches + corodiff --quick.
  CLASS STATEMENT CORRECTED (Aug 21, by 218b's own SC10 probe): the entry
  claimed `break` and `continue` were the only nonlocal exits that are not
  returns. They are not — a `try { } catch { }` BLOCK's error edge is a
  THIRD, and it leaks the try body's locals. Filed separately as DF-218v,
  since the fix is in codegen's try lowering rather than in the loop stack.

- **DF-218s (DEINIT-ORDER, PRE-EXISTING; filed Aug 21 by the 218b spec
  probes) — CLOSED Aug 21 (branch `df-218s-218w`, stage 1).** A
  driven body's done path runs `release()` (reverse declaration order over
  frame fields) BEFORE the lowered return's cleanup of surviving real locals,
  inverting the sync twin's scope-LIFO order. Stage C landed E-RET — the open
  scopes' frame fields clear innermost-first ahead of `release()` — which is
  the ordering fix AMONG FRAME FIELDS. The INTERLEAVING the pin measures is
  not reachable from the transform: codegen's `_cleanup_all_scopes` runs at
  the lowered `return Poll.Done`, after every statement the transform can
  emit, so no emission of its can land after a real local's drop. Three
  candidate fixes, each a ruling (release from the DRIVER on Done; route
  nested returns through a shared done STATE; force frame residency on the
  real locals of a block containing a `return`) — written up in
  designs/218b-scope-end-spec.md's landing note.
  PIN: `examples/coro_done_path_releases_in_scope_order.saw` (XFAIL, carries
  the mechanism and the containment fact that bounds it)
  **RULED Aug 21 (user): OPTION 3 — forced frame residency.** The owning
  real locals of any block containing a `return` become frame-resident via
  the `force` mechanism the try/catch split already uses, so E-RET's scope
  walk orders every owning local and sync-LIFO holds by the containment
  argument (a frame-resident scope is always an ancestor of a real-local
  scope). The driver option was rejected for resurrecting the
  reverse-declaration coincidence stage C retired; the done-state option
  for being wrong under an enclosing non-spanning loop. Frame-size cost
  accepted on the tag-cost precedent; bench timing is the watch item.
  SCHEDULED with DF-218w (one dispatch — see [QUEUE]).
  **LANDED as ruled.** `_collect_frame_locals` gained the second residency
  reason, scoped three ways: OWNING only (`_type_owns`, which reads the KIND —
  `_enc_owns`'s encoding answer calls an `UnsafePointer` owning, and forcing
  one resident made `net_cancel_parked_mt`'s spawned frame non-`Send`),
  RETURN-CONTAINING blocks only, and bodies that SUSPEND only (a spawn root
  with no suspension has no frame-resident scope for the inversion to need).
  `_lower_block_in_place` became a SCOPE with it — a forced field can sit in a
  block the CFG walk never splits, so the scope stack follows the in-place
  descent and E-RET sees the same stack a split block gives it; E-FALL closes
  it on the ordinary path. PIN FLIPPED, extended with the obligation-4 matrix
  (nested `if`s, a `match` arm, a `while` body, a sibling scope).
  RESIDUES, both bounded and both intra-statement timing rather than a leak:
  (a) a PATTERN binding live at a `return` — a non-spanning `match` arm
  payload, a non-split `if let`/`guard let`, a non-spanning `for`'s variable —
  is not forced, because nothing in the in-place lowering stores one into a
  field, so a field for it would never be written; (b) a block with a VALUE
  (`final_expr`) takes no in-place E-FALL, since a clear appended to its
  statement list would run ahead of the expression that reads the binding.
  THE WATCH ITEM, measured rather than estimated. The BENCH lane cannot see
  this change at all — `devtools/bench/warehouse/warehouse.saw` contains no
  `yield_now`/`spawn`/`TaskGroup`/`__saw_drive`, so the transform never runs on
  it (min 385 ms at the terminal battery, on a three-agent machine, and not
  comparable to a quiet-machine figure either way). The cost the ruling
  accepted is FRAME SIZE, so that is what was counted: `--emit-frame-layout`
  over the 110 `examples/coro_*.saw` files, 386 frames, summing each frame's
  extent. 46390 -> 46606 bytes, **+216 bytes total, +0.47%** (same 386 frames
  and the same 2 skipped files on both sides — probe:
  `.build/scratch/probe_frames.py`).

- **DF-218t (ICE, PRE-EXISTING; found Aug 21 while probing DF-218r's
  break-with-a-value edge)** — a VALUE-position loop whose result type is not
  an integer dies in codegen. `let out = while true { let s = "made-{i}"; …
  break s }` reports `internal compiler error: LLVM IR parsing error …
  integer constant must have integer type`, and the same shape at a NoCopy
  struct reports `internal compiler error: 'int' object is not iterable`.
  MECHANISM (one, two symptoms): `_generate_while_expr_value` /
  `_generate_for_loop_value` build the `None` sentinel for the loop's
  `Optional<T>` result storage as `ir.Constant(inner_type, 0)`, which is
  well-formed only for an integer `inner_type` — a pointer gets an
  ill-typed constant and a struct makes llvmlite iterate the `0`. The
  positions it reaches are the four value-loop forms (conditional and
  infinite × `while` and `for`) at any non-integer result type; an `Int`
  result is unaffected, which is why nothing caught it.
  NOT FIXED HERE, deliberately: the shape is currently unreachable, and
  making it compile would open a path where a `break <owned local>` hands the
  loop's result out while the DF-218r scope unwind also drops it — so the fix
  owes a transfer/retain decision at the break value, not just a constant.
  No pin (an ICE pin would have to be XFAIL against an ICE, which the runner
  reports as a crash); repro in this entry.

- **DF-218u — CLOSED on discovery (Aug 21, design 218 unit 2 stage A/B).** A
  design-107 same-scope redefinition in a body the coro transform TOUCHES but
  does not make frame-resident lost its drop-at-redefinition point: the
  replaced value survived to the scope's end. MECHANISM:
  `_uniquify_bindings` (DF-151a) renames the second binding, and codegen's
  `_drop_redefined_same_scope` matches by NAME, so the pair read as two
  unrelated locals. Positions: a SPAWN root with no suspension (the plainest
  face — its locals stay codegen's), and a driven body whose locals are not
  frame-resident; a frame-resident pair takes the transform's own E-REDEF edge
  and was never affected, and an un-transformed body never renames. FOUND by
  the stage-A/B corodiff `--all` run, which reported it as a new
  DEINIT-ORDER cell (`let_shadow_rebind/before @ generic`) once the DRIVEN
  twin started dropping at the redefinition — the DF-217n unmasking pattern.
  FIX: the transform hands the pairing over on a declared
  `LetStatement.coro_redefines` annotation. RESIDUE: a DESTRUCTURING `let`'s
  leaf redefinition on the same non-frame-resident path is not covered (it has
  no single-name hand-off); exotic, not probed further.
  PIN: `examples/spawn_body_same_scope_redefinition.saw` (three cells:
  un-transformed, spawned non-suspending, spawned suspending)

- **DF-218v (SYNC LEAK, PRE-EXISTING; found Aug 21 by 218b's SC10 probe)** —
  a `try { … } catch { … }` BLOCK does not release the TRY BODY's locals when
  the body's error edge leaves for the catch. Probe
  (`.build/scratch/p_sc10.saw`, sync twin): `try { let t = Res("try-local")
  … let v = try fail_now(1) … } catch { … }` prints `in try try-local / in
  catch catch-local bad / DEINIT catch-local / after try` — no `DEINIT
  try-local` anywhere. The counts do not balance, so this is a LEAK. The OK
  path releases correctly, and so does the common propagating shape (a bare
  `try` in a Result-returning function with no catch — probed, `DEINIT held`
  fires on the error path, because that edge runs `_cleanup_all_scopes` at
  results.py:197). MECHANISM: the same one DF-218r named, at a position that
  entry's class statement got WRONG — it said `break` and `continue` were the
  only nonlocal exits that are not returns, and the try/catch BLOCK's error
  edge is a THIRD. The DRIVEN twin does not leak it; it releases at frame
  teardown, i.e. late, which is DF-217p's residue on a path the scope walk
  cannot see (the error edge is codegen's, inside the synthesized landing).
  NOT FIXED HERE: the fix is in codegen's try/catch lowering (design 196's
  territory) and has to decide what the in-flight Result owns at the jump,
  which is more than a cleanup call. Owed a pin at the next batch.
  **STATUS: CLOSED Aug 21 (small-fix batch), SYNC half.** The in-flight
  question answered itself at the site: `_generate_try_propagate` COPIES the
  error into the catch's `caught_error` alloca before it branches, so the value
  the catch receives is already out of the scopes being released and the edge
  owes nothing but the cleanup. FIX: DF-218r's own walk, WIDENED rather than
  duplicated — `_cleanup_to_loop_boundary` moved to `resources.py` beside
  `_cleanup_all_scopes` as `_cleanup_to_depth`, whose docstring now names all
  three entry points (`return` at depth 0, `break`/`continue` at the loop's
  entry depth, the catch edge at the TRY BLOCK's), with `_cleanup_all_scopes`
  delegating to it so the funnel is total. The bound is a fifth
  `_catch_context` element, recorded BEFORE `_generate_block` pushes the try
  body's scope — the same discipline as `loop_stack`'s. Statement temporaries
  drain first, then the scopes innermost-first: the sequence `return` and
  `break` already run. MATRIX, all compiled and run: both edges live at runtime
  (one DEINIT per binding per iteration — a double release would show), a catch
  that `break`s out of the enclosing loop (two different depths of one stack), a
  NESTED try/catch, a `for` inside the try body (its design-65 owning loop
  variable is inside the unwind), a catch edge beside a propagating `return` in
  one body, and the OK-path control. PIN:
  `examples/try_catch_error_edge_releases_try_locals.saw` (six cells) +
  conformance row K73, which also corrects K71's class statement. Docs: the
  saw-lang skill's scope-end bullet (three broken edges, not two) +
  `sawc/codegen/README.md`'s loop-stack note.
  DRIVEN-TWIN PROBE (asked for at dispatch): BYTE-IDENTICAL before and after —
  the same suspending shapes release at frame teardown either way, so the fix
  introduces no new divergence. What it does is change the KIND of the standing
  one, from leak-vs-late to at-the-edge-vs-late, so the residue is filed as
  DF-242a rather than left inside a closed entry.

- **DF-242a (DEINIT-ORDER, PRE-EXISTING; filed Aug 21 by DF-218v's fix)** — a
  DRIVEN `try { } catch { }` releases the try body's frame fields at FRAME
  TEARDOWN, where the sync twin now releases them at the ERROR EDGE. Probe
  (`.build/scratch/p218v_driven.saw`, the sync pin's shapes with a `yield_now()`
  in the try body): `in try try-local / in catch catch-local bad / DEINIT
  catch-local / after try / DEINIT try-local` — one release, after the body has
  finished, where sync prints `DEINIT try-local` before `in catch`. Nested
  scopes are late together and in the right order among themselves (`DEINIT
  inner` then `DEINIT outer`, both after `after nested`). Never a leak and never
  a double free; intra-body timing only. MECHANISM: exactly what DF-218v's
  filing predicted — the error edge is CODEGEN's, emitted inside the synthesized
  landing, and design 218 unit 2's scope walk is the TRANSFORM's, so the walk
  cannot see this edge to place a release on it. Same family as DF-218w (the
  transform cannot reach a cell codegen owns) and DF-218s (which ruled forced
  frame residency for the neighbouring case). NOT FIXED HERE: the fix wants a
  decision about which side owns the edge — either the transform learns to emit
  a scope-end release for a codegen-owned branch, or codegen's
  `_cleanup_to_depth` learns to clear frame fields — and that is a ruling, not a
  cleanup call. No pin (an XFAIL would have to assert the INTENDED sync-matching
  order, which is exactly what DF-218s's queued option-3 work may reshuffle);
  repro in this entry.

- **DF-218w (DEINIT-ORDER; filed Aug 21 — the NARROWED RESIDUE of DF-217p) —
  NARROWED AGAIN Aug 21 (branch `df-218s-218w`, stage 2) to the MIXED
  `case Both(v, _)` shape; the rest is CLOSED.** —
  a driven `case Has(_)` releases the discarded payload at the END of the
  match statement, where the sync twin releases it at EXTRACTION. Design 218
  unit 2 moved this cell from frame teardown to statement end and could not
  move it further: a `_` binding names no value to own, so it is in no cleanup
  scope, and sync answers that with an INLINE drop at extraction
  (codegen/match.py's consume branch, the DF-217n fix) — which the driven twin
  cannot be in, because its scrutinee is the frame TEMP the container-head
  hoist made rather than an owned local (`scrut_is_local` is false). What
  remains is intra-statement timing, one position late, never a leak or a
  double free. An arm with a NAMED binding is clean on both twins, which is
  why `match_consume` retired with the rest of DF-217p and `match_nobinding`
  did not. The fix is per-ARM emission (release the scrutinee temp at the
  START of an arm whose only payload binding is `_`), which owes a rule for
  the mixed `case Two(v, _)` shape where sync drops one field inline and the
  other at arm end while the frame temp holds the whole enum.
  PIN: `examples/coro_discarded_match_payload_released_at_extraction.saw`
  (XFAIL) + two `tools/corodiff_known.txt` rows re-filed from DF-217p's block
  **LANDED, as the per-arm emission the entry named — E-ARM.** An arm that
  claims NOTHING of the scrutinee by name (every payload binding `_`, and a
  design-63 pattern binding nothing either) releases the hoisted temp at the
  arm's START; the merge-point release survives behind it as the idempotent
  tag-drop and is still the edge for an arm that DOES bind. Both lowerings take
  it (`_split_match`'s arm entry state, `_lower_inplace`'s MatchExpr). PIN
  FLIPPED with three cells added (bare wildcard, the CFG-split arm, the
  named-binding control); BOTH ledger rows retired.
  THE MIXED SHAPE keeps statement-end timing, which is what stays open. Probed
  first, as the dispatch directed: sync drops the `_` field inline at
  extraction and the NAMED one at arm end, through two different destructors.
  The driven twin holds ONE value — the frame temp carrying the whole enum —
  and `_release_shape` releases a field whole, so there is no spelling that
  drops `b` while `v` still names `a`, and an arm-start release would free what
  `v` reads. Intra-statement timing, never a leak; corodiff cannot see it
  (`st_match_nobinding` builds the single-field `case Has(_)`), so the pin is
  the whole instrument.
  NARROWED PIN: `examples/coro_mixed_match_payload_released_at_extraction.saw`
  (XFAIL, one cell)

- **DF-218y (DEINIT-ORDER, PRE-EXISTING; filed Aug 21 by DF-218w's fix) —
  NEEDS A RULING, and the SYNC twin is the suspect half.** A multi-field
  all-`_` arm (`case Pair(_, _)`) drops its payload fields in DECLARATION
  order on the sync twin and in REVERSE on the driven one. DF-218w's E-ARM put
  both at the same POINT (the arm's start); the order is what is left.
  MECHANISM: two different destructors. Sync drops a `_`-discarded field inline
  as it EXTRACTS it, so its loop runs in binding-index order — forward. The
  driven twin releases the frame temp as one value and the enum's synthesized
  memberwise deinit is reverse-declaration, which is what design 128 states for
  every structural teardown in the language. So sync's forward inline loop is
  the only drop path in Saw that is not reverse, and the fix may belong on THAT
  side rather than on the transform's. Not decided here — the pin states parity
  at sync's order (the standing contract) and flips whichever way the ruling
  goes.
  PIN: `examples/coro_discarded_match_payload_field_drop_order.saw` (XFAIL)
  **RULED Aug 22 (user): reverse-declaration everywhere.** Forward was an
  artifact of emitting the drop where the field was EXTRACTED, never a contract;
  the match lowering conforms to design 128 like every other teardown.
  **STATUS: CLOSED Aug 22 (branch `df-218xy`, commit 2), on the SYNC side as the
  ruling directs.** FIX: the consume branch COLLECTS its `_`-discarded fields in
  binding order and drops them after the binding loop in reverse — a forward
  emission cannot spell a reverse order, so the collect-then-flush is the whole
  change. The oracle was already in the file: a NAMED binding registers into the
  arm scope in declaration order and the scope releases it in reverse, which is
  what `case Trip(x, y, z)` has always done.
  OBLIGATION-4 SWEEP (probed before and after, `.build/scratch/p218y_sweep.saw`
  + `p218y_driven.saw`; the matrix is 15 cells). A SECOND position had the same
  forward loop: `_destructure_bind`'s TuplePattern walk, which serves
  `let (_, _)`, `if let (v, _, _)` and the `guard let` twin. Unlike the match
  one it was forward on BOTH twins — the transform does not rewrite a
  destructure's leaves — so it never DIVERGED and simply disagreed with the
  language; it is fixed by the same collect-then-flush (`_destructure_bind` is
  now an entry point over a `_destructure_walk` recursion) and moved both twins
  together, introducing no new divergence. Sibling positions probed and found
  NOT to be instances: `_match_pattern`'s general design-63 wildcard emits no
  drop at all (it returns no binding, and the scrutinee is released whole), and
  the single-value discards (`let _ = e`, `if let _ = opt`, `guard let _ = opt`)
  have no order to get wrong. AFTER, every cell is reverse and the two twins
  agree: 2-field and 3-field all-`_` arms, mixed arms with the discards leading
  and trailing, and all four destructuring spellings.
  RESIDUE, unchanged and still open: the MIXED shape's driven TIMING is
  DF-218w's (the driven twin releases at statement end where sync releases at
  extraction). Only the ORDER was DF-218y's, and the mixed rows now agree on it.
  PIN FLIPPED and extended to 11 rows (the two twins that diverged, three-field
  twins, both mixed arms, all four destructuring spellings, and the
  named-binding oracle) + conformance row K77. Docs: LANGUAGE_SPEC's
  synthesized-destruction section, the saw-lang skill's Deinit bullet, and
  `tools/corodiff_known.txt`'s DF-218w comment block (which named this pin as
  XFAIL).

- **DF-218x (SYNC LEAK, PRE-EXISTING; found Aug 21 by DF-218s's
  obligation-4 sweep)** — an `if let` binding is NOT released when the
  then-branch leaves by `return`, `break` or `continue`. Probe
  (`.build/scratch/p218s_iflet.saw`): `if let p = mk_opt(n) { print(...)
  return }` prints `have p` and no `DEINIT p`; the fallthrough control and the
  `guard let` twin both release correctly. MECHANISM: the binding is not on the
  cleanup stack at all. `_generate_if_let_expr` gives it an ad-hoc alloca plus
  a drop flag and drops it INLINE at the end of the then-branch, behind
  `if owns_binding and not self.builder.block.is_terminated`
  (codegen/conditionals.py:324) — whose comment reads "return/break cleaned all
  scopes", which is FALSE for this binding precisely because it is registered
  in no scope. So every terminated exit skips it and no unwind can reach it.
  The positions the mechanism reaches were probed and it is NARROW: a `match`
  arm's payload bindings ARE registered (`_register_cleanup`, match.py:356) and
  release correctly on `return` and on `break`, and `guard let`'s binding
  belongs to the enclosing scope, so the `if let` then-branch is the only
  binding held this way. The DRIVEN twin behaves identically (probed), so
  corodiff sees no divergence and the leak is invisible to that lane.
  NOT FIXED HERE: it is codegen's if-let lowering, the same batch as DF-218v
  (both are cleanup gaps at a nonlocal exit). Owed a pin with the fix.
  **STATUS: CLOSED Aug 22 (branch `df-218xy`, commit 1).** FIX: the branch gets
  a cleanup scope of its OWN — pushed before the binding is created, released at
  the fall-through and popped-only on a terminated edge — and the binding
  registers into it through `_register_cleanup`, the same funnel every other
  owning binding uses. So `_cleanup_to_depth` gained NO fourth entry point: the
  three edges DF-218r and DF-218v widened were already sufficient, and what they
  could not reach was a binding on no stack at all. The inline drop is gone with
  the ad-hoc flag it guarded (`_register_cleanup` mints the same flag), so a
  `move` inside the branch still suppresses the drop.
  SWEEP, wider than the entry predicted — the one lowering serves FIVE
  spellings and all five leaked (probed before and after,
  `.build/scratch/p218x_sweep.saw`): `if let` + `return`, + `break`,
  + `continue`; `if var` + `return`; `while let` + `break` and + `return`
  (design 233 desugars both `while let`/`while var` to this lowering). Two
  entry claims are CORRECTED. (a) The DRIVEN twin does NOT behave identically —
  it was already right (design 218 unit 2's scope walk releases the frame
  field), so the divergence was real and corodiff missed it because no
  generator row builds an `if let` with a terminated branch; the pin's driven
  twins are now that instrument. (b) A design-63 TUPLE pattern was not a leak
  but was not right either: `_destructure_bind` registered its leaves into the
  ENCLOSING scope, so two successive `if let (a, b) = …` branches held both
  pairs at once. Pushing the scope ahead of the binding moves them in with the
  named case. Unaffected and re-probed: `if let _ = <owned temp>` (dropped
  inline at extraction, before any branch), `guard let` and match-arm payloads
  (the two controls).
  PIN: `examples/if_let_binding_released_on_early_exit.saw` (18 cells: the
  three edges, the fall-through, `if var`, `while let`, the tuple pattern, a
  `move`-out where the flag must suppress, both controls, and four driven
  twins) + conformance row K76. Docs: the saw-lang skill's scope-end bullet
  (a fourth sync leak, and the first that was a broken BINDING rather than a
  broken EDGE), LANGUAGE_SPEC's `Deinit` scope-exit paragraph, and
  `sawc/codegen/README.md`'s loop-stack note.

- **DF-246a — CLOSED (Aug 24, branch `harness-doctrine`, commit 1): a test
  waits on STATE, never on the clock.** The three ruled rules are a TESTING.md
  section of their own ("Waiting in a multi-threaded test"), with the
  park-on-a-controlled-gate idiom as its worked example and the
  `Channel.try_receive` poll spelled out. BOTH members of the class are rewritten
  to it. `task_backtrace_mt.saw`: the worker announces its arrival on a `ready`
  channel and parks on a `gate` channel NOTHING sends on until the dump is over
  (so the parked state is permanent, not a four-second window), and the watcher
  polls the arrival report with a 1ms tick and a ~10s deadline that panics rather
  than hangs; the dump now reads `channel-parked`, which is the same assertion
  under the gate the test owns. `channel_receive_cancel_mt.saw`: the consumer
  publishes its running total on a `progress` channel and main polls that until
  it reads 30, so the cancel lands on a consumer that has provably handled both
  orders (and the loop-top cancel check makes the pre-park instant give the same
  answer, which is what keeps the assertion deterministic either way).
  WHAT THE DOCTRINE CANNOT BUY, recorded in the section: no userland test can
  observe a peer's park, so a handful of instructions still sit between the
  arrival report and the park. What changed is the shape of the window — the old
  margin raced POOL STARTUP (hundreds of ms under load, which is what it lost
  to), this races a few instructions against a whole poll period, with a
  permanent state on the far side. Evidence: each test 10/10 byte-identical in
  isolation and 10/10 at loadavg 34 (40 spinners), and the backtrace test fell
  from 3.9s per run to 0.01s — waiting on state is faster than waiting on a
  margin. One incidental finding worth keeping: a RUNNING task's dump row names
  its last suspension point, and a poll loop that may turn once or a thousand
  times reports line 0, so the watcher takes a `yield_now()` immediately ahead of
  the dump purely to give its own row a pinnable line. NO synchronized
  `dump_tasks` twin was added, per the ruling.
  ORIGINAL FINDING (FLAKY GATE LANE, PRE-EXISTING; found Aug 22 by `df-218xy`'s
  terminal battery) — `examples/task_backtrace_mt.saw` fails under machine
  LOAD, which costs an agent a full battery re-run to tell from a real
  regression. Observed once in a battery that ran beside a second agent
  (`saw tasks: 1 live` where the row expects `2 live`; only the watcher's slot
  in the dump, the worker's absent). Re-run 5/5 green in isolation immediately
  afterwards, and the full suite green on the same tree, so the tree was never
  at fault. MECHANISM: the test sequences two MT tasks with a FIXED WALL-CLOCK
  margin — the watcher `sleep(Duration.ms(150))`s and then dumps, on the
  assumption that the pool has by then CLAIMED and parked the worker it was
  handed first. That is a race the margin only hides: under load the pool has
  not claimed slot 0 yet, so the dump honestly reports one live task. The
  test's own header calls the margin "wide on purpose", which is the tell —
  wide is not the same as synchronized.
  SWEEP (obligation 4) — a CLASS, not a one-off: the mechanism is "a fixed
  sleep standing in for a happens-before between two MT tasks", and a second
  member is `examples/channel_receive_cancel_mt.saw`, whose margin is NARROWER
  (`sleep(Duration.ms(50))` before `h.cancel()`, its comment reading "give the
  worker time to drain both messages and park"). It did not flake in these
  runs; nothing about it is more synchronized, only luckier. The three
  single-threaded `dump_tasks` tests (`task_backtrace_nest`,
  `task_backtrace_churn`) are NOT members — a cooperative group's interleaving
  is deterministic, which is the whole reason they are the exact-output rows.
  NOT FIXED HERE (a test-harness change, out of this branch's scope, and the
  right fix is a design question): the honest repair is to make the observation
  wait for the STATE rather than for the clock — the watcher polling
  `g.count()` (or a readiness `Atomic`) until the worker is parked, with the
  sleep only as a backstop — but `dump_tasks` is deliberately an unsynchronized
  snapshot, so what a test may legitimately wait on wants a ruling. Note for
  whoever picks it up: a `task_backtrace_mt` failure reading `1 live` is this,
  not a regression; re-run it alone before chasing it.

- **DF-248d — CLOSED (Aug 22, `place-window-fixes`), filed and fixed by
  DF-218i's obligation-4 sweep: COMPARING a place is a borrow too.**
  `v[0] == w[0]` on a `Vector<Tag>` where `Tag: NoCopy + Equatable` was ``lends
  a place of type `Tag`, which is move-only``, while `a == b` over two move-only
  LOCALS compiled beside it — design 239 gave `equals`/`compare` an
  `other: &Self` precisely so a move-only type with a hand-written comparison is
  comparable, and the place path never got the message. SAME MECHANISM as
  DF-218i (a bare place read is judged by design 131's table wherever it sits,
  including in a position that hands the value to a `&self` callee and keeps
  nothing), so it went through the same funnel: `_rendering_slots` became
  `_borrowing_operand_slots` and grew a comparison clause, all six operators,
  both sides. Row: `examples/place_comparison_operand_is_a_borrow.saw`
  (LHS-only, RHS-only, both, all six operators, the ExplicitCopy tier and the
  Copy-tier control). Conformance row P20. The two-places-ONE-ROOT cell keeps
  DF-248a's boundary.

- **DF-248c (PROCESS GAP; filed Aug 22 by the place-window branch's xfail
  audit) — THE CITATION FACE CLOSED Aug 24 (branch `harness-doctrine`,
  commit 2); the XFAIL-CHARACTER FACE stays OPEN.** (Naming note for the lead:
  the entry already called the xfail-character half "FACE 2" when it was filed,
  and the Aug-24 conflict-marker incident was dispatched to me as "the second
  face" too — so the two halves are named by what they check here rather than by
  number.)
  A THIRD SHAPE OF THE SAME BLIND SPOT, added at the lead's request Aug 24 and
  landing in the same lane: COMMITTED CONFLICT MARKERS. Three git conflict
  blocks were found on `main` that day, one of which had been sitting in
  `designs/todo.md` since the Aug-22 transform-typing integration, and the other
  two nested inside each other in `examples/conformance/INDEX.md`; the lead
  repaired them at e414a8fb. Nothing caught them for the same reason nothing
  caught DF-232n's citation — every gate in the battery COMPILES something, and
  none of them reads a file nothing compiles. The check is the PAIR git writes:
  a line beginning `<<<<<<<` and a later line beginning `>>>>>>>` in one file,
  over every tracked text file (`git ls-files`, binaries skipped), no
  exclusions — `=======` alone is ordinary content and was deliberately not used,
  and the allow-list is an explicit path list with a reason if one is ever
  needed, never a directory skip. Negative control: the INDEX.md nested shape,
  which reports both of its pairs. NOTE FOR INTEGRATION — this branch also
  REPAIRS the todo.md block, identically to e414a8fb's hunks (the branch is off
  8110c1e4, which predates the repair, and the lane cannot be green on a tree
  that still carries it), so the cherry-pick will meet an already-applied hunk
  there.
  `tools/check_citations.py` is the `citations` battery lane, sitting
  beside `astgraft` at about a second: it collects every `// XFAIL: DF-xxx` in
  the tracked `.saw` corpus plus the rows of `corodiff_known.txt` and
  `sawfuzz_known.txt`, and reads each against the tracker. THREE RULES, and the
  third is the one that keeps it from crying wolf — (1) an entry in a
  `designs/done_*.md` file is closure, full stop (the lead moves an entry there
  only once it is closed, which is the cheap test the fix direction below asked
  for, and it is what catches face 1); (2) a `todo.md` entry struck through or
  opening `— CLOSED`/`FIXED`/`LANDED`/`RETIRED` is closed; (3) ANY other
  `todo.md` entry anchored on that DF is OPEN, and open WINS over every closure,
  because a finding is often closed in PART and the tracker spells the remainder
  as a RESIDUE entry — DF-218w, DF-248b and this entry are all live examples,
  and all three keep a citation that is exactly right. An "entry" is a heading or
  list item whose SUBJECT is the DF; a wrapped paragraph line beginning with a
  bolded cross-reference is not one (`**DF-239b** below.` in a done file must not
  read as DF-239b's closure, and does not). Anything undecidable — a DF no entry
  is anchored on — is reported as INFO and passes. The RECOGNISERS are checked on
  every invocation against real tracker lines copied into the tool, because a
  lint whose recognisers have stopped recognising anything reports a clean tree
  exactly the way a clean tree does — which is this finding's own shape, and the
  self-test earned its keep immediately (it caught `~~DF-218s remainder +
  DF-218w~~`, where the strikethrough spans two DFs so no `~~DF-218s~~` exists to
  match). Current tree: 4 citations, all open, 0 stale, 0 undecided. Negative
  controls run both ways — the historical DF-232n pin is reported stale against
  `done_aug18-aug25.md:1158`, a ledger row citing DF-232n likewise, and a ledger
  row citing the partly-closed DF-218w correctly passes. Documented in TESTING.md
  ("The citations stage", plus the reverse-direction paragraph under Known
  Failures) and in `examples/module_matrix/INDEX.md`, whose DF-248c note now ends
  at the lane instead of at the gap.
  THE XFAIL-CHARACTER FACE IS NOT CLOSED and stays the open half of this entry:
  an XFAIL that starts failing for a WORSE reason than the one cited is still
  invisible,
  because every gate reads pass/fail and nothing reads WHY. That wants the
  `XFAIL-EXPECT: error` / `XFAIL-EXPECT: output` discriminator described below,
  in `test_runner.py` rather than in a lint — a lint cannot see a run's
  character, only its citation.
  ORIGINAL FINDING — an XFAIL whose cited DF has CLOSED is invisible to every
  gate. The
  XFAIL policy's teeth are the XPASS direction: a marker on a test that starts
  passing breaks the build. Nothing looks the other way. A pin whose finding was
  fixed by a ruling that SUPERSEDED the intended behavior the pin asserts keeps
  FAILING — so it stays a well-behaved known failure, forever, while the ledger
  it belongs to reports a red cell that is green.
  FOUND: `examples/module_matrix/visibility_package_relative_import_fails_open.saw`
  cited DF-232n, which CLOSED Aug 20. It asked for a refusal (``EXPECT: error``,
  ``is public(package) in``) that DF-232n's own fix deliberately does not give:
  the fix closed the fail-open arm by IDENTITY, and a manifest-less tree
  compiled from one entry is ONE package (`ModuleResolver.package_identity` arm
  2, DF-229c's ruling generalized), so two relative siblings under
  `examples/module_matrix/` reach each other legally. Fixed here: the pin is the
  ACCEPT row of that ruling under the behavior's own name
  (`visibility_package_adhoc_tree_is_one_package.saw`), the grid's red cell is
  green and split in two (the across-a-`Saw.toml` arm got its own row), and
  `examples/module_matrix/INDEX.md` records both.
  SWEEP (obligation 4) — a population of ONE today, and the mechanism admits
  more. All nine `// XFAIL: DF-` citations in `examples/` were checked against
  `designs/todo.md`: DF-218h, DF-218w, DF-238c, DF-239b, DF-245c, DF-245d and
  DF-248b are open entries; DF-218j and DF-169h were this branch's own and are
  now flipped off; DF-232n was the one closed citation. Nothing about that ratio
  is structural — the next fix that closes a finding whose pin asserts a
  superseded expectation lands in exactly the same blind spot.
  FACE 2, found by this branch's own near-miss and the same mechanism: an XFAIL
  that starts failing for a WORSE reason than the one cited is invisible too.
  DF-169h's first commit gated GREEN while it had turned DF-218h's clean
  refusal into a DOUBLE FREE — the pin
  (`place_window_move_arg_consumes_local.saw`) compiled and printed each id's
  deinit twice, which is still a failing xfail, so nothing said a word. The
  marker records an expectation and every gate reads only pass/fail, so the two
  faces are one gap: what the ledger claims about a pin is never checked against
  what the pin does. The correction landed one commit later, with a moved-name
  exclusion in the capture synthesis.
  FIX DIRECTION (not built here — it is a gate-lane decision, and the matching
  is prose): a lane that reads every `// XFAIL: DF-xxx` in `examples/` and fails
  when the DF is not an OPEN tracker entry. The hard half is "open": todo.md
  keeps a closed entry IN PLACE until the lead moves it to the week's done file,
  so the test cannot be "appears in todo.md" — it wants either a machine-readable
  status on the entry or the check keyed to `designs/done_*.md` membership
  (a citation that appears in a done file is closed, full stop). The second is
  cheap and would have caught face 1. Face 2 is harder and probably wants the
  pin to say HOW it fails — an `XFAIL-EXPECT: error` / `XFAIL-EXPECT: output`
  discriminator the runner checks — so that a refusal turning into a miscompile
  breaks the build instead of blending in.

- **DF-248b (SILENT LOST WRITE, PRE-EXISTING; filed Aug 22 by DF-169h's sweep;
  the WINDOW half FIXED in the same branch) — a closure nested inside another
  closure captures the outer one's REFERENCE PARAMETER by value.** MECHANISM:
  codegen binds a reference closure parameter to the POINTER itself and records
  its INNER type beside it (`closures.py`, the `is_reference` arm — that is what
  makes `{ e in e }` yield a `T`), so the capture walk sees a `T`-typed name,
  loads the VALUE through the pointer and puts a copy in the env. The write
  lands in the copy. Two things hide it: the closure's own reads see that copy
  AFTER the write, so only the ROOT is stale, and design 132's capture-write
  rule catches the ASSIGNMENT spelling at compile time — so only the ARGUMENT
  spelling (`inner({ bump(&var c) })`) gets through.
  FIXED HERE, the PLACE-WINDOW face: `setboth(&var a.at().n, &var b.at().n)` —
  design 188's own accept side, two roots that alias nothing — lost BOTH writes
  before DF-169h and the outer one after it, which is what identified the
  remaining half as the window's own PARAMETER rather than an enclosing local.
  A window closure's parameter is bound under its REFERENCE type (the
  `place_shared_window` path), so the synthesis can see it and spells the
  borrow. Row: `examples/place_window_nested_writes_land.saw`. DF-218h's landing
  moved that arm AHEAD of the moved-name arm, so a reference the body `move`s
  takes the borrow mode and its own "cannot move out of reference" refusal
  instead of falling into the plain capture this finding is about.
  STILL OPEN, the hand-written face, and it is open because the checker cannot
  SEE it: a closure's `&var c` parameter is bound under its INNER type with a
  mutability flag, so `outer_scope.lookup("c")` is indistinguishable from an
  ordinary `var` local. The fix wants a borrow MARKER on `VariableInfo`, which
  every scope in the compiler shares — a small change with a wide blast radius,
  and a sweep of its own (`Mutex.lock`/`SpinLock.lock`/`Arc.with_unique` bodies
  are the shapes that hand out a `&var` closure parameter in std).
  PIN: `examples/closure_nested_ref_param_capture.saw` (XFAIL)

- **DF-248a — CLOSED (Aug 24, `deferred-move`): an assignment's RHS may read the
  target's own root; every other in-window naming of it keeps its refusal, and
  the refusal now teaches which is which.** The ruling, both halves.
  LEGALIZED BY ORDER, not by a carve-out: `place_uses`'s DF-218j hoist asked
  "does the right-hand side open a WINDOW on this root" because that was the
  shape it had; the rule it rides on is design 193's evaluation ORDER, which
  says nothing about windows. `_rhs_reenters_root` became `_rhs_names_root` and
  answers for a plain read too, so `v[0].n = v.len()` lowers to the `let` + write
  pair — the overlap REMOVED, not permitted, exactly as DF-218j's did. One
  predicate, both entry points (`_assignment` and `_hoist_chain_assign_rhs`).
  A consequence worth stating: `v[0].n = v.pop()!.n` now compiles and is
  well-defined — the pop finishes before the window opens, so the invalidation
  the old note called out cannot happen in that spelling.
  REFUSED, WITH THE ASYMMETRY SPELLED OUT: every other position runs AFTER the
  accessor's prologue, so there is no documented order to lift along.
  `_place_window_root_capture_error` is the one site (matching the one exclusion
  in `_synthesize_place_window_captures` that produces the case), and it replaces
  the copy-tier noun — which named a container the program never copies — with
  the reason: what a window's extent is, the `let` that fixes it, that the
  ASSIGNMENT shape one line up compiles and why, and why that lift is not
  available here. Scoped to the tiers that already refused; a Copy-tier root
  captures by value with no diagnostic, and turning that into an error would be a
  new refusal rather than better words.
  ROWS: `examples/place_window_root_read_in_assignment_rhs.saw` (subscript,
  compound, named accessor over a NoCopy root, the optional-chain spelling, a
  field-hop target, the pop shape, and the disjoint-roots control that must NOT
  hoist) and `examples/errors/place_window_root_read_teaches_the_asymmetry.saw`
  (argument, interpolation operand, comparison, `assert` condition — all four
  reported in one compile). Conformance P21; P18's note re-pointed.
  Original finding follows.
  **(BOGUS-REFUSAL, BOUNDED; filed Aug 22 by DF-169h's fix) — a window
  body may not name the window's own ROOT, even for a read that invalidates
  nothing.** `v[0].n = v.len()` is ``cannot copy value of type `Vector<Cell>`
  which implements ExplicitCopy``, anchored at the subscript, and so are the
  three shapes the borrow-classified positions add: `print("{v.len()} {v[0]}")`
  on a move-only element, `assert(v[0].n == 1, "{}", v[0])` (the condition is
  inside the message's window), and `v[0] == v[1]` (the second operand's window
  names the first's root). MECHANISM: DF-169h made a
  window closure borrow-capture every enclosing binding its body names EXCEPT
  the receiver's root, which stays a by-value capture — so the copy tier still
  answers for it. HELD DELIBERATELY, and this is the reason a sweep did not
  widen the fix: borrowing the root would put a SECOND access to it inside the
  open window, which is what design 188 refuses in one call, and
  `v[0].n = v.pop()!` is exactly the invalidation that rule exists for. Nothing
  today separates the safe second access (`len()`, a `&self` read) from the
  invalidating one (`pop()`, `push()`) at the window's own root, and inventing
  one is a design: the honest rule is probably "the root may be reached SHARED
  from inside the extent, never exclusively", which needs the window's borrow to
  join the access set (closures are their own access domain today —
  `_check_write_rhs_exclusivity` skips them). Until then the workaround is one
  line: bind what the body needs off the root ahead of the window
  (`let n = v.len()`). The two-windows-on-one-root half of this is DF-218j,
  which the assignment RHS-hoist closes without touching the rule.

- **DF-218i — CLOSED (Aug 22, `place-window-fixes`): a rendering operand is a
  BORROW, like the presence test beside it.** `place_uses` grew a third
  borrow-classified shape: where the operand IS the place and the value-read
  table would refuse it, the window's extent becomes the smallest RENDERING
  expression and the operand is the window's own `&T` binding — which every
  rendering position already accepts. The three positions go through ONE funnel,
  `_borrowing_operand_slots` (named `_rendering_slots` when it landed; DF-248d
  widened it a commit later), whose docstring names them (interpolation operand;
  single-argument `print` of a Printable; the format arguments of
  `print`/`panic`/`assert` past the literal format string and past `assert`'s
  condition). Scoped to the REFUSED reads deliberately: where the tier permits
  the read the ordinary per-operand window is the better lowering, and wrapping
  the whole rendering expression would pull every sibling operand inside the
  window with it. **The deferred family is RETIRED**, not narrowed:
  `FAM_RENDERED`/`rendering-operand` is gone from `coro_transform` and from
  `tools/test_forget_purge.py`'s ledger, so a rendered frame local migrates to
  `Slot<T>` like any other (`examples/place_rendered_frame_local_migrates.saw`
  is the IR-confirmed row — `%"__Frame_driven"` field 0 is a `Slot$…$Res` — and
  it carries blade's own `case Err(e) -> fail("{e}", …)` shape). Pin flipped and
  widened to the whole matrix. Original finding follows.
  **(BOGUS-REFUSAL) — rendering a PLACE is judged a
  value read, so a move-only element cannot be printed.** `print("{v[0]}")`
  and `print(v[0])` on a `Vector<Res>` where `Res: NoCopy + Printable` are
  refused with ``lends a place of type `Res`, which is move-only``, though
  rendering hands the value to `format(&self, into:)` and keeps nothing — the
  same borrow `v[0].method()` already gets. The two controls compile: a field
  read out of the place, and a `&self` method call on it. MECHANISM: the
  window lowering has one shape for a place used as a VALUE (the body returns
  the element), and the rendering path is lowered in CODEGEN from that value
  rather than as a `format` call inside the window — so `_value_read_ok`'s
  table is asked a question rendering never poses. The fix is design 218's
  ELABORATION PRINCIPLE again, as for DF-218a: desugar a rendering operand to
  the `format(into:)` call it becomes, before the place lowering runs.
  SURFACED BY design 218 stage 1, which makes a frame's locals places too:
  blade's `main` stopped compiling at `case Err(e) -> fail("{e}",
  EXIT_FAILURE)`, one `Box<any Error>` per command, and only the `bootstrap`
  battery lane catches it. Stage 1 holds that family back — a move-only or
  ExplicitCopy local whose WHOLE VALUE is a rendering operand keeps the legacy
  encoding (`_migrated_enc`, the sixth deferred family; a projection like
  `"{got.id}"` is an ordinary place hop and migrates).
  PIN: `examples/place_rendering_operand_is_a_borrow.saw` (XFAIL)

- **DF-218h — CLOSED (Aug 24, `deferred-move`): a `move` capture into a
  NON-ESCAPING closure transfers WHEN THE BODY RUNS.** The ruled answer, one
  site: `closures.py`'s env build gives a non-escaping `move` capture a
  `{ T*, i1* }` field (the local's storage and its drop flag) instead of a copy
  of the value, and the body's prologue takes the value, clears that flag and
  registers the taken value as an owned local of the body. Every branch of the
  old dilemma falls out rather than being handled: the absent path of a
  conditional lend never runs the prologue, so the local is still the frame's
  and deinits at scope end; the executed path clears the flag, so exactly one
  owner frees; a body that moves CONDITIONALLY drops what it took at its own
  end on the paths that keep it. The flag doubles as OCCUPANCY — a body run
  twice would take a value that is gone, so the take is guarded and a repeat
  PANICS (`closure body ran twice on `move` capture `h``) where it used to
  free three times silently. The window synthesis then stops excluding moved
  names: `_synthesize_place_window_captures` writes `[move h]` for them, behind
  the reference arm so `move` out of a reference keeps its own refusal.
  DROP ORDER, measured for the exactly-once direct call: deferred and eager
  agree wherever the body CONSUMES the capture (the consumer frees, at the same
  point either encoding would). They differ only where the body does not — eager
  defers to the env teardown, deferred drops at the body's end — and where the
  body never runs, which eager cannot express at all.
  SWEEP (obligation 4), one matrix, deinit-counted both ways:
  `examples/closure_move_capture_transfers_when_body_runs.saw` — a literal at a
  non-escaping parameter (consumed / kept / never run), `with_var_ref` and
  `with_ref` bodies, the place window's own lowered closure, a conditional lend
  on BOTH paths, and the three owning tiers (NoCopy, ExplicitCopy, and the
  declared Copy hook). Conformance row V48. Pin flipped
  (`place_window_move_arg_consumes_local.saw`); its driven row's expected output
  was corrected at the same time — eager frame teardown releases `pending` when
  the task completes, so both ids print before the length does.
  ONE SIBLING FOUND AND NOT FIXED: the ESCAPING half double-frees the same way
  and always did (DF-255a below, pinned). Its answer cannot be this one — the
  flag cleared here belongs to the source frame, which an escaping capture has
  left — so the occupancy has to live in the heap env.
  ALSO UNBLOCKED, not done: `FAM_WINDOW_MOVE` in `coro_transform` was held back
  by this defect and by DF-169h, both now fixed. Retiring the family also
  migrates design 222 unit 1's raw cell write (`_cell_hop_raw`), which is a
  frame-layout change with its own corodiff/irdet surface — a design-218
  staging landing, and the docstrings now say so instead of citing a defect.
  Original finding follows.
  **(BOGUS-REFUSAL + a worse alternative, PRE-EXISTING) — a `move` of
  a LOCAL inside a place window is refused, and every capture spelling that
  lifts the refusal double-frees.** `v.push(move h)` where `v` is a place puts
  the author's `move h` inside the closure the window lowering writes, and a
  `move` of an ENCLOSING local from inside a closure body has no way to clear
  that local's drop flag. The refusal is ``cannot copy value of type `Res`
  which implements NoCopy``, anchored at a receiver that copies nothing —
  DF-169h's family (that one is the `&var`-argument half; this is the by-value
  half). MEASURED, and the reason it is not a capture-list patch: adding
  `[move h]` to the synthesized closure compiles and deinits TWICE, and so
  does `[&var h]`; the hole is not confined to synthesized closures either —
  a hand-written `run({ [move h] in sink(move h) })` compiles today and
  double-frees (`.build/scratch/movecap.saw`). So the refusal is the
  protective behavior and the fix is a closure move-out design that answers
  both halves. Found by design 218 stage 1: a frame local is a `Slot` now, so
  `pending.push(move h)` in a driven body became a window call and irdet
  stopped compiling — stage 1 holds that family back (`_migrated_enc`, the
  fifth deferred family) rather than shipping either the refusal or the
  double free.
  **STOPPED, with the code site named (Aug 22, `place-window-fixes`).** The
  branch that fixed DF-169h/i/j reached this one and stopped rather than code
  around it, as the tracker's own reading says to. The double free is
  `sawc/codegen/closures.py`'s capture loop: the `move` arm clears the source
  binding's drop flag and marks it moved ONLY `if escapes`, because only an
  ESCAPING closure has a heap env with a destructor to release the value later.
  A NON-escaping closure keeps its env on the stack with no destructor at all
  ("captures are borrowed and no retain/teardown is needed"), so clearing the
  flag there would LEAK whenever the body does not consume the capture, and not
  clearing it double-frees whenever the body does — which is exactly what
  `run({ [move h] in sink(move h) })` prints (`sank 1 / deinit 1 / done /
  deinit 1`, re-measured on today's tree). So the missing piece is not a flag: a
  non-escaping `move` capture needs an env TEARDOWN after the call that consumes
  the closure, and a body that moves CONDITIONALLY (a value `if`/`match` arm, a
  `??` short-circuit) needs the flag to live in the env rather than in the
  frame. That is the closure move-out design the entry already asks for, and it
  is why the window lowering cannot patch its own closure: the hole is one layer
  below it. DF-169h's borrow captures deliberately do NOT reach this — a `move`
  of a borrow-captured name is "cannot move out of reference", a different
  refusal for the same protective reason.
  PIN: `examples/place_window_move_arg_consumes_local.saw` (flipped Aug 24)

- **DF-255a (DOUBLE FREE, PRE-EXISTING; filed Aug 24 by DF-218h's sweep) — an
  ESCAPING closure whose BODY consumes its `move` capture frees it twice.**
  `let f = { [move h] in sink(move h) }` then `f()` prints `built / sank 1 /
  deinit 1 / done / deinit 1` (stash-verified against the tree before
  `deferred-move`, so it is not this branch's). MECHANISM: an escaping env OWNS
  its captures and its generated destructor releases each one, and the body's
  prologue LOADS the capture out of the env into a per-call local — so `move h`
  in the body retires the LOCAL and leaves the env field looking occupied.
  `sink` frees the value; dropping `f` frees it again.
  WHY DF-218h's answer does not port: the flag the deferred take clears belongs
  to the SOURCE FRAME, and an escaping capture has already left it. The
  occupancy has to live in the heap env — a word beside the refcount, or a
  per-capture bit the destructor honors — which is a layout decision, and it
  raises the question the language has not taken a position on: a closure VALUE
  can be called any number of times, so a body that consumes a capture is
  a one-shot closure with no type to say so. Refusing the move-out for escaping
  closures is the other candidate answer, and it is the same question the
  non-escaping side answers at RUN TIME today (the second run panics).
  PIN: `examples/closure_escaping_move_capture_consumed_once.saw` (XFAIL).
  Conformance row V49.

- **DF-218j — CLOSED (Aug 22, `place-window-fixes`): two windows on one root,
  in one assignment, are SEQUENCED rather than nested.** An assignment already
  says in which order its two sides run (design 193 fixed the RHS as the first
  thing it evaluates), so `_assignment` hoists a right-hand side that opens a
  window on the TARGET'S OWN ROOT into a `let` ahead of the write — the "two
  windows in SEPARATE statements" shape design 188 has always accepted. The
  hoist REMOVES the overlap rather than permitting one, so 188's refusal of two
  by-reference accesses to one root in ONE CALL is untouched
  (`place_window_exclusivity.saw` still expects that error). Narrow by design:
  only an RHS rooted at the target's root hoists, since two windows on two
  different roots nest happily and hoisting those would move a temporary's
  death to the block's end for every `v[0] = w[1]` in the corpus. SWEEP: the
  pin is now the matrix — the named accessor, the subscript (`v[0] = v[1]`, an
  ordinary line that did not compile), a COMPOUND assignment whose RHS
  re-enters, a forced conditional lend on both sides, and the optional-CHAIN
  spelling (hoisted at the statement, `_hoist_chain_assign_rhs`). ONE position
  is out of reach and recorded rather than fixed: the value-position chain
  assignment (`guard let _ = m[k]?.f = m[k2]!.g`) has no statement to hoist
  into and stays refused. Original finding follows.
  **(BOGUS-REFUSAL) — an assignment whose TARGET and
  whose RHS each open a place window on the same MOVE-ONLY root is refused as
  a copy nobody wrote.** `h.at().n = h.at().n + 10` on a NoCopy `h` reports
  ``cannot copy value of type `Holder` which implements NoCopy``, hinting at a
  `move`. Two controls compile and run, which is what says the refusal is
  about the PAIR of windows rather than either one: `h.at().n += 10` (one
  window, same root) and `p.at().n = p.at().n + 10` (two windows, Copy root).
  Windows nest LIFO and a place borrow charges its root, so two windows on one
  root in one statement is at worst an exclusivity question — answering it
  with a copy error is the wrong noun for the wrong rule. Found by design 218
  stage 3: the `[&self]` capture reaches the receiver through a window in a
  driven body, so `self.n = self.n + 10` inside such a closure IS this shape,
  while its SYNC twin compiles (the sync capture lowering opens no window).
  PIN: `examples/place_two_windows_one_nocopy_root.saw` (XFAIL)

- **DF-218k/l/m and DF-223a FIXED (design 223 units 1 and 2, Aug 15).** One
  classifier, three-valued, replacing `_method_call_owner`; its definition-side
  twin aligned in the same commit; and the strip routed through a funnel that
  refuses to remove a method a conformance requires. Rows K33-K36, K39 pass
  (frame symbol in the IR AND the two-task interleave, per row).
  `examples/coro_closure_captures_self_nested.saw` gained back the three
  contexts it had recorded as unreachable. The four originals follow, kept for
  the mechanism each recorded.

- **DF-223b RULED AND REFUSED (design 223 unit 3, Aug 15)** — the cell is a
  clean, anchored compile error naming the DF; the DESIGN it is owed is still
  open (see the DF-223b entry above). **DF-218q CLOSED with it**: the
  unanchored `:0:0` refusal of a `&any Trait` parameter in a spawned body was
  the post-transform re-typecheck refusing a frame field the transform
  synthesized (`UnsafeRef<any Greeter>` — an unsized pointee). The transform
  refuses it itself now, at the PARAMETER the author wrote, naming the two
  spellings that work.

- **DF-218k (BOGUS-REFUSAL + wrong diagnostic, PRE-EXISTING) — a SUSPENDING
  method in a trait CONFORMANCE is reported as not implementing the
  requirement.** `extension Person: Greeter { func greet(&self) -> String {
  yield_now()  self.n } }` against `trait Greeter { func greet(&self) ->
  String }` reports ``type `Person` does not implement required method `greet`
  from trait `Greeter``` at the extension, about a method plainly written
  there. No closure and no coroutine machinery in the repro beyond the
  `yield_now()`; the same body without it conforms. Repro
  `.build/scratch/s3_trait_susp.saw`. Found while sweeping design 218 stage
  3's contexts (the sync `closure_captures_self.saw` covers a trait DEFAULT
  body; the suspending analogue cannot be written at all).

- **DF-218l (ICE, PRE-EXISTING) — a SUSPENDING method on an ENUM extension is
  a codegen ICE.** `extension Color { func label(&self) -> String {
  yield_now()  match self { ... } } }` dies `internal compiler error
  (MethodCall): Undefined method: Color.label` at the call site. Design 145
  gives enums extensions with `&self` methods and design 74 gives methods
  frames; the two have not met. Repro `.build/scratch/s3_enum_susp.saw`,
  reproduced on the stage-2 tree. Found with DF-218k, same sweep.

- **DF-218m (SILENT WRONG BEHAVIOR + ICE, PRE-EXISTING) — a suspending method
  on a GENERIC struct, reached from a driven body, is compiled as a PLAIN
  function.** `Box2<T>.describe(&self)` containing `yield_now()`, called from
  a `main` that a driven call already made a frame root, emits
  `Box2$1$String_describe$1$String` as an ordinary function (IR-confirmed):
  no frame, no sub-frame field in the caller, the suspension point compiled
  inline. It happens to print the right answer, which is what makes it the
  bad kind of finding — the cooperative contract is simply not applied. Add a
  closure naming `self` to that body and it becomes an ICE against the
  CALLER's frame (``Cannot find field v in struct with type
  %"__Frame_main"``), which is how it was found: design 218 stage 3's receiver
  capture never runs, because no frame builder ran for the method. Design 74
  shape 2 says a generic struct's suspending method drives; this is the
  EMBEDDED position of that shape. Repros
  `.build/scratch/s3_generic_noclosure.saw` (silent) and
  `.build/scratch/s3_generic_struct_self.saw` (ICE).

- **DF-218n — CLOSED (design 237 unit 4, Aug 21), as ruled: a clean refusal at
  the top of `_FrameBuilder.prepare`, on the untouched body — one entry
  covering every drive spelling and every root kind, since every body the
  transform frames passes through there. The diagnostic names the direct call.
  Pins: `examples/drive_site_in_suspending_body.saw` (XFAIL flipped to the
  refusal) + `examples/drive_site_in_suspending_function.saw` (the non-`main`
  and `__saw_drive_steps` row). LANGUAGE_SPEC's `__saw_drive` paragraph says
  so. Original finding below.**
  **(ICE, PRE-EXISTING) — an explicit `__saw_drive(f())` inside a body
  that ITSELF suspends dies in the drive-site rewrite.** `main` driving `s()`
  and then calling `t()` on its own account makes `main` suspending, so the
  coroutine transform rewrites its body before `_rewrite_drive_sites` walks it;
  the drive site's argument is no longer the `FunctionCall` that rewrite reads,
  and the compiler dies `AttributeError: 'MemberAccess' object has no attribute
  'name'`. Reproduced unchanged on the stage-3 tree.
  **RULED (user, Aug 15): CLEAN REFUSAL** — `__saw_drive` may not appear in
  a suspending body; the diagnostic teaches the blessed spelling ("this
  body suspends; call `f()` directly — suspending calls embed here").
  Grounds: `__saw_drive` is design 44's test-only entry, so the refusal
  costs zero real programs, and both-roots-run would design non-ceding
  nested-drive semantics (fairness, op-budget bypass) for a spelling only
  tests write; if a deliberate sync-bubble capability is ever wanted it
  gets its own designed spelling. Fix rides the 120-matrix ICE brief
  (217f/g family — same statement-position rewrite territory); the pin's
  EXPECT flips to the refusal text.
  Found by design 218 stage 4 writing coverage for the two `__result`
  encodings the migration defers.
  PIN: `examples/drive_site_in_suspending_body.saw` (XFAIL)

- **DF-223a (ICE, PRE-EXISTING) — a suspending METHOD-LEVEL generic on a
  concrete struct is an unanchored `internal compiler error: 'Holder_wrap'`.**
  `h.wrap<String>("x")` where `Holder.wrap<T>` suspends: the RECEIVER is
  concrete, so the call-site classifier names it and the call is classified
  embeddable; the method AST it names still carries `<T>`, so the closure walk
  skips it on its own `type_params` and `fbs[<key>]` raises. The two ends of
  the classifier key different things — the call site keys the RECEIVER, the
  definition-side skip keys the METHOD — which is the mechanism design 223's
  unit 1 targets, and why the two halves cannot be fixed apart. Found by
  design 223's cell-G probe.
  ROW: `examples/conformance/K35_suspending_generic_method_embedded.saw`

- **DF-223b (SILENT WRONG BEHAVIOR, PRE-EXISTING — owed a DESIGN, not just a
  fix) — an existential dispatch to a SUSPENDING conformance body never
  suspends.** `func shout(g: &any Greeter) -> String { g.greet() }` against a
  `Person.greet` whose body yields: the dispatch is recorded as a
  merely-CONSERVATIVE suspension source (`really_suspending`'s gate excludes
  it, exactly as it excludes a call through a closure), so `main` is never
  wrapped in the entry executor, NO frame is built anywhere in the program,
  and the `yield_now()` inside the impl runs outside a frame — where it is a
  no-op. The program compiles, prints the right answer and holds the thread.
  A `sync`-declared caller IS refused by name and line, so the effect graph
  knows; only the lowering does not.
  Design 223 makes it a CLEAN REFUSAL at the dispatch (its cell policy:
  work-where-the-mechanism-exists, refuse where it does not) and this entry is
  what the refusal cites. THE DESIGN IT IS OWED: a frame is a compile-time
  identity — the caller embeds the callee's frame BY VALUE, so it must know at
  compile time which body it embeds — and dynamic dispatch has none. Making it
  work needs an answer to "how big is the frame behind this vtable word":
  a boxed/erased frame reached through the vtable (a `Box<any Resumable>` the
  callee mints, which costs an allocation per call and a second frame ABI), a
  per-trait-method frame UNION over every conformer (whole-program, closed only
  in a single compilation unit), or a rule that a suspending method may not be
  a trait requirement at all (the smallest, and the one that keeps existentials
  honest about what they erase). Wants a ruling session.
  ROW: `examples/conformance/K37_existential_dispatch_suspending_impl_refused.saw`

- **DESIGN 218 STAGE 4 LANDED (Aug 14) — teardown, the forget purge, the
  trusted-list ratification. THE SLOT MIGRATION IS COMPLETE.** Census rows
  D1-D3 plus R8/P3/P4. Details in the 218 brief's STAGE 4 LANDED section and
  its rewritten trusted list.

  THE PURGE, in the adapted form the lead ruled (218a §9's "emission count hits
  ZERO" pre-dates the deferred families): every `__saw_forget` goes through ONE
  funnel that refuses to emit without naming the deferred family holding its
  field back, and `forgetgate` (`tools/test_forget_purge.py`) checks it — one
  emission site, every call cited, the family set the documented one, and the
  funnel provably refusing an uncited family. Four scattered constructions
  collapsed to one; NONE were deleted, because all four are live and a trace
  says which family reaches each.

  THE TRUSTED LIST is ratified to its final form, and it is shorter in the one
  place that matters: `Slot<T>` is NOT on it (it names no unsafe type, so the
  checker judges it). What is: `UnsafeRef`'s validity argument, the design-134
  spawn cell (R8/P4), the design-91 reactor token (P3), the drive-site cast, the
  resume dispatch, the executor/reactor, the two C files. Named as NOT trusted,
  so the lists cannot blur: the deferred families' legacy bookkeeping, which is
  unmigrated rather than trusted, and the permanent provenance exemptions.

  D4/D5 (cancel, panic) needed no migration and stop being S3-PENDING —
  corodiff carries three cancel contexts and a panic context with their own
  oracle classes, and `corodiff --all` gated every stage. M1/M3 still do not
  retire: `_read_field`'s legacy branch stamps them and it is alive for exactly
  the deferred families, so they go in the landing that deletes the funnel. But
  they are now UNDER THE GATE (lead's contract extension): each of the eight
  surviving stamp sites names its deferral, and extending the gate deleted a
  NINTH that was stamping the MIGRATED path — `move o!` asserting past design
  131's "a payload read out of a call result is already yours".

  Coverage the trace found missing and this stage added: the three `__result`
  emission sites fire ZERO times across the suite, because nothing in the corpus
  returned a fixed array or a closure from a driven function
  (`examples/coro_result_array_and_closure.saw`). One finding filed, pre-existing
  and reproduced on the stage-3 tree: DF-218n.

- **DESIGN 218 STAGE 3 LANDED (Aug 14) — closure envs, `[&self]`,
  `UnsafeRef`.** Census rows R4, R7, P1 and P2 migrated and 218a section 4
  landed whole. Terminal gate: the full tracked battery, every stage green —
  suite 1834 passed / 24 xfailed, `corodiff --all` (1566 pairs, 0 NEW
  findings), `irdet --all` (1153 examples, byte-identical IR), lexdiff and
  astdiff over 2050 tracked files, fuzz (150 mutants, 0 new), gmgate (51
  programs), bootstrap, and sos (32 tests, riscv32 + arm64).

  FLIPPED: `examples/closure_captures_self_suspending.saw` — DF-216g, the
  finding the stage folds in whole. A closure naming `self` in a driven method
  captures a second `UnsafeRef` handle minted with `copy()`; the frame keeps
  `__recv` for its later resumes, so duplication is written where it happens.
  Mode is the materialized binding's mutability, which is the same verdict the
  pre-transform check reaches by a different mechanism.

  DELETED: E6. NARROWED: E2, and the reason is measured rather than preferred
  — the transform splices a DRIVE-SITE CAST into the CALLER's own body, so
  deleting the flag outright holds an author to a rule about a pointer they
  did not write. It survives for REWRITTEN bodies and stops covering the
  declarations the transform AUTHORS, which now declare `unsafe` honestly and
  are CHECKED (`unsafe_decl_checked`). NOT deleted: M1/M3 — stage 1's six
  deferred census families keep the legacy encodings, and `_read_field`'s
  legacy branch is what stamps the marks; what stage 3 removed is the `ref`
  and `__recv` emitters, the two the migration owned.

  Details, including the forwarding rule three sites needed
  (`<handle>.p` beats `&` of a `deref()` window) and the nested-closure
  handle chain, are in the 218 brief's STAGE 3 LANDED section. Four findings
  filed: DF-218j (found by the stage), DF-218k/l/m (pre-existing contexts the
  sync capture test covers and the suspending one cannot reach).

- **DESIGN 218 STAGES 1 AND 2 LANDED (Aug 14).** Gate at both: full suite
  (1824 passed / 23 xfailed), `corodiff --all` (1566 pairs, 0 NEW findings)
  and `irdet --all` (1149 examples, byte-identical IR).

  STAGE 2 flipped SIX pins — the DF-217h five (`coro_hoisted_call_arg`,
  `_push_arg`, `_struct_init_arg`, `_tuple_element`, `_coalesce_rhs`) plus
  the seventeen-row DF-217h block in `tools/corodiff_known.txt`, removed as
  stale in the same landing. The transform's single-use temps are `Slot`s
  whose one read is `take()`, and `__result` joined them (census R5/R6) once
  DF-218f made `put(v)` work.

  TWO STAGE-2 ROWS DID NOT MIGRATE, each measured rather than preferred:
  (f) the SCRUTINEE temps `__hoistN`/`__matchN` (T1/T3) — their reader
  consumes only when the binding it feeds does, and neither answer is
  spellable: `take()` on a non-consuming dispatch leaks (the binding's scope
  is a CFG block the split reaches from elsewhere and its cleanup never
  runs), `value()` is refused for a move-only payload because a NAMED `if
  let` binding over an optional-typed lend is a value read — the half of
  DF-218a its `_`-only desugar left open. The DF-210f forget therefore
  STAYS, for exactly those two. (g) `__anfN!` — an unwrapped consuming temp
  keeps its borrow, because unwrapping leaves the optional as a temporary
  nobody registers and the SYNC twin of that shape leaks outright
  (DF-217m). `examples/coro_hoisted_receiver_temp_released_once.saw` is
  half-fixed and re-pinned on DF-217m accordingly.

  Kept below for the record: the stage-1 obstacles, their rulings, and the
  census families that proved wrong-shaped.
  The migration was built end to end (working patch, `.build/stage1-wip.patch`
  in the stage-1 worktree; 1813 of 1817 green, four failures, none of them
  cosmetic). What works is not in doubt: every owning frame LOCAL and PARAM
  becomes a `Slot<T>`, stores are `put`, move-reads are `take()`, non-move
  reads are `value()` lends, `__release` is a `clear()` loop, `Slot<T>.of` /
  `Slot<T>.empty()` seed the frame, and the paired `__saw_forget`s vanish with
  each converted row. The two things that stopped it landing:

  - **DF-218g — the frame vocabulary cannot be compiled into every driven
    program without taking the name `Slot` from user code.** Generated frames
    name `Slot`, so `std.compiler.frame` must be in codegen for any driven
    program; but it is a GATED std module precisely so a user may declare
    their own `Slot`, which `examples/std_gated_name_redefined_by_user.saw`
    pins. Forcing the leaf in and keeping its NAMES out of the merged
    namespace fixes the user-STRUCT case (`coro_generic_struct_method` goes
    green) and not the user-ENUM case (`df151d_match_temporary_scrutinee`:
    `internal compiler error: Undefined enum: Slot`) — hole 1 of the four that
    same pin lists, reopened because the std struct is now present. This is
    the design-82 exclusion boundary meeting design 144 identity: exclusion is
    the language's answer to name reuse, and a type the compiler must always
    emit cannot be excluded. **RULED (user, Aug 14 morning): QUALIFIED CODEGEN
    IDENTITY** — the frame module's types compile under their design-144
    identity (`Slot$m$std_compiler_frame` as the codegen base symbol);
    generated references, monomorphization keying, and method mangling all
    resolve by identity, never bare name — the Poll mechanism extended from
    references to the FULL compilation. User `Slot` (struct or enum) owns the
    bare name completely. Name-reservation rejected (breaks design 82's
    pinned promise; `__` names violate ruling 11's spellability).
  - **DF-218f — a CALL ARGUMENT does not auto-wrap to `Result`, while an
    assignment does.** `func takes(v: Result<Int, MyErr>)` refuses `takes(5)`
    ("argument `v` expects `Result<Int, MyErr>` but got `Int`"); the same
    value assigned to a `Result`-typed field wraps `Ok`. `Optional` auto-wraps
    in BOTH positions, which is what makes this an asymmetry rather than a
    missing feature. Consequence for 218: census rows R5/R6 (`__result`
    becomes a `Slot`) are STOPPED — a result store rides assignment auto-wrap
    (`return v.len()` from a `-> Result<Int, E>` body), and `put` takes its
    value as an argument, so migrating the slot would make the transform
    re-derive a wrap it is supposed to inherit. Repro
    `.build/scratch/framecheck/f7.saw`. **RULED (user, Aug 14 morning):
    EXTEND AUTO-WRAP TO CALL ARGUMENTS** — Result gains the argument
    position Optional already has (the asymmetry was unprincipled; any
    hides-mistakes argument applies equally to positions the language
    already accepts). Fixes the user-facing wart AND the __result rows in
    one move; the transform stays dumb (`put(v)` just works). Conformance
    rows owed for both payload kinds at the argument position; composes
    with unit 4's planned elaboration of ALL wrap positions to explicit
    `Ok(e)` constructor AST (this extends a list that gets desugared
    wholesale, not a mechanism we deepen).

  Recorded with them, from building it: FIVE census families proved
  wrong-shaped against reality and are deferred with reasons, not preference.
  (a) `opt_closure` — a frame closure is CALLED, and calling the result of a
  lend is not expressible (`self.f.value()()` parses as a tuple), so it owes a
  materialized local and a statement slot the expression rewrite does not
  always have; (b) every local whose ADDRESS is taken — `&x` anywhere, a
  nested suspending method call's receiver (P1), a `ref` argument (S9), and a
  `p?.x = v` head — because a `Slot` has no addressable payload spelling, which
  is exactly the `payload_ptr` 218a §4 deferred; (c) `Void` payloads
  (`Slot<Void>` is a pointer to void llvmlite refuses); (d) fixed ARRAYS
  (`a[i] = v` writes through element storage — the same addressing class);
  (e) a local a method call CONSUMES another local into (`v.push(move h)`) —
  DF-218h above, added at landing; (f) a move-only or ExplicitCopy local whose
  WHOLE VALUE is a rendering operand (`print("{e}")`) — DF-218i, likewise.
  Also found: the post-transform re-entry must RE-RUN the place lowering (the
  `value()` lends are emitted after that pass) and must NOT `uncheck` when it
  does (stripping the wraps the post-transform check inserted hands the next
  check `cannot assign Int to field of type Result<Int, IoError>?`).

  Landed with two more mechanisms the build turned up, both recorded in the
  commits: design 210's embed contract gains a SECOND kind of graft
  (`frame_slot_op` — re-checkable anywhere rather than pre-answered, because a
  `value()` lend becomes a window call only after the checker stamps
  `place_struct` on it), and `_check_payload_read` ASSIGNS
  `payload_needs_copy` instead of only adding it, because one node's source is
  a plain local on the first check and a place on the second and only the last
  answer is right.

- **DF-218b AMENDMENT (measured, Aug 14): the one-line flavor fix LEAKS.**
  Teaching `place_uses._method_mutates` that `Optional.take` is `&var self`
  (so an optional-typed place opens an EXCLUSIVE window) does remove the
  wrong-noun refusal — and changes drop behavior:
  `coro_iflet_move_scrutinee_releases_payload` moves from `t6 in 2 / t6 driven
  0 / t7 plain 0` to `t6 in 3 / t6 driven 1 / t7 plain 1`, i.e. a retained
  payload on the PLAIN path as well as the driven one. So the flavor decision
  and the write-back are coupled, and DF-218b's first half is not a one-liner:
  it owes its own analysis of what an exclusive window does to the payload.

- **QUEUED: the Rust-ism docs sweep** (user, Aug 13, after the Sync-doc
  catch) — audit LANGUAGE_SPEC/skill/README/builtin.saw doc comments for
  concepts described via RUST mechanisms rather than Saw's: Send/Sync
  phrasing (wave B fixes builtin.saw's), borrow/clone/RAII/destructor
  terminology (saw-docs bans some already), lifetime references, stale
  `T: Copy` semantics post-219. Dispatch AFTER wave B lands (it is
  rewriting the same docs; avoid conflicts).

- **QUEUED: the thread-sharing cookbook** (user, Aug 15, out of the
  DQ-222a probe session) — a LANGUAGE_SPEC section (+ a saw-lang skill
  digest line) answering "how do I build a type holding raw memory that
  multiple threads can safely share", which today is scattered across
  design 130's rules, builtin.saw's trait comments, and the
  Mutex/Arc/SpinLock sources. Content, all probe-verified Aug 15
  (`.build/scratch/probe_sendbuf.saw` + `probe_arc_tg8/9.saw`,
  GITIGNORED — the doc's examples must be rebuilt as compiling spec
  examples): the TWO-LEVEL recipe — Level 1: plain safe struct owning
  the buffer (raw pointer does not poison the type, Vector precedent;
  reaching methods carry `unsafe` + owe total soundness), ONE
  `UnsafeSend` assertion with its four obligations (heap-only, nothing
  thread-affine, deinit sound from any thread, no unsynchronized
  siblings), then `Arc<Mutex<T>>` composes mechanically (`Mutex<T:
  Send>: UnsafeSync` ignites, ran end-to-end under `threads: 2`);
  Level 2: internal atomics/SpinLock + `UnsafeSync` (obligation: the
  whole `&self` surface race-free under true parallelism) for
  lock-free sharing and `static` position (design 149 gate). Plus the
  two theorems worth stating: a mutex converts Send→Sync (serializes
  simultaneity, cannot un-migrate — why its Sync is bounded), and
  nothing upgrades !Send→Send except the type's own design; the
  universal fallback for any type is Channel-to-owner (remote
  operation, not shared access). Natural neighbor of the Rust-ism
  sweep above — same files, could be one dispatch. **DISPATCHED
  Aug 15 (one Opus agent, both parts), in flight.**

- **QUEUED: the doc-sync correctness scan, round 2** (user, Aug 15;
  SONNET by design — the fresh-reader-as-instrument logic, and every
  claim is oracle-checkable). Design 138 ran this Aug 6; ~85 designs
  landed since, and the Aug-15 design-158 staleness (three documents
  agreed with each other and disagreed with the tree) is the motivating
  incident. Scope: README.md, CLAUDE.md (the orientation digest — it
  may be a summary but must not be WRONG), LANGUAGE_SPEC.md, the
  saw-lang skill, all verified AGAINST THE CODE: every example
  compiles/runs as shown, CLI flag lists match sawc.py's argparse,
  stdlib/prelude surface lists match std/ and the actual gate, feature
  and status claims (built/not-built, "the ONLY", counts) match the
  tree, skill cheat-sheet spellings compile. Doctrine: where the CODE
  is authoritative (flags, surfaces, example behavior) the agent FIXES
  the doc; where the DOC may be stating intent the compiler fails
  (spec promises X, compiler does Y) it is a DF FINDING — report,
  never decide. SEQUENCED AFTER the in-flight docs dispatch integrates
  (it is rewriting the same files; scanning mid-rewrite audits stale
  text). Compile evidence required for every finding, per the sweep
  standard.

## Design 218 unit 0 LANDED (Aug 13) — corodiff is a battery lane; three new DFs

`tools/corodiff.py` (the coro differential harness, tracked), an 87-entry
`tools/corodiff_known.txt` ledger whose DF-217h and DF-217p blocks are
run-generated position matrices, and a `corodiff` battery stage (19s quick
mode). Full cross: 1514 twin pairs / 3028 programs, five tier chunks,
S3's axes (cancel, panic, MT `threads:2`) swept for the first time — no new
mechanism from cancel/panic/MT beyond confirming DF-217f/h reach them.
Three NEW findings, all lead-verified from standalone repros:

- **DF-217n — CLOSED (Aug 18, user-authored fix, lead-reviewed): `case
  Has(_)` on an owned enum drops its payload.** One call flipped in
  `codegen/match.py`'s consumed-`_` branch: `_emit_release_at` →
  `_emit_drop_at`. Release was a no-op for any AGGREGATE payload (a
  non-refcount-header struct never recursed — the pin's `Res{name:String}`
  leaked despite being auto-Copy) and deliberately skipped NoCopy deinit;
  drop recurses, and converges with release for a directly-refcounted
  payload. The old comment's `Map._slot_state` `Occupied(_,_)` hazard is
  DEAD PROSE from the pre-places world: the consume path requires an owned
  LOCAL or owned TEMPORARY scrutinee (match.py's `scrut_is_local` +
  `_is_borrowed_name` guard, the design-146 fix), and every Map peek
  matches a PLACE, which never reaches the branch — verified structurally
  and by the full suite (design-61 exactly-once rows green). Guards probed
  clean both sides of the patch: a failed `case Has(_) if cond` does not
  prematurely drop. Timing is documented: a `_` payload drops INLINE at
  extraction (deferred would leak through break/return/continue), a named
  binding at arm end. PIN flipped:
  `examples/match_wildcard_payload_released.saw`. The family matrix the
  entry owed landed as `examples/discard_forms_release_matrix.saw`
  (`let _` / `case Two(_,_)` / mixed `case Two(v,_)` / `if let _ = move`).
  Gated suite + sos both arches.
  LEDGER RETIREMENT ARRIVED LATE (Aug 18): the landing missed the
  three-artifacts rule — `tools/corodiff_known.txt`'s ten
  match_nobinding rows outlived the fix by a day, caught by the DF-217o
  gate's corodiff lane. Retired then; the fix also MORPHED the in_rhs
  cells' divergence from LEAK to DEINIT-ORDER (the driven twin's
  always-late teardown release, DF-217p's mechanism, now visible against
  a correct control) — two rows added under DF-217p's block, and its
  position matrix grows by the match_nobinding position.
- **DF-217o — CLOSED (Aug 18, user-authored fix, lead-reviewed): a spawned
  body with no suspension destructures tuples.** The DestructuringLet arm of
  `coro_transform`'s `_lower_stmt` blindly rewrote leaves into frame-field
  stores (`self.a = ...`) even when `_collect_frame_locals` had created no
  fields (it only adds destructured leaves that SPAN a suspension); the fix
  mirrors the LetStatement arm — when NO leaf is in `encmap`, keep the plain
  destructuring let with only the RHS rewritten (`cap_lets` + hosting still
  apply). Lead edge-probes, all green: all-wildcard `let (_,_)` (empty
  leaf_names falls to the old path, correct), `var` twin, nested tuple,
  mixed `(x,_)`, a leaf name-colliding with a frame-resident PARAM (the
  design-107 derived shadow — takes the old path, answers correctly), and a
  suspension BEFORE the let (plain let is legal mid-state-machine). PIN
  flipped: `examples/spawn_body_destructuring_let.saw`. Ledger retired:
  `tools/corodiff_known.txt`'s DF-217o block removed with the fix (the
  three-artifacts-together policy). Gated suite + sos + corodiff.
- **DF-217p (DEINIT-ORDER, 61 cells + 2 + 3 — the widest) — a driven frame
  local is released at FRAME TEARDOWN, not at its scope's end.** (+2, Aug 18:
  the DF-217n fix unmasked the match_nobinding/in_rhs cells — the driven twin
  always released the `_` payload late, invisible while the control twin
  leaked it entirely; morphed rows filed under this block in
  corodiff_known.txt. +3, Aug 21: design 237's full cross unmasked three more
  the same way — the two destructuring `in_rhs @ loop` cells, which did not
  COMPILE before its unit 2, and `match_consume/in_rhs @ linear`, whose ICE
  design 224 fixed and whose stale DF-217f row went on masking until unit 2
  retired it. Rows added under this block; none is a new bug.) A loop-body local
  outlives the loop; a design-107 shadow rebind holds the replaced binding
  to teardown where the sync twin drops it at the redefinition. Counts
  always balance (never a leak), but deterministic destruction is a
  headline guarantee — a `File`/`TcpStream` bound in a driven loop stays
  open for the rest of it. The known-list block IS the position matrix.
  PIN: `examples/coro_frame_local_released_at_scope_end.saw` (both faces —
  the loop-body local and the shadow rebind)
  **RULED Aug 20 (user): SCOPE-END REQUIRED** — the driven twin must agree
  with the sync twin; deterministic destruction is unconditional. The fix
  rides design 218 unit 2 (the transform emits safe Saw, so scope structure
  survives to emit per-scope releases); the corodiff known-list's 61+2 cells
  are the acceptance matrix, and the fix removes those ledger blocks in its
  landing commit per the harness-ledger rule. DF-217m's coro face follows
  this ruling.
  **CLOSED Aug 21 (design 218 unit 2, branch `design-218-u2`).** The funnel is
  `_FrameBuilder._scope_release_seq` over a scope map `_uniq_walk_block`
  already built and discarded; its entry points are the exit edges (E-FALL,
  E-BRK, E-CNT, E-RET, E-REDEF, E-STMT) and the docstring names them. WHAT a
  release is stays one decision, `_release_shape`, shared with teardown — so
  the deferred families are covered in the legacy spelling and deterministic
  destruction is unconditional (ruling 6). Details and the two deviations:
  designs/218b-scope-end-spec.md's landing note. PINS FLIPPED:
  `examples/coro_frame_local_released_at_scope_end.saw` + conformance row K70
  (seven scope kinds as twin pairs). Ledger: the whole DF-217p block retired.
- **DF-217h extended:** the `??` RHS is a tenth consuming position (husk
  release with an empty name), and `Vector.swap_out(i, f())` a second
  consuming-argument accessor; fires across linear/loop/cancel/teardown/MT,
  which pins it to the hoist, not the context.
  PIN: `examples/coro_hoisted_coalesce_rhs_consumed_once.saw`

## Design 218 — enforcement architecture (RULED Aug 13, staged)

Brief: `designs/218-enforcement-architecture.md`. The user's ruling: all
transforms happen BEFORE codegen, and transforms emit ordinary safe Saw over a
small manually-verified unsafe core (design 130's contract applied to the
compiler itself) — so the existing post-transform re-check genuinely validates
generated code, and the whole DF-217 ownership class becomes compile errors
instead of trusted bookkeeping. Five units: (0) the coro differential harness
becomes a battery lane FIRST — the net under the migration; (1) the `Slot<T>`
frame-primitive module, census-driven API, tag cost ACCEPTED by ruling;
(2) the coro transform migrates to safe code over it, `post_transform`
exemptions split then deleted one by one; (3) comparison/equality desugar to
AST, coordinated with the `other: &Self` brief; (4) the codegen
decides-vs-lowers census + standing ledger; (5) FUTURE, measurement-gated:
checked Slot elision — occupancy re-derived from the resume index as a proved
refinement, which is today's hand pattern earned back safely. The trusted-base
list at the brief's end is its most important artifact.

**Unit 1 LANDED (Aug 13)** — `sawc/std/compiler/frame.saw`: `Slot<T>`,
`UnsafeRef<T>`, and `Resumable` relocated from builtin.saw with a `release`
requirement (the transform's `__release` renamed to satisfy it; bodies
unchanged). Rows K27/K28 green. No transform emission migrated — that is unit
2. Details, including the first std module in a SUBDIRECTORY and the four
pre-existing design-82 name-reservation holes that landing a public `Slot`
exposed, in the brief's unit-1 paragraph.

## NEXT-WAVE SWEEPS (queued Aug 13, dispatch after the current fix wave lands)

- **S1 — the abstract-T boundary (DF-217i's class; HIGHEST SEVERITY).** One
  probe already proved corruption. Matrix: every tier- or effect-dependent
  rule x the generic laundering shape — copy-tier transfers (proven), `Send`/
  `Sync` at a generic `spawn` (plausible second soundness hole), NoMove
  pinning, design-146 place rules (verify the claimed coverage), unsafe-type
  contact, Deinit timing. Oracle: deinit counts + cross-thread data races vs
  the concrete-typed twin of the same body.
- **S2 — RUN (Aug 13). 117-row matrix in `.build/scratch/sweep_pos120/
  RESULTS.md`: 70 CORRECT, 16 MISCOMPILE, 12 ICE, 10 REFUSED.** The claim
  holds in ~65 of ~90 grammar positions. Findings, lead-verified where
  starred:
  - **DF-217h WIDENED into a class (*)** — the ANF hoist's temp for an
    owning value produced by a suspending call in a CHILD position is
    consumed by the parent and dropped AGAIN at frame teardown: free-fn
    args, struct-init/enum-ctor args, tuple-literal elements, multi-arg
    calls, `Vector.push(f())`, optional wrap, `?.` hops — nine positions,
    payload-refcount evidence (a shared `Arc`'s storage released under a
    live owner). Anchor: `_anf_lift` (coro_transform.py:1417) emits a bare
    temp with NO consume bookkeeping — contrast `_vc_hoist_to_temp:1738`
    which registers its temp. Agrees with worker C's independent narrowing.
    PIN: the four class files design 218a's flip list defines —
    `examples/coro_hoisted_struct_init_arg_consumed_once.saw` (a5/a6),
    `coro_hoisted_receiver_temp_released_once.saw` (b1-b4/m7),
    `coro_hoisted_push_arg_consumed_once.saw` (m14/h4),
    `coro_hoisted_tuple_element_consumed_once.saw` (p4)
  - **DF-217m (NEW, *) — SYNC-PATH LEAKS, no coroutine involved:** a
    by-value OWNING argument to a METHOD is never deinited, and a
    call-result temp RECEIVER (`mk(3).n`) is never deinited — three values
    created, one deinit, in ordinary sync code (`min_leak.saw`). The
    suspending twin drops exactly once, i.e. the coro path is CORRECT and
    the plain path leaks.
    PIN: `examples/sync_call_temp_released_once.saw`
    **CLOSED Aug 21. SYNC HALF by design 240 item 9 (branch `design-240`);
    CORO FACE by design 218 unit 2 stage D (branch `design-218-u2`) — E-STMT,
    the statement-end edge of the scope-end funnel. The UNWRAPPED
    call-result receiver's husk (`mk_opt(44)!.describe()`) and the `__rcvN`
    discard holder clear at the end of the statement the hoist lifted them
    from; the borrow READ is unchanged, only the husk's lifetime moved. Rows
    M1 (a driven by-value param — a frame's Done IS its return) and M2 (the
    plain receiver temp, already `take()`n since stage 2) owed nothing. PIN
    FLIPPED: `examples/coro_hoisted_receiver_temp_released_once.saw`.**
    The sync half's two codegen gaps, both
    where a shape had no cleanup scope at all:
      * an INSTANCE method was the one callable shape that never pushed a
        PARAM cleanup scope — a free function, a static method and an `init`
        all own their by-value params and drop the un-moved ones (design 42).
        `init` turned out to be missing it too (probed, fixed with it);
        `self` is deliberately never registered, whichever way it arrives,
        since a `&self` receiver BORROWS the caller's storage and its
        `variable_types` entry is the Self STRUCT type rather than a
        reference.
      * a FIELD READ off an owned temporary (`mk(3).n`) never registered the
        receiver, where a METHOD call on one already did.
    CONSUMER SWEEP (obligation 2 — the contract flips from "the callee leaks
    its by-value params" to "the callee owns and drops them", so every caller
    owes a transfer). Ordinary call sites already retain through
    `_gen_transfer_value`; the suite found exactly ONE synthesized site that
    did not, and it is design 239's recorded asymmetry —
    `String.equals`/`String.compare` take `other` BY VALUE (String conforms
    builtin, and `s.equals("literal")` must work), and `_emit_string_equals`
    / `_emit_string_compare` handed the operand straight through, balancing
    only while the callee leaked it. Both now retain, through one named
    helper. Caught by `df151i_tuple_copy` as an over-release panic, i.e. by a
    gmgate oracle rather than by reasoning.
    CORODIFF: the lane is GREEN (0 new findings, 11 known hits, all
    DF-217p), and there was NO DF-217m block in `tools/corodiff_known.txt` to
    remove — the harness's twin-parity axis never generated the two sync
    shapes, which is why sweep S2 found them by hand and why this pin exists.
    Recorded rather than left implicit, since the fixing commit was expected
    to retire ledger rows. Gated: full suite, sos both arches, corodiff and
    gmgate (51 programs under Guard Malloc, 0 failing).
  - **ICE family = statement-HEAD entry gaps — ALL CLOSED.** if/while
    conditions, `&&`/`||` LHS (RHS works), for-range bounds, and match
    scrutinees whose ctor args suspend (DF-217f + its struct-init sibling) all
    reached codegen unhoisted and died `Undefined function`; **design 224's
    container-HEAD hoist closed every one on Aug 15**, re-verified cell by cell
    by design 237's census. Bogus refusals: `??` LHS, `?.` HEAD and compound
    assignment RHS **also closed by design 224**; `return f()` under Result
    auto-wrap and DestructuringLet — DF-217g's REAL scope (the tuple literal
    itself compiles; `let (a,b) = ...` is what refuses) — **closed by design
    237 unit 2 (Aug 21)**.
  - Receiver-temp deinit TIMING drifts from the spec's promise (temp lives
    to frame teardown), lower severity.
  - **Funnel verdict — DISCHARGED by design 237 (Aug 21).** The verdict as
    written: one child-position funnel (`_uncond_children`) missing 3-5 node
    classes (EnumInit, RangeExpr, the ResultWrap family), entered from a
    scattered hand-enumerated statement set. What the census found of it: the
    ResultWrap family WAS missing and is now in; EnumInit was never missing
    (its arguments linearize, DF-133a order included); RangeExpr is a head and
    never a value, so `_head_lift` owns its endpoints by construction. The
    statement set is a TABLE now, and the head positions had already become
    design 224's own funnel (`control_heads`). `_anf_lift`'s temp-ownership
    bookkeeping was closed earlier, by design 218 stage 2's `Slot` migration;
    what it still owed was the POSITION's answer, which unit 3 gave it.
- **S3 — cancellation/panic teardown differential (DEEPEST UNKNOWN).** Extend
  the coro harness axes: cancel mid-suspend, cancel an io-parked task, panic
  mid-suspend, unjoined handles, group teardown order, and the MT
  (`threads: N`) contexts nothing has swept. Oracle: every frame slot
  released exactly once, deinit counts vs the uncancelled/unpanicked twin.
  (Also the harness's own named gaps: ImplicitCopy leak witnessing,
  match-arm-retain axis.)

## Obligation-4 retro triage of recent DF fixes (Aug 13 — BOTH SWEEPS RUN)

Reviewed the recent fix waves for class-shaped mechanisms; two sweeps
dispatched (checkpointed agents) and complete. Full matrices + probe files:
`.build/scratch/sweep_frame/RESULTS.md` and `sweep_labeled/RESULTS.md`
(gitignored — promote reproducers to cited pins before any `.build` clean), plus
the later differential sweep's `.build/scratch/coro_diff/RESULTS.md`.
DF-217x numbers are RESERVED here for these findings; the next authored
brief should skip to 218 or adopt them.

**Status (Aug 13): section 1 is CLOSED — all three frame-slot findings fixed,
each with its conformance row and position matrix, on branch
`worktree-agent-a94bfdce48f5369d5`.** Fixing them turned up two more, both from
sweeping the PREDICATES rather than the symptoms: DF-217l (fixed with them) and
DF-217h (open, pinned, wants its own dispatch). Section 2 (DF-216c / DF-217d /
DF-217e) is untouched and still open.

1. **Coro-frame owning-binding positions** (the DF-206a/b/f + DF-210a/b/f
   family). Ten positions probed at two tiers against non-suspending twins.
   Seven rows CORRECT/clean. THREE NEW FINDINGS — **ALL THREE FIXED Aug 13**;
   the differential sweep's extensions (both tiers for 217a, the
   auto-ImplicitCopy tier for 217c) are covered by the same fixes and named in
   the rows below.
   - **DF-217a — FIXED (`de7f49d` + coverage `2b9c185`).** Same-name shadow rebind across a suspend
     (`let s = derive(move s)`) double-freed and then panicked. Root cause:
     `_uniq_bind`'s reuse of an existing scope mapping, written for the
     parser's two views of ONE match-arm binding, also swallowed a design-107
     same-scope REDEFINITION, so both bindings shared a frame field. The reuse
     is now the caller's to ask for (`second_view=True`, the match pattern
     only). Tier-independent, as the differential sweep confirmed: rows S09 +
     `coro_same_scope_redefinition_owning_slots.saw` carry NoCopy AND
     ExplicitCopy, driven/spawned/loop.
   - **DF-217b — FIXED (`ea6c9da`).** `if let v = move opt` leaked in every
     driven function. Root cause: codegen's `_optional_binding_owns` read the
     ownership off the AST SHAPE (`isinstance(src, MoveExpr)`), and the
     transform's rewrite is exactly what deletes that shape — a `self_opt`
     field reads back as a plain `MemberAccess`, so all three of its tests said
     "borrowed" while `__saw_forget` had already told the frame not to release
     it. `_read_field` recorded the answer (`frame_move_read`) but stamped it
     only in its ForceUnwrap branch and nothing consumed it; it is now stamped
     on every shape (annotation moved to `Expression`) and read by the
     predicate. Rows O12 + `coro_iflet_move_scrutinee_releases_payload.saw`.
   - **DF-217c — FIXED (`d0f13c2`).** Root cause as suspected:
     `_materialize_closure_captures` spelled `.copy()` unconditionally. It now
     branches on `_frame_read_policy` — the extracted funnel `read_policy` sits
     behind, whose docstring names BOTH callers. `.copy()` is not a method
     every tier has, so the same bug refused a NoCopy `[move r]` capture AND an
     AUTOMATIC-ImplicitCopy struct (design 159's tier declares no `copy`) — the
     differential sweep's extension, cured by the same fix. Declared
     ImplicitCopy and ExplicitCopy come out byte-identical. Rows K26 +
     `coro_closure_capture_reads_by_policy.saw`.
   Obligation-1 verdict (held up): `read_policy` was the right funnel with a
   proven-incomplete entry list, and 217a/b were the ADJACENT class
   (frame-field identity/liveness) they were called.
   Two FURTHER findings came out of fixing them, both from sweeping the
   predicates rather than the symptoms:
   - **DF-217l — FIXED (`c783540`; committed under the colliding number
     DF-217i, renumbered at integration — DF-217i is the abstract-T
     boundary).** `if let _ = move opt` and
     `guard let _ = move opt` LEAK the payload they discard, with no coroutine
     involved at all: design 111's `_` rider dropped only a fresh-TEMPORARY
     payload, and a `move` scrutinee retires the source binding just as
     completely. Row O13.
   - **DF-217h — OPEN, pinned** (`examples/coro_hoisted_call_arg_consumed_once.saw`).
     A hoisted suspending call feeding an argument the callee CONSUMES by value
     is double-freed: the sub-frame's `__result` is forgotten correctly, but
     nothing then forgets the ANF TEMP the outer call consumed. DF-210f taught
     `_optbind_dispatch` this lesson for an optional scrutinee; a by-value call
     argument never learned it. NOT `Vector.set`-specific — a plain free
     function with a by-value NoCopy parameter does it too, and the second
     release reads a husk (empty name). A DIFFERENT chokepoint from 217a/b/c
     (the ANF hoist's temp lifecycle), and its fix owes a position matrix of
     its own: which argument positions consume (by-value NoCopy/ExplicitCopy)
     versus which do not (`&`/`&var`, an ImplicitCopy retain). Own dispatch.

1b. **Coro differential harness** (Aug 13, third retro sweep): a generator
   crossing binding constructs x copy tiers x suspend placements x contexts,
   oracle = parity with each program's non-suspending twin. Harness + full
   coverage log: `.build/scratch/coro_diff/` (RESULTS.md, gen.py,
   findings/). Re-confirmed DF-217a (now ALSO reproduces on ExplicitCopy,
   not just NoCopy) and DF-217b (across taskgroup/loop contexts). TWO NEW,
   both lead-verified against clean control twins:
   - **DF-217f (ICE) — CLOSED by design 224 (Aug 15).** The scrutinee is a
     container HEAD and no pass walked one; the head hoist lifts it and the
     ANF hoist then linearizes the constructor's argument out of the lifted
     `let`. Its own pin predicted this ("fixed alongside the other
     statement-HEAD gaps, which share the entry list"). Original: a suspending
     call as a LABELED enum-constructor
     argument that is itself a `match` scrutinee:
     `internal compiler error ... (FunctionCall): Undefined function: mk_s`.
     All four tiers, three contexts. Repro:
     `coro_diff/findings/NEW_enum_ctor_labeled_arg_suspending_call_ICE.saw`.
     PIN: `examples/coro_suspending_ctor_arg_in_match_scrutinee.saw` (both
     the enum-ctor and the struct-init sibling), now a passing test
   - **DF-217g (BOGUS-REFUSAL)** — a suspending call as a TUPLE-LITERAL
     element in a destructuring let (`let (a,b) = (mk_s(1), mk_s(2))`) is
     refused with the nested/expression-position error, contradicting design
     120's documented literals coverage. Control twin runs. All four tiers.
     Repro: `coro_diff/findings/NEW_tuple_literal_element_...refused.saw`.
     PIN: `examples/coro_destructuring_let_suspending_rhs.saw` (the
     rescoped shape — tuple literal AND suspending-call RHS)
   FINAL RUN (the harness completed after the interim report): 336 twin
   pairs / 672 programs, 1104 combos pruned with reasons logged, 264 pairs
   byte-identical, 60 flagged and triaged. Two more results:
   - **DF-217h (DOUBLE-FREE, lead-verified)** — `v.set(i, <suspending
     call>)` replacing a NoCopy element frees the REPLACEMENT value twice
     (repro prints `DEINIT r3` twice; overwritten element deinits once,
     correctly). The bare `v[i] = <suspending call>` spelling is a clean
     refusal (sync place-window rule), so `.set` is the exposed path.
     Likely the DF-210f mechanism (hoisted temp keeps its claim). Repro:
     `coro_diff/findings/NEW_vector_set_suspending_rhs_double_free.saw`.
   - **DF-217c EXTENDED** — the capture-materialization bug also refuses
     an AUTO-ImplicitCopy struct capture (`type Bag is not Copy`) called
     after a suspend; the original filing assumed non-NoCopy tiers were
     unaffected. The fix's "keep other tiers identical" bar applies to
     tiers that WORK today, not to this refusal, which is part of the bug.
   Remaining coverage gaps (harness rerunnable): non-main contexts a
   curated subset, match-arm-retain axis unimplemented, no ImplicitCopy
   leak witnessing.
   **Part 0 ranked UNSWEPT class candidates from the full DF history**
   (detail: `coro_diff/part0_table.md`): DF-193b (move-inside-container-
   literal gap, only struct-literal position tested) #1, then DF-206d (two
   independently-maintained suspending-call recognizers), DF-196e (N=2-only
   closure-collision fix), DF-210c, DF-193c, DF-204a/b. Caveat: ~126 of ~185
   DF ids were classified from their opening sentence only.

1c. **DF-217i — FIXED (design 219 wave C, Aug 14), and with it the whole S1
   family below: DF-217j, DF-217k, DF-217q and row C07. Kept for the sweep
   evidence, which is the map wave C was built against.** The requirement is
   inferred once at the definition and discharged at every call; the two
   declaration rules derive per instance. Rows V36-V47, K30, K31, U30.

   **DF-217i (SOUNDNESS, lead-found + verified Aug 13) — a generic body
   evades the copy-tier rules; instantiation never re-checks.** An UNBOUNDED
   `func launder<T>(x: T)` whose body binds `x` twice (`let y = x; let z =
   x`) compiles — no Copy bound demanded, no move checkpoint applied to the
   second read — and instantiated at a NoCopy type prints THREE deinits for
   ONE value, the payload read AFTER two of them (use-after-free), from
   fully safe code. Repro: `.build/scratch/generic_evasion_probe.saw`.
   PIN: `examples/generic_body_honors_copy_tier.saw` (EXPECTs the refusal
   the concrete twin already gets; the fix DIRECTION stays unruled)
   Mechanism: a generic body is checked ONCE with `T` abstract, and
   abstract `T` is treated as the MOST permissive tier instead of the
   least; nothing re-judges the body (or the bound-discharge site) at the
   concrete type argument. Same boundary as the 216b matrix's open row C07.
   Design 146 covers PLACE reads in generic bodies (`v[i]` needs a Copy
   bound); plain parameter/local reads of type `T` have no such rule.

   **SWEEP S1 RUN (Aug 13, 30 probes; matrix + repros in
   `.build/scratch/sweep_absT/`). The boundary leaks THREE independent rule
   families; Send is the sound counterexample.** DF-217i widened: a bound
   does not help (`T: Printable` unchanged), **`T: Copy` does NOT close it**
   (ExplicitCopy satisfies Copy but still owes `.copy()`/`move` — SIGTRAP),
   nesting widens multiplicatively (6 deinits for 1 value at two levels),
   generic METHODS leak identically, and — the design-218 hit — **a generic
   COROUTINE leaks across a suspend (row p08a, lead-verified: 3 deinits +
   use-after-free), because the post-transform re-check sees only abstract
   `T`: "the generated code typechecks" is satisfied VACUOUSLY there.** Two
   NEW findings, both lead-verified:
   - **DF-217j (RUNTIME ABORT from safe code) — the NoMove containment
     cascade is never derived per instantiation.** `struct Wrap<T>` declared
     NoCopy, instantiated at NoMove `TaskGroup`: `move w` compiles, and a
     spawn-move-spawn sequence dies `panic at taskgroup.saw:1008: force
     unwrap of None` — exactly the abort design 188 exists to prevent. The
     COPY policy of `Wrap<Res>` IS monomorphized (p04g refuses correctly);
     the NoMove cascade just never meets the same machinery (concrete twin
     p04e refuses at declaration). Repro: `p04f2_nomove_taskgroup_live.saw`.
     PIN: `examples/generic_container_nomove_cascade.saw`
   - **DF-217k (declaration hygiene) — the design-130 unsafe-signature rule
     skips monomorphized signatures.** `idn<T>` at `T = UnsafePointer<Int8>`
     compiles undeclared; the concrete twin is refused. Memory-safe (the
     caller rule still fires) but the signature lies about its domain.
     PIN: `examples/generic_instantiation_unsafe_signature.saw`
   FIX-BOUNDARY EVIDENCE (for the ruling): Send is checked
   POST-MONOMORPHIZATION with concrete-type diagnostics naming the mangled
   instance — the existence proof that per-instantiation re-judgement is
   built and wired to frames; design 146's place rule fires at the ABSTRACT
   check with the doctrine diagnostic ("copy for some instantiations, alias
   for others") — the model for a bound-vocabulary fix, but 9d shows that
   vocabulary must be TIERED (Copy alone is not a license to bind twice);
   call-site bound discharge (p09c) works but only fires when a bound is
   written. DF-217j sits outside all three: a type-declaration cascade
   needing the containment rule derived per instantiation the way copy
   policy already is. Not covered by S1: Sync (no forcing construct built),
   UnsafeSend/UnsafeSync assertions, trait-requirement/existential dispatch
   positions, const generics, enum-payload/fixed-array cascades.

2. **Labeled-call recognition divergence — hypothesis mostly REFUTED, and
   the refutation redraws DF-216c.** 11-recognizer census, 25 probe rows.
   Labeled and positional are byte-identical everywhere probed (effect census,
   ANF hoist, spawn lowering, `?.` call heads, transfer checkpoint, `&var`/
   exclusivity, free-fn overloads + inference). Two funnels exist and work
   (`_rewrite_labeled_calls` coro_transform.py:5981; `_infer_label_mapping`/
   `_bind_args` expressions.py:2311-2700). The real findings:
   - **DF-216c CORRECTED — the fault axis is METHOD-vs-FREE-FUNCTION, not
     labeled-vs-positional.** Generic method calls fail on EVERY spelling
     (positional: byte-identical inference error; explicit type-arg: two
     further distinct wrong diagnostics; labels misreported as unknown). The
     method-side inference path (expressions.py:8367-8440) is a second,
     independently written caller of the label-mapping funnel, defective as a
     whole. Brief updated.
   - **DF-217d (ICE) — `func probe<U = Int>(other: U = 7)` on an extension,
     called `h.probe()`**: internal compiler error (`Type of #1 arg mismatch:
     i64 != %"Plain"`). Free-function twin clean. The 216c family's sharpest
     member.
     PIN: `examples/generic_method_default_type_and_value_param.saw`
   - **DF-217e — CLOSED (Aug 17), and the diagnosis in the filing was wrong.**
     Labels were never ignored: the method identity test has been label-aware
     since design 66. It sliced a hardcoded `self` off EVERY method, and a
     STATIC extension method has none in its parameter list — so its first real
     parameter, TYPE and LABEL together, dropped out of the key, and any two
     statics agreeing on everything after slot 0 collided. That is exactly why
     the reported pair (differing in the only label there is) was refused while
     `labeled_overload_method_static.saw`'s pair (differing in its SECOND
     label) passed. The same off-by-one reached the MANGLER, so two such
     statics would also have collided in the LLVM symbol table. Both sides read
     `_overload_cand_offset` now — the notion `_resolve_overload` uses at the
     call site — which is the funnel obligation 1 asks for. Matrix:
     `examples/method_overload_static_first_param.saw` (first label, first
     type, arity, and the second-label control), reject side
     `examples/errors/method_overload_identical_signature.saw`. PIN flipped:
     `examples/method_overloads_distinguished_by_labels.saw`. Gated on suite +
     `sos_runner` both arches.
   - **DF-217q — CLOSED (Aug 17): a STATIC extension method reached through an
     INSTANCE is a clean error; the TYPE spelling is the only way to call one.**
     The ruling took the refusal reading rather than fixing the binding: a
     static has no `self`, so there is nothing for the receiver to become, and
     giving one method two call shapes buys nothing. `b.solo(index: 4)` reported
     ``solo` has no parameter named `index`` with ONE method declared — the
     call-site parameter offset sliced a `self` slot the callee does not have,
     so every label lined up against the wrong parameter — and where the labels
     did bind, codegen passed the receiver as argument 0 and failed the verifier
     (`Type of #1 arg mismatch: i64 != %"Bag"`).
     The refusal is at the instance-call path in `_check_method_call`, and it is
     "a static is not a CANDIDATE here", not "a static is invisible from a
     value" — two things had to hold together. `struct_info.methods` keeps the
     FIRST-registered overload as the representative, so a lookup for a name a
     type carries at BOTH kinds can hand a static back to an instance call;
     `_instance_method_alternative` re-asks for an instance overload before
     refusing. And `_scoped_method_overloads`' result is filtered for the
     instance path, so a mixed set resolves among the instance methods alone
     instead of letting a static win on arity. ENUM receivers come free —
     design 145 gives enums statics on the same terms and the same lookup
     answers for both, which the pin covers as its second row.
     PIN `examples/static_method_called_on_instance.saw` FLIPPED to the refusal
     (both receiver kinds, with the two legal type-spelled calls in the same
     file so the fix cannot pass by refusing everything); companion
     `examples/static_and_instance_method_share_a_name.saw` is the positive
     half. `method_overloads_distinguished_by_labels.saw`'s note updated —
     DF-217e's declaration-site fix and this call-site one are now both closed.
     **Consumer sweep: the suite was the census and it found exactly one.**
     Conformance row V39 (`V39_generic_method_body_honors_copy_tier.saw`) wrote
     `func dup(x: T)` — no `self`, so a STATIC — and called it `w.dup(...)`
     through an instance. It only resolved at all because this path was broken,
     and it wanted an instance call: the row's claim is that the RECEIVER's type
     arguments are the whole discharge, which a `Wrap<Res>.dup(...)` spelling
     would have written at the call instead. Given its `&self`, the row asserts
     what it always meant.

Reviewed and NOT owed a sweep (mechanism already funneled or swept by its
fix): design 196's erased-error family (one canonical spelling, unit 2; the
capture funnel + positions, unit 4), DF-176c (design 200 unit 3 committed its
sweep record), DF-203a/b (fix installed `really_suspending` as the ONE shared
definition, four routes named), design 195's platform-width family (units
quantified over ALL typed operands / ALL value-branch arms; remainder is
design 205's authored brief).

## Design 215 — the LLM client (Python reference LANDED; Saw stages A-C LANDED Aug 26; D-F future)

Brief: `designs/215-llm-client-saw-port.md`. Both programs sit in
`devtools/dogfood/programs/`. User order (Aug 12): Python first, port
second, debugging language issues as they surface.

**LANDED — `llm_client.py`**, the reference and the port's spec: stdlib
only, OpenAI-compatible `/v1`, with streaming, tool calling, gated file
editing, a system-prompt file, and an interactive REPL (vi bindings,
persistent history, slash commands). Verified against LM Studio on
`Mac-Studio.local:1234`.

**ALSO LANDED — `llm_client.saw`, REWRITTEN Aug 26 as stages A-C**
(dogfood agent, design 203 instrument; cherry-pick 3b3ec748): one-shot
chat, `/v1/models` + non-embedding auto-pick, `--stream` printing each
SSE delta as its HTTP chunk arrives (both body framings decoded:
Content-Length and chunked), `--system-prompt`/`--temperature`/
`--max-tokens`, hand-rolled JSON both ways (fourth std.json consumer).
Verified against a trap-laden loopback mock — decoy `"content"` key,
surrogate-pair emoji, 0.4s-spaced SSE frames proving incremental
arrival, a 400 path quoting the server detail. The first attempt it
replaces had bit-rotted at design 234's allocator flip. ~~Carries ONE
workaround: every suspending TcpStream op is `try!`-unwrapped rather
than matched (DF-215f below is why), so the connect-failure path exits
via panic instead of the designed ClientError line — DEBT the DF-215f
fix repays (the comment at the workaround site says so).~~ **DEBT REPAID
Aug 27** (design 247 unit 2): `send_request` returns
`Result<TcpStream, ClientError>` and matches both `connect` and `write`,
`must_read` became `read_chunk -> Result<Data, ClientError>` and its
seven call sites take a propagating `try`, and an unreachable port now
exits via the designed line (`error: could not connect to 127.0.0.1:9:
io error: connect failed (connection refused)`, status 1) instead of a
panic.

**Environment fact worth carrying beyond this brief:** macOS 15+ gates
Local Network access PER APP, so an unapproved binary gets
`EHOSTUNREACH` for ANY LAN address while loopback works. Not a Saw bug —
a freshly `cc`-built C binary behaves identically. Every future net
dogfood program on this machine will hit it.

Four findings from the attempt, all probe-reduced (evidence and repros in the
brief), plus one the DF-215a fix turned up:
- ~~**DF-215a — std.net can name NO remote-connect failure.**~~ **CLOSED**
  (Aug 15). The five off-loopback errnos are mapped on both hosts to five
  new SysError tags (17-21), `IoError.errno()` is now `code()` because it
  never returned an errno, and `examples/net_unroutable_connect_names_the_cause.saw`
  is the suite's first test that leaves loopback. Widening the tag table is
  additive, not an ABI change — the reading that licenses it is written into
  rt/ABI.md beside the table. REMAINDER (the other half of the Aug-4 stdlib
  review's M14, not fixed here): `code()` still hands back a bare `Int`, so a
  caller branching on the cause cannot `match` it exhaustively. A public
  raw-backed `SysError` enum in std.net is the shape; it wants a ruling on what
  an unknown tag becomes, since `from(raw:) -> E?` answering `None` would hide
  the very cause this finding was about.
- **DF-215e (OPEN, found while fixing DF-215a) — `IoError.from_errno` is a
  public std factory over a seam rt/ABI.md calls runtime-INTERNAL.** It reads
  errno through `__saw_rt_last_syserror`, which is sound only on the statement
  after a failing `__saw_rt_*` op; a public entry point invites the read at
  arbitrary distance, which is the v1 `tcp_listen` clobber the design-117 status
  convention exists to make impossible. Zero callers, and its comment claimed a
  job (backing file/directory/env) those modules stopped needing at 117. Comments
  corrected; whether the factory should exist is a ruling, since deleting a
  `public` std member is a surface change. `sawc/std/net.saw:413`.
- **DF-215b — `move` of a frame local in a nested block's TAIL
  expression is refused in a suspending body.** 25-line repro, ready to
  become a cited pin; the diagnostic's advice does not apply.
- **DF-215c — hand-written JSON pays `\{` at every brace**, since a bare
  `{` in a literal opens an interpolation.
- **DF-215d — the wrapped `&&` (DF-172d) re-confirmed.**

Five more from the Aug-26 stage A-C rewrite (evidence, matrix and
acceptance transcript in the brief's rewrite section; DF-215c was also
re-hit verbatim as the fresh reader's FIRST error, strengthening its
case for a diagnostic fix):
- **DF-215f (SOUNDNESS — USE-AFTER-FREE; filed Aug 26) — a payload
  moved OUT of a suspending call's `match` is released AGAIN when the
  value leaves the enclosing function.** All three legs required —
  suspending scrutinee, a `move`-out arm, the moved value crossing the
  function return (tail auto-wrap and `return move` alike) — and
  removing any one is clean, which is the pin's five-row matrix:
  `examples/coro_match_moved_payload_survives_return.saw` (XFAIL;
  deterministic — the Arc-instrumented payload prints its DEINIT while
  the caller still holds it, then the second row dies). Manifests as
  Arc refcount underflow, early deinit, or SIGSEGV depending on payload
  type; in the wild it corrupted a `TcpStream` moved out of `connect`'s
  match and a `Data` out of `read`'s. Same family as DF-218w/DF-242a —
  a frame-owned release placed blind to what an arm moved out — but a
  DOUBLE RELEASE of an owned payload, not a timing divergence.
  OBLIGATION-4 SWEEP OWED before the fix dispatches: the container-head
  hoist's frame temp is one of several frame homes a moved-from value
  can still be released from (DF-242a's try-body edge and DF-255a's
  consumed capture are known siblings); the sweep enumerates the rest
  of that family and the fix targets the mechanism.
  SCHEDULED Aug 26 at the HEAD of [QUEUE] (user: a correctness bug
  outranks everything scheduled). SWEPT Aug 27 (lead-dispatched, launched on
  the user's "let's launch DF-215f"): ONE mechanism — the legacy
  `__matchN`/`__hoistN` scrutinee-temp encoding design 218 stage 2 never
  migrated, whose merge-point release trusts a DF-210f forget that only
  fires for FRAME-RESIDENT bindings, while codegen's consume model judges
  scrutinee SYNTAX and sees a frame field as neither local nor temporary —
  and the RETURN-CROSSING LEG IS FALSIFIED: move-out to any destination
  double-releases (the pin's `local_use` row asserts Clean and is wrong;
  the Arc idiom hid the underflow — NoCopy printing-deinit is the honest
  detector). Five-condition boundary, 12 affected / 16 clean cells, matrix
  and mechanism in designs/247-scrutinee-temp-migration.md, whose fix
  (DISPATCHED Aug 27) is the take()-read migration.
  **CLOSED — FIXED Aug 27** by design 247, all three units on branch
  `worktree-agent-a15c1414bca26ee3b`. `FAM_SCRUTINEE_TEMP` is RETIRED, not
  narrowed: `__hoistN`/`__matchN` — and `__headN` with them, design 224's
  container-head lift being the same single-use shape — read with `take()`
  like every other hoist family, so the temp is emptied AT the read and what
  reaches codegen is an OWNED TEMPORARY, which is exactly what its existing
  consume model (the SYNC lowering, always correct) is written for. The two
  edges the legacy encoding needed are deleted with it — E-STMT/2c
  (`_scrutinee_temp_release`) and DF-218w's E-ARM (`_arm_claims_no_payload`)
  — along with the DF-210f forgets in `_optbind_dispatch`/`_split_match` and
  the `_hoist_temps` set that fed them; `_optbind_dispatch`'s docstring had
  said the rule would go "with the last of them", and this is that landing.
  IR-verified at -O0: the scrutinee is `Slot…_take`, codegen spills it into
  `%match_scrutinee` (DF-151d), each arm binding gets a real drop flag, and
  the `move` clears it — one owner throughout, no `__saw_forget` anywhere
  near it. Regression matrix: the corrected pin plus
  `coro_driven_match_move_out_releases_once.saw` (five destinations, three
  controls), `coro_match_move_out_releases_once_in_loop_try_and_task.saw`
  and `coro_iflet_move_out_releases_once.saw`. **DF-218w's residue pin
  (`coro_mixed_match_payload_released_at_extraction.saw`) FLIPPED and its
  marker is gone**, as the brief predicted — the mixed `case Both(v, _)` is
  the arm shape no driven-only edge could take and needs none once the
  scrutinee is a temporary. **DF-262a is DISSOLVED** (the refusal whose
  spelling leaked `self.__head0` was the head temp's `value()` lend; a
  take-read head has no place to refuse — probe compiles and single-releases
  at both its shapes), and **DF-262b still reproduces verbatim** (unrelated:
  an ANF/auto-wrap ICE). One unfiled divergence closed on the way:
  `if let _ = <suspending>` now drops its payload where the sync twin does
  (DF-218w's shape at the optional-binding spelling), pinned as a twin pair.
  Conformance row V50 (added ahead of the fix as unit 0) and K73 both
  updated. `tools/test_forget_purge.py` drops `scrutinee-temp` from its
  family set; no live corodiff/sawfuzz ledger entry named this mechanism, so
  none was removed. Unit 2 repaid the llm_client debt below.
- **DF-215g — bidirectional inference does not resolve a bare `None`
  compared `==` against a CALL expression's fully determined optional**
  (`find_thing(5) == None` is "cannot tell what this `None` is a `None`
  OF"; the same compare against an `Int?`-annotated local compiles).
  `.is_none()` is the workaround and the better idiom, but the refusal
  contradicts "infer when accurate" — the LHS type is determined by the
  callee's signature. Probe: `.build/scratch/probe_none_eq_call.saw`.
- **DF-215h — no newline-free stdout write exists.** `print` appends
  `\n` unconditionally and no std surface exposes a raw stdout handle,
  so incremental output — this client's `--stream` deltas, any progress
  meter — prints one line per piece. Wants a surface ruling: a
  `print`-family variant vs a stdout handle in std.
- **DF-215i — no boolean `guard cond else { }`** — only `guard let`;
  every plain bounds check falls back to an inverted `if`. Wants a
  ruling on whether the omission is deliberate.
- **DF-215j — `return` inside a VALUE match arm is a bare parse error**
  ("Unexpected token: RETURN") with no hint that arms are expressions —
  brace the arm to return, or drop the `return` and let the arm's value
  auto-wrap. The dogfood reader chased the wrong fix first.
  Diagnostic-only, so no pin.

Docs nits from the same rewrite, fixed on discovery (Aug 26): the spec
now states `byte_at`/`bytes()` return SIGNED `Int8` directly instead of
via a parenthetical (the reader wrote ~25 `u8`-literal comparisons
first). SUPERSEDED same day: the user ruled the TYPE was the bug, not
the wording — the String byte surface flips to `UInt8` as design 244
(`designs/244-string-byte-surface-unsigned.md`, queued behind DF-215f),
and the patched spec passage flips with it. Still open as a docs
QUESTION, not a DF: no user-facing doc enumerates the std method
signatures (exact overloads, labels), so the dogfood agent discovered
several via compiler-diagnostic candidate lists — `--emit-docs` exists
and may be the answer.

Port blockers, staged A-F in the brief: DF-215a DONE; stage C's
incremental reads DONE (Aug 26, in-client chunked/SSE decoding —
NOT a std surface); **std.json — tool use (stage D) is where
hand-rolled JSON stops working, this rewrite is its fourth consumer**;
a `TcpStream` read deadline; and **a line-editing story for stage E,
probably its own brief**, since Saw has no terminal surface at all.
STAGE D HALF-LANDED Aug 27: std.json unit 2 (`JsonEncoder`/`JsonDecoder`
over the serde seam + `encode_json`, sawc/std/json.saw + JSON.md + five
exact-fault tests) integrated at ae670624, suite + freestanding green on
main. The `JsonValue` tree half is the [QUEUE]'s event-gated unit 1,
blocked on design 246; the build filed DF-265a/DF-266a and corroborated
DF-260a's mechanism. OPEN riders recorded in the unit-1 queue line;
`max_items` parity with CborDecoder was scope-narrowed out and stays open.
UNIT 1 ALSO LANDED Aug 27 (e2464f70, after design 246 unblocked recursion):
`JsonValue` (NoCopy, Vector/Map payloads) + `parse` with byte offsets over
the shared lexical helpers + compact serialization + Optional-returning
accessors, six tree tests; that build filed DF-267a-d. `OBJECT`
SERIALIZATION LANDED Aug 28 (DF-267b/DF-267d stage 2, see the [QUEUE] entry
and the DF-267d entry above) — no longer open at this stage. STILL OPEN:
combined member/element accessors (behind DF-267c), `Number` Float support
(no correctly-rounded std Float<->text surface exists; Int-only meanwhile),
pretty-printing, `max_items` parity. Design 249 later renamed the one-call
`encode_json` -> `encode`; design 250's Byte migration counts json's byte
internals among its census rows.

## Design 213 findings — the closure-callable sweep (Aug 13)

- ~~**DF-213a — a closure body could not raise an error out of itself.**~~
  **CLOSED by design 213** (Aug 13). Two LLVM ICEs, both members of DF-212a's
  mechanism (see that entry and the brief's position matrix): a `try` inside a
  closure was validated against the ENCLOSING function's Result, so a `try` in
  an `Int`-returning closure was accepted whenever the outer function returned
  a Result and codegen emitted the Result out of an `i64` function; and a
  closure written inside an outer `try {} catch {}` inherited that catch, which
  lives in a frame the closure's error path never reaches. Both are clean
  diagnostics now, and codegen carries the closure's own return type.

- ~~**DF-213b — a closure declared `-> Result<T, E>` does not auto-wrap
  its TAIL value.**~~ — **FIXED Aug 22 by design 234 unit 1**, which found it
  again from a different angle and filed it as DF-232h; the two entries are
  one defect and one fix (`_autowrap_into_result`, the funnel extraction, with
  the closure tail as its fourth entry point). DF-213b's own repro
  `call_res({ x in let v = try f(x)  v })` compiles and prints 4. A named
  function returning `Result<Int, E>` auto-wraps a bare `n` tail into `Ok(n)`;
  a closure with the same declared return type did not, so that call was
  ``argument `body` expects `(Int) sync -> Result<Int, E>` but got
  `(Int) -> Int` ``. `return v` worked — the `return` path wraps — so the
  workaround was one keyword, which is why this was a wart rather than a
  blocker. Exposed while writing design 213's position matrix (leg 9 of
  `examples/closure_return_is_local.saw` carried the `return` spelling and a
  comment citing this entry, now updated); NOT caused by it — the tail-wrap gap
  predated the closure-callable funnel and lived in `_check_closure`'s
  post-body reconciliation, which handled the OPTIONAL auto-wrap and had no
  Result twin.

## Design 212 findings — the long-function decomposition sweep (Aug 12)

- ~~**DF-212a — `return` inside a closure literal is checked against the
  ENCLOSING NAMED FUNCTION's return type, not the closure's own.**~~
  **CLOSED by design 213** (Aug 13), which ruled that a closure's `return`
  returns FROM THE CLOSURE. The obligation-4 sweep found DF-212a was one of
  SEVEN readers of "what callable am I in" that a closure body never
  updated — two of the others (a `try` in a non-Result closure, and a
  closure's `try` routed to the OUTER frame's catch) reached codegen and
  ICEd; see the brief's position matrix. All seven now ask one funnel,
  `_return_target`. Pin + matrix: `examples/closure_return_is_local.saw`.
  Original text:

  **DF-212a — `return` inside a closure literal is checked against the
  ENCLOSING NAMED FUNCTION's return type, not the closure's own.** Hit while
  extracting unit 4's arg-scanner closures (`blade/src/cli.saw`), which
  wanted an early `return 1`/`return 2` to report how many tokens a branch
  consumed. `_check_return_statement` (`sawc/typechecker/statements.py:2825`)
  reads `self.current_function`/`self.current_method` unconditionally — it
  never tracks entry into a `ClosureExpr`, so a `return` textually inside a
  closure is type-checked as if it were a `return` from whichever `func` or
  method lexically contains the closure. When the two return types disagree
  this is a loud, confusing error (a closure returning `Int` reports
  `expected return type` as the OUTER function's unrelated type); when they
  happen to agree it would silently compile with the WRONG target — untested,
  but the mechanism gives no reason to expect otherwise. `designs/todo.md`'s
  own DF-187c entry (design 187, "Design 185" section) already describes the
  coro_transform's OWN model as "a closure's own `return` is untouched" when
  rewriting suspending bodies — i.e., the compiler's mental model already
  assumes closures have local returns; the typechecker's `_check_return_statement`
  just never implements it. Minimal repro:
  ```saw
  func call_it(body: (Int) -> Int) -> Int { body(5) }
  func outer() -> String {
      let r = call_it({ x in
          if x > 0 { return 99 }
          0
      })
      "r={r}"
  }
  ```
  `error: expected return type `String` but got `Int`` — pointing at `return
  99`, which correctly would want to return `99` from the closure (typed
  `(Int) -> Int`) but is instead checked against `outer`'s `-> String`. NOT a
  blocker for unit 4 on its own: this codebase's established closure idiom is
  already value-expression tails (`if`/`match` as the closure's last
  expression, no `return`), which every existing closure in
  `sawc/std/taskgroup.saw` already uses. Superseded as unit 4's actual blocker
  by DF-212b below, which rules out passing a closure to the helper at all.

- **DF-212b is FIXED (Aug 13).** The pin
  (`examples/crossmodule_embed_type_identity.saw`) is EXPECT success, and the
  census found the finding was a CLASS with TWO mechanisms, each with its own
  position matrix test:
  - **Unit 1 — the declaration annotation's KIND was never settled.** The two
    `Cmd`s agreed on identity and disagreed on KIND: the expected side was the
    struct FIELD's raw annotation, still carrying the parser's default
    `TypeKind.STRUCT`. `_types_compatible` bridges that gap by ASKING A
    NAMESPACE (`has_enum`), and the entry namespace reaches a provider's enum
    only DEEP — so the identical pair of types answered True, True, True,
    FALSE across the four comparisons a compile makes, the last one inside the
    spliced body. `_stamp_annotation_kind` (typechecker/types.py) settles the
    kind inside `_canonicalize_module_types`, the funnel that already settles
    the design-144 NAME half per module, in place on the `SawType` objects the
    symbol tables share. Matrix:
    `examples/crossmodule_embed_annotation_positions.saw`.
  - **Unit 2 — a TYPE-NAME head is not an opening.** `Cmd.Build`'s head names a
    type, is never checked as an expression, and so carries no `resolved_type`;
    design 210's `_close_embed_marks` read that absence as an opening and
    cleared the enclosing subtree's marks, re-running DF-206e. Three shapes
    failed and now pass — `take(Cmd.Build)`, `idn<Cmd>(Cmd.Build)`, and
    `deeper.deep_value()`, the last being the ``undefined variable `builder```
    shape `_check_preserved_embed`'s own docstring names. `_is_type_name_base`
    (coro_transform.py) is the predicate, and it is the ABSENCE itself rather
    than a fourth copy of the ~10 family-2 markers the three type-name ladders
    stamp between them. Matrix:
    `examples/crossmodule_embed_type_name_head.saw`.
  - **Unit 3 — the stamp must not eat a TYPE PARAMETER's name.** A regression
    unit 1 introduced, found by probing its own worst failure mode rather than
    by a test: `struct Holder<Cmd> { v: Cmd }` beside an `enum Cmd` stopped
    compiling. `SawType.substitute` recognizes a parameter reference through
    the STRUCT arm and has none for ENUM (an enum name is nominal), so the flip
    made monomorphization skip the field in silence. The walk now accumulates
    the type-parameter names it descends through, and they nest. Pin:
    `examples/generic_type_param_shadows_type_name.saw`, verified to pass both
    BEFORE unit 1 and after unit 3.
  Reuse verdict on `type_identity.py` (218 unit 1's Poll fix): NOT reused and
  not needed — the identity half was already correct on both sides; the gap was
  purely the kind. See DF-210c for what is still unstamped.
  The original entry follows, unchanged.

- **DF-212c (RECORDED, pre-existing, found while fixing DF-212b) — a generic
  EXTENSION whose type parameter is spelled like a module type name loses every
  method.**
  ```saw
  enum Cmd { case Build }
  struct Holder<Cmd> { v: Cmd }
  extension Holder<Cmd> { func get(&self) -> Cmd { self.v } }
  h.get()   // error: type `Holder` has no method `get`   hint: no methods defined
  ```
  The struct, enum-payload and free-function forms of the same collision all
  work (pinned by `examples/generic_type_param_shadows_type_name.saw`); only the
  extension form does. Bisected to BOTH sides of DF-212b's landing — identical
  failure before and after — so it is not that fix's doing and was left alone
  under stop-don't-workaround. Suspicion: extension registration keys the
  specialization on the canonicalized parameter name, which the collision maps
  onto the enum's identity. The "no methods defined" hint says the extension
  registered under a key the call site does not compute.

- **DF-212b — RESTATED Aug 13 by design 213 units 5-7: the CLOSURE IS
  INCIDENTAL, and so is the "second identity" reading.** The minimized repro
  (`examples/crossmodule_embed_type_identity.saw` + `examples/modules/
  embed_provider.saw`, pinned XFAIL) is 25 lines and contains no closure at
  all: a suspending EXTENSION METHOD in module A that constructs a struct with
  an ENUM-typed field, called from a module-B `main` that transitively
  suspends. The closure in the original bisection was only the cheapest way to
  make a function suspending — a non-`sync` function-typed parameter is
  conservatively suspending, so `scan_args` suspended, so `parse` did. Swapping
  it for a plain `yield_now()` reproduces identically.
  **What the two `Cmd`s actually are** (instrumented, Aug 13): NOT two module
  identities. The EXPECTED side is `TypeKind.STRUCT`, `struct_name='Cmd'`,
  `symbol=None` — an UNRESOLVED field annotation still carrying the parser's
  default kind for a bare named type; the ACTUAL side is the real
  `TypeKind.ENUM` with its `EnumSymbol`. They print the same because display
  renders the name. A STRUCT-typed field of the same shape compiles and runs,
  which is why only enum-typed fields bite.
  **Where it comes from**: design 84's cross-module embed splices the frame
  struct + resume method into the ENTRY AST (`coro_transform.py:6448-6456`),
  and the re-entry pass (`post_transform=True`) re-checks that spliced body as
  entry-module code. The struct symbol `Cli` it finds there has identity `Cli`
  (bare/root) and un-canonicalized field types — module A's own registration
  resolved them, this one did not. So the fix belongs at the registration of an
  imported module's declarations into the merged/entry namespace (resolve the
  field annotations), or at keeping the spliced body on A's identities; it is
  NOT at the design-204 `_type_lookup_module` funnel, which the brief nominated
  — making `_vis_module_for_source` answer from `_module_scope_by_file` for
  user files was tried and does NOT fix it (reverted, unlanded).
  **Unit 7 STOPPED and reported** rather than worked around: the fix touches
  the embed/registration path that `gmgate`/`bootstrap`/`sos` all ride.
  **RULED (user, Aug 13): OPTION 1 — STAMP THE SPLICE.** The spliced subtree
  carries fully-resolved identities BEFORE it lands in the entry AST: extend
  design 210's `embed_preserved` machinery to the TYPE-ANNOTATION positions
  it misses (DF-210c's "not fully annotated" list is the starting census —
  obligation 1: the position list is the matrix), stamped in the PROVIDER's
  context; the re-check consults stamps. Third application of the identity
  pattern (the Poll fix; the elaboration principle's provenance invariant),
  and it builds a piece of 218's midpoint contract early — unit 1.5's mono
  instances are the next splice-shaped consumer and inherit the fix free.
  Rejected: teaching the entry-side re-check a resolve-as-if-elsewhere mode
  (per-consumer ongoing cost). Deliverables: the annotation census, the
  stamping, the pin flip, DF-210c partially discharged and its entry
  updated. **DISPATCH AFTER 219 WAVE B LANDS** (touches the transform's
  splice path).
  Original text (superseded where it says "closure" and "second identity"):

  **DF-212b (BLOCKED unit 4 as designed) — a closure literal argument to a
  free function corrupts an unrelated enum's type identity, ACROSS the whole
  caller, when the caller sits in a module that gets cross-module-embedded
  for an unrelated reason.** Isolated by bisection in
  `blade/src/cli.saw`/`blade/src/main.saw` (both restored — no trace left in
  the tree): adding
  ```saw
  func scan_args(args: &Vector<String>, start: Int, handle: (Int, Int) -> Int) { ... }
  ```
  to `cli.saw`, and calling it with a closure LITERAL argument
  (`scan_args(&args, 2, { av, i in 1 })`, body irrelevant — even a trivial
  return-1 stub) from inside ONE branch of `Cli.parse()`'s value-returning
  `if`/`else if` chain (each branch builds `Cli(command: BladeCommand.X)`,
  both types declared in `cli.saw`), makes EVERY branch of that chain fail
  with ``field `command` expects type `BladeCommand` but got `BladeCommand` ``
  — the same printed name, two distinct identities, which is design 144's
  signature for a type resolved twice under two different (module, name)
  answers. The FIRST failing line is `return Cli(command: BladeCommand.Help)`,
  textually BEFORE the branch that calls `scan_args` at all. Bisection (each
  step re-verified against the real blade project, `--module-path`
  toml/semver/imgformat, via `sawc/sawc.py blade/src/main.saw`):
  - Declaring `scan_args` unused: compiles.
  - Calling it with a NON-closure argument (`scan_args(&args, 2) -> Int`, no
    `handle` parameter at all): compiles.
  - Calling it with a closure argument, `main.saw`'s own `main()` NOT
    suspending (a `main()` that only calls `cli.Cli.parse()` and prints the
    result, or that also imports `src.manifest`/`src.builder`/`src.tester`
    but never calls anything suspending): compiles.
  - Calling it with a closure argument AND `main()` transitively suspending
    (its real body's `Build` arm reaches `Builder.build` -> `Command.run`,
    which suspends): FAILS, reproducibly, regardless of whether the closure's
    own parameter types name a reference (`(&Vector<String>, Int) -> Int` and
    the reference-free `(Int, Int) -> Int` both trigger it).
  - Unrelated to design 212 units 2/3: reproduces identically with
    `sosimg.saw`/`builder.saw` reverted to their pre-212 content.
  Reading: `main`'s body becomes ONE coroutine frame because it eventually
  suspends, so the frame machinery has to carry every earlier local
  (`parsed_cli: Cli`) across the whole function — including the ones bound
  before the branch that will never suspend. Something about registering a
  closure-typed parameter's argument at that call site, during whatever pass
  builds or re-resolves that frame, mints a SECOND identity for
  `BladeCommand` that prints the same but does not `==` the first. NOT
  reproduced in an isolated two-file `import src.cli` + `Cli.parse()` project
  with no suspending call anywhere — the suspending-frame condition is load-
  bearing and a fully minimal standalone repro is still owed. Worked around
  by AVOIDING the closure entirely (not a "workaround" of THIS unit's design
  goal — a genuinely different, still-mechanical extraction): unit 4's
  `scan_args` takes `value_flags: &Set<String>` and returns a
  `ScanResult { flags: Map<String, String>, positional: Vector<String> }`
  instead of a `handle` closure, which collapses the SAME three loops with no
  closure anywhere in the call graph. `run`'s loop (no flag recognition at
  all — it collects every token, "--"-prefixed ones included) is left as its
  own small loop rather than forced through the flag-shaped scanner, which
  would have changed its behavior (a `blade run --foo` argument must still
  reach the child program's argv).

## Design 153 findings — the magic-values→backed-enums sweep (Aug 10)

- ~~**DF-153a — two std FILES cannot declare the same type name.**~~ **CLOSED
  by design 204** (Aug 10). Each std file's PRIVATE types are that file's:
  identity `State$m$std_once`, name bound only in its own module view. The
  vehicle is `tools/test_std_private_type_names.py` (conformance row B10, the
  battery's `stdtypes` stage) — it drops a second private `State` into the std
  tree, rebuilds the builtins, and asserts two identities, two layouts and two
  method symbol families. Original text:

  **DF-153a — two std FILES cannot declare the same type name.** Design 82
  makes each std file its own module and design 144 makes type identity
  `(defining module, name)`, but the std sources are type-checked as ONE
  `builtins` unit, so a second declaration of a name collides:
  ```
  sawc/std/once.saw:64      enum State: Int { case Unset = 0, ... }
  sawc/std/spinlock.saw     enum State: Int { case Unlocked = 0, case Held = 1 }
  → error: enum `State` is defined multiple times  --> builtins:38:1
  ```
  A user program with the same two modules compiles (that is what design
  144 landed). Not user-facing — only a std-authoring constraint — but it
  is the rule not holding where it is written to hold. The sweep worked
  around it by naming SpinLock's enum `LockState`, which is the spelling
  the skill's STYLE bullet uses for exactly these two constants anyway.

- ~~**DF-153b — a private std TYPE reserves its simple name for every
  program.**~~ **CLOSED by design 204** (Aug 10). A std type declared `public`
  keeps its exposure exactly; one declared without `public` is FILE-private —
  qualified identity, bound only in its own file's view, reachable through no
  import form. 24 std-internal type names are free for user programs now, and
  a std module's surface is a thing it SAYS rather than a thing that happens.
  Both pins flipped (`examples/user_enum_name_vs_private_std_enum.saw`,
  conformance row B09); row B12 is the fence that a PRELUDE name is still
  reserved. **The sweep's blocked item is UNBLOCKED**: `std.net`'s five `SYS_*`
  and `std.process`'s `SYS_WOULD_BLOCK` can take the `SysError` name rt/ABI.md
  gives them, since a private std enum no longer collides with the
  `enum145_*` tests' own `SysError`. Mech follow-up, alongside blade's
  `ElfSegFlag` naming decision below; design 204 deliberately did not do the
  conversion. Original text:

  **DF-153b — a private std TYPE reserves its simple name for every
  program.** USER-FACING, and the reason the sweep's `std.net` known-debt
  item did NOT land. Pin:
  `examples/user_enum_name_vs_private_std_enum.saw`.
  ```saw
  enum OpenMode: UInt8 { case Read = 0, case Write = 1 }   // a user program
  func main() { print("{OpenMode.Write as UInt8}") }
  → error: enum `OpenMode` has no variant `Write`
  ```
  std.file's private `enum OpenMode` wins, and the diagnostic names a
  declaration the author cannot see, import or find. This is exactly
  DF-140h — a private std `static` used to reserve its name the same way —
  fixed for statics and never for TYPES. A struct/enum name is what a user
  is most likely to pick, and std's private types are invisible, so the
  reserved set is unknowable.
  **What it cost this brief.** Giving `std.net`'s SysError tags the name
  rt/ABI.md gives them (`SysError`) broke three EXISTING tests
  (`enum145_methods`, `enum145_raw_backed`, `enum145_traits` — each
  declares its own `enum SysError`), so converting a std statics family
  into a std enum is not behavior-preserving until this is fixed: it
  widens the set of names std silently reserves. `std.net` and
  `std.process`'s SYS_WOULD_BLOCK are therefore left as statics, and the
  two std enums that DID land (`LockState`, `SeekWhence`) reserve two more
  names in the meantime. The fix is DF-140f/h's module-local identity
  applied to type declarations.

- **DF-153c — a fixed-width backed enum costs two casts at a word-wide
  seam.** Not a bug; the datum the brief asked the sweep to produce.
  `SysError` is `UInt8` because its numbers are ABI (design 47), but every
  seam that carries one types it `word`, so the use site reads
  ```saw
  if r == 0 - ((SysError.WouldBlock as UInt8) as Int) { ... }
  ```
  against the old `if r == -SYS_WOULD_BLOCK`. std.file's `OpenMode` already
  paid this (`(mode as UInt8) as Int`) at one site; the rt net ops pay it at
  a dozen. The same shape appears at every `Atomic<Int>` state machine —
  `LockState`/`Once.State` project with `as Int` per touch — which is what a
  hypothetical enum-typed `Atomic<E>` would remove. Two candidate answers if
  it is ever worth a design: a widening projection that reads the enum
  straight to the wider integer (one `as`), or `Atomic<E>` over a raw-backed
  enum. Recorded, not proposed.

### The sweep's census (what converted, and why the rest did not)

CONVERTED: SpinLock `UNLOCKED`/`HELD`; std.file `SEEK_*`; the rt-side
`SYS_*` tag space in all four rt modules; the spawn redirection bits on
both sides of the seam; sosrt's two abort codes.

NOT CONVERTED, by reason:
- ~~**Blocked by DF-153b**~~ **UNBLOCKED Aug 10 by design 204** — ready for a
  mech follow-up, not done there:
  `std.net`'s five `SYS_*` and `std.process`'s `SYS_WOULD_BLOCK` — both
  are the `SysError` vocabulary, and the name used to be taken by user
  programs. A private std enum reserves nothing now, so `enum SysError: UInt8`
  in `std/net.saw` no longer breaks `enum145_methods` / `enum145_raw_backed` /
  `enum145_traits`, each of which declares its own `SysError`. DF-153c's
  two-cast cost at the word-wide seams is the thing to re-read before doing it.
- **Host C constant families, not sets this code owns**: the ~20 `E*`
  errno numbers in each `net_os.saw` (an OPEN set — we name the ones we
  map, of hundreds); `EPOLL_CTL_*`, the kqueue `EV_*`/`NOTE_*`, the
  `CLOCK_*` ids, `AF_INET`/`SOCK_STREAM`/`PROTO_DEFAULT`, `WNOHANG`,
  `STDOUT_FILENO`/`STDERR_FILENO`. Each is one argument at one C call
  with no branch, no match and no `from(raw:)`, so the `as` ceremony
  swamps the gain (the brief's judgment clause).
- **Quantities, which is what a static is for**: every `*_OFF`/`*_LEN`/
  `*_SIZE`/`*_MAX`/`*_SHIFT`/`*_MASK` family — std.cbor's UTF-8 bounds,
  taskgroup's `BT_*` backtrace-table offsets, blade's ELF field offsets,
  the sos HAL's page/PMP/MAIR arithmetic, `Duration`'s scale factors.
- **Open sets**: `selfhost/lexer`'s 60 `B_*` byte codes (character
  values, not tags — the lexer compares against a sample of ASCII).
- **Refused by the language, correctly**: the arm64 HAL's `DESC_*`
  descriptor bits — `DESC_TABLE` and `DESC_PAGE` are both `0x2` (the same
  bit means different things at different levels), and a raw-backed enum
  rejects duplicate values. Two names for one number is what a static is
  still for.
- **Naming default set Aug 10 (check-in delegated reasonable decisions):
  `ElfSegFlag: UInt32` — the ELF spec's own noun (segment permission
  flags, p_flags), disambiguated from sosimg's `SegFlags` by the format
  prefix. Mech follow-up alongside the unblocked net.saw SYS_* once
  design 204 lands.** Original note:
  blade's ELF `PF_X`/`PF_W`/`PF_R` program flags
  (a genuine closed flag set — `PF_` is an abbreviation, and the nearby
  `SegFlag` names the OTHER format's flags, which these map into). Left
  rather than invented; a one-line ruling on the noun lands it.
- **examples/**: no incidental family. Every statics family there is the
  SUBJECT of its own test (const-init, `df140f`/`df140h` collisions,
  atomics counters) — the one exception, `serde169_hand_written`'s two
  wire tags, is scratch inside a hand-written-serde demo.
- **Docs**: no spec/README example models the pattern. Every statics
  example in either document is a size or a derived quantity, which is
  the form the ruling KEEPS; the ruling itself was already in the skill.
- **devtools/** was outside the brief's scope; `irdet`'s `EXIT_*` trio is
  the one family there.

## Design 204 findings — std type identity (Aug 10)

- **DF-204a — four std internals still reserve their names, because the
  compiler spells them.** `__TaskCell`, `__ResultCell` and `__VoidCell`
  (`std/taskgroup.saw`) are selected by NAME in `coro_transform.py` when it
  lowers a spawn, and `RangeInclusive` (`builtin.saw`) by
  `codegen/loops.py:226`. Design 204 marks all four `public` with a comment
  saying why: a qualified identity would rename the declaration out from under
  the Python string that builds the reference. So the ruling ("a private std
  type reserves nothing") holds for 24 of 28 genuinely internal types and not
  for these four. Not user-facing in practice (three are `__`-prefixed and
  `RangeInclusive` is a real language type), and a non-regression — they were
  reserved before too. The fix is for the four sites to resolve through the
  namespace's identity map instead of a literal, at which point the `public`
  markers come off; it wants its own small brief because "codegen names a std
  type by string" is a pattern worth counting before changing.

- **DF-204b — a closure's codegen symbol carries the LINE it was written on,
  so an unrelated edit above it renames the symbol.** Adding a three-line
  comment to `std/taskgroup.saw` moved eleven `__closure$__saw_bt_dump$1775_39`
  -style symbols by three. Harmless today (the names are internal and irdet
  measures run-to-run stability, not edit-to-edit), but it means an IR diff
  across two versions of the tree carries churn that has nothing to do with
  the change under review — which is exactly the measurement design 204 unit 3
  had to do by hand. Design 168 unit 3 already solved the analogous problem
  for literals with `mangle.content_tag` (name the thing after WHAT IS IN IT);
  the same treatment would fit a closure. Recorded, not proposed.

## Measured performance (Aug 10 — the warehouse benchmark)

The first profiling-backed performance entry (per the ruling: optimization
enters the tracker only with measurement behind it). The workload:
`devtools/bench/warehouse/` — a deterministic dispatcher/robots/orders
simulation, 200k ticks × 100 robots, implemented four ways with
checksum-identical output. Wall times on this host (contended by an agent
run; deltas consistent across alternating runs):

| impl | time | vs Rust |
|---|---|---|
| Rust `-C opt-level=3` | 0.22s | 1.0× |
| Swift structs `-O` | 0.45s | ~2.1× |
| Saw (default pipeline) | ~1.05s | ~4.9× |
| Saw IR → external `clang -O3` | ~1.08s | ~4.9× |
| Swift classes `-O` | ~1.37s | ~6.3× |

**The finding: the gap is LOWERING SHAPE, not the pass pipeline.** External
O3 on sawc's IR changes nothing, because every `v[i]` place access is
lowered as the full design-141 window protocol — the call site builds a
`{fn_ptr, env, dtor}` closure for the window body, calls the outlined
`Vector.[]` accessor, which reaches the body by an INDIRECT call at the
`lend` — and LLVM does not collapse the chain. ~3 calls + a closure build
per element access, tens of millions of times in the hot loop.

**Fix direction (brief AFTER the 195-202 queue drains):** a place-lowering
fast path — for a direct-storage accessor (Vector/Data `[]`), emit
bounds-check + GEP inline; the general protocol stays for accessors that
need it (epilogues, `#lend_var`, conditional lends). Acceptance: the
warehouse benchmark reaches Swift-structs territory (~0.45s) with every
check still on, checksums unchanged.

**Phase 2 (Aug 10 discussion, after the fast path lands + re-measure):
exclusivity-derived LLVM attributes, NOT a hoisting pass.** Repeated
access-chain hoisting with &var invalidation — the natural ask — is
exactly what LLVM's GVN/LICM already perform WHEN GIVEN ALIASING FACTS;
today every opaque call clobbers the world, so values reload. The Law of
Exclusivity statically proves what `noalias` asserts (one `&var` XOR
many `&`), and Saw's checked signatures license memory-effect attributes
(`&self` vs `&var self`, `sync`, no-escape) — with the exclusion set
ALREADY type-tracked: cell-carrying types, the `unsafe` effect,
`UnsafeMemory<_, Device>` (volatile, exempt). Rust's `&mut`→`noalias`
precedent. Emission is lowering-adjacent (ports with the design); LLVM
does the dataflow; per-attribute audit = "states what the checker
proved". A bespoke hoisting pass is REJECTED under the shapes-not-
optimizer rule above, and would be redundant with this.

**The standing rule this entry sets** (answers "will optimizing the Python
compiler hurt the port?"): improve the SHAPES codegen emits — lowering is
design, and a ported compiler inherits it — but build NO Python-side
optimizer machinery (custom passes, analysis frameworks, an inliner); LLVM
is the optimizer on both sides of any port. Pass-pipeline TUNING (an
O2-style llvmlite config) ports trivially and may ride any perf brief,
though the O3 null result says it buys little here.

Non-gating tracking: the `bench` battery stage times the Saw benchmark on
every battery run (checksums GATE — they are a behavioral pin; timing only
reports). Swift/Rust sources sit beside it as manual baselines so the
battery takes no swiftc/rustc dependency.

## Design 210 — annotated embedding (LANDED Aug 11; lands 206 with it)

`designs/210-annotated-embedding.md`. The user's ruling of Aug 11: an imported
NON-GENERIC function carries sufficient information for a caller to embed it in
its frame with NO re-typecheck; an imported GENERIC function exports what a
per-instantiation re-typecheck needs, and that recheck runs in the callee's HOME
module scope. Both paths built; design 84's std-only special case dissolved;
DF-206e closed by architecture, and design 206's two liveness fixes land with it.

**The embed contract is written down** (`coro_transform.py`'s module docstring,
indexed in the brief): six families an embed consumes — resolved expression
types, resolved callee SYMBOLS, effect/suspension facts, place/copy judgments,
what the transform stamps itself, and no-escape facts carried by construction.
Five ride the AST as declared `annotation(...)` fields; the sixth is the design-22
effect graph, keyed by `node_id` and therefore serializable on the same terms.
The astgraft lane is the closure proof. Kept serializable, NOT serialized —
separate compilation stays future work.

**The non-generic path** marks the expression kinds whose check CONSULTS THE
NAMESPACE (`FunctionCall`, `MethodCall`, `Identifier`, `MemberAccess`,
`StructInit`, `EnumInit`) with `Expression.embed_preserved`, and
`_check_expression` hands back the stored answer instead of re-resolving.
Marking only those is deliberate and was measured: everything else is judged
from its children's types and needs no scope, and skipping it LOSES facts,
because the post-transform pass accumulates context as it walks (a `try`'s error
type is collected from the `try` expressions the walk passes). The mark means
the subtree is CLOSED, which `_close_embed_marks` makes true bottom-up at the
splice boundary rather than assuming; the skip is wholesale, because descending
re-asks about nodes that were never independently askable (a module qualifier is
an `Identifier` its parent resolves). What the transform grafts, it answers for:
`_answered(node, type)` is the funnel, and a frame read takes the type of the
local it replaces.

**The generic path** keeps the per-instantiation recheck (designs 70/74) and
moves it into the template's home module through `_home_module_scope`, whose
docstring names all four rechecks. Plus the instantiation map: the caller's
concrete type ARGUMENTS are lent into the template's scope, because
`amplify<Lo>`'s body names `boost` (the template's module) and `Lo` (the
caller's) in one expression and neither namespace alone has both.

Conformance rows K21-K25 (`examples/conformance/INDEX.md`). blade compiles
again — 24 errors before, 0 after — which is DF-206e's stated acceptance.

Findings, all fixed:

- **DF-210a (FIXED) — a `match` arm's payload binding was stored into its frame
  slot by ALIAS.** For an ExplicitCopy or NoCopy payload the transfer checkpoint
  refused it outright: `cannot copy value of type `Cli` which implements
  ExplicitCopy`, anchored at `FILE:0:0`, on a program that writes no copy at all.
  Three of blade's 24 errors. PIN:
  `examples/conformance/K24_frame_slot_payload_binding_not_a_copy.saw`.
- **DF-210b (FIXED — silent memory corruption) — the `if let` twin moved
  UNCONDITIONALLY.** DF-182c made `_optbind_dispatch` store its binding with
  `move`, correct for a payload the binding OWNS and wrong for one whose read
  only RETAINS (the ImplicitCopy tier). For an `Arc` payload the frame released a
  reference the binding never held: probed on the pre-fix tree, `deinit` fires
  while the original still points at the value, `strong_count()` then reads freed
  memory, and a second `deinit` prints a garbage id. Only the `match` half was
  ever visibly broken, which is why the fix is ONE authority for both:
  `_store_binding_in_slot` asks `Namespace.read_policy` (design 193's funnel) and
  moves exactly when the read consumed. Both spellings balance now.
- **DF-210c (PARTIALLY DISCHARGED Aug 13 by DF-212b) — the declaration-time AST
  is not FULLY annotated.** Several node kinds carry no `resolved_type` —
  `StringInterpolation` and its `FormatPlaceholder`s among them — so
  "declaration-time annotated" and "fully annotated" are not yet the same
  statement. Design 210 does not need them to be (`_close_embed_marks` un-marks
  any subtree holding one, and it takes the ordinary path), but a future
  separate-compilation interface would, and the astgraft gate does not catch it:
  it polices whether a stamped attribute is DECLARED, not whether every node is
  stamped.
  DF-212b turned this from a note into a bug and closed the two positions that
  bit. **NOW STAMPED**: (a) the KIND of a written type annotation, in the
  declaring module's own view (`_stamp_annotation_kind`) — which covers the two
  reachable ones of design 194's three RAW declaration slots, a struct FIELD's
  type and an enum PAYLOAD's type, at every depth (bare, inside a generic
  argument, inside an optional); (b) a member access's TYPE-NAME or
  MODULE-QUALIFIER head, which is not stamped but is now correctly EXEMPT from
  the closedness test (`_is_type_name_base`) — an exemption, not an annotation,
  because the head is never asked anything either.
  **STILL UNSTAMPED**, each verified by probe: `StringInterpolation` and
  `FormatPlaceholder` (the original text's example — a subtree holding one still
  takes the ordinary re-check path, which is sound and merely slower); the third
  RAW declaration slot, a `type R = T` alias RHS, whose kind is stamped by the
  same walk but which has NO reachable cross-module-embed repro, so the coverage
  is claimed by construction rather than by a test; and the qualified SPELLING
  in those same three slots, which `_stamp_annotation_kind` deliberately skips
  (`'.' in name`) and which stays pinned by DF-194a's own xfail.
- **DF-210d (RECORDED, no action) — `ForceUnwrap.frame_move_read` is stamped and
  declared but has no reader.** Its documented job ("the read is a transfer even
  for a NoCopy payload") is done by the `frame_place_read` early return in
  `_check_value_transfer`, which covers move and non-move reads alike. Dead
  marker, or a second guard that never landed; folded into whatever next touches
  the frame-slot family.

**DF-206f is FIXED (unit 8)** — it was a real generated-code memory bug that
this branch's own widening exposed: a frame released one `Vector<String>` buffer
twice, through a consumed binding's slot and through the hoisted scrutinee temp
it came out of. The mechanism is DF-210f below; the pin is
`examples/coro_hoisted_scrutinee_released_once.saw`.

## Design 206 — executor park liveness (LANDED VIA 210, Aug 11)

**Landed as design 210 unit 0** — the five commits cherry-picked onto main and
integrated with design 201's spawn-reference lowering, which had never been
combined with them. No textual conflicts; `coro_transform.py` and `gmgate.py`
auto-merged, and both sides' rows are green in one tree (206's two liveness pins
flipped, 201's seven K-rows passing). The blocker below is closed by design 210.

The historical record of why it was blocked follows, unchanged.

**The branch was NOT landable on its own.** Both hangs were closed on the
`examples/` corpus (suite 1730 / 8 xfailed, gmgate both lanes green at -n 5,
ten-repeat stable) and the full battery was RED: `bootstrap` and `sos` failed
because blade no longer compiled. See DF-206e below.

`designs/206-executor-park-liveness.md`, with the unit-1 diagnosis written into
the brief. DF-203a and DF-203b were ONE bug, and it was neither of the two the
brief guessed: **the entry compile's effect graph has no node for any std
METHOD**, so the fixpoint answers NO to "does this body suspend?" for a body
whose only suspension is a std method call, and every consumer of that answer
lowers the body as if it never suspended. `main` was then never wrapped in the
entry executor (DF-203a: `accept`'s `io_wait` took the outside-frame lowering
that blocks the executor thread in `poll(-1)`), and a helper was never pulled
into the driven closure (DF-203b: `receive()` compiled to the library body,
whose `yield_now` is a NO-OP outside a frame — a bare spin). `sleep` differs
only in being an INTRINSIC, recorded as a direct source on its caller's own
node; timer-vs-reactor was a coincidence of the two spellings. Neither park
primitive nor the design-62 G3 receive lowering needed changing.
`really_suspending(nodes)` (effects.py) is now ONE definition of "really
suspends" shared by both typecheckers, with its callers and its four routes
named in its docstring.

Five findings; two fixed here, and the blocker was closed by design 210:

- **DF-206e (CLOSED by design 210, Aug 11) — the coroutine transform cannot embed
  a method of an imported USER module, and design 206 is what first asks it to.**
  The ruling was way (a): the honest fix, in its own brief. A non-generic embed
  keeps its home module's meaning by CARRYING its declaration-time answers rather
  than by re-resolving them anywhere; a generic one re-checks per instantiation in
  the template's home scope. blade compiles again (24 errors → 0), which is the
  acceptance this entry names. The frame-field half is DF-210a.
  Unit 2 makes `main` suspending whenever it REALLY suspends, by any route. That
  is what LANGUAGE_SPEC:5053 already promised, and its consequence is that the
  transform now runs on programs it has never run on. blade is one: its `main`
  reaches `Command.run` through `builder.Builder.build`, a method of the
  imported `builder` module, so the transform embeds that method as a sub-frame
  — and the spliced body is re-typechecked in the ENTRY module's namespace,
  where `builder`'s own private functions are not visible. blade dies on
  `resolve`, `read_file`, `sos_clang`, `arch_for_target`, `write_sosimg`
  ("function `resolve` is not directly accessible", 24 errors), which takes
  `bootstrap` and `sos` down with it. Design 84 built cross-module embedding for
  STD methods and its comment records the "static-inlining fix" that made
  `INVALID_FD` visible; std works because it is one scoping domain the entry
  compile has fully registered, and a user module is not.

  Minimal repro (two files, no blade): a `public` struct in `util.saw` whose
  method calls `Command.run` and a private sibling `inner()`, and a `main` in
  the entry module that calls the method — `error: undefined function `inner``.
  Beside it, blade's `main` shows the other half: the frame's own field copies
  are wrong too (`cannot copy value of type `Cli` which implements ExplicitCopy`
  at main.saw:0:0).

  THREE WAYS OUT, and the choice was a ruling: (a) fix the transform's
  cross-module splice so an embedded body keeps its home module's namespace —
  the honest fix, its own brief, and it makes "a suspending method drives at any
  depth" true across modules for the first time; (b) scope the entry-executor
  gate so it does not reach a user-module method (arbitrary, and it would leave
  the DF-203a family broken for exactly the multi-module programs that hit it);
  (c) accept the transform and change blade's shape. The user ruled (a) on
  Aug 11 and design 210 built it.

- **DF-206f (CLOSED by design 210 unit 8 — the mechanism is DF-210f below) —
  `irdet --all` printed OK and then exited 139 (SIGSEGV).** A real
  generated-code memory bug in frame teardown, not a harness artifact. It was
  DETERMINISTIC, it reproduced at **`-n 2`** in three seconds (the original
  "does not reproduce at 2 or at 119" was the same exit-code misreading
  corrected below), and Guard Malloc turned it into a first-bad-access fault on
  a guarded page. Crash frame, identical on every tree and every run:

      EXC_BAD_ACCESS (SIGSEGV)
      thread 0:
        Vector$2$String$GlobalAllocator_deinit
        __Frame_main___release

  `main`'s frame released the same `Vector<String>` buffer twice: once through
  the `guard let` binding's slot and once through the `__hoist0` slot holding
  the suspending scrutinee it was bound out of. See DF-210f.

  **A CORRECTION, recorded because the method matters.** This entry first said
  DF-206f was CLOSED by the design-201 integration, on a three-leg bisect that
  read exit 0 from two legs. That was wrong, and the error was entirely in the
  measurement: two legs ran as `./irdetbin --all > out.txt; echo "EXIT=$?"`, the
  shell moved the compound command to the background, and I read `out.txt` —
  which holds irdet's STDOUT and ends in `OK` — instead of the exit status,
  which had gone to the task's own output. The third leg appended `EXIT=$?` INTO
  the file, which is the only reason its 139 was ever visible. All four runs had
  crashed. Reading the artifact that is easy to reach instead of the one that
  answers the question is how a red gate reads green — and it also cost a real
  bug three hours of being called somebody else's.

- **DF-210f (FIXED) — a CONSUMED hoisted scrutinee never gave up its claim on
  the payload, so the frame freed it twice.** The mechanism behind DF-206f.

  The transform hoists a SUSPENDING scrutinee into a frame temp —
  `guard let out = cmd.output()` becomes `let __hoist0 = cmd.output()` plus a
  binding out of `__hoist0`, and `match fetch() { … }` becomes `__match0` the
  same way. When the payload's read policy is CONSUME (design 131's
  nocopy/explicit tiers), design 210 unit 3 stores the binding into its slot by
  `move` — correctly. But the temp still held the value, and nothing told it
  otherwise: `_optbind_dispatch`'s `forgets` list was fed only by an EXPLICIT
  `move` scrutinee (`if let r = move held`, DF-182c). The author cannot write
  that `move` here, because the temp is not a name they have. So `__release`
  dropped the binding's slot and the temp's slot, both pointing at one buffer.

  Fixed at both hoisters: `_hoist_temps` records the temps the transform makes
  (`__hoistN`, `__matchN`), `_slot_store_consumes` is the shared answer to "did
  this store take ownership" (the same `Namespace.read_policy` oracle
  `_store_binding_in_slot` uses), and the dispatch emits the clear the author
  could not write. The `match` side is per ARM, since only the arm that binds
  consumes. An ImplicitCopy payload is untouched: its read RETAINS, both slots
  legitimately own a reference, and both legitimately drop — which is DF-210b's
  rule seen from the other side, and why one oracle answers both.

  PIN: `examples/coro_hoisted_scrutinee_released_once.saw` — both spellings, an
  ExplicitCopy payload each. The exit code is the assertion; under Guard Malloc
  it faults on the first bad access.

Of the rest, two fixed here:

- **DF-206a (FIXED) — `let _ = expr` owed a frame field, and every discard in a
  driven body shared the one named `_`.** `_uniquify_bindings` (DF-151a) exempts
  `_` on the reasoning that it binds nothing: true of a match arm and an
  `if let`, false of a `let`. Two discards of different types were a bogus
  `cannot assign Int to field of type Data?` on a legal program — the
  `let _ = try! s.read()` / `let _ = h.join()` pair, which is what the DF-203a
  pin's own `main` says. The fix is not a rename: a discard drops its value AT
  the statement, so it owes no field at all, which also restores the timing a
  second same-typed discard had lost (it lived until frame death). THREE
  classifiers decide a `let`'s frame target and only two guarded `_`;
  `_classify_recv` now does too. PIN:
  `examples/coro_wildcard_discards_own_slots.saw`.
- **DF-206b (FIXED) — destructuring a tuple of OWNING elements in a driven body
  was a copy.** Design 77 item 10 lowered `let (a, b) = v` as a source temp plus
  `self.a = __destr0.0`, a tuple-index READ. Right for the `(Int, Int)` tuples
  it was built for; `let (a, b) = TcpStream.pair()` in a spawned task refused
  outright with "cannot copy value of type `TcpStream` which implements NoCopy",
  on a program the non-frame path compiles. Components now come out through the
  ordinary `DestructuringLet` over an explicit `move` of the source temp. PIN:
  `examples/coro_destructure_nocopy_into_frame.saw`; the copyable half stays
  pinned by `df151f_tuple_drop_glue`'s `destructured_across_suspend`.
- **DF-206c (FILED, not fixed) — a TAIL-position `ch.receive()` is a compile
  error.** `func take_one(ch: Channel<Int>) -> Int { ch.receive() }` is refused
  with "suspending call to `receive` ... appears in a nested/expression
  position; only a top-level `let x = receive(...)` or `receive(...)` statement
  is supported". That is design 62 G3's stated scope and a CLEAN anchored error,
  not a liveness bug — but it is the natural spelling of exactly the
  reusable-wrapper shape DF-203b was about, and the skill's own claim is that a
  suspending call embeds "in any EXPRESSION position" (design 120). Bind and
  return is the workaround (`examples/channel_receive_in_main.saw` does).
  Small: G3 needs the same ANF hoist the other suspending calls got.
- **DF-206d CLOSED (design 223 unit 3, Aug 15) — it was live, in the
  over-inclusion direction.** Design 223's cell K probed the predicted shape
  and found it real: a user `extension TcpStream { func read(&self) -> Int }`
  that suspends nothing was compiled into a full coroutine frame — state
  machine, heap frame, drive loop — because its name pair matched std's. The
  fix is not the typed key the note guessed at (design 144/204 exempt std's
  PUBLIC type names from qualification, so std's `TcpStream` and a user's
  entry-module one share one identity string and a typed key separates
  nothing): it is that a method's OWN effect answer, where this graph has one,
  outranks a name that agrees with std's. A std-seeded pair is dropped when
  every declaration of it is a NON-std extension this graph judges
  non-suspending; if std also declares the pair, the seed stays, because std's
  answer is the one this graph cannot compute. Row K38 pins it in the IR, in
  both directions.
  The ORIGINAL note follows.

- **DF-206d (OBSERVATION, no action) — the effect graph's std seam is keyed by
  NAME in the transform and by `node_id` in the typechecker.** Design 84's
  `_std_suspending_methods` is a set of `(struct, method)` name pairs, so a user
  struct named `TcpStream` with a method `read` would be treated as suspending
  by the coroutine transform's structural scan. Design 206's new table is keyed
  by `Method.node_id` instead — exact, and preserved verbatim across the std
  cache's pickle — so the two halves of the same seam now disagree about
  precision. Not a live bug (design 204 made std file-private types unnameable
  and the transform's imprecision is conservative), and not worth a brief on its
  own; worth folding into whatever next touches design 84's set.

## Design 203 dogfood wave 1 — findings (filed Aug 10, lead-triaged, both probe-confirmed)

Six Sonnet naive-implementer programs (203 u1). All six produced correct,
deterministic, spec-passing programs; the findings cluster in the
scheduler's park paths, stdlib seams, and diagnostics. The two (d)s:

- **DF-203a (LIVENESS — CLOSED by design 206, landed via 210 Aug 11): a task spawned before
  main's FIRST suspension never starts when that suspension is a REACTOR park.**
  `group.spawn(worker())` then `listener.accept()` blocks the executor on
  the OS reactor without draining the run queue, so a worker that would
  CONNECT to that listener never runs — permanent hang. The timer path
  (`sleep`) drains correctly (probe-isolated by the dogfood agent with
  three controls; hang re-confirmed by the lead on main). Breaks design
  89-b's "runs EAGERLY" promise on the reactor path; the chatroom
  program's natural spelling (spawn clients, then accept). PIN:
  `examples/spawned_task_runs_before_reactor_park.saw` (XFAIL REMOVED —
  it passes). THE DIAGNOSIS WAS NOT THE PARK: `sleep` is an intrinsic and
  `accept` is a std METHOD, and the entry compile has no effect node for a
  std method, so `main` was never wrapped in the entry executor at all and
  `accept`'s `io_wait` took the outside-frame blocking lowering. Timer vs
  reactor was a coincidence of the two spellings.
- **DF-203b (LIVENESS — CLOSED by design 206, landed via 210 Aug 11): `Channel.receive()`
  through ONE helper frame in a spawned task hangs.** Direct `ch.receive()` in the
  task body works; the same operation behind `acquire(ch)` (free function
  OR method — the extra FRAME is the trigger, isolated by a five-probe
  ladder) prints the first entry and stops. Contradicts the documented
  any-nesting-depth guarantee (96/104); suspected root is design 62 G3's
  INLINE receive lowering not composing with an embedding callee frame.
  The reusable-semaphore shape every library writes. PIN:
  `examples/channel_receive_through_helper.saw` (XFAIL REMOVED — it passes).
  THE G3 LOWERING WAS INNOCENT: the same std-method blind spot left `acquire`
  out of the driven closure entirely, so its `receive()` compiled to the
  library body, whose `yield_now` is a no-op outside a frame — a bare spin.

Both belong to ONE subsystem (executor park/drive paths) — candidate
small brief 206 alongside/ahead of 201, same surface discipline. The
rest of the wave's triage (std ergonomics batch: String→Data, File.write
overload, temp dirs, zero-pad; diagnostics batch: for-in .iter() hint +
cascade, transfer-error anchor at the read site, generic-ctor cascade,
PLUS two Aug-15 additions (probes `.build/scratch/probe_diag_a.saw` +
the arc probes): (i) a failed STATIC-METHOD resolution on a generic
type head falls back to "undefined variable `Vector`" — the head is
re-read as a value and the real error (no such static) is masked; cost
the lead three probe rounds live; (ii) a QUALIFIED generic static call
`arc.Arc<Int>.make(5)` is a PARSE error ("Unexpected token: DOT") —
the qualified generic head never reaches resolution at all;
skill/README edits: Atomic prelude line, build-and-return idiom, generic
CONSTRUCTORS excluded from inference, String.split unconfirmed-in-spec;
open probe: Vector<TaskHandle> dynamic-join spelling) lands with the
wave summary.

## The quality program — designs 190-194 (ALL LANDED Aug 9-10)

`designs/190-quality-program.md` is the analysis (findings-vs-proposals
matrix + three code censuses); 191-194 are the briefs it produced.
User-approved Aug 9, executed overnight Aug 9-10 in order (DF-190a
direct fix, then 193, 191 ∥ 192, 194), each ff-merged battery-green.
The process rules (position funnel-or-matrix; contract-flip consumer
sweep; safety-surface conformance-rows-first) live in CLAUDE.md.
NOTE for future census citations: several of 190's diagnoses were
corrected by the builds — DF-190b's cause, the spawn capture-MODE mask,
and the graft-straggler list (3 false, 5 missed) — the corrections are
recorded in the finding entries below and in 193/194's landed briefs.

**193 LANDED Aug 10** (all eight units; see `designs/193-checker-funnels.md`).
Four shared funnels exist now and each names its entry points in its docstring:
`Namespace.read_policy` (design 131's read table over design 139's tiers),
`ast_walk` (`child_nodes` / `map_nodes` / `control_blocks` + `CONTAINER_KINDS`),
`noescape.first_reference_in` (+ the `NO_ESCAPE_POSITIONS` matrix, three new
rows), and `Namespace.send_check` (+ `SEND_POSITIONS`). `sawc/visitor.py` is
deleted. Three soundness holes closed (DF-190d, DF-193b, the unchecked `spawn`
result); four findings filed (DF-193a/b/c-in-193b/d). Two census diagnoses were
wrong and are corrected in place below.

**192 LANDED Aug 10** (all five units; see
`designs/192-diagnostics-floor-and-oracles.md`). The compiler no longer has an
unwrapped stage: both typechecker dispatch fallthroughs RAISE, four dispatch
chokepoints stamp a `_current_node` breadcrumb, and every internal failure —
typechecker, codegen, or llvmlite — reports one line,
`internal compiler error at FILE:LINE:COL (<NodeType>): <message>`, with
`SAW_DEBUG=1` keeping the traceback. `tools/sawfuzz.py` fuzzes the corpus by
mutation against one oracle (succeed or diagnose cleanly), deterministic per
`(seed, index)` and wave-bounded; `tools/sawfuzz_known.txt` is its XFAIL
ledger. gmgate gained a 15-program `concurrency` lane beside the ownership one.
`tools/battery.sh` is now the tracked battery. SIX findings: DF-192a and
DF-192e fixed, DF-192b/c/d/f/g pinned (DF-192d fixed since, by design 198).
**DF-192g is a confirmed wrong answer** — below.

- **DF-190a — FIXED (pulled forward of the queue, landed Aug 9/10).**
  The typechecker now mirrors codegen's consume gate in
  `_check_match_expr`: a plain local scrutinee of an owning-tier
  (NoCopy/ExplicitCopy) enum with owning payload is marked moved, so a
  second `match s` is a clean use-after-move error. PIN flipped to a
  passing error test: `examples/match_owned_enum_double_consume.saw`.
  RESIDUAL for 193 u1: the copy-tier oracle unification note stands,
  and DF-190d (below) is the implicit-tier half of the same hole.
- **DF-190d — FIXED (design 193 unit 1).** The consume gate was
  `enum_has_owning` (any payload needs cleanup), which is not a transfer
  class, so an ImplicitCopy-tier enum's payload was released at the first
  arm's end while the scrutinee was still live. `_generate_match_expr`
  now has two modes on the scrutinee's tier: CONSUME for the owning
  tiers, RETAIN (bindings retain at extraction, scrutinee keeps
  ownership) for ImplicitCopy. Only a named non-borrowed local can be in
  retain mode — a temporary is owned by nobody and keeps consuming. The
  oracle unification landed with it: `Namespace.read_policy` is the one
  derivation of design 131's read table from design 139's tiers, named
  entry points in its docstring. PIN flipped:
  `examples/match_implicit_enum_payload_single_release.saw`.
- **DF-190b — FIXED (design 193 unit 2), and the census's root cause was
  WRONG.** The try/catch was a red herring: the failing spelling is the
  LABELED call `compute(ok: true)`, which is syntactically a struct
  literal (design 66), so it reaches the coroutine transform as a
  `StructInit` while every suspending-call classifier there tests for a
  `FunctionCall`. The call was never driven, and once the transform
  replaced the callee with its frame the leftover struct-init spelling
  had nothing to resolve against — hence ``undefined struct `compute` ``.
  The identical UNLABELED shape inside the same `try … catch` compiled
  and ran all along. Fixed by canonicalizing the spelling before any
  classifier runs (`_rewrite_labeled_calls`, beside the DF-158d yield
  rewrite) plus the sibling position at the SPAWN argument
  (`group.spawn(worker(n: 20))` was refused by the typechecker with a
  message showing the very call it was given). PINS:
  `examples/coro_try_catch_suspending.saw` (flipped),
  `examples/coro_labeled_call_positions.saw` (new, three positions).
- **DF-193b (SOUNDNESS, CONFIRMED double-free, found + FIXED by 193 u3): a
  `move` written inside a STRUCT LITERAL was invisible to the
  borrowing-match check, so a `match v[i]` arm destructured the element in
  place.** `_arm_moves_binding` decides whether an arm reads the place or
  destructures it, and its walk stopped at tuples —
  `StructInit.field_inits` being a list of `(name, value)` tuples, an arm
  body `Held(r: move r)` looked move-free. The match then lowered into a
  borrow window and the payload moved OUT of storage the vector still owned:
  probe printed `deinit 1` twice, exit 0. Now the ordinary value-read error
  naming `with_ref`/`swap_out`. The same tuple hole in the chain-assign
  exclusivity walk let `w?.c = Cell(v: refill(&var w))` past the Law while
  the shallower spelling was refused. Both walks are on the shared
  `ast_walk.child_nodes` now. PINS:
  `examples/place_match_arm_move_in_literal.saw`,
  `examples/chain_assign_exclusivity_in_literal.saw`.
- **DF-193c — FIXED by the unit that found it (193 u6): `spawn { … }`'s RESULT
  type was never `Send`-checked.** The captures were audited from the start;
  the result travels the other way (computed on the task's thread, handed back
  by `join()`) and nothing asked. `extension Task<T: Send>: UnsafeSend` was
  doing the only guarding, and it guards the wrong crossing — it stops the
  HANDLE from crossing a second boundary and says nothing about the one every
  task makes. `spawn { make_raw(&var n) }` returning a struct with an
  `UnsafePointer` field compiled and ran. Now refused at the `spawn`, with a
  type mentioning a type PARAMETER left to its instantiation. The census's
  other masked gap, capture MODE, is genuinely masked — by design 16/29 (an
  escaping closure may not borrow-capture), not by "closures are never Send" —
  and `examples/errors/capture_borrow_escaping.saw` already pins it. PIN:
  `examples/errors/spawn_result_not_send.saw`.
- **DF-194a — CLOSED (Aug 17), design 197 unit 2's ruling implemented for the
  three slots.** The module-qualifier walk is ONE function now,
  `_resolve_qualified_symbol`, with two entry points its docstring names:
  `_resolve_type` (every signature and expression position) and
  `_resolve_declared_qualified_names` (the three raw slots, called from
  `_register_struct`, `_register_enum` and `_register_type_definition`, each
  writing the result back onto the AST so the symbol table and the AST go on
  sharing one object). Both entries therefore get design 229's visibility
  check, which is why the slots route to the walk rather than to a
  canonicalizing name rewrite. The slot walk rewrites DOTTED names ONLY, so the
  DF-212b kind stamp — which knows the type PARAMETERS in scope, and must,
  since `struct Holder<Cmd>` beside an `enum Cmd` means the parameter — still
  settles the bare ones. The fourth face (a constructor's generic ARGUMENT) is
  closed in `_check_struct_init`, and a FIFTH the fix exposed: an `as` CAST
  target was read raw by codegen (`Undefined struct: dep.Point`), unreachable
  before because the cast was refused one error earlier. Tests:
  `examples/qualified_type_in_declaration_slot.saw` (pin flipped) and
  `examples/qualified_type_declaration_slots.saw` (the matrix — both kinds,
  every composite, a user module, the constructor argument). Docs: the spec's
  "every position" list and the skill's gotcha note. Gated on the compiler
  suite AND `sos_runner` both arches (the Aug-17 ruling: a compiler change can
  break kernel codegen, which the suite does not cover). **STILL OPEN from
  design 197: rule 7's six `parse_type` bypasses (unit 1's other half),
  untouched here.**
  As filed (SPEC/IMPL, Aug 10 by 194 u4): `struct Holder {
  p: dep.Point }`, `case Full(p: dep.Point)` and `type Alias = dep.Point` each
  keep the dotted spelling into type comparison, so `field `p` expects type
  `dep.Point` but got `Point``. Those three slots are read straight off the AST
  and never reach `_resolve_type`, the one place that walks a module qualifier —
  the same three unit 4 had to wire the prelude gate into by hand, which is how
  this surfaced. `_canonical_type_name` returns a dotted name unchanged ON
  PURPOSE ("for `_resolve_type`'s module-walk branch to handle") and for these
  slots that branch never runs. A fourth face: a constructor's generic ARGUMENT
  (`Vector<data.Data>()` binds a local whose element type keeps the dot).
  Pre-existing — reproduced identically on the unit-3 tree — and true for a USER
  module as well as for std. Design 150 claims outright that "a qualifier works
  in EVERY position a name appears", so this is a deviation from the spec, not a
  gap in it. It MATTERS MORE after unit 4: the gate's hint offers `import
  std.data` + `data.Data` as one of three ways to satisfy it, and that one does
  not work in a field. NOT fixed here — the fix is about what a dotted name
  canonicalizes to in a slot nothing resolves, which is a design-144 identity
  question and wants a ruling rather than a patch mid-brief. PIN:
  `examples/qualified_type_in_declaration_slot.saw` (XFAIL, cited).
- **DF-194b — CLOSED (Aug 17): a `type` alias whose underlying is an ENUM is
  now INVALID, refused at the alias declaration.** The ruling as stated. The
  rule is its OWN registration pass, `_reject_enum_underlying_aliases`
  (typechecker/registration.py), whose docstring names its two entry points
  (obligation 1): `check` and `check_module` in typechecker/core.py, each
  calling it once its own four registration passes have run. It cannot live
  inside `_register_type_definition` — aliases are registered BEFORE structs
  and enums, so at registration time no name is knowably an enum yet, which is
  the whole reason the gap existed. `_alias_underlying_enum` chases
  alias-of-alias through each link's WRITTEN type and asks the symbol tables
  rather than the annotation's kind (a bare named type parses STRUCT-kinded).
  Test: `examples/type_alias_of_enum_error.saw`, four rows — direct, a chain
  (the diagnostic names the middle: ``names the enum `Level` (through
  `Rank`)``), a raw-backed enum (a backing is not a way back), and a
  MODULE-QUALIFIED enum, which is where the DF-194a matrix's alias-of-enum row
  moved to: the refusal naming `Level` is itself the proof that the qualifier
  resolved in that slot, so slot 3's coverage survives the move.
  `examples/qualified_type_declaration_slots.saw` is slot 3 at the struct kind
  only now, with the pointer written at the line. Struct and primitive aliases
  are untouched (the in-file control, plus `type_alias.saw`,
  `type_alias_construction.saw`, `cast_distinct_*`). Consumer sweep: the tree
  had exactly ONE enum-underlying alias, that matrix row.
  **Consequence worth a ruling if anyone hits it:** `Result` and `Optional` are
  enums, so `type Outcome = Result<Int, ParseErr>` is refused too. Nothing in
  the tree writes one, and "until a use case exists" is the ruling — this is
  the shape the use case would take. Docs: the spec's Type Definitions section
  and the skill's cheat-sheet line. As filed:
- **(DF-194b, as filed) a `type` alias whose underlying is an ENUM cannot be
  projected back.**
  `enum L { case A, case B }` + `type R = L` + `r as L` is refused with
  ``cannot cast `L` to `L` `` — the two names printed identically, which is the
  DF-142a diagnostic shape. Nothing to do with module qualifiers: it reproduces
  on a plain local enum, and the same shape over a STRUCT underlying
  (`type M = Tag`, `m as Tag`) works. The projection `as` is design 63's
  sanctioned one-directional read toward the underlying, and `_check_cast_expr`
  reaches it through `_alias_ancestor_names`, which walks `is_struct()` chains
  only. RULED Aug 17 (user): until a use case exists, a `type` alias whose
  underlying is an ENUM is INVALID — a clean error at the alias declaration,
  covering the direct form, an alias-of-alias chain ending at an enum, and
  raw-backed enums; struct/primitive aliases unchanged. The DF-194a matrix
  test's alias-construction row updates to the refusal. Fix dispatch-ready.
  No pin was filed, since the matrix test constructs the alias and skips the
  projection with the reason written at the line.
- **DF-193d (SPEC/IMPL, filed Aug 10 by 193 u7 — supersedes DF-188k's "general
  fix" line with a diagnosis; CLOSED Aug 10 by 194 u4): the prelude gate cannot
  run on type ANNOTATIONS until a written-form PROVENANCE bit exists.** Building the funnel and running
  it over signature annotations refuses `func one() -> data.Data` under
  `import std.data` — the legal qualified spelling — because by the time any
  check can read the annotation, BOTH `_canonicalize_module_types` and
  `_register_function`'s design-68 write-back have replaced the author's
  spelling with the resolved identity, and a qualified `data.Data` is then
  indistinguishable from a bare unimported `Data`. (The front half also
  re-enters the same AST for the place lowering and the coroutine transform, so
  any hook must be idempotent against already-rewritten annotations.) The fix
  is a durable bit — on the annotation slot or the `SawType` — set where the
  qualifier is resolved; that is an AST-contract change and belongs with
  design 194's typed-AST work, not here. Also worth knowing before it lands:
  the corpus itself relies on the gap — `examples/cbor169_vectors.saw` names
  `IoError` in a return type with no import, and closing the gate makes that
  (and any user code like it) an error, so the landing owes a corpus sweep.
  A `static`'s annotation, the one slot nothing rewrites, stays gated (design
  188 unit 7, now through the shared `_gate_written_type`). PIN:
  `examples/std_import_gate_signature_position.saw` (XFAIL, cited).
  **CLOSED by 194 unit 4.** The bit is `SawType.written_name` (+ file/line/
  column), stamped by the parser at the one place a named type is built and
  never touched by either rewrite; the gate reads it in `_resolve_type` plus the
  three raw declaration slots, and it is exempt wherever the spelling is not a
  user's (no provenance = compiler-built; a dotted name = reached through a
  qualifier an import bound; a std source FILE = std extends itself by design).
  Design 188 unit 7's separate `static` mini-walk is retired — the funnel covers
  that position and keeping both printed the diagnostic twice. The XFAIL is
  gone; conformance rows W02-W05 carry the matrix and its two controls. Consumer
  sweep (recorded in the landing): exactly TWO offenders in the whole tree, both
  in `examples/` — `cbor169_vectors.saw` and
  `net_connect_dials_the_host_it_was_given.saw`, each naming `IoError` in a
  return type with no import, both fixed in the same landing. blade, libs,
  devtools and sos were clean.
- **DF-193a — FIXED (design 196 unit 3): a suspension inside a
  `try { … } catch { … }` BLOCK in a driven body.** The error path got its
  own states, and the shape of the answer is smaller than the finding
  feared. THE CATCH ARM IS A STATE. The try body lowers under a `_try_ctx`
  naming that state plus the frame field the caught error travels in, and
  every statement in it that holds a propagating `try` is wrapped in a
  synthesized ONE-STATEMENT `try { <it> } catch { <field> = error;
  __state = <catch>; continue }`. That wrapper is the whole trick: codegen's
  own try lowering keeps deciding where the error edge LEAVES (a `try`
  buried in an argument list, two in one expression, one inside a
  non-spanning `if`), and the landing only says where it GOES — and
  `continue` reaches the resume dispatch loop from inside a nested region,
  so the jump is a state transition rather than a branch within the state.
  Falling off either arm reaches a merge state, so the result is the same
  diamond `_split_if` builds. Everything under a split try/catch is
  frame-resident (a `let` inside the wrapper would otherwise be scoped to
  it), and the catch's implicit `error` binding now goes through
  `_uniquify_bindings` like any other name, so two catch blocks in one body
  get two fields. Value position works too, through design 120's
  value-conditional lowering (`let r = try { … } catch { … }`) and the
  tail normalization. PIN FLIPPED: `examples/coro_try_block_suspending.saw`;
  the 13-row position matrix is `examples/coro_try_block_positions.saw`.
  Three findings came out of building it, all fixed in the same landing
  (DF-196a/c/d) and one fence filed (DF-196b).

- **DF-196a — FIXED (design 196 unit 3, found while building it):
  reassigning an OWNING local across a suspension was a compile error.**
  `var out = "none"` … `yield_now()` … `out = "ok"` in any driven body.
  A frame-resident non-POD local is held as `T?` (the optional's tag is
  the drop flag), so a READ is `self.out!` — and the transform rewrote the
  assignment TARGET the same way, asking codegen to write THROUGH the `!`.
  That leaked the old payload until design 176 made `!` an illegal
  assignment target, and has been a clean error on an ordinary program
  since. A whole-binding write is a write of the FIELD: the same store an
  initializing `let` emits, which wraps to `Some` and drops what the field
  held. Only a bare whole-binding target changed — `out.f = v`, `out[i] = v`
  and a `ref`-encoded binding still reach their storage through the read.
  PIN: `examples/coro_reassign_owning_local.saw` (passing).

- **DF-196b (FENCE, filed + pinned by design 196 unit 3): a suspending
  `try { } catch { }` block may raise only ONE error type.** Two callees
  with different error types in one try body means the catch binds the
  synthesized `_CatchError_<id>` union, and each error edge has to wrap its
  concrete error into the right variant on the way to the frame field the
  split carries it in. Codegen builds that wrap for an IN-PLACE try/catch
  (`_wrap_error_in_union`); the split lowering hands the error over through
  an ordinary assignment and cannot ask for it. Refused cleanly at the
  user's `try`, naming both types and the two spellings that work (one
  block per error type, or an inline `try <call> catch { … }`). Fixing it
  means either synthesizing the union construction in the transform or
  moving the wrap somewhere the transform can reach. PIN:
  `examples/coro_try_block_two_error_types.saw` (a passing ERROR test — the
  fence is the behavior, so it is pinned by its diagnostic, not by XFAIL).

- **DF-196c — FIXED (design 196 unit 3, found while building it): an
  inline `catch` arm that DIVERGES was an ICE with an empty message.**
  `try f() catch { return E }` — the arm handles the error by leaving the
  function, so it reaches no merge and contributes no value, and codegen
  branched to the merge anyway. llvmlite asserted, and the wrapper printed
  `internal compiler error:` with nothing after it. Sync code, nothing to
  do with coroutines; the BLOCK form has guarded the same case since it was
  written. PIN: `examples/try_inline_catch_diverging_arm.saw` (passing) —
  four rows, incl. the same arm inside a suspending body and a `panic` arm.

- **DF-196d — FIXED (design 196 unit 3, found while building it): a
  propagating `try` in a body that SUSPENDS.** `let v = try inner(n)` after
  a `yield_now()` was ``` `try` cannot propagate errors from a function
  returning `__Poll` ``` — a type the author never wrote. The transform left
  the `try` alone and codegen tried to `ret` a Result out of `resume`. So
  design 92's failable-returns-Result idiom had NO concurrent spelling:
  `try!` panics, `try?` drops the cause, and an inline catch is not
  propagation. Same landing-pad shape as DF-193a's, with the landing being
  the frame's own done sequence over the wrapped error — `ResultErrWrap`
  when the callee's error type IS the function's, design 56's
  `ErasedErrWrap` when the function returns an erased `Result<T, Box<any
  Error>>` and the callee's error is a concrete conformer (the re-box at the
  propagation edge). Two DIFFERENT concrete error types on one statement's
  edge are refused cleanly (one error travels out of a frame; give each
  `try` its own statement). PIN:
  `examples/coro_try_propagate_suspending.saw` (passing) — five rows,
  including the spawned erased one.
- **DF-192a — FIXED by the unit that found it (192 u1): the checker's
  fourth wrap node had no re-check visitor.** Making
  `_check_expression`'s unknown-node fallthrough RAISE flushed exactly
  one node type out of the whole corpus: `ErasedErrWrap`. The checker
  BUILDS one (a concrete `E` on the way out of an erased-Result
  function), writes it back into the AST (`func.body.final_expr`,
  `stmt.value`), and then walks that same AST again on the design-146
  second pass — where it fell straight through the dispatch and returned
  `None`. Its three siblings (`visit_ResultOkWrap` /
  `visit_ResultErrWrap` / `visit_OptionalWrap`) all carry the re-check
  visitor for the documented reason (the coroutine transform rewrites
  identifiers inside `expr.value` into frame-field accesses that carry no
  `resolved_type`); this one never got it. Now it has the sibling body.
  Emission is byte-identical across all 14 erased-error corpus programs.
  No new pin: every erased-Result example in the corpus is one, since the
  fallthrough now raises rather than skipping.
- **DF-192b — FIXED (design 196 unit 2): spawning a function that returns
  an erased `Result<T, Box<any Error>>` was a codegen ICE.**
  `group.spawn(fail(7))` where `fail -> Result<Int, Box<any Error>>` died
  filling the result cell's vtable — `_get_vtable_thunk` looked up
  `__ResultCell$1$Result$2$Int$Box$2$$Any$Error$GlobalAllocator___carries_result`
  and the body was never emitted, because the cell had monomorphized under
  the arity-1 `Box$1$$Any$Error` spelling `_canonicalize_type_kind` gives
  an erased box. Two names for one type, and the vtable path was the one
  that had never been canonicalized. THE FIX IS A FUNNEL, not a patch of
  that lookup: `_erased_identity` is now the single canonical spelling an
  erasure derives every identity from, and its docstring names its two
  entry points — `_get_or_emit_vtable` (which covers the dtor, the thunks
  and the size/align header it fills) and `_type_id_for` (BOTH sides of a
  downcast). The downcast side had the same latent split: `e.is<Vector<Int>>()`
  hashed the as-written name while the vtable baked in the defaulted one.
  Pre-dated design 192 (probe-confirmed against e4761ef). PIN FLIPPED:
  `examples/erased_error_spawned_task.saw`; second row added,
  `examples/erased_error_spawned_container_result.saw` (a defaulted type
  arg at both nesting levels, plus the downcast).
- **DF-192c — FIXED (design 196 unit 1): an erased-error return in a
  SUSPENDING body was a codegen ICE.** `yield_now()` ahead of `return
  MyErr(...)` in an erased-Result function makes the body a state machine,
  so the coroutine transform lowers the return into an ASSIGNMENT into the
  frame's result slot — and codegen's `visit_ErasedErrWrap` finished
  through `_create_result_err_for_return`, which reads the ENCLOSING
  function's return type and raised `Cannot create Result.Err outside
  Result-returning function`. `ResultErrWrap` survives the same move
  because it carries its own `result_type` and passes it down; the erased
  wrap called the one-argument overload. The fix is the sibling's
  argument — one line, and the two wraps now read identically. Pre-dated
  design 192 (probe-confirmed against e4761ef). PIN FLIPPED:
  `examples/erased_error_across_suspension.saw`.
- **DF-192d — FIXED (design 198 unit 1).** A `match` with two arms for one
  enum case was an LLVM-level internal compiler error: it lowered to a
  `switch` carrying the same case value twice and llvmlite refused the
  module (`duplicate case value in switch`), while the SIBLING spelling —
  a duplicated LITERAL arm — compiled and silently took the first, because
  that lowering is a compare chain. RULED Aug 10: an EXACT duplicate arm —
  enum variant or literal — is a clean error naming both arms, and
  ranges/guards keep first-match-wins (overlap there is legitimate and
  documented). The deciding fact: a switch has no arm order, so first-wins
  was never the enum spelling's semantics — there was nothing to be
  consistent with, only a crash to replace. One chokepoint,
  `_check_duplicate_match_arms`, called before `_check_match_expr` picks a
  lowering, so both arm-checking entry points are covered by one rule.
  PINS: `examples/match_duplicate_enum_arm.saw` (flipped to a passing error
  test, still holding both spellings so they cannot drift apart again),
  `examples/match_duplicate_arm_spellings.saw` (the eight-row reject
  matrix), `examples/match_arm_overlap_legal.saw` (the accept side).
  The ledger entry left `tools/sawfuzz_known.txt` in the same landing.
  Its discovery also closed a
  unit-2 gap: `emit_ir` / `compile_to_object` run AFTER `run_codegen`
  returns and were outside every wrapper, so an IR module llvmlite refuses
  printed a raw traceback — `_run_llvm` now wraps both.
- **DF-198a — CLOSED (Aug 17).** The general pattern path now tests the
  scrutinee's LLVM shape before reading a tag, exactly as the classic switch
  path always did: a payload-free enum IS its tag, so there is nothing to
  index. The same landing narrowed that path's enum-name FALLBACK, which the
  fix made load-bearing — once payload-free enums reach the general path, a
  scan by LLVM shape alone is choosing among every payload-free enum in the
  program, all of them the same bare integer. It consults
  `self_type_context` first (design 145's rule, which the classic path had and
  this one did not) and then requires the candidate enum to HAVE the variant
  the pattern names. Route matrix:
  `examples/match_payload_free_enum_general_path.saw` — guard, tuple
  scrutinee, raw-backed (`UInt8`) enum, `Some(Red)` nesting, wildcard-with-
  guard, and the payload-carrying control; every row ICEd on the pre-fix
  compiler. PIN flipped:
  `examples/match_guard_on_payload_free_enum.saw`. Gated on suite +
  `sos_runner` both arches.
  As filed (ICE, Aug 10 by 198 u1's probes): a guarded match over an
  enum whose cases ALL carry no payload is a codegen ICE. A guard routes the
  match to the general pattern path, whose `_match_enum_pattern`
  (codegen/match.py) reads the tag with `extract_value(value, 0)` — the
  `{tag, payload}` shape. An all-payload-free enum lowers to a bare `i32`, so
  the read dies with `internal compiler error at FILE:L:C (MatchExpr): Can't
  index at [0] in i32`. A TUPLE scrutinee reaches the same line
  (`match (c, n) { case (Red, 0) -> ... }`), and adding a payload to any case
  of the enum makes both spellings work — which is why
  `examples/match_enum_guard.saw` (a `Slot` with a payload variant) never
  caught it. The classic switch path reads the tag correctly, so this is the
  general path missing the shape its sibling handles: design 190's duplication
  family again. Confirmed pre-existing (probed against the pre-198 compiler).
  Out of design 198's subject (duplicate arms), which is why it is filed
  rather than fixed. PIN:
  `examples/match_guard_on_payload_free_enum.saw` (XFAIL, cited).
- **DF-200a (over-rejection, filed Aug 10 by design 200 unit 1's rows): the
  `&var self.<field>` PROJECTION rule reads the lvalue SYNTACTICALLY, so it
  refuses a heap-reaching path the assignment rule accepts.** In a `&self`
  method, `self.rows[0][2] = 55` compiles and writes the caller's element (row
  M32 — `_writes_into_self_storage` walks TYPES and stops at the `Vector`
  indirection), while `f(&var self.rows[0][2])` is refused: the projection check
  in `_check_reference_expr` uses `_projects_from_self`, a purely syntactic
  walk that answers "inside the receiver" for anything rooted at `self`.
  One storage, two answers — design 190's duplication family, one rule with two
  implementations. Conservative (a refusal, never a silent write), which is why
  it is filed rather than fixed: aligning them RELAXES a safety refusal, so it
  wants a ruling rather than a drive-by. The write shapes are pinned either way
  by `examples/conformance/M32_shared_self_place_window_heap_field.saw`, whose
  header names this finding.
  **RULED Aug 10 (check-in): ALIGN — the projection rule adopts the same
  type-walking inline test (heap-reaching paths accepted, their
  assignment twin already legal; parameter-only refs can't escape the
  call), inline paths keep the refusal with a CORRECTED message (the
  current one claims "the write would be lost", false for heap paths).
  Small fix; ride the next typechecker fix batch, not its own brief.**
- **DF-192e — FIXED by the unit that found it (192 u3): a hex const generic
  argument was an uncaught parser crash.** `FixedBuf<0x10>()` died in
  `parse_const_expr`'s primary with `ValueError: invalid literal for int()
  with base 10: '0x10'` — no location, no message, a raw Python traceback.
  This is DF-185a at the SECOND hand-rolled site: design 185 routed the enum
  raw value through the shared decoder and left the const-expression grammar
  calling `int()` on an INT token's canonical text. Exactly design 190's
  duplication family — one rule, two implementations, the fix to the first
  never reaching the second — and, as with DF-185a, the notation that died is
  the one the feature exists for (a buffer or mask size is written in hex).
  Every notation design 50 defines works now, in the const-generic ARGUMENT
  and the const-parameter DEFAULT, the two positions that grammar serves. NO
  SPEC CHANGE OWED: LANGUAGE_SPEC's const-evaluator section already lists
  "integer and `Bool` literals, in every notation (`0xFF`, `0b1010`, `0o755`,
  `1_000_000`)" for "everywhere a constant is required — … a const generic
  argument", so this was documented-and-unimplemented the whole time, which
  is the one thing neither the suite nor a reader could see.
  PIN: `examples/const_generic_arg_notations.saw`.
- **DF-192f (ICE, filed Aug 10 by 192 u3): nothing checks that two integer
  operands agree on WIDTH, so a suffixed literal in a platform-`Int` context
  is a codegen ICE.** `n * 2i16` on an `Int n` is `internal compiler error at
  FILE:L:C (BinaryOp): Type of #2 arg mismatch: i64 != i16`; the same
  mismatch through an optional-binding value arm is `(AssignStatement):
  cannot store {i64, i64} to {i16, i16}*`. A suffixed literal is exact-typed
  (design 53 — the width-adopting rule is for a BARE literal) and Saw has no
  implicit integer conversion (design 170), so this is a plain type
  disagreement the checker should name. PIN:
  `examples/binop_mixed_width_operands.saw` (XFAIL, cited).
  **FIXED by design 195 unit 2** (all typed operands of an operation must be
  the same type; only bare literals promote). The ruling discussion's probe
  also found the SIGNEDNESS face — `i + u` (`Int` + `UInt`, same width)
  compiled SILENTLY and took SIGNED division — and it went through the same
  funnel. PIN flipped to a passing error test; both DF-192f signatures
  deleted from `tools/sawfuzz_known.txt`, which now holds one entry.
- **DF-192g (SOUNDNESS — CONFIRMED WRONG ANSWER, filed Aug 10 by 192 u3): a
  value `if` whose arms have different integer widths returns the WRONG
  ARM'S VALUE.** `func f(a: Int) -> Int { if a > 0 { 11 } else { 7i16 } }`
  compiles clean and `f(-3)` prints `11` — the then-arm's value on the path
  that took the else arm. The same program with a bare `7` prints `7`. No
  warning, no panic, exit 0. Same root as DF-192f (nothing checks integer
  width agreement) and the more serious face of it: the binop shape is loud,
  this one is silent. Reached by minimizing a fuzzer ICE. PIN:
  `examples/if_value_mismatched_width_arms.saw` (XFAIL, cited).
  **FIXED by design 195 unit 3** (value-branch arms are TRANSFERS — each arm
  merges against the reconciled type, so a same-sign widenable arm is LEGAL).
  PIN re-authored to EXPECT: success printing 11 then 7, the flip its own
  comment named. The finding reached two positions its entry did not name —
  a `match` arm and a `??` operand, where a CONSTANT narrow arm answered
  correctly BY ACCIDENT (LLVM's textual `phi` gives an incoming constant no
  type of its own) and a VARIABLE one was an ICE — and those are closed too.
  **UNIT-1 PROBE ADDENDUM (design 195, Aug 10).** Probing the twelve matrix
  rows found the finding reaches SIX positions the two entries above did not
  name, all one root: comparison mixed-width (an LLVM-level ICE) and
  comparison sign-mix (silent, signed compare on an unsigned operand);
  `&+ &- &*` mixed (ICE); COMPOUND ASSIGNMENT `a += b16` (ICE) and the
  BITWISE `& | ^` (silent — the right operand was ZERO-extended whatever its
  signedness, so a negative narrow operand masked against the wrong word),
  neither of which the brief's matrix carried; and the NEGATED bare literal
  `n * -2`, which is an adoption spelling (row 12) that the width rule never
  reached and which ICEd. Rows 9 and 10 (`match` arms, `??`) were RIGHT BY
  ACCIDENT for a constant arm — LLVM's textual `phi` prints an incoming
  constant with no type of its own, so an `i16` 7 was re-read as an `i64` 7 —
  and an ICE the moment the arm was a variable. Range bounds (row 11) and a
  narrowing `if` arm (row 8's first half) were already clean rejections. Rows
  W06-W19 of `examples/conformance/INDEX.md` carry all of it.
- **DF-195a (SOUNDNESS — WRONG ANSWER, filed Aug 10 by 195 u1's probes): an
  implicit LOSSLESS widening at a transfer extends by the TARGET's
  signedness, so an unsigned source SIGN-extends.** `let u: UInt32 =
  4000000000u32` followed by `let wide: Int = u` prints `-294967296`, and the
  same value through a `return` does too. LANGUAGE_SPEC's conversion cost
  table says the pair emits "one `zext`"; the extension is picked off the
  target instead, which is right for every signed source and wrong for every
  unsigned one. Load-bearing for design 195 rule 2: a value-branch arm is a
  transfer whose lossless widening is legal, so the widening has to be
  correct before arms can ride it. PIN:
  `examples/int_widening_transfer_preserves_unsigned.saw`.
  **FIXED by design 195 unit 3.** `_widen_int_value` is the one funnel now,
  extending by the SOURCE's signedness, its docstring listing every position
  an implicit widening happens. Fixed at `let`, `return` and a struct FIELD
  (each has the source expression in hand) and at the value-branch arms
  (through the synthesized cast rule 2 inserts). PIN flipped to a passing
  test — re-authored on the way, because its third case asserted a `UInt8`
  into an `Int16`, which design 53 refuses at a transfer whether or not the
  pair is lossless. RESIDUAL: DF-195e.
- **DF-195e — CLOSED (Aug 17).** Two implicit-widening positions extended by
  SIGNED because no source type reached them: `_coerce_call_args` and the
  fixed-array element-assignment path held LLVM values with no source
  EXPRESSION threaded to them, so `f(u32val)` into an `Int` parameter, and a
  store of an unsigned value into a wider signed element, sign-extended and
  answered negative. Fixed as the filing described — thread the expression to
  `_widen_int_value`, which already took the type. `_emitted_arg_types` is the
  one walk that builds the per-argument type list from the call expression
  (plan order for a labeled call, `arguments` order otherwise, receiver/env
  slots counted as `leading`), threaded through `_emit_call` to the funnel, so
  the ten callee kinds share it instead of growing ten parallel loops.
  Obligation 4: the mechanism is "a widening site with no source type", and a
  census of every raw `sext` in codegen/ found ONE more — `UnsafeMemory.write`
  coercing its value to the register width — fixed in the same landing; the
  remaining raw extensions (`main`'s exit status, the two format paths, the
  `as` cast lowering) each already test signedness or run under a
  signed-only branch. PIN flipped:
  `examples/int_widening_call_argument.saw`; the ten-row position matrix is
  `examples/int_widening_argument_positions.saw`, every row of which printed
  -294967296 against the pre-fix compiler.
- **DF-195b (SOUNDNESS + a RULING OWED, filed Aug 10 by 195 u1's probes): a
  NARROWING transfer through a platform `Int` truncates silently.**
  `let n: Int = 300` followed by `let b: Int8 = n` prints `44`. Design 170
  made every narrowing written (`as` panics, `from` answers `None`,
  `from(truncating:)` wraps); `_types_compatible` admits a platform
  `Int`/`UInt` into ANY integer type and bypasses all three. The permission
  exists so a bare LITERAL can adopt a fixed-width slot, a job design 87's
  expected-type propagation does properly now — so what it covers today is a
  runtime value losing its high bits. Between two FIXED widths the same
  transfer is already a clean error, so the hole is exactly the platform pair.
  DELIBERATELY OUT of design 195 (operand agreement, not conversion): closing
  it is a behavioral flip owing its own consumer sweep, and it belongs with
  design 170's rules. PIN:
  `examples/int_narrowing_transfer_through_platform_int.saw` (XFAIL, cited).
  **RULED Aug 10 (check-in): both axes become ERRORS naming design 170's
  three conversion spellings — the transfer-position twin of 195's
  operand rule. Own brief (205, to author) with its consumer sweep;
  bare-literal adoption stays untouched.**
  **FIXED by design 205 unit 2.** `_types_compatible`'s integer arm is SAME-KIND
  ONLY, and the one implicit integer conversion a transfer admits — a lossless
  widening through the platform pair — is admitted POSITIONALLY by
  `_transfer_compatible`, whose docstring names its entry points. It has to be
  positional: general assignability recurses into invariant positions (a generic
  argument, a tuple element, an optional payload), where a `Vector<Int8>` must
  not be a `Vector<Int>`. PIN flipped to a passing error test; the fifteen-position
  matrix is conformance row W20.
- **DF-195c (SOUNDNESS + a RULING OWED, filed Aug 10 by 195 u1's probes): a
  same-width SIGN-FLIPPING transfer through the platform pair reinterprets
  silently.** `let u: UInt = UInt.max` followed by `let i: Int = u` prints
  `-1`. The other axis of DF-195b, from the same `_types_compatible` arm, and
  the one design 170 checks hardest at a written cast (`-1 as UInt8` panics).
  Design 195 rule 1 closes the OPERATOR face (`i + u` is refused now); the
  transfer face rides with DF-195b. PIN:
  `examples/int_sign_flip_transfer_through_platform_int.saw`.
  **FIXED by design 205 unit 2, with DF-195b** — one admission covered both axes,
  so closing it closed both. PIN flipped to a passing error test; the matrix is
  conformance row W21.
- **DF-195d (ICE + a RULING OWED, filed Aug 10 by 195 u1's probes): mixing a
  `Float` and an integer operand is an internal compiler error.** The
  arithmetic arm answers `Float` for a mixed pair, promising a promotion the
  lowering does not implement: `a + f` dies with `Type of #2 arg mismatch:
  i64 != double` and `f + 1` with `Operands must be the same type, got
  (double, i64)`. Design 195 unit 2's funnel makes the first a clean error —
  `Int` and `Float` are two types, which is rule 1 exactly. THE OPEN
  QUESTION is the second: `f + 1` is a BARE literal beside a `Float`, and
  rule 1's own carve-out is that a bare literal adopts. Whether an INTEGER
  literal may adopt `Float` is a language question design 195 explicitly did
  not take ("float/integer mixing" is in its Explicitly out list), so both
  spellings are refused for now and the error hints at `1.0`. PIN:
  `examples/float_integer_operand_mix.saw` (XFAIL until 195 u2, then a
  passing error test).
  **RULED Aug 10 (check-in): NO adoption — an integer literal does not
  adopt `Float` (Saw has no integer→float conversion anywhere else;
  `1.0` is the spelling). The landed error + hint IS the ruled
  behavior; DF-195d CLOSES with no further work.**

- **DF-190c (VERIFY / latent must-agree, filed Aug 9, CLOSED Aug 10 by 194 u2):
  `_make_specialization_key` had DIVERGED** — codegen handled design-148
  const-value type args, the typechecker dropped them to an empty key.
  PROBE ANSWER: no, a const-generic specialization never keys through the
  typechecker copy — over the whole corpus it saw a `CONST_VALUE` argument
  zero times in 219,689 calls, and codegen's 24 const keys matched no
  registered entry either. The reason is upstream of both: a const-generic
  SPECIALIZATION cannot be written at all (`extension Ring<4>` is the parse
  error "Expected type parameter name"), so no const key is ever registered.
  Latent, never live. Both copies now delegate to one
  `ast_nodes.specialization_key`; PIN:
  `examples/const_generic_specialized_extension_unsupported.saw` (an ordinary
  expectation test — nothing is broken, and the pin flips the day the grammar
  admits a const specialization).

**194 LANDED Aug 10** (all five units; see `designs/194-contract-debt.md`). The
AST contract is declared and GATED: `tools/test_ast_graft.py` (battery lane
`astgraft`, `make astgraft`) fails on any attribute assignment in `sawc/` that
no class declares, which is design 126's own exit criterion mechanized after
five years of nobody checking it — twelve grafts had crept back, six of them
past the census. Two must-agree helper pairs deduplicated
(`ast_nodes.specialization_key`, `target_info.pointer_size_bits`) and a third
triple (`ast_walk.pattern_binding_sites`). The prelude gate runs on ANNOTATIONS
now, through one funnel over a parser-stamped written-form provenance bit
(`SawType.written_name`), closing DF-188k and DF-193d. 162 of codegen's 209
AST-field `getattr`s are direct typed reads; the 47 that remain are guards, each
named in its batch's commit. ONE finding filed (DF-194a below); two bugs fixed
on the way — the never-installed `static_globals` mangled key, and a
negative-array-length diagnostic that would have crashed on the path where the
length carries no expression, which is the first true positive Pyright could see
once the reads stopped being `Any`.

**191 LANDED Aug 10** (all five units; see `designs/191-conformance-suite.md`).
The Aug-8 audit's 247 rows are a standing suite: `examples/conformance/`, one
file per row that needed one, `examples/conformance/INDEX.md` naming the
covering test for every row that did not, and `-f conformance/` as the subset
switch. 54 rows ported, 193 deduped to existing pins — a higher dedup rate
than the census predicted, because designs 188/189/193 landed fifteen pins
straight out of this audit between the census and the port. Twelve rows were
re-authored to a RULING rather than to the audit's guess (listed in the INDEX's
"re-authored" column); one finding filed.

- **DF-191a — FIXED (design 196 unit 4): a `Mutex.lock` body that CAPTURES a
  frame-resident local of the DRIVEN function.** The rule was already right and
  its POSITIONS were not. A closure literal in a driven body captures frame
  locals through `let <name> = self.<name>.copy()` bindings the transform
  materializes AHEAD of it, and only three positions installed the accumulator
  that collects them (a `let`, an assignment, a bare expression statement).
  Everywhere else `_cap_lets` was None and the closure was refused. Now
  `_rewrite_hosting` is the ONE funnel, and its docstring names its entries: the
  body's tail (K13's own shape), a `return`, a destructuring `let`, the
  conditions/scrutinees of an in-place AND a CFG-split `if`/`match`/`if let`/
  `guard let`, a nested block's tail, a `for`'s range bounds, a nested
  suspending call's arguments, and an offloaded blocking extern's arguments. The
  one position that genuinely cannot host a statement — a bare (non-block) match
  arm expression — keeps its clean refusal, as does a `while` CONDITION (a
  capture materialized there would run once, ahead of a condition that runs
  every iteration). PIN FLIPPED: `examples/conformance/K13_mt_sum_under_mutex.saw`
  (+ its INDEX row, and the row now asserts the SUM rather than only compiling);
  the 12-row position matrix is `examples/coro_closure_capture_positions.saw`.
  Two more findings came out of it, both fixed in the same landing:

- **DF-196e — FIXED (design 196 unit 4, found while building it): two closures
  in one block capturing the SAME frame local collided.** Each materialization
  declared `let n = self.n.copy()` under the frame local's own name, so the
  second was ``variable `n` is already defined in this scope`` — and the first
  closure's `move` capture had consumed it anyway. The materialized local takes
  a FRESH name per closure now (`__capN_<name>`), and the closure is renamed
  onto it; a user-WRITTEN capture spec keeps its own name and its own meaning.
  Covered by row 5 of the position matrix.

- **DF-196f — FIXED (design 196 unit 4, found while building it): a
  suspension-spanning `match` whose arm PATTERN binds the SCRUTINEE lost the
  binding.** The frame fields for a spanning match came from the enum's variant
  PAYLOAD types, so a design-63 pattern binding the scrutinee itself — the
  catch-all `case v ->`, a tuple pattern over a tuple scrutinee, a catch-all
  over an enum — got no field, and the arm body (a separate state) read
  ``undefined variable `v``` on a legal program. `_scrutinee_binding_types` is
  the complement, permissive about the literals and ranges an arm may hold
  beside its bindings. PIN: `examples/coro_match_binds_scrutinee.saw` (passing).

- **DF-191a (ORIGINAL REPORT, filed Aug 10 by 191 u1): a `Mutex.lock` body that
  CAPTURES a frame-resident local of the DRIVEN function is refused, and the
  diagnostic's suggested workaround does not typecheck.** Conformance row K13 —
  an MT group accumulating a per-task amount into a shared `Arc<Mutex<Int>>`,
  which is the documented way to share mutable state across worker threads:
  ```saw
  func add(shared: Arc<Mutex<Int>>, n: Int) -> Int {
      shared.lock({ &var c in c = c + n  c })   // captures `n`
  }
  // group.spawn(add(shared.copy(), 1))
  // error: coroutine transform: a closure capturing a frame-resident local in
  //   this position of driven `add` is not supported; bind the closure to a
  //   `let` in straight-line body code
  ```
  The identical body with NOTHING captured (`c = c + 1`) compiles and runs, and
  so does the whole-body-in-`main` shape `examples/mutex_counter.saw` pins — so
  what the transform cannot do is specifically a capturing closure in an
  argument position of a driven body. The hint is unreachable here on top of
  that: binding the closure to a `let` first trips `Mutex.lock`'s `sync`
  requirement (``pass a `sync`-typed function value or a closure literal that is
  checked suspension-free``), so the two rules leave no spelling. Either the
  transform learns this position or the hint has to name a shape that works.
  Not a soundness issue — a clean compile error — but it blocks the canonical
  shared-counter idiom from a spawned task. PIN:
  `examples/conformance/K13_mt_sum_under_mutex.saw` (XFAIL, cited).

## Design 186 — `UnsafeMutableInterior` (ALL EIGHT UNITS LANDED, Aug 9)

`designs/186-unsafe-mutable-interior.md`. Interior mutability is a PROPERTY
now, not three names the compiler knows. Seven commits, the full suite green at
each. **Both name lists dissolved**: `namespace.py:_send_sync`'s Send/Sync
override list (`Arc`/`Mutex`/`Channel`/`Task`/`SpinLock`/`UnsafeMemory`/
`ReadOnly`/`WriteOnly`/`Vector`/`Map`/`Set`/`Data`/`StringBuilder`) and
`statements.py:_INTERIOR_MUTABLE_TYPES`. One pin flipped and was renamed
(`static_const_expr_init`, DF-185b).

Two of the migration's entries needed no replacement at all, which is the thing
a name list can never tell you: `UnsafeMemory` is a struct of one `Int` and
DERIVES both markers, and `ReadOnly`/`WriteOnly` derive from the inner type that
is literally their only field. `Map`, `Set` and `Data` derive through the
declarations on `Vector`, `Vector` and `DataBuf`+`Arc` respectively. The
interior-mutability EXEMPTION dissolved to nothing: every call it existed for is
a `&self` method the 176b rule never refused.

- **DF-186a — CLOSED by design 202: `Atomic` is move-only.**
  `extension Atomic<T>: NoCopy {}` in builtin.saw, on the spelling
  `SpinLock`/`Once`/`Mutex` already use. `NoCopy` and deliberately not
  `NoMove` — nothing pins an atomic's address, and statics are
  unaffected either way. The design-186 cell clause is UNTOUCHED and
  needed no code: `member_copy_tier` fires on the CELL ITSELF, and it
  reaches `copy_tier`, which consults `declared_copy_tier` before any
  structural join — so a declared policy on the field's own type wins,
  and `Atomic<Int>` cascades `NoCopy` upward while an undeclared
  `struct C { cell: UnsafeMutableInterior<Int> }` stays free-tier. Both
  directions pinned by `examples/atomic_nocopy_cell_clause.saw`; the
  refusals by conformance rows V26/V27, the three controls by V28-V30.
  THE FLUSH LIST matched the census exactly — five holders, nothing
  else in 1723 tests: `SlabHead` (std/slab.saw), `Job`
  (rt/common/offload.saw), and `Counter`/`Pair`/`Tagged<T>`,
  `Counter`, `Stats` in the three example files. Zero call sites needed
  a `move` or a `.copy()`; zero tests changed their expected output.
  Original entry follows.
  Should
  `Atomic<T>` be move-only? The cell is `NoCopy` as ruled, and a cell FIELD
  contributes its `T`'s copy class rather than cascading `NoCopy` onto its
  container (stated once in `Namespace.member_copy_tier`). Without that clause
  `Atomic<Int>` would become `NoCopy`, and with it every struct holding one —
  measured: std's `SlabHead` first, then the world. Rust agrees with the
  cascade (`AtomicUsize` is `!Copy`), so the question is real; it is a separate
  decision with its own migration and design 186 does not open it. What the
  clause costs today: a user `Cell<T>` wrapper is bitwise-copyable unless its
  author writes `extension Cell<T>: NoCopy {}`, which the wrapper idiom in the
  skill and the spec both say to do. Copying an `Atomic` has been legal and
  equally footgun-shaped since design 41.
- **DF-186b — CLOSED (unit 3), PRE-EXISTING.** A `static` of a GENERIC struct
  initialized by a const struct literal was `internal compiler error: 'Wrap'`.
  `_const_from_expr` looked the layout up under the TEMPLATE name, which the
  monomorphization table has never heard of, and the bare `KeyError` surfaced as
  an ICE. The non-generic form always worked, which is why it went unnoticed:
  design 41's const-init statics predate generic statics by a long way. Pin:
  `examples/static_generic_struct_const_init.saw`.
- **DF-186c — OPEN (two language gaps, one C body).** The Linux half of the
  one-word lock (`__saw_rt_lock_acquire`/`_release`) is a futex, and it lives in
  `rt/shim.c` rather than in `rt/host_linux/` because a futex needs two things
  Saw has not got: ATOMICS ON A 32-BIT WORD REACHED THROUGH A POINTER
  (`Atomic<T>` is `Atomic<Int>` in v1, and has no spelling for "atomically
  operate on this pointee"), and a VARIADIC extern (glibc's is `long syscall(long,
  ...)`, the same DF-113c gap `fcntl` sits in). Either feature shrinks the body
  back to Saw. The macOS half IS Saw (`rt/host_macos/lock.saw`, two
  `os_unfair_lock` calls). **The Linux half is UNEXECUTED**: this host is macOS,
  so it is reviewed C, not tested C — the first Linux run of the suite is what
  proves it, and `mutex_static_contention_mt` is the test that would catch it.
- **DF-186d — CLOSED (unit 5), PRE-EXISTING.** `Arc`/`Box` payload-method
  forwarding loaded the payload BY VALUE unconditionally, which is wrong the
  moment a payload's `&self` arrives by pointer. `Arc<SpinLock<Int>>.lock(...)`
  already had that shape before design 186 and ICE'd on the arity mismatch; the
  inline `Mutex` made it the common case (`mutex_counter` is
  `Arc<Mutex<Int>>`). Both forwards read the convention off the callee's emitted
  signature now. Had it type-checked instead of ICE'ing it would have been far
  worse than a crash: every thread would have locked its own copy of the mutex
  and all of them would have succeeded at once.

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

## Design 182 — Command without threads (COMPLETED by design 187, Aug 9)

Closed items: see todo_aug1-aug9.md.

**`Command.run()` landed cooperative here (Aug 8) and `Command.output()` joined
it in design 187 unit 11 (Aug 9): neither spends a thread waiting.** The four
findings this section filed against the `output()` half are all closed — DF-182c
and DF-182e in 187 units 10 and 9, the transform gaps under them in 187's unit
11 (DF-187b, DF-187c). The record of why it did not land at the time follows.

### Why `output()` did not land in 182, and the four findings behind it

Making `Command.output()` suspending is a two-line change to the same park loop
`run()` uses. What stops it is its BLAST RADIUS: suspension is colorless, so every
caller becomes a coroutine frame, and four separate limits turn up in real code
that reads a child's output. Three are transform gaps (two fixed here, one pinned);
the fourth is a language question only the user can answer.

- **DF-182c — CLOSED (design 187 unit 10).** An `if let` / `guard let` over a
  `move` SCRUTINEE whose continuation spans a suspension was rejected. The
  ordering was never the problem — the drop-flag clear belongs in both branches
  of the synthesized dispatch, as recorded — the STORE was: the dispatch's value
  path put the unwrapped payload into a frame field with a copy, which a NoCopy
  payload has none of and an ExplicitCopy one would double-drop. The store is a
  MOVE now: the binding owns the payload the unwrap produced and dies at the end
  of the dispatch arm, so the field taking ownership is exactly what it means,
  and an ImplicitCopy payload loses a retain/release pair it never needed. Pin
  flipped and renamed: `examples/coro_move_scrutinee_span.saw`, grown to the
  `guard let` twin, the None path, an ExplicitCopy payload and an ImplicitCopy
  one, and added to the Guard Malloc ownership lane (`tools/gmgate.py`) because
  a surplus release here reads correct natively. A `move` scrutinee of a
  suspension-spanning `match` stays rejected — several bindings and several
  arms, and not what this unit was scoped to.
- **DF-182e — LANDED (design 187 unit 9), as ruled.** An OWNING container is
  `Send` iff its contents are: `Vector`, `Map` and `Set` inherit their type
  ARGUMENTS' answer (the allocator argument included — a policy type carries
  what it carries, and `GlobalAllocator` is empty), and `Data`/`StringBuilder`
  are unconditional by `String`'s argument. Sync follows the same inheritance
  rather than being pinned False: `&var` access to any of them goes through the
  Law of Exclusivity, so sharing one is safe exactly when sharing its contents
  is. Landed where the ruling said — the by-name override list in
  `namespace.py:_send_sync` — and INTERIM by construction: design 186's
  migration sweep replaces the whole list with declared `UnsafeSend`
  conformances. Tests: `examples/taskgroup_send_containers.saw` (each container
  held across a suspend in `TaskGroup(threads: 2)`, plus a
  `Vector<Vector<Int>>`; counts and sums only, ten repeats one outcome) and
  `examples/errors/taskgroup_threads_nonsend_reject.saw`, rewritten so the
  ELEMENT is what refuses it — a `Vector` of closures, closures not being Send.
  Original ruling text follows. Mechanism NOW: additions to the by-name
  override list (`namespace.py:_send_sync`) in the 182-COMPLETION unit below;
  mechanism LATER: design 186's declared `UnsafeSend` conformances replace the
  whole fiat list in its migration unit. **The 182-completion unit** (queued
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
  starve every sibling task for the child's whole lifetime.** **CLOSED WHOLE
  (design 182 + design 187 unit 11, Aug 9):** `run()` parks on the reactor and
  spends no thread (182); `output()` joined it — its stdout drain is an offloaded
  `blocking` seam and its reap is `run()`'s park loop, shared as
  `Command.reap`. Neither holds the executor thread for any part of a child's
  life. Pin: `examples/process_output_concurrent.saw` (renamed from
  `_starvation_xfail` when it flipped). The v1 blocking reap
  `__saw_rt_proc_wait` had no callers left and was removed from the frozen ABI.
  The original finding follows. Both reap via
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
  argument.** **CLOSED WHOLE (design 184, Aug 9):** the seam carries the address
  and `connect` dials the host it is given; a NAME is resolved through
  `getaddrinfo` on a worker thread while siblings run, and an unresolvable one
  is an `Err` naming it. See the design-184 section above. Original finding
  follows.
  `connect(host: String, port: Int)` never reads `host` —
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
  **RE-EXAMINED against design 188 unit 2 (Aug 9) and NARROWED, not closed.**
  Re-probed on the landing: `self.grid[0] += 100` in a plain `&self` method
  still prints `first 1` (`.build/scratch/p176c.saw`). Unit 2 folded place
  window ROOTS into the Law of Exclusivity, which is about how many accesses one
  CALL makes; 176c is about how the receiver reached the window in the first
  place, and a single write through a single window makes exactly one access. So
  the two do not overlap and unit 2 changes nothing here. What the landing does
  settle is the family framing in this entry: the "same lost mutation" cases
  where TWO accesses were involved are now exclusivity errors on every tier, and
  what remains under 176c is exactly the receiver-COPY half — a `&self` method
  writing through a place window on an INLINE field (vanishes), and the borrows
  body writing one on a `let` root (lands).
  **RULED Aug 10, owned by design 200:** the plain-body half is the
  design-176 receiver-write ERROR extended to the synthesized window
  call (fix in the place lowering, exclusive windows only, heap-reaching
  fields keep the carve-out); the borrows-body half is RATIFIED as
  intended behavior (by-pointer receiver; `#lend_var` gates the shared
  specialization).
  **CLOSED by design 200 (Aug 10).** Both probe shapes reproduced exactly as
  filed before the fix — the plain body printed `first 1`, and the borrows body
  left a `let` root's counter at 2 after two pure reads — and each is a
  conformance row now (M31 row 1, M33). The refusal needed a fact the compiler
  did not have: WHERE an accessor lends from. `place_transform` records each
  lending path's shape (`(('member', 'cells'), ('index',))` for
  `lend self.cells[i]`; nothing for a lend through an indirection the receiver
  points at), and `place_uses` walks it against the receiver's real type, so
  design 176's inline-vs-indirect walk gains the one hop it could not take and
  composes through nesting. `lend self.inner[i]` keeps working: the forwarding
  accessor records an `index` hop into a `Vector`, which is not inline, so the
  outer accessor lends nothing inline either. PINS: `examples/conformance/`
  M31 (the seven-row position matrix), M32, M33, M34, M35.

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
- **DF-169f — a place WRITE whose RHS names `self` is an ICE — FIXED** by
  design 216 unit 1: it was DF-216a's missing `SelfExpr` arm reached through a
  COMPILER-SYNTHESIZED closure rather than a written one. One mechanism, two
  entry points. The pin now passes; original report below.
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
  places batch. Pinned: `examples/place_write_self_rhs.saw`.
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
- **DF-169h — CLOSED (Aug 22, `place-window-fixes`): a place window's body
  captures the enclosing scope BY BORROW.** The synthesized window closure now
  carries `[&x]`/`[&var x]` specs for every enclosing binding its body names —
  it is a lowering device, not a value, so the code inside it must run against
  the live bindings — and the borrow rides the very rule that admits a
  hand-written `[&var x]` (a direct argument to a non-escaping parameter). Two
  names stay value captures on purpose, each keeping a refusal exactly where it
  was: the receiver's own ROOT (borrowing that would put a second access to the
  root inside the open window — design 188; the bogus half of that boundary is
  DF-248a), and a name the body MOVES (DF-218h — `move` out of a borrow
  capture is not a transfer the language has, and the copy-tier refusal is the
  protective answer until the closure move-out design lands). The moved-name
  exclusion was CORRECTED IN, one commit later: without it the borrow capture
  lifted DF-218h's refusal and its pin compiled and DOUBLE-FREED, and the suite
  stayed green because an XFAIL that fails for a WORSE reason is still a known
  failure (DF-248c face 2). A REFERENCE-typed binding is not an exclusion — see
  DF-248b, whose window face landed with that correction. The sweep found a
  much wider face than the pin: `v[0] =
  w[1]` over two disjoint containers was the ExplicitCopy twin of the same
  refusal. Pin flipped (`examples/place_nocopy_arg_in_window.saw`) + the sweep
  matrix `examples/place_window_borrows_enclosing_locals.saw`; LANGUAGE_SPEC's
  "Window extent and nesting" and the skill's CBOR gotcha say so. Original
  finding follows.
  **(BOGUS REFUSAL) — a place window refuses a `&var` argument naming a NoCopy
  LOCAL.**
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
  `examples/place_nocopy_arg_in_window.saw`.
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

### DF-138c — CLOSED (design 188 unit 7): `std.slab` is gated

Resolved the second way it was filed: the gate had a hole, `sawc` was the bug,
and the three slab examples gained `import std.slab.*`. `std.spinlock` turned
out to be the same omission (DF-188i / audit W01) and both are in
`IMPORT_REQUIRED_STD_MODULES` now. The decision needed no ruling in the end —
the spec's own module table already said gated, and the reason it stayed open
was that nothing tied the table to the list. `tools/test_prelude_gate_doc.py`
(`make preludegate`) ties them: every module the table marks gated must be in
the set, and every module in the set must have a row that does not claim
otherwise.

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
  catches instances, not the class. The sweep's COST side is design 220's
  target (suite-IR reuse halves the --all gate in the steady state).

  **QUEUED (user, Aug 14) — rides the mech fix batch** (with the DF-153b
  SYS_* rename + ElfSegFlag items), not its own brief. Shape decided:
  taint-tracking "reaches emission" is not attempted; instead
  deterministic-by-construction — `tools/test_set_iter.py`, an AST walker
  over `sawc/` in the `tools/test_ast_graft.py` mold, new battery lane.
  Any iteration over a syntactically-resolvable set (for/comprehension/
  `join`/`list` of a `set()`, set literal, set comprehension, or set-typed
  self-attribute) must be `sorted(...)` or carry an explicit
  `# order-irrelevant` marker. Measured churn at queue time: ~107 `= set()`
  decls in sawc, 11 iterations already sorted — a one-time classification
  sweep of a few dozen sites. Earned by four instances of the class
  (design 126's two, design 141's two), all one mechanism.

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

- ~~**Design 212 — long-function decomposition sweep**~~ — **LANDED Aug
  12**, units 0-6 (unit 7 skipped per the brief's more-machinery clause),
  tracked battery green. Two findings filed: DF-212a, DF-212b (above).
  Was: (RULED + AUTHORED Aug
  12, dispatched to a Sonnet agent as a mechanical pass). Extraction
  refactor over the Aug-12 review's two hot spots (taskgroup.saw's
  `g[0].<field>` chains, blade) plus a handful of plain duplications and
  one enum-idiom miss; zero behavior change, sos/ out of scope.
  [designs/212-long-function-decomposition.md]
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
