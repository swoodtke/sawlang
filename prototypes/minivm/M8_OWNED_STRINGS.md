# M8: owned String values

Status: implemented after M7 (90cab6a1).

## Source contract

Accept String literals (decoded escapes, UTF-8, embedded NUL), locals,
parameters/results, ordinary copies/reassignment, `&String` and `&var String`.
Add `==`, `!=`, `print(String)`, and intrinsic methods `len()`, `is_empty()`,
`byte_at(index: Int) -> Byte`, `substring(start: Int, end: Int) -> String`,
`equals(other: String) -> Bool`. Positional arguments are also accepted, with
optional exact labels as in M7. Intrinsics may operate on temporary String
values and literals as well as named places. Existing user-record method
temporary restrictions remain. No interpolation, concatenation, numeric casts,
String statics, String fields in records, builders, vectors or payloads yet.

String is immutable byte content with value semantics. Length and indices are
bytes. byte_at requires 0 <= index < len; substring requires
0 <= start <= end <= len and copies its half-open range, including empty ranges
and raw byte slices through UTF-8. Errors are exactly
`runtime error: string index out of range` and
`runtime error: string range out of bounds`. Equality compares bytes, including
embedded NUL. Print writes every byte followed by newline; never C-string printf.

## Representation and ownership

Add ValueType.String, one logical word. It is NOT scalar_type or integer_type.
Add Program.strings: Vector<String> as literal pool; frontend interns literal
content. Root value_layout(String) is [String], but record fields containing
String reject until aggregate ownership is implemented. References may target
String. Helper `string_type(t)` identifies exactly ValueType.String.

Every String slot owns null or one strong reference. Null is an internal empty
slot, not the source empty string. All String slots are initialized null.
Copy, LoadRef, StoreRef and parameter initialization retain source BEFORE
releasing destination, then store. Newly allocated strings transfer ownership
into their destination (release old destination; no additional retain).
Return retains its String result before frame cleanup, then transfers that owned
result to the caller. Call adopts returned ownership without an extra retain.
All other value and reference ABIs stay unchanged. String reference loads/stores
operate on the String SLOT, not on the bytes/header behind its value.

Add Op.Drop(a String slot): release its claim and clear to null; idempotent on
null. At every normal block exit, drop String slots allocated within that block,
including temporary slots, except a value-block result that must survive for its
parent. Every function return additionally releases/clears ALL its String slots,
after retaining the return result. Thus early returns and skipped branches are
covered, and normal lexical cleanup cannot double-release at frame teardown.
Loop body cleanup runs before its back edge. Slots reused in loops also release
their previous value on replacement. No break/continue source support is added.

The VM uses nonzero integer handles into an execution-owned String heap; 0 is
null. Each entry holds bytes and a synthetic refcount. Reuse dead slots only for
well-formed compiled programs (the verifier is not a hostile-bytecode loader);
validate bounds/liveness before lookup and never expose handles in source. Last
release clears the actual Saw String value. Execution-wide heap ownership also
frees all values if a runtime error aborts execution; no objects survive execute.
On successful execution check that no live heap entries remain.

Native LLVM String values use ptr to runtime-owned header+bytes, never integer
pointer casts. String slots are separate ptr allocas, like Ref slots; records
remain String-free so their contiguous i64 data arrays stay valid. Header holds
refcount and byte length; helpers allocate/copy bytes, retain/release, equality,
length/index/substring/printing. Use handwritten LLVM runtime definitions in a
new src/string_runtime.saw emitter module if that keeps llvm.saw focused. libc
malloc/free/memcpy/memcmp/putchar are sufficient. Check allocation and length-add
overflow; panic with `runtime error: string allocation failed`. Refcount overflow
must not wrap. Native fatal errors terminate the process as existing runtime
errors do; success-path main checks the runtime live allocation count is zero.
Use the same stdio family for all prints, so mixed String/scalar output preserves
order. LLVM pointer result/argument emission must include String and Ref, while
ownership changes apply only to String.

## Typed instructions

| Op | Operands/result |
| --- | --- |
| StringConst | dst String, immediate valid Program.strings index; owned allocation |
| StringLen | a String, dst I64 |
| StringByteAt | a String, b I64, dst Byte |
| StringSlice | a String, b I64 start, args exactly one I64 end slot, dst String |
| Drop | a String slot; no result |

Existing Eq/Ne accept String/String and compare contents. Existing Copy and
Print admit String; Const still does not. Call/Return, Addr/LoadRef/StoreRef use
the ownership behavior above. StringLen followed by integer equality to zero
implements is_empty; Eq implements equals. All other operations keep existing
restrictions. Verifier validates every literal index, exact operand types, slice
argument count/slot, no String record fields and Drop only on String slots.

## Frontend and validation details

TokenKind.StringLit contains decoded bytes. It used to carry the lexer's 0x01
escape marker before an escaped brace, which collided with actual U+0001 bytes
followed by braces — the defect this milestone reproduced and filed, fixed since
by design 268 (SL-238): the marker protocol is gone from both lexers and a plain
StringLit's value is now unambiguous decoded content.

The frontend nevertheless keeps its own path: it preserves raw source in Compiler
and decodes the validated original literal at its token line/column, using the
lexer's UTF-8 continuation/column rules to locate it, restoring raw escapes
directly including Unicode scalars and escaped braces. That is now a choice
rather than a workaround, and it is deliberately left as it stands — this
milestone's contract is unchanged and no behaviour was migrated with the API.
InterpString remains a located rejection.

Named String intrinsic receivers use their own content snapshot before argument
evaluation; their methods are read-only. Retain snapshots through nested argument
calls and then release with lexical temporaries. This does not relax explicit
borrow or pending-write rules for user functions. General value postfix dispatch
must distinguish String intrinsics from named-place record methods.

Primary owns model.saw, verify.saw, direct contracts, docs and integration gates.
Sol frontend owns frontend.saw. Sol engines owns vm.saw, llvm.saw and optional
string_runtime.saw. Sol tests owns test_minivm.py and examples/strings. Program
constructor migration in existing direct contracts belongs to primary.

Tests: empty/ASCII/Unicode/NUL/escapes, lengths/bytes/slices/equality, mixed print
order, parameter/return/branch/recursive copies, self-assignment, shared/mutable
String reference forwarding/replacement, temporary intrinsic calls, lexical
cleanup and repeated loop allocations. Check valid boundaries and invalid
negative/end/overflow indices. Reject interpolation, String arithmetic/casts,
fields/statics and invalid intrinsic arguments. All prior cases stay green except
the old blanket String rejection, explicitly replaced by positive String cases.
Direct contracts verify typed op/index/ownership restrictions; native and VM
live-allocation checks run for every successful string program. Compare selected
source semantics with Python sawc and file independently established findings.

## Completed validation

277 integration cases pass through VM and clang O0/O2, including 28 isolated
String cases and all retained prior cases. All six representation contracts
compile and pass. AddressSanitizer probes for loop/value-branch cleanup and
String references pass with exact output and no heap diagnostics. Both engines
check that successful execution leaves no live String allocations.

The raw-source literal decoder preserves U+0001 before braces, unlike the Python
compiler's ambiguous marker replacement. The independently reproduced production
defect is filed as SL-238. No production compiler or lexer files changed.

Next: String fields in value records, preserving mixed pointer/data layouts and
all ownership claims across aggregate copies/returns, plus String-pattern match
for the unchanged keyword_kind and suffix_width lexer helpers.
