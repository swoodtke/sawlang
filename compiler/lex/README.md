# sawlex: the Saw lexer, in Saw

The lexer stage of the self-hosted compiler (`compiler/README.md`). It produces
the same token kinds, token boundaries and 1-based `line:col` positions as the
Python lexer in `sawc/lexer.py`, except where GRAMMAR.md's lexical layer (§2)
decides otherwise, and GRAMMAR.md §16 records each such difference:

- `borrow` is a keyword here and an identifier there;
- a number's `_` stands between two digits, or is the one `_` before a width
  suffix, and a base prefix is lowercase (§2.1); the Python lexer accepts
  `1__000`, `1_`, `0x_FF`, `0XFF` and the like;
- `.5` is refused, with a hint naming `0.5` (syntax.lex.float-point);
- an unterminated string is reported at its opening quote, or at the `{` of an
  interpolation that took its closing quote (syntax.lex.unterminated-string),
  and a bad escape at its backslash (syntax.lex.escape).

`LANGUAGE_SPEC.md` is authoritative for meaning and GRAMMAR.md for spelling.
The golden fixtures in `compiler/tests/lex/` pin its output.

## Layout

```
compiler/lex/
  Saw.toml          # package manifest (name = "sawlex")
  src/lib.saw       # the token model (TokenKind, Token, StringSegment), `lex`, the dump format
  tests/*.saw       # unit programs, one per token family
```

The CLI is the driver's `lex` subcommand:

```
./.venv/bin/python compiler/tools/build.py
.build/sawc2 lex [--docs] <file.saw>
.build/sawc2 lex --kinds
```

## Canonical token-dump format

`sawc2 lex <file.saw>` emits one record per token, newline-separated:

```
KIND<TAB>line:col[<TAB>escaped-text][<TAB>suffix]
```

* `KIND` is the token kind's dump name (see the mapping table below).
* `line:col` is 1-based, at the token's first byte or character.
* `escaped-text` is the token's canonical text (decoded for strings; underscores
  and a width suffix's `_` stripped for numbers), escaped at the **byte**
  level: `\\` for backslash, `\n` `\t` `\r` for those controls, `\0` for NUL, any
  other control byte (`< 0x20` or `0x7F`) as `\xHH`, a space that ends the text
  as `\x20`, and every other byte, including raw UTF-8 `>= 0x80`, verbatim.
* `suffix` is a 4th column, present **only** for a fixed-width-suffixed integer
  literal: one of `i8`/`i16`/`i32`/`i64`/`u8`/`u16`/`u32`/`u64`. `255u8` dumps as
  `INT<TAB>1:1<TAB>255<TAB>u8`; every other token stops at the escaped text.

**No record ends in whitespace.** When the last field of a record is empty, it is
left out together with the tab before it: the end-of-file token dumps as
`EOF<TAB>6:1`, an empty string as `STRING<TAB>1:1`, and an empty doc line as
`DOC<TAB>8:1<TAB>doc`. An empty field with another field after it keeps its tab,
since that tab does not end the record. And a space that ends an escaped field
is written `\x20`, so `"a "` dumps as `STRING<TAB>1:1<TAB>a\x20`. Tools that strip
trailing whitespace, such as `git apply --whitespace=fix` and most editors,
therefore leave every record intact.

The format changed to this after the one-time comparison with the Python
lexer's dump (SL-399). That comparison was made in the earlier format, where
such a record ended in a tab or a space. The golden fixtures were regenerated in
this format, and they are the oracle.

`sawc2 lex --kinds` prints every kind's dump name, one per line, in the order
`TokenKind` declares them.

### An `INTERP_STRING` record carries its segments

An interpolated string's `escaped-text` is the literal's **raw source spelling**
between the quotes (undecoded), and the record then continues with **one field
per typed segment** (design 268), in source order:

```
INTERP_STRING<TAB>line:col<TAB>raw<TAB>T:text<TAB>E:line:col:raw-expr...
```

* `T:` is a literal run, **decoded** (so an escaped brace is a plain `{`/`}`).
* `E:line:col:` is an interpolation, carrying the **raw** text between its braces
  and the exact 1-based source position of its opening `{`.

Both are escaped as the text field is, final space included.

An empty `T:` run is never emitted, so two adjacent interpolations produce two
consecutive `E:` fields. No token carries both a suffix and segments, so the
tail is unambiguous. The segments are what a parser consumes: nothing is encoded
into the token's bytes.

On a lex error the CLI emits a single record and exits 1:

```
ERROR<TAB>line:col<TAB>message<TAB>rule[<TAB>hint]
```

* `line:col` is where GRAMMAR.md §2.7 reports the refusal, at the offending
  character.
* `message` is this lexer's own wording, for the reader.
* `rule` is the stable id the refusal is compared by: the §2.7 rule it applies
  (`syntax.lex.escape`, `syntax.lex.unterminated-string`, ...); for a number
  that breaks §2.1's spelling, which no §2.7 rule names, the token production,
  `syntax.expr.int` or `syntax.expr.float`; and `parse-error` for the rest, an
  unexpected character and a `$` with no digits.
* `hint` suggests a fix, such as `` write `1_000` ``, and is left out with its
  tab when there is none.

## Doc-comment trivia dump

`sawc2 lex --docs <file.saw>` emits the documentation comments instead of the
token stream, one record per captured line:

