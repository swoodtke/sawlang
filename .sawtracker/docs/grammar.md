> **Landed as `GRAMMAR.md` at the repo root (SL-400, merged d34e8f1c).** This document is frozen at r4. Edit `GRAMMAR.md` by patch.

# Saw grammar

This document is the grammar of Saw: every construct a parser must accept, the
name each construct is cited by, and the positions each may appear in.

`LANGUAGE_SPEC.md` is authoritative for what a construct means. This document is
authoritative for how it is spelled. Every production cites the spec section it
belongs to, so the two can be checked against each other. A few forms are
settled by the locked-down design documents SL:borrowing, SL:testing and
SL:architecture before the spec carries them; those productions also cite the
document and section in a `ref=` field. Rulings that live in tracker issues are
cited the same way. Where the spec's text still shows an older spelling, or does
not yet show a ruled one, §15 lists the passage, and this document's spelling
holds.

Tests cite a construct by its stable name, for example
`// rule: syntax.expr.trailing-call` or
`@test(refuses: "syntax.stmt.refused-var-discard")`. A name is never reused or
renumbered.

## 1. Notation

Every production is in a fenced block tagged `ebnf`. A block holds one or more
productions, separated by blank lines. Nothing outside those blocks is a
production. The notation is:

```ebnf-notation
production          ::= header-line rule-line continuation-line*
header-line         ::= "#" production-name "status=" status "spec=" quoted-heading "node=" node-kind ( "ref=" quoted-source )?
status              ::= "current" | "lockdown" | "retired" | "removed" | "pending"
node-kind           ::= UpperCamelName | "-"
rule-line           ::= nonterminal "::=" alternative
continuation-line   ::= "|" alternative
alternative         ::= sequence annotation?
annotation          ::= "@" alternative-name
sequence            ::= "ε" | item+
item                ::= atom ( "?" | "*" | "+" )?
atom                ::= nonterminal | token-kind | quoted-terminal | contextual-terminal | "(" sequence ( "|" sequence )* ")"
nonterminal         ::= lowercase words joined by "-", e.g. call-hop
token-kind          ::= uppercase words joined by "_", e.g. IDENT, NEWLINE
quoted-terminal     ::= a spelling between double quotes, e.g. "func", "(", "#file"
contextual-terminal ::= a word between single quotes, e.g. 'sync'
production-name     ::= "syntax." area "." construct ( "." part )*
alternative-name    ::= production-name
```

- **Fields of the header line** are separated by two spaces and appear in the
  order shown. `spec=` names a heading of `LANGUAGE_SPEC.md` exactly as written
  there, without its `#` marks. `ref=` is optional and names a lockdown
  document section, a design ruling or a tracker issue.
- **Nodes.** `node=` is the preliminary AST node kind the production builds.
  The tree records syntax only: what was written, never what it means. `-`
  means the production builds no node of its own. An alternative that is
  exactly one nonterminal passes that nonterminal's node on, and a chain
  production (an operand followed by repeated operator-operand pairs) builds
  its node only when it has more than one operand. Grouping parentheses build
  no node.
- **Alternatives.** The rule line holds the first alternative. Each further
  alternative is on its own line, starting with `|`. When a production has more
  than one alternative, each one ends with its name annotation. A production
  with a single alternative may omit it, and the alternative then carries the
  production's name.
- **Terminals.** A token kind (`IDENT`) matches any token of that kind; the
  kinds are listed in §2.1. A quoted terminal matches a token whose source
  spelling is exactly the quoted text: a keyword, an operator, a delimiter, or a
  `#` directive. A contextual terminal (`'sync'`) matches an `IDENT` token whose
  text is the quoted word; the word stays an ordinary identifier everywhere the
  grammar does not ask for it.
- **Operators.** `?` is optional, `*` is zero or more, `+` is one or more, and
  parentheses group; inside a group, `|` separates choices. `ε` is the empty
  sequence.
- **Order.** Alternatives are unordered. Where two alternatives can match the
  same tokens, the disambiguation table (§13) decides, and names the rule that
  does.
- **Status.** `current` is the language as specified today. `lockdown` is new
  or changed by SL:borrowing, SL:testing or SL:architecture, or by a ruling on
  this grammar recorded on SL-400; its `ref=` names the document section or
  the ruling. `retired` still
  parses, and a later stage refuses it with a hint naming the new spelling.
  `removed` is a spelling the parser recognizes only to refuse it with a
  dedicated diagnostic, whether it was valid once or never; §10 says why each
  is refused. `pending` awaits a ruling, and the production shows the proposed
  spelling. An alternative that refers to a production whose status is not
  `current` carries that production's status too.
- **Tokens, not characters.** The grammar is over the token stream of §2, after
  the newline rules of §2.4 have removed the insignificant `NEWLINE` tokens.
  Every other `NEWLINE` token is visible to the grammar and is written where it
  may appear.
- **Contexts.** The nonterminal `head-expr` derives exactly what `expr` derives.
  It marks a head position, where the parser applies the head restriction of
  §12: a `{` at the outer level begins the construct's body, never a trailing
  closure.

**Start symbols.** `source-file` is a source file. `interp-segment` is the text
of one interpolation inside a string literal, parsed on its own (§2.5).
`refusal-unit` is the body of an `@test(refuses: …)` case, parsed on its own in
a test build (§4).

## 2. Lexical layer

The lexer turns bytes into tokens by longest match. Every token carries a kind,
its source spelling and its position. Whitespace other than line breaks
separates tokens and is otherwise discarded; a carriage return counts as
whitespace, so CRLF files lex like LF files.

### 2.1 Token kinds

| kind | spelling | notes |
|---|---|---|
| IDENT | an ASCII letter or `_`, then ASCII letters, digits and `_` | Keywords (§2.2) are not identifiers. Contextual words are. `_` alone is an identifier. Identifiers are ASCII only (syntax.lex.ascii-identifier). |
| INT | decimal digits, or `0x`, `0b`, `0o` and digits of that base, with `_` separators, and an optional width suffix | Suffixes are `i8 i16 i32 i64 u8 u16 u32 u64`, optionally after one `_`. |
| FLOAT | digits, `.`, digits | A digit is required on both sides of the point. There is no exponent and no suffix. |
| STRING | `"…"` with no interpolation | The token's value is the decoded content. |
| INTERP_STRING | `"…{…}…"` | The token carries typed segments (§2.5). |
| DOLLAR_PARAM | `$` then digits | A closure's shorthand parameter, `$0`. |
| NEWLINE | a line break outside a string literal | Significant unless §2.4 removes it. |
| EOF | end of input | |
| SHL | two `<` tokens with nothing between them, in expression position | Formed by the parser, not the lexer (§2.7). |
| SHR | two `>` tokens with nothing between them, in expression position | Formed by the parser, not the lexer (§2.7). |
| NON_BRACE | any token except `{`, `}` and EOF | Used only by the brace matcher of a refusal case body (§4). |

Every keyword, operator and delimiter is a token of its own and is written in
the grammar as a quoted terminal:

| class | spellings |
|---|---|
| arithmetic | `+` `-` `*` `/` `%` `&+` `&-` `&*` |
| comparison | `==` `!=` `<` `>` `<=` `>=` |
| logical and bitwise | `&&` `\|\|` `&` `\|` `^` `~` |
| assignment | `=` `+=` `-=` `*=` `/=` `%=` `&=` `\|=` `^=` `<<=` `>>=` |
| optional | `?` `??` `?.` `!` |
| range | `..` `..=` |
| delimiters | `(` `)` `{` `}` `[` `]` `,` `:` `;` `->` `.` `...` `@` |
| directives | `#file` `#line` `#function` `#lend_var` |

The lexer has no `<<` or `>>` token, so that `Vector<Vector<Int>>` closes two
lists. `<<=` and `>>=` are single tokens. `...` ends a variadic extern parameter
list; between two operands it is refused, since a range is `..` or `..=`
(syntax.expr.refused-ellipsis-range).

### 2.2 Keywords and contextual words

These words are keywords. The lexer never produces an `IDENT` for them, so they
cannot name anything:

`as` `borrows` `break` `case` `catch` `continue` `else` `enum` `extension`
`extern` `false` `for` `func` `guard` `if` `in` `init` `lend` `let` `match`
`move` `None` `not` `public` `return` `self` `static` `struct` `trait` `true`
`try` `unsafe` `var` `while`

These words have a meaning in one position and are ordinary identifiers
everywhere else:

| word | position | production |
|---|---|---|
| `import` `export` `module` | the head of a top-level item; `export` only to be refused | syntax.decl.import, syntax.decl.refused-export, syntax.decl.module |
| `package` `parent` | inside `public(…)` | syntax.decl.visibility |
| `private` | before a struct field's name | syntax.decl.field-visibility |
| `type` | followed by a name, at a declaration head | syntax.decl.type-alias, syntax.decl.assoc-type, syntax.decl.type-assign |
| `const` | followed by a name, in a generic parameter list; in a declaration head before `func` or `init`, or before a name at a top-level item's head or a statement's, only to be refused | syntax.generic.param, syntax.decl.refused-effect-prefix, syntax.decl.refused-const, syntax.stmt.refused-local-const |
| `any` | followed by a name, in a type | syntax.type.any |
| `sync` `consumes` `escaping` | after a parameter list; `sync` and `consumes` also in a declaration head before `func` or `init`, only to be refused | syntax.decl.effects, syntax.type.func-effects, syntax.decl.refused-effect-prefix |
| `constexpr` | after a parameter list; in a declaration head before `func` or `init`, only to be refused | syntax.decl.constexpr, syntax.decl.refused-effect-prefix |
| `blocking` | before `func` in an extern block | syntax.decl.extern-func |
| `copy` | a capture-list mode | syntax.expr.capture |
| `lends` | followed by `self` or a name | syntax.expr.lends |
| `borrow` | followed by `let` or `var` | syntax.borrow.place, syntax.borrow.block, syntax.borrow.unwrap, syntax.borrow.for, syntax.pat.borrow-binding |
| `static_assert` | followed by `(` | syntax.decl.static-assert |
| `sizeof` `alignof` | in a const-generic argument | syntax.const.layout-query |
| `_` | a pattern or a discarded binding | syntax.pat.wildcard, syntax.stmt.refused-var-discard |
| `export` `section` `synthesize` `align` `test` | after `@` | syntax.attr.attribute, syntax.test.case |
| `shared` | inside `@synthesize(…)` | syntax.attr.synthesize-shared |
| `panics` `refuses` `warns` `text` `at` `none` | inside `@test(…)` | syntax.test.panics, syntax.test.refuses, syntax.test.warns, syntax.test.text, syntax.test.at |

`deinit`, `Self`, `Void`, `Never` and the primitive type names are ordinary
identifiers. The planned reservations `and`, `defer`, `do`, `generic`, `macro`,
`none`, `or`, `some` and `where` are not enforced.

### 2.3 Literals

- **Integers.** An integer literal is a non-negative number; a leading `-` is a
  separate token. It must fit in 64 unsigned bits, or in its suffix's width.
  Digits right after a member `.` are a tuple index: a decimal integer that
  takes no second `.`, no base prefix and no suffix, so `t.0.1` is two index
  hops and not the float `0.1`.
- **Floats.** A `.` continues a number only when a digit follows it, so
  `7.to_string()` is a call on `7`, `1..=9` is a range, and `7e5` is the
  integer `7` followed by the identifier `e5`.
- **Strings.** A string literal may span lines. Its escapes are `\\`, `\"`,
  `\n`, `\t`, `\r`, `\0`, `\u{…}` with one to six hex digits naming a Unicode
  scalar, and `\{` and `\}` for literal braces. Any other escape is an error.
- **Directives.** `#file`, `#line` and `#function` are literals. `#lend_var` is
  lexed so that the parser can refuse it (§11). Any other `#name` is an error.

### 2.4 Newlines

Newlines are tokens. Whether one ends a statement is the parser's decision:

1. A `NEWLINE` whose innermost enclosing bracket is `(` or `[` is
   insignificant. A `{` inside the brackets restores significance, so a closure
   passed as an argument still separates its statements with newlines. The
   bracket structure is computed over the whole token stream.
2. Inside a generic list the parser has committed to (§13,
   syntax.rule.generic-or-less), every `NEWLINE` is insignificant.
3. A `NEWLINE` directly after an infix operator of the expression tiers is
   insignificant, so a line ending in `+`, `&&` or `??` continues. A line that
   starts with an operator or a `.` does not continue the line before it; a
   leading `.name` is an implicit member (§7.4).
4. Every other `NEWLINE` is a token the grammar sees. The grammar writes
   `NEWLINE*` where line breaks are allowed: before a body's `{`, around `else`
   and `catch`, and inside the brace-delimited lists of fields, cases, arms,
   imported names and literal entries.

A line break directly after `=`, after `->` in a match arm, or after `return`
ends that construct.

### 2.5 Interpolation

An unescaped `{` in a string literal opens an interpolation. The lexer finds its
end by counting braces, and records the literal as segments: text segments,
with escapes decoded, and expression segments, holding the raw text between the
braces and the position of the opening `{`. The lexer does not treat quotes or
comments inside the braces specially.

Each expression segment is lexed and parsed on its own with the start symbol
`interp-segment`. A blank segment is a format placeholder, `{}`. Positions in a
segment are source positions, and its nesting depth continues from the
string's. Head restrictions do not carry into a segment.

### 2.6 Comments and documentation

`//` starts a comment that runs to the end of the line. There are no block
comments.

A comment that starts its line with exactly `///` is a doc comment, and one
that starts its line with `//!` is a module doc comment. Both are trivia: they
never enter the token stream, and are attached by position. A run of `///`
lines documents the next declaration: a `func`, `struct`, `enum`, `trait`,
`extension`, `type` alias or `static`, a struct field, an enum case, a method or
`init`, or a trait requirement. Attributes and `public` between the comment and
the declaration do not matter. A test case is not documentable, so a `///` run
before one is an error. `//!` lines are legal only before the file's first
token. A doc comment that documents nothing is an error. `////` and a
`///` after code on the same line are ordinary comments.

### 2.7 Lexical rules

| rule | statement | source |
|---|---|---|
| syntax.lex.longest-match | The lexer takes the longest token at each position. `o!= 5` is a comparison and `a&-b` is a wrapping subtraction, and a warning flags both. `Vector<Int>= v` lexes `>=`, which the parser splits where it closes a generic list (syntax.rule.generic-close-split). | Appendix B: Operators |
| syntax.lex.ascii-identifier | An identifier is ASCII: letters `A` to `Z` and `a` to `z`, digits and `_`. A letter outside ASCII cannot start or continue one, so it is an error outside a string literal or a comment. | SL-400 c6 |
| syntax.lex.shift-adjacent | A shift is two `<` or two `>` tokens in expression position with no space between them. With a space they are an error, never a comparison. | Bitwise and Shift Operators |
| syntax.lex.double-question | In a type, a `??` token is two optional layers. In an expression it is the coalescing operator. | Optionals |
| syntax.lex.tuple-index | Digits after a member `.` are a tuple index (§2.3). | Composite Types |
| syntax.lex.float-point | `7.` and `.5` are refused with a hint naming `7.0` and `0.5`. | Primitive Types |
| syntax.lex.int-range | An integer literal must fit in 64 unsigned bits, or in its suffix's width. | Primitive Types |
| syntax.lex.escape | An unknown escape, or a `\u{…}` that is a surrogate, exceeds 0x10FFFF or has no digits, is an error at the escape. | String |
| syntax.lex.unterminated-string | An unterminated string is reported at its opening quote. When an interpolation inside it holds an odd number of unescaped quotes outside comments, so that the brace swallowed the literal's closing quote, the stray `{` is reported instead. | String |
| syntax.lex.directive | `#` must be followed by `file`, `line`, `function` or `lend_var`. | Source-location literals |
| syntax.lex.unclosed-bracket | An unclosed `(`, `[` or `{` is reported at its opener. | Layout |
| syntax.lex.doc-attach | A doc comment attaches to the next documentable declaration, and one that documents nothing is an error (§2.6). | Doc comments |
| syntax.lex.module-doc | `//!` is legal only before the first token. | Doc comments |

## 3. Files and declarations

A file is a list of top-level items, one per line. Items are never joined by
`;`, and two on one line are refused (§13, syntax.rule.declaration-separator).

```ebnf
# syntax.file.source  status=current  spec="Statement Boundaries"  node=File
source-file ::= NEWLINE* top-level-list? EOF

# syntax.file.list  status=current  spec="Statement Boundaries"  node=-
top-level-list ::= top-level-item ( NEWLINE+ top-level-item )* NEWLINE*

# syntax.file.item  status=current  spec="8. Module System"  node=-
top-level-item ::= import-decl  @syntax.file.item.import
    | module-decl  @syntax.file.item.module
    | static-assert  @syntax.file.item.static-assert
    | declaration-item  @syntax.file.item.declaration
    | test-item  @syntax.file.item.test
    | refused-export  @syntax.file.item.refused-export
    | refused-const  @syntax.file.item.refused-const
    | refused-unsafe-prefix  @syntax.file.item.refused-unsafe
    | refused-visibility-prefix  @syntax.file.item.refused-visibility
```

A declaration may carry attributes and a visibility. Which attribute is legal
on which declaration is the attribute position rule (§13,
syntax.rule.attribute-position).

```ebnf
# syntax.decl.item  status=current  spec="Visibility"  node=-
declaration-item ::= attribute-list? visibility? func-decl  @syntax.decl.item.func
    | attribute-list? visibility? static-decl  @syntax.decl.item.static
    | attribute-list? extension-decl  @syntax.decl.item.extension
    | visibility? struct-decl  @syntax.decl.item.struct
    | visibility? enum-decl  @syntax.decl.item.enum
    | visibility? trait-decl  @syntax.decl.item.trait
    | visibility? type-alias-decl  @syntax.decl.item.type-alias
    | extern-block  @syntax.decl.item.extern
    | refused-static  @syntax.decl.item.refused-static
    | refused-array-extension  @syntax.decl.item.refused-array-extension
    | refused-effect-prefix  @syntax.decl.item.refused-effect-prefix

# syntax.decl.visibility  status=current  spec="Visibility"  node=Visibility
visibility ::= "public"  @syntax.decl.visibility.public
    | "public" "(" 'package' ")"  @syntax.decl.visibility.package
    | "public" "(" 'parent' ")"  @syntax.decl.visibility.parent
```

### 3.1 Imports and modules

`public import` is the one re-export form; an `export` declaration is refused
(§10).

