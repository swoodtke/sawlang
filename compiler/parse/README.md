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
builds, a `Rule` case per name a refusal can carry, and `rule_named`, which
maps a lexer's rule name onto its case, the tokens that may follow a cast
target's generic list, the FOLLOW set the recognizer computes, the tokens a
generic list can hold at its own bracket depth, which the recognizer computes
too (Speculation, below), the tokens a closure head can hold at its
brace's own depth, those a capture list holds, the tokens that begin a
statement and no expression (Braces, below), and the tokens that begin a
statement, an expression, a range's upper bound and each list's declaration
(Refusals at a stop, below). Regenerate it when GRAMMAR.md changes;
`compiler/tests/run.py` fails while it is stale.

## Speculation

A `<` after a name, a member or a cast target may open a generic list or
compare (syntax.rule.generic-or-less), and the parser decides by parsing the
list and looking at the token after it. `Parser.checkpoint` opens such a
speculation and `restore` undoes it: the nodes built, the tokens an
interpolation appended or a list's close split, the alternatives recorded and
the levels taken. Nothing is reported while one is open. The SPECULATION LEDGER
above `Parser.checkpoint` gives every field of `Parser` its decision, restored,
unchanged or kept and why, and the one above `TreeBuilder.checkpoint` does the
same for the builder and the tree it builds; `compiler/tools/speculation_ledger.py`
fails when a field has none or a `restore` does not name one it claims to
restore.

Before speculating, the parser scans ahead of the `<` for a token that could
close the list at its bracket depth, and compares at once when there is none,
so a flat run of comparisons speculates nothing. The scan passes nested `( )`
and `[ ]` groups whole and stops at an unmatched `)` or `]`, or at any token no
generic-arguments derivation holds at the list's own depth: `stops_list_scan`
in `grammar.saw`, which is generated, never listed by hand, since a token
wrongly on it turns a generic list into comparisons. The recognizer tests
check the committed table against sentences of `generic-args` that hold each
token, and fail with `var` made a stop or `:` made a pass.

## Braces

A `{` in expression position is a map, a set or a closure
(syntax.rule.brace), and the parser decides it without speculating. `{:}` is
the empty map. A closure head is found by a scan past the `{` that passes
nested `( )` and `[ ]` groups whole and every token a closure head holds at
the brace's own depth, and finds its `in`: `holds_closure_head` in
`grammar.saw`, generated, and checked by the recognizer tests against a
sentence of `closure-head` holding each token, failing with `:` made a stop or
`{` made a pass. A leading `[` group is a capture list only when it holds what
captures hold (`holds_capture`, generated too), and two names side by side,
but `any P`, stand in no head, so `{ [borrow let x = a] in x }` and
`{ a b in c }` are closures whose first statement is refused as the
recognizer refuses it. Only a `for` puts an `in` in a statement, and `for` is no head
token, so a body never reads as a head. Otherwise a statement-only token first
makes a closure: one that begins a statement and no expression,
`begins_statement_only` in `grammar.saw`, generated as FIRST(non-expr-statement)
less FIRST(expr) and checked by the recognizer tests against witness sentences,
failing with `let` dropped or `*` added. Any other first element is parsed once, as a
closure's first statement would be (`StatementPlace.BraceFirst`, which leaves
an expression without its statement node), and the token after it decides: a
`:` on its line makes a map whose first key it is, a `,` after any line breaks
a set, and anything else a closure whose first statement it is.

A trailing closure attaches after a name, an implicit member, a member, or a
call of one (syntax.rule.trailing-closure). At a head's outer level such a `{`
begins the body instead, and the statement notes it. A refusal later in the
statement, a plain parse error or a rule the head restriction outranks, is
syntax.rule.head-restriction when the head, read again inside a speculation
with a closure attached at that `{` (`HeadState.Lifted`), goes on to the token
its construct takes next. Map and set literals start no fresh level, so their
elements stand in any head around them; a brace's first element is parsed
before the brace is known to be a literal, so a closure attaching there is
noted (`HeadState.Shadow`) and refused if the brace turns out to be one.

## Infinite loops

A `{` right after `while` begins the infinite loop's body
(syntax.rule.infinite-loop). The text is the refused form instead where a
condition read again from that `{`, inside a speculation, goes on with no
error to a body's `{` (`brace_condition_ahead`): a body that met an error is
refused as syntax.expr.refused-brace-condition at the `{`, and a sound one by
the rule, at the token after it on its line, when that token would continue
the condition.

## Refusals at a stop

Where the productions stop a text, the parser names the rule the recognizer
reads at that stop (compiler/tests/parse/README.md, Refusals). After a
statement that ended on its line, a token that begins a statement is
syntax.rule.juxtaposition, an assignment operator syntax.rule.assignment-target
and a `catch` past a plain `try`'s extent syntax.rule.try-extent
(`refuse_juxtaposed`); after a declaration, a `;` or a token that begins a
declaration of that list is syntax.rule.declaration-separator. `return` and
`break` take an operand only when the token after them begins an expression.
A range operator before a token that neither ends an open range nor begins an
upper bound is syntax.rule.range-open-end, and a borrow binding's `=` before
one that begins no expression is syntax.rule.borrow-form, as are bindings that
no brace follows at all. Each FIRST set is a generated table.

