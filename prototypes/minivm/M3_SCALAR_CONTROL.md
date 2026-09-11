# M3: scalar frontend support used by lexer helpers

Status: implemented after M2; 136-case integration gate passes. This slice needs no new VM or LLVM opcodes. It admits
short-circuit Boolean expressions, compound arithmetic assignment, and immutable
module scalar constants. Tail expressions and value-producing if/match remain
separate subsequent frontend slices; do not silently broaden this contract.

## Source behavior

* `&&` and `||` accept Bool operands and produce Bool. Both are left associative;
  `&&` binds tighter than `||`, and both bind less tightly than existing bitwise
  and comparison operators. Evaluate the left operand exactly once; evaluate the
  right operand only when needed. A skipped runtime trap must stay skipped in
  both VM execution and optimized native code. Even skipped source is typechecked.
* `+=`, `-=`, `*=`, `/=`, `%=` on mutable scalar locals and scalar fields use
  M1 checked arithmetic. The destination place is resolved once, the RHS evaluated
  once, and assignment retains the destination type. A literal may adopt that
  type; a typed expression must match it for arithmetic (no mixed-width operator).
  Immutable roots, records, Byte and Bool reject arithmetic mutation. References
  and indexed places are not admitted by this milestone.
* Module declarations `static NAME: IntegerOrBoolType = literal` are immutable constants.
  Allow signed/unsigned integer literals, unary-negative literals, Bool literals,
  and numeric type `.min`/`.max`; no arbitrary expression evaluator is needed for
  the lexer's B_* declarations. Validate type/range using the same M1 transfer
  rules. No dynamic initialization, global mutable storage or record constants.
  Constants may be referenced from any function irrespective of declaration order.
  Reject duplicate module names and assignment to a constant. Local bindings may
  shadow constants; tests use visible refinement (`let C = C - 1`) as required
  by Saw design 100. The prototype retains the baseline's broader shadowing
  acceptance; enforcing design 100 is deferred to scope/ownership completion.
  Accept `public static` syntactically; modules remain later.

## Lowering and ownership

Keep constant metadata in the frontend, emit a fresh typed Const on each read,
and preserve the existing Program schema. Reject unsupported static initializers
with a located diagnostic rather than executing arbitrary code during compilation.
Do not let constant collection emit instructions into a function's code or retain
slot indices from a temporary context.

Short-circuit lowering uses a fresh Bool result slot and existing Branch/Jump/Copy
instructions. Every reachable path defines the result before the continuation.
RHS instructions occupy only the conditional branch, with all branch targets patched
to real instructions by the existing function finalization logic. Preserve parser
nesting limits and newline behavior. Never lower &&/|| as eager bit operations.

For compound assignment, reuse the place resolver and scalar binary checks.
The current scalar-record subset has no reference side effects, but the design
must leave an explicit point for destination evaluation before the RHS so later
references and indexing will not change evaluation order.

## Isolated acceptance

Run both VM and native O0/O2 against explicit outputs:

1. Every Boolean truth-table row, mixed &&/|| precedence, and nested parentheses.
2. RHS functions print markers to show short-circuit skipping and left-to-right
   execution; false && divide-by-zero and true || divide-by-zero must succeed.
3. Mutable locals and nested fields for all five compound operators; a narrow
   overflow and division by zero must report the existing runtime error.
4. Static Int/UInt64/Bool reads, forward declaration use, local shadowing,
   and numeric limits beyond Int32. Byte statics are outside this slice.
5. Located rejections: non-Bool logical operand even on skipped RHS, immutable
   compound destination, mixed typed arithmetic, duplicate/assigned static, and
   nonconstant initializer.

Primary designs and reviews, Sol implements frontend and independent fixtures.
Retain M1/M2 gates; commit only reviewed passing integration.
