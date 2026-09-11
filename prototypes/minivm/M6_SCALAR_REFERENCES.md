# M6: direct-call scalar references

Status: implemented after M5 (b6b87a58); integration review and gates recorded below.

## Bounded source contract

Accept `&T` and `&var T` function parameters where T is an existing numeric,
Byte, Bool, or payload-free enum type. Calls spell `read(&n)` / `bump(&var n)`;
the operand must be a local, reference parameter, or scalar field of a direct
record local. References are transparent places: reading parameter `x: &Int`
loads its Int, while assigning/compound-assigning `x: &var Int` updates the caller.
Reborrow a parameter using the same explicit argument syntax. A mutable referent
may be reborrowed shared; a shared referent cannot be made mutable.

This milestone does not accept whole-record references, methods, references to
references, reference locals/record fields/statics/results, reference arithmetic,
reference comparison, or references as general expression values. Reject them
with located diagnostics. Those limits isolate addressing and call lifetimes
before record receivers/methods and owning strings. Existing value semantics stay
unchanged. No new prototype issue or patch submission is needed.

## Call lifetimes and exclusivity

Every source borrow ends when its direct call finishes; it cannot escape. Track
active argument borrows while parsing each call, retaining outer-call borrows
while parsing nested arguments. Identify a place by its root binding, conservatively
treating all fields of one record as overlapping. Shared/shared alias arguments
are allowed; any overlap involving a mutable borrow is rejected. Reads of a root
with an active mutable borrow, and writes to any actively borrowed root, are
rejected, including subsequent argument expressions. A value argument evaluated
and snapshotted before a later borrow is valid. Release only this call's borrows
after emitting its Call; preserve the enclosing call's active borrows.

Plain and compound assignments also reserve their destination root while parsing
the RHS: an explicit shared or mutable borrow of that root is rejected, including
inside nested calls/value blocks. Ordinary scalar reads remain allowed (`x += x`).
This follows Saw's design 227 write-path exclusivity rule and prevents a callee's
mutation from being overwritten by the pending assignment. Track pending writes
separately from active call borrows so reading the RHS does not become illegal.

The whole-root overlap rule is deliberately narrower than production Saw, which
can prove disjoint record fields. It is a located subset restriction to remove
when richer record references are added, not a proposed change to Saw semantics.

Incoming reference parameters are distinct roots under this call-site contract.
No mutable globals or closures exist in the subset, so callees cannot discover
another alias outside their arguments. `&var` requires a mutable local/root or
mutable reference parameter. Ordinary by-value parameters remain immutable.
References do not implicitly widen their referent numeric type: &Int8 is not &Int.
The explicit argument mutability spelling must match the requested borrow: a
shared argument cannot initialize a mutable parameter. A mutable argument may
weaken into a shared parameter, while still reserving its explicitly mutable
borrow for the duration of the call.

## Shared representation and primary-owned interfaces

Add `ValueType.Ref(index: Int)` and `Program.references: Vector<ReferenceIR>`.
`ReferenceIR { target: ValueType, mutable: Bool }` describes one reference type;
the frontend interns descriptors structurally. References occupy one logical word
(an integer cell index in the VM, a native pointer in LLVM).
They are NOT scalar data for arithmetic, equality, Const, casts, or printing.

Model helpers:
- `reference_type(t: ValueType) -> Bool`
- `reference_target(refs: &Vector<ReferenceIR>, t: ValueType) -> Result<ValueType, ProtoError>`
- `reference_mutable(refs: &Vector<ReferenceIR>, t: ValueType) -> Bool` (false for invalid/non-reference)
- `reference_transfer(refs: &Vector<ReferenceIR>, source: ValueType, target: ValueType) -> Bool`
  permits identical referent types and either equal mutability or mutable-to-shared.
- `validate_references(refs: &Vector<ReferenceIR>) -> Result<Void, ProtoError>`
  requires scalar-data targets; whole-program validation additionally checks enum indices.

Keep `scalar_type` unchanged. `value_layout` accepts a root Ref as one word, but
record fields containing references remain rejected. Function slots may contain
scalar data or Ref. Validate every reference index before dereferencing metadata.
No reference result or constant is allowed. Copy may copy references according
to reference_transfer; Call arguments must have the exact callee parameter type
(the frontend inserts a qualifying Copy where needed).

New instructions:
| Op | Contract |
| --- | --- |
| Addr | dst is Ref, a is a scalar-data slot of exactly its target type; produces its address |
| LoadRef | a is Ref, dst is a scalar-data slot of exactly its target type |
| StoreRef | a is mutable Ref, b is scalar data of exactly its target type; dst unused |

