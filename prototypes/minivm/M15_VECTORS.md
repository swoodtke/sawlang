# M15: vectors and bounded ownership transfer

SL-258 follows M14. The exact lexer needs Vector<Token>, Vector<DocComment>
and Vector<StringSegment>, with String-owning Copy elements. It returns
Result<Vector<Token>,LexError> and moves three vectors into NoCopy LexResult.
Implement storage and ownership as separately testable parts of one milestone.
Do not implement general generics, recursive data, or noncopyable elements.

## Source contract

Reserve Vector<T>. T may be any existing non-Void, non-reference Copy value:
integers, Bool, enum, String, records, Optional and Result composed of these.
Reject Builder, Vector and vector-containing records/sums anywhere in T.
Element identity is nominal, not just a flattened layout match.

Support empty Vector<T>(), len(), push(value:), get(index:), and checked
read-only indexing v[index], including field projection on the copied result.
Labels are optional but exact when present. len returns Int; push returns
Result<Void,AllocError>; get returns T?, None for negative/out-of-range indices.
[] traps with `runtime error: vector index out of bounds`. Both get forms return
owned element snapshots; there are no escaping element references or indexed
writes. Vector receivers are named local/field places or reference parameters.
Register receiver borrow before evaluating arguments/index: push mutable,
len/get/index shared. Evaluate inputs once. Mutable/shared vector reference
forwarding and vector fields through record references work.

Vectors are NoCopy, as are any record or Optional/Result containing a vector.
Permit fresh-value local initialization, explicit `move name` of a whole local,
vector-containing record construction, returns, Result wrapping/try extraction,
and consuming a fresh Result/Optional in matches/conditional binding.
Reject implicit reads of named noncopyable values. move checks active borrows,
transfers ownership into a fresh temporary, and marks the entire binding moved;
all later reads, moves, field accesses or borrows of that root are errors.
Only whole direct local moves are supported: reject moving fields, dereferenced
parameters or indexed elements. Copy values need not gain move syntax here.

Permit exactly empty `extension R: NoCopy {}` when R actually contains a vector;
reject this marker for otherwise-copyable records rather than pretending to
enforce a general user-defined copy policy. Other trait bodies remain excluded.
Vector-containing by-value parameters, reassignment, static values and general
value-producing if/match joins are deferred; use references for parameters.
Returning an owned temporary/fresh record or an explicit moved local works.
Do not reject by-value *results*: the lexer requires them.

Use conservative moved-binding tracking across branches: a move in any parsed
branch invalidates the binding after that branch, even if another path could
retain it. Document this limitation. Reject moving a binding declared outside
the current loop from inside the loop; otherwise a second iteration could use
inactive storage. Inner-loop locals may be moved. No source escape is allowed
through these restrictions. Tests must distinguish these bounded restrictions
from behavior required by production Saw; only shared-subset tests compare.

## Shared model and instructions

Add ValueType.Vector(index), VectorIR(element:ValueType), Program.vectors and
Program.vector_fail_after (-1 disabled). Existing Program literals supply an
empty vector table and -1. A Vector word is an owning leaf, including inside
flattened records and sum payloads. value_layout needs no vector table because
the leaf stays one word. Helpers: vector_type(t), vector_element(vectors,t),
copyable_type(records,sums,t), validate_vectors(records,sums,vectors).
Validate descriptor indices wherever types occur and reject noncopyable elements.

Add these operations (unused fields retain instruction() defaults):

| Op | dst | a | b | immediate |
| --- | --- | --- | --- | --- |
| VectorNew | Vector<I> | unused | unused | 0 |
| VectorLen | Int | Ref<Vector<I>> | unused | 0 |
| VectorIndex | element layout | Ref<Vector<I>> | Int index | 0 |
| VectorGet | Optional<element> layout | Ref<Vector<I>> | Int index | Optional descriptor |
| VectorPush | Result<Void,AllocError> layout | mutable Ref<Vector<I>> | element layout | Result descriptor |
| MoveVector | Vector<I> | Vector<I> source | unused | 0 |

Check exact element and nominal sum descriptor identity, full ranges, defaults,
and reference mutability. MoveVector requires distinct same-typed slots, drops
the old destination, transfers the source and zeros it. Inactive zero is legal
for MoveVector and Drop; it is never a valid method receiver. Generic Copy,
LoadRef and StoreRef reject vector-containing values. Address/RefField remain
legal. Internal aggregate transfer emits MoveVector for vector leaves, existing
Copy for other words; stage through fresh slots before replacing overlapping
ranges. Source implicit noncopyable reads must be rejected before reaching this
helper. All sum initialization clears vector words with Drop, not Const.

