# Minimal Saw compiler experiment

This is a disposable experiment, not the self-hosting port or a change to Saw's
language contract. No Sawtracker submission is part of this work. The primary
agent owns this design, interfaces, integration, and review; Sol implements
bounded modules against the interfaces. All implementation is synchronous Saw.

## Goal and acceptance

Compile a small Saw subset once into a shared instruction representation. Execute
that representation in a VM, or emit textual LLVM IR from it. External clang may
verify, compile, and link the emitted text; the prototype contains no LLVM binding.
Positive fixtures must produce identical stdout and exit status through both
paths, with explicit expected outputs as a third oracle. Compile-time rejection
fixtures must have a located error. Runtime overflow and division-by-zero fixtures
must fail consistently. This does not claim the prototype can compile itself.

The original Int32-only contract below records the baseline.
[M1_NUMBERS.md](M1_NUMBERS.md) supersedes its numeric types, operations, default
literal type, and signed-minimum remainder behavior.
[M2_RECORDS.md](M2_RECORDS.md) adds value records and flattened call/result layouts.
[M3_SCALAR_CONTROL.md](M3_SCALAR_CONTROL.md) adds short-circuit operators, compound
assignments and module constants. [M4_ENUMS.md](M4_ENUMS.md) adds nominal
payload-free enums and exhaustive statement match. [M5_VALUE_CONTROL.md](M5_VALUE_CONTROL.md)
adds implicit tails and value-producing branches.

## Source contract

* One source file; reuse selfhost/lexer via --module-path sawlex=selfhost/lexer.
* Functions: func name(p: Int32, flag: Bool) -> Int32/Bool { ... }, or omitted
  return type for Void. Exactly one main() returning Void; no parameters there.
* Explicit return statements. No implicit value tails, overloads, imports,
  methods, generics, closures, references, arrays, heap objects, or concurrency.
* let/var with initializer, optional Int32/Bool annotation; assignment only to
  mutable locals. Lexical block scopes; no duplicate declaration in a scope.
* Statement if/else and while with Bool conditions, nested blocks, print(expr),
  call expression statements (Void only), return expr or bare return for Void.
* Decimal Int32 literals, true/false, names, parentheses, positional function
  calls; unary minus/not; + - * / %, == != < <= > >=. Comparisons of integers;
  equality also supports Bool. No implicit Int32/Bool conversions. No &&/|| yet.
* Left-to-right operand and argument evaluation, forward calls and recursion.
  All non-Void functions must return on every reachable path. An implicit Void
  return at end is allowed. Reject unsupported tokens rather than ignoring them.
* Newlines separate statements; newlines in parentheses are whitespace. Semicolons
  are rejected. Braces may close a final statement without an intervening newline.
* Int32 means signed 32-bit everywhere. Ordinary arithmetic traps on overflow.
  Host Saw Int is 64-bit for this experiment: i32 operands' add/sub/multiply fit
  the host intermediate, followed by [-2147483648,2147483647] validation. Divide
  truncates toward zero; zero divisor traps; min/-1 division traps as overflow.
  Remainder min%-1 is zero (no LLVM poison: widen to i64 before srem).
  Literal -2147483648 must work; positive 2147483648 is rejected. Decimal suffix
  i32 may be accepted; all other suffixes/bases outside scope are rejected.

## Shared representation (src/model.saw is authoritative)

Program is a vector of FuncIR plus main function index. FuncIR owns its name,
parameter types, result type, slot types, and linear instruction stream. Parameters
occupy slots [0, parameter count). Other slots hold locals and expression results.
All scalar runtime cells are signed host Int, Bool encoded 0/1. No pointers/heap.
Each call allocates a fresh frame; recursive calls never share slots.

Instruction fields are intentionally uniform for the experiment. Op determines
which fields are meaningful; the constructor initializes unused scalar fields to
-1 except immediate=0. The verifier checks meaningful operands only; unused
fields are ignored by both execution paths.

