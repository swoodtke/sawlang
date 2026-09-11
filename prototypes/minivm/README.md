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

The LLVM path targets a 64-bit Unix C ABI (`printf`, `puts`, `exit`); validation
uses Apple clang on arm64 macOS. Clang is an external validation/compilation step,
not a dependency of the interpreter or text emitter.

## Supported source

```saw
func factorial(n: Int32) -> Int32 {
    if n <= 1 {
        return 1
    } else {
        return n * factorial(n - 1)
    }
}

func main() {
    print(factorial(5))
}
```

Single-file programs support `Int32`, `Bool`, functions, positional calls,
recursion, `let`/`var`, assignment, lexical scopes, statement `if`/`else` and
`while`, explicit returns, and scalar printing. Arithmetic is checked; signed
division truncates toward zero. Overflow and division by zero print an error
and exit with status 1. Boolean conditions require `Bool`.

Newlines separate statements. Omit the result annotation for Void functions;
`main()` must take no arguments and return Void. Value-returning functions need
explicit returns. There are no imports, strings, collections, references,
generics, methods, implicit value tails, or concurrency in the accepted subset.
Semicolons and logical `&&`/`||` are also outside this initial subset.

The VM defaults to a shared budget of 1,000,000 instructions and a maximum call
depth of 128. Override the budget with `run FILE --budget N`. These limits apply
only to VM execution; native code uses the host call stack and has no budget.

## Validation

```sh
python prototypes/minivm/test_minivm.py --binary .build/minivm/minivm
```

The harness compares VM execution and clang-compiled IR with explicit expected
outputs and statuses, checks rejected programs, and exercises VM limits. It
uses temporary files and 30-second subprocess timeouts. Initial validation passed
all 43 cases, including native execution at both `-O0` and `-O2`.

See [DESIGN.md](DESIGN.md) for the instruction schema and semantics. Source is
split into `frontend.saw`, `model.saw`, `verify.saw`, `vm.saw`, `llvm.saw`, and
`main.saw`. The verifier checks structural indices and types; initialization
is established by the frontend, so this is not a loader for untrusted bytecode.

This is a correctness experiment. Linear name lookup, heap-allocated slot
vectors, deep copies in the interpreter, and one LLVM block per instruction
favor simplicity over speed. Allocation failure can still trigger Saw's
`try!` behavior. The production compiler and lexer are unchanged.
