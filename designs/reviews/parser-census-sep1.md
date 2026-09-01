# Parser-port pre-freeze census — validated

Sweep agent, Sep 1 2026. Read-only: no tracked file changed. Every CLASS 1 /
CLASS 2 row below is backed by a direct `sawc.py` compile (and a run where the
answer is a value), with the exact diagnostic quoted. Probes live in
`/Users/shawn/Projects/sawlang/.build/scratch/census_*.saw`; the drivers are
`/Users/shawn/Projects/sawlang/.build/scratch/probe_census_run.py`,
`probe_census_brief.py`, `probe_gen_grammar.py`, `probe_gen_bisect.py`,
`probe_gen_bisect2.py`. No suite-shaped invocation was run.

**VERDICT.** The parser surface carries **9 confirmed CLASS 1 findings already
in the tracker plus 8 NEW ones found by fresh probing** — and the largest new
one is not a tracker item at all: **the Python parser has no recursion guard
and raw-tracebacks at 61 nested parens / 48 nested `if` blocks / 50 nested
closures**, escaping the ICE funnel entirely. Separately, **11 CLASS 2 findings
reproduce**, and four of them (DF-261d, DF-261e, DF-267c, DF-257a) sit directly
on the box-linked-recursive-enum + multi-module shape the port will be written
in. The freeze is not ready: the tracker's CLASS 1 set is incomplete.

---

## 1. Summary table

Legend: **VR** = verified-reproduces (probe run this session); **FIT** =
fixed-in-tree / does not reproduce; **OPEN** = could not determine, see §7;
**READ** = classified from the tracker entry alone (CLASS 3 only).

### CLASS 1 — ossifies into the contract

| # | Finding | Status | Tier | Note |
|---|---|---|---|---|
| 1 | DF-284b `{ ... }()` in any position | VR | silent wrong answer + parse error + wrong refusal | `let x = { 1 }()` compiles and DROPS the `()` |
| 2 | DF-266a leading-minus tail after `if { return }` | VR | ICE | and the dump shows the parser really builds `(if …) - 1` |
| 3 | DF-259c trailing closure inside a `try` operand | VR (pin still XFAILs) | wrong refusal | `try! v.map { … }` = field access |
| 4 | DF-172d binary-expression line wrapping, both spellings | VR | wrong refusal | plus the postfix-`.method()`-after-`)` third sighting |
| 5 | DF-259b reserved word in a declaration-name slot (5 slots) | VR | diagnostic-only | bare `Expected X name` at every slot |
| 6 | DF-215j `return` in a value match arm | VR | diagnostic-only | `Unexpected token: RETURN` |
| 7 | DF-215i no boolean `guard cond else { }` | VR | grammar gap | `Expected 'let' or 'var' after 'guard'` |
| 8 | DF-276a unrepresentable float literal degrades silently | VR | silent wrong answer | `inf` / `0.0`, no diagnostic — a LEXER-stage conversion |
| 9 | DF-270e primitive type as zero-arg call (`UInt8()`) | READ→CLASS 3 | — | parses fine; the ICE is downstream (see CLASS 3) |
| N1 | **parser recursion is unguarded — RAW PYTHON TRACEBACK** | VR | ICE (unfunneled) | 61 parens / 48 blocks / 50 closures / 500 `Box<>` / 1000 unary `-` |
| N2 | **`x as Int??` — the cast target changes with WHITESPACE** | VR | silent wrong answer | `Int? ??` → target `Int?`; `Int??` → target `Int` |
| N3 | **a bare trailing closure on a FREE function is not a call** | VR | wrong refusal | `run { 10 }` → `undefined variable run`; the method twin works |
| N4 | **`lend` is not an expression, so a value-match arm cannot lend** | VR | grammar gap | `case Leaf(n) -> lend n` = `Unexpected token: LEND` |
| N5 | **an unclosed `{` is NOT anchored at its opener** | VR | diagnostic-only | `(`/`[` are (design 129); `{` reports a token error lines later |
| N6 | **`.5` has no tailored diagnostic where `1.` does** | VR | diagnostic-only | `Unexpected token: DOT` |
| N7 | **an unterminated string reports at EOF, not at the opening quote** | VR | diagnostic-only | same doctrine gap as N5 |
| N8 | **a labelled call parses as `StructInit`, not `FunctionCall`** | VR | AST-shape decision | `h(b: 50)` dumps `StructInit h` — the dump format freezes this |

### CLASS 2 — blocks the implementation

