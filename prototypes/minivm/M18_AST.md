# M18: arena AST and first standalone parser

Tracking: SL-301, child of the SL-300 parser epic.

User direction, September 15: generate an AST first; classify and compare the
top-level examples corpus after this works. This is the next prototype step
after SL-260, not the whole production parser port in design 259. The user's
September 10 arena/index ruling supersedes design 259 U2's Box-linked storage;
its canonical dump and no-divergence requirements still govern the later port.

## Contract

Build `prototypes/parser/src/lib.saw` using the unchanged selfhost lexer. The
same parser source must execute under Python-built native Saw and under the
existing mini-VM (with import-free source assembly as in test_lexer.py). It
constructs syntax only: unresolved names and mismatched types are valid trees.
Do not call or modify minivm's semantic frontend. Do not add VM features merely
to avoid designing within the existing subset.

AST storage is an append-only arena of flat AstNode records and a separate
Vector<Int> of child IDs. IDs are node indices, valid until their owning arena
is destroyed. No recursive owning fields, pointers, borrowed arena elements,
or mutation of existing nodes. Child IDs must refer to previously appended
nodes; append an entire ordered child run only after constructing its children,
so nested calls cannot interleave a parent's children. Root is a Program node.
Node kinds form an enum. Each node has kind, text, first_child, child_count,
start_token, end_token, line, col. Token spans are half-open indices into the
lexer's token stream; line/col is a 1-based syntax anchor. They are NOT byte
offsets. Integer text is lexer token.value followed by its optional suffix;
string text is the decoded lexer token.value, not raw source spelling. Do not
range-check numbers or resolve names/types during parsing.

Public API: `parse_ast(source: String) -> Result<AstTree, AstError>`, where
AstTree owns `nodes: Vector<AstNode>`, `children: Vector<Int>`, `root: Int`;
AstError has `message: String`, `line: Int`, `col: Int`. Match results using
the existing lexer driver's ownership pattern. Use distinct Ast-prefixed
names to avoid prelude and lexer collisions. Implementation helpers may differ
but this API and node field names are shared with the test harness.

## Initial syntax

Program: zero or more functions. Functions have a name, typed named parameters
(no external labels/defaults), optional named return type (absent means Void
syntactically), and a brace body. Named types are retained as spelling, including
unknown names; generic/reference/optional type syntax is outside this unit.

Body: let/var identifier bindings with optional named type and required value;
return with optional expression; expression statements and a final expression.
Do not perform return-path/type/name checking. Retain final-expression versus
statement distinction; semicolons are refused (LANGUAGE_SPEC.md says there are
no statement semicolons). Follow documented Saw newline
and body-boundary rules for this subset, checking the Python parser on ambiguous
cases rather than inventing a rule. No naked brace-block-as-expression shortcut.

Expressions: integer, plain string, boolean literals, identifiers, parentheses,
positional calls on arbitrary expression heads, unary minus/not, multiplicative
(* / %), additive (+ -), one comparison/equality tier (< <= > >= == !=), && and ||.
Use Saw's actual precedence/associativity, and support newlines inside parentheses
and after a binary operator. Preserve nesting structurally. Reject interpolation,
float syntax, labelled calls, member/index access, assignments, control expressions,
declarations beyond functions, and every other unimplemented form explicitly at
the first unsupported token. Whole-input consumption is required.

Node kinds: Program, Function, Parameter, NamedType, Block, Let, Var, Return,
ExpressionStatement, FinalExpression, Identifier, IntegerLiteral, StringLiteral,
BooleanLiteral, Unary, Binary, Call. A Function's children are parameters in
order, return NamedType, then Block; Parameter children contain its NamedType.
Let/Var children are optional NamedType then initializer. Unary/Binary text is
the operator; Call children are callee then positional arguments. Parentheses
do not add a node; their outer token span may be recorded by the enclosing
constructed node, but existing arena nodes must not be rewritten. State the
chosen parenthesis-span convention in README and test it. Other text fields
are empty except names/literal payloads. Program/Block children retain order.

Concrete boundary conventions: parameter/call lists allow trailing commas and
ignore enclosed newlines. `return` followed by newline/closing brace/EOF has no
operand. A newline after `=` is not a continuation; a newline after a binary
operator is. A newline before an operator does not continue the previous
expression (a leading minus can instead start a new unary expression). Function
bodies may start on a new line after the signature. Logical negation is `not`;
postfix `!` is unsupported here. Grouping parentheses add no node and leave an
existing inner node's span unchanged; newly constructed outer expressions use
their consumed interval. Program's span is [0, EOF-index), including trivia
tokens emitted by the lexer. No node span includes EOF. A synthetic omitted
return type is a Void NamedType with zero-length span at the body opener.
Anchors: function/binding/return keyword, block opener, parameter/type/name/literal
token, unary/binary operator, call callee. Unsupported postfix/label syntax
reports at its introducer (`.`, `[`, `!`, `:`), not a later token.

Documentation comments (`///`, `//!`) are lexer metadata with no AST field in
this unit: refuse them at the first DocComment location before syntax parsing,
rather than silently discard their contents. Ordinary comments remain accepted.

One parser error state/funnel preserves the first error, stops work promptly,
and returns Err instead of a partial tree. Lex errors retain their location.
One nesting budget, named constant (256, the user-ratified design 259 value),
covers nested expression, unary, call-argument and parenthesis paths. The VM's
128-call resource limit must not set parser acceptance: use explicit expression
work/operator stacks for deep input rather than raising VM limits or lowering
the syntax limit. Long iterative binary/postfix chains
must remain bounded by source size, not recursive traversal. Test the boundary
and overflow. A parser subset refusal is not evidence Python should refuse.

## Tests and dump

Provide a deterministic flat arena dump in the test driver: explicit node/child
fields, string fields encoded as length plus byte values, so multiline strings
cannot corrupt records. This is a prototype diagnostic representation, NOT the
canonical AST_DUMP format. A later renderer can traverse these indices into that
format without changing the parser. Design 259's full-parser contract remains
no tolerated AST mismatches; M17 semantic known differences do not carry over.

The Python harness decodes driver output and independently checks valid roots,
child ranges, backward edges, node reachability, source spans, and expected
normalized tree structures. Golden expectations must be authored from grammar,
not copied from the implementation's output. Cover arena growth, nesting/order,
precedence/associativity, source anchors, empty functions/program, parameters,
bindings/returns/tails, unresolved names and type mismatches, strings/Unicode,
comments/newlines, malformed delimiters, unsupported tokens, trailing garbage,
and depth limit. Execute identical assembled source through VM, emitted LLVM
O0/O2 and Python sawc; compare the complete parsed dump. ASan checks native
arena traversal/cleanup. Keep compiler suites serialized under the machine lock.

## Ownership and sequencing

Parent owns design, docs, review, tracker and integration. Sol source agent owns
parser lib; Sol harness agent owns runner/drivers/fixtures. No production compiler
edits, full examples classification, semantic lowering, or battery integration in
this unit. File discovered production compiler bugs; do not mirror them. Once
focused AST generation is green, submit this isolated milestone for review and
then expand syntax and introduce the canonical Python AST differential.
