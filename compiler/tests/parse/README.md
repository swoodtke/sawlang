# compiler/tests/parse: the parser corpus

The corpus the parser units are written against (SL-406). Every expectation in
it comes from `GRAMMAR.md` through the reference recognizer in
`compiler/tests/grammar/`; none comes from a parser. This file specifies the
canonical AST dump that a parser's output is compared in, and the layout of the
corpus.

```
parse/
  README.md          this specification
  dump/              hand-checked dumps: NAME.saw and its NAME.dump
  generated/         the generator's cases: AREA.saw and AREA.dump
  golden/            hand-written cases: ASPECT.saw and their dumps, ASPECT.dump
  negative/          refused cases: ASPECT.saw and their refusals, ASPECT.expect
  waivers.tsv        coverage items and cases with no program, each with its reason
  FROZEN_COMPARISON.md  the one-time comparison with the frozen parser (SL-424)
```

`compiler/tests/grammar/dump.py FILE...` prints a file's dump,
`compiler/tests/grammar/generate.py` writes `generated/`,
`compiler/tests/grammar/negative.py` writes the generated files of `negative/`,
and `compiler/tests/grammar/cases.py --write FILE...` writes the expectations of
a hand-written case file.

## The canonical dump

A dump is an S-expression. A node prints as `(Kind child...)` and a leaf as its
text. Two inputs have the same dump if and only if they have the same tree.
What the tree does not record never shows:

- whitespace, line breaks outside string literals, and comments;
- grouping parentheses;
- separators: which of a comma, a `;` or a line break divides two items (or,
  between match arms, nothing), and a trailing comma (`f(b,)` against `f(b)`);
- the space after a doc comment's marker (`/// foo` against `///foo`);
- where a doc comment stands around `@test`: `/// d` then `@test func f`
  dumps as `@test` then `/// d` then `func f` does;
- source positions. The parser units check spans separately.

### Nodes

- **Kind.** A node's Kind is the `node=` of the production that builds it;
  `OptionalChain` (below) is the one Kind no production builds.
- **Suffix.** When the production that builds the node has more than one
  alternative, the Kind carries the last segment of the alternative's name:
  `Let.immutable`, `RefType.exclusive`, `Call.paren`. A production with one
  alternative adds nothing, so `trailing-hop` builds a plain `Call`.
- **Pass-through.** A production whose `node=` is `-` builds no node: its
  children become children of the node around it. Only there does an
  alternative that is exactly one nonterminal pass that nonterminal's node on
  (GRAMMAR.md §1). A production that names a node builds it even over a single
  nonterminal, so `(ExprStmt (Name x))` and `(Arg.positional (Name x))`. The
  one exception is a chain production, an operand followed by repeated
  operator-operand pairs, which builds its node only with a second operand. A
  binary tier is one flat node holding every operand and operator of the chain:
  `(Binary (Name a) + (Name b) - (Name c))`.
- **One node per construct.** An alternative that is exactly one nonterminal
  never yields a node of the Kind its production builds (the lint's
  `no-self-wrap` check). So the open range `a..` is `(Range.from (Name a) ..)`,
  its operator a leaf of the one `Range`. A construct the source nests still
  nests: `a!!` is `(ForceUnwrap (ForceUnwrap (Name a)))`, and `Int??`,
  `not not x` and `**p` hold a lone node of their own Kind the same way.
- **Declarations.** A declaration is one subtree, its modifiers inside it. A
  top-level `func`, `static`, `extension`, `struct`, `enum`, `trait`, type
  alias or extern block is a `Declaration` node (`declaration-item`), an
  extension member an `ExtensionMember` node and an attributed local an
  `AttributedLocal` node. Each holds what the declaration has of a doc comment,
  attributes and a visibility, in that order, then the declaration's own node:
  `public enum E {}` is `(Declaration.enum (Visibility.public) (Enum E))`. The
  other top-level items, an import, a `module`, a `static_assert` and a test
  item, are nodes of their own with no `Declaration` around them, so a
  `public` there is a leaf: `public module m` is `(ModuleDecl.file public m)`.
