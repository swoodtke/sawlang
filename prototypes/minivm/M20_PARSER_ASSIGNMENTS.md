# M20: inventory resolution and name assignments

SL-303, under SL-300, follows merged SL-302 (M19). On September 17 the user
approved resolving the seven inventory ambiguities and implementing a bounded
parser grammar expansion. Python oracle fixes are documentation-only for now.

## Inventory findings and scope

M19 inventoried 2,696 tracked examples: 58 candidates, 2,536 unsupported,
95 Python parse errors, and seven unresolved. Five unresolved files contain a
`StaticAssert` in statement position, and two contain a `ForLoop` in value
position. Both are real production AST shapes omitted from the classifier's
known-unsupported sets. Recognize the shapes wherever they occur; do not exclude
paths by filename or infer eligibility from the prototype's refusal.

The five StaticAssert files are `const_generic_default_and_arith.saw`,
`interior_cell_user_type.saw`, `static_assert_backed_enum.saw`,
`static_assert_pass.saw`, and `static_assert_statement_fail_error.saw` under
`examples/`. The ForLoop files are `for_loop_expr.saw` and
`range_inclusive_basics.saw`. These classifications say only that this prototype
does not yet implement their syntax, not that their programs are invalid.

Independent source/token and Python-AST auditing projects 61 eligible examples
with name assignment alone and 64 with arithmetic compound assignment. Choose
that slice first. A preliminary ordinary-if/else expansion estimate is 78;
that is a planning estimate, not tested parser coverage. Nested control syntax
needs explicit expression/block continuations to preserve the depth-256
contract on a VM with fewer call frames, and belongs to the next slice.

## Syntax and arena contract

Implement assignment statements to an Identifier target, including a grouped
name: `x = value`, `(x) += value`, and the other arithmetic compound operators
`-=`, `*=`, `/=`, `%=`. Assignment is a statement, never an expression or block
tail. A final assignment remains a statement even immediately before `}`.
Arguments, grouped expressions, returns, binding initializers, and assignment
values cannot contain assignment. No chained assignment. The RHS uses the
existing expression grammar and nesting budget, including its newline rules.
A newline immediately after the assignment operator is not continuation; a
newline after a binary operator or within call/group parentheses is.

`Assign` has empty text; `CompoundAssign` text is the underlying arithmetic
operator. Both have exactly two ordered children: target, then value. Their
spans include the entire target spelling (including grouping) through the RHS;
the source anchor is the target Identifier, whose own span remains unchanged.
Preserve backward edges, child ownership, reachability, and source containment.
Only the statement-head expression entry may stop before an assignment token;
all nested expression entries keep their assignment refusal. Report malformed
syntax through the existing first-error funnel, without returning partial trees.

Syntax parsing does not resolve names, check mutability, or check operand types.
Assignments to immutable bindings, parameters, and unknown names still parse.
Member/index assignment, bitwise compounds, control expressions, and other
unsupported grammar remain clean refusals. These are subset boundaries, not
new restrictions on the production language.

The canonical renderer emits Python's exact `AssignStatement` or
`CompoundAssignStatement <op>` header, with `target:` then `value:` sections,
using the existing iterative traversal and shared line writer. No new canonical
schema, newline normalization, or integer/string payload transformation.

## Validation and ownership

Sol source agent owns parser and renderer; Sol harness agent owns independently
authored arena/canonical fixtures and error cases; Sol inventory agent owns
classification and snapshot tests. Isolated worktrees. Parent authors this
brief, reviews integrations and Saw idiom, and runs final gates serially under
the machine-wide compiler-suite lock. No production compiler edits.

Cover every admitted assignment operator, grouped target spans/anchors, order
among bindings/assignments/tails, trailing assignments, semantic negatives,
multiline and binary RHS, string bytes, malformed targets/operators, assignment
in every forbidden expression position, depth 256/257, and long shallow RHS.
Run focused arena and canonical tests across VM, LLVM O0/O2, ASan, and production
sawc, plus Python parse-only checks for the admitted fixtures. Run the complete
fresh eligible-examples differential, record corpus and comparison counts, and
regenerate/check the inventory. Snapshot freshness and unknown classification
remain visible gates; do not count excluded files as parity.

