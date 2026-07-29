# Design 55 — Function/method overloading, exact-match model (DECIDED Jul 29)

**Ruling (user):** overloading beyond `init` ships, with the
exact-match design — viable precisely because Saw has NO implicit
conversions. Slotted BEFORE the N-family briefs so stdlib APIs are
designed with it. Also decided in the same session: `loop` keyword
DROPPED entirely (redundant with `while {}`); unsafe BLOCKS dropped in
favor of the named principle **"unsafety is type-carried, not
region-carried"** (spec doc item below).

## Resolution model (the whole design)
- Candidates: all visible functions/methods with the name.
- A candidate MATCHES iff every argument is exactly type-compatible
  (existing `_types_compatible`: aliases flow to underlying, defaults
  filled — no conversions).
- **Pinned tie-break rules (apply in order, then require uniqueness):**
  1. Exact beats optional-wrap: an `Int` argument prefers `f(Int)`
     over `f(Int?)`; both may coexist.
  2. Resolution runs BEFORE Result/Optional auto-wrap (the design-30
     machinery consumes the already-resolved callee).
  3. Concrete beats generic instantiation: `f(Int)` beats `f<T>(T)`;
     two generic candidates both matching = call-site ambiguity error.
- After rules: exactly one candidate or a call-site error listing the
  matching candidates.
- **Declaration-site rejection** for truly-irresolvable overlaps:
  identical normalized signatures (post-alias, post-default-fill), or
  pairs no rule can separate. Same-arity different-types is legal;
  different-arity always legal.
- Closures as arguments: resolve using the non-closure arguments
  first; if candidates still tie and differ only in closure-param
  types, ambiguity error (keeps brief-29/40 expected-type inference
  single-target). Report if this bites in practice.
- Mangling: extend the canonical mangler with parameter-type
  signatures for overloaded FUNCTIONS/METHODS (init's name-based
  scheme retired onto the same footing — migrate init mangling if it
  falls out naturally, else note).
- Effects/checkpoint machinery consume the resolved callee (no
  change — but assert resolution completes before effect edges are
  recorded).

## Items
1. Namespace: name → overload-set (list) for functions and methods;
   registration-time declaration-site checks.
2. Typechecker resolution per the model at every call form (free,
   method, static, module-qualified); diagnostics: no-match lists
   candidates with types; ambiguity names the survivors.
3. Mangler extension + codegen plumbing keyed on the resolved symbol.
4. Stdlib cleanup as the forcing consumer: `StringBuilder.append`
   absorbs `append_int` (keep the old name as deprecated alias or
   remove + migrate tests — report the choice); scan std/ for other
   `_int`/`_str` suffix warts and unify where clean.
5. Tests: same-arity type dispatch; arity dispatch; exact-vs-wrap;
   concrete-vs-generic; both ambiguity errors (call-site + decl-site);
   overload through modules; method + static forms; closure-arg rule;
   effects through overloads (a sync and non-sync overload pair —
   verify per-candidate effect edges).
6. Docs: spec functions section + the type-carried-unsafety principle
   in the unsafe section; drop `loop` from the keyword appendix and
   all spec mentions (while {} is the idiom); CLAUDE.md.

## Hazards
Resolution must be a single chokepoint feeding everything downstream
(checkpoint/effects/exclusivity key on the callee). The generic suite
+ closure-inference tests are the false-positive oracle. Full suite
per commit; zero xfails.
