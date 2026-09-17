# Prototype syntax parser

This is the AST-generation step after the mini-VM lexer milestone: a parser
written in Saw, using the unchanged selfhost lexer, with syntax stored in an
index arena. The design is [M18_AST.md](../minivm/M18_AST.md); work is tracked
by SL-301 under the SL-300 parser epic. M20 (SL-303) adds name assignment;
its design is [M20_PARSER_ASSIGNMENTS.md](../minivm/M20_PARSER_ASSIGNMENTS.md).

The parser preserves syntax without resolving names, checking types, or emitting
instructions. A program with an unknown variable or incompatible return type
can therefore parse successfully. Unsupported syntax produces a located error.

The first milestone covers functions, typed named parameters, named return
types, local bindings, returns, expression statements and final expressions.
M20 also accepts assignment statements to names (`=`, `+=`, `-=`, `*=`, `/=`,
`%=`), including grouped names. Assignments remain statements when last in a
block. They are not legal inside another expression. Undefined names, immutable
bindings, and incompatible operands remain later semantic questions. Bitwise
compound assignment and member/index writes are not yet supported.
Expressions include names, integer/plain-string/boolean literals, parentheses,
positional calls, unary minus/not, arithmetic, comparison/equality and logical
operators. Generics, control flow, closures, member/index access, labelled calls,
interpolation, floating-point syntax and other declaration kinds are later work.
Documentation comments are explicitly refused until the AST carries their
metadata; ordinary comments are accepted.
Statement semicolons are not Saw syntax. Comparison and equality operators
share one left-associative precedence level.

The tree owns flat node and child-index vectors. Nodes refer only to earlier
nodes, and each ordered child list occupies a contiguous range. This permits
recursive syntax without recursive owning types. Node IDs are local to their
tree and are not stable across parses. Source spans use half-open token-index
ranges, with separate one-based line/column anchors; they are not byte offsets.
The tree does not retain the source or token buffer. A consumer that needs to
map a complete token span back to text must retain the matching source and
token stream (or lex the source again). Source ownership and a file-reading
parser application are later steps.

The test dump exposes arena structure and locations so tests can check tree
shape, ordering, reachability, spans and storage invariants. It is not the
canonical Python AST dump. M19 (SL-302) adds a separate canonical renderer and
examples inventory; its design is [M19_PARSER_DIFFERENTIAL.md](../minivm/M19_PARSER_DIFFERENTIAL.md).
Known semantic differences in the mini-VM's M17 ledger do not authorize AST
mismatches.

`canonical_ast(tree: &AstTree) -> Result<String, AstError>` renders a
parser-produced arena using the parse-only Python dump format. It borrows the
tree and returns an owned string with no trailing newline. The explicit
traversal stack preserves M18's depth limit under the VM. It does not validate
arbitrary caller-fabricated arenas.

The canonical format omits locations and arena IDs, collapses parameter/type
nodes into function headers, and renders integer values in decimal without
suffixes. The arena dump remains necessary to verify those syntax details.
String payloads retain control bytes; only double quotes are escaped, matching
the existing Python writer. Framed test output uses lengths and byte values so
embedded newlines and NUL bytes remain unambiguous.

The current canonical schema only represents calls with an identifier callee.
A parsed call on another expression returns a located renderer error; the
parser still preserves that call correctly. Grouped identifier calls can render,
but the Python parser currently misparses them (SL-73). These are explicit
diagnostic comparison cases, never tolerated agreement. Full canonical parser
parity depends on resolving grammar debt as well as expanding the subset.

The index representation follows the September 10 prototype ruling and
supersedes design 259 U2's earlier Box-linked storage choice. Design 259's
canonical output contract and depth limit of 256 still apply to the parser
track. Explicit expression stacks keep the syntax limit independent of the
mini-VM's smaller call-stack resource limit.

The current library is assembled with the unchanged lexer by the test harness;
it does not yet have a file-reading command-line application. From the repository
root, with a built mini-VM and the Python compiler's dependencies installed:

```sh
python prototypes/parser/test_parser.py --binary .build/minivm/minivm
```

