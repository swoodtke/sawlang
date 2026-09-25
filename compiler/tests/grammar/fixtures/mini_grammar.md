# Mini grammar

The lint fixtures edit a copy of this file. It holds one of each structure that
GRAMMAR.md has, and it lints clean against mini_spec.md.

## 1. Notation

```ebnf-notation
status              ::= "current" | "lockdown" | "retired" | "removed" | "pending"
```

**Start symbols.** `source-file` is a source file.

## 2. Lexical layer

| kind | spelling | notes |
|---|---|---|
| IDENT | a name | |
| NEWLINE | a line break | |
| EOF | end of input | |

| class | spellings |
|---|---|
| delimiters | `(` `)` `,` `\|` |

These words are keywords. They cannot name anything:

`let` `var`

| word | position | production |
|---|---|---|
| `sync` | after a `var` item's name | syntax.mini.item |

| rule | statement | source |
|---|---|---|
| syntax.lex.longest-match | The lexer takes the longest token. | Spelling |

## 3. Productions

```ebnf
# syntax.mini.file  status=current  spec="Spelling"  node=File
source-file ::= NEWLINE* item-list? EOF

# syntax.mini.items  status=current  spec="Spelling"  node=-
item-list ::= item ( NEWLINE+ item )*

# syntax.mini.item  status=current  spec="Spelling"  node=Item
item ::= "let" IDENT  @syntax.mini.item.let
    | "var" IDENT 'sync'?  @syntax.mini.item.var
    | "(" head-expr ")"  @syntax.mini.item.group
    | refused-item  @syntax.mini.item.refused

# syntax.mini.head  status=lockdown  spec="Spelling"  node=-  ref="SL-400 c6"
head-expr ::= expr

# syntax.mini.expr  status=current  spec="Spelling"  node=Name
expr ::= IDENT ( "," IDENT )*

# syntax.mini.refused  status=removed  spec="Spelling"  node=Error
refused-item ::= "var" "|"
```

| tier | operators | associativity | production |
|---|---|---|---|
| 1 | `,` | left, flat | syntax.mini.expr |

| construct | why | write instead |
|---|---|---|
| syntax.mini.refused | A bar is not an item. | `let x` |

| shape | parses as | replacement |
|---|---|---|
| `var x sync` | syntax.mini.item | `let x` |

| construct | charge | held until |
|---|---|---|
| syntax.mini.item | 1 for the `(` | its `)` |

## 12. Contexts

| context | position | restriction |
|---|---|---|
| stmt | an item | none |
| grp | inside a group | head |

| code | meaning |
|---|---|
| Y | allowed |
| N | not allowed |

| construct | stmt | grp |
|---|:-:|:-:|
| syntax.mini.expr | N | Y |

## 13. Disambiguation

| rule | constructs | resolution | source | status |
|---|---|---|---|---|
| syntax.rule.group | syntax.mini.item, syntax.mini.head | A `(` opens a group. | Spelling | current |

## 16. Differences

- `ruled`: a ruling changed the syntax.
- `defect`: today's parser departs from the spec.

| construct | this grammar | today's parser | kind | source |
|---|---|---|---|---|
| syntax.mini.item.var, syntax.rule.group | parses `var x sync` | refuses it | ruled | SL-400 c6 |
