# M14: local StringBuilder support

Implementation contract for SL-257, following M13. The consumer is the unchanged
selfhost lexer: construction, append of String/Byte/Int/Scalar, build, and
reference forwarding. This remains a bounded compiler-known API; compiling the
stdlib's implementation comes later.

## Source and ownership boundary

Add a reserved nominal `StringBuilder` leaf type. A builder is NoCopy. Permit
fresh local initialization from `StringBuilder()` and shared/mutable reference
parameters. The constructor takes no arguments. A fresh local adopts the
constructor's owning slot directly; it must not pass through generic Copy.
Unannotated and explicitly typed local declarations both work.

Reject copying a named builder, reassignment, by-value parameters/results,
record fields, Optional/Result payloads, static builders, user extensions and
raw construction/projection. Value-producing control flow containing builders
is outside this slice. A builder may not escape its local scope. General move
analysis and aggregates containing builders are deferred. Reference forwarding
does not copy the builder: it passes access to the original owning slot.

Methods require named places. `append` requires mutable access and exactly one
String, Byte, Int or Scalar argument, returning `Result<Void, AllocError>`.
Use the stdlib's labels when supplied: `s`, `b`, `value`, `scalar`, respectively.
Bare integer literals select Int; other numeric widths need an explicit
conversion. `build()` requires shared access and no arguments and returns an
owned String snapshot. No other builder operations are admitted.

Register the receiver borrow before evaluating append's argument and restore
it afterward, using the same root-based exclusivity checks as ordinary methods.
Do not introduce the String snapshot-borrow divergence into this API. Both
direct references and forwarded reference parameters must observe mutations.

Install reserved `AllocError` as a nominal record with public Int fields `size`
and `align`, matching std.alloc. Named-field construction and copying are
ordinary record operations; reserve its identity against declarations and user
extensions. Error traits and error formatting remain outside the subset.

## Runtime representation and instructions

A Builder slot owns one immutable String handle using the existing string heap
or native string allocation. It does not own a separate mutable heap object.
Append allocates replacement content and changes the owning slot only after
success. Build retains the current content as a String. Earlier snapshots can
therefore outlive either later appends or destruction of the builder.

Add these operations:

| Operation | Destination | Operands |
| --- | --- | --- |
| BuilderNew | Builder slot | none |
| BuilderBuild | String slot | shared or mutable Ref<Builder> |
| BuilderAppendString | Result<Void, AllocError> | mutable Ref<Builder>, String |
| BuilderAppendByte | same | mutable Ref<Builder>, Byte |
| BuilderAppendInt | same | mutable Ref<Builder>, Int |
| BuilderAppendScalar | same | mutable Ref<Builder>, raw Int code point |

The frontend recognizes Scalar by its M13 nominal identity before projecting
its private word for BuilderAppendScalar. The verifier sees an Int operand;
the runtime also rejects an invalid raw scalar with `runtime error: invalid scalar`
before encoding it or consuming a failure counter. No source
constructor or field-access bypass is introduced.

All append results initialize their full three-word layout `[Bool,size,align]`:
success `[true,0,0]`, failure `[false,requested_size,requested_alignment]`.
Verify the destination range, exact field types and nominal error identity;
append instructions carry the Result descriptor index in `immediate`, checked
as Result<Void,Record(program.alloc_error_record)>; all unused operands keep
their normal defaults. This preserves a nominal check despite flattened slots.
Concretely, Program carries `alloc_error_record: Int` (-1 when absent in older
hand-built programs) and `builder_fail_after: Int` (-1 by default). The frontend
installs the record and sets its index. The latter is contract-test configuration
and is never set by source syntax or the CLI.

Classify Builder as owning for slot cleanup and Drop, including normal scope
exit, loop iterations, early return and propagating try. General Copy,
LoadRef and StoreRef must reject Builder values. Copy of a Ref<Builder> remains
legal. Builder operations access the referenced owning slot directly. Native
Builder words are pointers, VM Builder words are handles; all layout and ABI
helpers must agree. The string live-allocation check includes builder content.

BuilderNew establishes valid empty content. Build of an untouched builder is
an empty String, never an invalid or inactive String handle. Neither backend
may mutate shared content in place. Copy-on-every-append is acceptable here;
capacity growth and performance work require later measurements.

## Byte conversion and failure behavior

String and Byte append preserve exact bytes, including NUL and non-UTF-8 bytes.
Int append uses signed decimal, including Int.min without negating Int.min.
Scalar append encodes the validated code point into exactly 1–4 UTF-8 bytes.
Empty String append succeeds without allocating or changing content.

