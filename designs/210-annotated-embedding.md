# Design 210 — the embed carries its answers

**LANDED Aug 11.** All eight units. blade compiles again (24 errors → 0), which
is DF-206e's stated acceptance; design 206 lands with this brief as unit 0. What
landed, unit by unit, is at the bottom.

**Status: RULED Aug 11 (user: "fix this properly now") + AUTHORED;
dispatches immediately, building ON design 206's blocked branch.
Closes DF-206e by architecture rather than patch, and lands 206's two
liveness fixes with it. The ruling, verbatim in structure: an imported
NON-GENERIC function carries sufficient information for a caller to
embed it in its frame with NO re-typecheck; an imported GENERIC
function exports what a per-instantiation re-typecheck needs, and that
recheck runs in the callee's HOME module scope. The home-scope
machinery is therefore the PERMANENT generic path, not an interim fix.**

## The two paths

1. **Non-generic (user AND std — uniform):** the declaration-time
   typecheck's fully-annotated AST is the embed's input. The transform
   PRESERVES those annotations through the splice, stamps its own
   judgments for the rewrites it performs (locals→frame fields —
   generalizing the design-131/139 frame-slot carve-out from "don't
   re-judge" to "the transform is the authority for what it
   synthesizes"), and types only the GLUE: the frame struct (field
   types are the body's already-resolved local types), the state
   dispatch, the resumption edges. The post-transform recheck SKIPS
   preserved bodies; its safety-net role is replaced by the astgraft
   gate (the annotation schema is closed and declared — design
   126/194) plus targeted asserts at the splice boundary.
2. **Generic:** per-instantiation re-typecheck REMAINS (types and
   EFFECT re-infer per instantiation — designs 70/74, semantics
   unchanged) but runs with the callee's home-module namespace via
   design 204's `_type_lookup_module` funnel plus the instantiation's
   type map. This is where the DF-206e namespace loss is fixed for the
   path that genuinely must recheck.

**Design 84's std-only cross-module special case DISSOLVES** — std
methods ride the same two paths; the "static-inlining fix" era ends.

**The annotated-AST contract is a future-facing interface:** "what an
imported function exports" is exactly the module-interface shape
separate/incremental compilation will need. It is an IN-MEMORY contract
in this brief — enumerated, gated, and kept serializable — and is NOT
serialized now (explicitly out).

## Units

0. **Integration base.** Cherry-pick design 206's five commits
   (`a319aeb`, `a7db918`, `29829b0`, `cb0ce0d`, `ee24cdba` — branch ref
   `worktree-agent-a7323b534f1391273` still exists) onto current main
   (`f862aeb5`, which includes 201's spawn-reference lowering — the
   combination is UNTESTED and next-door; expect real conflicts in
   effects/coro/spawn surfaces and resolve them as integration, not
   rewrites). Full suite green before unit 1. 206's flipped pins,
   gmgate entries, and verified contracts are the acceptance harness
   for everything after.
1. **Conformance/pins first (obligation 3).** The DF-206e two-file
   repro shape (public method + private sibling + suspension) as a
   multi-module example via {TESTDIR} modules — non-generic embed row;
   the GENERIC cross-module embed row (a generic method whose body
   calls a private sibling, instantiated from the entry module); std
   regression rows (existing corpus largely covers; name them in
   INDEX); the frame-field foreign-type row (blade's `Cli`
   ExplicitCopy face). blade itself is the big consumer test — the
   bootstrap stage IS the acceptance for DF-206e.
2. **The contract, enumerated.** Write down (docstring + a short
   design-note section in this brief at landing) exactly which
   annotation families an embed consumes: resolved expression types,
   resolved callee symbols, effect facts (suspension points — they
   determine state splits), place/copy judgments, no-escape facts. The
   astgraft schema is the closure proof; anything an embed needs that
   is NOT a declared annotation is a finding, not a graft.
3. **The non-generic path** (the bulk): annotation-preserving splice;
   transform-stamped judgments for frame-field rewrites; glue-only
   typing; post-transform recheck scoped away from preserved bodies.
   The design-131/139 carve-out sites are the precedent — subsume
   them, do not duplicate them (process rule 1: one authority,
   docstring names its entries).
4. **The generic path:** home-scope recheck via `_type_lookup_module`
   + instantiation map; effects per 70/74 unchanged; the DF-206e
   generic row proves it.
5. **Dissolve the std special case** — delete design 84's std-only
   splice accommodations once both paths carry std; the suite's whole
   coro corpus is the regression net.
6. **DF-206f:** bisect and fix the `irdet --all` SIGSEGV on the
   combined branch (prints OK for all examples, then exits 139). It
   blocks the final gate regardless of cause; if it roots outside this
   brief's surface, STOP and file with the bisect result.
7. **Docs.** Spec: the embedding model gets a section stating what is
   now guaranteed across modules (any-depth driving, private siblings
   intact, generic instantiation semantics); skill: the concurrency
   section's cross-module story; close out DF-206e/DF-203a/DF-203b in
   the tracker; design 206's brief flips from BLOCKED to LANDED-VIA-210.

## The contract, enumerated (unit 2)

Written down in full as the module docstring of `sawc/coro_transform.py`
("THE EMBED CONTRACT"); the summary here is the index into it.

An embed consumes SIX families. Five are DECLARED `annotation(...)` fields on
AST node classes (design 126); the sixth is the effect graph, which rides
beside the AST keyed by `node_id`.

1. **Resolved expression types** — `resolved_type` on every node plus the
   derived records a later pass cannot recover without re-resolving
   (`resolved_type_identity`, `expected_type`, `autowrap_to_optional`, the
   match/result/error type records, the forward payload types). The frame
   struct is BUILT out of this family: a field's type is its local's resolved
   type.
2. **Resolved callee symbols and dispatch decisions** — `resolved_symbol`,
   `arg_plan`, `resolved_init_params`, `existential_dispatch`, `mangled_symbol`,
   the module/static/struct resolution records, the enum and erasure sets, the
   `um_*` set. **This is the family DF-206e lost**: each was answered in the
   callee's own module, and re-answering them under the entry namespace is
   exactly the request for `inner` in a scope that has no `inner`.
3. **Effect and suspension facts** — the state splits. On the AST:
   `is_chan_recv`, `is_yield_intrinsic`, `spawn_root`, `blk_extern`, the two
   `_coro_split` markers, `WhileExpr.diverges`. Beside it: the design-22 graph
   (`_suspend_nodes`), funnelled by design 206's `really_suspending`. CARRIED
   for a non-generic embed; RE-DERIVED per instantiation for a generic one,
   because designs 70/74 make effects depend on the type arguments.
4. **Place and copy judgments** — `needs_copy`, `payload_needs_copy`,
   `closure_lend`, `enum_variant_literal`, `place_value_read` /
   `place_abstract_read`, `lent_bindings`, `from_lend`, and the declaration's
   `place_*` set. Place lowering runs BEFORE the transform and is not re-run,
   so an embed consumes its output.
5. **What the transform stamps itself** — produced, not consumed:
   `frame_place_read` and the `ForceUnwrap` pair
   `frame_owning_read`/`frame_move_read`. Unit 3 turns this from a scattered
   habit into the one authority.
6. **No-escape facts** — carried by construction, stamped nowhere. The
   no-escape walk is a declaration-time refusal, so a body that compiled
   inherits its answer with nothing to carry.

**The closure proof is the astgraft gate** (813 declared attribute names,
zero grafted writes at unit 2): a fact the embed needed but no class declared
would have to be a graft, and the lane fails on any graft. Anything an embed
turns out to need beyond these six is a FINDING against the schema — declared
and listed — never a graft.

## Gates

Per-unit commits, full suite each; the FINAL gate is the full tracked
battery (all 17 stages — bootstrap and sos are the DF-206e acceptance),
gmgate BOTH lanes at -n 5, ten-repeat stability on 206's pins plus the
new multi-module rows, and irdet --all green (unit 6 is a prerequisite
of this gate). Read every verdict from actual output. This is the
largest transform surgery since the places work: any body shape the
two-path model cannot express STOPS and files rather than special-cases.

## Explicitly out

Serializing the interface (separate compilation is future work; keep it
serializable, do not serialize); a general typed-IR/MIR layer (the
annotation contract IS the layer this compiler gets); changing WHEN
embedding happens or which calls embed (design 84/96/104's decisions
stand); the effect-graph model beyond what 206 already fixed.

## What landed, unit by unit

0. Design 206's five commits cherry-picked onto main and integrated with
   design 201's spawn-reference lowering. **No textual conflicts** —
   `coro_transform.py` and `gmgate.py` auto-merged, `designs/todo.md` too — and
   the semantic combination held: both 206 liveness pins flipped and all seven
   of 201's K-rows green in one tree, 1738 passed / 8 xfailed.
1. Conformance rows K21-K24, three as cited XFAIL pins on DF-206e.
2. `THE EMBED CONTRACT` in `coro_transform.py`'s module docstring, censused off
   the schema (110 declared annotation fields across 23 classes) and indexed by
   the design-note section above.
3. The non-generic path. `Expression.embed_preserved` marks the expression kinds
   whose check consults the NAMESPACE; `_check_expression` hands back the stored
   answer; `_close_embed_marks` reduces the mark to subtrees that can actually
   answer; `_answered` is the funnel for what the transform grafts.
   `_store_binding_in_slot` is the frame-slot authority both binding
   constructs go through. DF-210a and DF-210b fixed. K21, K24 flip.
4. The generic path. `_home_module_scope` (four rechecks named in its docstring)
   plus `_lend_instantiation_types` for the caller's type arguments. K22 flips.
5. Design 84's std-only accommodation becomes `_decl_is_foreign_splice` —
   provenance, not privilege. Row K25 covers the position it could only permit:
   a module-private `static` in a CONST position, which lives in an annotation
   field and no structural walker reaches.
6. DF-206f: bisected in three legs, and the answer was not this brief's. It
   reproduces on design 206 ALONE (`ee24cdba`: 1089 examples, OK, **exit 139**)
   and on NEITHER integrated tree (unit 0: 1093, exit 0; unit 5: 1094, exit 0),
   so what closed it is design 201's spawn-reference lowering, combined with 206
   for the first time by unit 0. The tracker carries the table.
7. Docs: the spec's embedding-model paragraphs, the skill's cross-module
   concurrency story, README's positional paragraph, the tracker, and design
   206's brief flipped to LANDED-VIA-210.

### What the non-generic path's one authority subsumed

`_store_binding_in_slot` replaced two disagreeing copies of "how does a pattern
binding cross into its frame slot": `_optbind_dispatch`'s unconditional `move`
(DF-182c) and `_split_match`'s unconditional alias. Each was right for one copy
tier and wrong for the other, and the two failed in opposite directions — the
alias was a compile error on an owned payload, the move was silent memory
corruption on a retained one. One rule, asked of `Namespace.read_policy`, is
correct for both. `_answered` similarly gathered the frame-projection stamps
that had accumulated at seven call sites.

### Two things the ruling's premise did not survive contact with, both recorded

The declaration-time AST is not FULLY annotated (DF-210c: `StringInterpolation`
and friends carry no `resolved_type`), so "preserved" cannot be asserted
wholesale — it is COMPUTED, at the splice boundary, and any subtree that cannot
answer takes the ordinary path. And re-checking a node that never needed a scope
is not merely harmless but load-bearing: the post-transform pass accumulates
context as it walks, so marking too much LOSES facts. Both are why the mark is
scoped to the namespace-consulting kinds rather than to everything the
declaration pass touched.