- **Hops nest.** A postfix chain nests one node per hop, the base innermost,
  wherever the chain stands: an expression, an assignment or compound target,
  an optional-chain target, and a `move` operand's place path. A run of casts
  nests one `Cast` per `as` (syntax.rule.postfix-per-hop).
- **Optional chains.** Each run of an optional chain is one `OptionalChain`
  node, the one Kind no production's `node=` names. A run starts at its
  chain's base and takes every hop up to the `!`, subscript or tuple index
  that closes it, or to the chain's end (syntax.rule.optional-chain-run); a
  hop that closes the run applies to the `OptionalChain`, and a later `?.`
  hop opens a run around it. A parenthesized operand is a chain of its own,
  so parentheses end a run:

  | source | dump |
  |---|---|
  | `a?.b.c` | `(OptionalChain (Member (OptionalMember (Name a) b) c))` |
  | `(a?.b).c` | `(Member (OptionalChain (OptionalMember (Name a) b)) c)` |
  | `a?.b?.c` | `(OptionalChain (OptionalMember (OptionalMember (Name a) b) c))` |
  | `(a?.b)?.c` | `(OptionalChain (OptionalMember (OptionalChain (OptionalMember (Name a) b)) c))` |
  | `a?.b!` and `(a?.b)!` | `(ForceUnwrap (OptionalChain (OptionalMember (Name a) b)))` |

  An assignment target is a chain too: `x?.y = v` is
  `(OptionalAssign.plain (OptionalChain (OptionalMember (Name x) y)) (Name v))`,
  and `x?.y[0] = v` an `Assign` whose target is a `Subscript` of the
  `OptionalChain`.
- **Optional types.** Each `?` after a type wraps it in one `(OptionalType T)`,
  and a `??` token wraps it twice (GRAMMAR.md §5), in a type and in a cast
  target alike. `syntax.type.suffix` builds no node of its own.

### Leaves

A leaf is a token. Which tokens print:

1. Identifiers, integer, float and string literals, and `$0`-style
   parameters always print.
2. Keywords, contextual words and operators print unless the node's Kind and
   suffix imply them. A terminal written directly in the alternative that builds
   the node, not inside `?`, `*`, `+` or a group, is implied. So
   `func f() unsafe sync` prints `unsafe sync` and `static func` prints
   `static`, but `Let.immutable` prints no `let`. A keyword of a `node=-`
   production, such as `as` in a cast suffix or `else` before a final block,
   has no node to imply it, so it prints.
3. Line breaks, the end of input and the punctuation
   `( ) [ ] { } < > , ; : . -> @` never print, except in the `node=-`
   productions whose punctuation the tree needs. A production needs it when one
   of its derivations holds punctuation and prints nothing else, or when two of
   its alternatives always print the same leaves and nodes; so does a
   production such an alternative consists of. There each punctuation token but
   `,` and `;` prints, however many nodes it holds: `case A()`, `case A(x: Int)`
   and `case A(x: Int, y: Int)` each print their parentheses.
   `Grammar.flagged` in `recognize.py` computes the list, and today it is:

   | production | what it shows |
   |---|---|
   | `compare-op` | the `<` and `>` operators |
   | `import-target` | `import m.*` and `import m.{}` against `import m` |
   | `method-name`, `setitem-name` | `func []` and `func []=` |
   | `payload-decl` | `case A()` against `case A` |
   | `refusal-token` | the nested braces of a refusal case's body |

   A refusal case's body is a list of raw tokens, so each of its tokens, line
   breaks included, prints.
4. A shift, two `<` or two `>` tokens, is the one leaf `<<` or `>>`. In a
   refusal case's body, which no production reads, two `<` or two `>` tokens
   with nothing between them are the one leaf too, so there `a << b` prints
   `<<` and `a < < b` prints `< <` (syntax.lex.shift-adjacent).

