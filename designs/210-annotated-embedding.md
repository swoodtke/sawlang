# Design 210 — the embed carries its answers

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