```ebnf
# syntax.decl.import  status=current  spec="Imports"  node=Import
import-decl ::= 'import' import-target  @syntax.decl.import.private
    | "public" 'import' import-target  @syntax.decl.import.reexport
    | refused-scoped-import  @syntax.decl.import.refused-scoped

# syntax.decl.import-target  status=current  spec="Imports"  node=-
import-target ::= path  @syntax.decl.import-target.module
    | path "as" IDENT  @syntax.decl.import-target.module-alias
    | path "." "*"  @syntax.decl.import-target.glob
    | path "." "{" NEWLINE* import-symbol-list? "}"  @syntax.decl.import-target.selective

# syntax.decl.import-symbols  status=current  spec="Imports"  node=-
import-symbol-list ::= import-symbol ( "," NEWLINE* import-symbol )* ( "," NEWLINE* )?

# syntax.decl.import-symbol  status=current  spec="Imports"  node=ImportSymbol
import-symbol ::= IDENT NEWLINE*  @syntax.decl.import-symbol.name
    | IDENT "as" IDENT NEWLINE*  @syntax.decl.import-symbol.alias

# syntax.decl.module  status=current  spec="Module Declaration"  node=ModuleDecl
module-decl ::= "public"? 'module' IDENT  @syntax.decl.module.file
    | "public"? 'module' IDENT NEWLINE* "{" NEWLINE* top-level-list? "}"  @syntax.decl.module.inline

# syntax.decl.static-assert  status=current  spec="Compile-Time Evaluation"  node=StaticAssert
static-assert ::= 'static_assert' "(" expr "," STRING ")"
```

A module path's first segment may be `package` or `parent`; that is resolution's
concern, and both are identifiers here.

```ebnf
# syntax.type.path  status=current  spec="Imports"  node=Path
path ::= IDENT ( "." IDENT )*
```

### 3.2 Functions and effects

```ebnf
# syntax.decl.func  status=current  spec="Functions"  node=Func
func-decl ::= "func" IDENT generic-params? "(" param-list? ")" effect-slot return-clause? NEWLINE* block

# syntax.decl.params  status=current  spec="Functions"  node=-
param-list ::= param ( "," param )* ","?

# syntax.decl.param  status=current  spec="Functions"  node=Param
param ::= IDENT ":" type  @syntax.decl.param.plain
    | IDENT ":" type "=" expr  @syntax.decl.param.default
    | receiver  @syntax.decl.param.receiver
    | refused-receiver  @syntax.decl.param.refused-receiver

# syntax.decl.receiver  status=current  spec="Type Extensions"  node=Receiver
receiver ::= "&" "self"  @syntax.decl.receiver.shared
    | "&" "var" "self"  @syntax.decl.receiver.exclusive

# syntax.decl.return  status=current  spec="Functions"  node=-
return-clause ::= "->" type
```

The effect slot follows the parameter list. Its words appear in one order, each
at most once (§13, syntax.rule.effect-slot). `constexpr` declares a function
that compile-time evaluation may call, and takes `sync`'s place in the order.
It implies `sync`. `constexpr sync`, `unsafe constexpr` and `constexpr borrows`
parse, and a later stage refuses each with a hint. `constexpr` stands in every
effect slot, a trait requirement's included, where a later stage refuses it; a
function type does not take it. An effect word written in a declaration head,
before `func` or `init`, is refused wherever it stands there
(syntax.decl.refused-effect-prefix).

```ebnf
# syntax.decl.effects  status=current  spec="Consuming method receivers (`consumes`)"  node=-
effect-slot ::= 'consumes'? "unsafe"? constexpr-effect? 'sync'? borrows-effect? refused-escaping?

# syntax.decl.constexpr  status=lockdown  spec="Compile-Time Evaluation"  node=-  ref="SL:architecture §3.10"
constexpr-effect ::= 'constexpr'

# syntax.decl.borrows-effect  status=current  spec="Places (`borrows` and `lend`)"  node=-
borrows-effect ::= "borrows"  @syntax.decl.borrows-effect.plain
    | borrows-sync-effect  @syntax.decl.borrows-effect.sync

# syntax.decl.borrows-sync  status=lockdown  spec="Places (`borrows` and `lend`)"  node=-  ref="SL:borrowing §2.5"
borrows-sync-effect ::= "borrows" "(" 'sync' ")"
```

### 3.3 Structs and enums

A struct's fields, and an enum's cases, are separated by a comma, a line break,
or both, so two on one line need a comma between them (§14).

```ebnf
# syntax.decl.struct  status=current  spec="Structs"  node=Struct
struct-decl ::= struct-modifier? "struct" IDENT generic-params? NEWLINE* "{" NEWLINE* field-list? "}"

# syntax.decl.struct-modifier  status=current  spec="Borrowing structs"  node=-
struct-modifier ::= "unsafe"  @syntax.decl.struct-modifier.unsafe
    | "borrows"  @syntax.decl.struct-modifier.borrows

# syntax.decl.fields  status=current  spec="Structs"  node=-
field-list ::= field ( list-sep field )* list-sep?

# syntax.decl.list-sep  status=current  spec="Statement Boundaries"  node=-
list-sep ::= "," NEWLINE*  @syntax.decl.list-sep.comma
    | NEWLINE+  @syntax.decl.list-sep.newline
    | NEWLINE+ "," NEWLINE*  @syntax.decl.list-sep.newline-comma

# syntax.decl.field  status=current  spec="Member visibility"  node=Field
field ::= field-visibility? IDENT ":" type

# syntax.decl.field-visibility  status=current  spec="Member visibility"  node=Visibility
field-visibility ::= visibility  @syntax.decl.field-visibility.public
    | 'private'  @syntax.decl.field-visibility.private

# syntax.decl.enum  status=current  spec="Enums (Algebraic Data Types)"  node=Enum
enum-decl ::= "enum" IDENT generic-params? raw-backing? NEWLINE* "{" NEWLINE* case-list? "}"

# syntax.decl.raw-backing  status=current  spec="Raw-backed enums"  node=-
raw-backing ::= ":" type

# syntax.decl.cases  status=current  spec="Enums (Algebraic Data Types)"  node=-
case-list ::= enum-case ( list-sep enum-case )* list-sep?

# syntax.decl.case  status=current  spec="Enums (Algebraic Data Types)"  node=Case
enum-case ::= "case" IDENT payload-decl? raw-value?

# syntax.decl.payload  status=current  spec="Enums (Algebraic Data Types)"  node=-
payload-decl ::= "(" ( payload-field ( "," payload-field )* ","? )? ")"

# syntax.decl.payload-field  status=current  spec="Enums (Algebraic Data Types)"  node=PayloadField
payload-field ::= IDENT ":" type

# syntax.decl.raw-value  status=current  spec="Raw-backed enums"  node=-
raw-value ::= "=" expr
```

### 3.4 Traits and extensions

An extension head and a trait's parent list take qualified paths, as every
other position that names a type does. A trait requirement takes generic
parameters as a method does, and a later stage refuses them.

```ebnf
# syntax.decl.trait  status=current  spec="Traits"  node=Trait
trait-decl ::= "trait" IDENT generic-params? trait-parents? NEWLINE* "{" NEWLINE* trait-member-list? "}"

# syntax.decl.trait-parents  status=current  spec="Traits"  node=-
trait-parents ::= ":" path ( "," path )*

# syntax.decl.trait-members  status=current  spec="Traits"  node=-
trait-member-list ::= trait-member ( NEWLINE+ trait-member )* NEWLINE*

# syntax.decl.trait-member  status=current  spec="Traits"  node=-
trait-member ::= assoc-type-decl  @syntax.decl.trait-member.assoc-type
    | requirement  @syntax.decl.trait-member.requirement
    | refused-effect-prefix  @syntax.decl.trait-member.refused-effect-prefix
    | refused-member-private  @syntax.decl.trait-member.refused-private

# syntax.decl.assoc-type  status=current  spec="Traits"  node=AssocType
assoc-type-decl ::= 'type' IDENT

# syntax.decl.requirement  status=current  spec="Traits"  node=Requirement
requirement ::= "static"? "func" IDENT generic-params? "(" param-list? ")" effect-slot return-clause? default-body?

# syntax.decl.default-body  status=current  spec="Traits"  node=-
default-body ::= NEWLINE* block

# syntax.decl.extension  status=current  spec="Type Extensions"  node=Extension
extension-decl ::= "extension" path generic-params? conformance-list? NEWLINE* "{" NEWLINE* extension-member-list? "}"

# syntax.decl.conformances  status=current  spec="Traits"  node=-
conformance-list ::= ":" path ( "," path )*

# syntax.decl.extension-members  status=current  spec="Type Extensions"  node=-
extension-member-list ::= extension-member ( NEWLINE+ extension-member )* NEWLINE*

# syntax.decl.extension-member  status=current  spec="Type Extensions"  node=-
extension-member ::= type-assign-decl  @syntax.decl.extension-member.type-assign
    | visibility? method-decl  @syntax.decl.extension-member.method
    | synthesize-shared-attr visibility? method-decl  @syntax.decl.extension-member.synthesized-method
    | visibility? init-decl  @syntax.decl.extension-member.init
    | refused-effect-prefix  @syntax.decl.extension-member.refused-effect-prefix
    | refused-member-static  @syntax.decl.extension-member.refused-static
    | refused-member-private  @syntax.decl.extension-member.refused-private

# syntax.decl.type-assign  status=current  spec="Traits"  node=TypeAssign
type-assign-decl ::= 'type' IDENT "=" type

# syntax.decl.method  status=current  spec="Static methods"  node=Method
method-decl ::= "static"? "func" method-name generic-params? "(" param-list? ")" effect-slot return-clause? NEWLINE* block

# syntax.decl.method-name  status=current  spec="Places (`borrows` and `lend`)"  node=-
method-name ::= IDENT  @syntax.decl.method-name.ident
    | "[" "]"  @syntax.decl.method-name.subscript
    | setitem-name  @syntax.decl.method-name.setitem

# syntax.decl.setitem-name  status=lockdown  spec="Places (`borrows` and `lend`)"  node=-  ref="SL:borrowing §5.1"
setitem-name ::= "[" "]" "="

# syntax.decl.init  status=current  spec="What an `init` may return"  node=Init
init-decl ::= "init" "(" param-list? ")" effect-slot return-clause? NEWLINE* block
```

The three subscript roles are ordinary methods named by `method-name`: a getitem
`func [](&self, …) -> V` and a setitem `func []=(&var self, …, value: V)`,
beside the place accessor `func [](…) borrows -> &var V`. Which role a
declaration plays follows from its effect slot and receiver (§13,
syntax.rule.subscript-declaration).

### 3.5 Aliases, statics and externs

```ebnf
# syntax.decl.type-alias  status=current  spec="Type Definitions"  node=TypeAlias
type-alias-decl ::= 'type' IDENT "=" type

# syntax.decl.static  status=current  spec="Module-level statics"  node=Static
static-decl ::= "static" IDENT ":" type static-init?  @syntax.decl.static.immutable
    | "unsafe" "static" "var" IDENT ":" type static-init?  @syntax.decl.static.unsafe-var

# syntax.decl.static-init  status=current  spec="Module-level statics"  node=-
static-init ::= "=" expr

# syntax.decl.extern-block  status=current  spec="C FFI"  node=ExternBlock
extern-block ::= "extern" STRING NEWLINE* "{" NEWLINE* extern-func-list? "}"

# syntax.decl.extern-funcs  status=current  spec="C FFI"  node=-
extern-func-list ::= extern-func ( NEWLINE+ extern-func )* NEWLINE*

# syntax.decl.extern-func  status=current  spec="Blocking externs and the offload"  node=ExternFunc
extern-func ::= "func" IDENT "(" extern-param-list? ")" return-clause?  @syntax.decl.extern-func.prompt
    | 'blocking' "func" IDENT "(" extern-param-list? ")" return-clause?  @syntax.decl.extern-func.blocking

# syntax.decl.extern-params  status=current  spec="C FFI"  node=-
extern-param-list ::= extern-param ( "," extern-param )* ","?  @syntax.decl.extern-params.fixed
    | extern-param ( "," extern-param )* "," "..."  @syntax.decl.extern-params.variadic

# syntax.decl.extern-param  status=current  spec="C FFI"  node=Param
extern-param ::= IDENT ":" type
```

## 4. Attributes and tests

An attribute stands on the line before its declaration, or on the same line.

```ebnf
# syntax.attr.list  status=current  spec="Attributes (design 58)"  node=-
attribute-list ::= attribute+

# syntax.attr.attribute  status=current  spec="Attributes (design 58)"  node=Attribute
attribute ::= "@" 'export' NEWLINE*  @syntax.attr.attribute.export
    | "@" 'export' "(" STRING ")" NEWLINE*  @syntax.attr.attribute.export-symbol
    | "@" 'section' "(" STRING ")" NEWLINE*  @syntax.attr.attribute.section
    | "@" 'synthesize' NEWLINE*  @syntax.attr.attribute.synthesize
    | "@" 'align' "(" expr ")" NEWLINE*  @syntax.attr.attribute.align
    | synthesize-shared-attr  @syntax.attr.attribute.synthesize-shared

# syntax.attr.synthesize-shared  status=lockdown  spec="Synthesized conformances"  node=Attribute  ref="SL:borrowing §4"
synthesize-shared-attr ::= "@" 'synthesize' "(" 'shared' ")" NEWLINE*
```

`@test` decides whether a declaration exists in a given build. What follows it
decides the form: a string makes a case, `{` makes a group, and a declaration
makes that declaration test-only. The string after `panics:` always names a
panic's rule, and a user `panic("…")` has a rule of its own. An optional
`text:` adds a check on the panic's message, as it does for `refuses:`.

```ebnf
# syntax.test.item  status=lockdown  spec="Attributes (design 58)"  node=-  ref="SL:testing §2"
test-item ::= test-case  @syntax.test.item.case
    | test-group  @syntax.test.item.group
    | test-only-decl  @syntax.test.item.declaration

# syntax.test.case  status=lockdown  spec="Attributes (design 58)"  node=TestCase  ref="SL:testing §2"
test-case ::= "@" 'test' STRING NEWLINE* block  @syntax.test.case.run
    | "@" 'test' "(" test-panics ")" STRING NEWLINE* block  @syntax.test.case.panics
    | "@" 'test' "(" test-warns ")" STRING NEWLINE* block  @syntax.test.case.warns
    | "@" 'test' "(" test-refuses ")" STRING NEWLINE* refusal-body  @syntax.test.case.refuses

# syntax.test.panics  status=lockdown  spec="Attributes (design 58)"  node=-  ref="SL:testing §4"
test-panics ::= 'panics' ":" STRING test-at?  @syntax.test.panics.rule
    | panics-text  @syntax.test.panics.text

# syntax.test.panics-text  status=lockdown  spec="Attributes (design 58)"  node=-  ref="SL-400 c6"
panics-text ::= 'panics' ":" STRING test-text test-at?

# syntax.test.warns  status=lockdown  spec="Compiler warnings"  node=-  ref="SL:testing §5"
test-warns ::= 'warns' ":" STRING  @syntax.test.warns.key
    | 'warns' ":" 'none'  @syntax.test.warns.none

# syntax.test.refuses  status=lockdown  spec="Attributes (design 58)"  node=-  ref="SL:testing §5"
test-refuses ::= 'refuses' ":" STRING test-text? test-at?

# syntax.test.text  status=lockdown  spec="Attributes (design 58)"  node=-  ref="SL:testing §5"
test-text ::= "," 'text' ":" STRING

# syntax.test.at  status=lockdown  spec="Attributes (design 58)"  node=-  ref="SL:testing §5"
test-at ::= "," 'at' ":" INT

# syntax.test.group  status=lockdown  spec="Attributes (design 58)"  node=TestGroup  ref="SL:testing §2"
test-group ::= "@" 'test' NEWLINE* "{" NEWLINE* top-level-list? "}"

# syntax.test.declaration  status=lockdown  spec="Attributes (design 58)"  node=TestOnly  ref="SL:testing §2"
test-only-decl ::= "@" 'test' NEWLINE* declaration-item  @syntax.test.declaration.item
    | "@" 'test' NEWLINE* import-decl  @syntax.test.declaration.import
```

A refusal case is checked on its own. In a normal build only its braces are
matched, so its body may hold a syntax error. In a test build, the tokens
between its braces are parsed with the start symbol `refusal-unit`, which takes
declarations and statements alike.

```ebnf
# syntax.test.refusal-body  status=lockdown  spec="Attributes (design 58)"  node=RefusalBody  ref="SL:testing §5"
refusal-body ::= "{" refusal-token* "}"

# syntax.test.refusal-token  status=lockdown  spec="Attributes (design 58)"  node=-  ref="SL:testing §5"
refusal-token ::= "{" refusal-token* "}"  @syntax.test.refusal-token.nested
    | NON_BRACE  @syntax.test.refusal-token.other

# syntax.test.refusal-unit  status=lockdown  spec="Attributes (design 58)"  node=RefusalUnit  ref="SL:testing §5"
refusal-unit ::= NEWLINE* ( refusal-unit-item ( stmt-sep refusal-unit-item )* NEWLINE* )? EOF

# syntax.test.refusal-unit-item  status=lockdown  spec="Attributes (design 58)"  node=-  ref="SL:testing §5"
refusal-unit-item ::= top-level-item  @syntax.test.refusal-unit-item.declaration
    | statement  @syntax.test.refusal-unit-item.statement
```

## 5. Types and generics

A type is a reference, a function type, or an atom followed by optional-layer
suffixes. `?` wraps once, and a `??` token wraps twice, so `Int??` and
`Optional<Int?>` are one type. A reference and a function type are not atoms,
so a suffix after `&` or `->` belongs to the type that follows: `&Int?` is a
reference to an optional, and `(Int) -> Int?` returns an optional (§13,
syntax.rule.prefix-type-suffix).

```ebnf
# syntax.type.type  status=current  spec="3. Type System"  node=-
type ::= ref-type  @syntax.type.type.ref
    | func-type  @syntax.type.type.func
    | type-atom type-suffix*  @syntax.type.type.suffixed
    | refused-func-consumes  @syntax.type.type.refused-func-consumes

# syntax.type.suffix  status=current  spec="Optionals"  node=OptionalType
type-suffix ::= "?"  @syntax.type.suffix.optional
    | "??"  @syntax.type.suffix.double-optional

# syntax.type.atom  status=current  spec="3. Type System"  node=-
type-atom ::= named-type  @syntax.type.atom.named
    | slice-type  @syntax.type.atom.slice
    | array-type  @syntax.type.atom.array
    | tuple-type  @syntax.type.atom.tuple
    | single-tuple-type  @syntax.type.atom.single-tuple
    | paren-type  @syntax.type.atom.paren
    | any-type  @syntax.type.atom.any
    | refused-partial-named-tuple-type  @syntax.type.atom.refused-partial-named

# syntax.type.named  status=current  spec="Generics"  node=NamedType
named-type ::= path generic-args?

# syntax.type.ref  status=current  spec="Reference passing"  node=RefType
ref-type ::= "&" type  @syntax.type.ref.shared
    | "&" "var" type  @syntax.type.ref.exclusive

# syntax.type.slice  status=lockdown  spec="Composite Types"  node=SliceType  ref="SL:borrowing §6"
slice-type ::= "&" "[" type "]"  @syntax.type.slice.shared
    | "&" "var" "[" type "]"  @syntax.type.slice.exclusive

# syntax.type.array  status=current  spec="Composite Types"  node=ArrayType
array-type ::= "[" type ";" expr "]"

# syntax.type.tuple  status=current  spec="Composite Types"  node=TupleType
tuple-type ::= "(" ")"  @syntax.type.tuple.unit
    | "(" type ( "," type )+ ","? ")"  @syntax.type.tuple.positional
    | "(" tuple-type-field ( "," tuple-type-field )* ","? ")"  @syntax.type.tuple.named

# syntax.type.tuple-field  status=current  spec="Composite Types"  node=TupleField
tuple-type-field ::= IDENT ":" type
```

