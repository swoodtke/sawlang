# M5: tails and value-producing control flow

Status: implemented after M4 (1259292b). All 193 integration cases pass through
the VM and clang O0/O2, including 32 isolated value-control cases. All three
direct numeric/record/enum representation contracts pass.

## Scope and source contract

Add implicit function tail returns, value-producing `if` with mandatory `else`,
`else if` chains, and exhaustive enum `match` with either expression arms or
block arms containing a final expression. Support numeric, Bool, enum, and
flattened record results. Retain existing statement control flow and explicit
returns. No new runtime representation, opcode, or engine behavior is needed.
Strings, payload patterns, references, loop values, and general Never are deferred.

A value block may contain declarations, mutation, loops, and explicit returns
before its final expression. Only the last expression supplies its value. A
return exits the enclosing function, never merely the arm. A branch that always
returns needs no arm value; every continuing branch must supply a compatible
value. All-returning control flow is permitted in function tails and statements;
if handling it in a nested operand requires general bottom typing, reject that
position cleanly for this slice rather than manufacture a reachable value.

Use the existing transfer rules: nominal record/enum identity, exact Bool,
lossless numeric widening, and bare literal adoption. Carry expected types into
branch tails from local annotations, assignment destinations, function parameters,
record fields, and explicit/implicit returns. Without an expected type, infer a
common type from continuing arms, preserving contextual adoption of bare literals
against a typed sibling; incompatible nominal types are errors. For typed integer
arms, choose an existing arm type to which all arms widen losslessly (production
design-195/205 rule), not a new larger type absent from the arms. Do not introduce
general constant folding. Range-check even unselected branches. Document any
deliberate narrower inference rule with located rejection tests.

The no-context bare-literal sibling adoption above is an explicit prototype
choice: the production compiler currently defaults the literal to Int in the
probed `if flag { 5 } else { 6u8 }` initializer. Production comparisons therefore
validate the shared subset, while independent oracles define this choice. Likewise,
production acceptance is not sufficient evidence that missing-tail source is valid:
the prototype must reject it according to the continuing-path rule above.
The independently confirmed production missing-tail finding is tracked as SL-235.

Discarded statement control flow must not become an implicit function return.
Keep the prototype's restriction on ordinary non-Void expression statements;
only a final expression in a value context can supply a value. Tail position is
relative to the containing block and its consumer, not merely a closing brace.
Continue to reject missing returns and reachable value branches missing a tail.

## Frontend design

Replace the conflation of statement termination and block value with an explicit
frontend-only result carrying continuing/value/always-return information. Reuse
one control-flow lowering path for statement and value forms wherever practical.
The block parser must distinguish statements from a final expression, track scope
and statement separators, and propagate the enclosing function return type.
An expected type is contextual, not global state that leaks into conditions,
call arguments, binary operands, or nested unrelated expressions.

Lower each value branch to existing Branch/Jump and fresh result slots. Copy a
continuing arm's entire flattened value into the common destination before its
join jump; a returning arm has no copy or continuing edge. If type inference needs
all arm types before result allocation, record arm exit placeholders and append
small conversion/copy blocks after parsing arms, then patch their targets. Never
insert instructions into the middle of the vector without remapping all targets.
No default initialized value may disguise a missing source value.

Evaluate conditions, match subjects, operands, and call arguments in source order.
Evaluate a match subject exactly once. Only the selected arm executes, including
casts and overflow checks. Keep exhaustive coverage and duplicate-pattern checks.
Restore parenthesis whitespace handling at block boundaries so enclosing call
parentheses do not swallow statement newlines inside an arm. Bound recursive
else-if and value-block nesting using the existing parser limits.

## Delegation and acceptance

Primary owns design, independent review, adversarial checks, documentation and
integration. Sol frontend owns src/frontend.saw only. Sol fixtures owns
test_minivm.py and examples/values only. An independent Sol reviewer audits
production syntax/semantics and the implementation without editing shared files.

Fixtures need explicit stdout/status or located diagnostics. Cover scalar/Bool/
enum/record tails, nested if/match, else-if, both sides selected, side-effect order,
unselected runtime traps, subject-once, mixed explicit returns and values, all
arms returning, early return before an unreachable tail, narrow and full UInt64
literal contexts, argument/field/assignment contexts, and scope boundaries.
Reject missing else/tail, mismatched types, out-of-range literals in unselected
arms, incomplete matches and non-tail value expressions. Keep all earlier cases.
Primary runs the full prototype VM + clang O0/O2 gate, direct representation
contracts, and representative production compiler comparisons under the existing
suite coordination policy, then commits only reviewed passing work.

The `lexer_hex_value` fixture includes the lexer's unchanged numeric helper and
its constants. Independent production-compiler comparisons passed for that helper,
the nested record/UInt64 evaluation grid, contextual conditions, and parenthesized
branch composition. Statement-position else-if and unreachable statements remain
statements; they do not silently become value tails.

## Bootstrap observations

During integration, inspecting the String field of an unnamed cloned Token in
the statement classifiers produced SIGBUS/SIGSEGV in bootstrap-generated String
cleanup. Both the simple implicit-tail case and the rejected non-tail-expression
case reproduced the failures. Keeping the cloned Token in a named local resolved
both; those source-level cases are covered by the integration gate. The failure
was then reduced to a standalone Token/Reader program and reproduced on current
main with a passing named-local control. It is filed as SL-236; its exact
production cleanup mechanism has not been fixed in sawc.
The prototype uses explicit token locals for these classifiers; this milestone
does not claim to repair production compiler ownership behavior.