| # | Finding | Status | Tier | Note |
|---|---|---|---|---|
| 10 | DF-261d Box payload-method forwarding misses ENUM payloads | VR | wrong refusal | **no Saw-level traversal of a box-linked AST** |
| 11 | DF-261e optional chain through a `Box<T>?` field | VR | ICE | `BindOptional lowered outside an optional chain` |
| 12 | DF-267c `lend` a place indexed into a MATCH-BOUND payload | VR | wrong refusal | blocks `Node.child(at:)`-shaped accessors |
| 13 | DF-257a qualified init spelling loses a DEFAULTED parameter | VR | wrong refusal | **blocks a multi-module parser** |
| 14 | DF-261c `==` on an enum ignores a hand-written `equals` | VR | **silent wrong answer** | `a == b` false, `a.equals(&b)` true |
| 15 | DF-248b residue nested closure captures outer `&var` by value | VR (pin) | **silent wrong answer** | pin compiles; prints `root 1`, expects `root 42` |
| 16 | DF-267a Optional method on a `borrows -> T?` result | VR | wrong refusal | `v.get(0).is_some()` refused |
| 17 | DF-250a collection literal through a `Result` Ok payload | VR | wrong refusal | `-> Result<Vector<Int>, E> { [1,2,3] }` |
| 18 | DF-270b `G<Alias>` at a `G<Underlying>` slot | VR | ICE | `type TokenKind = UInt8` is the parser's natural spelling |
| 19 | DF-270a alias literal rule differs by slot | VR | wrong refusal | `let x: Byte2 = 45` refused |
| 20 | DF-272a enum variant construction drops the closure param type | VR | wrong refusal | struct-init twin infers |
| 21 | DF-277a `E.from(raw:)` does not adopt a bare int literal | VR | wrong refusal | the backed-enum token-kind idiom |
| 22 | DF-257d `$0` inside a `try` operand | VR (pin) | wrong refusal | `undefined variable $0` |
| 23 | DF-259a `Box<any Trait>.make` has the other fallibility+signature | VR | wrong refusal | `takes exactly one positional value` |
| 24 | DF-215g bare `None` `==` a call's determined optional | VR | wrong refusal | — |
| N9 | **a dependency module's prelude-name collision is not reported** | VR | wrong refusal, nonsense message | entry twin says "ambiguous enum"; the dep says "has no variant" |
| N10 | **`as` at the same type BYPASSES the copy check → double free** | VR | **soundness / silent wrong answer** | `let w = v as Vector<Int>` compiles, traps (`SIGTRAP`, exit 133) |
| N11 | **a Saw-level recursion overflow is a bare `SIGSEGV`** | VR | crash, no diagnostic | recursion depth 1e5 fine, 1e6 segfaults |
| N12 | **deep-drop stack exhaustion**: a Box chain segfaults on drop | VR | crash, no diagnostic | fine at 250 000, `SIGSEGV` at 300 000 |
| 25 | DF-215h no newline-free stdout write | READ (surface absent) | ergonomic | a dumper prints one line per piece |

### CLASS 3 roster — see §5

---

## 2. CLASS 1 — the repros

### 1. DF-284b — the immediately-invoked closure, three faces (VERIFIED)

`.build/scratch/census_284b_stmt.saw`, `census_284b_arg.saw`,
`census_284b_let.saw`.

```
$ sawc census_284b_stmt.saw       ->  { print("hi") }()
error: closure literal is never called: `{ ... }` in statement position builds a
closure and discards it, so its body does not run
  hint: call it — `{ ... }()` — or bind it (`let f = { ... }`).

$ sawc census_284b_arg.saw        ->  print({ 2 }())
error: Parse error at 2:16: Expected RPAREN, got LPAREN

$ sawc census_284b_let.saw        ->  let x = { 1 }()  ... print("{}", x())
[compile rc=0]
bound something
1
```

The `let` face is the one that matters: it COMPILES, binds the closure, drops
the `()`, and `x()` then prints `1` — a silently different program.
**Tier: silent wrong answer.** The diagnostic in face 1 names a spelling the
parser refuses in face 2, so the language documents a form it does not have.

### 2. DF-266a — leading-minus tail after a closed block (VERIFIED, ICE)

`.build/scratch/census_266a.saw` / `census_266a_let.saw`.

```
error: internal compiler error at .../census_266a.saw:5:5 (BinaryOp):
'NoneType' object has no attribute 'type'
```

The `let`-preceded control compiles and prints `-1`. **New evidence the tracker
does not have:** `tools/dump_ast.py` PARSES the ICE file successfully and dumps

```
Function h(b: Int) -> Int {
  final_expr:
    BinaryOp(-)
      left:
        IfExpr ...
      right:
        IntLiteral(1) : Int
```

so this is a *parse-shape* accident, not a typecheck accident — the port would
freeze `if {…}` NEWLINE `-1` as a subtraction. **Tier: ICE, over a wrong parse.**

### 3. DF-259c — trailing closure inside a `try` operand (VERIFIED; pin still XFAILs)

`.build/scratch/census_259c.saw` and the in-tree pin
`/Users/shawn/Projects/sawlang/examples/trailing_closure_inside_a_try_operand.saw`,
compiled directly:

```
error: struct `Vector` has no field `map`
 42 |     let labels = try! jobs.map { j in j.label() }
   hint: available fields: buffer, length, capacity
error: closure literal is never called: `{ ... }` in statement position ...
error: undefined variable `labels`
```

Pin is live. **Tier: wrong refusal.**

### 4. DF-172d — binary-expression wrapping, both spellings + the postfix face (VERIFIED)

`.build/scratch/census_172d_leading.saw`, `census_172d_trailing.saw`,
`census_172d_postfix.saw`.

```
leading  `| ATTR` on the next line  -> Parse error at 4:11: Unexpected token: PIPE
trailing `... |` then newline       -> Parse error at 3:27: Unexpected token: NEWLINE
Holder(\n  n: 5)\n  .show()        -> Parse error at 14:7: Unexpected token: DOT
```

All three of the tracker's cells confirmed, including the third-sighting
postfix note (todo.md:2203). **Tier: wrong refusal.**

### 5. DF-259b — reserved word in a declaration-name slot (VERIFIED, five slots)

| probe | diagnostic |
|---|---|
| `struct None { n: Int }` | `Parse error at 1:8: Expected struct name` |
| `func None() -> Int` | `Parse error at 1:6: Expected function name` |
| `struct Box2 { None: Int }` | `Parse error at 2:5: Expected field name` |
| `enum G { case true … }` | `Parse error at 2:10: Expected variant name` |
| `enum Chosen { … case None }` | `Parse error at 3:10: Expected variant name` |

Not one message names the token it actually got. **Tier: diagnostic-only.**
NOTE the scheduling interaction: **design 258 introduces a CONTEXTUAL `private`
keyword** and the tracker's ancient DF5 ("keywords can't be identifiers … an
eventual contextual-keyword sweep is noted", todo.md:9430) is the same surface.
Both change the reserved set the port would freeze.

### 6. DF-215j — `return` in a value match arm (VERIFIED)

`.build/scratch/census_215j.saw` / `census_215j_braced.saw`.

