# sawlex — the Saw lexer, in Saw

The first permanent module of the eventual stage1 (self-hosting) Saw compiler,
and a measurement instrument for the rewrite decision (design 116). It is a
faithful port of `sawc/lexer.py`: same token kinds, same token boundaries, same
1-based `line:col` positions, and the same lex-error positions.

The Python lexer's **observable output** is the correctness reference;
`LANGUAGE_SPEC.md`'s lexical section is authoritative where the two disagree.

## Layout

```
selfhost/lexer/
  Saw.toml          # Blade package manifest (name = "sawlex")
  src/lib.saw       # token model (TokenKind + Token + StringSegment) + `lex` + dump format
  src/main.saw      # the `sawlex` CLI
  tests/*.saw       # blade unit tests, one per token family
```

Build / run directly with sawc:

```
.venv/bin/python sawc/sawc.py selfhost/lexer/src/main.saw -o .build/sawlex
.build/sawlex <file.saw>
```

or via Blade (`blade build` / `blade test`) like the `libs/` packages.

## Canonical token-dump format

`sawlex <file.saw>` emits one record per token, newline-separated:

```
KIND<TAB>line:col<TAB>escaped-text[<TAB>suffix]
```

* `KIND` — the token kind name (see the mapping table below); identical to the
  Python lexer's `TokenType.name`.
* `line:col` — 1-based, at the token's first byte/character.
* `escaped-text` — the token's canonical text (decoded for strings; underscores
  stripped and the base prefix lowercased for numbers), escaped at the **byte**
  level: `\\` for backslash, `\n` `\t` `\r` for those controls, `\0` for NUL, any
  other control byte (`< 0x20` or `0x7F`) as `\xHH`, and every other byte —
  including raw UTF-8 `>= 0x80` — verbatim.
* `suffix` — a 4th column, present **only** for a fixed-width-suffixed integer
  literal: one of `i8`/`i16`/`i32`/`i64`/`u8`/`u16`/`u32`/`u64`. `255u8` dumps as
  `INT<TAB>1:1<TAB>255<TAB>u8`; every other token stops at the escaped text.

### An `INTERP_STRING` record carries its segments

An interpolated string's `escaped-text` is the literal's **raw source spelling**
between the quotes (undecoded), and the record then continues with **one field
per typed segment** (design 268), in source order:

```
INTERP_STRING<TAB>line:col<TAB>raw<TAB>T:text<TAB>E:line:col:raw-expr...
```

* `T:` — a literal run, **decoded** (so an escaped brace is a plain `{`/`}`).
* `E:line:col:` — an interpolation, carrying the **raw** text between its braces
  and the exact 1-based source position of its opening `{`.

An empty `T:` run is never emitted, so two adjacent interpolations produce two
consecutive `E:` fields. No token carries both a suffix and segments, so the
tail is unambiguous. The segments are what a parser consumes: nothing is encoded
into the token's bytes, which is what design 268 replaced (an escaped brace used
to be the two bytes `0x01` + brace — indistinguishable from that same pair
written as content, which silently lost it; SL-238).

On a lex error the CLI emits a single record and exits nonzero:

```
ERROR<TAB>line:col<TAB>message
```

Error **positions and kinds** match the Python lexer; message **prose does not**
(the differential harness compares the `ERROR` tag + position only).

`tools/dump_tokens.py` emits the byte-identical format from the Python lexer;
`tools/lexdiff.py` (`make lexdiff`) diffs the two dumps over every tracked `.saw`
file. Zero mismatches over the corpus is the acceptance bar.

## Doc-comment trivia dump

`sawlex --docs <file.saw>` emits the documentation comments instead of the token
stream, one record per captured line:

```
DOC<TAB>line:col<TAB>kind<TAB>escaped-text
```

* `kind` — `doc` for a `///` line, `module` for a `//!` line.
* `line:col` — 1-based, at the leading `/`.
* `escaped-text` — the line body with the `///`/`//!` marker and one following
  space stripped, escaped by the same byte-level scheme as a token's text.

Doc comments are **trivia**: `lex` skips them exactly as it skips `//` comments,
so the token dump above is unaffected. `lex` returns one `LexResult` carrying
the tokens, the doc records and the string-segment arena together — there is no
tokens-only entry point, because a token's `seg_start`/`seg_count` index into
that arena. Only a comment that starts its line is a doc comment; `////`
(four or more slashes) and a `///` trailing code on the same line are ordinary
comments.

`tools/dump_tokens.py --docs` emits the same records from the Python lexer, and
`make lexdiff` sweeps both dumps over the corpus (`--mode tokens|docs` picks one).

## Kind-name mapping (TokenKind case → dump name)