A one-element tuple type is written with its comma, `(T,)`. Without the comma,
the parentheses group, so `((Int) -> Int)?` is an optional function (§13,
syntax.rule.paren-type).

```ebnf
# syntax.type.single-tuple  status=lockdown  spec="Composite Types"  node=TupleType  ref="SL-400 c6"
single-tuple-type ::= "(" type "," ")"

# syntax.type.paren  status=lockdown  spec="Composite Types"  node=-  ref="SL-400 c6"
paren-type ::= "(" type ")"

# syntax.type.func  status=current  spec="The effect on a function type"  node=FuncType
func-type ::= "(" func-type-params? ")" func-type-effects "->" type

# syntax.type.func-params  status=current  spec="The effect on a function type"  node=-
func-type-params ::= type ( "," type )* ","?

# syntax.type.func-effects  status=current  spec="Spelling"  node=-
func-type-effects ::= "unsafe"? 'sync'? 'escaping'? func-type-borrows?

# syntax.type.func-borrows  status=lockdown  spec="Exclusivity, invalidation, and the fences"  node=-  ref="SL:borrowing §2.5"
func-type-borrows ::= "borrows"  @syntax.type.func-borrows.plain
    | "borrows" "(" 'sync' ")"  @syntax.type.func-borrows.sync

# syntax.type.any  status=current  spec="`any Trait` existentials (dynamic dispatch)"  node=AnyType
any-type ::= 'any' path
```

A cast target is a type that takes at most one `?`. A `??` token or a second
`?` after it is refused at that token, whatever the spacing (§13,
syntax.rule.cast-target-question). A reference or function type is a cast
target too, and a later stage decides which casts exist.

```ebnf
# syntax.type.cast-target  status=current  spec="Optionals"  node=-  ref="SL-309"
cast-target ::= type-atom  @syntax.type.cast-target.plain
    | type-atom "?"  @syntax.type.cast-target.optional
    | ref-type  @syntax.type.cast-target.ref
    | func-type  @syntax.type.cast-target.func
```

### 5.1 Generic parameters and arguments

A generic list ignores line breaks and takes no trailing comma. A `>=` or `>>=`
token whose `>` closes the list is split there (§13,
syntax.rule.generic-close-split).

```ebnf
# syntax.generic.params  status=current  spec="Generics"  node=-
generic-params ::= "<" generic-param ( "," generic-param )* ">"  @syntax.generic.params.list
    | refused-generic-param-comma  @syntax.generic.params.refused-comma

# syntax.generic.param  status=current  spec="Generics"  node=GenericParam
generic-param ::= IDENT bound-list? ( "=" type )?  @syntax.generic.param.type
    | 'const' IDENT ":" type ( "=" const-expr )?  @syntax.generic.param.const

# syntax.generic.bounds  status=current  spec="Traits"  node=-
bound-list ::= ":" path ( "+" path )*

# syntax.generic.args  status=current  spec="Generics"  node=-
generic-args ::= "<" generic-arg ( "," generic-arg )* ">"  @syntax.generic.args.list
    | refused-generic-arg-comma  @syntax.generic.args.refused-comma

# syntax.generic.arg  status=current  spec="Generics"  node=-
generic-arg ::= type  @syntax.generic.arg.type
    | const-expr  @syntax.generic.arg.value
```

### 5.2 Constant expressions in a generic list

A generic list is closed by `>`, so a value argument uses a smaller grammar
than an expression: integer literals, names, `+ - * / %`, unary `-`,
parentheses, and the layout queries. The bitwise operators are excluded because
`<` and `>` delimit the list. An array length and a repeat count are closed by
`]`, and take the full expression grammar.

```ebnf
# syntax.const.expr  status=current  spec="Generics"  node=Binary
const-expr ::= const-term ( const-add-op const-term )*

# syntax.const.add-op  status=current  spec="Generics"  node=-
const-add-op ::= "+"  @syntax.const.add-op.plus
    | "-"  @syntax.const.add-op.minus

# syntax.const.term  status=current  spec="Generics"  node=Binary
const-term ::= const-unary ( const-mul-op const-unary )*

# syntax.const.mul-op  status=current  spec="Generics"  node=-
const-mul-op ::= "*"  @syntax.const.mul-op.times
    | "/"  @syntax.const.mul-op.divide
    | "%"  @syntax.const.mul-op.remainder

# syntax.const.unary  status=current  spec="Generics"  node=Unary
const-unary ::= "-" const-unary  @syntax.const.unary.negate
    | const-atom  @syntax.const.unary.atom

# syntax.const.atom  status=current  spec="Generics"  node=-
const-atom ::= int-literal  @syntax.const.atom.int
    | path  @syntax.const.atom.name
    | "(" const-expr ")"  @syntax.const.atom.group
    | layout-query  @syntax.const.atom.layout

# syntax.const.layout-query  status=current  spec="Layout in a constant"  node=Call
layout-query ::= 'sizeof' generic-args "(" ")"  @syntax.const.layout-query.size
    | 'alignof' generic-args "(" ")"  @syntax.const.layout-query.align
```

## 6. Statements

A block is a list of statements. Two statements are separated by a line break,
or by `;` when they share a line. A `;` never ends a statement, and two
statements on one line with nothing between them are refused (§13,
syntax.rule.statement-separator). A block's last statement, when it is an
expression statement, is the block's tail: its value (§13,
syntax.rule.block-tail). There is no bare block statement; a `{` at the start of
a statement opens a closure literal.

```ebnf
# syntax.stmt.block  status=current  spec="Statement Boundaries"  node=Block
block ::= "{" block-body "}"

# syntax.stmt.body  status=current  spec="Statement Boundaries"  node=-
block-body ::= NEWLINE* ( statement ( stmt-sep statement )* NEWLINE* )?

# syntax.stmt.sep  status=current  spec="Statement Boundaries"  node=-
stmt-sep ::= ";"  @syntax.stmt.sep.semicolon
    | NEWLINE+  @syntax.stmt.sep.newline

# syntax.stmt.statement  status=current  spec="Statement Boundaries"  node=-
statement ::= expr-stmt  @syntax.stmt.statement.expr
    | non-expr-statement  @syntax.stmt.statement.other

# syntax.stmt.expr  status=current  spec="Statement Boundaries"  node=ExprStmt
expr-stmt ::= expr

# syntax.stmt.non-expr  status=current  spec="Statement Boundaries"  node=-
non-expr-statement ::= let-stmt  @syntax.stmt.non-expr.let
    | destructure-stmt  @syntax.stmt.non-expr.destructure
    | assign-stmt  @syntax.stmt.non-expr.assign
    | compound-assign-stmt  @syntax.stmt.non-expr.compound-assign
    | optional-assign-stmt  @syntax.stmt.non-expr.optional-assign
    | return-stmt  @syntax.stmt.non-expr.return
    | break-stmt  @syntax.stmt.non-expr.break
    | continue-stmt  @syntax.stmt.non-expr.continue
    | lend-stmt  @syntax.stmt.non-expr.lend
    | guard-stmt  @syntax.stmt.non-expr.guard
    | static-assert  @syntax.stmt.non-expr.static-assert
    | attributed-local  @syntax.stmt.non-expr.attributed-local
    | refused-var-discard  @syntax.stmt.non-expr.refused-var-discard
    | refused-uninitialized  @syntax.stmt.non-expr.refused-uninitialized
    | refused-local-type-alias  @syntax.stmt.non-expr.refused-local-type-alias
    | refused-local-const  @syntax.stmt.non-expr.refused-local-const
    | refused-compound-self  @syntax.stmt.non-expr.refused-compound-self
    | refused-bare-lend  @syntax.stmt.non-expr.refused-bare-lend
```

### 6.1 Bindings

Every binding is initialized where it is declared. `_` as the name discards the
value.

```ebnf
# syntax.stmt.let  status=current  spec="Variables and Mutability"  node=Let
let-stmt ::= "let" binding-name type-annotation? "=" expr  @syntax.stmt.let.immutable
    | "var" binding-name type-annotation? "=" expr  @syntax.stmt.let.mutable

# syntax.stmt.type-annotation  status=current  spec="Variables and Mutability"  node=-
type-annotation ::= ":" type

# syntax.stmt.destructure  status=current  spec="Composite Types"  node=DestructureLet
destructure-stmt ::= "let" tuple-pattern "=" expr  @syntax.stmt.destructure.immutable
    | "var" tuple-pattern "=" expr  @syntax.stmt.destructure.mutable

# syntax.stmt.binding-name  status=current  spec="Variables and Mutability"  node=BindingName
binding-name ::= IDENT

# syntax.stmt.binding-target  status=current  spec="Optionals"  node=-
binding-target ::= binding-name  @syntax.stmt.binding-target.name
    | tuple-pattern  @syntax.stmt.binding-target.tuple

# syntax.stmt.attributed-local  status=current  spec="Alignment"  node=-
attributed-local ::= attribute-list let-stmt
```

### 6.2 Assignment

Assignment is a statement, never an expression. Its right side starts on the
line of its `=`. The target is parsed as an expression and must have one of the
place shapes below (§13, syntax.rule.assignment-target).

```ebnf
# syntax.stmt.assign  status=current  spec="Reference passing"  node=Assign
assign-stmt ::= assign-target "=" expr

# syntax.stmt.compound-assign  status=current  spec="Bitwise and Shift Operators"  node=CompoundAssign
compound-assign-stmt ::= compound-target compound-op expr

# syntax.stmt.compound-op  status=current  spec="Bitwise and Shift Operators"  node=-
compound-op ::= "+="  @syntax.stmt.compound-op.add
    | "-="  @syntax.stmt.compound-op.subtract
    | "*="  @syntax.stmt.compound-op.multiply
    | "/="  @syntax.stmt.compound-op.divide
    | "%="  @syntax.stmt.compound-op.remainder
    | "&="  @syntax.stmt.compound-op.and
    | "|="  @syntax.stmt.compound-op.or
    | "^="  @syntax.stmt.compound-op.xor
    | "<<="  @syntax.stmt.compound-op.shift-left
    | ">>="  @syntax.stmt.compound-op.shift-right

# syntax.stmt.assign-target  status=current  spec="Writing through a place"  node=-
assign-target ::= name-ref  @syntax.stmt.assign-target.name
    | self-expr  @syntax.stmt.assign-target.self
    | projection-target  @syntax.stmt.assign-target.projection
    | deref-expr  @syntax.stmt.assign-target.deref
    | borrow-place  @syntax.stmt.assign-target.borrow
    | call-target  @syntax.stmt.assign-target.call

# syntax.stmt.compound-target  status=current  spec="Writing through a place"  node=-
compound-target ::= name-ref  @syntax.stmt.compound-target.name
    | projection-target  @syntax.stmt.compound-target.projection
    | deref-expr  @syntax.stmt.compound-target.deref
    | borrow-place  @syntax.stmt.compound-target.borrow
    | call-target  @syntax.stmt.compound-target.call

# syntax.stmt.projection-target  status=current  spec="Writing through a place"  node=-
projection-target ::= primary-expr postfix-hop* place-hop

# syntax.stmt.place-hop  status=current  spec="Writing through a place"  node=-
place-hop ::= member-hop  @syntax.stmt.place-hop.member
    | tuple-index-hop  @syntax.stmt.place-hop.tuple-index
    | subscript-hop  @syntax.stmt.place-hop.subscript
    | force-hop  @syntax.stmt.place-hop.force

# syntax.stmt.call-target  status=retired  spec="Writing through a place"  node=-  ref="SL:borrowing §9"
call-target ::= primary-expr postfix-hop* call-hop
```

An assignment whose target ends in an open optional chain writes through the
chain and has type `Void?` (§13, syntax.rule.optional-chain-run). As a statement
its value is discarded; as the subject of `if let` or `guard let` it is tested.

```ebnf
# syntax.stmt.optional-assign  status=current  spec="Optionals"  node=OptionalAssign
optional-assign-stmt ::= optional-chain-target "=" expr  @syntax.stmt.optional-assign.plain
    | optional-chain-target compound-op expr  @syntax.stmt.optional-assign.compound
    | borrow-optional-target "=" expr  @syntax.stmt.optional-assign.borrow-plain
    | borrow-optional-target compound-op expr  @syntax.stmt.optional-assign.borrow-compound

# syntax.stmt.optional-chain-target  status=current  spec="Optionals"  node=-
optional-chain-target ::= primary-expr postfix-hop* optional-hop chain-hop*

# syntax.stmt.chain-hop  status=current  spec="Optionals"  node=-
chain-hop ::= member-hop  @syntax.stmt.chain-hop.member
    | optional-hop  @syntax.stmt.chain-hop.optional
    | call-hop  @syntax.stmt.chain-hop.call
    | trailing-hop  @syntax.stmt.chain-hop.trailing
```

### 6.3 Control transfer

`return` and `break` take an operand when the next token can begin one. The
tokens that end a statement are a line break, `;`, `}` and end of input, and, in
an unbraced match-arm body, `,` and `case` (§13,
syntax.rule.arm-statement-end).

```ebnf
# syntax.stmt.return  status=current  spec="Control Flow"  node=Return
return-stmt ::= "return" expr?

# syntax.stmt.break  status=current  spec="Diverging loops"  node=Break
break-stmt ::= "break" expr?

# syntax.stmt.continue  status=current  spec="Control Flow"  node=Continue
continue-stmt ::= "continue"

# syntax.stmt.lend  status=current  spec="`lend` suspends the accessor; it does not return"  node=Lend
lend-stmt ::= "lend" expr
```

### 6.4 Guard

A `guard` takes an optional binding or a boolean condition. Its `else` block
must leave the enclosing scope, which a later stage checks. A `guard` takes no
borrow binding.

```ebnf
# syntax.stmt.guard  status=current  spec="Control Flow"  node=Guard
guard-stmt ::= "guard" "let" binding-target "=" binding-subject NEWLINE* "else" NEWLINE* block  @syntax.stmt.guard.let
    | "guard" "var" binding-target "=" binding-subject NEWLINE* "else" NEWLINE* block  @syntax.stmt.guard.var
    | guard-condition  @syntax.stmt.guard.condition

# syntax.stmt.guard-condition  status=lockdown  spec="Control Flow"  node=Guard  ref="SL-400 c6"
guard-condition ::= "guard" head-expr NEWLINE* "else" NEWLINE* block

# syntax.stmt.binding-subject  status=current  spec="Optionals"  node=-
binding-subject ::= head-expr  @syntax.stmt.binding-subject.value
    | optional-chain-target "=" expr  @syntax.stmt.binding-subject.chain-assign
    | borrow-optional-target "=" expr  @syntax.stmt.binding-subject.borrow-chain-assign
```

## 7. Expressions

### 7.1 Precedence

Tighter tiers are higher in the table. Each binary tier is a flat chain: one
node holding every operand of the chain and the operator between each pair, so
the tree's depth follows source nesting, not chain length (§13,
syntax.rule.flat-chains). Postfix chains stay nested, one node per hop.

| tier | operators | associativity | production |
|---|---|---|---|
| 1 | call `(…)`, trailing closure, subscript `[…]`, member `.name`, tuple index `.0`, optional member `?.name`, force `!` | left, nested | syntax.expr.postfix |
| 2 | prefix `-` `not` `~` `*` `&` `&var` `move` `try` `try?` `try!` `lends` `borrow let` `borrow var` | prefix | syntax.expr.prefix |
| 3 | `as` | left, nested | syntax.expr.cast |
| 4 | `*` `/` `%` `&*` | left, flat | syntax.expr.multiplicative |
| 5 | `+` `-` `&+` `&-` | left, flat | syntax.expr.additive |
| 6 | `<<` `>>` | left, flat | syntax.expr.shift |
| 7 | `..` `..=` | none | syntax.expr.range |
| 8 | `==` `!=` `<` `>` `<=` `>=` | none | syntax.expr.compare |
| 9 | `&` | left, flat | syntax.expr.bitand |
| 10 | `^` | left, flat | syntax.expr.bitxor |
| 11 | `\|` | left, flat | syntax.expr.bitor |
| 12 | `&&` | left, flat | syntax.expr.and |
| 13 | `\|\|` | left, flat | syntax.expr.or |
| 14 | `??` | right, flat | syntax.expr.coalesce |

`if`, `match`, `while`, `for`, a `try` block, a `borrow` block and a closure
are primaries, so each can be an operand, an argument or a receiver.

A range may omit either bound: `a..`, `..b`, `..=b` and `..` are range
expressions, and a later stage decides which positions accept an open range.

A line that ends in an operator of tiers 4 to 14 continues onto the next line.
The prefix operators, `try` included, bind tighter than `as`
(syntax.rule.prefix-or-cast, syntax.rule.try-extent). A `??` chain is one flat
node whose operands group right to left (syntax.rule.coalesce-grouping). A
comparison takes exactly two operands, and a chain of comparisons is refused
(syntax.rule.compare-chain).