The verifier checks these structural/type rules and existing CFG/ranges. Source
mutability, initialization, alias restrictions, and address provenance are frontend
proofs, not a claim that the IR is an untrusted bytecode loader.

## VM and handwritten LLVM

The VM changes from independent frame slot vectors to a shared cell vector with
a base offset for each active frame. Frame creation appends initialized cells;
all local accesses use base + slot. Addr produces that absolute cell index.
LoadRef/StoreRef access the indexed cell with explicit runtime bounds checks and
`runtime error: invalid reference` on failure. Call arguments/results are still
snapshots. Copy return words before popping the frame's cells. On an error the
whole execution aborts and frees the shared vector. Indices remain valid across
Vector growth, unlike pointers into its backing allocation. Preserve depth and
instruction budgets, all numeric behavior, and record value snapshots.

LLVM keeps scalar data allocas and data arguments as i64, but Ref slots and
reference arguments use native `ptr`. Addr stores the scalar slot's pointer in
the Ref alloca; LoadRef/StoreRef load that pointer and load/store i64 data through
it. Reference Copy uses ptr loads/stores, and function/call parameter emission
distinguishes Ref words from data words. No pointer-to-integer roundtrip, pointer
arithmetic or heap allocation is introduced. Borrowing one scalar record field
uses that field's existing alloca; whole-record reference contiguity is deferred.

## Frontend implementation guidance

Keep signature parameter types as Ref, but resolve a reference binding to a place
with its referent type and indirect address slot. Extend Place with an explicit
direct/indirect distinction and root-binding identity. Ordinary expression reads
snapshot the referent through LoadRef; assignments emit StoreRef after the usual
transfer checks. Compound assignment resolves/loads its destination before RHS
evaluation and performs the existing checked arithmetic before storing. The
write-path restriction above forbids overlapping RHS borrows regardless of this
lowering order.

Only parse an address argument when the known formal parameter is Ref. Parse the
explicit `&` / optional `var`, then a place; verify type, mutability, and overlap.
For direct places emit Addr of the requested reference descriptor. For forwarding
an existing reference parameter use a qualifying Copy, never address the pointer
slot itself. Reject unexpected address syntax for a value parameter. Register the
borrow before parsing subsequent arguments and restore the borrow stack at call exit.
Enforce read/write conflicts centrally so nested value blocks and calls participate.

## Delegation and validation

Primary owns this design, model.saw, verify.saw, direct reference contract tests,
documentation and final integration. Sol frontend owns frontend.saw only. Sol
engines owns vm.saw and llvm.saw only. Sol tests owns test_minivm.py and
examples/references only. Agents may compile individual scratch probes; primary
coordinates suite runs and commits. Any Python sawc findings encountered are
independently reproduced and filed in Sawtracker, as the user requested.

Test shared reads, caller-visible mutation, compound updates, scalar record-field
addresses, Bool/Byte/enum/full UInt64 references, shared/shared aliasing, recursive
forwarding and growth of VM storage while an ancestor reference stays live,
mutable-to-shared forwarding, value-before-borrow snapshots, and reuse after calls.
Reject mutable access through shared references, borrowing immutable places,
referent type mismatch, missing/wrong address syntax, mixed alias arguments,
later-argument reads/writes during exclusive borrows, escaped/stored references,
and whole-record/nested references. Direct IR tests cover invalid indices, target
types, Addr/LoadRef/StoreRef, qualification Copy, reference constants/results, and
existing verifier boundaries. All prior cases plus the new isolated section must
pass with explicit expected outputs through VM and clang O0/O2; run all direct
representation contracts and compare representative source semantics with Python
sawc without treating its acceptance as the correctness oracle.

## Completed validation

- 227 integration cases pass: the previous 193 plus 34 reference cases. Valid
  programs run in the VM and through clang at both O0 and O2; invalid programs
  require located diagnostics. Existing budget/depth cases remain green.
- All four direct contracts (numeric, record, enum, reference) compile and pass.
  The reference contract covers malformed metadata/opcodes and defensive VM
  bounds checks for negative and out-of-range addresses.
- Python sawc agrees with the independent expected outputs for scalar mutation,
  recursive forwarding/storage growth, and mutable-to-shared forwarding.
- Review corrected assignment-RHS borrowing to enforce Saw design 227 for both
  plain and compound assignments. Tests cover those rejections alongside legal
  self-reads and borrows of a different root. Repeated nested reference syntax is
  rejected immediately rather than recursing through unsupported types.
- No new production compiler defect was established in this milestone.

Next: whole-record references and basic instance methods, using a scalar-only
`Lexer.advance`-shaped fixture. Establish aggregate addressing and receiver
exclusivity before adding owning String/Builder/Vector operations.
