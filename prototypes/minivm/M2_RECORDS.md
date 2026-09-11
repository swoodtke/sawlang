# M2: value records over scalar fields

Status: implemented after numeric milestone ecc8d515; validation in README.md. This is the struct subsection of
the lexer dependency checklist. Strings, owning containers, methods, and references
will build on this layout in later isolated milestones.

## Observable source behavior

Single-file named structs with scalar fields or other named structs. Fields may
be comma/newline separated and may carry `public` (cross-module visibility is
validated in the module milestone). Constructors use named fields exactly once,
in any written order; evaluation follows written order. Record field reads,
nested field access, whole-record assignment, and mutation through a mutable
local are supported. Immutable locals and value parameters cannot be mutated.
Passing and returning a record have value semantics. A copy followed by mutation
must leave the original unchanged. Records are nominal: equal layouts do not
make two declared types interchangeable. No record arithmetic, implicit equality,
printing, references, custom initializers, or user-defined copy policies yet.

The first slice requires at least one field and caps a flattened value at 256
words with a located diagnostic. Recursive by-value records are rejected, including
indirect cycles; forward type references are allowed. Nesting is limited to 128
records to bound compiler recursion. Numeric casts and literal
adoption apply at scalar field initialization/assignment exactly as at local
transfers. Built-in type names, duplicate records, duplicate fields, missing or
extra constructor labels, and wrong field types get explicit diagnostics.

## Representation decision

Records are flattened into contiguous scalar slots, recursively in declaration
order. They do not become shared mutable heap handles. This needs no allocator
or provisional garbage collector, and matches scalar record value semantics.
Later String/Vector handles can occupy scalar words with separate ownership rules;
their retention/destruction is not silently supplied by this scalar-only milestone.

Shared model contract:

* `ValueType.Record(index: Int)` identifies a nominal declaration in Program.
* `RecordIR` carries name, ordered `field_names` and `field_types`, and line/col.
* `Program.records` stores the declarations. Numeric helpers return false/zero
  for Record. All actual FuncIR.slots remain flattened scalar types.
* FuncIR.params/result retain source types. Parameter storage is the concatenation
  of their flattened layouts starting at slot zero. Compiler and verifier share
  one checked layout function, not independent offset calculations.
* ExprValue.slot is the first slot of a contiguous value; ExprValue.ty retains
  its source type. Field access computes the relevant subrange.
  A constructor allocates a complete contiguous result range separately from
  initializer temporaries, then populates fields in declaration order. Every
  aggregate expression producer must preserve this contiguity invariant.
* No record instruction is required: construction/copy/assignment lowers to
  scalar Copies after evaluating source operands. The frontend preserves source
  evaluation order independently of declaration-order layout.
* Call.args lists the flattened argument slots; Call.dst is the start of the
  result slot range, or -1 for Void. Return.a identifies the returned range.
  The verifier derives and validates the width/types from the callee signature.

The VM returns a vector of result cells rather than a single Int and initializes
fresh parameter slots on each call. LLVM returns scalar i64 for scalar types,
void for Void, or an LLVM aggregate of i64 fields for Record; record arguments
are flattened scalar ABI parameters. The LLVM emitter packs/unpacks aggregate
results with insertvalue/extractvalue. No LLVM bindings or layout assumptions
about the production Saw ABI are introduced.

All record indices and the complete by-value layout graph must be checked before
indexing or summing widths. Calls validate flattened argument types and complete
destination ranges; Returns validate complete source ranges. VM call arguments
and return words are snapshots, not borrowed slices into another frame. Even a
one-field record uses an LLVM aggregate return type consistently at both ends.

Public helpers are `scalar_type(t)`,
`value_layout(records: &Vector<RecordIR>, t: ValueType) -> Result<Vector<ValueType>, ProtoError>`,
`validate_records(records: &Vector<RecordIR>) -> Result<Void, ProtoError>`, and
`record_field_offset(records: &Vector<RecordIR>, record_index: Int, field_index: Int) -> Result<Int, ProtoError>`.
Void has an empty result layout but is prohibited in fields and parameters.
Record constructors use Saw's `Pair(first: 1, second: 2)` syntax.

## Tests and division of work

Primary implements/reviews model/layout/verifier and defines all interfaces before
delegation. Sol frontend task handles declarations, constructor/field syntax,
typechecking, and scalar lowering. Sol engine task handles flattened argument and
aggregate return ABI in VM and LLVM. A bounded Sol test task adds fixtures, then
the primary independently reviews aliasing, overlap, and evaluation order.

Minimal acceptance examples: two-field construction; reordered labels with
side-effecting calls; independent copy then field mutation; nested records;
assignment through nested fields; records as parameters/results; forward record
declaration; two nominally distinct equal-layout types rejected; immutable
mutation rejected; missing/duplicate/unknown labels; direct/indirect type cycles.
All success/error fixtures use explicit oracles and both VM/native paths, with
native -O0/-O2. Retain M1 and baseline tests. Commit only after integration passes.
