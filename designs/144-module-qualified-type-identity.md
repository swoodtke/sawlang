# Design 144 — module-qualified type identity

STATUS: APPROVED (user, Aug 5). Queued after 138 (end of the current
approved queue — P2: today's behavior is a SOUND hard error, never a
miscompile, so nothing burns; this is scaling groundwork). Closes DF-142a.
Kinship: design 126 (stable NodeId) — the same shape of wide-but-mechanical
identity change, and 126's astdiff/irdet gates are the safety net that
makes this one tractable.

## Problem (DF-142a, repro in the tracker)

Two modules each declaring a PRIVATE `struct Header` collide ("ambiguous
struct `Header`"), so every private type in a dependency is a reserved
word for consumers — the exact hole design 142 closed for statics and
functions, left open for types because a type's identity is not one
symbol string: it threads through `SawType.struct_name`, the
`Codegen.struct_types` layout registry, monomorphization keys, method
mangling (`Struct_method`), synthesis keys, the AST dump, and docs
emission. The 142 agent correctly refused the shortcut (suppressing the
error would register ONE layout under the shared name and silently
miscompile the other module's field accesses).

## The change

Type identity becomes `(defining module, name)` END TO END:
- `SawType` carries its defining module (or `struct_name` becomes the
  qualified form with a short display name — pick ONE representation and
  state it; diagnostics and docs always render the short name, qualified
  only when ambiguous in context).
- The layout registry, monomorphization/instantiation keys, method
  mangling, `@synthesize` derivation keys, and any other name-keyed table
  inherit the qualified identity. Two modules' private `Header`s become
  two types with two layouts, two `Vector<Header>` instantiations, two
  method symbol families.
- Name RESOLUTION rules are unchanged (142's scoping already governs
  which names are visible where); this brief changes what resolved names
  MEAN downstream. A resolved type reference carries its qualified
  identity from the typechecker so codegen never re-resolves by string.
- **Public same-name types across modules stop colliding too**: with real
  identities, `import x as` aliasing (already in the language) lets two
  packages' public `Header`s coexist; a bare ambiguous reference stays
  the existing use-site error naming both modules (the 142 pattern).
- Wire-stability note: `--emit-docs` and the AST dump gain the module
  qualifier as a FIELD, not a renamed name (astdiff must show a purely
  structural, deterministic change; document the dump-format bump).

## Proof obligations
irdet byte-identical on the unchanged corpus; astdiff deterministic with
the format bump recorded; the DF-142a repro compiles with BOTH `Header`s
live (each module constructs and uses its own — field offsets asserted
distinct via different layouts); `Vector<Header>` from both modules in
one program instantiates twice (oracle: distinct element behavior);
method calls dispatch to the right type's methods; public same-name
coexistence via aliasing; the 142 use-site ambiguity error unchanged for
bare references; full gate battery.

## Docs
Spec: the type-identity paragraph joins the member-visibility/142 section;
skill note only if user-visible spelling changes (expected: none — this
is semantics of existing spellings). Tracker: DF-142a closed.