| Op | Fields and behavior |
|---|---|
| Const | dst, immediate; slot type is I32 or Bool |
| Copy | dst = a, same type |
| Add/Sub/Mul/Div/Rem | dst = a op b, all I32, checked |
| Neg | dst = -a, I32, checked |
| Not | dst = !a, Bool |
| Eq/Ne | dst Bool, a/b same non-Void type |
| Lt/Le/Gt/Ge | dst Bool, a/b I32 |
| Jump | target is instruction index in current function |
| Branch | a Bool; true -> target, false -> next instruction |
| Call | target function index, args slot indices; dst=-1 for Void |
| Print | a scalar, output decimal or lowercase true/false plus newline |
| Return | a return slot or -1 for Void |

Except Jump/Branch/Return, execution continues to the next instruction. Branch
targets always point to real instructions. There must be no reachable falloff.
Frontend resolves names/types and validates initialization before emitting IR;
integration verification additionally checks structural indices/types and calls.
Slots may be reassigned (not SSA); LLVM uses one alloca per slot and one basic
block per instruction. Thus both backends consume exactly the same CFG, with no
phi construction or second control-flow lowering. LLVM can optimize externally.
Emit function names from their numeric IDs, never unsanitized user identifiers.

## Interfaces and file ownership

* model.saw: primary-owned shared schema, ProtoError, constructors.
* frontend.saw: Sol frontend task. compile_source(String) -> Result<Program,ProtoError>.
  Signature scan first, then parse/typecheck bodies and lower directly to IR; a
  second public AST is unnecessary for this small prototype. Bound parser depth.
* vm.saw: Sol VM task. execute(&Program, budget: Int) -> Result<Void,ProtoError>.
  Explicit call stack preferred; impose max depth 128 and a shared instruction
  budget (default 1000000). These are VM execution limits, not language rules.
* llvm.saw: Sol backend task. emit_llvm(&Program) -> Result<String,ProtoError>.
  Scalar slots map to i64 cells in LLVM as well; I32 operations use i64 intermediates
  and bounds checks, Bool branch converts canonical i64 to i1. Direct native
  function calls use i64 scalar arguments/results, void for Void. main wrapper
  returns i32 0. Declare printf/puts/exit for output and trap support. No optimizer,
  LLVM library calls, target structs, FFI generality, or runtime allocation.
* main.saw, verify.saw, README.md: primary integration ownership.
* test_minivm.py, examples/: Sol test implementation, reviewed by the primary.

Runtime error messages are exact: `runtime error: integer overflow`,
`runtime error: division by zero`, `runtime error: instruction budget exceeded`,
`runtime error: call depth exceeded`. VM returns ProtoError; CLI prints its message
once and exits 1. LLVM trap helpers print the same line and exit 1. No extra output
on successful emit-llvm: stdout is only IR. CLI: minivm run FILE [--budget N],
minivm emit-llvm FILE. Usage/I/O/parse/type errors exit 1 with a message. Source
errors format `FILE:line:col: message`; runtime errors omit source coordinates.

## Testing and review sequence

1. Compile each new module with existing Python sawc, reusing the venv. No changes
   to sawc/, std, existing lexer, existing gates, or numbered designs are intended.
2. Verify arithmetic, precedence, shadowing, mutation, branches, loops, calls,
   forward references, recursion, early returns, and evaluation order with stdout
   oracles; include each backend's error and nonzero-exit path.
3. Reject unknown names/types/operators, malformed syntax, immutable assignment,
   argument/return type mismatch, missing return, and unsupported features.
4. Emit .ll, compile with clang, run with a timeout, compare VM/native/expected
   outputs. VM budget tests are VM-only; native nontermination uses process timeout.
5. Primary reviews code and independently adds adversarial tests. Do not claim
   completion based on two engines agreeing without expected-output checks.

Prototype allocation failure may retain existing try! behavior. Compiler-language
bugs encountered must be reported to the primary with repro evidence; do not change
the production compiler or create tracker entries. Record reviewed milestones as
separate commits on the prototype branch.
