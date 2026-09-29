# compiler/parse: the parser

The parser stage of the self-hosted compiler, package `sawparse` (epic SL-398,
unit U4 of SL-424). It reads the tokens of `sawlex` and builds the arena AST of
SL:architecture §3.2, whose canonical dump `compiler/tests/parse/README.md`
specifies. `GRAMMAR.md` is its authority for spelling.

```
parse/
  CLAIMS.tsv        the alternatives and rules the parser implements so far
  src/
    api.saw         parse_source and the record `sawc2 parse` prints for a file
    parser.saw      recursive descent, the depth funnel, recovery, doc comments
    tokens.saw      the lexer's tokens with byte spans, line breaks settled, and
                    the expression segments of interpolated strings
    tree.saw        the arena, its builder and its invariant checker
    render.saw      the canonical dump, rendered from the arena
    reader.saw      a reader of the dump's text back into an arena
    source.saw      the source buffer, its file identity and line index
    diag.saw        diagnostics as records
    grammar.saw     the grammar tables, generated from GRAMMAR.md
  tests/*.saw       unit programs
```

`grammar.saw` is written by `compiler/tools/grammar_tables.py`: an `Alt` case
per alternative of GRAMMAR.md, with its stable name and the Kind of the node it
builds, a `Rule` case per name a refusal can carry, and the tokens that may
follow a cast target's generic list, the FOLLOW set the recognizer computes.
Regenerate it when GRAMMAR.md changes; `compiler/tests/run.py` fails while it
is stale.

## Speculation

A `<` after a name, a member or a cast target may open a generic list or
compare (syntax.rule.generic-or-less), and the parser decides by parsing the
list and looking at the token after it. `Parser.checkpoint` opens such a
speculation and `restore` undoes it: the nodes built, the tokens an
interpolation appended or a list's close split, the alternatives recorded and
the levels taken. Nothing is reported while one is open. The SPECULATION LEDGER
above `checkpoint` gives every field of `Parser` its decision, restored or
unchanged and why, and `compiler/tools/speculation_ledger.py` fails when a
field has none or `restore` does not name one it claims to restore.

## `sawc2 parse`

```sh
.build/sawc2 parse --dump [--alternatives] [[--unit] FILE | @LIST]...
.build/sawc2 parse --check [[--unit] FILE | @LIST]...
.build/sawc2 parse --redump [FILE | @LIST]...
```

Each input gets one record, in order, so one process can cover a corpus. A
record starts with the line `FILE<TAB>path` and holds:

- for a refused file, one `ERROR<TAB>id<TAB>line:col<TAB>message[<TAB>hint]` line
  per diagnostic, in the order they were found, where `id` is the refusing
  rule's or removed production's stable name, or `parse-error`;
- for an accepted file, with `--dump`, its canonical dump; with
  `--alternatives`, one `ALT` line naming, tab-separated, every alternative its
  derivation took; and an `INVARIANT<TAB>message` line should its tree break
  the arena's invariants.

`--unit` parses the file after it from `refusal-unit`, as a test build parses a
refusal case's body. `@LIST` names a file of inputs, one path per line, a line
`--unit PATH` for a refusal unit. `--redump` reads a file of dumps, such as an
expectation file of `compiler/tests/parse/`, into arenas and renders each again,
keeping every other line; the renderer agrees with its reader exactly when the
file comes back unchanged. The exit code is 1 when any file is refused, 2 on a
usage or I/O failure, and 0 otherwise.

## The claims

`CLAIMS.tsv` lists, one per line after its header, the GRAMMAR.md alternatives,
§13 rules, lexical rules and removed productions the parser implements, each
with the unit that claimed it. The parse lane, `compiler/tests/parse_lane.py`,
reads it (SL-424, contract item 7):

- a generated, golden or dump-pin case, and a `tests/corpus/` file, whose
  recognizer record uses claimed alternatives only, must be accepted with
  exactly its expected dump and a derivation record equal to the recognizer's;
- a negative case whose expected refusal is claimed must be refused first by
  that name;
- a negative case the parser accepts while every alternative of its own
  derivation is claimed fails, since the parser then accepts ground it claims
  that the recognizer refuses;
- everything else counts as not yet.

Claiming an alternative is how a unit says it is done with it: a claimed
alternative whose cases fail fails the lane.

## The depth funnel

Every construct GRAMMAR.md §11 charges takes its level through
`Parser.enter_level`, at its opener. `compiler/tools/depth_funnel.py` checks,
over the source, that every recursive call cycle crosses that funnel and that
the funnel's ENTRY POINTS list names exactly the methods that charge; and, by
running `sawc2 parse`, that 256 levels parse, the 257th is refused at its opener
as syntax.rule.depth-limit, a flat chain of any length parses, and a refused
statement gives its levels back. The run-time cells cover each charging
construct kind, those a loop charges too (an `as` chain and a postfix chain),
since the static check sees only recursion, and a speculation that fails at the
limit, which must give its levels back to the reading that follows it. Its fixtures, in
`compiler/tests/funnel/`, and a copy of the parser with the funnel cut out of
`parse_paren` show that it fails on a recursion that bypasses the funnel.