The Saw `TokenKind` enum is the model. Case names are Saw-idiomatic; the dump
name column is what appears in a record and matches Python's `TokenType.name`.

| TokenKind case | dump name | TokenKind case | dump name |
|---|---|---|---|
| `IntLit` | `INT` | `WrapAdd` | `WRAP_ADD` |
| `FloatLit` | `FLOAT` | `WrapSub` | `WRAP_SUB` |
| `StringLit` | `STRING` | `WrapMul` | `WRAP_MUL` |
| `InterpString` | `INTERP_STRING` | `Not_` | `NOT` |
| `BoolLit` | `BOOL` | `Move_` | `MOVE` |
| `Ident` | `IDENT` | `Unsafe_` | `UNSAFE` |
| `Func` | `FUNC` | `Assign` | `ASSIGN` |
| `Let` | `LET` | `PlusAssign` | `PLUS_ASSIGN` |
| `Var` | `VAR` | `MinusAssign` | `MINUS_ASSIGN` |
| `If` | `IF` | `StarAssign` | `STAR_ASSIGN` |
| `Else` | `ELSE` | `SlashAssign` | `SLASH_ASSIGN` |
| `Guard` | `GUARD` | `PercentAssign` | `PERCENT_ASSIGN` |
| `Return` | `RETURN` | `AmpAssign` | `AMP_ASSIGN` |
| `True_` | `TRUE` | `PipeAssign` | `PIPE_ASSIGN` |
| `False_` | `FALSE` | `CaretAssign` | `CARET_ASSIGN` |
| `Struct` | `STRUCT` | `ShlAssign` | `SHL_ASSIGN` |
| `Extension` | `EXTENSION` | `ShrAssign` | `SHR_ASSIGN` |
| `SelfKw` | `SELF` | `Question` | `QUESTION` |
| `Init` | `INIT` | `DoubleQuestion` | `DOUBLE_QUESTION` |
| `NoneKw` | `NONE` | `Exclaim` | `EXCLAIM` |
| `Enum` | `ENUM` | `QuestionDot` | `QUESTION_DOT` |
| `Case` | `CASE` | `DotDot` | `DOTDOT` |
| `Match` | `MATCH` | `DotDotEq` | `DOTDOT_EQ` |
| `While` | `WHILE` | `Ellipsis` | `ELLIPSIS` |
| `Break` | `BREAK` | `LParen` | `LPAREN` |
| `Continue` | `CONTINUE` | `RParen` | `RPAREN` |
| `Trait` | `TRAIT` | `LBrace` | `LBRACE` |
| `For` | `FOR` | `RBrace` | `RBRACE` |
| `In` | `IN` | `LBracket` | `LBRACKET` |
| `TypeKw` | `TYPE` | `RBracket` | `RBRACKET` |
| `Extern` | `EXTERN` | `Comma` | `COMMA` |
| `As` | `AS` | `Colon` | `COLON` |
| `Try` | `TRY` | `Semicolon` | `SEMICOLON` |
| `Catch` | `CATCH` | `Arrow` | `ARROW` |
| `Static` | `STATIC` | `Dot` | `DOT` |
| `Module` | `MODULE` | `At` | `AT` |
| `Import` | `IMPORT` | `HashDirective` | `HASH_DIRECTIVE` |
| `Public` | `PUBLIC` | `DollarParam` | `DOLLAR_PARAM` |
| `Export` | `EXPORT` | `Newline` | `NEWLINE` |
| `Package` | `PACKAGE` | `Eof` | `EOF` |
| `Parent` | `PARENT` | `Plus` … `Tilde` | `PLUS` … `TILDE` |

The remaining single-character operators/keywords map by uppercasing:
`Minus`→`MINUS`, `Star`→`STAR`, `Slash`→`SLASH`, `Percent`→`PERCENT`,
`Eq`→`EQ`, `Neq`→`NEQ`, `Lt`→`LT`, `Gt`→`GT`, `Lte`→`LTE`, `Gte`→`GTE`,
`And`→`AND`, `Or`→`OR`, `Ampersand`→`AMPERSAND`, `Pipe`→`PIPE`,
`Caret`→`CARET`, `Tilde`→`TILDE`. `Module`/`Import`/`Export`/`Package`/`Parent`
exist in the enum for completeness but are never produced — like the Python
lexer, those words lex as `IDENT` (the parser handles them positionally).

## Note on the port strategy

The port lexes over the source's UTF-8 **bytes** while counting columns by code
point (a column advances once per non-continuation byte). That reproduces the
Python lexer's per-code-point column counting exactly while letting token text be
assembled from raw bytes. The only place a scalar is re-encoded is a `\u{...}`
escape, which goes through the std `StringBuilder.append(scalar: Scalar)`
(design 245; the port's hand-rolled `encode_utf8` is gone).
