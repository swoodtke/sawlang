# Design 259 — The Self-Hosted Parser (selfhost ladder, rung 2)

**Status: AUTHORED Sep 1 2026** (lead), from the user's Sep-1 direction and the
same-day parser-surface census (187 probes, sweep agent, read-only). **§3
BATCH RULED (user, Sep 1): R1–R6 and R8 as recommended; R7 SUPERSEDED by the
user's own R7′ — arm bodies accept STATEMENTS** (rationale at R7). Per the user
(Sep 1): this brief is **the source of the next queue batch** once the current
queue drains (218/1.5 remainder → 258 → 245 v1 → DF-247a). Agent DF ranges:
assigned at dispatch. The census's N-numbered findings get DF numbers when the
tracker reopens for filing (held while 218/1.5's agent owns its todo.md entry).

## 0. Charter and the freeze doctrine (user-ratified Sep 1)

Port sawc's parser to Saw at `selfhost/parser/`, against `tools/astdiff.py`'s
dump as a whole-corpus differential oracle — the exact shape `selfhost/lexer`
already lives under (`lexdiff` + `selfhostlex` lanes). The day the dump becomes
the oracle, the Python parser's behavior stops being current state and becomes
**the contract**. Hence the doctrine, ruled Sep 1:

1. **Every open finding on the frozen surface is FIXED or explicitly
   RULED-intended before the freeze.** "Match the Python parser's accident" is
   never an admissible resolution — that is how a rewrite inherits bugs.
2. **The parser diff has NO known-divergence ledger, ever.** A mismatch fails
   the gate; the resolution is always a ruling that fixes one side (almost
   always Python plus the corpus), never a tolerance entry. This is what keeps
   "two compilers with different results" structurally impossible rather than
   vigilance-dependent.
3. **The oracle bar is the one the tool already chose** (lead-verified against
   `tools/astdiff.py` / `tools/dump_ast.py` / `sawc/ast_dump.py` /
   `docs/AST_DUMP.md`): **byte parity** on accepted files (shape only — no
   line/column in the dump body, no node_ids without `--ids`, no typechecker
   nodes), **verdict + `line:col` parity** on rejections (`ERROR` record, first
   error only), **message prose free**. Two consequences the units below act
   on: diagnostic-only findings are invisible to the oracle and get fixed on
   their own merits — but a refusal's *position* freezes, so a wrong anchor
   (N5) is contract damage.

Validation criterion for everything in the backlog, ruled with the doctrine:
classify by SURFACE, not by interestingness. Class 1 ossifies into the
contract (lex/parse/AST-shape) — blocking. Class 2 blocks the implementation
(Saw-language bugs the parser's own code steps on) — blocking. Class 3
(typechecker/codegen) cannot be written into a parser and stays on its own
schedule; it gets this same treatment later, at the typechecker-port rung.

## 1. Where the ladder stands

- **Rung 1 done**: `selfhost/lexer` — its own tests (`selfhostlex` lane) plus
  `lexdiff` over every tracked `.saw`, no divergence ledger. `devtools/irdet`
  proved the devtool path before it.
- **Rung 2 unlocked by design 246** (recursive types, Aug 27): an AST is
  box-linked enums, unwritable in Saw before it.
- **The port is pure `.saw` plus battery lanes — zero `sawc/` collision** with
  design 258's typechecker surface, so its build can run CONCURRENTLY with the
  queue in its own worktree. Only unit 0 (Python-side grammar fixes) touches
  `sawc/parser/`, and it serializes like any compiler dispatch.
- The port lands under `selfhost/`, NOT `sawc/std/` (confirmed; the lexer's
  precedent). This keeps DF-267d/271a/272c out of the blocker set — they bite
  only std-internal code.

## 2. The census (Sep 1; evidence absorbed here — the scratch report was
## `.build/scratch/sweep_parser_census.md` and is ephemeral)

Headline: **the freeze is not ready.** 9 tracker Class-1 findings reproduce,
plus 8 NEW ones from fresh probing — the largest not a tracker item at all
(N1). 11 Class-2 findings reproduce, four sitting directly on the shape the
parser will be written in. One soundness finding (N10) fell out by accident
and outranks the list; it is NOT this brief's (§4).

### 2a. Class 1 — ossifies into the contract (all verified by direct compile/run)

| finding | tier | one-line repro/evidence |
|---|---|---|
| DF-284b `{ … }()` | **silent wrong answer** + parse error + wrong refusal | `let x = { 1 }()` compiles, DROPS the `()`, `x()` prints `1` |
| DF-266a leading `-` tail after `if { return }` | ICE over a wrong parse | `internal compiler error … (BinaryOp)`; `dump_ast.py` parses the same text fine as `BinaryOp(-)` with an `IfExpr` LHS |
| DF-259c trailing closure in a `try` operand | wrong refusal | pin `examples/trailing_closure_inside_a_try_operand.saw` still XFAILs |
| DF-172d line wrapping (3rd sighting) + postfix face | wrong refusal | `Unexpected token: PIPE` / `NEWLINE` / `DOT` |
| DF-259b reserved word in 5 declaration-name slots | diagnostic-only | none of the five messages names the token as a keyword |
| DF-215j `return` in a value match arm | diagnostic-only | `Unexpected token: RETURN` + a bogus cascaded second error |
| DF-215i no boolean `guard cond else { }` | grammar gap | `Expected 'let' or 'var' after 'guard'` |
| DF-276a unrepresentable float literal | **silent wrong answer** | prints `inf` / `0.0`; the integer twin is a clean located refusal |
| **N1** parser recursion unguarded | **ICE, unfunnelled** | raw ~2100-line Python traceback; §3 R4 |
| **N2** `as Int??` — whitespace picks the cast target | silent wrong answer | §3 R5 |
| **N3** bare trailing closure on a free function | wrong refusal | `run { 10 }` → ``undefined variable `run` `` (labelled `runtag(tag: 5) { 10 }` and method receivers both work) |
| **N4** `lend` is statement-only in a match arm | grammar gap + noisy cascade | `case Leaf(n) -> lend n` → `Unexpected token: LEND`; the braced arm parses |
| **N5** unclosed `{` not anchored at its opener | diagnostic-only, but the POSITION freezes | reports `Unexpected token: FUNC` at the NEXT function; `(`/`[` anchor correctly, three deep |
| **N6** `.5` gets no tailored message where `1.` does | diagnostic-only | `Unexpected token: DOT` |
| **N7** unterminated string reports at EOF | diagnostic-only | not at the opening quote (the bad-escape message is the good control) |
| **N8** a labelled call parses as `StructInit` | AST-shape **decision** | `f(n: 0)` dumps `StructInit f`; resolved only in the typechecker |

N1's bisection, one shape at a time (the numbers a ruling needs):
nested `(…)` last-OK 60 / first-FAIL **61**; nested `if true { }` 47/**48**;
nested closures **50**; `[[[…]]]` 60–80; `Box<Box<…>>` 200–500;
repeated unary `-` 100–1000. The control: `1 + 1 + … + 1` at 500 terms fails
CLEANLY (`internal compiler error at FILE:2:691 … maximum recursion depth
exceeded`) — the TYPECHECKER's recursion is funnelled, the parser's is not.
One missing wrapper, not a language-wide gap. No `sys.setrecursionlimit`
anywhere in `sawc/` or `tools/`. This violates `tools/sawfuzz.py`'s single
oracle today, and 48 nested blocks is inside machine-generated range.

N2's cells (the lexer emits `??` as ONE token, so the type grammar can never
consume it in a cast target):

```
n as Int? ?? 9   -> cast target Int?     (documented operator-wins rule)
n as Int?? 9     -> cast target Int      (?? taken whole as the operator)
n as Int? ?      -> cast target Int??    (both ?s consumed by the type)
n as Int??<EOL>  -> Parse error: Unexpected token: NEWLINE
```

`Int??` as a cast target has no spelling at all except `as Optional<Int?>`.
Annotation position (`let a: Int?? = None`) is unaffected. LANGUAGE_SPEC
documents operator-wins but not that SPACING decides.

### 2b. Class 2 — blocks the implementation (all verified)

The four on the port's own shape, hard prerequisites:

| finding | tier | why the parser steps on it |
|---|---|---|
| DF-261d `Box` forwarding misses ENUM payloads | wrong refusal | the AST is box-linked enums; no Saw-level traversal without it |
| DF-261e `?.` through a `Box<T>?` field | ICE | `Box<Node>?` is the optional-child spelling |
| DF-267c cannot `lend` into a match-bound payload | wrong refusal | this IS `Node.child(at:)` |
| DF-257a qualified init loses a DEFAULTED param | wrong refusal | blocks the `lex`/`ast`/`parse` module split |

The rest, triaged at unit-0 dispatch (fix, or verified workaround named in the
port's style guide): DF-261c (`==` ignores a hand-written `equals` — SILENT
wrong answer, worth fixing regardless of the port), DF-248b residue (nested
closure loses a write through an outer `&var` — SILENT; the pin is the
authority, lead's minimization hit a different correct refusal), DF-267a,
DF-250a (collection literal through a `Result` Ok — every parser function
returns `Result`), DF-270a/b (alias adoption + `G<Alias>` ICE — `type
TokenKind = UInt8` is the natural spelling), DF-272a, DF-277a (`E.from(raw:)`
won't adopt a bare literal — the backed-enum token-kind idiom), DF-257d
(reproduces ONLY at the pin's shape — `try` inside a closure whose parameter
is the `$0`; recorded so nobody re-minimizes it to "fixed"), DF-259a,
DF-215g, **N9** (a `--module-path` dependency declaring a prelude-colliding
name gets NO collision report — the name silently resolves to the builtin and
the errors are nonsense about its own declaration; the entry-file twin reports
correctly; DF-280b's family at the dependency position), **N11/N12** (stack
exhaustion is a bare SIGSEGV at both levels: Saw recursion ~1M frames, and a
box-chain deep DROP at ~300k links on the 8 MB main-thread stack — design
246's warning confirmed; pairs with R4: whatever depth limit is ruled must be
enforced BY the parser, because neither the language nor the runtime catches
the overflow). Joined Sep 1, post-census, both sos-relayed and lead-verified
with full matrices in their tracker entries: **DF-287a** (a `move` inside a
DIVERGING catch poisons the fall-through — catch is the one diverging
construct the move checker treats sequentially, and a parser's error paths
are exactly catch-and-diverge over move-only nodes) and **DF-287b**
(bare-literal adoption never runs at an OVERLOADED call site — DF-242c's
matcher family; a parser leans on overloaded helpers throughout).

### 2c. Class 3, non-reproducers, OPEN cells

Class 3 (cannot be written into a parser; own schedule): everything else open
in the tracker — the census report carried the one-line roster and nothing in
it claims current behavior, so it is not restated here.

- **DF-273a does NOT reproduce** (two shapes probed, including the entry's
  own). Likely closed by designs 249/255. Lead re-verifies and closes at the
  next tracker filing.
- **DF-272b does not reproduce** at parameter position; the entry carries no
  repro of its own. OPEN.
- DF-267d / DF-271a / DF-272c: unprobed (require editing `sawc/std/`);
  Class 3 under this brief's `selfhost/` placement.
- Not measured: non-main-thread stack limits, Linux N1 thresholds, CRLF/BOM/
  non-UTF-8 input (a lexer question `lexdiff` owns; out of scope here).

### 2d. Negative controls (inherited into the port's test plan)

Probed FINE, recorded so the port's tests cover them from day one: `t.0.0`
tuple-index chains; newlines inside `<>` at depth, nested; `Vector<Vector<
Vector<Int>>>` beside `a < b`; a 1000-arm match; 40 chained postfix calls;
4-hop `?.` chains; nested string interpolation (`"nested: {"inner {a}"}"`) and
a value-`if` inside an interpolation; unicode identifiers; the full escape
set + `\{`; comments inside brackets with trailing commas; multi-line labelled
decl/call/init; `///` misplacement (clean both positions); `1..3`/`1..=3`
beside the `1...3` refusal; unclosed `<` (clean); unclosed `(`/`[` anchored at
the OUTERMOST opener three deep.

## 3. THE RULING BATCH (user) — each with the lead's recommendation

- **R1 (DF-284b).** `{ … }()` — three positions, three different wrong
  outcomes today, one of them silent. RECOMMEND: the postfix call applies to a
  closure literal in every expression position (the spec and the design-122
  diagnostic both already promise it); unit 0 settles the trailing-closure
  interaction the DF entry flags.
- **R2 (DF-266a).** A statement-start `-` after a CLOSED block: today parsed
  as a binary op whose LHS is the block (then ICEs). RECOMMEND: a new
  statement/expression — a closed block statement ends the expression; the ICE
  becomes moot and the value-`if` tail spelling is unaffected (it is inside a
  value position, not after a statement).
- **R3 (DF-172d) — RULED as recommended, individually confirmed (user,
  Sep 1: "the narrow fix seems fine").** A line ENDING in a binary operator
  continues (`a +⏎ b`); leading-operator continuation stays refused (it is
  the ambiguous half — exactly R2's shape). The third-sighting postfix face
  (`.method()` on the line after a `)`) is NOT covered — a leading `.` is
  the same ambiguous half, and the `let` spelling stays the idiom there.
- **R4 (N1) — RULED as recommended, individually confirmed (user, Sep 1:
  "256 sounds good, and is easy to change in both parsers if necessary").**
  **256** nesting depth, one funnel counting all recursive-descent entry
  points, clean error at the construct's OPENER (`nesting exceeds the parser
  depth limit (256)`), same number enforced in the Saw parser explicitly
  (its native stack would otherwise pick a different, larger, accidental
  limit — N11/N12 show nothing downstream catches the overflow). 256 clears
  every probed real shape by 4x+ and the corpus by far more; the limit is
  contract, so it gates in astdiff's ERROR records like any refusal. Per the
  user's confirmation note, changeability is part of the design: the limit
  is ONE named constant per parser, cited by the diagnostic, so a future
  re-ruling is a two-line change plus the limit/limit+1 pins.
- **R5 (N2).** RECOMMEND the principle: **spelling never depends on
  whitespace**; the grammar detail (re-splitting `??` after a type in a cast
  target, and whether `as Int??` gains a meaning or a tailored refusal) is
  unit 0's to design under that principle, with the cells above as its matrix.
- **R6 (N3).** A bare trailing closure on a free function is a call.
  RECOMMEND: fix — the labelled form and the method form both already work;
  the gap is one position in design 138's matrix.
- **R7 (N4) — RULED R7′ (user, Sep 1), superseding the lead's
  recommendation: a match arm body accepts a single STATEMENT in addition to
  an expression or a block.** The user's frame: expecting the user to
  understand the expression/statement distinction is asking a lot, and
  always requiring a block is too heavy-handed — so accept statements. The
  lead's probes established this is a FAMILY, not a `lend` gap: bare
  `-> break`, `-> return 9` and `-> lend n` all died with the identical
  `Unexpected token` + two-line cascade while `-> panic("gone")` (an
  expression) compiled — so the ruling dissolves **DF-215j** (the bare
  `return` arm becomes legal) and N4 together. IMPLEMENTATION SHAPE (U0):
  the arm body becomes `block | statement`, with NO keyword list — an
  expression-statement is a statement, a lone `let` arm is legal and inert
  exactly as `{ let x = 5 }` is, and a value-match arm producing no value
  keeps its existing type error; `return`/`break`/`continue` arms type as
  diverging under design 228's rule and a `lend` arm checks under DF-146d's
  rules unchanged, both exactly as their braced twins do. Multiple
  statements still take the block. Pins owed: all four keywords as bare
  arms, statement arms in VALUE matches (diverging-arm typing), the inert
  `let` arm, and the arm-separator comma after a statement body. This is a
  grammar CHANGE, so it lands in the Python parser at U0 and natively in
  the Saw parser — pre-freeze, once, both sides.
- **R8 (N8).** A labelled call parsing as `StructInit`, resolved in the
  typechecker, is a parse-time decision the freeze makes permanent — the Saw
  parser must emit the same shape or dumps diverge on a large fraction of the
  corpus. RECOMMEND: bless as-is. The alternative (a neutral CallOrInit node)
  buys nothing the typechecker doesn't already do and would churn the dump
  format for the whole corpus.

Rulings NOT in this batch: N9 rides DF-280b's open wording ruling (same
family, now with the dependency position); DF-276a, DF-259c need no ruling —
mechanism-known fixes, unit 0.

## 4. Prerequisites OUTSIDE this brief

- **N10 — SOUNDNESS, dispatches FIRST, own brief-let.** `let w = v as
  Vector<Int>` (a cast to the value's own type) bypasses
  `_check_value_transfer`: compiles where `let w = v` is refused, two owners,
  double free at scope exit (probe exits 133). This is DF-216a's NAMED
  MECHANISM — another call construction skipping the transfer check — so
  obligation 4 applies in full: the fix targets the mechanism, with a sweep of
  the remaining `CastExpr`-like positions as its test plan. Serialized after
  218/1.5 integrates (typechecker-surface collision rule, Aug-31 precedent),
  ahead of the queue by fix-on-discovery policy.
- **The Class-2 hard four** (DF-261d/e, DF-267c, DF-257a): fixed before U2
  dispatches. Small; plausibly one batched dispatch.
- Tracker filing for N1–N12 + DF-273a's closure: at the next filing window.

## 5. Units

- **U0 — the grammar debt (Python side; sawc/parser/ + lexer.py).** Implement
  the §3 rulings + the mechanism-known fixes (DF-259c, DF-276a) + the anchor
  fix N5 (its position freezes) + the cheap diagnostic batch (DF-259b,
  DF-215j, DF-215i's message or the boolean-guard ruling if the user extends
  R-batch to it, N6, N7). Every fix lands with pins; the two silent-wrong-
  answer rows (DF-284b's `let` face, DF-276a) get conformance-adjacent
  regression tests. Full per-commit compiler gate.
- **U1 — the depth-limit funnel.** R4's limit in the Python parser (one
  wrapper, named entry points per obligation 1), the clean opener-anchored
  error, sawfuzz's oracle restored (a traceback is a finding again), pins at
  limit and limit+1.
- **U2 — the AST in Saw.** `selfhost/parser/` package: node enums per design
  246 (Box-linked, NoCopy, policies declared), plus the dump writer to
  `docs/AST_DUMP.md` byte parity. Gate: dump a hand-curated file set
  byte-identically.
- **U3 — the parser itself.** Recursive descent mirroring `sawc/parser/`'s
  module split, the R4 limit enforced natively, first-error `ERROR` records at
  verdict+position parity. New battery-adjacent tool `parsediff` (astdiff's
  twin driving BOTH parsers, byte-comparing dumps corpus-wide, no divergence
  ledger). Gate: whole-corpus parsediff clean.
- **U4 — differential fuzzing.** sawfuzz's mutated corpus fed to both
  parsers, agree-on-verdict oracle — the tracked corpus is where two parsers
  won't differ; the mutants are where they will. Findings triage as U0-class
  rulings, never tolerance entries.
- **U5 — the lanes.** `selfhostparse` (the package's own tests) + `parsediff`
  join `tools/battery.sh` STAGES; TESTING.md and the repo map updated per the
  design-125 docs convention.

U0/U1 are compiler dispatches (serialize with the queue); U2–U5 are
`selfhost/`-side and may run concurrently with design 258 in a worktree.

## 6. Open questions (deferred, not blocking the rulings)

- Error RECOVERY: astdiff records the first error only; the port matches (no
  multi-error contract in v1). Multi-error parity is a later rung.
- Perf: no bar in v1 — correctness first; measure once parsediff is green.
- The typechecker-port rung repeats this whole exercise (census → freeze
  doctrine → rulings) against its own surface; nothing here pre-commits it.
