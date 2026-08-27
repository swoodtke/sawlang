# Design 249 — Free Functions Get Module Identity (the DF-265a Fix)

**Status: AUTHORED Aug 27 2026** (lead; scheduled by the user directly after
DF-215f, which landed the same day — this brief dispatches on 247's
integration). Fix brief for DF-265a; DF-242b is an EXPECTED CLOSURE;
DF-242c is re-probed and expected to SURVIVE. Agent DF range: **DF-268a+**.

## The finding (verified mechanism — tracker entry DF-265a has the full text)

`namespace.function_overloads` is one FLAT dict keyed by bare name
(`sawc/namespace.py:762-774`); free-function symbols carry no module
identity. Consequences, both probed in the wild:
- The design-53/55 declaration-site ambiguity check
  (`typechecker/registration.py:925-949`) compares call-shape keys against
  EVERY registration under the name, cross-module — so `std.json` adding
  `public func encode<T: Serialize>(value: &T) -> Result<String, EncodeError>`
  beside `std.cbor`'s same-shaped `encode` fails every build (reported as
  `builtins failed to type-check` only because std typechecks in the
  builtins pass — the registry is compilation-wide, and user modules share
  it).
- DF-242b: a cross-module overload set imported BARE binds as a single
  overload, so a call only another member matches is refused while the
  qualified spelling sees all of them — the same unkeyed registry read from
  the call-site side.

The contrast is already in the tree twice: STATICS got a per-module overlay
at DF-140h (`namespace.py:776-789`), and TYPE identity has been
(defining module, name) since design 144. Free functions are the LAST
unkeyed symbol kind. That is the fix: give them the same treatment.

## The fix

**Key free-function symbols by defining module.** Concretely (the agent maps
the exact shape onto what `FunctionSymbol`/`Namespace` already do for
statics — match the DF-140h pattern, do not invent a third scheme):

1. A `FunctionSymbol` records its defining module (root module = the empty
   key, exactly as statics do). Registration lands the symbol in its
   module's overload set.
2. **The declaration-site ambiguity check compares SAME-MODULE declarations
   only.** Two modules may hold shape-identical same-named functions —
   that is the point.
3. **Lookup follows the design-150 binding order, per position** (obligation
   1 — this is a position-quantified rule and the lookup is the funnel: the
   docstring of the one lookup entry point names its callers; if
   `lookup_function_overloads` has grown multiple callers that each
   assemble visibility differently, the brief's first job is routing them
   through one resolver):
   - Bare call in module M: M's own overloads, then names imported bare
     into M (`import x.*` / `import x.{f}`). If bare imports bring
     same-named functions from TWO modules, the merged set is the overload
     set — resolution proceeds normally; a genuine tie is the existing
     ambiguity error AT THE CALL, naming both origins. (This is DF-242b's
     cell fixed: the merged set actually contains every member.)
   - Qualified call `q.f(...)`: exactly the named module's overloads.
4. Visibility (design 80/82) applies as today — this brief changes symbol
   IDENTITY, never exposure.

## Obligation 2 — the consumer sweep (who relies on the flat behavior)

- Nobody relies on the COLLISION (it was a build failure).
- DF-242b's single-overload bare binding: relied on by nothing knowingly —
  it produced refusals, not results; the pin (if one exists under its
  entry) flips and its marker is removed in the same landing.
- Overload RESOLUTION within one scope is unchanged — same-module sets
  resolve exactly as before; the change only ADDS members that were
  previously invisible (bare-imported cross-module) or forbidden
  (same-name-other-module). The suite + irdet/reemit lanes police the
  emission consequences of resolution changes corpus-wide.
- `builtin.saw` + prelude functions: the agent verifies prelude-visible
  free functions (the `print`/`panic` family et al.) keep their binding
  order relative to user declarations — the design-150 weak-binding ladder
  must come out of this unchanged; a probe per ladder rung goes in the
  test set.

## Units

**Unit 1 — the keyed registry + scoped check + funnel lookup**, with the
probe matrix as tests:
- std collision legalized: re-probe the DF-265a shape (a scratch std twin or
  the real one — see unit 2).
- User-module twins: two dep modules exporting same-named same-shaped
  generics; cells for qualified calls to each, selective bare import of one,
  bare imports of BOTH + a resolvable call (distinct arg types), bare
  imports of both + a genuine tie (error names both origins).
- DF-242b's matrix from its entry: the bare-bound cross-module set now
  resolves the member the old binding refused; qualified spelling unchanged.
- DF-242c re-probe (suffixed-literal disambiguation): expected to SURVIVE —
  record the post-fix behavior on its entry; its same-module cell is a
  resolution-order question, not identity. Do not attempt its fix here.
- Ladder probes per obligation 2.

**Unit 2 — `std.json.encode` reclaims its name.** Rename `encode_json` ->
`encode` (the natural name DF-265a forced away), now legal beside
`std.cbor.encode`; update `JSON.md`, the docstring, and any test callers.
This is the live in-tree proof of unit 1 and lands only after it.

**Unit 3 — tracker close in place** (DF-265a + DF-242b under it), never
touching done files.

## Gates

Compiler branch: per-commit full suite + freestanding runner through the
machine-wide suite lock (SPLIT lock pattern in sandboxed worktrees — bare
mkdir-wait call, gate calls, bare rmdir; never stop or background while
holding). Terminal: the full battery; the resolution surface this touches
makes `irdet`/`reemit` the lanes to watch, and `bootstrap` exercises
blade's real multi-module binding.

## Obligations ledger

1. The lookup funnel (rule 3 above) — one resolver, docstring-named
   callers. 2. The sweep above. 3. No conformance rows (name binding, not a
   runtime safety guarantee). 4. The mechanism is the DF-265a entry's,
   verified; the matrix above is its position enumeration (declaration
   check, bare lookup, qualified lookup, import-merge — every reader of the
   registry).
