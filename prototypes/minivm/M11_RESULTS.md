# M11: Result construction, matching and propagation

Planned after the M10 Optional gate. This design uses M10's SumIR metadata and
disjoint tagged payload layout. It does not authorize changing production code.

## Source boundary

Admit Result<T,E> type applications, explicit qualified constructors
`Result<T,E>.Ok(value: expr)` / `.Err(error: expr)`, unambiguous implicit payload
wrapping, and bare success return for Result<Void,E>. Require a non-Void data
error type and reject stored references. No Error trait machinery is required
by the actual lexer. No catch, routing clauses, try?, generic declarations,
custom payload enums or error formatting are part of this slice.

Implicit wrapping must select exactly one compatible variant. A literal fitting
both numeric payload types is ambiguous even when those types differ. Existing
exact Result values copy unchanged. Preserve contextual numeric/Optional typing
inside selected payloads and each control-flow arm. None can target an Optional
payload only when exactly one Result variant accepts it. Never pick a side by
declaration order. Explicit constructors resolve ambiguity and require the
correct label and arity. Explicit Void Ok construction is omitted: production
rejects both `.Ok()` and `.Ok(value: ())`. Use a bare success return instead.
Pin existing Optional payload wrapping separately: Int? into Result<Int??,E>
owes one layer, while None into Result<Int??,E> denotes an absent Ok payload.

## Result observation

Support statement and value matches with `case Ok(name)` and `case Err(name)`,
including `_` payload patterns; Void Ok uses `case Ok`. A final whole-value `_`
may cover the remaining variant. Reject duplicate/missing arms and wrong arity.
Bindings are local payload snapshots; evaluate the scrutinee exactly once.
Retain complete String/record/Optional payloads before source mutation or scope
cleanup. This small match surface also lets the eventual lexer test wrapper
observe LexError line/column without requiring catch support.

## try and try!

Parse prefix try and try! at production precedence (their operand is a complete
expression), with normal delimiters ending it. Nested `try! f(try g())` must
propagate the inner error before the outer call runs. Operand must be Result.

On Ok, return a complete payload snapshot (or a Void expression for Void Ok).
On Err, try is legal only in a Result-returning function with the same error
type. Construct its complete Err value, preserve all owning result leaves,
clean the function frame via the shared return helper, and return immediately.
Do not evaluate later arguments, RHS operations or following statements on
the error edge. Different success types between callee and caller are valid.

try! on Err emits a terminal `Panic` instruction with a fixed message
`runtime error: try! failed` and exit status 1 in VM/native. Payload formatting
is explicitly deferred. Verifier validates the instruction's fixed contract;
VM reports its ordinary runtime failure and native calls the existing fatal
runtime path. It must never read or expose an inactive payload. Panic requires
default unused instruction fields (dst/a/b/target -1, immediate 0, no args),
has no CFG successor, and emits native `unreachable` after the fatal call.
The fixed message is a compatibility limitation: production can format an
error cause, while this prototype slice deliberately cannot.

## Ownership and validation

Initialize every inactive payload leaf on every construction, including loop
reuse. Return/Call/Copy/reference operations continue to use the complete
flattened layout. Dropping inactive null String claims is safe. Keep the
successful-execution zero-live-allocation check; error execution may unwind
the VM-owned execution heap or terminate the native process as before.

Tests: distinct and same-type variants; literal ambiguity; nested Result and
Optional payloads; mixed String-owning record payloads; Result<Void,E>; exact
payload observation through match; mutation after snapshot; early propagation
through several frames and argument evaluation; try! Ok/Err; loops and branch
cleanup; explicit and implicit return contexts; malformed type/constructor/
match/try rejects. Add direct representation/IR checks and ASan ownership probes.
Full regression gate remains required before a milestone commit.

## Following slice

String.to_uint is a separate small intrinsic returning UInt?, allowing the
unchanged literal_fits helper to run. Accept default radix 10 and explicit
radix 2..36. Parse the whole byte string, optional leading +, no whitespace,
prefix or underscore handling; negatives, lone sign, invalid digit, embedded
NUL, invalid radix and overflow yield None. Guard multiplication/addition by
the UInt64 ceiling without signed overflow or undefined LLVM arithmetic.
Test UInt64.max and its neighbors across bases, then actual literal_fits.
