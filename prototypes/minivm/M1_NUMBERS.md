# M1: lexer numeric foundation

Status: implemented; final validation recorded in README.md. Baseline: 5af086c4.
This supersedes the scalar-only portions of DESIGN.md. Primary owns this contract,
model/verifier, integration and review. Sol owns bounded implementations. No
production compiler/library changes or tracker entries. Commit passing milestones.

## Scope and compatibility

Support Int8/16/32/64, UInt8/16/32/64, platform Int/UInt (64-bit for this
prototype), and the prelude Byte distinct type with UInt8 representation.
Unsuffixed integers now default to Int (= I64), as Saw specifies. Update old
Int32 overflow fixtures to make their width explicit; retain their assertions.
Support decimal/hex/binary/octal literals and all fixed-width suffixes. Literal
range failures are located compile errors. Negative signed minimum literals work.
Unsigned full-width values must survive constants, calls, comparisons and printing.

Bare literals adopt an expected numeric type at declarations, assignments, call
arguments and returns, and beside a typed binary operand. Do not silently narrow
an already typed expression. Lossless integer widening at transfer sites is allowed;
other conversions require `as` or `T.from(truncating: value)`. Full constant-expression
adoption is a later isolated frontend task; reject unsupported combinations cleanly.
Byte construction is `Byte(u8)` (bare literal may adopt UInt8); Byte may project
to its underlying UInt8, and explicit integer casts can widen it. General distinct
types and user-defined methods remain later milestones. Byte arithmetic is outside
this milestone; Byte equality and printing its numeric byte value are supported.
An unwrapped literal assigned directly to Byte is rejected, as in Saw; the
constructor is required. Literal adoption does not bypass the distinct type.

`T.min`/`T.max` are scalar constants. `T.from(truncating: x)` explicitly retains
low target-width bits and interprets signed targets in two's complement. `x as T`
checks both sign and range and never silently truncates. Optional-returning
`T.from(x)` waits for Optional. Bool/integer conversions are rejected.

Checked +,-,* and unary negation trap on overflow. Division/rem trap on zero.
Signed minimum / -1 AND signed minimum % -1 trap, matching LANGUAGE_SPEC.md;
the initial prototype's remainder-zero exception is intentionally removed.
`&+`, `&-`, `&*` wrap at the operand width. Bitwise &,|,^,~,<<,>> operate on
integer operands; shifts check 0 <= count < lhs width, right shift is arithmetic
for signed and logical for unsigned, and left shift truncates to width.
Binary arithmetic/bitwise operands must have the same type after literal adoption.
Shift count may be any integer type; the result has lhs type.
No eager Boolean &&/|| implementation: those require separate short-circuit lowering.

Precedence follows Saw (tightest first): postfix/casts, unary, multiply, add, shifts, comparison,
equality, bitwise &, bitwise ^, bitwise |. Use actual lexer token kinds; it may
represent a shift as consecutive Lt/Gt tokens. The source parser must distinguish
this from comparisons. Existing explicit-return source syntax remains supported.

## Representation and API

ValueType adds I8,I16,I64,U8,U16,U32,U64,Byte to existing I32,Bool,Void.
Int and Int64 share I64; UInt and UInt64 share U64 on this fixed 64-bit target.
Every numeric runtime cell and Instruction.immediate remains a host Int carrying
64 bits. Signed values are sign-extended; unsigned widths below 64 are zero-extended;
U64 uses the same bits, even when the host Int reading is negative. Never use
checked `as Int` to convert U64 storage: use Int.from(truncating: value), and
UInt.from(truncating: cell) for the reverse. Constants and slots use this canonical
representation. LLVM cells/ABI remain i64 with signed/unsigned interpretation by type.

Op adds Cast, Truncate, WrapAdd, WrapSub, WrapMul, BitAnd, BitOr, BitXor,
BitNot, Shl, Shr. Cast/Truncate use dst and a; source/target types come from slots.
Binary operations use dst,a,b; unary operations dst,a. The verifier checks canonical
constants, operation type rules and existing control-flow invariants.

model.saw helpers (public): integer_type(t)->Bool (includes Byte), arithmetic_type(t)
excludes Byte, integer_signed(t)->Bool, integer_width(t)->Int (0 for Bool/Void),
integer_min(t)->Int, integer_max(t)->Int (U64.max has bit pattern -1),
integer_canonical(value:Int,t)->Bool, integer_normalize(value:Int,t)->Int,
integer_fits(value:Int,source:ValueType,target:ValueType)->Bool,
integer_widens(source:ValueType,target:ValueType)->Bool.

## Runtime implementation constraints

VM: no host checked arithmetic may overflow before our diagnostic. For signed
64-bit add/sub/multiply precheck bounds (or use wrapping arithmetic plus sound
overflow detection). For unsigned use UInt bit-pattern reads and precheck UInt.max
for add/multiply/subtract, then check the target width. Use wrapping operations only
for wrap/bit semantics. Guard division's min/-1 and zero before host division.

LLVM: use llvm.sadd/ssub/smul.with.overflow.i64 or unsigned equivalents plus narrow
width checks, or an equally correct explicit precheck. Do not attach unjustified
nsw/nuw. Guard min/-1 and zero before sdiv/srem; never produce poison even on the
error path at -O2. Unsigned comparisons/div/rem use unsigned LLVM operations.
Narrow bit operations normalize the result. Checked casts branch to a trap on
invalid range/sign; truncating casts normalize without a trap. Unsigned print uses
an unsigned 64-bit printf format. Keep current success stdout and exit statuses.

Exact diagnostic lines (exit 1): runtime error: integer overflow;
runtime error: division by zero; runtime error: integer cast out of range;
runtime error: shift out of range. Existing VM budget/depth behavior is unchanged.

## Acceptance

Keep all baseline behavior except the two documented scalar compatibility changes
(default Int and min%-1). Add small isolated tests for: each width/signedness;
literal bounds and min/max; UInt64 above Int.max; checked and truncating casts;
Byte constructor/projection; contextual literal adoption and invalid typed narrowing;
checked overflow at each extreme; wrapping; signed division/rem; bitwise precedence
and shift ranges. Every positive/runtime-error case has an explicit output/status
oracle and runs through VM and clang -O0/-O2. Compile failures require a located
diagnostic. Cross-check representative boundary expressions against the existing
Saw compiler as a separate compatibility oracle. No performance work in M1.
