# M4: payload-free enums and exhaustive statement match

Status: design, after M3. This isolates the TokenKind representation and dispatch
required by the lexer. Value-producing match, implicit tails, strings, and payload
enums remain later slices. No new instruction opcode is required.

## Source contract

Accept private/public enums with one or more named, payload-free cases using Saw
syntax `enum Color { case Red, case Green }`. Qualified case values `Color.Red`
are nominally typed. They can be copied, assigned, passed, returned, stored in
records, and compared for equality/inequality only with the same declared enum.
Reject duplicate enum/case names, module namespace collisions, numeric casts,
arithmetic, implicit integer conversion, and direct printing. There are no raw
values, payloads, enum methods, or user-defined discriminants in this slice.

Accept statement `match subject { case Red -> { ... }, case Green -> { ... } }`
where subject has enum type. Patterns may be unqualified cases or `Color.Red`;
qualified patterns must name the subject's declared enum. A final `_` wildcard is
allowed. Require exhaustive coverage without duplicates; reject arms following a
wildcard. Each arm is a statement block for M4; it can contain explicit returns.
A function whose exhaustive match arms all return satisfies return checking.
Evaluate subject exactly once. Execute exactly one arm. Typecheck every arm.

Record and function type references may refer forward to enums. Case expressions
may refer to enums declared later in the file. Local values do not introduce
unqualified enum cases into ordinary expression lookup.

## Shared representation

Add `ValueType.Enum(index: Int)`, `EnumIR { name: String, cases: Vector<String>,
line: Int, col: Int }`, and `Program.enums`. A value occupies one scalar slot;
its canonical immediate/cell is the case's zero-based ordinal. Enum identity stays
in slot types, function signatures and record fields. No integer helper should
classify enums as integers. `scalar_type` includes enums so layout/copy/call ABI
remain unchanged, while printing still accepts only numeric and Bool values.

The record layout routine does not dereference enum metadata: enums flatten to
one word. Full Program verification must separately validate enum type indices
in every record field, signature and slot; validate enum declarations as nonempty
with unique names/cases; and enforce ordinal bounds for enum Const instructions.
Keep nominal equality checks. Malformed enum indices and constants must return a
ProtoError before any indexing. Record type validation and layout cycle/width
checks remain intact. Direct contract tests must cover these trust boundaries.

Both engines use existing i64 cells and Eq/Ne. LLVM returns enums as scalar i64,
including enum fields flattened inside record results. Do not emit enum values
as record aggregates. VM/native dispatch uses existing Const/Eq/Branch/Jump.

## Frontend lowering

Extend declaration-name collection to enumerate both struct and enum names before
resolving types; retain M3 newline-terminated statics handling. Record/enum/function/
static names share the module namespace. Resolve qualified enum cases before
ordinary field access without changing numeric static-member parsing.

For match, snapshot the subject once, then emit a test chain with canonical enum
constants and Eq. Each true branch enters its arm; false continues to the next
test. Every non-returning arm jumps to a common continuation. A final wildcard is
an unconditional arm. The frontend proves coverage; the verifier still checks all
branch targets and ordinary reachable-falloff rules. Existing final padding must
provide real targets for end-of-function joins, including all-returning matches.

## Independent tests

Keep prior gates. Add small cases for qualified values, nominal equality,
assignment, enum parameters/results, enum fields in records, forward declarations,
qualified and unqualified exhaustive matches, wildcard selection, subject evaluation
once with a marker function, and all-arms explicit-return control flow. Include
located failures for duplicate declaration/case, missing case, duplicate arm,
wrong enum qualifier, mixed-enum equality/transfer, integer conversion and print.
Run VM and clang O0/O2 with independent expected outputs; compare one representative
source fixture with the production compiler. Primary owns schema/verifier and
review, Sol owns bounded frontend and fixture tasks. Commit only passing integration.
