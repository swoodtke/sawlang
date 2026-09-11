# M7: record references and basic instance methods

Status: implemented after M6 (94110cfd).

## Source scope

Allow `&Record` and `&var Record` parameters for the existing nonempty,
scalar-only/nested value records. Reading a reference produces a by-value
snapshot; replacing it or assigning a field updates the caller. References to
scalar/nested fields can be forwarded through a record reference. The existing
ban on stored/returned/nested references remains. Whole-root borrow overlap and
assignment-RHS exclusivity from M6 remain intentionally conservative.

Allow `extension Record { func name(&self, arg: Int) -> Int { ... } }`
and `&var self`. Methods require an explicit first receiver, are unique by
record/name (no overloads), and lower to ordinary functions with the receiver
as first Ref parameter. Different records may have same-named methods; free
functions and methods have separate lookup. Multiple extension blocks may add
distinct methods. Reject unknown/non-record extension targets, traits, static
methods, generic extensions, by-value receivers and duplicate methods.

Call a method on a named local/reference parameter or nested record field:
`cursor.advance(byte: b)`, `self.reset()`, `outer.cursor.position()`.
The receiver is borrowed before explicit arguments, with mutability dictated by
the method signature. An immutable receiver cannot call a mutable method.
Do not snapshot the receiver before calling a mutating method. Method calls on
temporaries/general value expressions remain a located subset rejection.
Explicit arguments retain positional order; optional labels must match the
corresponding formal parameter name (no reordering or duplicate labels).
This optional-label rule also applies to existing free-function calls.

## Shared IR contract

ReferenceIR targets may now be scalar data or Record; value_layout of a Ref
remains one reference word. Record fields cannot themselves contain Ref.
Existing record layout validation checks cycles and empty/invalid records.

- Addr: dst Ref points at `a`, the start of a flattened scalar/record slot range
  exactly matching the target layout. No source pointer arithmetic.
- LoadRef: snapshot the entire target layout into dst's contiguous data range.
- StoreRef: copy b's entire target layout through mutable Ref a. Snapshot source
  words before stores, so overlap cannot change copy behavior.
- New RefField: a is Ref to Record, immediate is a direct field index, dst is Ref
  to that field's exact declared type. Destination mutability may weaken but may
  not strengthen the parent. Compute offset with record_field_offset. Nested
  fields use repeated RefField instructions. Field indices and both Ref types
  must be validated before metadata access; no arbitrary integer offset opcode.

Primary owns model.saw and verify.saw updates. Keep helpers' signatures stable;
validate_references accepts Record targets and check_declared_types validates
their indices before record layout traversal. Addr/LoadRef/StoreRef use
range_matches against value_layout. Methods need no new backend ABI: they are
ordinary functions with a Ref parameter followed by value/reference arguments.

## Engine representation

VM retains shared absolute-index cells. Bounds-check the whole referent extent
using subtraction after validating the start, avoiding overflow. RefField checks
the parent range before adding the validated field offset. Preserve snapshots
for overlapping bulk stores and loads. All invalid handles report the existing
`runtime error: invalid reference`.

LLVM must make data words contiguous: allocate a single `[N x i64]` data array
per function, N = number of logical slots (including unused holes at Ref slots).
Define each data `%sN` as a constant-index GEP into it; Ref slots remain separate
native `ptr` allocas. This preserves every existing slot name and mixed ptr/i64
call ABI while making a record's consecutive data words addressable from its
first word. Addr stores that native pointer, RefField uses typed i64 GEP by the
computed field-word offset, and bulk accesses load/store i64 at consecutive
offsets. Load all source words before any stores for snapshot semantics. Keep
all allocas/GEP definitions in entry, no ptrtoint/inttoptr conversions.

## Frontend implementation guidance

Signature carries method owner (record index or -1); free lookup excludes
methods. Scan extensions and method signatures before bodies, so forward and
recursive calls work. Compile receiver as named `self` Ref binding. Permit the
lexer-token spelling of self explicitly if distinct from ordinary identifiers.

Keep Place's root binding identity across projections. An indirect record field
projection emits RefField with an interned field descriptor. Forward its actual
pointer slot type, not the original root binding's whole-record Ref type.
read_place allocates new_value(target), then LoadRef; store_place emits StoreRef.
Resolve named place method calls before parse_atom snapshots any receiver.
Use the same borrow registration and pending-write restrictions for implicit
receivers as explicit address arguments. Preserve enclosing call borrow stacks.

## Validation and ownership

Primary authors design, reviews integration, adds direct IR contracts and runs
all suites under the machine suite lock. Sol frontend owns frontend.saw; Sol
engines owns vm.saw/llvm.saw. The separate patch reviewer owns no prototype files.
No prototype tracker issue/patch; independently established Python bugs are filed.

Tests: nested record read/replace, scalar/nested field mutation and forwarding,
whole-record return snapshots, mixed reference/value ABI, ancestor references
across recursive VM growth; shared/mutable methods, same name on distinct record
types, forward calls, multiple extension blocks, named arguments, and a scalar
Lexer.advance-shaped receiver updating position/line/column. Reject shared writes,
immutable mutation, receiver/argument overlap, pending-write receiver borrowing,
wrong labels/arity/types, invalid extensions/method declarations, and escaping
references. Direct contracts pin RefField invalid index/type/mutability, malformed
aggregate ranges and runtime bounds. Retain all previous cases except the M6
whole-record-reference rejection, which is explicitly superseded by this slice.
Run VM and clang O0/O2 expected-output gates and all representation contracts.

## Completed validation

- 250 integration cases pass: the previous 227, minus the superseded
  whole-record-reference rejection, plus 24 receiver cases. Valid cases execute
  through both the VM and clang at O0/O2; rejection cases require located errors.
- All five direct representation contracts compile and pass. The new receiver
  contract exercises nested projection, qualification, malformed field/range/type
  combinations and whole-referent bounds checks, including Int.max handles.
- Python sawc independently agrees with expected outputs for whole-record
  replacement/snapshots, shared/mutable methods and the lexer-style receiver.
- Review caught and fixed a whole-record load destination using a scalar slot
  allocation instead of the flattened record layout. Final gates include that
  exact whole-record snapshot/replacement case.
- No new Python compiler defect was established by the prototype work. SL-222
  patch review was separate and its ownership finding was posted there.

Next: define owned String representation and copy/drop points, then isolate
literals, byte length/access, equality and substring in VM/native tests. Keep
builders, vectors and Optional/Result payload ownership for subsequent slices.
