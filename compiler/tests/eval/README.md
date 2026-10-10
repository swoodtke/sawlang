# compiler/tests/eval: the constant evaluator's corpus

The corpus the constant evaluator (`compiler/eval`, package `saweval`,
SL-452) is held to. This file specifies `sawc2 eval`'s records and dump, the
positions the evaluator covers, and the rules it refuses by.

```
eval/
  README.md        this specification
  eval_lane.py     the lane compiler/tests/run.py runs
  golden/          NAME.saw, a program, and NAME.eval, its expected record
  refuse/          RULE.saw or RULE.VARIANT.saw, a constant refused by RULE
```

## The evaluator

SL:architecture §3.10 rules that a MIR interpreter is the compile-time
evaluator, and that the bootstrap slice builds it scoped to the slice's
constant positions, as one mechanism from the start. It covers four
positions, each a MIR function of its own (`compiler/tests/mir/README.md`):

- a `static`'s initializer;
- a raw-backed enum case's value;
- an `@align` argument;
- a `static_assert`'s condition, which must evaluate `true`.

Const-generic arguments, array lengths and repeat counts are folded by
typecheck's other folder, `build_const`, and have no MIR body yet; SL-457
owns lowering them to MIR and evaluating them here.

The evaluator runs the MIR as it would run, at the target's integer widths:
integer and `Bool` literals (a literal is written at the type its expression
adopts, and a negated literal is one constant, so `-128` is an `Int8`), an
integer type's `max` and `min`, the arithmetic, wrapping, bit and shift
operators, comparisons, `not`, `&&` and `||` as the branches MIR makes them,
casts, widenings and adoptions between integer types, a type alias's
construction (`Byte(65)`, the identity at its underlying type), payload-free enum cases
(read as their raw values where they adopt an integer type), and reads of
other statics and raw-backed cases, evaluated once each, before or after the
reader in the source. Arithmetic is typed: each operation runs at its
operands' type through `sawtypecheck.src.arith`, the rule typecheck's fold
follows too. Calls, loops, aggregates, references and every other construct
are outside it.

The value of every constant position is a side table, `EvalProgram.values`,
indexed by MIR function, which later stages read.

## `sawc2 eval`

```sh
.build/sawc2 eval (--dump | --check) [--notes] [--std-root DIR]
                  [--module-path NAME=DIR]... [FILE | @LIST]...
```

Each FILE is the entry of its own program, resolved, type checked, lowered to
MIR and its constants evaluated. The flags are resolve's. Each entry's record
starts with `FILE<TAB>path` and holds, in order:

- every line `sawc2 mir --check` prints for it (`compiler/tests/mir/README.md`);
- one `ERROR<TAB>rule<TAB>file:line:col<TAB>message` line per refusal the
  evaluator makes, in the order it evaluates, at the constant's expression;
- one `INVARIANT<TAB>module<TAB>message` line per problem the evaluator's
  verifier finds;
- with `--dump`, each lowered module's constants: `module IDENTITY`, then a
  line per constant position, in typecheck's order, `NAME: TYPE = VALUE`, or
  `NAME: TYPE (no value)` when its evaluation was refused or read a refused
  constant. NAME is its MIR function's (`static`, `raw`, `align`,
  `static_assert`). VALUE is an integer in decimal, an unsigned one past
  `Int.max` included, `true` or `false`, or a case's identity.

The exit code is 1 when any program has a refusal, 2 on a usage failure, and 0
otherwise.

## Refusals

Each refusal is reported once, at the constant whose evaluation met it. One met
while evaluating a static another constant reads names the constants evaluated
to reach it, outermost first (`; evaluated for static m.A`); the reader is
left with no value and no refusal of its own. A refusal names a static, a raw
case or an `@align` argument by its MIR function's name, and a `static_assert`,
which has none, by its condition's position: `the static_assert at 12:16`.

| rule | refuses | fixture |
|---|---|---|
| `eval.overflow` | an operation whose result its type cannot hold | eval.overflow |
| `eval.shift-range` | a shift count negative, or at or past the shifted type's width | eval.shift-range |
| `eval.divide-by-zero` | a division or remainder by zero | eval.divide-by-zero |
| `eval.not-fit` | a value converted, adopted or written as a literal at a type that cannot hold it | eval.not-fit |
| `eval.cycle` | a static whose value depends on itself, naming the statics around the cycle; an evaluation past the step budget, naming the statics under way | eval.cycle |
| `eval.assert` | a `static_assert` whose condition is `false` | eval.assert |
| `slice.not-yet` | a construct outside the evaluator: a call, a loop, an aggregate, a part of a value, a mutable static, a static whose initializer this program does not lower | slice.not-yet |

Typecheck's fold refuses the faults it meets first, at a constant expression
where it adopts an integer slot; the evaluator meets the rest, such as one
behind a cast or `Int.max`, which the fold does not range-check.

## The verifier

The evaluator's verifier checks, per lowered module:

- every constant position was evaluated, and one that has a value has its
  position's type;
- typecheck's fold (`compiler/typecheck/src/fold.saw`), which computes the
  same constants from the tree, agrees with the evaluator on every one: the
  same value at the same type, or the same fault. A constant whose value is an
  enum case is skipped, since the fold has no form for one.

## The lane

`eval_lane.py` runs one `sawc2 eval` process per group and checks that each
golden program's record equals its `.eval` file byte for byte (`--write`
rewrites them), that each refusal fixture is refused first by the rule its
header names at its position (`--fill` writes a `// refuses: TODO` header),
that every rule in `eval_rules` (`compiler/eval/src/report.saw`) has a fixture,
that no golden or fixture record carries an `INVARIANT` line, that the
compiler's own source evaluates whole with no refusal and no invariant, and
that over tests/corpus/ the evaluator's verifier finds nothing: the agreement
with typecheck's fold is a gate there. It prints how many of the compiler's
constants it evaluated, and how many of the corpus's have a value.
