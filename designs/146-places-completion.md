# Design 146 — places completion: front-end AST reuse, use sites, the P0 pair

STATUS: APPROVED (completion of the user-approved design 141 — its
deferred half; dispatches immediately after 141's declaration half
integrates, AHEAD of 145/135/138/144: it carries the open P0). The 141
agent's stop findings are the specification's first unit; its landed
declaration half (lexers, effect slot, `[]` names, `lend` coverage, the
closure-shaped lowering) is on main and NOT re-opened here.

## Unit A — `_prepare_codegen` reuses parsed ASTs (the unblocker)

The coro transform's mutate-AST-and-re-enter pattern cannot carry a
mutation into std because `_prepare_codegen` RE-PARSES every module and
builtin from disk on the `post_transform` pass — so no post-typecheck
rewrite reaches `std/vector.saw`. Teach it to reuse the already-parsed
(and already-transformed) module ASTs. This also DELETES a redundant
full re-parse of std from every compilation — measure and record the
front-end time saved. Proof: astdiff clean (the dump must not change),
irdet FULL sweep byte-identical, suite green — the refactor is
observable only as speed.

## Unit B — use-site lowering

With unit A, the 141 lowering reaches call sites: a place USE
synthesizes the closure call the declaration half already lowers to
(`v[i].count += 1` → the `__window` closure receiving `&var T` — types
come from the typechecked tree, which is why this runs post-typecheck).
The 141 agent's finding stands: the address form is NOT expressible
(`&var` is argument-position-only), so the closure synthesis IS the
lowering — same code with_ref emits. Cover every semantics bullet from
the 141 brief's table at USE sites now: both flavors from one
declaration, window extent, root attribution + exclusivity conflicts
(the review's invalidation probe as a place), LIFO epilogues for
multi-place arguments, chained windows (`m["k"]!.items[2].flag = true`),
value reads consulting `Namespace.copy_tier`, conditional-lend None
paths, `f(&v[i])` call-spanning windows.

## Unit C — std conversions, the P0 pair, the migration (from 141)

- `Vector.[]` (panicking place) + `Vector.get` → `borrows -> T?`
  (conditional lend) + Map's `[]`; Data equivalents per the 141 brief.
- **The DF-132a/DF-128c pair, ONE commit**: the `_type_method_base`
  drop-glue mangling fix + the `get` conversion land together (each
  unsound alone — 132 unit H's diagnosis, repros in the tracker).
  Trivial/ImplicitCopy `get` value reads keep owned-`T?` behavior
  (retain oracle proves zero caller breakage).
- toml → places (`section(name) borrows -> TomlTable?`), blade call
  sites become chains. One migration, no closure interim.
- Count the with_ref-ceremony sites that become places in
  std/blade/examples.
- DOCS land here (they were correctly withheld): the unified spec
  Places section with the suspension-not-return teaching paragraph,
  skill, README. Tracker: close the P4 places entry, DF-132a, DF-128c.

## Unit D — the irdet gate learns from its miss [finding promoted]

The 40-file sample sat on a latent nondeterminism until 141's new
examples reshuffled it; the agent's FULL sweep (807 files) caught it.
Policy change: `make irdet` keeps the fast sample for per-commit use;
the FINAL gate battery of every brief runs `irdet --all` (Makefile
target `irdet-all`; document in CLAUDE.md's testing section + the
tracker's DF-126b entry gets the "gate strengthened" note with the
wall-clock cost recorded).

## Gates
Per-unit commits, suite green each; final battery: suite, lexdiff,
irdet --all, astdiff, bootstrap, sos. The 124/134/127 fences and 137's
format tests stay green throughout.
