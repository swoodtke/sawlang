# Saw compiler / VM prototype

A small compiler written in Saw, with two consumers of the same typed instruction
stream: an interpreter and a handwritten textual LLVM IR emitter. The existing
Saw lexer is reused. There are no LLVM library calls in this prototype.

The existing Python compiler builds the prototype executable. Once built, it
parses, checks, lowers, interprets, and emits IR without invoking Python. It
cannot yet compile its own source.

[COMPATIBILITY.md](COMPATIBILITY.md) tracks known semantic differences,
unsupported features and implementation limits, with the work required toward
full Saw support. In particular, Vector snapshot reads are not borrowing places.

## Build and try it

From the repository root, using a Python environment with Saw's dependencies:

```sh
mkdir -p .build/minivm
python sawc/sawc.py prototypes/minivm/src/main.saw \
  --module-path sawlex=selfhost/lexer -o .build/minivm/minivm
.build/minivm/minivm run prototypes/minivm/examples/factorial.saw
.build/minivm/minivm emit-llvm prototypes/minivm/examples/factorial.saw > .build/minivm/factorial.ll
clang .build/minivm/factorial.ll -o .build/minivm/factorial
.build/minivm/factorial
```

The LLVM path targets a 64-bit Unix C ABI (stdio, allocation and byte-copy routines); validation
uses Apple clang on arm64 macOS. Clang is an external validation/compilation step,
not a dependency of the interpreter or text emitter.

## Supported source

```saw
func factorial(n: Int32) -> Int32 {
    if n <= 1 {
        1
    } else {
        n * factorial(n - 1)
    }
}

func main() {
    print(factorial(5))
}
```

Single-file programs support signed and unsigned 8/16/32/64-bit integers,
`Int`/`UInt` (64-bit), `Byte`, `Bool`, functions, positional calls,
recursion, `let`/`var`, assignment, lexical scopes, `if`/`else if`/`else` and
`while`, explicit and implicit tail returns, and numeric/Bool printing. Named structs can contain scalars
Strings or nested structs, with
field access, mutable fields, value copying, and function parameters/results.
Payload-free enums support copying, equality, record fields and function
parameters/results. Exhaustive enum `match` supports qualified or unqualified
cases and a final wildcard; see [M4_ENUMS.md](M4_ENUMS.md). Value-producing `if`
and `match` join numeric, Bool, enum, or record values, with explicit returns
allowed inside arms; see [M5_VALUE_CONTROL.md](M5_VALUE_CONTROL.md).
Record layouts are limited to 256 words and 128 nesting levels; see
[M2_RECORDS.md](M2_RECORDS.md). Arithmetic is checked; signed
division truncates toward zero. Overflow and division by zero print an error
and exit with status 1. Boolean conditions require `Bool`.

Integer literals support decimal, hex, binary, octal and fixed-width suffixes;
bare literals default to `Int`. Numeric operations include checked `as` casts,
truncating conversions, wrapping arithmetic, bitwise operations, and checked
shift counts. See [M1_NUMBERS.md](M1_NUMBERS.md) for the precise numeric contract.

Newlines separate statements. Omit the result annotation for Void functions;
`main()` must take no arguments and return Void. Value-returning functions need
a value on every continuing path, supplied by an explicit return or final expression.
There are no imports, general collections, user-defined generics, or concurrency
in the accepted subset. `Result<T,E>` and `Vector<T>` are compiler-known fixed
generic types.
Semicolons remain unsupported. Boolean `&&`/`||` short-circuit, mutable integers
and fields support `+=`/`-=`/`*=`/`/=`/`%=`, and module `static` integer/Bool
constants accept literal and numeric-limit initializers. See
[M3_SCALAR_CONTROL.md](M3_SCALAR_CONTROL.md) for this frontend slice.
The prototype still accepts broader lexical shadowing than Saw's design-100 rule.

Scalar and record `&T` / `&var T` function parameters support explicit call-site
borrowing, forwarding, snapshots and caller-visible mutation. Nested fields can
be borrowed through record references. Overlapping mutable arguments and borrowing an assignment's
destination inside its RHS are rejected. Different fields of one record are
conservatively treated as overlapping. Reference storage/results remain
unsupported; see [M6_SCALAR_REFERENCES.md](M6_SCALAR_REFERENCES.md).

