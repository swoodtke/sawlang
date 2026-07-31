# Design 80 — Member visibility: fields + methods, std under the gate (DECIDED Jul 31)

**Ruling (user):** close the encapsulation hole before more code is
written. Structs/top-level already have private-by-default +
`public`/`public(package)`/`public(parent)`; FIELDS and METHODS have
no visibility at all (all-visible-with-the-struct), and std bypasses
the gate entirely (prelude-merged) — so "internal" helpers like
Vector.grow are comment-only fiction, and Vector's length/capacity
invariants are writable from user code (a memory-safety hole through
safe code: corrupt length → OOB reads via bounds-checked get).

## Semantics (pinned — consistent with the existing rule)
- **Private-by-default OUTSIDE the defining module**, for BOTH struct
  fields and extension methods (incl. init and static methods). Same
  modifier family per member: `public name: String`,
  `public(package) buf: ...`, `public func get(...)`. Inside the
  defining module: unrestricted (today's behavior).
- Trait-conformance methods: visibility follows the TRAIT's
  requirement — a method satisfying a public trait's requirement is
  callable wherever the conformance is visible (a `public` marker on
  it is allowed and redundant); dispatch through `any Trait`/generics
  unaffected.
- Struct LITERAL construction (`Point(x:, y:)`) cross-module requires
  ALL fields visible; otherwise use a visible init (the init system
  already covers this; error message says so).
- Pattern matching/destructuring on a struct cross-module requires
  the matched fields visible (same rule as access).
- Enum variants: follow the enum's visibility as today (per-variant
  visibility NOT in scope; note as future if ever wanted).
- **std goes under the gate**: std modules obey the same rules as
  user modules (kill the prelude bypass for visibility purposes —
  compiler-known-ness for codegen stays; only the ACCESS check
  changes). The `_`-prefix convention stays as style, but privacy is
  now real.

## Scope
1. **Probe first**: demonstrate the Vector length-corruption hole
   from user code on baseline (`.build/scratch/`); it becomes the
   headline locking error test after the fix.
2. Typechecker: member-access / method-call / struct-literal /
   pattern checks consult member visibility (definition module vs
   use module — the existing top-level visibility machinery's
   module-identity logic is the pattern to reuse). Clean errors
   naming member, type, and required visibility.
3. Parser/AST: visibility modifiers on fields and on extension
   methods (grammar mirrors top-level).
4. **Std/libs/blade sweep**: annotate intended-public members
   (`public` on the real API surface: Vector.push/pop/get/len/...,
   Map/Set API, String methods, std.net's public functions, blade's
   cross-module types/fields); leave internals unannotated (now truly
   private); fix anything the suite/blade/bootstrap flush out. This
   sweep IS the audit of every std API surface — report anything
   that was only working via the bypass.
5. Tests: field private cross-module (read + WRITE + literal +
   pattern), method private cross-module (incl. static + init),
   public(package)/(parent) member forms, trait-conformance method
   visibility, same-module unrestricted, the Vector-invariant
   headline test. Full regression.
6. Docs: spec visibility section (member rules + the construction/
   pattern consequences), saw-lang skill (visibility gotchas +
   'public your API surface' guidance), CLAUDE.md digest line,
   tracker (design 80 landed; the encapsulation hole closed).

## Hazards
- The std sweep touches every std file — mechanical but wide; the
  suite + blade + bootstrap are the oracle, run attentively per
  commit.
- Synthesized code (Equatable/Comparable/Hashable synthesis, drop
  glue, coroutine frames, existential thunks, literal lowerings)
  reads fields ACROSS module boundaries by construction — compiler-
  generated access must be EXEMPT from the gate (it enforces source-
  level access only). Getting this wrong breaks everything; getting
  it silently too-permissive re-opens the hole for user code.
  Distinguish by provenance (synthesized nodes), not by name.
- `public` on a member of a non-public struct is legal but inert
  (like Rust) — no warning in v1.
Full suite + blade/libs + bootstrap green per commit; zero xfails.
Standing policy applies. Load the saw-lang skill; self-review .saw
changes against it.
