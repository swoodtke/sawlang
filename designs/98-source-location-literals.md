# Design 98 — `#file` / `#line` / `#function` source-location literals (queued Aug 2)

User request: debug prints need the call site —
`print("{#file}:{#line} - foobar")`. Today only panic/assert get a
location (the design-69 `panic at FILE:LINE: ` prefix, embedded by
codegen); interpolation has no magic constants.

## Decision (user-confirmed)
- Swift's spelling: `#file`, `#line`, `#function` — magic LITERALS,
  usable in any expression position (including interpolation).
- **Definition site**: each literal expands where the TOKEN literally
  appears in source. In a generic, that's the generic's own file/line
  (identical across monomorphizations); in a default argument, the
  default's definition site. No caller-site propagation (`#file`-as-
  default-argument capturing the CALLER, Swift's other mode, is OUT of
  scope — note it in the brief as a possible future design if wanted).

## Semantics
- `#file` -> `String` constant: the source file's BASENAME (match the
  design-69 panic prefix — same file, same spelling; not a full path,
  which would embed build-machine paths in binaries).
- `#line` -> `Int` constant: 1-based line of the token.
- `#function` -> `String` constant: the enclosing function/method's
  bare name (`init`, `main`, method name without struct qualifier —
  match what design-69 debug info uses); top-level/module scope ->
  the module init context name codegen already uses.
- All three are compile-time constants: no runtime cost, freestanding-
  safe, usable where any literal of that type is (const contexts,
  static initializers, default values — evaluated at their definition
  site per the decision above).

## Implementation sketch
1. Lexer: `#file`/`#line`/`#function` tokens (`#` currently unused at
   expression level — verify no collision with attributes like
   `@export`; error message for unknown `#foo`: "unknown directive").
2. Parser: expression atoms carrying their own source position.
3. Typechecker: resolve to String/Int literal nodes with the values
   filled from the token position + enclosing-function context —
   AFTER this pass they ARE ordinary literals (codegen untouched
   except that no special handling must strip them).
4. Coroutine transform: runs on SOURCE — ensure the transform does not
   re-print/re-parse these into wrong positions; if the transform
   round-trips source text, expand them BEFORE the transform or make
   the transform preserve original positions (check how design-69
   panic lines survive the transform — same mechanism).
5. `#line`/`#file` inside a suspending function body must report the
   ORIGINAL source line, not the transformed frame method's line —
   test this explicitly.

## Tests
- Basic: each literal in print interpolation matches the actual
  file/line/function (exact-match on a pinned-line test file).
- Inside: a method, a generic function (two instantiations — same
  values), a closure, a suspending function (post-transform original
  line), a default parameter value (definition site), top level.
- Error: unknown `#directive` diagnosed cleanly.
- panic/assert prefix unchanged.

## Docs
LANGUAGE_SPEC.md (literals section), saw-lang skill (debug-print
idiom), tracker.

Bars: full suite + blade/libs + bootstrap green per commit; zero
xfails. Standing policy; foreground suites; interruption-safe;
saw-lang skill self-review. NOTE: touches lexer/parser/typechecker —
do NOT run concurrently with design 82 (sequence after it lands).