```
case 0 -> return 7,          -> Parse error at 3:19: Unexpected token: RETURN
                                Parse error at 6:5: Expected import, export, module, ...
case 0 -> { return 7 },      -> compiles, prints 7
```

Note the *second* cascaded error, which points at a line with nothing wrong
with it — the recovery makes the real error harder to find, not easier.
**Tier: diagnostic-only.**

### 7. DF-215i — no boolean `guard cond else { }` (VERIFIED)

`.build/scratch/census_215i.saw`:
`Parse error at 2:11: Expected 'let' or 'var' after 'guard'`.
**Tier: grammar gap.** Classified CLASS 1 rather than CLASS 2 because it is a
missing PRODUCTION, which is exactly what the port freezes; its cost to the
implementation (every bounds check becomes an inverted `if`) is real but
secondary.

### 8. DF-276a — an unrepresentable float literal degrades silently (VERIFIED)

`.build/scratch/census_276a.saw` (a 1-followed-by-~330-zeros `.0`, and its
underflow twin) compiles clean and RUNS:

```
over = inf
under = 0.0
```

The integer control `.build/scratch/census_276a_control.saw` is a clean located
refusal (`integer literal 300 does not fit in UInt8 (range 0..=255)`). This is a
LEXER/literal-conversion-stage fact and therefore squarely on the frozen
surface. **Tier: silent wrong answer.**

### N1 — NEW, and the biggest: the parser has no recursion guard

Generated probes; thresholds bisected one at a time
(`probe_gen_bisect.py`, `probe_gen_bisect2.py`). Every failure below is a
**raw Python traceback on stderr**, ~2 100–2 200 lines, NOT an
`internal compiler error at FILE:LINE` — i.e. it escapes the ICE funnel and
violates `tools/sawfuzz.py`'s single oracle ("a traceback … is a finding").

| shape | last OK | first FAIL | failing frame |
|---|---|---|---|
| `((((…1…))))` | 60 | **61** | `parser/expressions.py:282 parse_unary` |
| `if true { … }` nested | 47 | **48** | `parser/expressions.py:202 parse_shift` |
| `[[[[…1…]]]]` | 60 | 80 (not bisected finer) | parser |
| `{ { { … } } }` closures | — | **50** | `parser/expressions.py:177 parse_range` |
| `Box<Box<…Int…>>` | 200 | 500 | parser (type path) |
| `-` unary repeated | 100 | 1000 | `parser/core.py:271 _skip_suppressed_newlines` |
| `1 + 1 + … + 1` | 200 | 500 | **clean**: `internal compiler error at …:2:691 (BinaryOp): maximum recursion depth exceeded` |

Exact text at the paren boundary:

```
  File ".../sawc/parser/expressions.py", line 282, in parse_unary
    if self.match(TokenType.MINUS):
       ~~~~~~~~~~^^^^^^^^^^^^^^^^^
RecursionError: maximum recursion depth exceeded
```

Two facts the lead needs:

* the **binop** row shows the TYPECHECKER's recursion IS funnelled into a
  located ICE, while the **parser's** is not — so this is a missing wrapper at
  one place, not a language-wide gap. No `sys.setrecursionlimit` call exists
  anywhere in `sawc/` or `tools/` (`grep`, whole tree).
* `tools/dump_ast.py` inherits it: on `census_deep_paren_100.saw` it emits the
  same traceback, which `tools/astdiff.py` classifies as `crash` — its
  three-way `ok` / `parse-error` / `crash` split exists for exactly this.

**Why this is CLASS 1 and not merely a bug:** 48 nested blocks is inside the
range machine-generated Saw hits, and the port in Saw will have a completely
different limit (native 8 MB stack). Whatever the port does, "matches the
Python parser's stack" is not a contract anyone can write down. The lead has to
RULE a depth limit before the freeze, not discover the divergence in astdiff.

### N2 — NEW: the `as` cast target changes meaning with WHITESPACE

`.build/scratch/census_qq_cast.saw`, `census_qq_cast_nospace.saw`,
`census_qq_cast_spaced.saw`, `census_qq_cast_two_layer.saw`.

```
n as Int? ?? 9   -> error: cannot cast `Int` to `Int?`          (target = Int?)
n as Int?? 9     -> error: left side of `??` must be optional, got `Int`
                                                                 (target = Int !)
n as Int? ?      -> error: cannot cast `Int??` to `Int??`        (target = Int??)
n as Int??       -> Parse error at 8:23: Unexpected token: NEWLINE
```

The lexer emits `??` as ONE token, so the type grammar can never consume it in
a cast target: with a space the reader gets `Int?`, without a space the reader
gets `Int` and a coalesce, and `Int??` as a cast target has **no spelling at
all** (`as Optional<Int?>` reaches it, but only through the generic name).
LANGUAGE_SPEC.md:1908-1913 documents the operator-wins exception and says
"types nested inside a cast target are unaffected" — it does not document that
the SPACING decides. **Tier: silent wrong answer** (the no-space form compiles
in any context where `Int` is already optional).
Confirmed the type-annotation position is unaffected:
`let a: Int?? = None` compiles (`census_qq_type_layers.saw`).

### N3 — NEW: a free function's bare trailing closure is not a call

`.build/scratch/census_trailing_matrix.saw`. Three rows, one file:

```
A  runtag(tag: 5) { 10 }        free fn, paren list then brace   -> OK
B  Box2(n: 1).with { 10 }       method, bare brace               -> OK
C  run { 10 }                   free fn, bare brace              -> FAILS
```

Row C:

```
error: undefined variable `run`
 22 |     let r = run { 10 }
error: closure literal is never called: `{ ... }` in statement position ...
```

The in-tree example `examples/labeled_args_trailing_closure.saw` covers row A
only. **Tier: wrong refusal**, with a diagnostic that names the wrong thing
(`run` is a function, not an undefined variable).

