# Design 218c — unit 1.5: monomorphization becomes a pre-codegen transform (spec)

**Status: SPEC AUTHORED (Aug 25 2026); LEAD-RATIFIED same night under the
user's overnight authorization ("continue through 218/1.5, normal rules" —
Aug 24) — all six section-8 questions resolved AS RECOMMENDED, none touching
a user ruling: (1) COLLECT instance errors (architecture-independent, the
fallback recorded); (2) `--emit-ast`/`--ids`/astdiff see the PARSED
pre-monomorphization AST — applies the recorded 218 authored-form contract,
astdiff untouched, `--emit-mono-ast` future work; (3) the freestanding /
`--no-hidden-alloc` gates do NOT re-run per instance — design 135's
source-construct semantics, with the per-rule skip list defaulting future
tier-dependent rules to running; (4) DF-258a pins XFAIL at stage 0 and flips
at stage 4 — 1.5 is the next dispatch, so an interim refusal would be
built-then-deleted; the restore-the-refusal fallback stands IF the queue
slips; (5) DF-247a gets its own small dispatch after 1.5; (6) the
instantiation depth limit is 64 per chain — it refuses only what today
HANGS (DF-258b). Implementation dispatches after the 234 flip integrates.**
Charter: design 218 unit 1.5 (RULED Aug 13; SCHEDULED Aug 24, moved ahead of
the 238 split so the migration lands under the full in-tree battery). Process
per the 218 ruling and the 218a/218b precedent: this spec documents the exact
form; the lead reviews, the user rules on section 8, Opus implementers dispatch
against the staging in section 7.

Probes live in `.build/scratch/spec218c/` (gitignored), every one compiled and
run against this worktree's sawc with the main venv; outputs are quoted where
load-bearing. Anchors cite FILE + FUNCTION, with this tree's line numbers
(main @ ae442120) as a courtesy only — design 234 unit 3 is landing in
parallel and will churn std and the corpus, so a reader re-derives lines from
the function names, never the reverse.

**What changed since the charter was written (Aug 13), verified by probe:**
design 219 wave C landed the DF-217i fix the day after the ruling, so the
expected closures the queue line names are mostly ALREADY CLOSED at the
abstract layer — probe P2 (the S1 p08a launder shape, spawned at a NoCopy
type) is refused today at the spawn site with the wave-C diagnostic
(``error: `launder` requires `T` to be `Copy` — it binds `x` twice, at lines
13 and 14; `Res` is move-only``). What this unit still owes those findings is
the ARCHITECTURE: the instance re-check that today deletes its own errors
becomes real, so the "WHICH FORM THE GUARANTEE VALIDATES" caveat in the 218
brief discharges structurally instead of resting on 219's rule inventory
staying complete. And the probes found two NEW findings the current
architecture cannot express a fix for, filed here as DF-258a (a silent
cooperative-contract drop — section 6) and DF-258b (a compiler hang — section
1d). Both dissolve under this unit's pipeline.

## 0. The two sentences this migration is

Today, WHICH generic instantiations exist is decided in three places — the
effect pass (clone + substitute + re-check with errors DELETED, for
driven/spawned/effect-polymorphic instances the coro transform needs), the
coro transform (promotion walks that splice more), and codegen (lazy
`_ensure_monomorphized_*` during lowering, for everything else) — and no
judgment with real errors ever runs on any instance. After: ONE demand-driven
reachability fixpoint, running inside the typecheck phase after abstract
checking, computes the full instance set, re-checks each instance ONCE with
errors real, and splices the survivors into the AST as ordinary concrete
declarations; the place/coro transforms and codegen consume concrete ASTs
only, and codegen's `_ensure_*` entry points become LOOKUPS that ICE on a
miss — codegen lowers, it no longer decides.

## 1. The pipeline contract

### 1a. Phase order, and what each phase consumes/produces

Today's driver is `sawc.py _prepare_codegen`: check modules → check entry
(inside which `_process_effect_monos` + `finalize_effects` run) → place
lowering (+ re-entry) → coro transform (+ re-entry with `post_transform=True`,
which re-checks the whole entry AST) → codegen. The new order inserts ONE
phase and deletes the private machinery in two others:

| # | phase | consumes | produces |
|---|-------|----------|----------|
| 1 | parse + abstract typecheck (KEPT — the definition-site UX/inference layer) | source | checked ASTs; templates checked abstractly; design 219 requirements inferred + discharged at calls; effect templates harvested |
| 2 | **MONOMORPHIZE** (new phase, absorbing `_process_effect_monos`) | checked ASTs + the pristine template store | the INSTANCE REGISTRY (section 4) and, spliced into the ASTs, one checked concrete declaration per demanded instance; per-instance effect nodes (the existing design-70 re-inference, now with errors real) |
| 3 | effect finalize + the driven/spawn classification | concrete instances included | roots for the transform, exactly as today |
| 4 | place lowering | concrete ASTs | window calls (unchanged) |
| 5 | coro transform | CONCRETE ASTs ONLY | frames/drivers/helpers; the promotion + template-consumption machinery DELETED (census section 2c) |
| 6 | post-transform re-entry | transformed AST | full re-check as today — AND a re-run of phase 2's fixpoint, because the transform's synthesized code demands NEW instances (section 9b); the cache makes the re-run cheap |
| 7 | codegen | concrete ASTs + the registry | lowering only: `_ensure_monomorphized_*` become registry lookups; a demand the registry cannot answer is an ICE naming the miss (the decides-vs-lowers gate) |

The TYPE-LAYOUT half stays physically in codegen — an LLVM identified struct
type can only be built against an `ir.Module` — but its DECISION moves up: the
registry enumerates every (base, canonical args) pair, and codegen constructs
layouts for exactly that set. The canonicalization trio that today defines
instance identity inside codegen (`_fill_default_type_args`,
`_canonicalize_type_kind`, `_mark_stored_closure_escaping` — codegen/
generics.py) moves into ONE identity funnel the monomorphizer owns and codegen
calls, so the two sides cannot disagree about what an instance IS (the
DF-190c/design-194-unit-2 lesson, already learned once for
`specialization_key`).

### 1b. Where the fixpoint's roots come from

