# M9: String-valued records and String-pattern match

Status: design after M8 (36cc9d69).

## Scope and invariants

Allow String leaves in existing nested value records. Record copies retain their
String contents; writes release replaced contents; String fields can be borrowed
and accessed through record references and methods. All existing whole-root
exclusivity rules remain. No stored references, custom destructors, user-defined
copy/move policy, Optional/Result or collections in this slice.

Add literal String patterns plus a required final wildcard to both value and
statement match. Compare decoded byte content with existing String Eq; reject
duplicate decoded patterns, non-String patterns, interpolation and missing
wildcard. Preserve enum match behavior. Statement arms retain existing block
requirements, while value arms use the existing expression/block value rules.
Snapshot subject before evaluating any arm; an arm may subsequently mutate the
original binding without changing which value was matched.

## Layout and ownership

value_layout now permits String leaves in records; Ref leaves stay rejected.
Flattened layouts remain authoritative for every copy/call/return/address.
No new opcodes or type metadata are needed. Copy of an aggregate is lowered from
a complete source snapshot, so writes cannot partially overlap a live source.
Verify that assignment, constructor fields and value joins all maintain this
invariant rather than assuming a per-word copy is safe in isolation.

LLVM data arrays now include String words: every non-Ref `%sN` is a GEP into
the existing `[N x i64]` allocation, with ptr loads/stores for String words.
Initialize every String slot to ptr null. This is a host-64 ABI (8-byte pointers
and i64 cells, naturally aligned), not a cross-target layout promise. Ref slots
may remain separate ptr allocas because references cannot be stored in records.
Opaque LLVM pointers preserve pointer provenance; do not use ptrtoint/inttoptr.

Aggregate LLVM types derive from the exact flattened layout: ptr for String,
i64 for scalar words. Use that same type for function results, calls, insertvalue
and extractvalue. Parameter flattening emits ptr for String words and retains
them into callee-owned slots. Callee record returns snapshot all words and retain
every String word BEFORE any local cleanup; caller adopts each returned String
claim, releasing overwritten destination claims without another retain.

Both VM and LLVM bulk LoadRef/StoreRef use three phases: snapshot all words,
retain all String words, then release and replace all destination words, adopting
the snapshot claims. This protects partially overlapping ranges and repeated
String handles. Whole-record source assignments use fresh frontend snapshots.

Frontend lexical cleanup and returns preserve a whole result RANGE, not one
slot. Preserve/promote every String leaf in the returned value layout at a
value-block exit; cleanup_function excludes the complete return range. Other
String slots still Drop normally. Backend return cleanup remains idempotent and
retains the result before releasing frame claims. Unreachable dummy record
returns initialize String leaves via StringConst of the empty string, numeric
leaves with Const, never fake integer String handles.

## Delegation and tests

Primary owns model.saw, verify.saw as needed, direct owning-record contracts,
design/docs, integration review, gates and commit. Sol frontend owns frontend.saw;
Sol engines owns vm.saw/llvm.saw (String runtime changes only if necessary);
Sol tests owns test_minivm.py and examples/owning_records. No suites run by agents.

Supersede the M8 String-record-field rejection with positive record tests.
Direct contracts include mixed layouts, aggregate ref accesses and overlapping
bulk transfers with repeated String handles, plus invalid field/range/type checks.
Native/VM successful execution must leave zero live String allocations. Source
tests cover nested copies/replacement, field refs and mutating methods, mixed ABI,
record returns from value if/match, early return and loop cleanup, alias-safe
assignment and retained snapshots. String matches cover all branches/default,
empty/NUL/UTF-8/escaped patterns, decoded duplicates and unsupported patterns.

Integration extracts use the unchanged lexer keyword_kind and suffix_width
functions, actual TokenKind declaration, and an unchanged Lexer.advance body
with its real String-backed Lexer fields plus ubyte/constants. Validate keywords
and suffixes against explicit expected values; advance checks ASCII, newline and
UTF-8 continuation-byte column behavior. Keep the existing lexer source unchanged.
Run all retained tests plus new cases on VM and clang O0/O2, all representation
contracts, and targeted native memory checks for owning aggregate transfers.

Next: fixed Optional/Result families and their payload cleanup/try propagation,
then opaque builder/vector runtime operations, and the unchanged whole lexer.
