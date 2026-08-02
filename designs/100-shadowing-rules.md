# Design 100 — shadowing: error unless derived from the shadowed binding (queued Aug 2)

User-decided (Aug 2). Today an inner `let/var x` silently shadows an
outer `x` — an accident-prone hole. New rule: **shadowing an existing
binding is a compile error UNLESS the new binding's initializer
expression references the binding it shadows** — a shadow is legal
exactly when it is a visible REFINEMENT of the old value.

## The rule
```saw
let x: Int? = get()
if let x = x { ... }          // OK: initializer references shadowed x (unwrap)
var data = read()
let data = parse(move data)   // OK: derived + old binding retired
let data = parse(data)        // ALSO OK: derived (mentioning data proves intent;
                              // "it's obvious data is being redefined")
let x = 5
{ let x = compute() }         // ERROR: initializer never mentions outer x
```
- The reference may be ANY use of the shadowed name in the initializer
  expression (bare, `move x`, `x.copy()`, `f(x)`, nested) — the
  mention IS the declaration of intent. (Considered requiring the
  initializer to INVALIDATE the original (`move` only); decided the
  broader mentions-rule is enough — the mention already makes the
  redefinition obvious.)
- No initializer = no way to prove intent, so these shadows are flat
  ERRORS: `match`/`if let`/`guard let` PATTERN bindings that shadow an
  outer binding (`case Move(x, y)` under an outer `x` — the classic
  bind-when-you-meant-compare footgun; the error should note patterns
  bind, and suggest renaming), function PARAMS shadowing module-level
  names, closure params shadowing enclosing locals.
  EXCEPTION that stays legal by the main rule: `if let x = x` /
  `guard let x = x` — the scrutinee references the shadowed binding.
- Same-scope redefinition (`let x = 1; let x = 2` in ONE scope): if
  currently legal, same rule applies; if already an error, unchanged.
- Scope of "outer": any lexically enclosing binding a bare use of the
  name would resolve to (locals, params, captures, module statics).
  Prelude/std names are NOT bindings — `let print = 5` stays governed
  by existing rules, not this design.

## Diagnostics
`error: 'data' shadows the binding declared at FILE:L:C` +
`hint: rename it, or derive it from the original (e.g. \`let data =
parse(move data)\`) to make the redefinition explicit`. Pattern
variant: `hint: patterns bind new variables, they do not compare
against 'x' — rename the binding`. Positions must be exact (design 99
landed — interpolation sub-exprs included).

## Implementation sketch
Typechecker scope machinery: on binding introduction, look up the name
in enclosing scopes; if found, check whether the initializer expression
(already type-checked first) references that binding — a small
AST walk for Identifier nodes resolving to the shadowed symbol (before
the new binding is defined, any bare `x` in the initializer resolves to
the OUTER x — so "was the outer symbol read/moved in this init expr"
may already be derivable from use/move tracking). Pattern/param sites
error on plain name collision.

## Migration + tests
- BREAKING: sweep std/blade/libs/examples for now-illegal shadows;
  rename or derive each (report the count — it doubles as an audit of
  how common accidental shadowing was).
- Tests: each OK/ERROR form above (incl. `if let x = x` stays green,
  match-pattern shadow error, param shadow error, closure-param shadow
  error, derived let/var forms, `move`/`.copy()`/call-wrapped derivations,
  exact positions in both messages); suite stays green.
- Docs: LANGUAGE_SPEC.md (bindings section), saw-lang skill (rule +
  gotcha entry), tracker.

Bars: full suite + bootstrap green per commit; zero xfails. Standing
policy; foreground suites; interruption-safe; saw-lang skill
self-review. Sequencing: touches typechecker scope code — do NOT run
concurrently with design 93 (land after it).
