# Design 194 — the typechecker→codegen contract debt

**Status: AUTHORED from design 190's analysis (Aug 9), awaiting user
approval to queue. Payoff (matrix evidence): structurally forecloses the
DF-187b class (twelve hand-walks disagreeing about a stamped-field
shape), fixes one latent must-agree divergence (DF-190c), turns Pyright
from policy-noise toward signal, and de-risks the parser port you are
about to author. Cost (census-priced): mostly SMALL — design 126 already
did 89% of the schema work. Keep serial with 193 (both touch typechecker
internals).**

## Units

1. **Finish design 126's schema + gate it.** Declare the NINE grafted
   stragglers that crept back since 126 as annotation fields (census
   citations: `sync_reason`, `poly_candidate`, `suspends` in effects.py;
   `resolved_static_symbol`, `_authored_callee`,
   `is_interior_cell_construct`, `interior_cell_ptr`, `enum_from_raw`,
   `is_yield_intrinsic` in expressions.py/statements.py). Then MECHANIZE
   126's own "zero grafted AST writes" exit criterion that was checked
   once by hand: `tools/test_ast_graft.py` — grep for `setattr` on nodes
   and `node.<name> =` writes of names not in the declared schema, fail
   on any. A walk-the-declaration gate, same family as the prelude-gate
   and abidoc tests that already earn their keep.
2. **DF-190c — the diverged specialization key (latent must-agree
   bug).** `_make_specialization_key` handles design-148 const-value
   type args in codegen (generics.py:566-571) but drops them to an
   empty key in the typechecker (expressions.py:6409-6411). FIRST a
   probe: does a const-generic specialization ever key through the
   typechecker copy (if it does, front and back disagree — a real
   miscompile)? Record the answer. THEN unify to one shared helper.
   Pin whatever the probe reveals.
3. **Deduplicate the other two must-agree helpers.** `_pointer_size_bits`
   — codegen delegates to `target_info` (its comment already says
   "kept identical on purpose"); trivial. `_pattern_binding_names` —
   three divergent variants (typechecker returns triples + walks
   subpatterns generically; codegen bare names, no EnumPattern;
   coro_transform bare names, explicit EnumPattern) → one canonical
   triple-returning helper with thin adapters, and codegen's
   missing-EnumPattern case checked against its callers (a latent gap
   in its own right).
4. **DF-193d — the written-form provenance bit + the std annotation gate
   (inherited from 193 u7, Aug 10).** 193 built the std import gate for
   annotation positions and STOPPED with the diagnosis: the author's
   spelling of a type annotation is destroyed before any check can read
   it — `_canonicalize_module_types` and `_register_function`'s design-68
   signature write-back both replace it. Add a provenance bit ("the user
   wrote this name here") as a declared annotation field under unit 1's
   schema, then route the std gate through `_resolve_type` on that bit,
   closing DF-188k across every annotation position. PIN to flip:
   `examples/std_import_gate_signature_position.saw` (XFAIL, cited
   DF-193d). **This is a behavioral-contract flip and owes the consumer
   sweep** (CLAUDE.md brief-rule 2): legal-today code names ungated std
   types in signatures — the sweep found `examples/cbor169_vectors.saw`
   naming `IoError` in a return type with no import; sweep the whole
   corpus + std + blade/libs before flipping, and fix the offenders in
   the same landing.
5. **Stage the getattr→field conversion.** Now that the schema fields
   carry defaults, `getattr(node, 'a', None)` ≡ `node.a`. Convert
   codegen's ~236 AST-node getattrs to direct typed reads in reviewable
   batches (by file, the census gives the per-file counts). This is the
   unit that makes Pyright signal on codegen and shrinks the parser
   port's surface; it is MEDIUM and mechanical — land it in per-file
   commits, suite green each, and STOP a batch if a getattr turns out
   to guard a genuinely-optional field (that field stays getattr and is
   noted).

## Gates

Per-unit commits, full battery each. Unit 1's graft gate must pass on
the tree it lands in (declaring the nine first). Unit 2's probe result
is recorded before the unification. Unit 4's consumer sweep is recorded
before its gate flips. irdet --all matters for unit 5 (a
getattr-vs-field read must not change emission) — byte-identity across
the corpus is the check. Pyright's codegen diagnostic count is reported
before/after unit 5 as a secondary metric (the point is fewer false
positives, so real ones surface).

## Explicitly out

A full typed-IR or MIR layer (this is the AST-node contract only); the
parser port itself (this de-risks it, does not do it); converting the
typechecker's own 617 getattrs (unit 5 is codegen-only — the reader
side of the contract; the writer side is units 1-2); the six duplicate
qualified-name parsers (parse_type brief material, design 190 rule 7).
