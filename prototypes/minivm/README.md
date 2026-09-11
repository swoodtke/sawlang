# Saw compiler / VM prototype

A small compiler written in Saw, with two consumers of the same typed instruction
stream: an interpreter and a handwritten textual LLVM IR emitter. The existing
Saw lexer is reused. There are no LLVM library calls in this prototype.

The existing Python compiler builds the prototype executable. Once built, it
parses, checks, lowers, interprets, and emits IR without invoking Python. It
cannot yet compile its own source.

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
or nested structs, with
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
There are no imports, collections, generics, or concurrency in the
accepted subset.
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
methods also accept temporary receivers. String fields/statics, interpolation
and concatenation remain unsupported. Both engines retain/release owning slots
and check for live allocations after successful execution; see
[M8_OWNED_STRINGS.md](M8_OWNED_STRINGS.md).

The VM defaults to a shared budget of 1,000,000 instructions and a maximum call
depth of 128. Override the budget with `run FILE --budget N`. These limits apply
only to VM execution; native code uses the host call stack and has no budget.

## Validation

```sh
python prototypes/minivm/test_minivm.py --binary .build/minivm/minivm
```

The harness compares VM execution and clang-compiled IR with explicit expected
outputs and statuses, checks rejected programs, and exercises VM limits. It
uses temporary files and 30-second subprocess timeouts. The first eight milestones
pass all 277 cases, including native execution at both `-O0` and `-O2`.

Independent representation checks live in `tests/numeric_contract.saw`,
`tests/record_contract.saw`, `tests/enum_contract.saw`,
`tests/reference_contract.saw`, `tests/receiver_contract.saw`, and
`tests/string_contract.saw`; build and run them
with the Python compiler.
Use `--section numbers`, `--section records`, `--section control`, or
`--section enums`, `--section values`, `--section references`, or
`--section receivers` or `--section strings` for an isolated
integration gate.

See [DESIGN.md](DESIGN.md) and [M1_NUMBERS.md](M1_NUMBERS.md) for the instruction
schema and semantics. [LEXER_DEPENDENCIES.md](LEXER_DEPENDENCIES.md) tracks the
remaining dependencies needed to compile the existing lexer with this prototype.
The fixtures include the lexer's actual `TokenKind` declaration and `hex_value`
helper. Source is
split into `frontend.saw`, `model.saw`, `verify.saw`, `vm.saw`, `llvm.saw`, and
`main.saw`. The verifier checks structural indices and types; initialization
is established by the frontend, so this is not a loader for untrusted bytecode.

This is a correctness experiment. Linear name lookup, heap-allocated slot
vectors, deep copies in the interpreter, and one LLVM block per instruction
favor simplicity over speed. Allocation failure can still trigger Saw's
`try!` behavior. The production compiler and lexer are unchanged.