```
DOC<TAB>line:col<TAB>kind[<TAB>escaped-text]
```

* `kind` is `doc` for a `///` line and `module` for a `//!` line.
* `line:col` is 1-based, at the leading `/`.
* `escaped-text` is the line body with the `///`/`//!` marker and one following
  space stripped, escaped by the same byte-level scheme as a token's text. An
  empty body is left out with its tab.

Doc comments are **trivia**: `lex` skips them exactly as it skips `//` comments,
so the token dump above is unaffected. `lex` returns one `LexResult` carrying
the tokens, the doc records and the string-segment arena together. There is no
tokens-only entry point, because a token's `seg_start`/`seg_count` index into
that arena. Only a comment that starts its line is a doc comment; `////`
(four or more slashes) and a `///` trailing code on the same line are ordinary
comments.

## Kind-name mapping (TokenKind case to dump name)

| TokenKind case | dump name | TokenKind case | dump name |
|---|---|---|---|
| `IntLit` | `INT` | `WrapAdd` | `WRAP_ADD` |
| `FloatLit` | `FLOAT` | `WrapSub` | `WRAP_SUB` |
| `StringLit` | `STRING` | `WrapMul` | `WRAP_MUL` |
| `InterpString` | `INTERP_STRING` | `Not_` | `NOT` |
| `Ident` | `IDENT` | `Move_` | `MOVE` |
| `Func` | `FUNC` | `Unsafe_` | `UNSAFE` |
| `Let` | `LET` | `Borrow` | `BORROW` |
| `Var` | `VAR` | `Borrows` | `BORROWS` |
| `If` | `IF` | `Lend` | `LEND` |
| `Else` | `ELSE` | `Assign` | `ASSIGN` |
| `Guard` | `GUARD` | `PlusAssign` | `PLUS_ASSIGN` |
| `Return` | `RETURN` | `MinusAssign` | `MINUS_ASSIGN` |
| `True_` | `TRUE` | `StarAssign` | `STAR_ASSIGN` |
| `False_` | `FALSE` | `SlashAssign` | `SLASH_ASSIGN` |
| `Struct` | `STRUCT` | `PercentAssign` | `PERCENT_ASSIGN` |
| `Extension` | `EXTENSION` | `AmpAssign` | `AMP_ASSIGN` |
| `SelfKw` | `SELF` | `PipeAssign` | `PIPE_ASSIGN` |
| `Init` | `INIT` | `CaretAssign` | `CARET_ASSIGN` |
| `NoneKw` | `NONE` | `ShlAssign` | `SHL_ASSIGN` |
| `Enum` | `ENUM` | `ShrAssign` | `SHR_ASSIGN` |
| `Case` | `CASE` | `Question` | `QUESTION` |
| `Match` | `MATCH` | `DoubleQuestion` | `DOUBLE_QUESTION` |
| `While` | `WHILE` | `Exclaim` | `EXCLAIM` |
| `Break` | `BREAK` | `QuestionDot` | `QUESTION_DOT` |
| `Continue` | `CONTINUE` | `DotDot` | `DOTDOT` |
| `Trait` | `TRAIT` | `DotDotEq` | `DOTDOT_EQ` |
| `For` | `FOR` | `Ellipsis` | `ELLIPSIS` |
| `In` | `IN` | `LParen` | `LPAREN` |
| `Extern` | `EXTERN` | `RParen` | `RPAREN` |
| `As` | `AS` | `LBrace` | `LBRACE` |
| `Try` | `TRY` | `RBrace` | `RBRACE` |
| `Catch` | `CATCH` | `LBracket` | `LBRACKET` |
| `Static` | `STATIC` | `RBracket` | `RBRACKET` |
| `Public` | `PUBLIC` | `Comma` | `COMMA` |
| `Plus` … `Tilde` | `PLUS` … `TILDE` | `Colon` | `COLON` |
| `HashDirective` | `HASH_DIRECTIVE` | `Semicolon` | `SEMICOLON` |
| `DollarParam` | `DOLLAR_PARAM` | `Arrow` | `ARROW` |
| `Newline` | `NEWLINE` | `Dot` | `DOT` |
| `Eof` | `EOF` | `At` | `AT` |

The remaining single-character operators map by uppercasing:
`Minus`→`MINUS`, `Star`→`STAR`, `Slash`→`SLASH`, `Percent`→`PERCENT`,
`Eq`→`EQ`, `Neq`→`NEQ`, `Lt`→`LT`, `Gt`→`GT`, `Lte`→`LTE`, `Gte`→`GTE`,
`And`→`AND`, `Or`→`OR`, `Ampersand`→`AMPERSAND`, `Pipe`→`PIPE`,
`Caret`→`CARET`, `Tilde`→`TILDE`. The words `module`, `import`, `export`,
`package`, `parent` and `type` are not keywords: each lexes as `IDENT`, and the
parser decides by position.

## How it reads the source

The lexer works over the source's UTF-8 **bytes** while counting columns by code
point (a column advances once per non-continuation byte). That gives the
per-code-point columns positions are defined in, and lets token text be
assembled from raw bytes. The only place a scalar is re-encoded is a `\u{...}`
escape, which goes through the std `StringBuilder.append(scalar: Scalar)`
(design 245).