```ebnf
# syntax.expr.expr  status=current  spec="Appendix B: Operators"  node=-
expr ::= coalesce-expr

# syntax.expr.head  status=current  spec="Control Flow"  node=-
head-expr ::= expr

# syntax.expr.coalesce  status=current  spec="Optionals"  node=Coalesce
coalesce-expr ::= or-expr ( "??" NEWLINE* or-expr )*

# syntax.expr.or  status=current  spec="Appendix B: Operators"  node=Binary
or-expr ::= and-expr ( "||" NEWLINE* and-expr )*

# syntax.expr.and  status=current  spec="Appendix B: Operators"  node=Binary
and-expr ::= bitor-expr ( "&&" NEWLINE* bitor-expr )*

# syntax.expr.bitor  status=current  spec="Bitwise and Shift Operators"  node=Binary
bitor-expr ::= bitxor-expr ( "|" NEWLINE* bitxor-expr )*

# syntax.expr.bitxor  status=current  spec="Bitwise and Shift Operators"  node=Binary
bitxor-expr ::= bitand-expr ( "^" NEWLINE* bitand-expr )*

# syntax.expr.bitand  status=current  spec="Bitwise and Shift Operators"  node=Binary
bitand-expr ::= compare-expr ( "&" NEWLINE* compare-expr )*

# syntax.expr.compare  status=current  spec="Ordering (`Comparable`)"  node=Binary
compare-expr ::= range-expr ( compare-op NEWLINE* range-expr )?  @syntax.expr.compare.pair
    | refused-compare-chain  @syntax.expr.compare.refused-chain

# syntax.expr.compare-op  status=current  spec="Appendix B: Operators"  node=-
compare-op ::= "=="  @syntax.expr.compare-op.equal
    | "!="  @syntax.expr.compare-op.not-equal
    | "<"  @syntax.expr.compare-op.less
    | ">"  @syntax.expr.compare-op.greater
    | "<="  @syntax.expr.compare-op.less-equal
    | ">="  @syntax.expr.compare-op.greater-equal

# syntax.expr.range  status=current  spec="Control Flow"  node=Range
range-expr ::= shift-expr ( range-op NEWLINE* shift-expr )?  @syntax.expr.range.closed
    | range-from  @syntax.expr.range.from
    | range-upto  @syntax.expr.range.upto
    | refused-ellipsis-range  @syntax.expr.range.refused-ellipsis

# syntax.expr.range-op  status=current  spec="Control Flow"  node=-
range-op ::= ".."  @syntax.expr.range-op.exclusive
    | "..="  @syntax.expr.range-op.inclusive

# syntax.expr.range-from  status=lockdown  spec="Composite Types"  node=Range  ref="SL:borrowing §6"
range-from ::= shift-expr ".."

# syntax.expr.range-upto  status=lockdown  spec="Composite Types"  node=Range  ref="SL-400 c6"
range-upto ::= ".." shift-expr  @syntax.expr.range-upto.exclusive
    | "..=" shift-expr  @syntax.expr.range-upto.inclusive
    | ".."  @syntax.expr.range-upto.full

# syntax.expr.shift  status=current  spec="Bitwise and Shift Operators"  node=Binary
shift-expr ::= additive-expr ( shift-op NEWLINE* additive-expr )*

# syntax.expr.shift-op  status=current  spec="Bitwise and Shift Operators"  node=-
shift-op ::= SHL  @syntax.expr.shift-op.left
    | SHR  @syntax.expr.shift-op.right

# syntax.expr.additive  status=current  spec="Integer Arithmetic Semantics"  node=Binary
additive-expr ::= multiplicative-expr ( add-op NEWLINE* multiplicative-expr )*

# syntax.expr.add-op  status=current  spec="Integer Arithmetic Semantics"  node=-
add-op ::= "+"  @syntax.expr.add-op.plus
    | "-"  @syntax.expr.add-op.minus
    | "&+"  @syntax.expr.add-op.wrapping-plus
    | "&-"  @syntax.expr.add-op.wrapping-minus

# syntax.expr.multiplicative  status=current  spec="Integer Arithmetic Semantics"  node=Binary
multiplicative-expr ::= cast-expr ( mul-op NEWLINE* cast-expr )*

# syntax.expr.mul-op  status=current  spec="Integer Arithmetic Semantics"  node=-
mul-op ::= "*"  @syntax.expr.mul-op.times
    | "/"  @syntax.expr.mul-op.divide
    | "%"  @syntax.expr.mul-op.remainder
    | "&*"  @syntax.expr.mul-op.wrapping-times

# syntax.expr.cast  status=current  spec="Integer Conversions"  node=Cast
cast-expr ::= prefix-expr cast-suffix*

# syntax.expr.cast-suffix  status=current  spec="Address casts (`&T` → pointer, pointer ↔ `Int`)"  node=-
cast-suffix ::= "as" cast-target  @syntax.expr.cast-suffix.cast
    | "as" refused-cast-question  @syntax.expr.cast-suffix.refused-question
```

### 7.2 Prefix operators

A prefix operator applies to the prefix expression after it, so, following
Appendix B, it binds tighter than `as` and every binary operator: `-x as Int8`
negates `x` and then casts, and `&x as UnsafePointer<Int>` casts the reference
(syntax.rule.prefix-or-cast).

```ebnf
# syntax.expr.prefix  status=current  spec="Appendix B: Operators"  node=-
prefix-expr ::= postfix-expr  @syntax.expr.prefix.postfix
    | unary-expr  @syntax.expr.prefix.unary
    | deref-expr  @syntax.expr.prefix.deref
    | ref-expr  @syntax.expr.prefix.ref
    | move-expr  @syntax.expr.prefix.move
    | try-expr  @syntax.expr.prefix.try
    | lends-expr  @syntax.expr.prefix.lends
    | borrow-place  @syntax.expr.prefix.borrow
    | refused-unsafe-expr  @syntax.expr.prefix.refused-unsafe

# syntax.expr.unary  status=current  spec="Appendix B: Operators"  node=Unary
unary-expr ::= "-" prefix-expr  @syntax.expr.unary.negate
    | "not" prefix-expr  @syntax.expr.unary.not
    | "~" prefix-expr  @syntax.expr.unary.complement

# syntax.expr.deref  status=current  spec="Prefix `*` — the pointer place, spelled"  node=Deref
deref-expr ::= "*" prefix-expr

# syntax.expr.ref  status=current  spec="Reference passing"  node=Ref
ref-expr ::= "&" prefix-expr  @syntax.expr.ref.shared
    | "&" "var" prefix-expr  @syntax.expr.ref.exclusive

# syntax.expr.lends  status=current  spec="Borrowing structs"  node=Lends
lends-expr ::= 'lends' prefix-expr
```

`move` takes a place path: a name or `self`, optionally dereferenced, then
field, tuple-index and subscript hops, and an optional final `!`. It does not
call, so `(move b).finish()` needs its parentheses.

```ebnf
# syntax.expr.move  status=current  spec="Move-Only Types"  node=Move
move-expr ::= "move" move-base move-hop* "!"?  @syntax.expr.move.place
    | refused-move-self  @syntax.expr.move.refused-self

# syntax.expr.move-base  status=current  spec="Pointer-place reads (`move ptr[i]`)"  node=-
move-base ::= name-ref  @syntax.expr.move-base.name
    | self-expr  @syntax.expr.move-base.self
    | move-deref  @syntax.expr.move-base.deref

# syntax.expr.move-deref  status=current  spec="Prefix `*` — the pointer place, spelled"  node=Deref
move-deref ::= "*" name-ref  @syntax.expr.move-deref.name
    | "*" self-expr  @syntax.expr.move-deref.self

# syntax.expr.move-hop  status=current  spec="Moving a field out"  node=-
move-hop ::= member-hop  @syntax.expr.move-hop.member
    | tuple-index-hop  @syntax.expr.move-hop.tuple-index
    | subscript-hop  @syntax.expr.move-hop.subscript
```

`try`, `try?` and `try!` are prefix operators. `try` alone may route its error
into an enum case, and may be followed by an inline `catch`. `try` directly
followed by `{` is a try block.

```ebnf
# syntax.expr.try  status=current  spec="Try Variants"  node=Try
try-expr ::= "try" NEWLINE* prefix-expr  @syntax.expr.try.propagate
    | "try" NEWLINE* prefix-expr catch-clause  @syntax.expr.try.catch
    | "try" try-route NEWLINE* prefix-expr  @syntax.expr.try.route
    | "try" "?" NEWLINE* prefix-expr  @syntax.expr.try.optional
    | "try" "!" NEWLINE* prefix-expr  @syntax.expr.try.force
    | refused-try-route  @syntax.expr.try.refused-route

# syntax.expr.try-route  status=current  spec="Error routing at `try`"  node=-
try-route ::= "(" "as" path ")"

# syntax.expr.catch  status=current  spec="Inline Catch"  node=Catch
catch-clause ::= NEWLINE* "catch" NEWLINE* block

# syntax.expr.try-block  status=current  spec="Block Try-Catch"  node=TryBlock
try-block ::= "try" NEWLINE* block NEWLINE* "catch" NEWLINE* block
```

### 7.3 Postfix hops

Hops apply left to right to the primary before them. A call's callee may be any
expression (`foo()(1)`, `v[i](x)`, `{ … }()`); a trailing closure attaches only
when the callee is a name or a member (§13, syntax.rule.trailing-closure).
Generic arguments after a name or member are kept only when a call follows
(§13, syntax.rule.generic-or-less).

```ebnf
# syntax.expr.postfix  status=current  spec="Functions"  node=-
postfix-expr ::= primary-expr postfix-hop*

# syntax.expr.hop  status=current  spec="Functions"  node=-
postfix-hop ::= member-hop  @syntax.expr.hop.member
    | tuple-index-hop  @syntax.expr.hop.tuple-index
    | optional-hop  @syntax.expr.hop.optional
    | call-hop  @syntax.expr.hop.call
    | trailing-hop  @syntax.expr.hop.trailing
    | subscript-hop  @syntax.expr.hop.subscript
    | force-hop  @syntax.expr.hop.force

# syntax.expr.member  status=current  spec="Composite Types"  node=Member
member-hop ::= "." IDENT generic-args?

# syntax.expr.tuple-index  status=current  spec="Composite Types"  node=TupleIndex
tuple-index-hop ::= "." INT

# syntax.expr.optional-member  status=current  spec="Optionals"  node=OptionalMember
optional-hop ::= "?." IDENT generic-args?

# syntax.expr.call  status=current  spec="Functions"  node=Call  ref="SL-73"
call-hop ::= "(" arg-list? ")"  @syntax.expr.call.paren
    | "(" arg-list? ")" closure-literal  @syntax.expr.call.paren-trailing

# syntax.expr.trailing-call  status=current  spec="Functions"  node=Call  ref="SL-310"
trailing-hop ::= closure-literal

# syntax.expr.args  status=current  spec="Functions"  node=-
arg-list ::= argument ( "," argument )* ","?

# syntax.expr.argument  status=current  spec="Functions"  node=Arg
argument ::= expr  @syntax.expr.argument.positional
    | IDENT ":" expr  @syntax.expr.argument.labelled

# syntax.expr.subscript  status=current  spec="Composite Types"  node=Subscript
subscript-hop ::= "[" expr "]"  @syntax.expr.subscript.single
    | multi-subscript  @syntax.expr.subscript.multi

# syntax.expr.multi-subscript  status=lockdown  spec="Composite Types"  node=-  ref="SL:borrowing §5.3"
multi-subscript ::= "[" expr "," arg-list? "]"  @syntax.expr.multi-subscript.positional-first
    | "[" IDENT ":" expr ( "," arg-list )? "]"  @syntax.expr.multi-subscript.labelled-first

# syntax.expr.force  status=current  spec="Payload reads: the place rule"  node=ForceUnwrap
force-hop ::= "!"
```

### 7.4 Primaries

An implicit member, `.North`, names a case of the enum its position expects. A
payload is an ordinary call hop on it, as in `.Move(x: 1, y: 2)`. It names enum
cases only, and a later stage resolves it only where the expected type is
determined (§13, syntax.rule.implicit-member). A line that starts with `.` does
not continue the line before it (§2.4), so a leading `.name` begins a new
statement as an implicit member. A pattern names a case bare, never with a `.`.

```ebnf
# syntax.expr.primary  status=current  spec="Appendix B: Operators"  node=-
primary-expr ::= literal  @syntax.expr.primary.literal
    | interp-string  @syntax.expr.primary.interpolation
    | source-location  @syntax.expr.primary.source-location
    | name-expr  @syntax.expr.primary.name
    | implicit-member  @syntax.expr.primary.implicit-member
    | self-expr  @syntax.expr.primary.self
    | shorthand-param  @syntax.expr.primary.shorthand-param
    | paren-expr  @syntax.expr.primary.paren
    | tuple-expr  @syntax.expr.primary.tuple
    | array-literal  @syntax.expr.primary.array
    | repeat-literal  @syntax.expr.primary.repeat
    | map-literal  @syntax.expr.primary.map
    | set-literal  @syntax.expr.primary.set
    | closure-literal  @syntax.expr.primary.closure
    | if-expr  @syntax.expr.primary.if
    | match-expr  @syntax.expr.primary.match
    | while-expr  @syntax.expr.primary.while
    | while-let-expr  @syntax.expr.primary.while-let
    | for-expr  @syntax.expr.primary.for
    | try-block  @syntax.expr.primary.try-block
    | borrow-block  @syntax.expr.primary.borrow-block
    | refused-lend-var  @syntax.expr.primary.refused-lend-var

# syntax.expr.literal  status=current  spec="Primitive Types"  node=-
literal ::= int-literal  @syntax.expr.literal.int
    | float-literal  @syntax.expr.literal.float
    | string-literal  @syntax.expr.literal.string
    | bool-literal  @syntax.expr.literal.bool
    | none-literal  @syntax.expr.literal.none

# syntax.expr.int  status=current  spec="Primitive Types"  node=IntLit
int-literal ::= INT

# syntax.expr.float  status=current  spec="Primitive Types"  node=FloatLit
float-literal ::= FLOAT

# syntax.expr.string  status=current  spec="String"  node=StringLit
string-literal ::= STRING

# syntax.expr.bool  status=current  spec="Primitive Types"  node=BoolLit
bool-literal ::= "true"  @syntax.expr.bool.true
    | "false"  @syntax.expr.bool.false

# syntax.expr.none  status=current  spec="Optionals"  node=NoneLit
none-literal ::= "None"

# syntax.expr.interpolation  status=current  spec="String"  node=Interp
interp-string ::= INTERP_STRING

# syntax.expr.interp-segment  status=current  spec="Format arguments and the allocation-free path"  node=-
interp-segment ::= expr EOF  @syntax.expr.interp-segment.expr
    | EOF  @syntax.expr.interp-segment.placeholder

# syntax.expr.source-location  status=current  spec="Source-location literals"  node=SourceLoc
source-location ::= "#file"  @syntax.expr.source-location.file
    | "#line"  @syntax.expr.source-location.line
    | "#function"  @syntax.expr.source-location.function

# syntax.expr.name  status=current  spec="Generics"  node=Name
name-expr ::= IDENT generic-args?

# syntax.expr.name-ref  status=current  spec="Move-Only Types"  node=Name
name-ref ::= IDENT

# syntax.expr.implicit-member  status=lockdown  spec="Enums (Algebraic Data Types)"  node=ImplicitMember  ref="SL-400 c7"
implicit-member ::= "." IDENT

# syntax.expr.self  status=current  spec="Type Extensions"  node=SelfExpr
self-expr ::= "self"

# syntax.expr.shorthand-param  status=current  spec="Functions"  node=ShorthandParam
shorthand-param ::= DOLLAR_PARAM

# syntax.expr.paren  status=current  spec="Composite Types"  node=-
paren-expr ::= "(" expr ")"

# syntax.expr.tuple  status=current  spec="Composite Types"  node=Tuple
tuple-expr ::= "(" ")"  @syntax.expr.tuple.unit
    | "(" expr "," ( expr ( "," expr )* ","? )? ")"  @syntax.expr.tuple.positional
    | "(" tuple-field ( "," tuple-field )* ","? ")"  @syntax.expr.tuple.named
    | refused-partial-named-tuple  @syntax.expr.tuple.refused-partial-named

# syntax.expr.tuple-field  status=current  spec="Composite Types"  node=TupleField
tuple-field ::= IDENT ":" expr

# syntax.expr.array  status=current  spec="Composite Types"  node=Array
array-literal ::= "[" ( expr ( "," expr )* ","? )? "]"

# syntax.expr.repeat  status=current  spec="Composite Types"  node=Repeat
repeat-literal ::= "[" expr ";" expr "]"
```

A `{` in expression position is a map literal, a set literal or a closure,
decided by a bounded look at what follows it (§13, syntax.rule.brace). Inside
map and set literals line breaks are allowed around entries.

```ebnf
# syntax.expr.map  status=current  spec="Composite Types"  node=Map
map-literal ::= "{" NEWLINE* ":" NEWLINE* "}"  @syntax.expr.map.empty
    | "{" NEWLINE* map-entry ( NEWLINE* "," NEWLINE* map-entry )* ( NEWLINE* "," )? NEWLINE* "}"  @syntax.expr.map.entries

# syntax.expr.map-entry  status=current  spec="Composite Types"  node=MapEntry
map-entry ::= expr ":" expr

# syntax.expr.set  status=current  spec="Composite Types"  node=Set
set-literal ::= "{" NEWLINE* expr NEWLINE* "," NEWLINE* ( expr ( NEWLINE* "," NEWLINE* expr )* ( NEWLINE* "," )? NEWLINE* )? "}"
```

### 7.5 Closures

A closure is a brace holding an optional capture list, optional parameters
closed by `in`, and a statement list whose last expression statement is its
value. Without named parameters, `$0`, `$1`, … name the parameters.

```ebnf
# syntax.expr.closure  status=current  spec="Capturing `self` and reference parameters"  node=Closure
closure-literal ::= "{" NEWLINE* closure-head? block-body "}"

# syntax.expr.closure-head  status=current  spec="Capturing `self` and reference parameters"  node=-
closure-head ::= capture-list NEWLINE* "in" NEWLINE*  @syntax.expr.closure-head.captures
    | capture-list NEWLINE* closure-params "in" NEWLINE*  @syntax.expr.closure-head.captures-params
    | closure-params "in" NEWLINE*  @syntax.expr.closure-head.params

# syntax.expr.capture-list  status=current  spec="The spawn brace's capture list"  node=-
capture-list ::= "[" capture ( "," capture )* ","? "]"

# syntax.expr.capture  status=current  spec="Capturing `self` and reference parameters"  node=Capture
capture ::= IDENT  @syntax.expr.capture.value
    | "move" IDENT  @syntax.expr.capture.move
    | 'copy' IDENT  @syntax.expr.capture.copy
    | "&" IDENT  @syntax.expr.capture.borrow
    | "&" "var" IDENT  @syntax.expr.capture.borrow-exclusive
    | "&" "self"  @syntax.expr.capture.self
    | "&" "var" "self"  @syntax.expr.capture.self-exclusive
    | refused-capture-self  @syntax.expr.capture.refused-self

# syntax.expr.closure-params  status=current  spec="Functions"  node=-
closure-params ::= closure-param ( "," NEWLINE* closure-param )*

# syntax.expr.closure-param  status=current  spec="Functions"  node=ClosureParam
closure-param ::= IDENT type-annotation?  @syntax.expr.closure-param.value
    | "&" IDENT type-annotation?  @syntax.expr.closure-param.ref
    | "&" "var" IDENT type-annotation?  @syntax.expr.closure-param.ref-exclusive
```

### 7.6 Conditionals and loops

An `if` is one node with an ordered list of arms, so an `else if` chain is flat
(§13, syntax.rule.flat-else-if). Each arm's head is a condition, an optional
binding, or a borrow of an optional place.

```ebnf
# syntax.expr.if  status=current  spec="Control Flow"  node=If
if-expr ::= "if" if-head NEWLINE* block else-if-arm* else-arm?

# syntax.expr.else-if  status=current  spec="Control Flow"  node=IfArm
else-if-arm ::= NEWLINE* "else" NEWLINE* "if" if-head NEWLINE* block

# syntax.expr.else  status=current  spec="Control Flow"  node=-
else-arm ::= NEWLINE* "else" NEWLINE* block

# syntax.expr.if-head  status=current  spec="Control Flow"  node=-
if-head ::= head-expr  @syntax.expr.if-head.condition
    | optional-binding  @syntax.expr.if-head.binding
    | borrow-unwrap  @syntax.expr.if-head.borrow

# syntax.expr.optional-binding  status=current  spec="Optionals"  node=LetArm
optional-binding ::= "let" binding-target "=" binding-subject  @syntax.expr.optional-binding.let
    | "var" binding-target "=" binding-subject  @syntax.expr.optional-binding.var
```

