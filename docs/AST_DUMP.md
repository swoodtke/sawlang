# Canonical AST dump

The textual form of a parsed Saw program, emitted by `sawc/ast_dump.py`. It is
the acceptance oracle for the Saw parser port, the way the canonical token dump
(`selfhost/lexer/README.md`) is the oracle for the lexer port. The Python
parser's observable output is the correctness reference; `LANGUAGE_SPEC.md` is
authoritative where the two disagree.

Two producers, for two different jobs:

| Command | Stage | Use |
|---|---|---|
| `python tools/dump_ast.py <file.saw>` | lex + parse only | the oracle: one file, one tree, no stdlib |
| `sawc <file.saw> --emit-ast` | after typechecking | debugging: resolved types, desugar nodes, `builtin.saw` merged in |

`make astdiff` (`tools/astdiff.py`) sweeps every tracked `.saw` file through the
first one.

## Format

Indented plain text, two spaces per level, `\n`-separated, no trailing newline
from the dumper itself. A node emits a header line naming its class, then its
children indented beneath it, each under a label line (`condition:`, `body:`,
`value:`) where the position needs naming.

```
Program {
  functions: [
    Function main() -> Void {
      final_expr:
        FunctionCall print()
          arg[0]:
            StringLiteral("Hello, Saw!") : String
    }
  ]
}
```

Field order is fixed by hand-written emit sequences, never by reflection over a
dict or set, so the output is byte-stable across runs. `astdiff` checks this by
dumping each file twice under differing `PYTHONHASHSEED`.

**Positions are not in the dump.** `line`/`column` are carried by every node but
never printed: the token dump already pins positions, and repeating them here
would make every dump churn on unrelated edits.

**`node_id` is not in the dump** unless `--ids` is passed (`tools/dump_ast.py
--ids`, `sawc --emit-ast --ids`), which appends ` #N` to each node header. Ids
are stable within a run and are the compiler's internal node identity, but they
number nodes in construction order — an implementation detail a second parser
has no reason to reproduce. The oracle omits them.

**Type names are SHORT, and the module is a separate field** (design 144). A
type's identity is `(defining module, name)`, carried internally as one
qualified string. The dump never shows that string. A declaration keeps the
name the author wrote and gains a ` module=<tag>` field at the end of its
header line:

```
Struct Header module=dep {
  kind: Int
}
Extension Header: Printable module=dep {
```

A reference to a type — a `StructInit`, an `EnumInit`, an `Extension`'s target,
a rendered `SawType` — shows the short name alone.

The field is absent for the entire corpus `astdiff` sweeps, and that is not an
accident: `tools/dump_ast.py` parses ONE file with no module context, and
`sawc --emit-ast` type-checks a single file, whose module is the root — neither
qualifies anything. So the format grew a field that a module-aware producer can
fill, and the oracle's output did not change by a byte. A port that never emits
`module=` matches today's corpus exactly.

## Error records

A file that does not lex or parse emits exactly one record and nothing else:

```
ERROR<TAB>line:col<TAB>message
```

Positions and the fact of rejection are part of the contract; message prose is
not (the harness compares the tag and position, as lexdiff does). The parser can
report several errors from one file in recovery mode; the record carries the
first.

26 of the corpus's 1149 tracked `.saw` files are rejected here, and every one of
them carries an `// EXPECT: error` directive. They are coverage of error
positions, not a hole in the sweep.

## Completeness

Every AST node type has a dispatcher arm. This is the property that makes the
dump usable as an oracle at all: before design 126 R11 a node type with no arm
was skipped or rendered `<unknown ...>` in the middle of an otherwise plausible
tree, so `ReferenceExpr` (308 occurrences in the corpus) and `WhileExpr` in
statement position (280) were invisible — and an incomplete oracle would have
accepted a port that dropped exactly the same nodes.

Misses are still emitted rather than raised, but the dumper records them in
`ASTDumper.unknown` and `tools/dump_ast.py` appends one record per miss:

```
UNKNOWN<TAB><dispatcher>:<ClassName>
```

`astdiff` fails on any of these. **Adding a node type to `ast_nodes.py` without
adding an arm will fail `make astdiff`** — that is the intended coupling.

Three dispatchers, plus structural walkers for declarations:

| Dispatcher | Covers |
|---|---|
| `_dump_expression` | every `Expression` |
| `_dump_statement` | every `Statement`, plus `GuardLetStatement` and `StaticAssert` |
| `_dump_pattern` | every `Pattern` |
| `_expr_summary` | inline one-line rendering (static initializers) |

`WhileExpr` and `ForLoop` are each reachable through both the statement and the
expression dispatcher, because the parser produces them in both positions.

## Node inventory

93 dataclasses in `sawc/ast_nodes.py`, all covered.

**`Expression` (44)** — `ArrayIndex`, `ArrayLiteral`, `BinaryOp`, `BindOptional`,
`BoolLiteral`, `CastExpr`, `ClosureExpr`, `EnumInit`, `ErasedErrWrap`,
`FloatLiteral`, `ForceUnwrap`, `FunctionCall`, `Identifier`, `IfExpr`,
`IfLetExpr`, `IntLiteral`, `MapLiteral`, `MatchExpr`, `MemberAccess`,
`MethodCall`, `MoveExpr`, `NilCoalesce`, `NoneLiteral`, `OptionalChain`,
`OptionalChainAssign`, `OptionalEvalExpr`, `OptionalWrap`, `RangeExpr`,
`ReferenceExpr`, `ResultErrWrap`, `ResultOkWrap`, `SelfExpr`, `SetLiteral`,
`SourceLocationLiteral`, `StringInterpolation`, `StringLiteral`, `StructInit`,
`TryCatchExpr`, `TryExpr`, `TupleIndex`, `TupleLiteral`, `UnaryOp`,
`UnsafeExpr`, `WhileExpr`.

`OptionalWrap`, `ResultOkWrap`, `ResultErrWrap`, `ErasedErrWrap`, `EnumInit` and
`OptionalChain` are never built by the parser — the typechecker inserts them, so
they appear only in a `--emit-ast` dump, not in the oracle's.

**`Statement` (9)** — `AssignStatement`, `BreakStatement`,
`CompoundAssignStatement`, `ContinueStatement`, `DestructuringLet`,
`ExpressionStatement`, `ForLoop`, `LetStatement`, `ReturnStatement`.

**`Pattern` (6)** — `BindingPattern`, `EnumPattern`, `LiteralPattern`,
`RangePattern`, `TuplePattern`, `WildcardPattern`.

A `MatchArm` carries either the legacy `variant_name`/`bindings` pair or a
`pattern`, and optionally a `guard`; all three are dumped.

**Declarations and structure (22)** — `AssociatedType`, `Attribute`, `Block`,
`Enum`, `Extension`, `ExternBlock`, `ExternFunction`, `Function`,
`GuardLetStatement`, `MatchArm`, `Method`, `Program`, `StaticDecl`, `Struct`,
`Trait`, `TraitMethod`, `TypeAssignment`, `TypeDefinition`, plus the `ASTNode` /
`Expression` / `Statement` / `Pattern` bases.

**Not yet `ASTNode` subclasses (12)** — `Argument`, `CaptureSpec`,
`ClosureParam`, `EnumVariant`, `ExportDecl`, `ImportDecl`, `ModuleDecl`,
`Parameter`, `SawType`, `StaticAssert`, `StructField`, `TypeParameter`. These
are reached by the structural walkers rather than by a dispatcher. Folding the
four top-level declaration types (`ImportDecl`, `ExportDecl`, `ModuleDecl`,
`StaticAssert`) into the node hierarchy is a later brief.

Types render through `SawType.__repr__`, not through a dumper arm.
