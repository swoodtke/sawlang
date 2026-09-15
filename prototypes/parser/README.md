# Prototype syntax parser

This is the AST-generation step after the mini-VM lexer milestone: a parser
written in Saw, using the unchanged selfhost lexer, with syntax stored in an
index arena. The design is [M18_AST.md](../minivm/M18_AST.md); work is tracked
by SL-301 under the SL-300 parser epic.

The parser preserves syntax without resolving names, checking types, or emitting
instructions. A program with an unknown variable or incompatible return type
can therefore parse successfully. Unsupported syntax produces a located error.

The first milestone covers functions, typed named parameters, named return
types, local bindings, returns, expression statements and final expressions.
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
canonical Python AST dump. After this foundation is working, a canonical
renderer and classified top-level examples corpus will drive the parser
differential. Known semantic differences in the mini-VM's M17 ledger do not
authorize AST mismatches.

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

The M18 gate covers 52 cases across all five engines, including depth 256/257
for groups, unary operators, calls and mixed nesting. Eight Python harness
tests exercise record decoding, invalid arena handling and failure artifacts.
Use `--artifacts PATH` to keep successful-run dumps and generated source/IR;
failed runs retain their artifacts automatically.

Grouping parentheses leave an existing inner node's span unchanged. When a
new enclosing expression is constructed, its span includes the consumed
grouping tokens. An omitted return type is represented by a synthetic Void
NamedType with an empty span at the body opener. Integer text is the lexer's
normalized number followed by its suffix; String text is decoded content.