Every nonempty append first determines the complete byte count. Check all
length/header arithmetic before allocation or copying. Unrepresentable lengths
raise `runtime error: builder length overflow` rather than wrapping, truncating or inventing an
AllocError size. Once a representable allocation is requested, allocation
failure returns Err and leaves both builder content and existing snapshots
unchanged. Error fields describe this runtime's actual requested allocation,
not the production stdlib's different capacity-growth implementation.

Use a Builder-private native append helper that creates the same String header
and updates the existing live-allocation count. Existing String operations keep
their current allocation path. Builder append must not call its fatal allocator
and lose the Err channel. The requested size is new content length plus the
16-byte header, with alignment 8; enforce the current `Int.max - 16` content
bound before addition. Do not saturate an unrepresentable error size. On success,
copy bytes before releasing old content, then install the new handle. On
failure, retain the old handle and release any staging resources.

The VM should propagate recoverable allocation failures from the host operations
it uses. Exhaustion of the interpreter's own bookkeeping or its infallible host
String allocation remains a host-runtime failure, as in earlier milestones;
do not claim that this prototype can recover from all host OOM conditions.

For repeatable failure tests, provide an internal execution/emission option
`builder_fail_after`, default -1 (disabled). A nonnegative N injects one failure
after N successful nonempty append allocation attempts, then disables itself.
This exercises failure followed by recovery in one program. Empty append does
not consume the counter. Positive counters decrement only after a successful
allocation, not after a real failure or invalid input. Use the same policy in VM and native helpers; expose
it to contract tests, not as new source syntax or a user-facing CLI option.

## Acceptance tests

Each source test runs through VM and emitted native code at O0/O2 with literal
expected output. Mark shared-subset cases for Python sawc comparison.

- Empty and repeated build; append after build; snapshot outlives builder;
  multiple snapshots interleaved with appends; two builders remain independent.
- String, Byte and Int formatting: empty, embedded NUL, high bytes, signed
  extremes and zero. Scalar encoding at every UTF-8 width boundary and both
  sides of the surrogate gap, using byte values as the oracle.
- Direct and forwarded shared/mutable references; input expressions evaluate
  once; nested argument evaluation follows borrow rules.
- Loop and early-return cleanup, error propagation and explicit Result match.
  Allocation-failure injection preserves builder/snapshots, reports nonzero
  request fields, and permits a subsequent append after the one-shot failure.
- Located refusal for forbidden copying/storage/transfers/extensions, wrong
  labels/types/arity, mutation through shared access, temporary receivers and
  overlapping borrows. Existing String/Scalar behavior remains unchanged.
- Self-checking IR contracts for every instruction's operands, destination
  layout and invalid forms, plus inactive-zero and failure-state assertions.
  Run native ownership cases under ASan.
- Compile unchanged lexer helper extracts using these APIs, including char_str
  and escape_text where their remaining dependencies fit the current subset.

The full minivm harness, focused differential and independent ownership/failure
contracts gate submission. No Vector or production compiler changes belong in
this patch. Any Python sawc defect encountered gets a minimized Sawtracker
finding; do not encode a workaround or reproduce its wrong behavior here.

Python sawc currently accepts nested implicit receiver borrows that violate
whole-call exclusivity (SL-284); the prototype rejects overlapping builder
receivers. The corresponding rejection is intentionally not a differential
agreement case. Prototype-only storage and transfer restrictions are likewise
excluded from shared-subset comparisons.

Build and run the independent contracts from the repository root:

```sh
python sawc/sawc.py prototypes/minivm/tests/builder_contract.saw -o .build/minivm/builder_contract
.build/minivm/builder_contract
python sawc/sawc.py prototypes/minivm/tests/builder_vm_contract.saw -o .build/minivm/builder_vm_contract
.build/minivm/builder_vm_contract
.build/minivm/builder_vm_contract emit-llvm > .build/minivm/builder_vm_contract.ll
clang -O2 .build/minivm/builder_vm_contract.ll -o .build/minivm/builder_native_contract
.build/minivm/builder_native_contract
```

The runtime contract verifies the same instruction program before VM execution
or native emission. It checks failure fields, unchanged snapshots, one-shot
recovery, empty append counter behavior, reference forwarding and inactive-slot
cleanup. Compile its emitted IR with `-O0` and `-fsanitize=address` as additional
native ownership checks.

`tests/builder_source_contract.saw` additionally compiles source containing an
untaken builder branch and propagated `try` from a local builder. Build it with
`--module-path sawlex=selfhost/lexer`; its VM and emitted native programs must
print `21`, `8`, and `ok` on separate lines, demonstrating error fields and a
successful subsequent call after the injected failure. It accepts the same
`emit-llvm` test-driver argument.