Leaves are spelled as written. A literal prints its source spelling, with its
underscores, base prefix, suffix and escapes: `1_000`, `0xFF`, `0xFF_FF`,
`2u8`, `2_u8`, `1_0.5` and `"tab\there"`.
So that a dump line holds one line of the dump, a leaf escapes the C0
controls, U+007F, and the other characters Python's `str.splitlines` ends a
line at: a C0 control, such as a line break inside a string literal, U+007F
and U+0085 print as `\xHH`, and U+2028 and U+2029 as `\uHHHH`. A parenthesis
leaf prints as `\(` or `\)`, so that it never reads as the S-expression's own.
These escapes are unambiguous: a backslash in a valid literal always starts
one of the literal's own escapes (`\\`, `\"`, `\n`, `\t`, `\r`, `\0`,
`\u{…}`, `\{`, `\}`), so read from the left a dump's `\x`, `\u` followed by a
hex digit, `\(` and `\)` are never part of one, `"\\x09"` included.

### Interpolated strings

An interpolated string is `(Interp ...)`. Its children are its segments in
order: a literal run as a quoted string, spelled as written with its escapes;
an expression segment as its own dump; and a blank segment, a format
placeholder, as the leaf `{}`. So `"a \{ {x}{} b"` dumps as
`(Interp "a \{ " (Name x) {} " b")`. Each segment is parsed on its own
(GRAMMAR.md §2.5).

### Doc comments

A `///` run gives the declaration it documents (GRAMMAR.md §2.6) a first child
`(Doc "line" ...)`, one string per line. The node is the one that holds the
declaration's modifiers, so `/// ...` before `public func f` documents the
`Declaration.func`, and one before a method documents its `ExtensionMember`; a
struct field, an enum case and a trait requirement take it on their own
`Field`, `Case` and `Requirement`. Under `@test` the `Doc` goes on the inner
`Declaration`, not on the `TestOnly` node that holds the attribute, whether the
run stands before `@test` or after it. `//!` lines give the `File` node its
first child the same way. A doc line's text is what follows the marker and the
one space after it, if there is one, quoted, with `\` and `"` escaped as `\\`
and `\"` and the characters a leaf escapes escaped the same way. Plain `//`
comments never print.

### Layout

The dump is byte-stable. A node whose children are all leaves, or nodes of
leaves, takes one line. Any other node opens a line with `(`, its Kind and the
leaves before its first child node; every later child, node or leaf, takes a
line of its own, indented two spaces deeper, and the node's `)` ends its last
line. A file's dump is its `File` node. For example,
`let r = f(x) + 1` in `main` dumps as:

```
(File
  (Declaration.func
    (Func main
      (Block
        (Let.immutable
          (BindingName r)
          (Binary
            (Call.paren
              (Name f)
              (Arg.positional (Name x)))
            +
            (IntLit 1)))))))
```

## Refusals

A parser refuses what the recognizer refuses, and the contract for a refusal
depends on what decided it:

- A refusal decided by a named §13 rule, a lexical rule or a removed
  production must name it exactly, by its stable `syntax.*` id (SL:testing).
- A plain parse error must be refused. A `parse-error` expectation accepts
  any refusal, named or not. The recognizer's `L:C`, the furthest token its
  chart reached, is recorded for information only: matching it exactly would
  demand the correct-prefix property of every parse, the speculative generic
  lists included.

A refusal has one name, whatever follows the token that decides it, so a
parser deciding at that token can give it. The recognizer's name is the first
of these that applies:

1. A §13 rule on a removed production, one its row lists, that refuses a token
   after a complete construct, where that production's reading takes the
   token. The rule decides at that token, so the case records the rule's name
   even where the production would also make the text parse: `n as Int??`,
   `n as Int? ?`, `n as Int?? 9` and `n as Int? ?? 9` each record
   syntax.rule.cast-target-question at the `??` or the second `?`. The earliest
   such token counts.
2. The removed production whose enabling alone makes the text parse. A rule
   that chooses between two readings of the same tokens leaves the name to the
   production: syntax.rule.discard-binding reads `var _ = e` as
   syntax.stmt.refused-var-discard.
3. The rule the recognizer reports, else `parse-error`.

A name from step 3 must also be decided at the refusing token. A rule that
decides by the token after the construct it refuses, as range-open-end and
borrow-form do, keeps its name only while dropping the tokens after that token,
or replacing each run of them by one name, keeps it; line breaks and the
brackets that balance the text stay. Otherwise the case records `parse-error`:
`let b = a.. == c` is refused by range-open-end only while an operand follows
the `==`, so it records `parse-error`, as `a.. + b` does. A rule that decides
by the construct's own tokens decides at them, whatever follows. Making the
recognizer name range-open-end at its token is SL-410.

