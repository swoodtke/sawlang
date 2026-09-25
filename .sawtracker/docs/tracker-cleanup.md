# Tracker cleanup

The Python compiler is frozen (Sep 24), so the SL tracker is being cleaned up for
the new compiler's work. Six read-only sweep agents classified all 299 open SL
issues. The lead reviewed their calls, and those corrections are applied below.

## Applied (Sep 25)

The user approved every recommendation ("i agree with all your
recommendations"), and for decision 9 ruled "close the remote worker issues".

- **201 issues closed.** Each has a label (`frozen`, `superseded`, `done` or
  `duplicate`, plus `hazard` where flagged) and a comment pointing here. The
  SL-367 epic needed `--force`, because its child SL-340 stays open.
- **98 issues kept,** relabelled `language`, `runtime`, `std`, `product` or
  `tooling`, or `frozen` plus `pinned` for the ten pinned issues. Kept issues
  that were queued moved to the backlog, so **the queue is empty** for the new
  compiler's work.
- **Five carry-forward issues created:**
  - SL-393: the rule inventory's carried rulings and test inputs;
  - SL-394: decompose the runtime functions marked wholly unsafe;
  - SL-395: std gaps (bit intrinsics, checked and saturating arithmetic, radix
    formatting, iterator adaptors);
  - SL-396: decide `select` / receive with timeout;
  - SL-397: `unix_timestamp` is documented but not public.
- **Four parked patches deleted,** with the reason recorded: SL-2.p2, SL-345.p1,
  SL-328.p1 and SL-355.p1. Deleted records still return their diffs.
  SL-355.p1's runtime half is attached to SL-355 (c19), at the Air's request.
  SL-340.p1 stays with its pinned issue.
- **Architecture corrections are in SL:architecture r17 and r18.**
- **Result:** 103 open SL issues, all in the backlog: 39 `language`,
  18 `runtime`, 16 `product`, 15 `std`, 10 pinned and 5 `tooling`. (SL-398 and
  SL-399, the new compiler's epic and its first unit, were created afterwards.)
- **SL:hazards is published,** and it grew from the 82-ID handoff to 86 entries
  after the Air's review. SL-68, SL-71, SL-83 and SL-390 were promoted. The
  `hazard` label now covers exactly those 86 issues, SL-14 and SL-107 included
  (Air t5).

## Summary

| Action | Count |
|---|---|
| Close as `frozen`: Python-compiler bugs | 150 |
| Close as `frozen`: Python-compiler tooling | 5 |
| Close as superseded by SL:borrowing, SL:testing or SL:architecture | 24 |
| Close as already done | 12 |
| Close as a duplicate | 1 |
| Keep open, label `frozen` (cited by an XFAIL pin, so the `citations` lane stays green) | 10 |
| Keep, label `language` | 36 |
| Keep, label `runtime` | 16 |
| Keep, label `std` | 13 |
| Keep: tooling the new compiler reuses | 5 |
| Keep: not about the compiler | 15 |
| Needs the user | 12 |

So about **190 close** and about **95 stay**, along with the 12 decisions below.
82 issues are flagged as hazards for bootstrap Stage 0, and they become
SL:hazards (Carried forward, item 2). The Hazard column of the frozen-bugs table
shows 76 of them. The other six sit in tables without that column: four pinned
issues (SL-38, SL-41, SL-80, SL-340) and two closing as done (SL-14, SL-107),
whose shapes still count.

## Decisions for the user

Each has the lead's recommendation.

1. **SL-105: does design 200's carve-out survive?** Today a `&self` method may
   write storage it reaches through a pointer, such as `self.rows[0].push(9)`,
   because "the copy shares the buffer" (conformance rows M28 and M32). Under
   the new model that is a write through a shared borrow. Another holder of
   `&x` may be reading `rows[0]` while the push reallocates it.
   **Recommend: retire it.** Interior mutation happens only through cell types
   (`Mutex`, `Atomic`, the `(&self) borrows -> &var T` shape of SL:borrowing
   §3). M28 and M32 become refusals, annotated "language changed".
   **Ruled: retire it** (user, t2: "I agree"). Recorded in SL:borrowing §9.
   SL-105 closes as superseded.
2. **SL-328 and SL-289: the prototype track** (M21 parser, minivm).
   **Recommend: close both, delete SL-328.p1, and keep the branches as
   reference.** SL:architecture §3.2 takes M21's fixtures and harness when the
   parser work starts, and declines its iterative control stack. The minivm
   pauses; the planned VM backend can revisit it.
   **Ruled: yes** (user, t3).
3. **SL-355: the SL-353 fix brief.** SL:architecture §3.9 settles R1–R4.
   **Recommend: keep it open as `runtime`,** carrying the ruled R5 (the atomic
   wake word with a CAS latch) for the runtime, which carries over. Delete the
   parked patch.
4. **SL-373: widen the per-patch server gate.** Most of the lanes it adds gate
   frozen sawc code. **Recommend: close.** The new compiler's gate is designed
   with its test runner.
5. **SL-166: small-string optimization,** gated "before separate compilation
   or never". **Recommend: keep as `language`,** decided before `String`'s layout
   is fixed in the new std, since shipped package interfaces fix layouts
   (SL:architecture §3.12).
6. **SL-146: the `io_wait` intrinsic gate.** **Recommend: close.** The spec
   already calls `io_wait` private, and test sidecars (SL:testing §4) give the
   reactor's white-box tests private access.
7. **SL-18: linter scope** (design 248). Both halves sit on the frozen
   compiler. **Recommend: keep in the backlog** until the new compiler's
   diagnostics and dumps exist.
8. **SL-279: the `Timed<T>` hint** points at borrowing when `match move` is
   needed. **Recommend: close as `frozen`.** It is a Python-compiler hint, and
   `match move` is already the spec's rule.
9. **SL-127, SL-128, SL-129: the design-160 remote test worker,** unchanged
   since Aug 7. **Question:** do you still run it? If not, close all three.

## Carried forward before anything closes

Closed issues stay readable, but these items must also live somewhere current:

1. **Rulings recorded only in the tracker,** which go into the rule inventory
   (SL:testing §6), and where needed into the spec:
   - SL-59: statement arms in `match` (design 259 R7′).
   - SL-73: the general postfix call (Sep 23). SL:architecture §3.2 covers its
     parse, not its typing rule.
   - SL-309: `??` or a second `?` in a cast target is refused. LANGUAGE_SPEC
     still teaches the opposite ("operator wins"), so the spec is corrected.
   - SL-310: a bare trailing closure on a free function is a call (R6).
   - SL-45: design 259 R2.
   - SL-2: the rulings design 274 still owes (N2, U5′). B1 is settled: SL-347
     refuses `x = 1 y`.
2. **Hazards,** which become SL:hazards, silent ones first. The handoff is
   checked against this inventory of unique IDs (codex t1), so closing an
   original cannot hide a missing entry:
   - **the 82 flagged issues:** SL-5, SL-7, SL-13, SL-14, SL-22, SL-28, SL-31,
     SL-32, SL-36, SL-38, SL-41, SL-42, SL-45, SL-46, SL-49, SL-50, SL-52,
     SL-53, SL-56, SL-59, SL-61, SL-62, SL-63, SL-65, SL-70, SL-73, SL-74,
     SL-75, SL-77, SL-78, SL-80, SL-84, SL-85, SL-88, SL-96, SL-107, SL-111,
     SL-113, SL-114, SL-115, SL-125, SL-130, SL-131, SL-132, SL-133, SL-156,
     SL-191, SL-192, SL-194, SL-195, SL-199, SL-240, SL-264, SL-270, SL-284,
     SL-285, SL-288, SL-290, SL-291, SL-292, SL-293, SL-294, SL-295, SL-297,
     SL-298, SL-299, SL-308, SL-309, SL-310, SL-319, SL-340, SL-348, SL-352,
     SL-358, SL-363, SL-368, SL-380, SL-381, SL-382, SL-383, SL-384, SL-389;
   - **separately, the cases in SL-2's last comment** (codex c29), which have
     no issue of their own: an uncharged `move *p`, a lexer crash on a
     trailing backslash at end of file, a misanchored quote inside a `//`
     comment in an interpolation, and a comma-free next case after an
     operand-less `return` or `break`.
3. **Test-plan inputs for the rule inventory:**
   - SL-214's interaction matrix (sources × copy tiers × positions ×
     generic/concrete × sync/suspending);
   - SL-175's four owed TaskGroup conformance rows;
   - branch `sl340`'s conformance rows K170–K179;
   - SL-390's table of alias- and depth-bounded walks;
   - SL-353's parksoak stress kit;
   - rules the spec is silent on: float-literal underflow (SL-68),
     `break`/`continue` in a closure body (SL-286), `escaping` inside an
     optional parameter type (SL-293), and a bare `None` arm at nested-optional
     destinations (SL-264).
4. **Splits,** made as new issues when this is applied:
   - SL-118 hides two live items: decomposing the runtime functions marked
     wholly unsafe (design 130; `runtime`), and std gaps (bit intrinsics,
     checked and saturating arithmetic, radix formatting, iterator adaptors;
     `std`).
   - The `select` / receive-with-timeout question in SL-176 and SL-185 becomes
     one `language` issue.
   - SL-165 and SL-185 are mixed roadmap lists. They are trimmed to their open
     parts; slices are settled by SL:borrowing §6.
   - `unix_timestamp` in `sawc/std/time.saw` is documented API but not
     `public` (found through SL-132): a new `std` issue.
5. **Architecture corrections,** already in SL:architecture r17:
   - SL-3: generic effects are conditions over type arguments, keeping design
     70's `run<Fast>`/`run<Slow>` rule;
   - SL-380: postfix chains stay nested and charge per hop;
   - SL-313: a native stack overflow is a SIGSEGV today, and the runtime owes
     a guard-page handler;
   - SL-182: `noalias` from exclusivity.

   Added since (r19–r20): SL-99, closure symbols named by content rather than
   source line (§3.0).
6. **Epic SL-367** closes. Its runtime members SL-354 and SL-355 stay.
7. **How each closing issue is marked:** a label (`frozen`, `superseded`,
   `done` or `duplicate`) and a short comment pointing here, plus the doc
   section for superseded issues. Parked patches on closing issues (SL-2.p2,
   SL-340.p1 stays with its pinned issue, SL-345.p1, SL-328.p1) are deleted
   with the reason recorded.

## The full classification

### Close as `frozen`: Python-compiler bugs (150)

| ID | Title | Aspect | Hazard |
|---|---|---|---|
| SL-5 | DF-303b: Discover generic methods even when a free function has the s… | mono.generic-method-name-collision | yes |
| SL-6 | DF-301a: Emit valid frame types for generic-struct closure parameters | coroutine.frame.closure-param |  |
| SL-7 | DF-301b: Infer closure parameters from an annotated function-type let | closure.param-inference.annotated-l… | yes |
| SL-8 | DF-297a: Share namespace symbols when snapshotting generic templates | n/a (sawc perf) |  |
| SL-13 | DF-242c: Disambiguate integer overloads using exact-typed literals | overload.resolution.suffixed-literal | yes |
| SL-15 | DF-225o: Reproduce compiler reemit divergence under load | determinism.emission-order |  |
| SL-22 | DF-218t: Handle non-integer results of value-position loops | loop.value-position.break-value | yes |
| SL-23 | DF-242a: Release driven try-body locals at the error edge | drop.try-catch.driven |  |
| SL-24 | DF-218w: Align mixed-pattern payload release timing between sync and … | drop.match-payload.driven |  |
| SL-25 | DF-247a: Keep ordinary calls resolvable when a function is also a spa… | coroutine.spawn-root |  |
| SL-28 | DF-250a: Shape collection literals through a Result Ok payload | literal.collection.result-payload | yes |
| SL-29 | DF-250b: Refuse an invalid None coalescing default without an LLVM cr… | optional.coalesce.none-default |  |
| SL-31 | DF-251b: Register owning parameter cleanup in generic initializers | drop.generic-init-param | yes |
| SL-32 | DF-251c: Substitute renamed extension parameters at initializer calls | generic.extension-param-rename.init | yes |
| SL-33 | DF-251d: Define and lower suspending initializer calls safely | coroutine.suspending-init |  |
| SL-36 | DF-257a: Apply the same defaulted-init selection to bare and qualifie… | init.selection.defaulted-param | yes |
| SL-40 | DF-259b: Explain reserved words at every declaration-name position | diagnostics.reserved-word |  |
| SL-42 | DF-215g: Infer None against the optional result of a comparison opera… | literal.none.comparison | yes |
| SL-43 | DF-262b: Fix the suspend-interpolation, task-result and optional-wrap… | coroutine.anf.autowrap |  |
| SL-44 | DF-264a: Validate Copy deinit signatures consistently with the other … | copy-tier.deinit-signature |  |
| SL-45 | DF-266a: Parse a negative tail after if-return without a BinaryOp cra… | parse.newline.leading-minus | yes |
| SL-46 | DF-267a: Resolve Optional methods on optional-typed borrows places | borrow.conditional-lend.optional-me… | yes |
| SL-47 | DF-267c: Allow indexed lends through match-bound payload places | borrow.lend.payload-index |  |
| SL-49 | DF-270b: Reject invariant generic Alias/Underlying mismatches consist… | alias.distinct.generic-invariance | yes |
| SL-50 | DF-270c: Validate alias types in trait-conformance signatures | alias.distinct.conformance-signature | yes |
| SL-52 | DF-275a: Discharge alias trait bounds consistently at free generic ca… | alias.trait-bound | yes |
| SL-53 | DF-277a: Apply literal adoption to synthesized backed-enum factories | literal.adoption.synthesized-static | yes |
| SL-54 | DF-271a: Reconcile std pre-check try propagation in nested generic bo… | try.generic-body |  |
| SL-56 | DF-269a: Apply bare-literal adoption after label-based overload selec… | overload.literal-adoption | yes |
| SL-59 | DF-215j: Implement the ruled statement-arm grammar for return in matc… | match.statement-arm | yes |
| SL-61 | DF-261c: Honor handwritten Equatable.equals for enums | equatable.enum-user-equals | yes |
| SL-62 | DF-261d: Forward Box payload methods to enum payloads | box.method-forwarding | yes |
| SL-63 | DF-261e: Lower optional chains through Box fields without BindOptiona… | optional.chain.box-field | yes |
| SL-64 | DF-261f: Diagnose recursively suspending functions without a raw trac… | coroutine.frame.recursion |  |
| SL-65 | DF-272a: Infer closure arguments from enum-variant payload types | closure.inference.enum-payload | yes |
| SL-67 | DF-272c: Make std and user checks agree on maybe-suspending place win… | borrow.window.suspension |  |
| SL-68 | DF-276a: Diagnose unrepresentable float literals instead of producing… | literal.float.range |  |
| SL-70 | DF-276c: Propagate operand width into literal-valued if and match exp… | literal.adoption.branch | yes |
| SL-71 | DF-280b: Report prelude type-name collisions at construction sites | diagnostics.prelude-collision |  |
| SL-73 | The general postfix call: a Call node whose callee is any expression … | call.general-callee | yes |
| SL-74 | DF-287a: Keep fall-through ownership after a move in a diverging catch | move.diverging-catch | yes |
| SL-75 | DF-287b: Apply bare-literal adoption during overload resolution | overload.literal-adoption | yes |
| SL-77 | DF-294b: Preserve type aliases through glob and qualified imports | import.alias | yes |
| SL-78 | DF-299d: Preserve explicit generic type arguments on qualified initia… | import.qualified.generic-init | yes |
| SL-84 | DF-178e — a bare literal does not adopt an annotated type through a m… | literal.adoption.match-arm | yes |
| SL-85 | DF-221a (NEW, found writing design 221's conformance row G11) — a Res… | enum.zero-sized-payload | yes |
| SL-86 | DF-218b (BOGUS-REFUSAL, found probing DF-218a, pre-existing and unrel… | borrow.window.mode |  |
| SL-87 | DF-218c — the driven-path channel refusal is channel-blind and anchor… | channel.receive.copy-policy |  |
| SL-88 | DF-218d (ICE, sawfuzz-oracle class) — a value-if statement followed b… | syntax.newline.unary-minus | yes |
| SL-89 | DF-218u: Verify destructuring redefinition cleanup on non-frame-resid… | drop.redefinition.destructuring |  |
| SL-94 | DF-215b — move of a frame local in a nested block's TAIL expression i… | move.block-tail.coroutine |  |
| SL-96 | DF-212c (RECORDED, pre-existing, found while fixing DF-212b) — a gene… | generic.param-shadows-type | yes |
| SL-98 | DF-204a — four std internals still reserve their names, because the c… | std.type-identity.compiler-named |  |
| SL-99 | DF-204b — a closure's codegen symbol carries the LINE it was written … | mangling.closure-symbol |  |
| SL-100 | DF-210c: Complete surviving declaration-time AST annotations | internal.ast-annotation |  |
| SL-101 | DF-210d: Audit the unused ForceUnwrap.frame_move_read marker | coroutine.frame.force-unwrap |  |
| SL-102 | DF-206c (FILED, not fixed) — a TAIL-position ch.receive() is a compil… | coroutine.suspension.tail-position |  |
| SL-103 | DF-206d: Audit name versus node-identity keying at the std effect seam | effect.suspend-inference |  |
| SL-104 | DF-196b (FENCE, filed + pinned by design 196 unit 3): a suspending tr… | coroutine.try-catch.error-union |  |
| SL-111 | DF-176a: Revisit same-root place read/write spelling when a consumer … | assign.rhs-before-lhs | yes |
| SL-112 | DF-175c — OPEN (minor, docs). --emit-docs cannot distinguish a &var s… | docs.emit.receiver-kind |  |
| SL-113 | DF-169e — a STATIC trait requirement is not callable on a type PARAME… | trait.static-requirement.generic-ca… | yes |
| SL-114 | DF-169g — the automatic ImplicitCopy tier does not satisfy a Copy BOU… | copy-tier.bound | yes |
| SL-115 | DF-169i — a std-module static as a DEFAULT PARAMETER VALUE breaks at … | default-param.module-static | yes |
| SL-118 | DF-146p — OPEN, diagnostic quality (Aug 6; RENUMBERED from DF-146l by… | diagnostics.exclusivity-window |  |
| SL-123 | DF-168a — _CatchError_{node_id} is the last node-id-derived name in t… | try-catch.error-union |  |
| SL-124 | DF-168b — the place-lowering re-entry re-checks std for every program… | perf.place-lowering |  |
| SL-125 | Verify whole-module imported type names and their diagnostics | import.qualified | yes |
| SL-126 | DF-163b — a nested yield_now()/sleep() silently does not cede. A user… | effect.suspend-inference |  |
| SL-130 | DF-151m — FILED, NOT FIXED (typechecker; found while fixing DF-151j, … | mutability.let-projection-ref | yes |
| SL-131 | DF-151k — FILED, NOT FIXED (typechecker; found while fixing DF-151i, … | copy-tier.bound.optional-tuple | yes |
| SL-132 | DF-140h-fn — OPEN, stopped deliberately (unit A, design 145). Wants i… | visibility.private-function | yes |
| SL-133 | DF-148a — FILED (design 148 unit B). A repeat literal cannot repeat a… | literal.repeat.generic | yes |
| SL-134 | Measure reusable Printable formatting scratch storage | format-args.printable-scratch |  |
| SL-139 | DF-126a: Verify the latent pre-port AST annotation contract | mono.type-substitution |  |
| SL-147 | Design multi-hop optional-chain assignment with a suspending RHS | optional.chain-assign.suspending |  |
| SL-148 | Verify source anchors for NoCopy optional-chain suspension refusals | diagnostics.anchor |  |
| SL-150 | Verify the historical two-suspend helper embedding report | coroutine.embed |  |
| SL-151 | Verify frame layout for spawn parameters containing std task types | coroutine.frame-layout |  |
| SL-156 | L2. Return-type reconciliation for type-param/associated-type returns… | generic.return-type-check | yes |
| SL-180 | Audit residual findings from the ownership and labeled-call sweeps | copy-tier.generic-body |  |
| SL-182 | Reconcile and measure the warehouse lowering performance plan | borrow.place-lowering |  |
| SL-184 | Verify nested generics whose templates suspend unconditionally | coroutine.generic-nested |  |
| SL-188 | Anchor prelude ambiguity diagnostics on the real declarations | diagnostics.anchor |  |
| SL-191 | Allow element writes through a directly borrowed mutable fixed array | reference.array-element-write | yes |
| SL-192 | Enforce borrowed place-match ownership, including nested read-only ma… | match.place-payload-move | yes |
| SL-194 | Reconcile platform UInt literal adoption across overloads and enum fa… | literal.adoption | yes |
| SL-195 | Give module-level statics defining-module identity | static.module-identity | yes |
| SL-197 | DF-218s remainder: pattern bindings and value-block release timing | drop.order.coroutine |  |
| SL-198 | DF-257c remainder: carry per-instantiation try annotations | try.generic-instantiation |  |
| SL-199 | Design 197 remainder: route the six parse_type bypasses through one p… | import.qualified.declaration-positi… | yes |
| SL-216 | ICE: driven `match <Optional> { case Some(v) -> v, ... }` — payload b… | coroutine.match-payload-binding |  |
| SL-217 | a module-qualified suspending free call cannot be a drive/spawn ROOT,… | coroutine.spawn-root |  |
| SL-221 | a suspending parameter default cannot be OMITTED at a call that build… | coroutine.default-argument |  |
| SL-232 | coroutine frame slot count makes object emission quadratic: 3 frame b… | coroutine.frame-layout |  |
| SL-233 | the three deep-lookup walks in Namespace want one funnel (obligation … | import.transitive-lookup |  |
| SL-240 | A discarded statement-position inline try/catch leaks its owning valu… | drop.discarded-try-catch | yes |
| SL-264 | Bare None arm of a value if/match at a nested-Optional annotated dest… | optional.nested-none-arm | yes |
| SL-270 | Set element and Map key gates call the automatic Copy tier move-only;… | copy-tier.collection-key | yes |
| SL-271 | The .copy() refusal on an automatic-Copy-tier receiver asserts the ty… | diagnostics.copy-tier |  |
| SL-281 | A driven [move x] capture of an ExplicitCopy frame local runs copy(),… | coroutine.closure-capture.move |  |
| SL-283 | Driven match with a guarded arm double-frees an OWNING payload binding | coroutine.match-guard-payload |  |
| SL-284 | Nested implicit method receiver borrows escape whole-call exclusivity… | exclusivity.nested-receiver | yes |
| SL-285 | Named borrowing accessors silently ignore argument labels | call.labels.borrows-accessor | yes |
| SL-286 | ICE: break/continue inside a closure body emits a branch to a label i… | closure.break-continue |  |
| SL-288 | Box<any Trait>.take<T>() on a PROJECTION receiver double-frees the bo… | move.consuming-call-projection | yes |
| SL-290 | sawc: nested Optional argument compatibility reaches incompatible LLV… | optional.nested-arg-wrap | yes |
| SL-291 | sawc: Result payload assignment omits implicit wrapping at declared d… | result.auto-wrap.assignment | yes |
| SL-292 | sawc: annotated Result value branches lose destination wrapping conte… | result.auto-wrap.value-branch | yes |
| SL-293 | A closure literal at an Optional-wrapped function slot does not take … | closure.optional-slot | yes |
| SL-294 | sawc: later value arguments bypass whole-call borrow access checks | exclusivity.whole-call-args | yes |
| SL-295 | sawc: dead statements after unconditional return poison the function … | control-flow.unreachable-tail | yes |
| SL-296 | sawc: missing Result type argument reaches codegen with unbound E | generics.arity |  |
| SL-297 | sawc: repeated named constructor arguments are silently accepted | call.labels.duplicate | yes |
| SL-298 | sawc: conditional return permits a reachable value-less function exit | control-flow.missing-return | yes |
| SL-299 | sawc: out-of-range bare Int literal silently truncates to -1 | literal.int-range | yes |
| SL-308 | N1 (design 259/274): parser recursion is unguarded — 300 nested paren… | parser.depth-limit | yes |
| SL-309 | N2 (design 259/274): 'as Int??' — whitespace decides the cast target … | parser.cast-optional-target | yes |
| SL-310 | N3 (design 259/274): a bare trailing closure on a FREE function is no… | closure.trailing.free-call | yes |
| SL-311 | N5 (design 259/274): an unclosed '{' is reported at the NEXT 'func' i… | diagnostics.anchor.unclosed-brace |  |
| SL-312 | N6+N7 (design 259/274): '.5' gets a bare 'Unexpected token: DOT' wher… | diagnostics.lexer-literal |  |
| SL-315 | A [&var x] borrow capture writes nothing when the enclosing body is a… | coroutine.closure-capture.reference |  |
| SL-319 | a module-qualified free call into a user module resolves to a std fre… | import.qualified-call | yes |
| SL-320 | a user module named std breaks the compilation of std's own files (IC… | module.reserved-std-root |  |
| SL-332 | a generic METHOD template naming a consumed callee is stripped even w… | coroutine.template-consumption |  |
| SL-345 | USE-AFTER-FREE: a closure's captured reference-param root is not char… | closure.capture.reference-exclusivi… |  |
| SL-346 | A value-position loop in a driven body is refused by naming the op bu… | diagnostics.coroutine.op-budget |  |
| SL-348 | sync: a by-value move argument evaluated before a failing propagating… | drop.try-abandoned-argument | yes |
| SL-349 | A driven derived shadow of a module static reads the shadow's own emp… | coroutine.shadow-static |  |
| SL-351 | A callable associated Item (next -> (() -> T)?) draws a spurious Item… | diagnostics.associated-type.function |  |
| SL-352 | An immediately-invoked closure literal { … }(x) is not applied in bin… | closure.immediate-invocation | yes |
| SL-353 | Completed stdout offload remains I/O-parked in MT irdet; root readine… | coroutine.park-protocol |  |
| SL-358 | ICE: a module-qualified const-generic construction with no expected t… | generic.const.qualified-construction | yes |
| SL-363 | A constant repeat/fixed-array literal at a memory destination still b… | literal.repeat-array.large | yes |
| SL-364 | ICE: an Int?? parameter of a suspending function (nested optional acr… | coroutine.frame.nested-optional |  |
| SL-365 | A suspending generic cannot return its own local at R = Void: `functi… | coroutine.generic-void-return |  |
| SL-368 | A &self method called directly on a pointer-index receiver (p[0].stor… | receiver.pointer-index-place | yes |
| SL-369 | Passes behind the parser ICE below the ruled nesting limit of 256 | syntax.nesting-limit |  |
| SL-377 | A cast to an optional type is refused as 'cannot cast Int? to Int?': … | diagnostics.cast.optional-target |  |
| SL-378 | A placement write through a non-identifier pointer drops its by-value… | drop.placement-write |  |
| SL-380 | A flat 400-term binary chain (1 + 1 + ... + 1) is an ICE: maximum rec… | syntax.flat-chain | yes |
| SL-381 | A bounded extension's method is instantiated for a type argument that… | generic.conditional-conformance | yes |
| SL-382 | A generic struct built with an explicit nested type argument never dr… | drop.generic-field | yes |
| SL-383 | A match arm binding an enum payload whose type is an alias over a str… | match.payload-binding.alias | yes |
| SL-384 | Member access through a distinct alias over a struct is silently type… | alias.distinct.member-access | yes |
| SL-385 | In a driven body, a shared capture of a reference parameter ([&v], or… | coroutine.closure-capture.reference |  |
| SL-386 | Driven [&self] (or implicit self) capture in a closure that runs more… | coroutine.closure-capture.self |  |
| SL-388 | A non-escaping closure passed to a STATIC method is checked as escapi… | closure.escaping.static-method-arg |  |
| SL-389 | prototypes/minivm/tests/numeric_contract.saw hits an ICE on current s… | copy.field-glue | yes |
| SL-390 | A reference nested 13+ levels deep in a type escapes the no-reference… | reference.no-escape.nested-type |  |

### Close as `frozen`: Python-compiler tooling (5)

| ID | Title | Reason |
|---|---|---|
| SL-140 | DF-126b: Reconcile reproducible-build regression coverage after the f… | What remains is a set-iteration lint over sawc/ Python source (the queued test_set_iter.p… |
| SL-179 | Reconcile the remaining generic and cancellation differential sweeps | Differential sweeps over sawc's coroutine transform (abstract-T, positions, cancel/panic … |
| SL-237 | Deterministic guards for SL-230's perf behavior: option-mapping check… | Guards for SL-230's sawc perf behaviour (the TargetMachine opt level, namespace visit cou… |
| SL-241 | corodiff lane: driven-vs-sync deinit-trace differential — the sync tw… | Corodiff lane diffing driven-vs-sync deinit traces of the Python coroutine transform. Arc… |
| SL-277 | producer-taxonomy gate should enumerate codegen-declared Expression s… | Producer-taxonomy gate over sawc's typechecker and codegen Expression subclasses. It gate… |

### Close as superseded, with a pointer (24)

| ID | Title | Settled by |
|---|---|---|
| SL-2 | Design 274 (reconciling 259): the self-hosted parser track … | architecture §3.2 (Starting point) |
| SL-3 | Index the existing both-ways generic suspension conformance… | architecture §3.4 (r17): design 70's per-instantiation rule kept; the… |
| SL-16 | Maintain the native compiler readiness gate for v1.0 | architecture §4, §3.10 |
| SL-66 | DF-272b: Rule default type arguments for bare generic type … | architecture §3.0 (types are interned by structure) |
| SL-76 | DF-286b: Census and resolve the stage 3c instance-check res… | architecture §3.4 (generic bodies type-checked once), §3.8 |
| SL-117 | DF-146k — OPEN, needs a user decision (Aug 6). A borrows ac… | borrowing §3 (also §1, §9; §2.7 for forwarding) |
| SL-142 | Carry the ruled binary AST seam into the parser-port plan | architecture §4 (also §6, serialization format) |
| SL-149 | Decide the syntax for method calls on integer literals | LANGUAGE_SPEC, literals (design 161) |
| SL-163 | Generic-method type-arg inference. [36] | architecture §3.4 (Inference) |
| SL-172 | M2. Unit tests for lexer/parser/typechecker internals; fuzz… | architecture §5; testing §6 |
| SL-175 | Reconcile the safe async prototype with the landed enforcem… | architecture §3.9 |
| SL-178 | Plan the remaining enforcement architecture stages | architecture §1–2, §3.9 |
| SL-183 | Decide whether measured frame overlay savings justify imple… | architecture §3.9 (frame layout) |
| SL-193 | Design address-taking through a borrows accessor’s lent fie… | borrowing §9.1 (K12), §2.1 |
| SL-201 | Design separate-compilation interfaces carrying suspension … | architecture §3.12 (Module interface row), §3.4 |
| SL-209 | EPIC: ownership uniformity — every value transfer an explic… | architecture §2 (principle 1), §3.5, §3.9 |
| SL-214 | Ownership Unit E: mandatory pre-codegen transfer-decision v… | architecture §3.0 (boundary verifiers), §3.5, §3.9 |
| SL-242 | EPIC: minivm lexer milestone — the self-hosted subset compi… | architecture §3.1, §4 |
| SL-300 | EPIC: prototype indexed AST and standalone parser | architecture §3.2 |
| SL-335 | retire `#lend_var` in favour of per-mode accessor overloads… | borrowing §4, §9 |
| SL-342 | The generic statement-scoped borrow window: a keyword block… | borrowing §2.1, §2.2, §2.4 |
| SL-343 | with_ref/with_var_ref bodies and accessor lend windows acro… | borrowing §2.5, §9; architecture §3.5 |
| SL-344 | The exclusive-window derivation for borrowing structs: &var… | borrowing §3, §2.6; architecture §3.6 |
| SL-367 | EPIC: must-fix soundness, liveness and ICE findings from de… | architecture §1, §5 |

### Close as already done (12)

| ID | Title | Evidence |
|---|---|---|
| SL-14 | DF-226b: Reconcile the stale FuncPointer v1 gap pointer | both entries are already in done_aug18-aug25.md |
| SL-91 | Write and verify the thread-sharing cookbook | the thread-sharing spec section landed (645de0c6) |
| SL-107 | DF-180a (OPEN, filed Aug 8): a static and an instance metho… | the spec now lets a static and an instance method share a name |
| SL-158 | Enum-direct Printable (enum method dispatch is a general ga… | enums already conform to Printable (design 145) |
| SL-168 | DF-112b (pin deviation, design 112): the pinned ISA was rv3… | `--target-features` exists |
| SL-173 | Restore package encapsulation after public(package) landed | its narrowing landed Aug 20 |
| SL-186 | DF-138b: Complete CLAUDE.md’s documented compiler flag list | CLAUDE.md lists the flags |
| SL-202 | DF-300d: Make export registration idempotent during entry-m… | fixed in d9dabfd6 (sawc 0.11.1) |
| SL-263 | MORNING REVIEW MANIFEST — overnight run Sep 10-11 2026 (non… | stale overnight manifest; everything it lists merged |
| SL-282 | A nested closure literal naming a frame local is an ICE: th… | fixed by SL-213.p1 r3; pin on main |
| SL-314 | B1 (design 274, NEW Class-1): the Python parser accepts 'x … | fixed by SL-347.p1 (0839ed7d) |
| SL-329 | sawtracker's Thread.spawn test worker calls Command.output … | fixed on the sawtracker side (ST-37.p1) |

### Close as a duplicate (1)

| ID | Title | Of |
|---|---|---|
| SL-21 | DF-223b: Design suspending trait dispatch through existenti… | SL-322 |

### Keep open, label `frozen` (cited by an XFAIL pin) (10)

| ID | Title | Bucket |
|---|---|---|
| SL-26 | DF-248b: Preserve mutable-reference captures through nested handwritt… | FROZEN |
| SL-30 | DF-255a: Prevent double-free when escaping closures consume move capt… | LANGUAGE |
| SL-34 | DF-252a: Resolve named FuncPointer calls inside driven bodies | FROZEN |
| SL-38 | DF-257d: Discover shorthand closure parameters inside try operands | FROZEN |
| SL-41 | DF-259c: Recognize trailing closures inside try operands | FROZEN |
| SL-51 | DF-270e: Diagnose zero-argument primitive construction without an ICE | FROZEN |
| SL-80 | DF-302b: Prevent moved initializer parameters from being released twi… | FROZEN |
| SL-231 | A value-carrying inline catch cannot host a move of a frame local in … | FROZEN |
| SL-267 | A driven body's non-escaping closure capture duplicates twice where i… | FROZEN |
| SL-340 | USE-AFTER-FREE: Mutex(value: move v) frees a heap-owning payload at c… | FROZEN |

### Keep, label `language` (36)

| ID | Title | Aspect |
|---|---|---|
| SL-4 | DF-307b: Design one aggregate layout oracle for all const positions | const.sizeof-aggregate |
| SL-9 | DF-300b: Design type-carried alignment for byte buffers | layout.align.type-carried |
| SL-11 | Decide return inference for cooperative spawn brace syntax | concurrency.spawn-brace.return-infe… |
| SL-12 | Revisit package-scoped re-exports when an internal-prelude consumer n… | import.reexport.package-scoped |
| SL-17 | Scope the deferred trailing-brace call syntax design | syntax.trailing-brace |
| SL-39 | DF-259a: Rule allocation fallibility for Box<any Trait>.make | alloc.fallibility.erased-box |
| SL-48 | DF-270a: Rule consistent literal adoption for distinct aliases across… | literal.adoption.distinct-alias |
| SL-58 | DF-215i: Decide boolean guard syntax | guard.boolean |
| SL-69 | DF-276b: Design integer-to-float conversion and rounding rules | conversion.int-float |
| SL-72 | DF-283c: Rule typed unsigned operands in constant-expression evaluati… | const-eval.signedness |
| SL-81 | DF-306a: Design alignment for coroutine-frame-resident locals | align.frame-local |
| SL-82 | DF-178a — a /// doc comment cannot document an extern declaration. In… | doc-comment.extern |
| SL-83 | DF-172d, third sighting. A binary expression still cannot wrap across… | syntax.newline.binary-continuation |
| SL-95 | DF-215c — hand-written JSON pays \{ at every brace, since a bare { in… | literal.string.interpolation-brace |
| SL-97 | DF-153c — a fixed-width backed enum costs two casts at a word-wide se… | enum.raw-backing.projection |
| SL-110 | DF-181c (filed Aug 7): Channel.recv from a cooperative task wedges th… | effect.blocking-call |
| SL-121 | DF-155c — a String cannot be a static. Statics take compile-time cons… | static.string |
| SL-136 | DF-172a — FILED, and it is the brief's predicted one. Saw cannot name… | extern.data-symbol |
| SL-145 | Design the remaining language features needed by runtime shims | extern.c-interop |
| SL-154 | DF5. Keywords (extension etc.) can't be identifiers — fine, but an ev… | lexical.contextual-keywords |
| SL-157 | Debug trait (synthesized structural formatting) — own design. [56] | trait.debug-synthesis |
| SL-159 | Named tuple PATTERN form (x: a, y: b). [63] | pattern.named-tuple |
| SL-161 | Labeled-arg _ opt-out; labeled-only enforcement. [66] | call.labels |
| SL-162 | Integer range-cover exhaustiveness. [63] | match.exhaustiveness.integer-range |
| SL-165 | Slices (needs own design vs no-escape refs); \x byte escapes; where c… | syntax.misc |
| SL-169 | F5. Once/Lazy<T>, PerCpu<T>, UnsafeCell-equivalent story. | cell.interior-mutability |
| SL-171 | AllocatedBy<Slab> sugar. [19, 42] | allocator.sugar |
| SL-185 | Reconcile the deferred language and tooling research roadmap | roadmap.research |
| SL-187 | Design runtime-installable function hooks for freestanding code | static.function-pointer-init |
| SL-189 | Rule declared versus imported name precedence against the prelude | import.prelude-precedence |
| SL-190 | Design shareable visibility for extern C declarations | extern.visibility |
| SL-200 | Design catch-side match-on-concrete error sugar | error.catch-match-concrete |
| SL-203 | DF-308a: Reassess scalar literal syntax against labeled construction … | construction.labels |
| SL-322 | design: heap-allocated coroutine frames — existential dispatch (K37) … | coroutine.heap-frame |
| SL-379 | UnsafeMemory.read() returns an unretained bitwise alias of an owning … | unsafe.memory-view.copy-tier |
| SL-387 | Nested closure borrow of an outer closure's by-value capture silently… | closure.capture.nested-reference |

### Keep, label `runtime` (16)

| ID | Title |
|---|---|
| SL-35 | DF-256b: Use one thread-control-block layout for allocation and deallocation |
| SL-106 | DF-186c — OPEN (two language gaps, one C body). The Linux half of the one-word lock (__sa… |
| SL-108 | Verify Linux pidfd child waiting at runtime |
| SL-109 | DF-181b (P0-adjacent by reach, filed Aug 7): every std.file / std.directory seam is a nak… |
| SL-138 | Verify cross-poller one-shot wakeup consumption |
| SL-144 | Reconcile the remaining pure-Saw runtime extraction shims |
| SL-276 | __saw_rt_thread_spawn discards pthread_create's failure and returns an uninitialized hand… |
| SL-307 | Runtime sockets are not FD_CLOEXEC: spawned commands inherit the listener and open connec… |
| SL-313 | N11+N12 (design 259/274): stack exhaustion is a bare SIGSEGV at both levels — Saw recursi… |
| SL-354 | never-hide-errors gap: the reactor arm discards kevent's return (reactor.saw:105/118/142/… |
| SL-360 | Thread<T>/VoidThread.join free the control block with a hand-computed size (24 + sizeof<T… |
| SL-361 | rt/common/sleep.saw chunks usleep at exactly 1 s, which POSIX allows to fail with EINVAL;… |
| SL-366 | Signal self-pipe: stale-generation records can fill the pipe when many threads are paused… |
| SL-375 | Single-frame entry executor polls with no timeout after one wake-word read (__saw_exec_pa… |
| SL-376 | reactor.saw ignores kevent's return when arming the wake event at create and when trigger… |
| SL-392 | Runtime concurrency hazard candidates found reading std/taskgroup.saw (SL-357 final wave)… |

### Keep, label `std` (13)

| ID | Title |
|---|---|
| SL-37 | DF-257b: Rule fallible collection copying under the infallible Copy contract |
| SL-55 | Derive Map field serialization for CBOR and JSON |
| SL-57 | DF-215h: Design newline-free stdout output for streaming clients |
| SL-93 | DF-215e (OPEN, found while fixing DF-215a) — IoError.from_errno is a public std factory o… |
| SL-116 | DF-170b: Finish the checked-cast census in std.data |
| SL-119 | DF-155a — a child's stderr can be merged, but not captured or discarded. Command.merge_st… |
| SL-120 | DF-155b — std cannot report the core count. Python's irdet defaulted -j to min(10, cores … |
| SL-122 | DF-155f — verdicts do not stream out during a --all sweep. The tool spawns every task, th… |
| SL-160 | Reconcile the remaining Map snapshot and copy API requests |
| SL-164 | Weak<T> (Arc slot reserved). [16, 21] |
| SL-170 | F6. dtoa/Float printing under freestanding. [20] |
| SL-177 | Design 216: audit the remaining collection closure and sort constraints |
| SL-359 | Directory.current hides errors: returns Path? (a getcwd failure's cause is erased into No… |

### Keep: tooling the new compiler reuses (5)

| ID | Title |
|---|---|
| SL-10 | Give the 46 docverify error fragments real scaffolding and diagnostic checks |
| SL-27 | DF-248c: Detect XFAILs that fail for a different or worse reason |
| SL-60 | DF-242d: Replace conformance K90’s bounded spin with a deterministic gate |
| SL-272 | devtools/dogfood/programs/w1_chatroom.saw does not compile: design-234 Channel drift, and… |
| SL-374 | The suite lock is unowned: any holder's chained rmdir can release ANOTHER holder's lock (… |

### Keep: not about the compiler (15)

| ID | Title |
|---|---|
| SL-19 | Design out-of-tree Blade target plugins |
| SL-20 | Reconcile old SawOS M4 seeds against current downstream milestones |
| SL-90 | Audit documentation for misleading Rust-based descriptions |
| SL-92 | Complete the second documentation correctness scan |
| SL-135 | DF-172i — a COVERAGE NOTE, not a bug, recorded because it is easy to lose. The kernel's @… |
| SL-137 | DF-172c — the arm64 HAL keeps CPACR_EL1.FPEN, and the brief's line about dropping it is v… |
| SL-141 | Plan the deferred Saw documentation website |
| SL-152 | D10. Cortex-M0-class atomics (ARMv6-M has no CAS) — decide with the first such port. [19,… |
| SL-153 | DF4 (meta). Blade bit-rots as the compiler tightens — re-validate periodically (the boots… |
| SL-155 | B4 limit. A git dep's locked REV isn't pinned without re-resolution (build-from-lock path… |
| SL-167 | Registry for Blade (salvaged sketch, old pm design): static HTTP index or git repo; GET /… |
| SL-174 | Plan the ESP32-P4 and TCP/IP hardware path |
| SL-176 | Design deterministic Raft simulation |
| SL-181 | Plan LLM client stages D–F |
| SL-196 | Retire the dormant sosimg device-segment flag and manifest key |