Roots are **every CONCRETE (non-generic) declaration in the compilation
unit**: entry + module + std free functions, extension methods (enum
extensions included), statics' initializers, and `@export`/`@section`
declarations. Spawn/drive sites need no special root treatment — they are
call positions inside those bodies. This deliberately over-approximates for a
hosted `-c` object (which keeps every symbol — `whole_program=False`), and
matches it exactly; for executables the design-168 reachability strip still
decides which BODIES are emitted, unchanged — instance EXISTENCE (checked,
registered, declared) and body EMISSION (design 168's demand) stay two
different questions, and this unit moves only the first.

The walk: from each root body, every expression that names a generic with
resolved type arguments records a DEMAND — the typechecker has already stamped
`expr.type_args` on every call shape (inference included, via
`_fold_method_type_args` and `_resolve_overload`), and annotations/field
types/signature types name type instantiations directly. Each demand
substitutes through the demanding context's own binding (the census's per-row
"substitute against the active context first" discipline, now done once at
demand-record time), canonicalizes, and enters the registry; a fresh
instance's checked body is then itself walked, to a fixpoint. The type-closure
half: an instantiated struct/enum's substituted FIELD types are demands
(subsuming DF-256a's template-reach-through fix), and a type instance demands
its extension-method instances per the design-168 rule (signatures exist,
bodies deferred).

### 1c. What "instances re-enter the checker" means — the rule inventory

The instance check is `_check_function`/`_check_method` over the substituted
clone, in the TEMPLATE's home module scope (design 210 unit 4, already built),
with the reporter LIVE. Enumerated, because "full re-entry" has documented
exceptions:

**Run REAL on every instance** (today suppressed or never run):
- name/member resolution and full type checking of the substituted body;
- the transfer/move checkpoint, exclusivity, place rules, payload-read policy
  — the ownership family;
- effect inference per instance (design 70 — already real, keeps its node);
- Send/Sync at spawn forms, bounds discharge of nested calls, design 146's
  place-read bound, the design-219 requirement discharge for calls the
  instance body makes;
- the two design-219 per-instance derivations (NoMove containment, unsafe
  signature) — already landed, unchanged;
- the design-130 unsafe trigger rule over the substituted signature/body.

**Skipped on instances, as PROVENANCE rules** (the design-218-stage-4 pattern:
a rule about what an author WROTE does not apply to code that arrived by
substitution — each skip is named and per-rule, never a blanket bool):
- shadowing/redefinition (surface-form rules; the template was judged);
- the design-194 written-annotation prelude/import gate and design-82
  visibility-of-written-names (substituted types were not written; the
  template's written names were already gated — and the instance is checked in
  the home module scope where they resolve);
- design 135 hidden-alloc and the design-150 warning categories (authored-form
  rules; E1/E4's existing rationale);
- the design-132 rule that a Void you can SEE errors: an instance-arrived
  `Void` binding stays legal — this is the ONE rule for which the
  `is_mono_instance` provenance mark is load-bearing and KEPT;
- design 151's Result-discard on a discard that becomes a Result only by
  substitution (same family as the Void rule: the authored form had abstract
  `R`, and refusing `f(x)` statement-position at `R = Result<...>` would make
  a legal generic body illegal at one instantiation with no spelling
  available in the template). NOTE: this is a rule-by-rule judgment the
  implementer applies from THIS list; new checker rules default to RUN.
- **skip 3 — a `.copy()` the SILENT tier answers** (`_mono_copy_is_a_retain`,
  typechecker/core.py; read at the `.copy()` receiver test in
  expressions.py). The receiver test asks for a `copy` METHOD or a trivially
  copyable type, and the refcounted half of the Copy tier (`String`, an
  escaping closure) is neither — its copy is a retain codegen emits with
  nothing to look up. In an AUTHORED body the refusal is right (`s.copy()` on
  a local `String` is a real error today). In a substituted clone the spelling
  is not the author's choice at this type: the template wrote
  `buf[i].copy()` under a declared `<T: ExplicitCopy>` bound — design 219's
  licence for the spelling — and every Copy type satisfies that bound, so the
  call site discharged it and codegen lowers the element copy BY TIER. That is
  why `Vector<String>.copy()` compiles and runs today and the re-check is the
  only thing that disagrees.
- **skip 4 — a transfer of a by-value parameter whose type arrived by
  SUBSTITUTION** (`_transfer_is_substituted_param`, typechecker/core.py; read
  at `_check_value_transfer` in types.py, ahead of the tier chain). In the
  template that parameter's type is a type PARAMETER, so the checkpoint takes
  design 219 wave C's `'abstract'` arm: it RAISES A REQUIREMENT that every
  call site discharges against its concrete argument, per PATH — so a body
  that forwards its parameter once (`buf[i] = value`,
  `self.swap_out(i, value)`) duplicates nothing and requires nothing. The
  concrete tier test on the clone is a SECOND, coarser judgment of the same
  transfer. Its input is computed at the clone by the one funnel
  `monomorphize.substituted_param_names`, whose entry points its docstring
  names; it fires only for an `Identifier` naming such a parameter, so a
  local, a field read, a place read and a concretely-typed parameter are all
  re-judged unchanged.

Skips 3 and 4 are the A3 OUTCOME's triage, lead-signed at the stage-3c
dispatch; the residue counts and the evidence are in that section. The third
family the sign-off named — the `__window` argument-type pair on
`Map.copy`/`try_copy` — needed no rule: it is a CASCADE of skip 3 (the window
closure's result type is inferred from a body whose `.copy()` had just failed,
so it came out `Void`), and it disappeared when skip 3 landed.

The `check_module` skip of `is_mono_instance` functions (typechecker/core.py,
the "re-checking it HERE would report those suppressed errors as the author's"
comment) survives in its scheduling role — instances are checked once, by the
mono phase, not re-checked per pass — but its SUPPRESSION rationale retires:
there are no suppressed errors left to protect the author from.

### 1d. Termination — the depth story

The fixpoint terminates iff the demand graph reaches finitely many instances.
A template that demands itself at a GROWN argument makes it infinite, and the
current compiler HANGS on that shape — probe P4
(`.build/scratch/spec218c/p4_recursive.saw`):

```saw
func deepen<T>(x: T, n: Int) -> Int {
    if n <= 0 { return 0 }
    deepen(Wrap<T>(inner: x), n - 1)
}
```

did not produce a diagnostic within 120 s and was killed — codegen's
`_instantiate_generic_function` recurses through `_generate_function_call`
building `deepen$1$Wrap$1$...` forever. **Filed as DF-258b** (pre-existing;
fuzz-oracle class — a hang; no corpus pin is legal for a hang, so the refusal
test ships WITH the fix). The new fixpoint carries an **instantiation-depth
limit** from its first commit: each demand records `depth = demander's depth
+ 1` (roots at 0), and a demand past the limit is a clean error at the
DEMANDING call site naming the chain (`instantiation of `deepen<Wrap<Wrap<…>>>`
exceeds the depth limit (64): deepen<Int> → deepen<Wrap<Int>> → …`, elided in
the middle). Recommended limit 64 — deep enough that no legitimate corpus
chain approaches it (the corpus's deepest today is single digits), shallow
enough to answer fast. The limit is per-CHAIN, not a global instance cap, so
wide-but-shallow programs are untouched.

### 1e. What the guarantee becomes

With phases 2 and 6 in place, the 218 brief's "WHICH FORM THE GUARANTEE
VALIDATES" caveat discharges: transformed output is judged at the form the
checker actually judges — concrete — because no abstract body survives into
the transform, and the one re-check that used to stamp types while deleting
its own errors no longer exists. S1 row p08a's vacuous-validation mechanism
has no carrier left.

## 2. The census

### 2a. Codegen sites that DECIDE an instantiation today

Every `_ensure_monomorphized_*` / `_instantiate_generic_function` call site,
one row each. "Registry lookup" means: canonicalize via the shared identity
funnel, look up; found → proceed exactly as today; missing → ICE naming the
(base, args) pair and the demanding function ("instance not discovered by the
monomorphization fixpoint"), which is the standing decides-vs-lowers gate.

| # | site (file, function) | today | where the demand moves |
|---|----------------------|-------|------------------------|
| G1 | calls.py `_generate_function_call` (~795) | `_instantiate_generic_function` on a bare generic call | the call walk of the enclosing body (roots or a checked instance); codegen resolves the pre-spliced concrete function by mangled name — the instantiate call DELETES |
| G2 | calls.py `_generate_module_function_call` (~2809) | same, qualified spelling (DF-238a) | same row as G1 — one demand kind, two spellings |
| G3 | generics.py `_instantiate_generic_function` (47) | the body generator (state save/restore, DF-251a's family) | DELETES — instances are ordinary concrete functions emitted by `_generate_function` |
| S1 | structs.py `_generate_struct_init` (46, 54) | struct init with type args / zero-arg defaulted | the annotation/constructor walk; lookup |
| S2 | types.py `_get_llvm_type` STRUCT arm (~271/273) + zero-arg default (~286/289) | nested generic in any type position | the type-closure walk (1b); lookup |
| S3 | types.py `_get_llvm_type` ENUM arm (~319) | generic enum type | same; lookup |
| S4 | core.py `_const_from_expr` (~1407) | a static's struct-literal initializer | statics are roots (1b); lookup |
| S5 | core.py `_register_types_in_order` (~2294; DF-256a's template reach-through) | registration-order graph + build-on-register | the registration SET comes from the registry (which already closed over field types, subsuming DF-256a's fix); the topological sort and LLVM construction stay |
| S6 | calls.py `_generate_enum_from_raw` (~1515, DF-232i) | instantiation recovered from the result type | result types are walked; lookup |
| S7 | calls.py `_generate_enum_init` (~3125) | generic enum construction | constructor walk; lookup |
| S8 | calls.py thread-handle construction (~2435, `Thread<T>`/`Task<T>`) | spawn lowering demands the handle struct | the spawn form's checked type demands it in phase 2; the transform-synthesized helpers re-demand in phase 6 (section 9b); lookup |
| S9 | calls.py `_generate_arc_forward_call` (~2535) / `_generate_box_forward_call` (~2606) | wrapper payload struct | the receiver's checked type; lookup |
| S10 | calls.py `_generate_static_method_call` (~2692) | receiver struct for a generic-struct static | the call's stamped receiver; lookup |
| M1 | calls.py `_generate_method_call` (~1947) | `_ensure_monomorphized_generic_method` at an instance method-generic call | the call walk (stamped `expr.type_args` from `_fold_method_type_args`); the method instance is a checked concrete method AST; codegen resolves by composed symbol |
| M2 | calls.py `_forward_target_symbol` (~2586) | same through an Arc/Box forward | same row as M1 |
| M3 | calls.py `_generate_static_method_call` (~2713, the DF-216c/217d landing) | same at a generic static | same row as M1 — the DF-216c fix's demand moves up wholesale; its typechecker half (`_fold_method_type_args`) is UNCHANGED and is what stamps the demand |
| M4 | generics.py `_ensure_monomorphized_generic_method` (763) incl. the `plain_generic_methods` C6 path and the `mono_struct_args` receiver-recovery | locate template, build binding, declare + queue body | DELETES as a decider; its declaration/symbol-composition half survives as the registry-driven declaration path |
| M5 | generics.py `_monomorphize_extension` (496) / `_monomorphize_single_extension` (566) + `_extension_bounds_satisfied` (532) | struct-time extension-method instantiation, conditional-conformance filtering, specialized-extension override via `specialization_key` | the registry's type-closure carries the same method set per type instance, decided in phase 2 with the SAME three rules (bounds filter, specialization override, method-generic skip); codegen keeps declare-eager/body-deferred (design 168) over that set |
| M6 | generics.py `_generate_method_generic` (879) / `_generate_init_method_generic` (1012) + `pending_method_bodies` / `_generate_pending_method_bodies` (865) | the parallel generic body generators with hand-maintained state isolation — DF-251a's mechanism, DF-251b's three open faces | DELETE — instance methods are concrete method ASTs emitted by the ordinary `_generate_extension_methods`/`_generate_init_method` path, which already registers param cleanups (design 240 item 9), populates `variable_types` and sets the `_current_decl` breadcrumb. **DF-251b closes structurally here** |

Not census rows, and why: `mangle_function`/`mangle_named`/`mangle_method`
(codegen/mangle.py) survive unchanged — the mono phase mints the same symbols
(it already does, via the same imports effects.py uses today);
`specialization_key`/`ext_param_aliases` (ast_nodes.py) survive as shared
identity helpers; the design-168 reachability strip (codegen/reachability.py)
survives untouched (body-emission demand, a different question); the vtable
queue `_pending_vtables` survives (it consumes registered instances; the
erasure sites that demand them are ordinary walked expressions).

### 2b. The typechecker's private mono machinery — absorbed, with errors real

| # | site (typechecker/, function) | today | disposition |
|---|------------------------------|-------|-------------|
| T1 | core.py `check_module` pristine capture (~3692-3724): `_pristine_generics`, `_pristine_generic_methods`, `_pristine_generic_struct_methods` | per-module pre-body-check deep copies | SURVIVES as the mono phase's template store (same capture point; spans every module — design 104 item 2) |
| T2 | effects.py `_effect_queue_fn_mono` (540) ← expressions.py driven call (~4170) and spawn (~9111) | eager queue for driven/spawn instances | becomes an ordinary DEMAND — the fixpoint serves every call site alike, so the driven/spawn special path stops being special |
| T3 | effects.py `_effect_queue_method_mono` (553) ← expressions.py (~2031) | method-generic drive path | same |
| T4 | effects.py `_effect_queue_generic_struct_method_mono` (568) ← expressions.py (~2102) + coro_transform (~9771) | generic-struct-method drive path | same; the coro-transform caller deletes with 2c |
| T5 | effects.py `_effect_record_poly_call` (641) ← expressions.py (~3534, ~4661, ~10447, ~10608) | deferred effect edges, materialized only for poly templates | ABSORBED: every demanded instance gets its own effect node unconditionally (built by the instance check), so the poly-candidate deferral and its four recorder sites delete; the fixpoint IS the materialization |
| T6 | effects.py `_process_effect_monos` (653) | the three-queue fixpoint + poly-edge materialization | REPLACED by the one monomorphization fixpoint (phase 2) |
| T7 | effects.py `_build_fn_mono` (707) — **`del self.reporter.errors[saved:]` at ~749-750** | clone/substitute/re-check, errors deleted, splice-or-effect-only | becomes the fixpoint's instance builder, ERRORS REAL, attribution per section 3; the `splice=False` effect-only mode deletes with T5 (every instance splices) |
| T8 | effects.py `_splice_fn_mono` (753) — **del at ~802** | the transform-time splice (design 74 shape 3) | DELETES — nothing splices at transform time; phase 2 spliced already. Its home-module-scope discipline (the DF-206e lesson in its docstring) carries into T7's builder |
| T9 | effects.py `_build_method_mono` (808) — **del at ~835-836** | method-generic clone onto the extension | absorbed into T7's builder (method flavor), errors real |
| T10 | effects.py `_build_generic_struct_method_mono` (590) — **del at ~629-630**, plus the double `substitute_ast_types` re-stamp | generic-struct-method clone into `_driven_generic_struct_methods` | absorbed; the clone becomes a registry-owned concrete method (see 2c C3 for how the transform finds it); the second substitution pass survives as the builder's post-check re-stamp (it exists because `_resolve_type` leaves `self`-field reads abstract — a mechanism note the implementer keeps) |
| T11 | core.py `check_module` `is_mono_instance` skip (~3727-3739) | protects the author from suppressed clone errors | KEPT as scheduling (check once, in phase 2), suppression rationale retired; the provenance mark stays for the two rules in 1c that need it |

**The error-deletion sites are the heart of this unit: exactly four `del
self.reporter.errors[...]` sites exist in effects.py (T7-T10), and the landing
that finishes stage 2 deletes all four.** A grep gate rides the staging
(section 7): `grep -n "del self.reporter.errors" sawc/typechecker/` must
report zero after stage 2.

### 2c. The coro transform's generic-instance machinery — deleted

| # | site (coro_transform.py, function) | today | replacement |
|---|-----------------------------------|-------|-------------|
| C1 | `_promote_nested_generic_calls` (9510) | walks driven bodies, splices suspending free-fn instantiations, rewrites call sites to mangled names | DELETES — phase 2 already spliced every instance and rewrote nothing (call sites keep `type_args`; the transform's classifier reads the same stamped `type_args` + the instance's OWN effect node, so a nested suspending instantiation is an ordinary concrete suspending callee). The call-site rewrite (name → mangled, `type_args → None`) moves into phase 2's splice so every consumer sees one spelling |
| C2 | `_promote_nested_generic_methods` (9694) | the method twin (design 223 unit 1): builds instantiations for embedded suspending method calls, stamps `coro_frame_key` | DELETES — the frame key is stamped from the registry's concrete method instance at classification time; no build happens inside the transform |
| C3 | the `gsm` table consumption (`_driven_generic_struct_methods`, ~10468-10498) | drive-root generic-struct methods pulled from the typechecker's private table | the table becomes a registry view: same data (concrete receiver SawType + checked clone), owned by phase 2, read-only in the transform. The `raise CoroTransformError("was not monomorphized")` arm becomes unreachable and deletes |
| C4 | `_consume_templates_naming_removed` (9427) — DF-218e's consumption symmetry, with the `_names_the_survivors_call` live-guard | consumes generic templates whose bodies name a consumed callee | DELETES — templates are not part of the concrete program the transform sees (they live only in the mono phase's store), so no template can dangle a reference to a consumed callee. `examples/coro_generic_spawn_root_nested_suspending_call.saw` must stay green through the deletion (regression, not a flip) |
| C5 | the effect re-inference + error-deleting re-check the 218 charter names | lives in T7-T10, reached FROM the transform via C1-C3 | gone with them |

What the transform KEEPS: everything non-generic — the frame builders, the
scope-end machinery (218b), spawn helpers, `_strip_driven_method`/design 223's
conformance-aware strip, and the spawn-root consumption at ~10416/10443
(which is DF-247a's mechanism and is NOT this unit's — section 6c).

## 3. Error attribution

**The abstract-first principle, restated as the contract:** an error
expressible abstractly fires abstractly, at the definition or the call, with
no instance involved — design 219's requirement inference, the design-239b
declaration-time resolution ruling, and the bound-discharge funnels are the
standing direction ("migrate rules into abstract bound vocabulary over time so
the instance check rarely fires" — the ruling's words; DF-239b's landing is
the worked example: the abstract error at the generic's own line stays the
better error post-1.5). The instance check is the NET. On this corpus it is
expected to report zero new errors at stage 2 (section 7's gate makes that a
measured claim, not a hope) — every diagnostic it produces after that is
either a genuine soundness catch or a rule that should migrate up, and either
way it is a finding.

**The format.** An instance error renders as the ordinary body diagnostic —
the clone keeps the template's source spans (`substitute_ast_types` preserves
line/column), so the error anchors at the author's own line in the template —
plus one attached note naming the instantiation and the demand path:

```
error: <the ordinary diagnostic, anchored in the template's body>
  --> lib.saw:12:9
note: in the instantiation `launder<Res>`, required from main.saw:21:25
```

The demand site is the FIRST edge the fixpoint recorded for that instance
(deterministic: the walk order is declaration order over roots, so "first" is
stable across runs — an irdet obligation, stated here so the implementer
builds it in). For an instance demanded through a CHAIN of instances, the note
names the full chain to the nearest root, elided in the middle past 4 hops
(the depth-limit rendering, reused).

**The dedupe rule.** One bad instance = one report, however many demand paths
reach it (the registry's built-once discipline gives this for free: the
instance is checked at first demand, and later demands hit the cache).
Multiple bad instances of one template each report — they are different
programs — subject to section 8 Q1's ruling on collection vs fail-fast.

## 4. The cache

**Key**: the canonical instance identity = (template identity, canonical
type-argument tuple), where template identity is the design-144 (module, name)
pair plus the design-105 `$OL$` overload tag, and the argument tuple is
canonicalized by the shared identity funnel (defaults filled — design 37;
enum-kind re-tagged — design 61 L14; erased box normalized to arity-1;
stored-closure escaping bit restored — design 77; const VALUES included —
design 148, exactly as `specialization_key` and the manglers already encode
them). In practice the key IS the mangled symbol, which is why the manglers
move up unchanged: one identity, one spelling, both sides.

**What is cached**: the registry entry — the checked, substituted instance
AST (the clone phase 2 spliced), its effect node key, its verdict (clean /
the error list it produced), the concrete receiver SawType for method
instances (what `_driven_generic_struct_methods` carries today), and the
first-demand edge for attribution. Caching the AST rather than a verdict-only
record is required anyway: the transform and codegen consume the body.

**Invalidation: none, argued.** A compile is single-shot: templates are
captured pristine before any body check mutates annotations
(`check_module`'s capture point), nothing edits a template after capture, and
the language has no compile-time evaluation that could make one instantiation
observe another's side effects. The one in-process wrinkle is the
post-transform RE-RUN (phase 6): the transform synthesizes new demanders but
never re-defines a template, so every cache hit stays valid and the re-run
only ADDS entries. `--emit-docs` and the design-220 artifact reuse operate on
whole compiles and are untouched.

**Memory shape.** Today the driven/spawned/poly subset of instances already
exists as deep-copied clones; this unit extends clone-existence to ALL
demanded instances (the ones codegen used to build directly from the template
under `type_param_context`). The delta is one substituted function/method AST
per instance that was previously codegen-only. The corpus's instance counts
are modest (std's containers dominate; the design-168 measurement found the
IR bloat problem was bodies-per-instantiation, not instantiation count) —
but this is an assertion to MEASURE, not to trust: section 5's instrument
covers peak RSS alongside wall time.

## 5. Perf

**Instrument**: the suite's own wall time — `test_runner.py` full suite on an
uncontended machine (3-run median), compared before/after on the same
machine, plus the battery's `bench` lane timing report (report-only, but
recorded in the landing note) and `bootstrap` (the biggest real compile).
Peak RSS via `/usr/bin/time -l` on three representative compiles: a
four-line hello, a generic-heavy example, and blade's stage1. The spec run
happens at stage boundaries (section 7), not per commit.

**Envelope (acceptance)**: full-suite wall time and bootstrap wall time
within +10% of the same-machine baseline; peak RSS within +25% on the three
probes. These are the "measure before optimizing" tripwires, not promises —
exceeding one PAUSES the staging for the lead, it does not license
speculative optimization inside the migration.

**If exceeded, in order:**
1. Verify the re-check is not being run twice per instance (the phase-6
   re-run must be cache-hits except for genuinely new demands).
2. The residue fast path: an instance whose template's abstract judgment left
   NO instance-dependent residue (no tier-dependent reads design 219 didn't
   already discharge at the call, no spawn forms, no unsafe-signature
   contact, no NoMove-relevant containment) can register + substitute
   WITHOUT re-running the body rules — the abstract check already proved it
   for every instantiation. This is an optimization precisely because the
   abstract-first principle keeps growing; it must be gated by a per-rule
   list, not a heuristic.
3. The ruling's tier-shape sharing, sketched: key the OWNERSHIP half of the
   instance judgment not on the type tuple but on its judgment-relevant
   projection — per argument: (copy tier, Send/Sync bits, unsafe-type
   contact, NoMove bit). Two instantiations with equal projections get one
   ownership verdict (`Vector<Int>` and `Vector<Bool>` are one row). Layout
   and codegen stay per-instance; only the re-check dedupes. NOT built in
   this unit; sketched so the cache's key module leaves room for a second,
   coarser key.

## 6. The flip list, pre-registered

The 219 landing already flipped the pins the charter expected this unit to
flip, so this unit's list is smaller and different in kind: one new
soundness-adjacent pin, one structural closure with a new pin, two probed
dispositions, and a REGRESSION SET that must survive the deletions.

### 6a. Pins that flip

| pin | DF | flips at | impossibility argument |
|-----|----|----------|------------------------|
| `examples/coro_nested_generic_call_parks.saw` (NEW — lands XFAIL with stage 0) | **DF-258a** (new, filed by this spec's probe P3/P3b): a nested call to an unconditionally-suspending generic that calls no type-parameter method compiles its instantiation as a PLAIN function — `slowly$1$Int` is `ret i64 %x`, the `yield_now()` erased — so the cooperative contract is silently dropped. Probe P3b: task A's three iterations all print before task B's first (`A 0, A 1, A 2, B 0…`); the direct-yield control twin P3c interleaves (`A 0, B 0, A 1…`). The documented behavior ("suspending calls embed at any nesting depth … or error cleanly — never silently block") promises a refusal at worst; 218b's landing note (c) records the promotion DECLINE that produces it | stage 4 | phase 2 splices `slowly$1$Int` as a concrete function whose own effect node says it suspends, so the transform's classifier sees an ordinary concrete suspending callee and embeds a sub-frame; the path "codegen instantiates a suspending body late, outside the transform" is unrepresentable because codegen can no longer instantiate ANYTHING (registry lookups only, ICE on a miss) |
| `examples/init_generic_param_released.saw` (NEW — lands XFAIL with stage 0) | **DF-251b**: a generic extension's `init` registers no param cleanups (an un-moved owning param leaks), populates no `variable_types`, sets no ICE breadcrumb — three faces of `_generate_init_method_generic` lacking what the non-generic twin has | stage 3 | the generator is DELETED (census M6); a generic init instance is a concrete method AST emitted through `_generate_init_method`, which has carried the param scope since design 240 item 9 — there is no second body path left to lack it |

### 6b. Findings this unit closes with no pin flip (architectural discharges)

- **DF-217i/j/k, S1 row p08a, DF-217q, C07** — closed by design 219 wave C at
  the abstract layer (probed: P2 refuses). This unit discharges their
  ARCHITECTURAL residue — the 218 brief's caveat that generic driven
  functions remain the soft spot while the post-transform re-check sees
  abstract `T`. Discharge is structural: after stage 4 no abstract body
  reaches the transform. Evidence of discharge = the stage-2 grep gate (zero
  error-deletion sites) + the regression set below staying green.
- **DF-258b** (new, filed by probe P4): unbounded recursive instantiation is
  a compiler HANG (>120 s, killed), no diagnostic. Closed by the depth limit
  (1d) at stage 1; the refusal test
  (`examples/errors/generic_instantiation_depth_limit.saw`) ships with the
  fix — a hang cannot sit in the corpus as an XFAIL.

### 6c. Probed dispositions (the charter's questions answered)

- **DF-247a — NOT dissolved.** Probe P1 reproduces on this tree (``undefined
  function `work` `` at the ordinary call). The mechanism is the transform's
  spawn-root consumption (`removed.add(root_name)` at the spawn-helper
  synthesis, coro_transform.py ~10416/10443) — no generics involved; the
  probe's `work` is concrete. This unit deletes the TEMPLATE-consumption
  machinery (C4) but not root consumption, so DF-247a stays open with its
  own root matrix owed. Recommendation (section 8 Q5): its own dispatch,
  after this unit — the fix wants `_names_the_survivors_call`-style
  liveness at the root-removal site, which survives this unit untouched.
- **DF-252a — NOT affected.** The mechanism is `_frame_field_encoding`
  classifying by TYPE KIND (`FuncPointer<F>` is a plain one-word struct, so
  no `opt_closure` call rewrite fires). Instance machinery is not involved —
  the failing cells reproduce with a fully concrete `FuncPointer` local. It
  stays with the DF-226b/c batch as filed.
- **The Aug-25 tree already compiles the shape the skill calls "still a
  clean error"** (the nested unconditionally-suspending generic) — but
  wrongly, which is DF-258a above. The docs sentence retires at stage 4
  (LANGUAGE_SPEC + the saw-lang skill both carry it).

### 6d. The regression set (must survive every stage; unpromised flips are review findings)

`generic_body_honors_copy_tier.saw`, `generic_container_nomove_cascade.saw`,
`generic_instantiation_unsafe_signature.saw`, conformance V36-V47 / K30 / K31
/ U30 (design 219), K22 (home-module scope of a cross-module instance), K34 /
K35 (design 223's embedded-position instantiations — their machinery is
REPLACED by the registry, so these two are the sharpest deletion tests),
`coro_generic_spawn_root_nested_suspending_call.saw` (DF-218e — C4's
deletion), `generic_static_type_arg_inference.saw` +
`generic_method_default_type_and_value_param.saw` (DF-216c/217d — M3's
demand moves up), `examples/std_gated_name_redefined_by_user.saw` (the
218-unit-1 name-reservation family — instance splicing must not re-open it),
and the corodiff generic contexts (stage 0).

## 7. Staging

Ordered commits, one implementer (every stage touches the same fixpoint).
Per-commit gate (the Aug-21 amended policy): full compiler suite +
`tools/freestanding_runner.py` both arches + `corodiff --quick` + the
`citations` lane. Stage-boundary gates as annotated; terminal = the FULL
battery. Both pipelines COEXIST from stage 1 to stage 4 — the coexistence
mechanism is the SHADOW REGISTRY (stage 1) and the rule that codegen's
lazy path survives, assertion-wrapped, until stage 4's cutover, so every
intermediate commit ships a working compiler whose new phase is checked
against the old one on the whole corpus.

| stage | content | flips / retires | gate specifics |
|-------|---------|-----------------|----------------|
| **0 — the net** | corodiff gains the GENERIC-DRIVEN-FUNCTION axis (the 218 brief's carried requirement: the S1 p08c parity shape + a NoCopy-instantiated generic coroutine with deinit witnesses + the DF-258a nested-generic-yield interleaving shape); the two new pins land XFAIL (6a); the DF-258a and DF-258b tracker entries land | — | `corodiff --all` once to baseline the new axis; suite |
| **1 — the fixpoint, shadow mode** | the monomorphize phase: demand walk, identity funnel (canonicalization trio lifted), registry + cache, depth limit (DF-258b's diagnostic), template store handoff (T1). Instances are BUILT AND CHECKED (errors still suppressed — one thing per stage) but NOT yet spliced beyond what T2-T4 splice today; codegen unchanged, plus a shadow assertion: every codegen `_ensure_*` demand must be present in the registry, logged (env `SAWC_MONO_SHADOW=strict` promotes to ICE for the gate runs) | DF-258b's refusal test lands passing | full suite under `SAWC_MONO_SHADOW=strict` (the registry-completeness proof over the whole corpus); freestanding both arches same way; `irdet` sample (the walk must be deterministic) |
| **2 — errors real** | T7-T10's builders report through the live reporter with section-3 attribution; the four `del self.reporter.errors` sites DELETE; the 1c provenance-skip list lands as named per-rule skips; T11's comment rewritten | — | full suite MUST be zero-delta (any new diagnostic is a triaged finding — either a real catch, kept and pinned, or a rule moved to the skip list with the lead's sign-off); the grep gate (zero deletion sites) joins the battery's `citations` lane or a one-line check in `forgetgate`'s style |
| **3 — splice-all + codegen cutover** | phase 2 splices every demanded instance as concrete declarations (call sites rewritten to mangled names at the splice); codegen G1/G2/M1-M4 become symbol lookups; G3 + M6 (the generic body generators) DELETE; S-rows become registry-driven with ICE-on-miss; the codegen template stores (`generic_functions`, `generated_instantiations`, `pending_method_bodies`'s call-site half) retire | **flips `init_generic_param_released.saw` (DF-251b)** | full suite + freestanding; `reemit` + `irdet --all` at the stage boundary (emission ORDER changes here — declaration order of spliced instances must be deterministic and documented in the landing note); gmgate both lanes (body-generator deletion changes cleanup paths) |
| **4 — the transform goes concrete** | C1-C4 DELETE (promotions, consumption symmetry, the gsm private table becomes a registry view); the phase-6 re-run of the fixpoint lands (section 9b); the docs sentence retires (LANGUAGE_SPEC + saw-lang skill) | **flips `coro_nested_generic_call_parks.saw` (DF-258a)**; retires any corodiff generic-axis ledger rows the stage-0 baseline recorded for the DF-258a shape | `corodiff --all`; full suite + freestanding; the C4 regression pin green |
| **5 — the old shell** | `_process_effect_monos`'s remaining shell, T5's poly-candidate machinery and the shadow-mode scaffolding DELETE; unit-4-ledger entry ("what codegen is allowed to know about generics: nothing but the registry") authored | — | terminal FULL battery (compiler branch: every lane incl. reemit / irdet-all / gmgate / bootstrap / sos) |

Consumer sweep (obligation 2 — this migration flips WHERE instances are
decided, a behavioral contract for everything reading instantiation timing or
order): **irdet/reemit** — emission order of monomorphized bodies changes at
stage 3 from lazy-discovery order to registry order; determinism, not
stability, is the gate, and both lanes run at that boundary. **`--emit-docs`**
— stops before the transform and documents the AUTHORED surface; phase 2 runs
before it under `object_only` finalize, so the docs emitter must keep reading
templates, not instances (one assertion in the docs path; no behavior
change). **`--emit-frame-layout` / `--emit-bt-table`** — read transform
output; unchanged shapes, but the frame keys for generic-struct methods now
come from the registry — byte-compare on the design-104 examples at stage 4.
**blade/bootstrap** — no API change; the bootstrap lane is the perf probe.
**sawfuzz** — the ICE-on-miss is a new internal-error surface; the fuzz
oracle already treats any ICE as a finding, which is the desired polarity.
**The design-192 ICE breadcrumbs** — the instance builder sets
`_current_decl` to the instance (template name + args), so an ICE inside an
instance body names it; this replaces the third face of DF-251b.

## 8. Open questions for the user

1. **Instance-error UX: collect or fail-fast?** Recommendation: COLLECT — one
   diagnostic per (instance, error) with first-demand attribution (section
   3), all bad instances of all templates in one compile, no cap. Rationale:
   abstract-first makes these rare, and a fail-fast would hide a second
   template's genuine error behind the first's. Fail-fast-per-template is the
   fallback if collection produces walls of text in practice; nothing in the
   architecture depends on the choice.
2. **The authored-form contract: what do `--emit-ast` / `--ids` / astdiff
   see?** Recommendation: the PARSED, PRE-monomorphization AST, exactly as
   today — `tools/dump_ast.py` deliberately shows the authored form (the
   218/DF-218a note), astdiff pins the dumper's completeness over source, and
   a future Saw parser must reproduce the authored form, not the elaborated
   one. The checked-monomorphized-transformed AST is a SEPARATE artifact (the
   self-hosting midpoint the 218 brief names); a `--emit-mono-ast` dump is
   future work, not this unit's. Ratify that the astdiff lane is therefore
   untouched by this unit.
3. **Do the freestanding / `--no-hidden-alloc` gates re-run per instance?**
   Recommendation: NO — both are authored-form/provenance rules (design 135's
   three sites are source constructs; the freestanding refusals key on
   declarations), and the abstract check already judges the authored
   construct. An instance introduces no allocation the template didn't write.
   The per-rule skip list (1c) records both, so a future rule that IS
   tier-dependent defaults to running.
4. **DF-258a interim handling.** The silent cooperative-contract drop is live
   on main today (probe P3b). Recommendation: pin it XFAIL at stage 0 and let
   stage 4 flip it — this unit is next in the queue, and an interim fix would
   rebuild the refusal the promotion decline lost only to delete it weeks
   later. Rule the alternative (restore the clean refusal now, as a
   fix-on-discovery inside the current architecture) if the queue slips.
5. **DF-247a scheduling.** Probed NOT dissolved by this unit (6c).
   Recommendation: its own small dispatch after 1.5, fixing the root-removal
   site with survivor-liveness plus the root matrix its entry owes; it should
   not ride this branch (different mechanism, and this branch is large
   enough).
6. **The depth limit.** Recommendation: 64, per chain, clean error naming the
   elided chain (1d). Implementation-shaped — the lead may ratify the number;
   flagged only because it is the one place this unit REFUSES a program the
   current compiler accepts (by hanging on it, so nothing working breaks).

## 9. The interaction ledger

### 9a. Design 234 unit 3 (the fallibility flip) — running in parallel NOW

Its landing churns std constructors and takes `try!` through the corpus —
.saw surface, not the compiler's Python. Overlap with this unit: (a) LINE
anchors in sawc/ shift little, but this spec cites functions for that reason;
(b) the corpus flip changes which example files exercise generic
instantiations (fallible generic `init` — DF-245a's `Result<Wrap<T>, E>`
lowering rides `_declare_monomorphized_method`'s `_init_llvm_return_type`
path, census M5/M6's surface), so **stage 3's suite gate must run on a tree
that already contains 234 unit 3** — the integration order is 234-then-1.5
per the queue, and this spec assumes it; (c) DF-251b's new pin (6a) should be
written with a fallible-init sibling row once 234 unit 3 lands, since the
fallible form is what made DF-251a visible in the first place.

### 9b. Design 242's spawn machinery — the synthesized helpers are monomorphization CONSUMERS

Verified against the transform as landed (unit 3, Aug 25): `_make_spawn_helper`
synthesizes `__spawn_<f>` / `__bgspawn_<f>` and the background singleton's
plumbing AFTER the transform runs — Saw ASTs that construct `Task<T>` /
`VoidTask` / `Thread<T>` and touch `__ResultCell<T>`, `Slot<...>` frame
fields, and (for the singleton) the process-wide group. Those are NEW generic
demands that do not exist in the pre-transform AST — today codegen serves
them lazily (census S8, and `_get_llvm_type` walks over frame structs). A
pre-transform-only monomorphizer would MISS them, which is why the pipeline
contract's phase 6 re-runs the fixpoint on the post-transform re-entry
(`_prepare_codegen`'s existing `post_transform=True` recursion is the hook —
the re-run walks the synthesized declarations, serves their demands from the
cache or freshly, and re-splices). The stage-1 shadow assertion is what
PROVES this list complete over the corpus: any demand class this spec failed
to enumerate surfaces as a shadow-mode miss on the very first full-suite run,
not as a stage-4 ICE. The 242 conformance rows K85-K91 join the regression
set for stage 4.

### 9c. Design 238 (the sawos split) — sequenced AFTER, by ruling

The Aug-24 re-order exists so this migration lands under the full in-tree
battery (sos lane included) and the sawos pin starts life post-1.5. Nothing
in this spec depends on 238; the terminal battery still carries the `sos`
stage.

## Appendix: probe inventory

| probe | file (`.build/scratch/spec218c/`) | result (this tree) |
|-------|-----------------------------------|--------------------|
| P1 | `p1_247a.saw` | ``error: undefined function `work` `` at the ordinary call — DF-247a reproduces |
| P2 | `p2_p08a.saw` | refused at the spawn: `` `launder` requires `T` to be `Copy` — it binds `x` twice, at lines 13 and 14; `Res` is move-only`` — S1 p08a's shape is closed abstractly (219) |
| P3 | `p3_nested_uncond.saw` | COMPILES and prints 5; IR shows `slowly$1$Int` = `ret i64 %x` (yield erased) while `__Frame_outer` exists — DF-258a |
| P3b | `p3b_interleave.saw` | `A 0, A 1, A 2, B 0, B 1, B 2` — the nested generic's yield never parks |
| P3c | `p3c_control.saw` | `A 0, B 0, A 1, B 1, A 2, B 2` — the direct-yield control interleaves |
| P4 | `p4_recursive.saw` | compiler produced no output in 120 s; killed — DF-258b |

## Amendment A (Sep 1, post-stage-2) — the template store, the splice cost, and stage 3's shape

**Status: USER-RATIFIED Sep 1**, in full, including A2(b)'s semantic cell —
ratified together with A5, which adds the forced-eager escape hatch and makes
3b's measurement decide whether laziness is bought at all. Its inputs were
ruled the same day: the process (amend the spec before stage 3 re-dispatches)
and the perf direction (BOTH remedies below — the substituting copier AND lazy
body materialization). Stages 0-2 + the DF-285a fix are INTEGRATED to main
(466812fe); stage 3 dispatches against this amendment as written.

### A1. The false premise (DF-285b) and its fix

Section 4 argues invalidation-free caching from "templates are captured
pristine at `check_module`'s capture point" and section 1c checks instances
"in the TEMPLATE's home module scope". Neither is true of std: std bodies are
checked by a separate typechecker inside `build_builtin_namespace` whose
result is cached, so on `examples/hello.saw` the pristine stores hold **zero**
templates and `_module_scope_by_file` has one entry — against 111 demanded
instances, every one std's. `_build_fn_mono` already declines a template with
no pristine copy; stage 3 cannot.

**The fix (RECOMMENDED): extend the capture, not the argument.** The std
checker gains the same two capture points the entry checker has — pristine
generic-template snapshot before body checks mutate annotations, and a
per-file module scope entry — carried in `build_builtin_namespace`'s cache so
the cost is paid once per cache build, not per compile. Section 4's
invalidation argument then holds verbatim over the union store.
**The fallback, only if the snapshot's cache cost measures prohibitive:**
clone CHECKED templates out of the merged AST (probed: 276/306 clean). This
is a different artifact from the one §4 argues about — a checked template's
annotations are post-mutation — so taking it means rewriting §4's argument,
and the probe's 30 failures (A3) suggest the real gap was scope, not the
template body. OPEN: none — the recommendation decides unless measurement
forces the fallback, which then returns here.

### A2. The splice cost (DF-285c) and the two ruled remedies

Splice-all measured ~+83% per compile (~1s absolute, 81% of it
`copy.deepcopy`, on hello/serde/json alike — the cost is std's type closure,
so every compile pays it). Envelope is +10%. The user ruled BOTH remedies:

**(a) The substituting copier.** One purpose-built AST walker that produces
the substituted clone in a single pass — copy and substitute together, no
`copy.deepcopy`, no second rewrite walk. It lives beside `mono_identity.py`
(same "one funnel, both sides" rationale) and MUST carry the DF-285a lesson:
the one type-parameter spelling that is not a `SawType` — a zero-argument
construction call's NAME (design 37) — is substituted by the copier itself,
not by a patch-up pass. Oracle: while shadow mode still exists, an
equivalence assertion (copier output vs deepcopy+substitute, whole corpus)
rides one gate run, then the deepcopy path deletes.

**(b) Lazy body materialization.** The registry still DECIDES every instance
— the fixpoint walks every demand, assigns identity, depth-checks, and
re-infers the per-instance effect node exactly as specced; nothing about
sections 1b/1d/4-keys changes. What moves is WHEN the checked clone AST is
built: eagerly (phase 2) only for the transform-relevant set — instances
whose effect node suspends, plus the driven/spawned/poly set already cloned
today — and for everything else at first BODY demand (design 168's existing
demand, which for a hosted `-c` object is every instance, and for an
executable is the reachable fraction). Materialization = copier + instance
check (§1c's inventory, errors real, §3 attribution) + splice, ONE funnel;
phases 5-7 consume only materialized bodies, and an unmaterialized instance
reaching either is an ICE. Section 1b's sentence stays the law: instance
EXISTENCE and body EMISSION are two questions, and lazy materialization
aligns CHECKING with emission, not with existence.

**The semantic cell this pins (RATIFIED Sep 1, with A5):** under (b),
an instance demanded but never emitted in an EXECUTABLE build is registered
and depth/effect-validated but its body is never instance-checked — a
diagnostic living only in such a body surfaces in a `-c` build and not in
the executable. This matches today's stage-2 behavior (codegen demands are
what get checked) and the compile's actual link surface; splice-all would
have been stricter and is what the envelope rules out. It is NOT the
design-168 narrowing the user declined — that one shrinks the `-c` instance
SET; here the `-c` set is complete and untouched. The cell is ratified under
A5: A5(a) keeps the strict answer computable and the reversal cheap, and
A5(b) may retire the cell outright if the copier alone brings splice-all
inside the envelope.

### A3. The ~30 std-instance diagnostics

At type-closure granularity the instance check reports ~30 diagnostics
against std's own bodies on hello.saw; two classes verified refusals of code
that compiles and runs (`Vector<String>.copy` — ``String is not Copy`` — and
`Vector<Item>.push` for a `@synthesize`d ExplicitCopy `Item`). HYPOTHESIS:
artifacts of the missing std module scope (A1) — the probe's check ran with
no home scope, where conformance lookups fail closed. After A1 lands,
re-run the probe (`.build/scratch/probe_std_instance_check.py`); whatever
survives goes through stage 2's own triage rule, unchanged: each residue is
either a REAL catch (kept, pinned) or a rule moved to §1c's named per-rule
skip list with the lead's sign-off. No blanket suppression.

### A4. Stage 3 restaged

Stage 3 splits into three separately-gated commits; 4 and 5 are unchanged.

| stage | content | gate |
|-------|---------|------|
| **3a — the store completed** | A1's std capture (pristine snapshot + module scopes in the builtin cache) | full suite under `SAWC_MONO_SHADOW=strict` (re-proof over the union store); the A3 probe re-run recorded in the landing note |
| **3b — the copier** | A2(a), landed while shadow mode still exists | the corpus equivalence assertion rides one strict-shadow gate run; suite + freestanding; **plus A5(b)'s decisive re-measurement of splice-all**, recorded in the landing note with the branch it selects |
| **3c — the cutover** | the atomic remainder, now affordable: phase 2 splices the eager set; codegen G1/G2/M1-M4 become registry lookups that MATERIALIZE through the one funnel on first body demand; G3 + M6 delete; S-rows registry-driven, ICE-on-miss; the codegen template stores retire | original stage-3 gate (suite, freestanding, reemit + irdet --all at the boundary, gmgate) PLUS the §5 measurement at this boundary — the +10% envelope BINDS here |

DF-251b's XFAIL flips at 3c (the generator deletion is 3c's). The §5
measurement instrument and envelope are unchanged; remedies 2/3 and the
design-168 set-narrowing remain unauthorized.

### A5. The forced-eager mode, and the measurement that picks the default

USER-RATIFIED Sep 1, together with A2(b), on the user's ruling that **the
measurement dictates which path we take**. Two clauses.

**(a) The forced-eager escape hatch and its lane.** Materialization gains a
forced mode — `SAWC_MONO_MATERIALIZE=all`, sibling to the existing
`SAWC_MONO_SHADOW` instrument (`sawc/monomorphize.py:82-90`; same shape: an
env switch, off by default, documented at the module header, run by the gate).
When set, the eager set is EVERY registered instance, so every demanded
instance is materialized and instance-checked whether or not its body is ever
emitted. It lands with 3c, since the funnel is 3c's, and it takes ONE battery
stage (`tools/battery.sh` STAGES — the whole suite under the forced mode).

The lane exists for three reasons, and they are the reasons the cell is
ratifiable: the strict answer stays computable on demand; the corpus is
PROVED to carry no latent errors sitting in never-emitted instances, so the
lax→strict ratchet never gets a chance to accumulate against us; and if the
default is ever flipped back, the evidence that flipping is safe is already
in the gate rather than owed as a migration.

Reversal cost, recorded so a later session does not have to re-derive it: the
default flips by WIDENING the eager-set predicate from transform-relevant to
all-registered. It is a predicate, not a redesign — the registry decides every
instance either way (1b/1d/4-keys untouched), and nothing 3c deletes blocks
it, because G3, M6 and the codegen template stores are the OLD path, not the
eager one.

**(b) The measurement decides the default.** The +83% that bought laziness was
measured with `copy.deepcopy`, and 81% of it WAS the deepcopy — which A2(a)
removes. So at 3b's boundary, after the copier is in and before 3c is
dispatched, §5's instrument re-measures splice-all (every registered instance
materialized eagerly, the post-copier cost). The result selects the path:

- **within the +10% envelope** → laziness is NOT bought. The eager set is
  everything, A2(b)'s semantic cell is MOOT and never ships, the forced mode
  of (a) degenerates to the default (keep the lane as the pin, drop the
  switch), and 3c's row loses its materialize-on-first-body-demand clause.
- **over the envelope** → A2(b) stands as ratified: lazy is the default, the
  cell ships, and (a)'s lane is what keeps it honest and reversible.

The 3b landing note RECORDS the number and names the branch it selects; the
lead confirms the branch before 3c dispatches. Nothing else in this amendment
is conditional — A1, A2(a), A3 and 3a/3b proceed as written either way.

### A5(b) OUTCOME — measured Sep 1, then USER-OVERRIDDEN the same day

The instrument answered OVER the envelope: full-suite compile median +18.8%
(330.8 → 393.0 s), bootstrap +16.8% (232.9 → 272.0 s), RSS nowhere close to
its +25%. By A5(b)'s own rule that selected lazy. **THE USER OVERRODE IT
(Sep 1): splice-all anyway.** The ruling, in the user's frame: an 18%
slowdown is acceptable now; it gets recovered later by TARGETED performance
work and/or the self-hosted compiler rewrite's own gains. What the override
buys is exactly A2(b)'s cell never shipping — every registered instance is
materialized and instance-checked in every build, `-c` and `-o` report
identically, and checking aligns with EXISTENCE, the strictest reading and
the one the never-hide-errors doctrine prefers. Consequences, all binding
on 3c:

- **The eager set is EVERYTHING.** Phase 2 splices every registered
  instance; the demand-time materialization funnel of A2(b) is NOT built;
  codegen's lookups hit already-spliced bodies, ICE-on-miss unchanged.
- **`SAWC_MONO_MATERIALIZE` is not built** — the default IS materialize-all,
  so A5(a)'s switch has nothing to switch. What survives of A5(a) is the
  PIN: an examples/ test asserting that a diagnostic living in a
  demanded-but-never-emitted instance's body fires in an `-o` build.
- **The §5 envelope is RE-BASED at 3c, not waived silently**: 3c's gate
  measurement compares against 3b's measured splice-all numbers (+18.8% /
  +16.8%), as a regression guard on 3c's own work — the +10% envelope is
  SUPERSEDED by this ruling for this landing, and a 3c result materially
  worse than the accepted figures still pauses for the lead.
- **Lazy materialization remains the recorded future perf remedy** — the
  registry-and-funnel architecture supports it unchanged, and taking it
  later would put A2(b)'s semantic cell back on the user's desk; it is not
  authorized by this ruling. §5 remedies 2/3 and the design-168 narrowing
  stay unauthorized too.
- **A3's residue is now a HARD 3c blocker in full**: under splice-all every
  compile checks all 30 type-closure instances, so every residue must be
  resolved — fixed, or a named §1c per-rule skip — before 3c can be green
  on `hello.saw`.

### A3 OUTCOME (Sep 1) — the hypothesis failed; the ruling on the real catch

3a's re-probe answered 30/30 IDENTICAL diagnostics before and after the
scope fix — A1's hypothesis is NOT confirmed; the residues are artifacts of
re-checking substituted/lowered std bodies, not of the missing scope. (Six
additional diagnostics present at filing time were FALSE, produced by
DF-286a's inflated registry, and died with its fix.) Triage per stage 2's
rule:

- **The `Box<any Trait>.value` family (6) is a REAL CATCH, and the fix is
  USER-RULED (Sep 1): `value` BORROWS.** The method returns the payload by
  value and an existential has no `copy`, so the body is only sound for a
  copyable payload — the check is right and std's API is the defect. It
  becomes a `borrows` accessor (lend the payload where it sits); Copy-tier
  call sites keep working (a place value-read retains), move-only payloads
  get the place surface instead of an unsound copy. Lands as 3c's FIRST
  unit with obligation 2's consumer sweep (who calls `.value`, both
  profiles) — a behavioral by-value→place flip on a std surface.
- **The remaining 24 (three families: tier tests on substituted clones,
  transfer checks on lowered bodies, one window-closure re-inference)** go
  to §1c's named per-rule skip list with LEAD sign-off, per stage 2's rule
  — the lead validates each rule is genuinely an artifact-of-recheck class
  before signing, at 3c dispatch.

**A3 CLOSED (Sep 1, stage 3c-0 + 3c-1).** The `Box<any Trait>.value` family
went first, as its own unit: the accessor BORROWS, so the six diagnostics have
no carrier and the residue dropped 30 -> 24, exactly the three pre-authorized
families and nothing new. The 24 then went to §1c as TWO named skips, not
three — skip 3 (a `.copy()` the silent tier answers) covered its six, skip 4
(a transfer of a substituted by-value parameter) covered its sixteen, and the
third family's two `__window` diagnostics turned out to be a CASCADE of skip 3
and vanished with it. The probe answers 292 pairs materialized, 292 clean, 0
reported.

## Amendment B (Sep 1, post-3c-2-stop) — the full-population census, the
## contaminated instrument, and the cutover's remaining rulings

**Status: PROPOSED by the lead from the Sep-1 full-population census
(224,768 instances / 667,851 pairs / 1,617 compilation units / 10,311
merged-scope diagnostics in 20 classes; evidence preserved verbatim at
`designs/reviews/splice-census-sep1.md`, per-diagnostic records
regenerable via `.build/scratch/census_splice/`). Awaiting the user on B4
and ratification of the rest.** The census's margin read: the class list
is CLOSED — `examples/` produced all 20 classes and the five later
populations (blade, blade tests, libs, devtools, selfhost) added none;
six classes have a single instance tree-wide. The open risk is IR-level
only (DF-286c face 4, invisible to a pre-codegen instrument) plus 14
method-generic instances with no pristine template.

### B1. M1 — the instrument's namespace is wrong, and it contaminated
### every prior number (FUNNEL GAP, fix first)

`measure_splice_all` — and therefore A3's 30 and DF-286b's 115 — checks
each instance in the template's home module scope with the compile's
AMBIENT namespace as the lend source, and that namespace is never
`mono.namespace` (probed, every compile): `_lend_instantiation_types`
copies nothing, and `copy_tier(Handle)` answers `free` merged and
`abstract` inside `std/vector`'s. Four whole classes and roughly a fifth
of the census volume are THIS, not rules (the census's classes 2 in
part, 5/8/9/10, 15/20-24; DF-286c face 3 is REFRAMED into it — the
registry's `_bounds_satisfied` answers correctly). THE FIX, recommended:
the instance check runs against the MONOMORPHIZER'S MERGED namespace
(conformances, tiers, lend types — program-wide facts are program-wide)
with the template's home module supplying VISIBILITY only (design 80/82
gating, which is what "home scope" was ever for). One funnel; its
docstring names both inputs. Class 14 (a private sibling function lost —
conformance K22's own shape) is expected to dissolve here and is
verified at B6, OPEN until then.

### B2. The dominant REAL class: the `borrows` lowering's own clones —
### skip 5, the substituted-RETURN sibling of skip 4

The `borrows` lowering makes every accessor a method-generic over its
window result type `__R`; nothing materializes method generics today, so
splice-all is the first thing ever to check them — and at `__R = Void`
the clone's `return __window(...)` is refused (``function returns void
but return has a value of type Void``) in 1,538 of 1,617 programs,
twelve USER-written accessors among them. Twin verdict: runs. **Skip 5:
a return-position judgment whose RETURN TYPE arrived by substitution is
the abstract layer's, not the instance check's** — one predicate, the
named sibling of skip 4's parameter rule, which also covers DF-286b
class 6 and its std twin (`Map._take_value`'s NoCopy return) and the
census's classes 17/18. Lands like skips 3/4: a named predicate with the
census citation, never keyed on "is std".

### B3. The design-130 unsafe classes carry their own doctrine — skip 6,
### citing design 136's as-written rule

Census classes 4/6/7 (`not declared unsafe`, 118 raw): the carrier is
the FRAME's `Slot<T>` and the window result type — lowering machinery —
not the user's `Vector<UnsafePointer<Int8>>`. Design 136 already rules
the position: an unsafe judgment is made on the type AS WRITTEN and
"never re-judged for a `T = UnsafePointer<Int8>` instantiation". The
instance check re-judging substituted types contradicts the written
rule, so **skip 6 cites 136 rather than minting policy**. Flagged for
the user's eye because it is a safety surface; the lead's read is that
no new semantics is being decided — 136 already decided it.

### B4. `Box<T, A>.make` placement-moves a NoMove payload — the census's
### one REAL-CATCH candidate, and a USER RULING

`std/box.saw:45` moves the payload into the heap slot; at a `NoMove` T
the instance check refuses (``cannot `move` `value`: `Anchor` is
`NoMove` ``), the hand-written CONCRETE twin is refused today — and
`examples/nomove_tier.saw:75` calls `Box<Anchor>.make` and RUNS, because
nothing ever instance-checked the generic. The bind: design 188's OWN
DOCUMENTED IDIOM is "hold a NoMove value behind a Box for a movable
handle over pinned storage" — so the language promises Box-of-NoMove
while its construction path is unwritable as concrete code. OPTIONS:
(a) BLESS the constructor-into-box as NoMove's one sanctioned second
move — amend 188: a NoMove value moves exactly once INTO ITS HOME, and
`Box.make`'s placement write is a home (the pointer-write path in
box.saw is unsafe-domain code whose soundness argument is exactly
"pinned hereafter"); (b) refuse it and retract the 188 idiom (breaks
`nomove_tier.saw` and the documented story). LEAD RECOMMENDS (a),
implemented not as a skip but as a RULE: the placement-move into
freshly-allocated unsafe storage inside the defining module's
constructor is legal for NoMove — otherwise the idiom is folklore.

### B5. The DF-286c fix list (funnel work, no rulings)

Face 1 CONFIRMED AND WIDER: the copier does not carry const-generic
VALUES — std's own `FixedBuf`/`FixedStringBuilder` are in the blast
radius (78 raw / 53 instances / 20 templates). Face 2 confirmed
(associated-type return unsubstituted). Face 3 reframed into B1. Face 4
(`-> T?` tail wrap, IR-level) is invisible to the census instrument and
is VERIFIED AT THE CUTOVER's own gates (reemit/irdet). Plus: the 14
method-generic instances with no pristine template get an answer (the
capture widened or the miss made a clean ICE), and the 71 module-support
refusals + 8 flag-needing fixtures are recorded as census scope notes,
not gaps.

### B6. The staging, and the enumerate-vs-invert ruling

The redo of 3c-2, serialized AFTER design 260 lands (typechecker
surface): **3c-2a** B1's namespace funnel + B5's faces 1/2 + skip 5 +
skip 6 (+ B4's rule as ruled), each gated; **3c-2b** THE RE-CENSUS AS A
GATE — the census instrument re-run over the full population must answer
ZERO reported (everything fixed, skipped-by-name, or B4-ruled) before
the cutover commit; **3c-2c** the cutover itself exactly as the stopped
3c-2 specced it (G3/M6 delete, template stores retire, DF-251b flips,
A5(a) pin, oracle retirement, §5 measurement against the re-based
envelope). On ENUMERATE vs INVERT for §1c: the census answers it —
the class list closed at the margin, the skip list totals ~6 named
predicates, and the re-census gate is the completeness proof a whitelist
inversion was supposed to buy; ENUMERATE stands, with inversion recorded
as the fallback if the IR-level population (face 4's layer) ever
surprises. RECOMMENDED, not yet ratified.