A rule the productions encode, such as syntax.rule.statement-separator, refuses
without the recognizer naming it, so its cases record `parse-error`. A lexical
rule the lexer applies, such as syntax.lex.unterminated-string, is named by the
lexer's error, and the recognizer passes that name on with the lexer's position,
the one §2.7 fixes. syntax.lex.unclosed-bracket, which no lexer applies, is
recorded at its opener by `cases.py` itself (The negative corpus, below). A
lex error no §2.7 rule names, such as an unexpected
character or a number whose `_` stands between no two digits, records
`parse-error` at the lexer's position. A lex error inside an interpolation's
segment records `parse-error` with no position, since the segment is lexed on
its own.

Where two rules each refuse another reading of one text, a parser reports
syntax.rule.head-restriction when it is one of them (GRAMMAR.md §13): `if v.any
{ $0 } { }` is also refused as a trailing closure on the `if`, and records
head-restriction. The recognizer reports it at its own token, wherever the
other rule's refusal lies (`PRECEDENCE` in `recognize.py`). Between two other
rules the grammar does not say which a parser reports, so no case records such
a text.

Nor does any case record a text refused twice, once inside a removed form's
reading. That is a text with a tree, every removed production enabled, in which
a removed production's reading holds another removed production's reading and,
for a name from step 1, the token that name is decided at. A parser that reads
the refused form by the rules meets the inner refusal first, so the grammar does
not say which refusal it reports. `while { a } + (x as Int??) { }` needs
syntax.type.refused-cast-question inside the condition of
syntax.expr.refused-brace-condition, and `while { a } + (while { b } { }) { }`
holds one refused condition inside another; `cases.py` raises `Problem` for
both. A refusal after the reading is not inside it, so `n as Int?? 9` records
syntax.rule.cast-target-question at the `??`.

## The generated corpus

`compiler/tests/grammar/generate.py` derives the cases from the grammar.
`generated/AREA.saw` holds the cases of one grammar area, the GRAMMAR.md
section its production or construct row is written in: `declarations` (§3),
`attributes` (§4), `types` (§5), `statements` (§6), `expressions` (§7),
`patterns` (§8) and `borrow` (§9). A removed production (§10) has no case
here. A case starts with a header line

```
// case: NAME
```

and runs to the line before the next header, less the blank line that
separates two cases, or to the end of the file. Each case is parsed on its own,
as a whole program from `source-file`, so no context leaks from one case into
the next; a statement or an expression stands in a minimal function of its
own, never in `@test`. `AREA.dump` holds, for each case in the same order, its
header line, its dump, and a blank line between cases.

### The cases

A case NAME is the alternative or construct row it exists for, then `/` and
its variant:

| variant | the case |
|---|---|
| `alt` | the alternative, each of its options at its cheapest value |
| `opt:ITEM=absent`, `=present` | an item written `x?`, absent, or present at its cheapest expansion that writes a token |
| `rep:ITEM=0`, `=1`, `=many` | an item written `x*`, zero times, once or three times, each time writing a token; `x+` has no 0 |
| `choice:ITEM=N` | a group `(a \| b)`, taking its Nth choice |
| `pair:ITEM=V,ITEM=V` | two options of one alternative, each at its last value |
| `cell:CONTEXT` | a §12 construct row placed in that context |

ITEM is the option's position among the alternative's items, then its text,
so two options with the same text stay apart. An alternative needs cases when
its production is not removed and it names a removed production only where it
can be absent: inside an item written `x?` or `x*`, which its cases hold
absent. So `effect-slot`, whose last item is the removed `refused-escaping?`,
has cases for each effect word before it. Pairwise cases take every pair of an
alternative's options, in item order, both at their last value (present,
many, the last choice).

A case counts only when its tree holds what it is named for: a derivation of
its alternative, in which each option it names takes that value, the item
present or absent, written that many times, or taking that choice, and a value
that writes a token spans one. A cell case writes the construct row's spelling
(`INSTANCES` in `generate.py`), its constant spelling for a C cell, into a
program for the context (`CONTEXTS`), with a space on a side where the lexer
would otherwise read the spelling and its neighbour as other tokens (`a..`
before `..x` is not `a....x`). A P cell's construct is parenthesized,
and so is any other that no host of the context places bare, since precedence
decides the grouping of an operand; a P cell's bare form is a negative case
(`bare`, below). The case counts only when the recognizer's record holds its
cell.