A `match` takes arms that start with `case`. Arms are separated by a comma, a
line break, or nothing. An arm's body is a block, an expression, or a single
statement (§13, syntax.rule.arm-body).

```ebnf
# syntax.expr.match  status=current  spec="Control Flow"  node=Match
match-expr ::= "match" head-expr NEWLINE* "{" NEWLINE* match-arm-list? "}"

# syntax.expr.match-arms  status=current  spec="Control Flow"  node=-
match-arm-list ::= match-arm ( arm-sep match-arm )* arm-sep?

# syntax.expr.arm-sep  status=current  spec="Statement Boundaries"  node=-
arm-sep ::= NEWLINE* "," NEWLINE*  @syntax.expr.arm-sep.comma
    | NEWLINE+  @syntax.expr.arm-sep.newline
    | ε  @syntax.expr.arm-sep.none

# syntax.expr.match-arm  status=current  spec="Control Flow"  node=MatchArm
match-arm ::= "case" pattern arm-guard? "->" arm-body

# syntax.expr.arm-guard  status=current  spec="Control Flow"  node=-
arm-guard ::= "if" head-expr

# syntax.expr.arm-body  status=current  spec="Control Flow"  node=-  ref="SL-59"
arm-body ::= block  @syntax.expr.arm-body.block
    | expr  @syntax.expr.arm-body.expr
    | non-expr-statement  @syntax.expr.arm-body.statement
```

`while` with no condition loops until a `break`; there is no `loop` keyword.
`while let` repeats while its subject is present and has no `else`. `for` binds
one name per element.

```ebnf
# syntax.expr.while  status=current  spec="Control Flow"  node=While
while-expr ::= "while" head-expr NEWLINE* block  @syntax.expr.while.conditional
    | "while" block  @syntax.expr.while.infinite

# syntax.expr.while-let  status=current  spec="Optional binding in a loop header (`while let`)"  node=WhileLet
while-let-expr ::= "while" "let" binding-target "=" head-expr NEWLINE* block  @syntax.expr.while-let.let
    | "while" "var" binding-target "=" head-expr NEWLINE* block  @syntax.expr.while-let.var
    | refused-while-let-else  @syntax.expr.while-let.refused-else

# syntax.expr.for  status=current  spec="Control Flow"  node=For
for-expr ::= "for" binding-name "in" head-expr NEWLINE* block  @syntax.expr.for.plain
    | for-borrow  @syntax.expr.for.borrow
    | refused-for-tuple  @syntax.expr.for.refused-tuple
```

## 8. Patterns

Patterns appear after `case`, and as the target of a destructuring `let`,
`if let`, `guard let`, `while let` and a `borrow` binding. A bare name is a
binding or a payload-free variant; which one is decided by name resolution, not
by the parser (§13, syntax.rule.name-pattern). `None` is the pattern for an
absent optional.

```ebnf
# syntax.pat.pattern  status=current  spec="Control Flow"  node=-
pattern ::= wildcard-pattern  @syntax.pat.pattern.wildcard
    | literal-pattern  @syntax.pat.pattern.literal
    | range-pattern  @syntax.pat.pattern.range
    | tuple-pattern  @syntax.pat.pattern.tuple
    | variant-pattern  @syntax.pat.pattern.variant
    | name-pattern  @syntax.pat.pattern.name
    | none-pattern  @syntax.pat.pattern.none
    | refused-qualified-variant-pattern  @syntax.pat.pattern.refused-qualified-variant
    | refused-dot-variant-pattern  @syntax.pat.pattern.refused-dot-variant

# syntax.pat.wildcard  status=current  spec="Control Flow"  node=WildcardPat
wildcard-pattern ::= '_'

# syntax.pat.literal  status=current  spec="Control Flow"  node=LiteralPat
literal-pattern ::= INT  @syntax.pat.literal.int
    | "-" INT  @syntax.pat.literal.negative-int
    | STRING  @syntax.pat.literal.string
    | "true"  @syntax.pat.literal.true
    | "false"  @syntax.pat.literal.false

# syntax.pat.range  status=current  spec="Control Flow"  node=RangePat
range-pattern ::= pattern-int ".." pattern-int  @syntax.pat.range.exclusive
    | pattern-int "..=" pattern-int  @syntax.pat.range.inclusive

# syntax.pat.int  status=current  spec="Control Flow"  node=-
pattern-int ::= INT  @syntax.pat.int.positive
    | "-" INT  @syntax.pat.int.negative

# syntax.pat.tuple  status=current  spec="Composite Types"  node=TuplePat
tuple-pattern ::= "(" ( pattern ( "," pattern )* )? ")"  @syntax.pat.tuple.positional
    | refused-named-tuple-pattern  @syntax.pat.tuple.refused-named

# syntax.pat.variant  status=current  spec="Enums (Algebraic Data Types)"  node=VariantPat
variant-pattern ::= IDENT "(" ( payload-pattern ( "," payload-pattern )* )? ")"

# syntax.pat.payload  status=current  spec="Enums (Algebraic Data Types)"  node=-
payload-pattern ::= pattern  @syntax.pat.payload.pattern
    | borrow-binding-pattern  @syntax.pat.payload.borrow

# syntax.pat.name  status=current  spec="Enums (Algebraic Data Types)"  node=NamePat
name-pattern ::= IDENT

# syntax.pat.none  status=lockdown  spec="Optionals"  node=NonePat  ref="SL-400 c6"
none-pattern ::= "None"
```

## 9. The borrow construct

`borrow let` and `borrow var` mark every use of storage in place. The block form
names the place and scopes it to a block; the place form borrows for one
statement, or for a call when written as an argument. The forms are told apart
by what follows `let` or `var` (§13, syntax.rule.borrow-form). The place form's
operand is a postfix expression, so it binds tighter than every binary operator,
`as` and `=` (§13, syntax.rule.borrow-extent).

A borrow binding stands in four places: a `borrow` block, an `if` or `else if`
head, a `for` head, and a variant's payload pattern. A `guard`, a `while`, the
top level of a `case` pattern and a tuple pattern take none.

```ebnf
# syntax.borrow.block  status=lockdown  spec="Places (`borrows` and `lend`)"  node=BorrowBlock  ref="SL:borrowing §2.1"
borrow-block ::= 'borrow' borrow-binding ( "," borrow-binding )* NEWLINE* block

# syntax.borrow.binding  status=lockdown  spec="Places (`borrows` and `lend`)"  node=BorrowBinding  ref="SL:borrowing §2.3"
borrow-binding ::= "let" binding-target "=" head-expr  @syntax.borrow.binding.let
    | "var" binding-target "=" head-expr  @syntax.borrow.binding.var

# syntax.borrow.place  status=lockdown  spec="Places (`borrows` and `lend`)"  node=BorrowPlace  ref="SL:borrowing §2.2"
borrow-place ::= 'borrow' "let" postfix-expr  @syntax.borrow.place.let
    | 'borrow' "var" postfix-expr  @syntax.borrow.place.var

# syntax.borrow.optional-target  status=lockdown  spec="Optionals"  node=BorrowPlace  ref="SL:borrowing §9.1"
borrow-optional-target ::= 'borrow' "var" optional-chain-target

# syntax.borrow.unwrap  status=lockdown  spec="Conditional lends (`borrows -> &T?`)"  node=BorrowArm  ref="SL:borrowing §2.4"
borrow-unwrap ::= 'borrow' "let" binding-name "=" head-expr  @syntax.borrow.unwrap.let
    | 'borrow' "var" binding-name "=" head-expr  @syntax.borrow.unwrap.var

# syntax.borrow.for  status=lockdown  spec="Borrowing structs"  node=ForBorrow  ref="SL:borrowing §2.6"
for-borrow ::= "for" 'borrow' "let" binding-name "in" head-expr NEWLINE* block  @syntax.borrow.for.let
    | "for" 'borrow' "var" binding-name "in" head-expr NEWLINE* block  @syntax.borrow.for.var

# syntax.pat.borrow-binding  status=lockdown  spec="Lending an enum payload"  node=BorrowBindPat  ref="SL:borrowing §2.4"
borrow-binding-pattern ::= 'borrow' "let" IDENT  @syntax.pat.borrow-binding.let
    | 'borrow' "var" IDENT  @syntax.pat.borrow-binding.var
```

## 10. Refused forms

The parser recognizes each spelling below only to refuse it, with a diagnostic
that names the valid form. Each is `removed`.

```ebnf
# syntax.decl.refused-effect-prefix  status=removed  spec="Spelling"  node=Error
refused-effect-prefix ::= attribute-list? ( visibility | "static" )* ( "unsafe" | 'sync' | 'constexpr' | "borrows" | 'consumes' | 'const' ) ( visibility | "static" | "unsafe" | 'sync' | 'constexpr' | "borrows" | 'consumes' | 'const' )* "func" method-name generic-params? "(" param-list? ")" effect-slot return-clause? default-body?  @syntax.decl.refused-effect-prefix.func
    | attribute-list? ( visibility | "static" )* ( "unsafe" | 'sync' | 'constexpr' | "borrows" | 'consumes' | 'const' ) ( visibility | "static" | "unsafe" | 'sync' | 'constexpr' | "borrows" | 'consumes' | 'const' )* "init" "(" param-list? ")" effect-slot return-clause? default-body?  @syntax.decl.refused-effect-prefix.init

# syntax.decl.refused-unsafe-prefix  status=removed  spec="Spelling"  node=Error
refused-unsafe-prefix ::= "unsafe" enum-decl  @syntax.decl.refused-unsafe-prefix.enum
    | "unsafe" trait-decl  @syntax.decl.refused-unsafe-prefix.trait
    | "unsafe" extension-decl  @syntax.decl.refused-unsafe-prefix.extension

# syntax.decl.refused-export  status=removed  spec="Re-export"  node=Error  ref="SL-400 c6"
refused-export ::= 'export' path  @syntax.decl.refused-export.symbol
    | 'export' path "as" IDENT  @syntax.decl.refused-export.alias
    | 'export' path "." "*"  @syntax.decl.refused-export.glob

# syntax.decl.refused-const  status=removed  spec="Module-level statics"  node=Error
refused-const ::= attribute-list? visibility? 'const' IDENT ( ":" type )? ( "=" expr )?

# syntax.decl.refused-visibility-prefix  status=removed  spec="Member visibility"  node=Error
refused-visibility-prefix ::= 'private' declaration-item  @syntax.decl.refused-visibility-prefix.private
    | visibility extension-decl  @syntax.decl.refused-visibility-prefix.extension
    | attribute-list visibility extension-decl  @syntax.decl.refused-visibility-prefix.attributed-extension

# syntax.decl.refused-static  status=removed  spec="`unsafe static var` — mutable statics for compound state"  node=Error
refused-static ::= "static" "var" IDENT ":" type static-init?  @syntax.decl.refused-static.var-without-unsafe
    | "unsafe" "static" IDENT ":" type static-init?  @syntax.decl.refused-static.unsafe-without-var

# syntax.decl.refused-array-extension  status=removed  spec="Composite Types"  node=Error
refused-array-extension ::= "extension" array-type NEWLINE* "{" NEWLINE* extension-member-list? "}"

# syntax.decl.refused-scoped-import  status=removed  spec="Re-export"  node=Error
refused-scoped-import ::= "public" "(" IDENT ")" 'import' import-target

# syntax.decl.refused-member-static  status=removed  spec="Static methods"  node=Error
refused-member-static ::= "static" init-decl  @syntax.decl.refused-member-static.init
    | "static" visibility method-decl  @syntax.decl.refused-member-static.before-visibility

# syntax.decl.refused-member-private  status=removed  spec="Member visibility"  node=Error
refused-member-private ::= 'private' method-decl  @syntax.decl.refused-member-private.method
    | 'private' requirement  @syntax.decl.refused-member-private.requirement

# syntax.decl.refused-receiver  status=removed  spec="Type Extensions"  node=Error
refused-receiver ::= "var" "self"  @syntax.decl.refused-receiver.var-self
    | "self"  @syntax.decl.refused-receiver.by-value
    | "&" IDENT ":" type  @syntax.decl.refused-receiver.ref-name
    | "&" "var" IDENT ":" type  @syntax.decl.refused-receiver.ref-var-name

# syntax.decl.refused-escaping  status=removed  spec="Spelling"  node=Error
refused-escaping ::= 'escaping'

# syntax.type.refused-func-consumes  status=removed  spec="v1 boundaries"  node=Error
refused-func-consumes ::= "(" func-type-params? ")" func-type-effects 'consumes' "->" type

# syntax.type.refused-partial-named-tuple  status=removed  spec="Composite Types"  node=Error
refused-partial-named-tuple-type ::= "(" tuple-type-field "," type ( "," ( type | tuple-type-field ) )* ")"  @syntax.type.refused-partial-named-tuple.named-first
    | "(" type "," tuple-type-field ( "," ( type | tuple-type-field ) )* ")"  @syntax.type.refused-partial-named-tuple.positional-first

# syntax.type.refused-cast-question  status=removed  spec="Optionals"  node=Error  ref="SL-309"
refused-cast-question ::= type-atom "??"  @syntax.type.refused-cast-question.double
    | type-atom "?" "??"  @syntax.type.refused-cast-question.optional-then-double
    | type-atom "?" "?"  @syntax.type.refused-cast-question.second

# syntax.generic.refused-param-comma  status=removed  spec="Layout"  node=Error
refused-generic-param-comma ::= "<" generic-param ( "," generic-param )* "," ">"

# syntax.generic.refused-arg-comma  status=removed  spec="Layout"  node=Error
refused-generic-arg-comma ::= "<" generic-arg ( "," generic-arg )* "," ">"

# syntax.expr.refused-unsafe  status=removed  spec="The accessor rule"  node=Error
refused-unsafe-expr ::= "unsafe" prefix-expr

# syntax.expr.refused-lend-var  status=removed  spec="`#lend_var`: a body that knows its flavor"  node=Error  ref="SL:borrowing §4"
refused-lend-var ::= "#lend_var"

# syntax.expr.refused-try-route  status=removed  spec="Error routing at `try`"  node=Error
refused-try-route ::= "try" "!" try-route prefix-expr  @syntax.expr.refused-try-route.force
    | "try" "?" try-route prefix-expr  @syntax.expr.refused-try-route.optional
    | "try" try-route prefix-expr catch-clause  @syntax.expr.refused-try-route.with-catch

# syntax.expr.refused-compare-chain  status=removed  spec="Ordering (`Comparable`)"  node=Error  ref="SL-400 c6"
refused-compare-chain ::= range-expr compare-op NEWLINE* range-expr ( compare-op NEWLINE* range-expr )+

# syntax.expr.refused-ellipsis-range  status=removed  spec="Control Flow"  node=Error
refused-ellipsis-range ::= shift-expr "..." shift-expr

# syntax.expr.refused-move-self  status=removed  spec="Moving a field out"  node=Error
refused-move-self ::= "move" "self"

# syntax.expr.refused-capture-self  status=removed  spec="Capturing `self` and reference parameters"  node=Error
refused-capture-self ::= "self"  @syntax.expr.refused-capture-self.value
    | "move" "self"  @syntax.expr.refused-capture-self.move

# syntax.expr.refused-partial-named-tuple  status=removed  spec="Composite Types"  node=Error
refused-partial-named-tuple ::= "(" tuple-field "," expr ( "," ( expr | tuple-field ) )* ")"  @syntax.expr.refused-partial-named-tuple.named-first
    | "(" expr "," tuple-field ( "," ( expr | tuple-field ) )* ")"  @syntax.expr.refused-partial-named-tuple.positional-first

# syntax.expr.refused-while-let-else  status=removed  spec="Optional binding in a loop header (`while let`)"  node=Error
refused-while-let-else ::= "while" "let" binding-target "=" head-expr NEWLINE* block NEWLINE* "else" NEWLINE* block

# syntax.expr.refused-for-tuple  status=removed  spec="Variables and Mutability"  node=Error
refused-for-tuple ::= "for" tuple-pattern "in" head-expr NEWLINE* block

# syntax.stmt.refused-var-discard  status=removed  spec="Variables and Mutability"  node=Error
refused-var-discard ::= "var" '_' type-annotation? "=" expr

# syntax.stmt.refused-uninitialized  status=removed  spec="Variables and Mutability"  node=Error
refused-uninitialized ::= "let" binding-name type-annotation  @syntax.stmt.refused-uninitialized.let
    | "var" binding-name type-annotation  @syntax.stmt.refused-uninitialized.var

# syntax.stmt.refused-local-type-alias  status=removed  spec="Appendix A: Keywords"  node=Error
refused-local-type-alias ::= 'type' IDENT "=" type

# syntax.stmt.refused-local-const  status=removed  spec="Variables and Mutability"  node=Error
refused-local-const ::= 'const' IDENT ( ":" type )? "=" expr

# syntax.stmt.refused-compound-self  status=removed  spec="Reference passing"  node=Error
refused-compound-self ::= self-expr compound-op expr

# syntax.stmt.refused-bare-lend  status=removed  spec="`lend` suspends the accessor; it does not return"  node=Error
refused-bare-lend ::= "lend"

# syntax.pat.refused-named-tuple  status=removed  spec="Composite Types"  node=Error
refused-named-tuple-pattern ::= "(" IDENT ":" pattern ( "," IDENT ":" pattern )* ")"

# syntax.pat.refused-qualified-variant  status=removed  spec="Enums (Algebraic Data Types)"  node=Error
refused-qualified-variant-pattern ::= IDENT ( "." IDENT )+ ( "(" ( payload-pattern ( "," payload-pattern )* )? ")" )?

