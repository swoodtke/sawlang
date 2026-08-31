# Design 258 — Field Visibility Inherits the Type's (amending design 80)

**Status: AUTHORED Aug 31 2026** (lead; RULED by the user same day after
reading the sos code — "the member should inherit the visibility of their
parent after all. lots of duplication the current way." Three cells pinned on
the ruling sheet below). SCHEDULED after design 218 unit 1.5 (user's
ordering). Agent DF range: assigned at dispatch.

## The ruling (user, Aug 31 — supersedes design 80's field default)

1. **A bare struct field takes the visibility OF ITS DECLARING TYPE, at every
   tier** — `public`, `public(package)`, `public(parent)`. A
   `public(package) struct ProcessSlot` no longer spells `public(package)` on
   each of its fields; a `public struct`'s bare fields are public. The gate
   itself is unchanged — it only ever applied OUTSIDE the defining module,
   and same-module access stays ungated.
2. **`private` becomes the narrowing spelling.** A contextual keyword (the
   spec's second group, like `module`/`parent` — an ordinary identifier
   everywhere else, so `let private = 3` keeps compiling), legal on a FIELD:
   `private buffer: UnsafePointer<T>?` means what a bare field means today.
   On any other declaration it is a clean error naming the default ("a
   declaration with no modifier is already module-private").
3. **Fields only — extension members are EXPLICITLY EXCLUDED** (user ruling,
   over the lead's own-module-inheritance alternative). THE RATIONALE, in the
   user's own frame (Aug 31): **extension methods are FUNCTIONS — they just
   happen to act on a struct — so they need a DECLARED visibility or else
   they are per-module helpers.** A field is the type's own data and rides
   the type's tier; a method is a declaration in its own right, and a bare
   one is a module-private helper exactly as a bare free function is. So
   methods, inits and statics keep design 80's per-member marking, and the
   principle generalizes: nothing function-shaped ever inherits reach from a
   type. Two standing idioms are consequences that fall out and stand: the
   Aug-5 safe-utility-extension idiom (a bare helper on a foreign/std type is
   safe BECAUSE bare means private there) and the Aug-20
   no-visibility-on-extension-heads ruling.
4. **Widening stays capped**: a field marked wider than its type is
   legal-but-inert exactly as today (gotcha 3 of design 80).
5. **The public-API-needs-public-types rule (Aug 21) applies to the INHERITED
   visibility.** A public struct's bare field whose type is less visible was
   fine yesterday (the field was private) and is a refusal now — the field's
   reach is public and its type must keep up. The migration answers every
   in-tree instance with `private` (below); the diagnostic's two-fixes hint
   gains a third out: mark the field `private`.
6. **Memberwise literals follow for free**: construction visibility is field
   visibility (unchanged rule), so a cross-module `T(a:, b:)` on a public
   struct with bare fields now works by default — part of the point.

Enum CASES are untouched (already as visible as the enum — they are its
constructors and its match surface); a case's payload fields have no separate
gate today and gain none.

## Obligation 1 — the funnel

Effective member visibility must be answered in ONE place. The gate is
`_member_gate_allows` (`sawc/typechecker/core.py`, beside
`_ext_scope_allows`); the change is wherever a FIELD's declared visibility is
READ on the way into it — route every reader through one "effective
visibility" accessor (declared marker, else the declaring type's tier, else
private for `private`), so the default lives in one function and the
`--emit-docs` surface, the memberwise-literal check, the design-193
public-API-needs-public-types walk and the gate itself all agree by
construction. If field-visibility reads turn out scattered, the funnel is
unit 1 and the sweep of its call sites is the evidence.

## Obligation 3 — conformance rows FIRST

The "Visibility and module boundaries" section of
`examples/conformance/INDEX.md` claims field privacy in several rows (B22's
private-type-escape most directly). Unit 0 re-reads every B row against the
new default and updates the claims + covering tests before the semantics
land; a row whose test asserted "bare field refused cross-module" flips to
assert the marked-`private` refusal plus the new inherit-works half.

## Obligation 2 — the consumer sweep IS the migration

Every bare field in the tree changes meaning, so the sweep is total and
mechanical, with ONE decision rule: **existing code keeps today's surface
exactly.**

- Every bare field of a non-private struct in `sawc/std/`, `sawc/builtin.saw`,
  `libs/`, `blade/`, `devtools/` gets an explicit `private` (std's
  `Vector.buffer`/`length`/`capacity`, `Data`'s window fields, `File`'s fd —
  the census enumerates them all). Zero behavior change, byte-identical
  surfaces, and the suite proves it.
- Existing explicit `public`/`public(package)` field markers are KEPT even
  where now redundant — stripping them is churn with no information gain,
  and a later cleanup can be its own mechanical pass if the user wants one.
- `examples/` design-80 tests that assert a bare field's refusal flip per
  the conformance unit; the rest of the corpus compiles unchanged (bare
  fields of PRIVATE structs — the overwhelming majority — mean what they
  always meant, since private-tier inheritance IS module-private).
- Grep census before dispatch bounds the patch: the agent reports the count
  of bare-field-in-visible-struct sites per tree.

## Tests

Matrix rows: {public, public(package), public(parent), private} struct ×
{bare field, `private` field, explicitly-marked field} × {same-module,
same-package, importing-module access} — refusals AT the access naming the
tier, acceptances by direct read/write AND memberwise literal. Plus: the
rule-5 refusal (public struct, bare field, private field type — error names
the three outs); `private` as an ordinary identifier still compiling; the
capped-widening regression row; `--emit-docs` showing inherited visibility.

## Docs

Spec "Member visibility" section rewritten (the rule, the keyword, the
fields-only boundary and WHY extensions are excluded); the saw-lang skill's
design-80 bullets — including the "do NOT cargo-cult `public`" gotcha, which
inverts into "mark internal fields `private` in a visible struct"; README's
visibility line if it states the field default. CLAUDE.md digest untouched.

## Version

A language-semantics change: minor bump at landing (value fixed at dispatch
against whatever is then current).