### How a program is built

An alternative's items are expanded at their cheapest, fewest tokens first with
an identifier the cheapest operand, and placed in the cheapest host a
`source-file` offers. A test form, a `static` initializer, a `static_assert`
and a destructuring `let` cost more as hosts, so a statement or an expression
stands in a function and a pattern in a match arm. Identifiers are named `a`,
`b`, `c` and on in order. Line breaks the tokens start or end with stay, so a
case about a file's leading or trailing line breaks has them; a text whose
tokens end in none ends in one line break. Where the cheapest program has no
single tree, because a §13 rule the productions do not encode refuses it, or
its tree does not hold what the case is named for, the generator repairs the
case: it tries other hosts, then changes one choice, inside an item or among a
host's siblings, then two. A case no repair saves has no program, and
generation fails unless the case or its item is waived. The lexer must read
each program back as the tokens it was written from, so spacing never joins
two tokens into a third.

Every case has exactly one tree. A case with two trees, or none, is a
generator bug: the case is fixed, never the check. Regenerating must reproduce
`generated/` byte for byte, and `compiler/tests/run.py` fails when it does not.

## The golden corpus

`golden/ASPECT.saw` holds hand-written cases, in the shape of `generated/`:
each starts with a `// case: NAME` header and is parsed on its own from
`source-file`. A case headed `// case from refusal-unit: NAME` is the body of
a refusal case, parsed on its own from `refusal-unit` as a test build parses
it. The last case of a file may end with no line break, so that the end of
input follows its last token. Each case must be accepted with exactly one tree,
and `ASPECT.dump` holds, for each case in order, its header line, its dump, and
a blank line between cases. A case NAME is its source, then `/` and what the case shows:

| source | the cases |
|---|---|
| `syntax.rule.RULE` | each §13 rule, with a case for each decision it makes, both sides of a decision where the rule accepts both |
| `syntax.lex.RULE` | each lexical rule of §2.7 |
| any other GRAMMAR.md name | the production or alternative that refuses a negative case, where no rule does |
| `census-N1` to `census-N12` | the parser census (designs/reviews/parser-census-sep1.md) |
| `design259-R1` to `design259-R8` | the ruling batch of designs/259-selfhost-parser.md |
| `SL-400-c6-Q1` to `SL-400-c6-Q23` | the numbered rulings of SL-400 comment c6, but Q15, which c7 replaces, and Q12, which SL-423 replaces: `borrow` is a keyword |
| `SL-400-c6-U2a` | c6's rulings on the U2a report |
| `SL-400-c7`, `SL-400-c9` | the rulings of those SL-400 comments |
| `SL-406-c11-1` to `SL-406-c11-3` | the three numbered rulings of SL-406 comment c11 |
| `SL-406-c17`, `SL-406-c22`, `SL-406-c23`, `SL-406-c25` | the cast-target rulings of those SL-406 comments; c24 and c26 adopt c23's and c25's |
| `SL-408-c1` | the numeric separator ruling: a `_` between two digits, and the one `_` before a width suffix |
| `SL-409-c1` | a closure's line breaks: before its head, after `in`, around a capture list, and with no head |
| `SL-414-c1` | `move self` in a consuming body: a builder, forwarding and wrapping |

A decision's refusing side is a negative case under the same name. The
`parsecoverage` check fails a case whose name starts with none of these
sources, and a source in a row from `census-N1` on, or a lexical rule, that no
case of either kind is named for. `CENSUS`, `DESIGN_259` and `RULINGS` in
`cases.py` list those rows' sources.

## The negative corpus

`negative/ASPECT.saw` holds refused cases in the same shape, and
`ASPECT.expect` holds, for each case in order, its header line and its
expectation, one of:

```
refuses NAME
refuses NAME at L:C
refuses parse-error at L:C
refuses parse-error
parses as another construct
DUMP
```