Record extensions support instance methods with `&self` / `&var self`, called on
named locals, reference parameters or nested fields. Optional call labels must
match parameter names in order. Temporary receivers, overloads, static methods
and trait extensions remain unsupported. See [M7_RECORD_RECEIVERS.md](M7_RECORD_RECEIVERS.md).

Owned String values support literals, copies, locals, parameters/results,
references, equality, printing, and `len`, `is_empty`, `byte_at`, `substring`,
and `equals`. Byte offsets and embedded NUL are preserved. Intrinsic String
methods also accept temporary receivers. String statics, interpolation
and concatenation remain unsupported. Both engines retain/release owning slots
and check for live allocations after successful execution; see
[M8_OWNED_STRINGS.md](M8_OWNED_STRINGS.md).

Nested records can own String fields, including through references, methods and
aggregate calls/returns. String matches support literal patterns and a required
final wildcard, comparing decoded bytes and snapshotting the subject before
arm execution. See [M9_OWNING_RECORDS_MATCH.md](M9_OWNING_RECORDS_MATCH.md).

Optional values support postfix `T?` and nested `T??`, contextual `None` and
implicit payload wrapping, including String-owning record fields. Statement
and value `if let` / `if var` evaluate once and bind copied payloads in the then
scope. Coalescing, chaining and force unwrap remain unsupported. See
[M10_OPTIONALS.md](M10_OPTIONALS.md).

Fixed `Result<T,E>` types support unambiguous payload wrapping, explicit qualified
Ok/Err constructors, payload matches, and `try` / `try!`. Error propagation
returns immediately with full ownership cleanup. Result<Void,E> success uses a
bare return. Statement match arms accept blocks or Void call expressions;
value arms may be expressions or blocks. Forced errors print `runtime error: try! failed`; cause formatting
and catch blocks remain unsupported. See [M11_RESULTS.md](M11_RESULTS.md).

`String.to_uint()` and `String.to_uint(radix:)` return `UInt?`, accepting whole
byte strings in bases 2 through 36 and an optional leading plus. Invalid input
and overflow return None. Full unsigned 64-bit values are preserved; see
[M12_UNSIGNED_PARSE.md](M12_UNSIGNED_PARSE.md).

`Scalar(value: Int)` validates a Unicode code point and returns
`Result<Scalar, InvalidScalar>`. `Scalar.value()` exposes the code point on a
named place. Both builtin records are nominal and opaque: source cannot use
their private representation fields, construct `InvalidScalar`, or extend
either type. `InvalidScalar` cases and formatting are intentionally deferred;
Result matching can currently observe and forward only the opaque error value.
See [M13_SCALAR.md](M13_SCALAR.md).

Local `StringBuilder()` values support String, Byte, Int and Scalar append,
shared `build()` snapshots, `clear()`, and shared/mutable reference forwarding. Append
returns `Result<Void, AllocError>`; `AllocError` has public Int `size` and `align`
fields. Builders cannot yet be copied, reassigned, returned by value or stored
in aggregates. Append preserves previous snapshots and leaves content unchanged
on allocation failure. See [M14_STRING_BUILDER.md](M14_STRING_BUILDER.md).

`Vector<T>` supports empty construction, `len`, `push`, `get`, checked read-only
indexing, and shared/mutable reference forwarding. Elements may be non-Void,
non-reference Copy values, including records and Optional/Result values that own
Strings; nested vectors and other noncopyable elements are rejected. Vectors are
unique owning values: whole local moves, vector-containing aggregate construction
and by-value results are supported, while implicit copies, by-value parameters,
reassignment, statics, indexed writes and escaping element references remain
outside this slice. Push failure preserves the vector and its input, and get or
index returns an owned element snapshot. See [M15_VECTORS.md](M15_VECTORS.md).
Move tracking is conservative across branches, and moving an outer local inside
a loop is rejected. Empty `NoCopy` markers are accepted only on records that
contain vectors; general explicit copy policies and vector-valued control-flow
joins remain unsupported.

Conditional while bodies support bare statement `break`, including nested
loops and owning-value cleanup. Value-bearing breaks, continue and loop values
remain unsupported. Repeated `let _ = ...` declarations discard a result without
creating a binding. See [M16_LEXER_ACCEPTANCE.md](M16_LEXER_ACCEPTANCE.md).