# syntax.pat.refused-dot-variant  status=removed  spec="Enums (Algebraic Data Types)"  node=Error  ref="SL-400 c8"
refused-dot-variant-pattern ::= "." IDENT ( "(" ( payload-pattern ( "," payload-pattern )* )? ")" )?
```

Each refused form, why it is refused, and what its diagnostic suggests:

| construct | why | write instead |
|---|---|---|
| syntax.decl.refused-effect-prefix | A function's and an initializer's effects are written in the slot after the parameters, whatever the declaration's position, and the compile-time effect is spelled `constexpr`. Only `struct` and `static var` take `unsafe` in front, and only `struct` takes `borrows`. | the word in the effect slot: `func f(…) unsafe -> T`, `init(…) unsafe`, `func f(…) constexpr -> T` for `const` |
| syntax.decl.refused-unsafe-prefix | An enum, a trait or an extension is not unsafe as a whole. Only `struct` and `static var` take `unsafe` in front. | `unsafe` in the effect slot of each function that needs it |
| syntax.decl.refused-export | `public import` is the one re-export form. | `public import m.{name}`, `public import m.{name as alias}`, or `public import m.*` |
| syntax.decl.refused-const | A module constant is a `static`, whose initializer is evaluated as a constant. | `static MAX_DEPTH: Int = 256` |
| syntax.decl.refused-visibility-prefix | A declaration with no modifier is already module-private, and an extension has no name to be visible. | delete `private`; put the visibility on each member |
| syntax.decl.refused-static | A mutable static is `unsafe static var`, and `unsafe` on a static marks a mutable one. | `unsafe static var X: T = …`, or `static X: T = …` |
| syntax.decl.refused-array-extension | A fixed array has only the builtin `len()` and `swap(i, j)`, and takes no extension. | a free function |
| syntax.decl.refused-scoped-import | `public import` is the only re-export form. | `public import m` |
| syntax.decl.refused-member-static | An initializer takes no receiver by construction, and `static` follows the visibility. | `init(…)`, or `public static func` |
| syntax.decl.refused-member-private | A member with no modifier is already module-private. `private` narrows only a field. | delete `private` |
| syntax.decl.refused-receiver | A receiver is a reference, `&self` or `&var self`, and a reference parameter carries `&` on its type. | `&self`, `&var self`, or `x: &T` |
| syntax.decl.refused-escaping | `escaping` describes a closure's environment, and a named function has none. | `escaping` on the function type |
| syntax.type.refused-func-consumes | `consumes` describes a method's receiver, and a function type has none. | call the method |
| syntax.type.refused-partial-named-tuple | A named tuple labels every element or none. | label every element, or none |
| syntax.type.refused-cast-question | A `??` after a cast target reads both as an optional layer and as coalescing (SL-309). | `(n ?? 9) as Int` |
| syntax.generic.refused-param-comma | A trailing comma is allowed only in `(…)` and `[…]` lists. | drop the comma |
| syntax.generic.refused-arg-comma | A trailing comma is allowed only in `(…)` and `[…]` lists. | drop the comma |
| syntax.expr.refused-unsafe | Unsafety belongs to a declaration, not to a line. | mark the enclosing function `unsafe` |
| syntax.expr.refused-lend-var | A body never tests its lend mode. When the shared and exclusive bodies differ, both are written (SL:borrowing §4). | two accessors, or `@synthesize(shared)` |
| syntax.expr.refused-try-route | `try!` panics and `try?` discards, so neither has an error to route, and a routed `try` leaves no error for a `catch`. | `try(as E.Case) f()` alone |
| syntax.expr.refused-compare-chain | A comparison takes two operands. A chain would compare the first result, a `Bool`, with the next operand. | `a < b && b < c` |
| syntax.expr.refused-ellipsis-range | Saw's ranges are `..` and `..=`; `...` only ends a variadic extern parameter list. | `a..=b` |
| syntax.expr.refused-move-self | A receiver is borrowed. Only a consuming body moves out of it, one field at a time. | `move self.field` in a `consumes` method |
| syntax.expr.refused-capture-self | `self` may be captured only as a borrow. | `[&self]` or `[&var self]` |
| syntax.expr.refused-partial-named-tuple | A named tuple labels every element or none. | label every element, or none |
| syntax.expr.refused-while-let-else | The loop ends when the binding fails, so an `else` has nothing to mean. | `if let … else` |
| syntax.expr.refused-for-tuple | A `for` head binds one name. | `for p in v { let (a, b) = p }` |
| syntax.stmt.refused-var-discard | `_` binds nothing, so there is nothing to mutate. | `let _ = e` |
| syntax.stmt.refused-uninitialized | Every binding is initialized where it is declared. | `var x: T = …` |
| syntax.stmt.refused-local-type-alias | An alias is declared at module level, or as an associated type. | a module-level `type` |
| syntax.stmt.refused-local-const | A local that never changes is a `let`. | `let x = 5` |
| syntax.stmt.refused-compound-self | `self` is not a compound-assignment target; a receiver is replaced whole. | `self = …` |
| syntax.stmt.refused-bare-lend | `lend` hands out a place, so it needs one. | `lend place` |
| syntax.pat.refused-named-tuple | Patterns destructure tuples by position only. | `(a, b)` |
| syntax.pat.refused-qualified-variant | A variant pattern names the case alone, and the scrutinee's type supplies the enum. | `case Red` |
| syntax.pat.refused-dot-variant | A variant pattern names the case bare; the `.` of an implicit member belongs to expressions. | `case North` |

### 10.1 Retired shapes

These spellings still parse, as the production shown. A later stage refuses
each with a hint naming the replacement, because SL:borrowing requires every use
of storage through a `borrows` accessor to say `borrow`. The parser cannot tell
them apart from valid code, since whether a subscript or call is an accessor is
a type fact.

| shape | parses as | replacement |
|---|---|---|
| `g[4].weight += 1`, a write through a `borrows` subscript or accessor | syntax.stmt.compound-assign | `borrow var g[4].weight += 1` |
| `c.slot(i) = v`, an assignment to an accessor call | syntax.stmt.call-target | `borrow var c.slot(i) = v` |
| `bump(&var g[4])`, a reference argument through an accessor | syntax.expr.ref | `bump(borrow var g[4])` |
| `&buf[4..]`, a reference to a slice | syntax.expr.ref | `borrow let buf[4..]` |
| `m[k]?.field = v`, a chain write through a conditional accessor | syntax.stmt.optional-assign | `borrow var m.find(&k)?.field = v` |
| `m[k]! = v`, a forced write through a map subscript | syntax.stmt.assign | `m[k] = v` to insert, or `borrow var e = m[k] { e = v }` to require the key |
| `if var x = e` over an optional place | syntax.expr.optional-binding | `if borrow var x = e` |

## 11. Nesting depth

A parser may hold at most 256 levels of nesting. Each construct below charges
one level at its opener and keeps it while its contents are parsed. The 257th
level is refused at the opener that would take it, with the diagnostic
`nesting exceeds the parser depth limit (256)`. The limit is one named
constant.

A charge is released when its construct ends, so siblings do not add up. A
postfix chain is the exception: each hop's charge is held until the whole chain
ends, so a chain of 300 hops is refused at its 257th hop. The braces a
construct requires (the body of an `if`, a `match` arm's block) add no charge
of their own. Flat chains charge nothing per element: a binary chain of any
length, a `??` chain, the arms of one `if` chain, a list of statements, a list
of top-level items, and the `?` suffixes of a type.

| construct | charge | held until |
|---|---|---|
| syntax.expr.paren | 1 for the `(` | its `)` |
| syntax.expr.tuple | 1 for the `(`, including `()` | its `)` |
| syntax.expr.array | 1 for the `[` | its `]` |
| syntax.expr.repeat | 1 for the `[` | its `]` |
| syntax.expr.map | 1 for the `{` | its `}` |
| syntax.expr.set | 1 for the `{` | its `}` |
| syntax.expr.closure | 1 for the `{` | its `}` |
| syntax.expr.interpolation | 1 per string literal; each segment continues from it | the literal's end |
| syntax.expr.call | 1 per call hop, covering its argument list | the end of the postfix chain |
| syntax.expr.trailing-call | 1 per hop | the end of the postfix chain |
| syntax.expr.member | 1 per hop | the end of the postfix chain |
| syntax.expr.tuple-index | 1 per hop | the end of the postfix chain |
| syntax.expr.optional-member | 1 per hop | the end of the postfix chain |
| syntax.expr.subscript | 1 per hop, covering its arguments | the end of the postfix chain |
| syntax.expr.force | 1 per hop | the end of the postfix chain |
| syntax.expr.cast | 1 per `as` | the end of the cast chain |
| syntax.expr.unary | 1 per operator | its operand's end |
| syntax.expr.deref | 1 per `*` | its operand's end |
| syntax.expr.ref | 1 per `&` or `&var` | its operand's end |
| syntax.expr.move | 1 for `move`, and 1 more for a `*` after it | the end of its place path |
| syntax.expr.try | 1 for `try`, `try?` or `try!` | its operand's end |
| syntax.expr.lends | 1 | its operand's end |
| syntax.borrow.place | 1 for `borrow let` or `borrow var` | its operand's end |
| syntax.expr.if | 1 per `if` chain, whatever its number of arms | the chain's end |
| syntax.expr.match | 1 | its `}` |
| syntax.expr.while | 1 | its body's end |
| syntax.expr.while-let | 1 | its body's end |
| syntax.expr.for | 1 | its body's end |
| syntax.borrow.for | 1 | its body's end |
| syntax.expr.try-block | 1 | its `catch` block's end |
| syntax.borrow.block | 1 | its body's end |
| syntax.stmt.guard | 1 | its `else` block's end |
| syntax.decl.module | 1 for an inline module | its `}` |
| syntax.test.group | 1 | its `}` |
| syntax.type.ref | 1 per `&` or `&var` | its inner type's end |
| syntax.type.slice | 1 | its `]` |
| syntax.type.array | 1 for the `[` | its `]` |
| syntax.type.tuple | 1 for the list, including `()` | its `)` |
| syntax.type.single-tuple | 1 | its `)` |
| syntax.type.paren | 1 | its `)` |
| syntax.type.func | 1 for the parameter list | its return type's end |
| syntax.generic.args | 1 per list | its `>` |
| syntax.generic.params | 1 per list | its `>` |
| syntax.pat.tuple | 1 for the `(` | its `)` |
| syntax.pat.variant | 1 for the payload's `(` | its `)` |
| syntax.const.unary | 1 per `-` | its operand's end |
| syntax.const.atom | 1 for a parenthesized constant | its `)` |

## 12. Contexts

A context is a position a construct can stand in. The positions below are
where parsers most often go wrong: each is its own column, and the grammar
generator covers every construct in every context the table allows.

| context | position | restriction |
|---|---|---|
| stmt | a statement in a block body, other than the last | none |
| tail | the last statement of a block or closure body, taken as its value | none |
| clos | a statement in a closure body | none |
| catch | a statement in a `catch` block | none |
| arm | an unbraced match-arm body | a leading `{` opens a block; `,` and `case` end a statement |
| opnd | the operand of a binary or prefix operator, or of `as` | precedence decides the grouping |
| rhs | the right operand of `&&`, `\|\|` or `??` | none; evaluated only when needed |
| arg | a positional call argument | none |
| larg | a labelled call argument, which includes a struct field value and an enum payload | none |
| elem | a collection-literal element: array, tuple, set, map key or value, repeat value | none |
| recv | the expression a postfix hop applies to | only primaries and postfix chains; wider ones need parentheses |
| idx | a subscript argument | none |
| interp | an interpolation segment | parsed on its own; head restrictions do not carry in |
| cond | the condition of `if`, `else if`, `while`, or a boolean `guard` | head |
| subj | the subject of `if let`, `guard let`, `while let` or `if borrow` | head |
| scrut | the scrutinee of `match` | head |
| aguard | a match-arm guard, `case p if g` | head |
| iter | the iterable of `for` | head |
| rend | an endpoint of a range written as the iterable of `for` | head |
| bhead | the head of a `borrow` binding | head |
| init | a `let` or `var` initializer | none |
| asgn | the right side of `=` | none |
| crhs | the right side of a compound assignment | none |
| atgt | an assignment target | a place shape only |
| ret | the operand of `return` | none |
| brk | the value of `break` | none |
| lend | the operand of `lend` | none |
| try | the subject of `try`, `try?` or `try!` | a prefix expression |
| dflt | a default parameter value | none |
| sinit | a `static` initializer | a constant |
| alen | an array length, `[T; N]` | a constant |
| rcnt | a repeat count, `[v; N]` | a constant |
| cgen | a value argument in a generic list | the constant grammar of §5.2 |
| raw | an enum case's raw value | a constant |
| aarg | an attribute argument, as in `@align(N)` | a constant |
| sassert | a `static_assert` condition | a constant |
| cap | an entry of a closure's capture list | a capture only |

In a **head** context, the parser does not attach a trailing closure at the
outer level of the expression, because a `{` there begins the construct's body
(§13, syntax.rule.head-restriction). Restrictions nest: a construct inside an
operand of a head expression is still in the head, until a bracket, a closure
body or an interpolation segment intervenes (syntax.rule.head-reset).

Each cell says whether the construct in the row may stand in the context of the
column:

| code | meaning |
|---|---|
| Y | allowed |
| N | not allowed: a syntax error, or the tokens parse as something else |
| P | allowed only inside parentheses |
| H | allowed; the head restriction applies |
| C | allowed only through the constant grammar of §5.2 |
| K | parses with the full grammar; the constant evaluator decides whether it is a constant |
| S | parses; a later stage refuses the construct in this position |
| T | allowed as a place: the construct is an assignment target |

| construct | stmt | tail | clos | catch | arm | opnd | rhs | arg | larg | elem | recv | idx | interp | cond | subj | scrut | aguard | iter | rend | bhead | init | asgn | crhs | atgt | ret | brk | lend | try | dflt | sinit | alen | rcnt | cgen | raw | aarg | sassert | cap |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| syntax.expr.literal | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | Y | K | K | K | C | K | K | K | N |
| syntax.expr.interpolation | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | Y | S | S | S | N | S | S | S | N |
| syntax.expr.source-location | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | Y | K | K | K | N | K | K | K | N |
| syntax.expr.name | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | H | H | H | H | H | H | H | Y | Y | Y | T | Y | Y | Y | Y | Y | K | K | K | C | K | K | K | N |
| syntax.expr.implicit-member | S | Y | S | S | Y | Y | Y | Y | Y | Y | S | Y | S | S | S | S | S | S | S | S | Y | Y | S | N | Y | S | S | S | Y | K | S | S | N | S | S | S | N |
| syntax.expr.self | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | T | Y | Y | S | Y | S | S | S | S | N | S | S | S | N |
| syntax.expr.shorthand-param | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | S | S | S | S | N | S | S | S | N |
| syntax.expr.paren | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | Y | Y | Y | K | K | K | C | K | K | K | N |
| syntax.expr.tuple | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | Y | Y | Y | K | S | S | N | S | S | S | N |
| syntax.expr.array | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | Y | K | S | S | N | S | S | S | N |
| syntax.expr.repeat | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | Y | K | S | S | N | S | S | S | N |
| syntax.expr.map | Y | Y | Y | Y | P | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | Y | S | S | S | N | S | S | S | N |
| syntax.expr.set | Y | Y | Y | Y | P | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | Y | S | S | S | N | S | S | S | N |
| syntax.expr.closure | S | Y | S | S | P | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | Y | K | S | S | N | S | S | S | N |
| syntax.expr.call | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | H | H | H | H | H | H | H | Y | Y | Y | S | Y | Y | Y | Y | Y | K | K | K | C | K | K | K | N |
| syntax.expr.trailing-call | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | N | N | N | N | N | N | Y | Y | Y | N | Y | Y | S | Y | Y | S | S | S | N | S | S | S | N |
| syntax.expr.member | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | H | H | H | H | H | H | H | Y | Y | Y | T | Y | Y | Y | Y | Y | K | K | K | C | K | K | K | N |
| syntax.expr.tuple-index | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | T | Y | Y | Y | Y | Y | S | S | S | N | S | S | S | N |
| syntax.expr.optional-member | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | H | H | H | H | H | H | H | Y | Y | Y | T | Y | Y | S | Y | Y | S | S | S | N | S | S | S | N |
| syntax.expr.subscript | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | T | Y | Y | Y | Y | Y | S | S | S | N | S | S | S | N |
| syntax.expr.force | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | T | Y | Y | Y | Y | Y | S | S | S | N | S | S | S | N |
| syntax.expr.unary | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | H | H | Y | Y | Y | N | Y | Y | S | Y | Y | K | K | K | C | K | K | K | N |
| syntax.expr.deref | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | H | H | Y | Y | Y | T | Y | Y | Y | Y | Y | S | S | S | N | S | S | S | N |
| syntax.expr.ref | S | S | S | S | S | Y | S | Y | Y | S | P | S | S | S | S | S | S | S | S | S | S | S | S | N | S | S | S | S | S | S | S | S | N | S | S | S | N |
| syntax.expr.move | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | S | S | S | S | N | S | S | S | N |
| syntax.expr.try | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | H | H | Y | Y | Y | N | Y | Y | S | Y | Y | S | S | S | N | S | S | S | N |
| syntax.expr.lends | S | S | S | S | S | S | S | S | Y | S | P | S | S | S | S | S | S | S | S | S | S | S | S | N | S | S | S | S | S | S | S | S | N | S | S | S | N |
| syntax.expr.cast | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | H | H | Y | Y | Y | N | Y | Y | S | P | Y | K | K | K | N | K | K | K | N |
| syntax.expr.multiplicative | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | H | H | Y | Y | Y | N | Y | Y | S | P | Y | K | K | K | C | K | K | K | N |
| syntax.expr.additive | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | H | H | Y | Y | Y | N | Y | Y | S | P | Y | K | K | K | C | K | K | K | N |
| syntax.expr.shift | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | H | H | Y | Y | Y | N | Y | Y | S | P | Y | K | K | K | N | K | K | K | N |
| syntax.expr.range | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | N | H | Y | Y | Y | N | Y | Y | S | P | Y | S | S | S | N | S | S | S | N |
| syntax.expr.range-from | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | N | N | N | N | N | N | N | Y | Y | Y | N | Y | Y | S | P | Y | S | S | S | N | S | S | S | N |
| syntax.expr.range-upto | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | N | H | Y | Y | Y | N | Y | Y | S | P | Y | S | S | S | N | S | S | S | N |
| syntax.expr.compare | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | P | H | Y | Y | Y | N | Y | Y | S | P | Y | K | K | K | N | K | K | K | N |
| syntax.expr.bitand | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | P | H | Y | Y | Y | N | Y | Y | S | P | Y | K | K | K | N | K | K | K | N |
| syntax.expr.bitxor | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | P | H | Y | Y | Y | N | Y | Y | S | P | Y | K | K | K | N | K | K | K | N |
| syntax.expr.bitor | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | P | H | Y | Y | Y | N | Y | Y | S | P | Y | K | K | K | N | K | K | K | N |
| syntax.expr.and | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | P | H | Y | Y | Y | N | Y | Y | S | P | Y | K | K | K | N | K | K | K | N |
| syntax.expr.or | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | P | H | Y | Y | Y | N | Y | Y | S | P | Y | K | K | K | N | K | K | K | N |
| syntax.expr.coalesce | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | H | P | H | Y | Y | Y | N | Y | Y | S | P | Y | S | S | S | N | S | S | S | N |
| syntax.expr.if | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | Y | S | S | S | N | S | S | S | N |
| syntax.expr.match | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | Y | S | S | S | N | S | S | S | N |
| syntax.expr.while | Y | N | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | Y | S | S | S | N | S | S | S | N |
| syntax.expr.while-let | Y | N | Y | Y | Y | S | S | S | S | S | S | S | S | S | S | S | S | S | S | S | S | S | S | N | S | S | S | S | S | S | S | S | N | S | S | S | N |
| syntax.expr.for | Y | N | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | Y | S | S | S | N | S | S | S | N |
| syntax.borrow.for | Y | N | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | Y | S | S | S | N | S | S | S | N |
| syntax.expr.try-block | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | N | Y | Y | S | Y | Y | S | S | S | N | S | S | S | N |
| syntax.borrow.place | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | H | H | H | H | S | H | S | Y | Y | Y | T | Y | Y | S | Y | S | S | S | S | N | S | S | S | N |
| syntax.borrow.block | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | P | Y | Y | Y | Y | Y | P | Y | Y | Y | N | Y | Y | S | Y | S | S | S | S | N | S | S | S | N |
| syntax.expr.optional-binding | N | N | N | N | N | N | N | N | N | N | N | N | N | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.borrow.unwrap | N | N | N | N | N | N | N | N | N | N | N | N | N | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.stmt.let | Y | N | Y | Y | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.stmt.destructure | Y | N | Y | Y | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.stmt.assign | Y | N | Y | Y | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.stmt.compound-assign | Y | N | Y | Y | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.stmt.return | Y | N | Y | Y | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.stmt.break | Y | N | Y | Y | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.stmt.continue | Y | N | Y | Y | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.stmt.lend | Y | N | Y | Y | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.stmt.guard | Y | N | Y | Y | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.stmt.guard-condition | Y | N | Y | Y | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.decl.static-assert | Y | N | Y | Y | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.stmt.attributed-local | Y | N | Y | Y | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.stmt.optional-assign | Y | N | Y | Y | Y | N | N | N | N | N | N | N | N | N | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| syntax.expr.capture | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | Y |

## 13. Disambiguation

Where the productions allow more than one reading of the same tokens, or where
a spelling is refused although the productions would allow it, the rule below
decides. The constructs column names the productions a rule governs.

| rule | constructs | resolution | source | status |
|---|---|---|---|---|
| syntax.rule.generic-or-less | syntax.expr.name, syntax.expr.member, syntax.expr.optional-member, syntax.generic.args, syntax.expr.compare | After a name or a member in an expression, `<` starts a speculative generic list. It is kept only if it parses and its `>` is followed by `(`, `.`, or, where a trailing closure may attach, `{`. Otherwise the tokens are re-read as comparisons. Once kept, the list ignores line breaks, and an error inside it, such as a trailing comma, is reported rather than re-read. So `f < g > (x)` is the generic call `f<g>(x)`, `show(a < b, c > (d))` calls `a<b, c>(d)`, and `FixedBuf<1 << 4>()` compares, because a shift is not in the constant grammar. Parenthesize a comparison to force it. In a type, `<` always opens a generic list. | Layout; SL:architecture §3.2 | current |
| syntax.rule.generic-close-split | syntax.generic.args, syntax.generic.params, syntax.type.named | The lexer keeps longest match (syntax.lex.longest-match). Where the first `>` of a `>=` or `>>=` token closes a generic list the parser has committed to, the parser splits the token after that `>`, and splits what remains the same way when it closes an enclosing list: `let v: Vector<Int>= w` closes the list and assigns, and `let m: Map<K, Vector<V>>= w` closes both lists and assigns. `>>` needs no split, because the lexer has no `>>` token. Elsewhere longest match stands, and a warning, never an error, flags the two spellings whose longest-match reading may not be the one meant: `o!= 5`, a comparison written directly after what reads as a postfix `!`, compares where `o! = 5` writes the payload; and `a&-b`, a wrapping operator written where a unary minus could follow `&`, subtracts where `a & -b` is a bitwise and of a negation. The warnings' category name is not part of the grammar. | Appendix B: Operators; SL-400 c6 | lockdown |
| syntax.rule.trailing-closure | syntax.expr.call, syntax.expr.trailing-call, syntax.expr.closure, syntax.expr.implicit-member | A closure literal right after a call's `)`, or right after a name, a member or an implicit member, is a trailing-closure argument when its `{` is on the same line and the position allows one (syntax.rule.head-restriction). A name takes one bare (`run { 10 }`), with or without generic arguments. Only a name, member or implicit-member callee takes a trailing closure, and `.Case` takes one exactly as `Enum.Case` does; `foo() { }` attaches to `foo`, and a general callee such as `foo()(1)` takes none. There is at most one trailing closure. A line break before the `{` ends the call. | Functions; SL-310; SL-73 | current |
| syntax.rule.head-restriction | syntax.expr.head, syntax.expr.if-head, syntax.expr.while, syntax.expr.while-let, syntax.expr.for, syntax.expr.match, syntax.expr.arm-guard, syntax.stmt.guard, syntax.stmt.binding-subject, syntax.borrow.binding, syntax.borrow.unwrap, syntax.borrow.for | In a head context (an `if`, `else if` or `while` condition, a binding subject, a `match` scrutinee, a match-arm guard, a `for` iterable, a `borrow` head) no trailing closure attaches at the outer level, because a `{` there begins the construct's body. `if v.any { $0 } { }` is refused; write `if v.any({ $0 }) { }`. | Control Flow; SL-2 c24 | current |
| syntax.rule.head-reset | syntax.expr.head, syntax.expr.paren, syntax.expr.tuple, syntax.expr.array, syntax.expr.closure, syntax.expr.args, syntax.expr.subscript, syntax.expr.interpolation | Inside a head, any bracket, a closure body and an interpolation segment start a fresh level where trailing closures attach again, so `if f(v.map { $0 }) { }` and `if (v.any { $0 > 1 }) { }` parse. | Control Flow; SL-400 c6 | lockdown |
| syntax.rule.interpolation-segment | syntax.expr.interpolation, syntax.expr.interp-segment | Each expression segment of an interpolated string is parsed on its own as `interp-segment`. A blank segment is a format placeholder. Positions are source positions, and the nesting depth continues from the string's. | String; SL:architecture §3.1 | current |
| syntax.rule.static-head | syntax.decl.static, syntax.decl.method, syntax.decl.requirement, syntax.decl.refused-effect-prefix | At a top-level item, `static` followed by a name declares a static, so `static sync: Int = 0` names a static `sync`. In an extension or trait body, `static` must be followed by `func`, and marks a static method. In either place, an effect word after `static` that is followed by `func`, `init`, a visibility, `static` or another effect word begins a refused head (syntax.rule.contextual-words). | Static methods | current |
| syntax.rule.brace | syntax.expr.map, syntax.expr.set, syntax.expr.closure, syntax.stmt.block, syntax.expr.arm-body | Where a block is required, `{` opens a block: every construct body, and an arm body that starts with `{`. Elsewhere a `{` in expression position is decided by what follows it: `{:}` is an empty map; a capture list followed by `in`, or names followed by `in`, is a closure; otherwise the first `:` or `,` at the brace's own level makes a map or a set; `{}`, `{expr}` and a statement body are closures. There is no bare block statement, and an interpolation's braces belong to its string. | Composite Types | current |
| syntax.rule.statement-separator | syntax.stmt.body, syntax.stmt.sep | A statement ends at a line break, a `;`, the enclosing `}` or the end of input. `;` separates two statements on one line and never ends one, so a `;` before a line break, before `}`, at the end of input, doubled, or at the start of a line is refused. | Statement Boundaries; SL-347 | current |
| syntax.rule.juxtaposition | syntax.stmt.body, syntax.expr.closure, syntax.file.list | Two statements on one line with nothing between them are refused at the second statement's first token, so `x = 1 y` and `let a = b (c)` are errors. | Statement Boundaries; SL-347 | current |
| syntax.rule.declaration-separator | syntax.file.list, syntax.decl.trait-members, syntax.decl.extension-members, syntax.decl.extern-funcs | Declarations take a line each. A `;` between two declarations, or two on one line, is refused. | Statement Boundaries; SL-347 | current |
| syntax.rule.operator-continuation | syntax.expr.coalesce, syntax.expr.or, syntax.expr.and, syntax.expr.bitor, syntax.expr.bitxor, syntax.expr.bitand, syntax.expr.compare, syntax.expr.range, syntax.expr.shift, syntax.expr.additive, syntax.expr.multiplicative | A line ending in a binary operator continues onto the next. A line starting with an operator or a `.` begins a new statement, so a leading `-` is a unary minus and a leading `.name` is an implicit member (syntax.rule.implicit-member). | Layout; design 259 R3 | current |
| syntax.rule.implicit-member | syntax.expr.implicit-member, syntax.expr.member, syntax.pat.refused-dot-variant | `.` followed by a name at the start of an operand is an implicit member, and after an operand it is a member hop. A line that starts with `.` does not continue the line before it (syntax.rule.operator-continuation), so `let n = s` followed by `.len()` on the next line is two statements, and the second is an implicit member. A later stage resolves an implicit member only where its position's expected type is determined. One call hop may follow it, its payload (`.Move(x: 1, y: 2)`), and the expected type reaches the implicit member through that call. Any other hop after an implicit member is refused by a later stage, since the member's own position then expects nothing (§12's `recv` cell is S). Its diagnostic spells the qualified form, as in `Direction.North.opposite()`. When one that starts a line fails to resolve, the diagnostic names the chain reading, that a method chain continues onto another line only inside parentheses, beside the `Enum.Case` fixit. In a pattern, `case .North` is refused; a pattern names the case bare, `case North`. | Enums (Algebraic Data Types); SL-400 c7; SL-400 c8 | lockdown |
| syntax.rule.leading-minus | syntax.stmt.body, syntax.expr.unary, syntax.expr.if | A line break after a construct that ends in `}` ends the statement, so `if c { return 1 }` followed by `-1` on the next line is two statements. On one line, `if c { 1 } else { 2 } - 1` is a subtraction whose left operand is the `if`. | Statement Boundaries; design 259 R2 | current |
| syntax.rule.continuation-keywords | syntax.expr.else-if, syntax.expr.else, syntax.expr.catch, syntax.expr.try-block, syntax.stmt.guard | `else` and `catch` may start the line after the `}` they follow, and the construct continues. A body's `{` may start the line after its head. | Control Flow | current |
| syntax.rule.cast-target-question | syntax.type.cast-target, syntax.type.refused-cast-question | A cast target takes at most one `?`. A `??` token or a second `?` directly after it is refused at that token, whatever the spacing: `n as Int? ?? 9`, `n as Int?? 9`, `n as Int ?? 9` and `n as Int? ?` are all errors. Write `(n ?? 9) as Int`. Types nested inside the target, `x as Vector<Int??>`, are unaffected. | Optionals; SL-309 | current |
| syntax.rule.block-tail | syntax.stmt.body, syntax.stmt.expr, syntax.expr.while, syntax.expr.while-let, syntax.expr.for, syntax.borrow.block | A block's last statement is its tail when it is an expression statement. A loop that starts a statement is a statement, never the tail. `if`, `match`, a `try` block and a `borrow` block at the start of a statement are expression statements, so they can be the tail and can continue on their line as an operand: `borrow var it = v[i] { it.hits }` at the end of a body is the body's value, and `borrow let e = m[k] { e.n } + 1` continues on its line. | Statement Boundaries | current |
| syntax.rule.arm-body | syntax.expr.arm-body, syntax.expr.match-arm | An arm body is a block, an expression, or one statement; the statement parser decides, with no keyword list. A body that starts with `{` is a block, so a closure, map or set literal there needs parentheses. A statement arm means what the same statement in braces means. The body starts on the line of its `->`. | Control Flow; SL-59 | current |
| syntax.rule.arm-statement-end | syntax.expr.arm-body, syntax.stmt.return, syntax.stmt.break | In an unbraced arm body, `,` and `case` also end a statement, so `case 0 -> return case _ -> 1` is two arms and `return` has no operand. | Control Flow; SL-59 | current |
| syntax.rule.one-call-node | syntax.expr.call, syntax.expr.argument | `Name(…)` is one call node whether `Name` is a function, a type, an enum case or a value; the tree records the arguments with their labels, and resolution decides. Labelled and positional arguments mix freely, so `f(a: 1, 2)` parses. | Functions; SL:architecture §3.2 | current |
| syntax.rule.flat-else-if | syntax.expr.if, syntax.expr.else-if, syntax.expr.else | An `if` with its `else if` arms and final `else` is one node with an ordered arm list. `else if let` and `else if borrow` arms join the same list. | Control Flow; SL:architecture §3.2; SL-380 | current |
| syntax.rule.flat-chains | syntax.expr.coalesce, syntax.expr.or, syntax.expr.and, syntax.expr.bitor, syntax.expr.bitxor, syntax.expr.bitand, syntax.expr.shift, syntax.expr.additive, syntax.expr.multiplicative, syntax.const.expr, syntax.const.term | A chain of one precedence tier is one node holding its operands and the operator between each pair. The tree's depth follows source nesting, not chain length. | SL:architecture §3.2; SL-380 | current |
| syntax.rule.coalesce-grouping | syntax.expr.coalesce | A `??` chain is one flat node, and its operands group right to left: `a ?? b ?? 0` means `a ?? (b ?? 0)`, so it works over two optionals. | Optionals; SL-400 c6 | lockdown |
| syntax.rule.compare-chain | syntax.expr.compare, syntax.expr.refused-compare-chain | A comparison takes exactly two operands. A chain such as `a < b < c` or `a == b == c` is refused, with the fixit `a < b && b < c`, so no comparison silently compares a `Bool`. | Ordering (`Comparable`); SL-400 c6 | lockdown |
| syntax.rule.prefix-or-cast | syntax.expr.cast, syntax.expr.unary, syntax.expr.ref, syntax.expr.deref | A prefix operator binds tighter than `as`, following Appendix B: `-x as Int8` is `(-x) as Int8`, and `~b as UInt64` is `(~b) as UInt64`, which complements `b` before widening it. | Appendix B: Operators; SL-400 c6 | lockdown |
| syntax.rule.try-extent | syntax.expr.try, syntax.expr.cast | `try`, `try?` and `try!` sit at the prefix tier and apply to the prefix expression after them, so `try parse_id() as UserId` casts the unwrapped value and `try f() + 1` adds to it. | Error routing at `try`; SL-400 c6 | lockdown |
| syntax.rule.postfix-per-hop | syntax.expr.postfix, syntax.expr.cast | A postfix chain stays nested, one node per hop, and every hop charges one nesting level until the chain ends (§11). | SL:architecture §3.2; SL-380 | current |
| syntax.rule.depth-limit | syntax.expr.postfix, syntax.expr.prefix, syntax.expr.primary, syntax.type.type, syntax.pat.pattern | Nesting deeper than 256 levels is refused at the opener of the 257th, as §11 counts. | Layout; design 259 R4 | current |
| syntax.rule.borrow-form | syntax.borrow.block, syntax.borrow.place, syntax.borrow.unwrap, syntax.borrow.for | `borrow` followed by `let` or `var` is the borrow construct; otherwise `borrow` is an identifier. After `let` or `var`, a name followed by `=`, or a parenthesized pattern followed by `=`, is a binding: a `borrow` block, or at an `if` head an optional-place unwrap. Anything else is the place form. After `for`, `borrow let` and `borrow var` bind the loop name. | Places (`borrows` and `lend`); SL:borrowing §2 | lockdown |
| syntax.rule.borrow-extent | syntax.borrow.place, syntax.borrow.optional-target | The place form's operand is a postfix expression, whatever its hops, so it binds tighter than `as`, every binary operator and `=`. Where the `borrows` call falls inside the operand is decided by typing, not by the parser. `borrow let doc.section_at(x).get("k") ?? ""` coalesces the borrowed read, and `borrow var v[i].x = borrow let v[j].x` assigns between two place forms. | Places (`borrows` and `lend`); SL:borrowing §2.2 | lockdown |
| syntax.rule.optional-chain-run | syntax.expr.optional-member, syntax.stmt.optional-assign, syntax.stmt.optional-chain-target | A `?.` hop opens a run that continues over member, optional, call and trailing-closure hops. A `!`, a subscript, a tuple index, or the end of the postfix expression closes it; one short-circuit skips the whole run. An assignment whose target ends in an open run is an optional assignment of type `Void?`; `a?.b[0] = 1` closes the run first and is a plain assignment. | Optionals | current |
| syntax.rule.label-or-tuple | syntax.expr.argument, syntax.expr.tuple, syntax.expr.tuple-field, syntax.type.tuple | At the start of a call argument, a name followed by `:` is a label. Inside grouping parentheses, a name followed by `:` begins a named tuple, which labels every element or none. | Composite Types | current |
| syntax.rule.paren-type | syntax.type.func, syntax.type.tuple, syntax.type.single-tuple, syntax.type.paren | In a type, a parenthesized list followed by effect words and `->` is a function type. Otherwise `()` is the empty tuple, a list with a comma or labels is a tuple, `(T,)` is a one-element tuple, and `(T)` groups `T`, so `((Int) -> Int)?` is an optional function. | Composite Types; SL-400 c6 | lockdown |
| syntax.rule.prefix-type-suffix | syntax.type.type, syntax.type.ref, syntax.type.func, syntax.type.slice, syntax.type.suffix | A reference and a function type are not atoms, so a `?` or `??` after `&`, `&var` or a function type's `->` belongs to the type that follows: `&T?` is `Ref(Optional(T))`, and `(A) -> B?` is a function returning an optional. A slice is one atom, and `[T]` alone is not a type, so `&[T]?` is `Optional(Slice(T))`. Parentheses make a suffix apply to a whole function type, as in `((A) -> B)?`. A later stage, the reader of a `borrows` return type, reads `&T?` and `&[T]?` there as the conditional lend. | Optionals; Reference passing | current |
| syntax.rule.generic-arg-value | syntax.generic.arg, syntax.const.expr, syntax.const.layout-query | A generic argument that starts with an integer, `-`, `sizeof` or `alignof` is a value. One that parses as a type and is then followed by `+ - * / %` is re-read as a value, so `Ring<N + 1>` works. Otherwise it is a type, and a bare name such as `N` is decided against the parameter it fills. `sizeof` and `alignof` are written bare, `Ring<sizeof<UInt64>()>`. A shift cannot appear, because `<` and `>` delimit the list; name a `static` instead. | Generics | current |
| syntax.rule.deref-or-multiply | syntax.expr.deref, syntax.expr.multiplicative | `*` before an operand is a dereference, and `*` between operands is a multiplication, so `a * *p` multiplies by the pointee. | Prefix `*` — the pointer place, spelled | current |
| syntax.rule.tuple-index-dot | syntax.expr.tuple-index, syntax.expr.member | A tuple index never takes a following `.` as a decimal point, so `t.0.1` is two hops and `t.0.name` a member of element 0. | Composite Types | current |
| syntax.rule.name-pattern | syntax.pat.name, syntax.pat.wildcard, syntax.pat.variant | `_` is the wildcard. Any other lone name is a name pattern, and resolution decides whether it names a payload-free variant or binds. A name followed by `(` is a variant pattern. | Enums (Algebraic Data Types) | current |
| syntax.rule.contextual-words | syntax.decl.field-visibility, syntax.decl.type-alias, syntax.decl.assoc-type, syntax.generic.param, syntax.type.any, syntax.expr.lends, syntax.decl.static-assert, syntax.decl.effects, syntax.decl.constexpr, syntax.decl.refused-effect-prefix, syntax.decl.refused-const, syntax.stmt.refused-local-const | A contextual word is recognized only in its position and by one token of lookahead: `private` before a field name, `type` followed by a name at a declaration head, `const` followed by a name in a generic list, `any` followed by a name in a type, `lends` followed by `self` or a name, `static_assert` followed by `(`, and the effect words (`consumes`, `constexpr`, `sync`, `escaping`) after a parameter list. In a declaration head, `const`, `consumes`, `constexpr` and `sync` are recognized when the token after the word is `func`, `init`, a visibility, `static` or another effect word, and only to be refused (syntax.decl.refused-effect-prefix). At a top-level item's head or a statement's, `const` followed by a name is recognized only to be refused (syntax.decl.refused-const, syntax.stmt.refused-local-const). Elsewhere each is an identifier. | Appendix A: Keywords | current |
| syntax.rule.effect-slot | syntax.decl.effects, syntax.decl.constexpr, syntax.decl.borrows-effect, syntax.type.func-effects, syntax.decl.refused-effect-prefix | Effect words appear in one order, each at most once: `consumes unsafe sync borrows` after a declaration's parameters, with `constexpr` in `sync`'s place, and `unsafe sync escaping borrows` in a function type. Another order is refused naming the canonical one. `consumes` is legal only on a method with a `&var self` receiver, and `borrows` is not legal on `init`. The pairs `consumes borrows`, `constexpr sync`, `unsafe constexpr` and `constexpr borrows` parse, with `constexpr` written before `sync`; a later stage refuses each. An effect word in a declaration head, before `func` or `init`, is refused with a fixit that moves it into the slot (syntax.decl.refused-effect-prefix). | Spelling; Consuming method receivers (`consumes`); SL:architecture §3.10 | lockdown |
| syntax.rule.subscript-declaration | syntax.decl.method-name, syntax.decl.setitem-name | A method named `[]` with a `borrows` effect is a place accessor; without one it is a getitem. A method named `[]=` is a setitem, and its last parameter is the value. | Places (`borrows` and `lend`); SL:borrowing §5 | lockdown |
| syntax.rule.subscript-arguments | syntax.expr.subscript, syntax.expr.multi-subscript | A subscript with one unlabelled argument is a single subscript; one with a label or a second argument follows the call-argument rules, so `m[r, c]`, `m[(r, c)]` and `m[k, default: 0]` are three different forms. `default:` is an ordinary label here. | Composite Types; SL:borrowing §5.3 | lockdown |
| syntax.rule.range-open-end | syntax.expr.range-from, syntax.expr.range-upto, syntax.expr.range | A range's upper bound is omitted, as in `buf[4..]` and `buf[..]`, only when the token after `..` is `]`, `)`, `,`, `;`, a line break, `}` or the end of input. | Composite Types; SL:borrowing §6 | lockdown |
| syntax.rule.move-place | syntax.expr.move, syntax.expr.move-hop | `move` takes a place path and stops at the first token that is not a field, tuple-index or subscript hop, so `move x.f()` does not call `f`. | Move-Only Types | current |
| syntax.rule.assignment-target | syntax.stmt.assign, syntax.stmt.compound-assign, syntax.stmt.assign-target, syntax.stmt.compound-target | The target is parsed as an expression, then checked against the place shapes. `a = b = c` and `(a, b) = t` are refused, and `self` is not a compound-assignment target. | Reference passing | current |
| syntax.rule.attribute-position | syntax.attr.attribute, syntax.attr.synthesize-shared, syntax.decl.item, syntax.stmt.attributed-local, syntax.decl.extension-member | `@export` and `@section` go on a top-level `func` or `static`, `@align` on a `static` or a local `let` or `var` that binds one name, `@synthesize` on an extension, and `@synthesize(shared)` on a method. An attribute elsewhere, an unknown name, a repeat, or the wrong argument shape is refused. | Attributes (design 58) | current |
| syntax.rule.receiver-and-static | syntax.decl.param, syntax.decl.method, syntax.decl.requirement | A receiver may only be a method's first parameter. A method or requirement without a receiver is declared `static`, and one declared `static` has no receiver. | Static methods | current |
| syntax.rule.extern-abi | syntax.decl.extern-block | The ABI string is `"C"`. | C FFI | current |
| syntax.rule.module-inline | syntax.decl.module | `module name` followed by `{`, on its line or the next, is an inline module. | Module Declaration | current |
| syntax.rule.try-block | syntax.expr.try-block, syntax.expr.try | `try` directly followed by `{` is a try block, never a `try` applied to a closure. | Block Try-Catch | current |
| syntax.rule.test-form | syntax.test.item, syntax.test.case, syntax.test.group, syntax.test.declaration | After `@test`, a string makes a case, `{` makes a group, and anything else makes the declaration that follows test-only. `refuses:`, `panics:` and `warns:` go only on a case. A group holds declarations and cases, never statements. `@test` items stand at top level or in a group, never in an ordinary extension. On a declaration, `@test` comes before its other attributes, and a later stage refuses a combination that means nothing. | Attributes (design 58); SL:testing §2 | lockdown |
| syntax.rule.refusal-body | syntax.test.refusal-body, syntax.test.refusal-unit | In a normal build a refusal case's body is matched by braces only. In a test build its tokens are parsed as a unit of their own, and its errors belong to the case. | Attributes (design 58); SL:testing §5 | lockdown |
| syntax.rule.requirement-borrows | syntax.decl.requirement, syntax.decl.borrows-effect | A trait requirement may be `borrows` or `borrows(sync)`. It may not be `consumes`. | Traits; SL:borrowing §5.4 | lockdown |
| syntax.rule.reference-position | syntax.expr.ref | `&x` and `&var x` stand only as a call argument, or as the operand of a cast to a pointer type. | Reference passing | current |
| syntax.rule.discard-binding | syntax.stmt.let, syntax.stmt.refused-var-discard | `let _ = e` discards the value. `var _ = e` matches the refused form, never a binding. | Variables and Mutability | current |
| syntax.rule.try-route-case | syntax.expr.try-route | The routing clause names an enum and a case, so its path has at least two segments: `try(as ConfigError.Alloc)`. | Error routing at `try` | current |
| syntax.rule.import-names | syntax.decl.import-symbols, syntax.decl.import-symbol | One selective import binds each local name once, so `import m.{a, b as a}` is refused. | Imports | current |
| syntax.rule.interpolation-whole | syntax.expr.interp-segment | An interpolation segment must be exactly one expression: `"{a b}"` and `"{1F600}"` are refused, not read as their first token. | String | current |

## 14. Not in the grammar

These forms appear in the spec as planned or illustrative, were removed
earlier, or are refused by construction, and no production accepts them:

- `loop`: the infinite loop is `while { }` (design 55).
- `const` declarations (`const NAME: T = …`), macros, `@derive`, `@inline` and
  compile-time reflection: planned. Compile-time evaluation is the effect word
  `constexpr` (syntax.decl.constexpr), and the spec's planned `const func` is
  refused (syntax.decl.refused-effect-prefix).
- `where` clauses, generic type aliases (`type H<T> = …`) and computed
  properties: planned.
- A `subscript { get set borrow }` block: deferred; the three subscript roles
  are separate methods.
- The operators `**`, `=>` and `::`: planned or superseded.
- `async` and `await`: never.
- `unsafe { }` blocks and a line-level `unsafe` marker: removed (§10).
- A conformance in a struct header, `struct X: Trait`: conformance is written as
  an extension.
- Two struct fields or enum cases on one line with nothing between them, as in
  `struct P { x: Int y: Int }`. A field or case list is separated by a comma or
  a line break (syntax.decl.list-sep), so the second field is a syntax error.
- Or-patterns and struct destructuring patterns. Qualified variant patterns
  (`case Color.Red`), dotted variant patterns (`case .North`), named tuple
  patterns and tuple destructuring in a `for` head are refused with a
  diagnostic (§10).
- Parameter labels distinct from parameter names, and labels in function types.
- Declarations inside a function body, and bare block statements.
- Character literals, exponent floats, and block comments.

## 15. Spec text to update

The spec's text differs from this grammar in the passages below, or does not
yet show a spelling the grammar has. Until the spec is updated, this document's
spelling holds. The spec still:

- says that a match arm's bare body is an expression, where it may also be one
  statement (syntax.rule.arm-body);
- teaches `x as Int? ?? y`, which is refused (syntax.rule.cast-target-question);
- says `@synthesize` takes no argument, that traits cannot require a `borrows`
  method, that there are no `borrows` function values, and that a borrowing
  struct holds shared references only (SL:borrowing changes all four);
- describes a consuming `self` "declared without `&`", where the receiver is
  `&var self`;
- shows the planned `const func`, and gives the slot order as
  `consumes unsafe sync` without `constexpr` in `sync`'s place
  (syntax.rule.effect-slot);
- shows enum values only as `Enum.Case`, and does not describe implicit members:
  `.Case` and `.Case(…)` where the expected type is determined, and never in a
  pattern (syntax.expr.implicit-member, syntax.rule.implicit-member). Its `.Less`
  in "Ordering (`Comparable`)" and its `clock_get(type: .Monotonic)` in
  Appendix A are valid as written;
- does not say, under "Re-export", that an `export` declaration is refused in
  favour of `public import` (syntax.decl.refused-export);
- leaves `try`, `try?` and `try!` out of Appendix B's precedence table. They sit
  at the prefix tier, above `as`, which is how "Error routing at `try`" reads
  `try parse_id() as UserId` (syntax.rule.try-extent);
- does not say in Appendix B that `??` groups right to left, that a comparison
  chain is refused, or that a range may omit its lower bound, as in `..b`,
  `..=b` and `..` (syntax.rule.coalesce-grouping, syntax.rule.compare-chain,
  syntax.expr.range-upto);
- does not give the one-element tuple type's spelling, `(T,)`, or say that `(T)`
  in a type groups (syntax.rule.paren-type);
- does not show the `case None` pattern or the boolean
  `guard cond else { … }`, and does not say that identifiers are ASCII only
  (syntax.pat.none, syntax.stmt.guard-condition, syntax.lex.ascii-identifier).

## 16. Differences from today's parser

The reference compiler's parser (`sawc/parser/`) was checked against this
grammar over every tracked `.saw` file and a set of small test programs. Where
the two disagree, a row below says which way and why. Where a grammar rule
(§13) and today's parser refuse the same form, no row is needed. The kinds are:

- `ruled`: a ruling changed the syntax, and today's parser predates it.
- `later`: the grammar parses the form, and a later stage refuses it, because
  the tree records syntax only. Today's parser refuses it while parsing.
- `earlier`: the grammar refuses the form while parsing, and today's compiler
  refuses it in a later stage.
- `defect`: today's parser departs from the spec.

| construct | this grammar | today's parser | kind | source |
|---|---|---|---|---|
| syntax.borrow.block, syntax.borrow.place, syntax.borrow.unwrap, syntax.borrow.for, syntax.pat.borrow-binding | parses every `borrow let` and `borrow var` form | refuses them | ruled | SL:borrowing §2 |
| syntax.type.slice, syntax.expr.range-from, syntax.rule.prefix-type-suffix | parses `&[T]`, `&var [T]`, the optional slice `&[T]?`, and `buf[4..]` | refuses them | ruled | SL:borrowing §6 |
| syntax.expr.multi-subscript, syntax.rule.subscript-arguments | parses `m[r, c]` and `m[k, default: 0]` | refuses a second subscript argument | ruled | SL:borrowing §5.3 |
| syntax.decl.setitem-name, syntax.rule.subscript-declaration | parses `func []=`, and `func []` without `borrows` as a getitem | refuses both | ruled | SL:borrowing §5.1 |
| syntax.decl.borrows-sync, syntax.type.func-borrows | parses `borrows(sync)`, and `borrows` in a function type | refuses both | ruled | SL:borrowing §2.5 |
| syntax.rule.requirement-borrows | parses `borrows` on a trait requirement | refuses it | ruled | SL:borrowing §5.4 |
| syntax.decl.struct-modifier.borrows | parses a `&var` field in a `borrows struct` | refuses it | ruled | SL:borrowing §2.6 |
| syntax.stmt.lend | parses a tuple lend, `lend (a, b)` with `-> (&var T, &var T)` | refuses the reference return type | ruled | SL:borrowing §7 |
| syntax.attr.synthesize-shared | parses `@synthesize(shared)` | wants a string argument | ruled | SL:borrowing §4 |
| syntax.expr.refused-lend-var | refuses `#lend_var` | parses it; std's `data.saw` and several examples use it | ruled | SL:borrowing §4 |
| syntax.test.item | parses every `@test` form | refuses `@test` as an unknown attribute | ruled | SL:testing §2 |
| syntax.decl.constexpr | parses `constexpr` in the effect slot | refuses `constexpr` | ruled | SL:architecture §3.10 |
| syntax.rule.arm-body, syntax.rule.arm-statement-end | parses a statement arm, `case 0 -> return` | refuses `return` and `lend` there | ruled | design 259 R7′; SL-59 |
| syntax.rule.operator-continuation | continues a line that ends in a binary operator | refuses the line break | ruled | design 259 R3; SL-83 |
| syntax.expr.call | parses a call on any postfix operand, `(f)(x)`, `f(1)(2)` and `{ … }()` | refuses them | ruled | SL-73 |
| syntax.rule.trailing-closure, syntax.expr.trailing-call | attaches a bare trailing closure to a name, as in `run { 10 }`, after `try!`, and in a `static` initializer | refuses them | ruled | SL-310 |
| syntax.rule.one-call-node | builds one call node, with labelled and positional arguments mixed | parses a labelled call as a struct literal and refuses the mix | ruled | SL:architecture §3.2 |
| syntax.type.refused-cast-question, syntax.rule.cast-target-question | refuses `n as Int? ?` and every `??` after a cast target | parses `n as Int? ?` | ruled | SL-309 |
| syntax.rule.prefix-or-cast | reads `-x as Int8` as `(-x) as Int8`, and `~b as UInt64` as `(~b) as UInt64` | binds `as` tighter: `-(x as Int8)` and `~(b as UInt64)` | ruled | Appendix B: Operators; SL-400 c6 |
| syntax.rule.try-extent | reads `try parse_id() as UserId` as a cast of the unwrapped value, `(try parse_id()) as UserId` | gives `try` the whole expression, `try (parse_id() as UserId)` | ruled | Error routing at `try`; SL-400 c6 |
| syntax.rule.coalesce-grouping | groups `a ?? b ?? 0` right to left, `a ?? (b ?? 0)` | folds left, `(a ?? b) ?? 0` | ruled | Optionals; SL-400 c6 |
| syntax.rule.compare-chain, syntax.expr.refused-compare-chain | refuses `a < b < c` and `a == b == c`, with the fixit `a < b && b < c` | parses a chain, nested left: `(a < b) < c` | ruled | Ordering (`Comparable`); SL-400 c6 |
| syntax.type.paren, syntax.type.single-tuple | reads `(T)` as grouping and `(T,)` as a one-element tuple, so `((Int) -> Int)?` is an optional function | reads `(T)` and `(T,)` alike as a one-element tuple, so `((Int) -> Int)?` is an optional tuple | ruled | Composite Types; SL-400 c6 |
| syntax.decl.list-sep | refuses two fields or cases on one line with nothing between them, as in `struct P { x: Int y: Int }` | accepts them | ruled | Structs; SL-400 c6 |
| syntax.decl.refused-export | refuses `export m.f`, `export m.f as g` and `export m.*`, with the fixit `public import` | parses them, and a later stage refuses them outside a package's `init.saw` | ruled | Re-export; SL-400 c6 |
| syntax.expr.implicit-member | parses `.Case` and `.Case(…)` as an implicit member, including at the start of a line | refuses a leading `.` ("Unexpected token: DOT") | ruled | Enums (Algebraic Data Types); SL-400 c7 |
| syntax.rule.generic-close-split | splits a `>=` or `>>=` whose `>` closes a generic list, so `let v: Vector<Int>= w` parses; warns on `o!= 5` and `a&-b` | refuses the unsplit token ("Expected '>' after type arguments"), and gives no warning | ruled | Appendix B: Operators; SL-400 c6 |
| syntax.pat.none, syntax.stmt.guard-condition, syntax.expr.range-upto | parses `case None`, a boolean `guard`, and the open ranges `..b`, `..=b` and `..` | refuses them | ruled | SL-400 c6; SL-58 |
| syntax.rule.head-reset | attaches trailing closures again inside a bracket in a head, as in `if f(v.map { $0 }) { }` and `if (v.any { $0 > 1 }) { }` | keeps them off inside parentheses | ruled | Control Flow; SL-400 c6 |
| syntax.decl.extension, syntax.decl.trait | takes a qualified path in an extension head and a trait's parents | takes a bare name | ruled | Type Extensions; SL-400 c6 |
| syntax.lex.ascii-identifier | takes ASCII identifiers only | also takes Unicode letters | ruled | SL-400 c6 |
| syntax.decl.refused-effect-prefix | refuses `unsafe` and `borrows` before `func` or `init` in every head position, with the effect-slot fixit | gives a dedicated error for `unsafe` except after `static` at top level ("Expected static name") and after a visibility in a trait, and for `borrows` only at top level and not after `static`; elsewhere a generic one, such as "Expected 'type', 'func', or 'init' in extension, got BORROWS" | ruled | Spelling |
| syntax.decl.refused-effect-prefix | refuses `sync`, `constexpr`, `consumes` and `const` before `func` or `init` in every head position, with the effect-slot fixit | gives a generic error in every position, such as "Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration" | ruled | Spelling |
| syntax.decl.refused-const | refuses a top-level `const NAME: T = …` with the fixit `static` | gives the generic "Expected import, export, module, …" error | ruled | Module-level statics |
| syntax.stmt.refused-local-const | refuses a statement `const x = 5` with the fixit `let` | reads `const` as an identifier and fails on the juxtaposition | ruled | Variables and Mutability |
| syntax.type.ref | parses `&T` wherever a type goes | refuses a reference type outside a parameter, whatever the declaration | later | Reference passing; SL:borrowing §2.6; SL-400 c6 |
| syntax.rule.effect-slot | parses `consumes` beside `borrows` | refuses the pair | later | Consuming method receivers (`consumes`) |
| syntax.stmt.lend, syntax.expr.closure | parses `lend` as a closure-body statement | refuses it | later | `lend` suspends the accessor; it does not return |
| syntax.decl.requirement | parses generic parameters on a trait requirement | refuses them | later | Traits; SL-400 c6 |
| syntax.expr.refused-try-route | refuses a routing clause on `try!` or `try?`, and beside `catch` | parses them, and the type checker refuses them | earlier | Error routing at `try` |
| syntax.rule.interpolation-whole | refuses a segment that is not one expression, such as `"{1F600}"` | keeps the first token and drops the rest, which `selfhost/lexer/tests/escapes.saw` relies on | defect | String |
| syntax.stmt.guard, syntax.expr.closure | parses `guard` as a closure-body statement | refuses it | defect | Closures |
| syntax.expr.try-block, syntax.rule.try-block | refuses `try? { … } catch { … }` | parses it as a plain `try` block and drops the `?` | defect | Block Try-Catch |
| syntax.type.func-effects | refuses effect words out of order in a function type | accepts any order | defect | Spelling |
| syntax.decl.extern-params.variadic | wants `, ...` | also accepts `T ...` with no comma | defect | C FFI |
| syntax.type.func-params | refuses labels in a function type | accepts `(x: Int) -> Int` | defect | The effect on a function type |