This builds one Saw driver containing the lexer, parser and test inputs, then
compares its complete AST/error records across VM execution, emitted LLVM at
O0/O2, an AddressSanitizer build, and Python-sawc compilation. `--case-prefix`
selects a focused set; the default runs the complete milestone gate. Python
checks independently authored expected trees and arena invariants. It is not
yet comparing these trees against Python's parser output.

The M20 arena gate covers 88 cases across all five engines, including depth
256/257 for groups, unary operators, calls, mixed nesting, and assignment
targets/values. Harness tests exercise record decoding, invalid arena handling,
assignment child order/operators, and failure artifacts.
Use `--artifacts PATH` to keep successful-run dumps and generated source/IR;
failed runs retain their artifacts automatically.

Grouping parentheses leave an existing inner node's span unchanged. When a
new enclosing expression is constructed, its span includes the consumed
grouping tokens. An omitted return type is represented by a synthetic Void
NamedType with an empty span at the body opener. Integer text is the lexer's
normalized number followed by its suffix; String text is decoded content.

## Canonical comparison and examples inventory

With the compiler's Python environment active, run the focused renderer gate:

```sh
python prototypes/parser/test_canonical.py --binary .build/minivm/minivm
python -m unittest discover -s prototypes/parser/tests -p 'test_*.py'
```

The M20 renderer gate passes 27 cases across VM, LLVM O0/O2, ASan and production
sawc, with identical complete output. Seventeen cases also match Python's
parse-only oracle. Depth, long-chain, and grouped/general-callee cases use
independently authored expectations where Python agreement is not established.
A separate arena VM run checks structural invariants. The combined Python
harness suite contains 42 passing tests.

The [inventory report](examples_inventory.md) and [snapshot](examples_inventory.json)
cover all tracked examples, including nested directories. The snapshot records
source hashes, syntax evidence and test expectations. A semantic EXPECT-error
directive does not exclude a file from parser comparison.

The checked-in JSON uses lossless schema v2 with named columns and shared string
tables to fit sawtracker's request limit. Its `schema` field names every column
and code table; `inventory.decode_snapshot()` reconstructs the full per-file
records. Detailed comparison artifacts retain ordinary object-shaped JSON.

```sh
python prototypes/parser/inventory.py --check
python prototypes/parser/compare_examples.py --binary .build/minivm/minivm
```

The snapshot check fails on added/deleted files, changed source or changed
classifications. Run `inventory.py` without `--check` to regenerate and review
both snapshot files. The comparison command independently rebuilds and saves
the current inventory, then tests every candidate in bounded embedded-source
batches. It can measure a changed corpus before the snapshot is updated; its
source hashes additionally detect edits during the run. Snapshot freshness is
a separate submission gate, not a frozen filename allowlist.

M19's first sweep passed all 58 candidates (36 top-level, 22 nested), including
29 semantic-negative programs. M20's inventory has 64 candidates (37 top-level,
27 nested), including 35 semantic negatives, out of the same 2,696 examples.
It identifies 2,537 unsupported files and 95 Python parse errors, with no
unresolved classifications. All 64 candidates pass the canonical VM/Python
comparison. The seven M19 ambiguities were known unsupported
`StaticAssert` statements and `ForLoop` expressions missing from the audit's
node sets; they are now classified by syntax evidence. The unsupported and error groups
have not established parser parity and are not counted as agreement. Candidates
are selected independently of the prototype result; a refusal or mismatch
fails the comparison rather than changing the classification.

Use `--artifacts PATH` with a new or empty directory to preserve the inventory,
per-file sources and canonical outputs, batch sources, commands and failure
diagnostics. The comparison parses example source text; it does not typecheck
or execute the example programs. The focused renderer gate checks the same
Saw implementation across execution engines.

`test_canonical.py --binary .build/minivm/minivm --debt-probe` runs the strict
SL-73 grouped-callee comparison separately. It currently fails on Python's
wrong tree, and will succeed when both parsers agree. It is not part of the
passing fixture set and has no tolerated mismatch entry.