By-value vector-containing parameters are verifier errors for this slice.
Return transfers each vector leaf out and zeros the source BEFORE frame cleanup;
String leaves retain as before. Call results adopt returned vector leaves,
dropping any old destination. All owning slots initialize inactive and clean up
on scope exit, loops, return and propagated errors. Preserve existing Builder
restrictions and existing String copy semantics.

## VM representation

Use a separate Vector<VectorEntry> heap. Entry has descriptor:Int,
alive:Bool, words:Vector<Int>, length:Int. Handles are positive indices;
zero is inactive. Validate live handles and descriptor identity on operations.
Constructor creates a live empty entry. Cleanup releases every String leaf of
every element using its descriptor layout, then marks the entry inactive.
Vector elements cannot own vectors, so destruction does not recurse into this
heap. Final execution checks live vector entries as well as String references.

Push stages old raw words plus incoming raw words in a new host Vector<Int>,
recovering fallible push failures before changing the entry. Once staging
succeeds, retain incoming String leaves, replace storage and increment length.
Existing element handles relocate without retain/release. Failed push leaves
content/length and input ownership unchanged; argument temporaries clean up in
their normal scope. Get/index copy String leaves with retain. Host bookkeeping
and infallible constructor OOM remain interpreter infrastructure limitations.

## Native representation

Vector owning word is a unique pointer to a stable 16-byte header:
{ i64 length, ptr data }. New mallocs the header with length0/data null; failure
is a runtime allocation trap (constructor is infallible in the source subset).
No refcount/sharing or capacity API. Push allocates exactly (len+1)*width*8 bytes,
copies existing words and incoming words, retains incoming String leaves, then
installs the new buffer/length and frees old raw storage without dropping its
relocated elements. Growth on every push is acceptable for this prototype.

Emit descriptor-specific drop/push/index helpers (or equivalent verified static
metadata), using the element's flattened layout for String retain/release.
Get/index may return an internal pointer into storage to the emitter, which
immediately copies/retains fields into destination slots; never expose that
pointer as source-level borrowed storage. Optional Get must clear ALL inactive
payload words on misses and when reusing destination slots in loops.
Track live vector headers and include their count in successful-exit checks.
Keep native by-value result ABI pointer classification consistent for vector
leaves in flat aggregate returns. Existing String ownership remains separate.

## Errors and deterministic failure tests

Bad zero/dead handles: `runtime error: invalid vector handle`.
Unrepresentable length/buffer arithmetic: `runtime error: vector length overflow`.
Check len>=0, width>0, len+1 and multiplication against Int.max before allocation
or data access. Do not wrap or saturate requested bytes. Push allocation failure
returns [false,requested_bytes,8]; success [true,0,0]. Initial empty header has
no element buffer, and the push error reports the requested *buffer* allocation.

Program.vector_fail_after is a separate one-shot counter shared across calls:
-1 disabled, 0 fails next representable push then resets to -1, positive N
decrements only after success. No CLI/source flag. Invalid inputs and real
allocation failure do not consume a positive counter. Both backends obey this.

## Independent gates and division of work

Parent owns this design, shared model/verifier, migration of existing Program
literals, integration, review and final submission. Sol frontend owns
frontend.saw, source fixtures and harness registration. Sol VM owns vm.saw and
new vector runtime contracts. Sol native owns llvm.saw and vector_runtime.saw.
Agents use isolated worktrees; only owned files are integrated.

First prove empty/push/len/index/get independently with Int and String, then
String-owning records/Optional/String-backed enum records, then move/Result/
aggregate/reference/cleanup paths. Assert snapshots survive later pushes and
vector destruction, get misses clear old payloads, once-only argument/index
evaluation, bounds traps, exact failure fields and recovery. Test moved roots,
double move, borrow after move, noncopyable element rejection, nominal descriptor
mixups, aggregate implicit copy, and outer-loop moves. Native owning cases run
at O0/O2 and under ASan. Full existing harness and bounded sawc differential
gate the patch. Production findings go to sawtracker, not compatibility hacks.

The latest lexer also needs StringBuilder.clear() and break. They are separate
whole-lexer integration gaps for SL-259, not hidden parts of Vector support.
Update the inventory accordingly; M15 alone does not claim whole-lexer success.