## Comma lists

Every list whose elements a `,` separates goes through one funnel,
`Parser.parse_comma_list`: import symbols, parameters, function-type
parameters, tuple types, generic parameters and arguments, call arguments,
a multi-argument subscript's arguments, tuple expressions, array, map and set
elements, tuple and payload patterns, closure parameters and capture lists,
struct fields, enum cases and their payload fields, extern parameters, a
trait's parents, an extension's conformances and a `borrow` block's bindings.
`list_shape` is the position matrix, one
row per list: the element parser (`CommaList`, which `parse_list_element`
dispatches on), the closer the funnel tests for and the caller consumes (a
bracket, a generic list's `>`, which a `>=` or `>>=` may hold, `in`, or the
`{` of a declaration's body), the
trailing-comma policy and the rule that names its refusal, where the list's
line breaks are decided, and whether it may be empty. Between fields and
between cases a line break separates as a comma does, and the funnel records
which `list-sep` stood there (`LineBreaks.Separate`, syntax.decl.list-sep).
An attribute takes one argument, and a test case one clause, never a list.
A caller that must parse the first element to tell the list apart, as `(e)`
from a tuple, a brace's first element from a map's, or a subscript's one
argument from several, hands the funnel the rest. A refused trailing comma
inside a speculation is noted and refused only if the list is kept, so that
`f<Int,>(1)` is refused as syntax.generic.refused-arg-comma and not re-read as
comparisons. `golden/lists.saw` and `negative/lists.saw` in
`compiler/tests/parse/` hold a case for each row.

`compiler/tools/comma_funnel.py` fails on a loop that takes a `,` outside the
funnel, unless the COMMA LEDGER above the funnel exempts it with a reason (a
`match` arm's separator is one), and on an ENTRY POINTS list that is not
exactly the funnel's callers. It proves itself on copies of the parser with an
ad hoc list loop added, a stale exemption and a missing entry point.

## Declarations

A declaration's head is read ahead past its attributes and visibility before
anything is built, since what it declares decides which of them it may carry
(syntax.rule.attribute-position) and whether a `///` run before it documents
it (syntax.lex.doc-attach). The same scan finds the heads GRAMMAR.md section 10
refuses: an effect word before `func` or `init`, `const`, `private`, a
visibility on an extension, `unsafe` on an enum, a trait or an extension, and
the malformed statics. A trait's, an extension's and an extern block's members
stand one per line, and a member that fails is skipped to the end of its line,
as a top-level item is. The receiver rule and the effect slot's rules are
checked once a declaration's parameters and effects are parsed
(`parse_signature`). A test case's or group's head refuses a doc run before it
at once, since nothing it holds can make the run document anything.

## Borrow forms

The tokens after `borrow` decide its form (syntax.rule.borrow-form):
`Parser.borrow_binding_end` finds `let` or `var`, a name or a parenthesized
pattern, and `=`, which make a binding. A binding is a `borrow` block, a
primary; at an `if`, `else if` or `while` head it is the unwrap, which binds
one name; and at a `guard` head it is refused. Anything else is the place
form, whose operand is one postfix chain, or with `let` the refused unbound
form. A borrow binding's head is a head, which the next binding's `,` or the
body's `{` follows, so the head restriction's re-read accepts either there.
The place form at a statement's start is kept open, as a leading chain is
(Assignment targets, below): an assignment makes it a target, and an
exclusive one whose optional run is open at the end writes through the chain.

## Tests

After `@test`, a string or `(` makes a case, `{` a group and anything else
makes the declaration after it test-only (syntax.rule.test-form). A case's
clause is one of `panics:`, `warns:` and `refuses:`, with an optional
`text:` and `at:` in that order. A `refuses:` case's body is matched by its
braces only, each token between them a leaf, line breaks included; a test
build parses it apart, from `refusal-unit` (`--unit`). A group holds items,
as an inline module does, and takes its level at its `{`. A `///` run before
the `@test` of a test-only declaration documents the declaration.

## Assignment targets

A statement that starts with a postfix chain, or with `*`, may be an
assignment, and only the operator after the chain says so. The parser parses
the chain once, keeping its own alternative and each hop's aside
(`spine_alts`). Before an assignment operator it records them as the target's
production derives them (a place hop, a call target, an optional-chain target,
a bare name or `self`); otherwise it records them as an expression's and goes on
parsing the expression with the chain already on the scratch stack as its first
operand (`primed`). No statement is parsed twice.

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
  rule's or removed production's stable name, a lexical rule's for a lex error
  one names, or `parse-error`. An unclosed bracket is found before the parse
  begins, so its refusal, at the opener, comes first;
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

## Long lines

A parse costs time linear in its input, however long its lines are. A token's
byte span starts at the offset the lexer records beside it (`LexResult.offsets`),
and an interpolation segment's at its own `offset`, so nothing converts a
`line:col` back into a byte on the token path: that walk is linear in the
column, which makes it quadratic over a long line's tokens. `SourceFile.offset_of`
remains for one-off positions, a lex error's and a doc line's.
`compiler/tests/line_length.py` holds the parser to it: 20,000 call arguments, a
set literal of 20,000 elements and a tuple pattern of 20,000 names, each on one
line, must parse within a small factor of the time the same call takes written
one argument per line.