## Deferred Python oracle work (user direction, September 17)

SL-73 remains open. Python's postfix-call parsing loses the call relationship
for grouped names, call-result heads, and immediately invoked closures. Keep
its diagnostic differential failing until the mechanism is repaired; never
copy the accident or add a tolerated-divergence ledger. A general callee is
representable in the arena, but the current canonical FunctionCall schema only
represents Identifier callees. Repairing the production parser and deciding the
canonical representation of other callees require their own reviewed work.

Design 259's pre-freeze obligations remain: fix or explicitly rule intended
behavior for parser/lexer/AST-shape findings before freezing that surface;
preserve the no-known-divergence contract; bring production depth/refusal
locations into agreement before claiming whole-grammar parity. Its historic
finding list must be checked against the live tracker before scheduling fixes.
M20 does not implement those production changes or establish a global freeze.
File-reading CLI, VM parser integration, and full design-259 bootstrap remain
later milestones. The next grammar slice should measure complete-file gains
and address control-flow continuations before adding ordinary if/else.

The inventory review also reproduced Python's permissive statement-boundary
behavior: `func f() { x = 1 y }` and `func f() { x += 1 y }` become separate
statements/expressions, while this prototype requires a boundary. The same
behavior predates assignments (`let x = 1 y`, `g() h()`), and SL-73's existing
comment records the adjacent-expression face. None of the six newly eligible
tracked examples uses it. The candidate classifier is not a complete grammar
proof; if such a file enters the corpus, the strict comparison must fail.
Keep boundary reconciliation in the deferred pre-freeze review, with no
allowance that converts a mismatch into agreement. Design 274, proposed in
SL-2.p1, tracks this as B1 pending a user ruling and a dedicated issue; this
reference does not mark the proposed grammar decision approved.

To reproduce the assignment-slice measurement without running the prototype:

```sh
python - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, "prototypes/parser")
import inventory
saved = set(inventory.ADMITTED_TOKENS)
compounds = {"PLUS_ASSIGN", "MINUS_ASSIGN", "STAR_ASSIGN", "SLASH_ASSIGN", "PERCENT_ASSIGN"}
for label, admitted in (("assignment only", saved - compounds), ("arithmetic compounds", saved)):
    inventory.ADMITTED_TOKENS.clear()
    inventory.ADMITTED_TOKENS.update(admitted)
    print(label, inventory.build_inventory(Path.cwd())["counts"])
PY
```

This temporary process restricts the classifier for measurement only. It does
not change the checked-in snapshot or the comparison runner's eligibility rule.

## Completed validation (September 17)

Integrated Sol source `88c22e66`, harness `00040cf3`, and inventory `99254d95`.
Parent independently ran all gates on their combined changes:

- Arena: 88 cases, identical complete outputs across VM, LLVM O0/O2, ASan,
  and production sawc; authored trees, locations, errors, and arena invariants.
- Canonical: 27 cases across the same five engines plus arena VM invariants;
  17 fixtures independently matched Python's parse-only bytes. The unchanged
  120-million-instruction budget passes the complete expanded gate, including
  the 300-term assignment RHS and both assignment depth-256 cases.
- Python harness: 42 tests; full inventory snapshot freshness passes.
- Examples: 64/64 candidates match, with 35 semantic negatives; full census
  2,696 = 64 candidates + 2,537 unsupported + 95 Python parse errors.

Commands use the compiler venv and the unchanged M19 mini-VM binary:

```sh
python -m unittest discover -s prototypes/parser/tests
python prototypes/parser/inventory.py --check
python prototypes/parser/test_parser.py --binary PATH_TO_MINIVM --artifacts .build/m20-validation/arena
python prototypes/parser/test_canonical.py --binary PATH_TO_MINIVM --artifacts .build/m20-validation/canonical
python prototypes/parser/compare_examples.py --binary PATH_TO_MINIVM --artifacts .build/m20-validation/examples
```

The parent retained outputs, sources, commands, and per-example comparison
artifacts under `.build/m20-validation/` in the integration worktree. Compiler
execution gates ran serially under the repository's machine-wide suite lock.