The VM defaults to a shared budget of 1,000,000 instructions and a maximum call
depth of 128. Override the budget with `run FILE --budget N`. These limits apply
only to VM execution; native code uses the host call stack and has no budget.

## Validation

```sh
python prototypes/minivm/test_minivm.py --binary .build/minivm/minivm
```

The harness compares VM execution and clang-compiled IR with explicit expected
outputs and statuses, checks rejected programs, and exercises VM limits. It
uses temporary files and 30-second execution timeouts. Native execution is
checked at both `-O0` and `-O2`. The first sixteen milestones cover 439 cases;
the Vector section covers 30, with 13 shared-subset cases also checked against
Python sawc using `--section vectors --sawc sawc/sawc.py`.

Independent representation checks live in `tests/numeric_contract.saw`,
`tests/record_contract.saw`, `tests/enum_contract.saw`,
`tests/reference_contract.saw`, `tests/receiver_contract.saw`,
`tests/string_contract.saw`, `tests/owning_record_contract.saw`,
`tests/optional_contract.saw`, `tests/result_contract.saw`,
`tests/uint_parse_contract.saw`, `tests/scalar_contract.saw`,
`tests/builder_contract.saw`, `tests/builder_vm_contract.saw`,
`tests/builder_source_contract.saw`, `tests/vector_contract.saw`,
`tests/vector_vm_contract.saw`, `tests/vector_source_contract.saw`, and
`tests/builder_clear_contract.saw`; build and run them
with the Python compiler.
Use `--section numbers`, `--section records`, `--section control`, or
`--section enums`, `--section values`, `--section references`, or
`--section receivers`, `--section strings`, `--section owning_records` or
`--section optionals`, `--section results`, `--section unsigned_parse`, or
`--section scalars`, `--section builders`, `--section vectors`, or
`--section lexer_completion` for an isolated
integration gate.

The whole-lexer gate concatenates the unchanged `selfhost/lexer/src/lib.saw`
with a generated driver and compares complete token/doc/segment/error records
across the VM, native O0/O2/ASan and Python-sawc-built source:

```sh
python prototypes/minivm/test_lexer.py --binary .build/minivm/minivm \
  --timeout 300 --compile-timeout 600
```

Use `--case-prefix golden-` for the five exact hand-authored golden cases, or
`--large --large-limit 100` to add tracked-source inputs. The default corpus
includes lexer tests, the lexer source itself and explicit lexical edge cases;
lexing a test file is distinct from exercising the input strings inside it.
Failure artifacts remain under `.build/scratch/lexer-*`. Passing this gate means
the complete lexer runs under the prototype, not that full Saw is supported.
M16 validation passed 39 default inputs and 100 additional tracked files through
all five engine modes, plus 15 focused completion cases (13 compared with sawc).

To run the initial SL-260 shared-subset differential as well:

```sh
python prototypes/minivm/test_minivm.py --binary .build/minivm/minivm \
  --section unsigned_parse --sawc sawc/sawc.py
```

Use a Python environment containing sawc's dependencies, or pass
`--sawc-python /path/to/python`. Compiler invocations have a separate 180-second
timeout. The initial lane covers nine agreement cases and one explicitly
checked known divergence: String receiver snapshot evaluation permits an
overlapping borrow that Saw rejects. SL-260 tracks this existing M8/M12 gap;
the diagnostic-checked ledger lives in `test_minivm.py`. This is initial coverage,
not a claim of parity across the entire accepted subset.

See [DESIGN.md](DESIGN.md) and [M1_NUMBERS.md](M1_NUMBERS.md) for the instruction
schema and semantics. [LEXER_DEPENDENCIES.md](LEXER_DEPENDENCIES.md) tracks the
remaining dependencies needed to compile the existing lexer with this prototype.
The fixtures include the lexer's actual `TokenKind` declaration, `hex_value`,
`keyword_kind`, `suffix_width`, and String-backed `Lexer.advance`. Source is
split into `frontend.saw`, `model.saw`, `verify.saw`, `vm.saw`, `llvm.saw`, and
`main.saw`. The verifier checks structural indices and types; initialization
is established by the frontend, so this is not a loader for untrusted bytecode.

This is a correctness experiment. Linear name lookup, heap-allocated slot
vectors, deep copies in the interpreter, and one LLVM block per instruction
favor simplicity over speed. Allocation failure can still trigger Saw's
`try!` behavior. The production compiler and lexer are unchanged.
