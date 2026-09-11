# M10: Optional values and conditional binding

## Objective and boundary

Admit the lexer's `Token.suffix: String?`, contextual `None` and String wrapping,
and `if let` bindings as an independently tested milestone. Preserve the M9
copy/ownership contract. Result syntax, propagation, collections, String.to_uint,
optional chaining, coalescing, force unwrap and general generic declarations
remain later slices. Do not change the production compiler or lexer.

## Representation

Use a dedicated `Program.sums: Vector<SumIR>` table, not synthetic nominal
records. `SumKind` has Optional and Result cases; `SumIR` contains kind, payload,
and error ValueTypes. Optional uses error Void. ValueType gains Optional(index)
and Result(index). The Result representation is established now to avoid another
cross-cutting layout migration, but no Result source operations land in M10.

Structurally intern descriptors. Optional<T> layout is Bool tag followed by the
full T layout. Result<T,E> layout is Bool tag, full T layout, full E layout;
Void success contributes no words. Tag true means Some/Ok. Disjoint payload
regions retain a fixed String-versus-integer type for every physical word.
Optional<Void>, Ref payloads and Void Result errors are invalid. Record/sum
cycles, invalid indices, descriptor-kind mismatches and aggregate depth/size
overflow are rejected. Existing 128-depth/256-word limits apply jointly across
records and sums. Reference targets may be data sums, but references still may
not be stored in aggregates or returned.

Migrate value_layout and all dependent type/range/field checks to receive sum
metadata. All Program constructors provide an empty sum table unless used.
Do not let nominal record constructors, fields or extension lookup see sums.

## Construction and ownership

Every construction initializes the complete flattened range. Inactive numeric
and Bool leaves are canonical zero; inactive String leaves are null, established
using Drop on the zero-initialized owning slot. No fake integer String handles.
Some sets the tag and copies a complete payload snapshot. None has false tag
and cleared payload. Reusing slots in loops or replacing Some with None must
release previous String claims. Whole-value copy, references, calls and returns
use the existing complete-layout retain/release and ABI rules.

No new projection opcode is required for conditional binding: the frontend
branches on the canonical tag slot, then copies the known payload range only
on the Some edge. The verifier retains its existing structural scope; this is
not an untrusted bytecode loader. A later forced unwrap must check the tag.

## Source and contextual typing

Accept postfix T? in every data-type position, including record fields,
parameters/results and references. Nested optionals are supported; DoubleQuestion
in a declaration type means two suffixes. Bound recursive type parsing. Generic
Optional<T> spelling is optional convenience, not required by this milestone.
Unsupported coalescing/chaining/force unwrap must fail with a located diagnostic.

None requires an expected Optional type. A bare T implicitly wraps into an
expected Optional<T>, recursively through nested Optional layers; an existing
Optional value of exactly the expected type is copied without wrapping again.
Apply this consistently to declarations, assignments, record constructors,
call arguments, explicit returns, implicit tails and each arm of contextual
if/match. Preserve numeric contextual literal rules through the payload type.
An uncontextualized None is rejected rather than inventing a payload type.
Do not infer types from None or silently choose an arbitrary sibling-arm type.
Preserve whole result ranges and all owning leaves during branch joins/returns.

## Conditional binding

Support statement and value `if let name = optional { ... } else { ... }`,
including else-if chains; permit `if var` with a mutable copied payload and `_`
for ignored payload. Evaluate the scrutinee once and snapshot it before binding.
Only Optional is accepted. The binding exists only in the then scope, and the
scrutinee is evaluated before introducing it (`if let x = x` works). Source
mutation inside the arm cannot invalidate the bound snapshot. Missing else is
valid for a statement, but continuing value paths need a value as in M5.
Early returns and loop iterations clean both scrutinee and payload claims.

## Validation and responsibilities

Engines agent owns model.saw, verify.saw, vm.saw, llvm.saw and migration of
existing direct contracts, plus a new optional_contract.saw. Frontend agent owns
frontend.saw and migrates its Program/layout calls. Tests agent owns isolated
examples/optionals and harness entries. Primary reviews, runs gates, documents
and commits. Coordinate exact public model helpers before implementation.

Contract tests must cover nested/mixed layouts, invalid/cyclic descriptors,
reference storage rejection and Optional record fields. Source tests must cover
Some/None replacement, String/nested record payloads, nested optionals, exact
context propagation, numeric limits, calls/returns/references/methods, statement
and value binding, derived shadowing, subject-once/snapshot semantics, early
return and bounded-loop cleanup, and located rejection paths. Include a small
unchanged lexer Token declaration and tok method extraction where practicable.
Use explicit expected VM/native outputs at O0/O2; use ASan for an ownership probe.
Full previous regression gate and direct contracts must remain green.

## Review finding

SL-239 records a separately reproduced Python sawc rejection: an annotated
String? value-if/if-let is rejected when one arm is already String? and another
needs a String wrap. The prototype applies the destination context per arm.
`examples/optionals/review_nested_context.saw` also checks this through nested
conditional binding, alongside ownership snapshots and Some(None).