### N4 — NEW: `lend` is a statement, so a value-match arm cannot lend

`.build/scratch/census_267c.saw`, first version:

```
case Leaf(n) -> lend n,
Parse error at 26:29: Unexpected token: LEND
  + two cascaded "Expected import, export, module, ..." errors
```

Bracing the arm (`case Leaf(n) -> { lend n }`) parses. Design 146d's
"a borrowing `match` arm may lend its PAYLOAD binding" therefore has exactly
one spelling. **Tier: grammar gap** (arguably intended — the lead rules) with
a diagnostic that cascades two lines of noise.

### N5 / N6 / N7 — NEW: three diagnostic asymmetries on the frozen surface

```
census_unclosed_nested.saw   let x = ( 1 + [ 2, ( 3 + 4 ) ].len()
  -> Parse error at 4:13: unclosed `(` — no matching `)` before the end of the
     file (a line break inside brackets does not close them)      GOOD, anchored
     at the OUTERMOST unclosed opener, three deep.

census_unclosed_brace.saw    an unclosed `{` inside func a()
  -> Parse error at 6:1: Unexpected token: FUNC                   N5: no anchor,
     reported on the NEXT function's line.

census_float_trailing_dot.saw  let x = 1.
  -> Parse error at 2:15: Expected field name or tuple index after '.', got
     NEWLINE — a float literal needs a digit after the point (write `1.0`)  GOOD
census_float_leading_dot.saw   let x = .5
  -> Parse error at 2:13: Unexpected token: DOT                   N6: bare.

census_string_unterminated.saw  let a = "no closing quote
  -> Lexer error at 5:1: Unterminated string                      N7: EOF, not
     the opening quote (contrast the `(` rule above).
```

`census_string_bad_escape.saw` is the good case and stays good:
`Lexer error at 2:32: unknown escape \q in a string literal (supported: \\ \" \n \t \r \0 \u{...})`.
**Tier for all three: diagnostic-only.**

### N8 — NEW (contract shape, not a bug): a labelled call dumps as `StructInit`

`tools/dump_ast.py .build/scratch/census_215j_braced.saw`:

```
      FunctionCall print()
        arg[1]:
          StructInit f
            n:
              IntLiteral(0) : Int
```

`f(n: 0)` — a call to a FUNCTION with a labelled argument — is parsed as a
`StructInit` and only resolved in the typechecker. The port must reproduce
this or the dumps diverge on a large fraction of the corpus. It is not a
defect; it is a **decision the freeze makes permanent**, and it belongs in the
ruling list beside the depth limit. (`FunctionCall` is reserved for the
positional/builtin form — `print()` above.)

### Grammar shapes probed and found FINE (negative controls)

Recorded so the port's test plan can inherit them.

| probe | result |
|---|---|
| `census_tuple_index.saw` `t.0.0`, `t.0.1`, `t.1` | prints `1 2 3` — design 161 holds |
| `census_newline_in_generic.saw` newline inside `<A, B>` | compiles, runs |
| `census_newline_nested_generic.saw` newline in a NESTED `<>` at depth | compiles, runs |
| `census_generic_shift.saw` `Vector<Vector<Vector<Int>>>` + `a < b`/`b > c` | compiles, `true false` |
| `census_lt_ambiguity.saw` `a < b` beside `f<Int>(x: 5)` | compiles |
| `census_unclosed_angle.saw` `Vector<Vector<Int> = []` | `Expected '>' after type arguments` — clean |
| `census_many_arms_100/1000.saw` a match with 1000 arms | compiles, runs |
| `census_long_postfix.saw` 40 chained `.step()` | prints `40` |
| `census_long_optchain.saw` 4-hop `?.` chain + `??` | prints `-1` |
| `census_interp_nested.saw` `"nested: {"inner {a}"}"` | prints `nested: inner 1` |
| `census_interp_expr.saw` `{if a > 0 { 1 } else { 2 }}` in a string | prints `1` |
| `census_unicode_ident.saw` `café`, `π` as identifiers | prints `4` |
| `census_string_escapes.saw` `\t \" \\ \{ \n` and a trailing `\\` | all correct |
| `census_comment_in_brackets.saw` `//` inside `()` and `[]` with trailing commas | compiles |
| `census_labeled_multiline.saw` decl + call + init, each spanning lines with trailing commas | prints `3` |
| `census_doc_edges.saw` `///` before a non-declaration | `doc comment is not followed by a documentable declaration` — clean |
| `census_doc_trailing.saw` `///` at EOF | same clean message |
| `census_range_inclusive.saw` `1..3` and `1..=3` | `a 1 a 2` / `b 1 b 2 b 3` |
| `census_range_vs_float.saw` `1...3` | `Expected LBRACE, got ELLIPSIS` — `...` is not a range |
| `census_qq_nested_cast.saw` `v as Vector<Int?>` | **parses fine, but see N10** |

---

## 3. CLASS 2 — the repros

### 10. DF-261d — `Box` forwarding reaches struct payloads, not enum payloads

`.build/scratch/census_261d.saw` (both halves in one file):

```
error: type `Box` has no method `rank`
 27 |     print("{}", t.rank())
   hint: available methods: deinit, make, value
```

The struct twin `b.twice()` on a `Box<Leafy>` in the same file produced no
error. **This is the finding that removes Saw-level traversal from a
box-linked recursive enum — i.e. from the parser's own AST.**

### 11. DF-261e — optional chain through a `Box<T>?` field is an ICE

`.build/scratch/census_261e.saw`:

```
error: internal compiler error at .../census_261e.saw:19:18 (BindOptional):
BindOptional lowered outside an optional chain
```

`self.slot?.twice() ?? 0` on a `slot: Box<Leafy>?`. **`Box<Node>?` is the
natural spelling of an optional child.**

### 12. DF-267c — cannot `lend` into a match-bound payload

`.build/scratch/census_267c.saw` (control in the same file, plus
`census_267c_control.saw` alone):

```
error: cannot open an exclusive place window on immutable variable `kids`
 27 |             case Branch(kids) -> { lend kids[at] }
   hint: consider using `var` instead of `let` to make it mutable
```

The field-projection control `lend self.cells[i]` compiles and prints `2`.
**This is `Node.child(at:)`.**

### 13. DF-257a — a qualified init spelling loses a DEFAULTED parameter

`.build/scratch/census_257a_bare.saw` vs `census_257a.saw` +
`.build/scratch/censusmod4/lib.saw` (`--module-path lex=…`):

```
bare      Token(k: 1)       -> compiles, prints `bare with default omitted: 0`
qualified lex.Token(k: 1)   -> error: no matching initializer for `Token` with
                                      parameters: k
                               hint: field init expects: kind, line;
                                     available init methods: [['k', 'ln']]
```

**A parser split into `lex` / `ast` / `parse` modules hits this the moment any
constructor has a default.**

### 14. DF-261c — `==` on an enum ignores a hand-written `equals` (SILENT)

`.build/scratch/census_261c.saw`, compiled and RUN:

```
equal? false
direct? true
```

### 15. DF-248b residue — a nested closure loses a write through an outer `&var` (SILENT)

The in-tree pin `/Users/shawn/Projects/sawlang/examples/closure_nested_ref_param_capture.saw`
compiles clean and runs:

```
actual:   explicit borrow capture: root 42 / argument face: root 1  / shared read: root 1 saw 1
expected: explicit borrow capture: root 42 / argument face: root 42 / shared read: root 1 saw 1
```

My own three-shape probe `.build/scratch/census_248b.saw` hit a DIFFERENT and
correct refusal (an escaping closure may not capture a `&var`), so the pin is
the authority; recorded here so nobody re-derives the wrong minimal repro.

### 16. DF-267a — an Optional method on a `borrows -> T?` result

`.build/scratch/census_267a.saw`:

```
error: type `Int` has no method `is_some`
   hint: available methods: abs, clamp, is_even, is_odd, max, min, pow, signum
error: argument `__window` expects `(&var Int) sync -> Bool` but got `(&var Int) -> Void`
```

Control `census_267a_control.saw` (`if let _ = v.get(0)`) prints `present`.

### 17. DF-250a — a collection literal does not shape through a `Result` Ok

`.build/scratch/census_250a.saw`:

```
error: function `wrapped` should return `Result<Vector<Int, GlobalAllocator>, String>`
but returns `[Int; 3]` (doesn't match Ok type `Vector<Int, GlobalAllocator>` or
Err type `String`)
```

The bare `-> Vector<Int> { [1,2,3] }` twin in the same file compiles.
**A parser's every function returns `Result<_, ParseError>`.**

### 18. DF-270b — `G<Alias>` at a `G<Underlying>` slot is an ICE

`.build/scratch/census_270b.saw` (`type TokenKind = UInt8`):

```
error: internal compiler error at .../census_270b.saw:10:17 (StructInit):
Type of #1 arg mismatch: %"Vector$2$UInt8$GlobalAllocator"* !=
%"Vector$2$TokenKind$GlobalAllocator"*
```

`census_270b_let.saw` — the `let`-slot cell the entry calls "silently accepted"
— compiles and runs, confirming both directions.

### 19. DF-270a — the alias literal rule differs by slot

`.build/scratch/census_270a.saw`: `static A: Byte2 = 45` is accepted;
`let x: Byte2 = 45` is `error: cannot assign UInt8 to variable of type Byte2`.

### 20. DF-272a — an enum variant construction drops the closure param type

`.build/scratch/census_272a.saw`:

```
error: Cannot infer type for closure parameter `c`. Add type annotation: `c: Type`
 15 |     let h = Holder.Handler(f: { c in c + 1 })
```

The struct-init twin `FnField(f: { c in c + 1 })` on line 13 produced no error.

### 21. DF-277a — `E.from(raw:)` does not adopt a bare integer literal

`.build/scratch/census_277a.saw`:

```
error: `Tag.from` expects `UInt8` (the enum's backing type), got `Int`
   hint: write the conversion: `as UInt8` panics out of range, ...
```

`takes(x: 9)` at a `UInt8` parameter, three lines up, adopts. **A backed enum
is the token-kind idiom.**

### 22. DF-257d — `$0` inside a `try` operand

The pin `/Users/shawn/Projects/sawlang/examples/closure_shorthand_parameter_inside_a_try.saw`:

```
error: undefined variable `$0`
 36 |     run({ print("forced {try! fallible($0)}") })
error: argument `body` expects `(Int) -> Void` but got `() -> Void`
```

**Correction to the tracker's shorthand:** my first three minimal shapes
(`try! v.map<Int>({ $0 + 1 })` and two twins,
`.build/scratch/census_257d*.saw`) all COMPILE and RUN. The finding needs the
`try` to sit inside a closure whose PARAMETER is the `$0`, which only the pin
has. Anyone re-minimizing this will otherwise conclude it is fixed.

### 23. DF-259a — `Box<any Trait>.make` has the other signature

`.build/scratch/census_259a.saw`:

```
error: `Box<any Trait>.make(...)` takes exactly one positional value
 15 |     let erased = Box<any Shape>.make(value: Sq(s: 4))
```

The concrete `try! Box<Sq>.make(value:)` on line 13 is fine. Two fallibilities
AND two calling conventions behind one method name.

### 24. DF-215g — bare `None` `==` a call's determined optional

`.build/scratch/census_215g.saw`:

```
error: cannot tell what this `None` is a `None` OF — no annotation, parameter,
field, return type or element type in scope fixes its payload type
  9 |     print("call: {}", find_thing(n: 5) == None)
```

The annotated-local twin one line up compiles.

### N9 — NEW: a dependency module's prelude-name collision is not reported

`.build/scratch/censusmod3/lib.saw` declares `enum JsonValue { case Null, case Num(n: Int) }`
and `census_modcollide.saw` imports it (`--module-path dep=…`):

```
error: enum `JsonValue` has no variant `Num`
 11 |         JsonValue.Num(n: k)
error: method `make` should return `JsonValue` but body has no value
```

The ENTRY-file twin (`.build/scratch/census_enum_variant_min.saw`, same enum in
the entry file) gets the right report:

```
error: ambiguous enum `JsonValue`: defined in both `<builtins>` and `<entry>`
   hint: rename one definition, or import `JsonValue` from a single module
```

So inside a dependency the name silently resolves to the BUILTIN and the author
gets a nonsense message about their own declaration. This is DF-280b's family
(a recorded collision that is never reported) at the DEPENDENCY position, and
it will bite a parser port whose `ast` module names anything std also names.

### N10 — NEW, SOUNDNESS: `as` at the same type bypasses the copy check

`.build/scratch/census_as_copy_bypass.saw` vs `census_as_copy_control.saw`:

```
let v: Vector<Int> = [1, 2, 3]
let w = v as Vector<Int>      -> compiles; prints 3 / 3; then Trace/BPT trap: 5
                                 (exit 133)
let w = v                     -> error: cannot copy value of type
                                 `Vector<Int, GlobalAllocator>` which implements
                                 ExplicitCopy
                                 hint: use .copy() ... or `move` ...
```

Two owners of one buffer, a double free at scope exit. Found by accident while
probing the `??`/`as` grammar boundary (`census_qq_nested_cast.saw`, same trap).
This is **exactly DF-216a's named mechanism** — "the comparison operators are
one of several compiler-synthesized call constructions that skip
`_check_value_transfer`" — with `CastExpr` as another member. It is not a
parser finding; it is reported here because the sweep found it and it outranks
most of the list.

### N11 / N12 — NEW: stack exhaustion has no diagnostic at either level

```
census_saw_recursion.saw     down(n:) at 10 000 -> 10000
                                        100 000 -> 100000
                                      1 000 000 -> SIGSEGV (rc -11), no output
census_deepdrop2.saw   build+drop a Box<Chain> chain
      1 000 / 10 000 / 50 000 / 200 000  -> built + dropped
      1 000 000                          -> "built 1000000" then SIGSEGV
census_deepdrop3.saw   250 000 -> built + dropped;  300 000 -> SIGSEGV on DROP
```

Design 246's warning ("destruction recurses to data depth") is confirmed, with
the threshold between **250 000 and 300 000** on macOS's 8 MB main-thread stack.
A recursive-descent parser in Saw is well under both thresholds for any real
file, so **CLASS 2, low severity** — but the failure mode is a bare `SIGSEGV`
with no message, which is what a self-hosted compiler would show a user who
feeds it a pathological file. It pairs with N1: whatever depth limit the lead
rules for the parser must be enforced by the PARSER, because neither the
language nor the runtime will catch the overflow.

---

## 4. CLASS 2, surface-absent (no probe possible)

### 25. DF-215h — no newline-free stdout write

`print` appends `\n` unconditionally and no std surface exposes a raw stdout
handle. Verified by reading the prelude roster in CLAUDE.md's digest and by the
absence of any alternative in `.build/scratch/census_215h.saw`'s available
surface. A Saw AST dumper builds whole lines anyway (`ast_dump.py`'s format is
line-oriented), so this is an ergonomic tax on the port's tooling, not a
blocker. **No probe can prove a negative here beyond "no such name exists"; I
did not exhaustively enumerate std, so this row is READ, not VR.**

---

## 5. CLASS 3 roster — cannot be written into a parser port

One line each, classified from the tracker entry (these rows claim nothing
about current behaviour, per the evidence bar).

**Concurrency / coroutine transform** — a parser is sync throughout:
- **DF-258a** nested unconditionally-suspending generic loses its yield.
- **DF-251d** a suspending `init` body is an ICE.
- **DF-252a** calling a `FuncPointer` by name inside a DRIVEN body is an ICE.
- **DF-261f** a directly recursive SUSPENDING function loops the coro transform.
- **DF-262b** suspending interpolation + `Task.spawn` + auto-wrap is an LLVM ICE.
- **DF-242a** a driven `try {} catch {}` releases frame fields at teardown.
- **DF-218w residue** the mixed `case Both(v, _)` arm keeps statement-end timing.
- **DF-255a** an escaping closure consuming its `move` capture double-frees.
- **DF-223b** existential dispatch of a suspending trait method (owed a design).
- **DF-224a/b** silent hangs on the main task's wake path.
- **EXEC-1** cross-poller one-shot consumption (VERIFY).
- **Cooperative brace sugar** (`Task.spawn { }`) — design 242's held piece.

**Monomorphization / codegen internals:**
- **DF-285b** the pristine template store is empty in an entry compile.
- **DF-285c** stage 3's splice-all fails §5's acceptance test by ~8x.
- **Design 218 unit 1.5 stages 3-5** — the phase itself.
- **DF-247a** a `group.spawn` root is `undefined function` elsewhere.
- **DF-251b** a generic extension's `init` registers no param cleanups.
- **DF-251c** DF-216h's extension-param rename misses an `init`.
- **DF-218t** a value-position loop at a non-integer result type ICEs.
- **DF-250b** `??` with a bare `None` default at a non-optional peel is an LLVM ICE.
- **DF-270c** a conformance body naming the underlying where the trait names the alias.
- **DF-270e** `UInt8()` / `Int()` zero-arg is an ICE — **parses cleanly**, so the port freezes nothing here.
- **DF-264a** a `deinit(&self)` inside `@synthesize Copy` reaches codegen.
- **DF-259a-adjacent** design 219 tier machinery.
- **DF-225o** `reemit` divergence under load.

**Builtins-vs-user-file checking divergence** (std-only, and the port is a user
file — but see §7 if the port ever lands under `sawc/std/`):
- **DF-271a** a `try` statement in a match in a while in a generic method, std only.
- **DF-272c** a maybe-suspending call inside a place window, std only.
- **DF-267d** dissolved-pending-confirmation.

**Typechecker rules with no parse-surface face:**
- **DF-242c** a suffixed literal does not disambiguate an overload set.
- **DF-269a** a label-selected overload loses bare-literal width adoption.
- **DF-276b** there is NO `Int` → `Float` conversion in any spelling.
- **DF-276c** a value `if`/`match` of bare literals does not adopt a neighbour's width.
- **DF-283c** a const expression over unsigned operands folds in the signed domain.
- **DF-280b** a prelude-name collision is recorded and not reported (**but see N9 — its dependency-position face is CLASS 2**).
- **DF-275a** an alias satisfies a bound through a receiver and not a free function.
- **DF-272b** a bare all-defaulted generic gets no design-37 fill (**see §7 — not reproduced**).
- **DF-273a** a qualified static call on an ENUM (**see §7 — NOT REPRODUCED, likely fixed**).
- **DF-257b** `Vector.try_copy` naming ruling.
- **DF-259a** — no, this is CLASS 2 (§3 row 23).
- **DF-232f re-narrowing rider**, **`public(package) import`** — visibility design work.

**Runtime / platform / harness / SOS / process:**
- **DF-256b** the thread control block's deallocation size.
- **DF-242d** conformance row K90's bounded GO spin.
- **DF-248c residue** the `XFAIL-EXPECT:` discriminator (a RUNNER change).
- **DF-226b/c** FuncPointer v1 gaps.
- **DF-215h** — no, CLASS 2 §4.
- **Design 231** native-compiler readiness ledger; **design 248** the linter;
  **design 243** trailing-brace call syntax; **blade out-of-tree target
  plugins**; **M4 seeds**; **ESP32 path**; **SOS M3 / kcore split / design 178
  M2 units**; **design 214 Raft**; **design 216 Copy-bound proposal**;
  **design 222 / 223 briefs**; **design 220 / 126b set-iteration lane**;
  **std.serde derived `Map` encoding**; **D10 Cortex-M0 atomics**; **B4 git-dep
  lock**; **L2 return-type reconciliation**; **DF4 blade bit-rot**.

**Scheduling interactions the lead should note (not findings):**
- **Design 258** adds a CONTEXTUAL `private` keyword — a grammar change landing
  into a frozen parser. Same surface as **DF5** ("keywords can't be
  identifiers … an eventual contextual-keyword sweep is noted", todo.md:9430)
  and as **DF-259b** above.
- **Design 245 v1** (`Scalar`) has literals + patterns as LATER units — a
  future lexer/grammar change.
- **Design 243** (trailing-brace call syntax) is a grammar change, backlogged.

---

## 6. The astdiff contract

Read: `/Users/shawn/Projects/sawlang/tools/astdiff.py` (126 lines),
`/Users/shawn/Projects/sawlang/tools/dump_ast.py`,
`/Users/shawn/Projects/sawlang/sawc/ast_dump.py` (1168 lines),
`/Users/shawn/Projects/sawlang/docs/AST_DUMP.md`. Exercised directly on three
probe files.

**(a) What it dumps.** SHAPE ONLY, plus literal values and a few names — never
diagnostics, never types-as-resolved, never positions. Concretely:

* Producer is `tools/dump_ast.py`, which is **lex + parse only** — no
  typecheck, no builtin/std merge, no module resolution. (`sawc --emit-ast` is
  the *other* producer and is explicitly NOT the oracle.)
* Node headers name the class (`BinaryOp(-)`, `IntLiteral(0) : Int`,
  `Function main() -> Void`), children go under label lines (`condition:`,
  `body:`, `arg[0]:`), two spaces per level.
* **`line`/`column` are carried by every node and NEVER printed** — the token
  dump pins positions, and repeating them would churn the dump on unrelated
  edits (AST_DUMP.md, "Positions are not in the dump").
* **`node_id` is excluded** unless `--ids` is passed; the doc says a second
  parser "has no reason to reproduce" construction-order ids.
* Type names are SHORT; design 144's defining module is a separate
  ` module=<tag>` header field, **absent for the entire current corpus**
  because the oracle parses one file with no module context. A port that never
  emits `module=` matches byte-for-byte today.
* Types render through `SawType.__repr__`, not through a dumper arm — the one
  place the format delegates outside `ast_dump.py`.
* Six node classes in the inventory (`OptionalWrap`, `ResultOkWrap`,
  `ResultErrWrap`, `ErasedErrWrap`, `EnumInit`, `OptionalChain`) are
  **typechecker-inserted and never appear in the oracle's dump**.
* A dispatcher miss is emitted as a record, not raised:
  `UNKNOWN<TAB><dispatcher>:<ClassName>`, and `astdiff` fails on any.

**(b) Are error-path files in the corpus?** YES, deliberately, and they are
first-class. `tools/astdiff.py` sweeps `git ls-files '*.saw'` — every tracked
`.saw`, `examples/errors/` included. A file that does not lex or parse emits
exactly one record and nothing else:

```
ERROR<TAB>line:col<TAB>message
```

AST_DUMP.md: "**Positions and the fact of rejection are part of the contract;
message prose is not** (the harness compares the tag and position, as lexdiff
does)". It records 26 of 1149 tracked files as rejected, every one carrying an
`// EXPECT: error` directive. Only the FIRST error is recorded — the parser's
recovery mode can report several and `dump_ast.py` deliberately keeps one.
Verified live: `dump_ast.py census_266a.saw` exits 0 with a full tree (that
file's failure is downstream of the parser), while
`dump_ast.py census_deep_paren_100.saw` produces a raw traceback, which
`astdiff` classifies `crash` via its third status.

**(c) Deterministic by construction or by luck?** **By construction, and
verified by measurement.** `ast_dump.py`'s docstring states it: "Field order is
fixed by hand-written emit sequences, and nothing address-like reaches the
output." The one `set` in the dumper (`self._tagged_lines: set[int]`) is
membership-tested, never iterated into output. On top of that, `astdiff` dumps
each file TWICE in fresh processes under `PYTHONHASHSEED=1` and `424242`
(deliberately not `0`, "that would DISABLE hash randomization and mask what (b)
looks for") and byte-compares.

**What this decides for the lead.** The tool has already chosen **BYTE parity
on the success path and VERDICT-plus-POSITION parity on the error path.** The
port owes byte-identical trees for every parsing file, and for every rejecting
file owes only the same `line:col` and the fact of rejection — message prose is
explicitly free. Two consequences worth ruling before dispatch:

1. Message prose being free means **every diagnostic-only CLASS 1 row above
   (DF-259b, DF-215j, N5, N6, N7) is invisible to astdiff** — the port could
   reproduce or improve them and the oracle would not care. So those rows must
   be fixed or ruled on their own merits, not left to the harness.
2. **The `line:col` of a refusal IS frozen.** N1 (parser recursion) therefore
   matters twice: a Saw port with a different depth limit produces a different
   verdict on a deep file, and a crash is not an `ERROR` record at all.

---

## 7. OPEN cells — what I tried

| Cell | What I tried | Why it is OPEN |
|---|---|---|
| **DF-273a** (qualified static call on an ENUM) | two shapes, both cross-module with `--module-path`: `.build/scratch/censusmod/lib.saw` + `census_273a_mod.saw` (plain enum + struct control), and `.build/scratch/censusmod2/lib.saw` + `census_273a_mod2.saw` (a `Box`-recursive `NoCopy` enum with a fallible `parse`, the entry's own shape) | **BOTH COMPILE AND RUN** (`3`, and `struct static via qualifier: 0 / enum static via qualifier: 7`). Likely FIXED IN TREE by design 249/255. I could not reconstruct a failing cell; the entry names no probe file, so I cannot rule out a shape I did not try. Recommend the lead re-probe with the original `std.json` spelling before closing. |
| **DF-272b** (bare all-defaulted generic gets no design-37 fill) | `.build/scratch/census_270b.saw`'s sibling `census_272b.saw`: `struct Arena<A: Allocator = GlobalAllocator>` referenced BARE as `&Arena` in a parameter | compiles and runs (`1`). The entry says "`_resolve_type` skips design 37's default fill entirely when a written type has NO type arguments"; my parameter-position cell does not show it. Needs the entry's own repro (which the entry does not carry — it points at "the DF-267b sweep"). |
| **DF-257d** minimal repro | three shapes (`census_257d.saw`, `_control.saw`, `_try.saw`) | all three COMPILE AND RUN. The finding reproduces only at the PIN's shape (a `try` inside a closure whose parameter is `$0`) — recorded in §3 row 22 so the next reader does not conclude it is fixed. |
| **DF-248b residue** minimal repro | `census_248b.saw`, a two-level nested closure over a `&var` parameter | hit a DIFFERENT, correct refusal ("an escaping closure cannot capture `n`, a reference"). The pin is the authority and it reproduces; my minimization does not. |
| **DF-267d / DF-271a / DF-272c** (builtins-vs-user-file divergence) | not probed | reproducing them requires EDITING `sawc/std/`, which is a tracked path. Out of scope for a read-only sweep. They are CLASS 3 **on the assumption the port lands under `selfhost/`, not `sawc/std/`** — if that assumption is wrong they all become CLASS 2 blockers, since a parser is self-recursive, walks a `Map`, and calls through closure APIs. **This is the single assumption in the census the lead should confirm.** |
| Deep-drop / recursion thresholds on non-main threads | measured only on the main thread (8 MB) | a `Thread.spawn` body has a different stack size; not measured. |
| Whether N1's thresholds hold on Linux / in CI | measured on this macOS host only | Python's recursion limit is the binding constraint, so it should port, but the exact numbers are host-specific. |
| Exhaustive enumeration of std for DF-215h | read CLAUDE.md's prelude digest only | negative claim not fully established; row marked READ. |
| `astdiff` / `lexdiff` lane status on the current tree | did NOT run | battery lanes are suite-shaped; another agent holds the battery. |

---

## 8. What this census did NOT cover

* **The full battery, `test_runner.py`, `freestanding_runner.py`, and the
  `astdiff`/`lexdiff` lanes** — suite-shaped, owned by the lead's scheduler.
  All evidence above is individual `sawc.py` compiles of scratch probes and
  three direct `tools/dump_ast.py` invocations.
* **`blade/tests` and `libs/*/tests` as a corpus** — the coverage map says only
  `bootstrap` typechecks them. They are tracked `.saw`, so `astdiff` DOES sweep
  them for parse; I did not compile them individually because nothing in this
  census turns on their semantics.
* **`sawc/std/` and `sawc/rt/` sources** — reproducing the builtins-divergence
  family needs edits to tracked files.
* **CRLF / BOM / tab-indentation / non-UTF-8 input** — not probed; a lexer-port
  question that `lexdiff` already owns.
* **`--freestanding` and cross-target parse differences** — none expected (the
  parser is target-independent), not verified.
* **Filing.** Nothing was filed, numbered, or written to `designs/`. The eight
  N-rows are unnumbered by design; the lead triages and numbers.