NAME is the refusing rule's or removed production's stable id (Refusals,
above), and `at L:C` the recognizer's position when it gives one, for
information only. A case that leaves a bracket unclosed holds the line
`// an unclosed bracket, refused at its opener` and records
`refuses syntax.lex.unclosed-bracket at L:C`, the first unclosed opener, where
§2.7 reports it: the recognizer balances no brackets and only fails later,
where the chart stops, with a plain parse error. A closer that closes an
opener deeper in the stack leaves the openers above it unclosed. A lexical
refusal records the lexer's position (Refusals, above).
A negative case that the recognizer accepts is an error,
except an N cell, or a P cell's bare form, whose tokens parse as another
construct: its text holds
the line `// parses as another construct`, its expectation is that line's
words and then the reading's dump, and the reading's record must not place the
construct in the cell's context.

Four files are generated by `compiler/tests/grammar/negative.py`, and the rest
are hand-written:

- `removed`: one case per removed alternative, named for it: an alternative of
  a removed production, or one that names a removed production where it cannot
  be absent. Its program is the cheapest the generator builds with that
  production enabled, and it must be refused as that production alone. A
  waived alternative gets only its cheapest program, which still shows when
  its waiver is no longer needed. An alternative whose refusal needs a choice
  deeper than a repair reaches takes its program from `SEEDS` in
  `negative.py`, which must pass the same test.
- `cells`: one case per N cell, `CONSTRUCT/cell:CONTEXT`, the construct's
  spelling placed in its context's first program as the generated cells are,
  or, where that one's refusal has two names, in the next (`MORE_CONTEXTS` in
  `negative.py`).
- `bare`: one case per P cell, `CONSTRUCT/bare:CONTEXT`, the program of the
  cell's generated case with the construct's parentheses taken away (SL-417).
  A bare form the recognizer accepts with the construct in the cell's context
  is a finding: it is reported, and its cell waived with the finding as the
  reason, never recorded as expected.
- `mutations`: mutations of each generated `/alt` case, named
  `CASE/KIND:N` for the Nth token: one dropped, one duplicated, two adjacent
  swapped (N and N+1), one closing bracket dropped, each at a position a
  stable hash of the case's name picks. The case's final line break is never
  mutated, and a space keeps the tokens around a mutation apart. A mutation the
  lexer does not read back as the mutated tokens, one the recognizer accepts,
  one whose refusal has two names, and one that repeats another's program are
  discarded, never recorded.

## Coverage

The `parsecoverage` check, which `compiler/tests/run.py` runs with the
regeneration, reads the coverage records of the generated and golden cases
(`Parse.record` in `recognize.py`) and the expectations of the negative cases.
It fails when a non-removed alternative is used by no generated or golden
case, when a §12 cell whose code is Y, S, K, T, P, H or C is recorded by no
generated case, when a removed alternative has no negative case refused as its
production whose tree, with that production enabled, uses it, when an N cell
has no negative case, when a P cell has no bare-form negative case, when a §13 rule has no golden case named for it, when
a rule the recognizer names in a refusal has no negative case refused by it, or
when a case's name has no source (The golden corpus, above) or a source is owed
a case and has none.
`waivers.tsv` lists the items that have none, one per line: the kind
(`alternative`, `cell`, `removed`, `n-cell`, `p-cell`, `rule`, `refusal` or
`source`),
the item (an alternative's, rule's or source's name, or a construct row and a
context separated by a space), and the reason, separated by tabs. A waived item's case may have no
program. A `case` row waives one generated case, by name, whose tree no
program can make hold what the name says; the generator tries only its
cheapest program. A waiver for a covered item or a case that has a program, or
for one the check does not ask for, fails too, so the list only shrinks.

## Who checks what

`compiler/tests/grammar/corpus.py` skips `compiler/tests/parse/`, whether it
walks the tracked files or is given them, and so does the per-file check the
per-patch gate runs on changed `.saw` files. A case file holds many programs,
and a negative one need not parse, so no file here is a whole program. The
parse lane in `compiler/tests/run.py` checks each case against its own
expectation instead: it regenerates `generated/` and `negative/`'s generated
files, checks every hand-written case file's expectations with `cases.py`, and
runs `parsecoverage`.
