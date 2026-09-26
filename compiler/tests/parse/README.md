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
  waivers.tsv        coverage items and cases with no program, each with its reason
```

`compiler/tests/grammar/dump.py FILE...` prints a file's dump, and
`compiler/tests/grammar/generate.py` writes `generated/`.

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
underscores, base prefix, suffix and escapes: `1_000`, `0XFF`, `2u8`,
`"tab\there"`, and `1_` and `2__u8`, which the lexers accept (GRAMMAR.md §16).
So that a dump line holds one line of the dump, a leaf escapes each character
Python's `str.splitlines` ends a line at: the C0 controls U+0000 to U+001F,
such as a line break inside a string literal, and U+007F and U+0085 print as
`\xHH`, and U+2028 and U+2029 as `\uHHHH`. A parenthesis leaf prints as `\(` or
`\)`, so that it never reads as the S-expression's own. These escapes are
unambiguous: a backslash in a valid literal always starts one of the
literal's own escapes (`\\`, `\"`, `\n`, `\t`, `\r`, `\0`, `\u{…}`, `\{`,
`\}`), so read from the left a dump's `\x`, `\u` followed by a hex digit, `\(`
and `\)` are never part of one, `"\\x09"` included.

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
- A plain parse error must be refused. The recognizer's `L:C`, the furthest
  token its chart reached, is recorded for information only: matching it
  exactly would demand the correct-prefix property of every parse, the
  speculative generic lists included.

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
program for the context (`CONTEXTS`). A P cell's construct is parenthesized,
and so is any other that no host of the context places bare, since precedence
decides the grouping of an operand. The case counts only when the recognizer's
record holds its cell.

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

## Coverage

The `parsecoverage` check, which `compiler/tests/run.py` runs with the
regeneration, reads the coverage records of the generated cases
(`Parse.record` in `recognize.py`). It fails when a non-removed alternative is
used by no case, or when a §12 cell whose code is Y, S, K, T, P, H or C is
recorded by no case. `waivers.tsv` lists the items that have none, one per
line: `alternative` or `cell`, the item (an alternative's name, or a
construct row and a context separated by a space), and the reason, separated
by tabs. A waived item's case may have no program. A `case` row waives one
case, by name, whose tree no program can make hold what the name says; the
generator tries only its cheapest program. A waiver for a covered item or a
case that has a program, or for one the check does not ask for, fails too, so
the list only shrinks.

## Phase 2b

These hold for the golden and negative corpus that phase 2b adds:

- `compiler/tests/grammar/corpus.py`, and the per-file check the per-patch gate
  runs, skip `compiler/tests/parse/`. The parse lane in
  `compiler/tests/run.py` checks each case there against its own expectation,
  so each file has one owner, and a negative case need not parse as a whole
  program.
- A §12 N cell whose tokens parse as something else has no refusal to record.
  Its negative case records the other reading's dump as its expectation.
