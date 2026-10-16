# SL-722: Float in sawc2's backend, a staged plan

Planning sweep p722, Oct 16. Read-only: no tracked file changed.

- **Measured at:** main `64f7f4caf`. The baseline is `compiler/tests/corpusdiff/corpus_diff.tsv`; the six rows it changed since `f433ef5cb` are SL-717's, and none is in this census.
- **sawc2:** `.build/sawc2-stage2`, rebuilt by `compiler/tools/build.py` at the start of the sweep (key `45a72be5…`). The binary on disk was older than 59 changed source files.
- **Stage 0:** `./.venv/bin/python sawc/sawc.py`.
- **Evidence files:** every probe is under `.build/scratch/p722/`. The probe programs are in `probes/`, the transcripts in `probes.txt` and `typecheck_probes.txt`, and the census tools are `probe_census.py`, `probe_statics.py` and `probe_run.py`.

## 1. The refusal census

There are 757 refused rows in all. The table counts the rows whose **first** refusal is Float-related or is one of SL-722's other four refusals. A program reports only its first refusal, so these counts are lower bounds on demand.

### 1a. Float-related first refusals: 19 rows, plus 2 hidden behind std.net

| refusal (stage, key) | rows | programs |
|---|---|---|
| llvm `a Float constant, X, is not in the backend slice yet` | 3 | primitive_conformances, send_sync_bounds, tuples_advanced |
| llvm `an operator on this type is not in the backend slice yet` (Float `/`, `<`, `==`) | 2 | comparable_float_nan, equatable_nan |
| mono `synthesized Printable.format … on Float … the backend lowers no Float operation` | 10 | compound_assign, coro_ref_param_compound_assign, format_args_print, format_into_builtin_alloc_free, number_literal_member_access (via `std/prelude.saw:150`, `Printable.to_string`'s default), primitive_extension_self_is_its_own_type, string_interpolation, tuple_index_member_access, variables, **wrapping_requires_integers** (an `EXPECT: error` test, see finding F1) |
| mono `synthesized Comparable.compare … on Float` | 1 | comparison_requirement_concrete_receiver |
| typecheck `member.unknown` / `call.no-match` (std.float and numeric's Float half are not in `std/`) | 3 | float_methods (`abs`), string_to_float (`to_float`), float_text_format (`StringBuilder.append(value: Float)`) |
| resolve `no module std.net` (the `IoError` import), then std.float | 2 | float_text_parse_vectors, float_text_shortest_vectors |

Other Float users whose first refusal is something else:
- generic_primitive_bounds: `Equatable` on `(Int, Int)` comes first. It later needs `print(run<Float>(2.0))`.
- offload_signature_shapes: coro refuses first. It uses `extern pow`, Float `==` and interpolation.
- json_value_accessors: refused with no module `std.json`.

All 23 rows refused with `no module std.json` are blocked on the Float side too, because json reads its numbers through std.float. The json port itself is SL-596 S11.

Two Float rows already pass, and they must stay passing: bitwise_requires_integers and float_integer_operand_mix.

### 1b. SL-722's other four refusals: 41 rows, none of them Float

| refusal | rows | what it is |
|---|---|---|
| `a static whose value is not an integer or a Bool` | 24 | **No row involves a Float static.** No tracked `.saw` file declares one (checked over `tests/corpus`, `examples`, both stds, `libs`, `blade`). By kind (`probe_statics.py`): 8 rows need only a bare static (zerofill, which is SL-685's subject); 13 need only an aggregate initializer (struct, array literal, `[v; N]`, struct holding `Atomic`); 3 need both (slab_basic, kernel_slab_idiom, any_box_slab). |
| `this conversion is not in the backend slice yet` | 8 | **None is Float.** Six are `E.from(raw:)`, whose MIR is `_1 = from(raw:)(… as E?)` and has no arm in `convert_into`: backed_enum_extension_param, crossmodule_embed_type_name_head, d144_private_type_identity, enum145_raw_backed, enum_raw_value_takes_const_expression, generic_enum_raw_backing_keeps_values. Two project an alias of a memory-layout type: cast_distinct_string_underlying (`n as String`) and conformance/V65_forwarding_cast_is_tier_blind (`a as Arc<Res>`, a conformance row). |
| `the constant X` | 9 | Eight are a const generic `N` read as a value: const_generic_arg_notations, const_generic_basic, const_generic_enum_and_function, const_generic_infer_length, generic_default_init, generic_instance_const_parameter_value, init_fallible_result_shapes, init_receiver_return_spellings. SL-548, which is open, owns these. One is `#line` in a suspending function (source_location_suspending); its sibling source_location_literals is refused with `a memory constant`. |
| `indexing an array or a slice` | 0 | Fixed-array indexing landed with SL-710 (probe `q04_array_index` builds and runs). `indexing a slice` is still refused, but no corpus row reaches it. |

### 1c. Which gap blocks which std module

| module | blocked by (probe evidence) |
|---|---|
| **std.float** | I copied `sawc/std/float.saw` into a user module (`probes/modules/sfloat.saw`, programs `r01`/`r03`). It **resolves, typechecks, lowers to MIR, borrow-checks and drop-elaborates clean under sawc2.** The backend has only two gaps: (1) Float `!=` in `is_nan` (sfloat.saw:1402); (2) the four aggregate static tables `FLOAT_POW5_INV_SPLIT [UInt64; 584]`, `FLOAT_POW5_SPLIT [UInt64; 652]`, `FLOAT_POW5_TRUNCATED [UInt64; 1302]` and `FLOAT_POWER_TABLE [Int; 9]` (eval: `an aggregate in static … is not evaluated`; backend: refusals at sfloat.saw:1586, 1988 and 2314). It needs no Float literal, no Float arithmetic and no conversion. `to_bits`/`from(bits:)` reinterpret through a pointer, which already works (probe `s01`). |
| **numeric (Float half)** | Float values in the backend (constants, arithmetic), the libm externs (the C ABI with `double` already works, probe `s07`), and `-lm` on Linux (finding F5). |
| **json** | std.float, then SL-596 S11's own gaps (`any Trait` calls, `Vector.each` and others). |
| **fixedbuf** | **Not Float.** `N` as a value (SL-548), `StringBuilder.rebind`, `append(value: UInt)` (probe `r02`). |

## 2. What exists in sawc2 today

| layer | state |
|---|---|
| layout (`compiler/target/src/layout.saw`) | `TargetKind.Float`, 8 bytes. The value type is `double` (`llvm/src/module.saw`), and `ll_is_scalar` includes Float. |
| typecheck | `Float` is builtin. A float literal types as Float through `peel(…, TcClient.Floating)`. Arithmetic, comparison and unary `-` are admitted. `%`, shifts, bit operators, `~` and `not` are refused (they match Stage 0). Mixed Float/Int operands are refused with `type.mismatch`. **It accepts `&+`/`&-`/`&*` on Float (F1) and `as` between Float and every integer type (F2).** |
| MIR | `MirConstKind.Float` holds the literal's text. Operators are `Binary`/`Unary` rvalues. A generic ordering operator lowers to `compare(...)` plus an Ordering test (`le`: `Ne(compare, Greater)`). |
| eval | No Float value. `EvalKind` holds Integer, Boolean, Case, Unit, Cell and Missing. A Float static is refused with `a constant of a type the evaluator does not hold`. |
| mono | THE SCALAR HOOK TABLE (`mono/src/glue.saw` `scalar_refusal`) refuses every Floating cell, `copy()` included, with "the backend lowers no Float operation". |
| llvm | `const_value` refuses a Float constant. `binary_into`/`unary_into` refuse a non-Int, non-Pointer layout. `comparable_bits` refuses Float, so `==` on a struct, tuple or Optional holding a Float is refused (s11–s13). `convert_into` refuses every non-Int pair. `static_global` lowers Int, Bool and `Atomic(<int>)` only. |

**What already works** (built by sawc2, bit-identical to Stage 0; probes `s01`, `s04`–`s07`, `s09`, `s10`): a Float value obtained without a literal or operator can be bound, moved and copied, and stored in a struct field, an array, a `Vector`, an Optional and an enum payload. It can be passed to and returned from an `extern "C"` function, and reinterpreted to and from `UInt64` through a pointer.

### The probe verdicts (sawc2 / Stage 0)

| probe | Stage 0 | sawc2 first refusal |
|---|---|---|
| p01 `let x = 1.5` | builds | Float constant `1.5` |
| p02 arithmetic, p20 compound assignment, p04 unary `-` | builds | Float constant |
| p03 compare / NaN / `-0.0 == 0.0` | `false true false false true true true true` | operator on this type (`0.0 / 0.0`) |
| s02 arithmetic, no literal | the bits | operator on this type |
| s03 comparison, s08 compound assignment, no literal | builds | operator on this type |
| p05 `n as Float`, p43 `UInt8 as Float` | **refuses** `cannot cast` | typecheck **accepts**; backend `this conversion` |
| p06 `f as Int`, p38 `f as UInt8` | **refuses** `cannot cast` | typecheck **accepts** (see p40 `typecheck --check` rc=0) |
| p07 `Float.from(n)` | refuses (reaches `from(bits:)`) | `member.unknown` |
| p36 `let f: Float = n`, p37 `Int.from(f)`, p44 `Float(n)` | refuses | refuses (matches) |
| p08 field, p10 Vector, p22 Optional, p23 function, p27 array, p28 enum payload, p29 closure, p31 tuple, p19 extern, p47 default parameter | builds `true` | Float constant |
| p09 `static PI: Float = 3.14`, p24 `-1.5`, p45 `-0.0`/`0.5`/`0.1` statics | builds; bits `0x8000…`, `0x3FE0…`, `0x3FB999999999999A` | operator, or `a static whose value is not…` |
| p35 `static SUM: Float = 1.0 + 2.0` | **refuses** (`must be initialized by a compile-time constant`) | typecheck accepts; eval `slice.not-yet`; backend refuses at the use |
| p46 Float struct/array statics | builds | operator on this type |
| p11 `"{f}"`, p12 `print(f)` ×8, p17 `to_string` | `0.30000000000000004`, `1.0`, `-0.0`, `inf`, `nan`, `100.0`, `0.001`, `1.2345678901234567e+19` | mono Format on Float |
| p13 `print("{}", f)` | `x = 2.5` | Float constant |
| p14 generic `>`, p26 generic `==`, p30 `compare` on NaN | `true`; `true false`; `Equal` | mono Compare / Equals on Float |
| p15 `Set<Float>` with `0.0`, `-0.0`; p34 hash ±0 | `1`; `true` | mono Equals / Hash on Float |
| p16 `abs`/`sqrt`, p18 `to_float` | builds | `member.unknown` |
| p21 `%` on Float | refuses | refuses (matches) |
| p25 bits of `0.1`, `-0.0`, `0.30000000000000004` | `4591870180066957722`, `9223372036854775808`, `4599075939470750516` | Float constant |
| p32 min-subnormal literal (324 characters) | `true` | Float constant |
| p41 a literal of 1 followed by 400 zeros, and `0.` followed by 400 zeros and a 1 | **builds**; `inf > 1.0` and `== 0.0` (SL-68: the oracle is known wrong) | typecheck accepts (no range rule) |
| s11/s12/s13 `==` on a struct, tuple or Optional holding a Float | `false true` (NaN unequal; `+0 == -0`) | refused: `the operator == on … only == and != on integers, …` |
| s15 synthesized `Comparable` with a Float member | `false false Equal` | mono: synthesized compare on a struct (not a Float gap) |
| g01 generic `<=`/`>=`/`<` on NaN | `false false false false false true false` | mono Compare on Float; see **Q3** |
| t01/t02 `&+`/`&*` on Float | refuses `wrapping operator … requires integer operands` | **accepts** (F1) |

**LLVM's decimal parser agrees with Stage 0 bit for bit.** `llvm_decimal.ll` and `llvm_edges.ll`, compiled with the manifest's `/usr/bin/clang` 21, produce the same bits as Python's `float()` (`probe_bits.py`) for `0.1`, `0.30000000000000004`, `3.14`, a 336-character subnormal, `12345678901234567890.0`, `-0.0`, and the ties-to-even pair `9007199254740993.0` → `…000` and `…995.0` → `…002`. LLVM silently turns an overflowing decimal into `inf` and an underflowing one into `0` (`llvm_over.ll`), just as Stage 0 does.

## 3. The semantics, cell by cell

| construct | spec / ruling (quoted) | Stage 0 does | sawc2 needs | status |
|---|---|---|---|---|
| **constant materialisation** | SL:architecture §3.1: "literals keep their text … float text converts to a value through the bit-exact routine of design 253". GRAMMAR §2.1: "`FLOAT ::= decimal-run "." decimal-run`" with `_` separators, "There is no exponent and no suffix." | Python `float()` (correctly rounded, ties-to-even), emitted as llvmlite's hex `double` | correctly rounded binary64 bits from the text with `_` removed; emit `double 0x%016X` | **DECIDED** (§3.1). Emitting the decimal text to LLVM would also match (§2), but it gives eval no value and leaves the range check nowhere to live. |
| literal out of range | SL-68's title: "Diagnose unrepresentable float literals instead of producing infinity or zero" (an imported TODO record, closed as "oracle known wrong", aspect `literal.float.range`). SL-393: "float-literal underflow: is a literal that rounds to 0.0 or to a subnormal an error? (SL-68)", listed under "Rules the spec is silent on". | silent `inf` / `0.0` | a diagnostic, if ruled | **OPEN (Q2)** |
| `-` on a Float literal | GRAMMAR has no negative literal; unary `-` applies | `fneg` (`-0.0` → `0x8000…`, p25) | `fneg` or a fold that sets the sign bit. Never `fsub 0.0, x`, which yields `+0.0` for `x = 0.0`. | **DECIDED** (IEEE negation; Stage 0 bits) |
| arithmetic `+ - * /`, compound assignment | spec: "**Float arithmetic** is untouched: IEEE semantics (inf/nan), no overflow trap." | `fadd/fsub/fmul/fdiv` | the same | **DECIDED** |
| `%`, shifts, bit operators, `~`, `not` on Float | spec: wrapping operators are "**integer operands only** (a `Float` operand is a type error)"; bit operators and shifts take integers | refuses | already refuses, except the wrapping operators (F1) | **DECIDED** |
| `==` / `!=` | spec: "**Float keeps IEEE semantics** — `NaN != NaN`"; "`!=` is always the negation of `==`"; "primitives keep direct `icmp`/`fcmp`" | `fcmp oeq`, `!=` = `not oeq` | `fcmp oeq` / `fcmp une` | **DECIDED** |
| `< <= > >=`, concrete | spec: "**Float NaN:** a `NaN` is unordered, so every ordering operator involving it is `false` (matching the primitive `fcmp`)" | `fcmp olt/ole/ogt/oge` | the same | **DECIDED** |
| `Comparable.compare` | spec: "in a three-way `compare`, an unordered pair yields `Equal` (there is no total order over NaN — documented)" | `lt ? Less : (gt ? Greater : Equal)` (`_emit_float_compare`); `+0.0` vs `-0.0` is `Equal` | the Float cell must test `<` then `>` and fall to `Equal`. The integer builder (`<`, then `==`, else `Greater`) would answer `Greater` for NaN. | **DECIDED** |
| `<=` / `>=` in a **generic** body over NaN | the spec says both "`a <= b` is `!= .Greater`" (the desugaring) and "every ordering operator involving it is `false`". The two contradict each other for NaN. | **false** (each instance lowers to `fcmp`, probe g01) | sawc2's MIR desugars to `compare != Greater`, so it would answer **true** | **OPEN (Q3)** |
| `Hashable.hash` | spec: "`Float` normalizes `-0.0`/`+0.0` so they hash alike; NaN bit patterns are not normalized" | `f == 0.0 ? 0 : bitcast(f)`, then `write_int` | the same word, through `write_int(n:)` | **DECIDED** |
| `copy()` | Float is in the Copy tier | bitwise | bitwise; today the hook table refuses it too | **DECIDED** |
| `==` on a struct, tuple or Optional holding a Float | spec (design 32): memberwise `&&`; the Optional rule | memberwise `fcmp oeq` (s11–s13) | `equal_at` gains a Float arm. `comparable_bits` must admit Float, which is no longer a bit comparison. | **DECIDED** |
| `Printable` (`print`, `"{}"`, a format argument, `to_string`, `format(into:)`, panic/assert) | spec §Float ↔ text: "Every position that shows a `Float` produces those bytes … There is one formatter, so the six agree." The layout rules, plus "a NaN is `nan` and the infinities are `inf` / `-inf`". Oracle: `tests/float_vectors/` ("asserted BIT-EXACT"). | std.float's `StringBuilder.append(value: Float)`, which the codegen calls through `__float_to_chars` | the Floating row's Format cell calls std.float's `append(value: Float)`. That needs std.float in `std/`. | **DECIDED** |
| `String.to_float`, `to_bits`, `from(bits:)`, `is_nan` and the rest | spec table §Float ↔ text; "available without an import" | std.float | port std.float | **DECIDED** |
| `abs floor ceil round sqrt min max` | spec §Numeric: "lower to the libm math functions and follow **IEEE** semantics"; "`round()` (half away from zero)" | libm externs; `-lm` on non-Apple links (`sawc.py` `math_libs`) | port the Float half; the driver links `-lm` off Apple | **DECIDED** |
| `Int as Float`, `Float as Int`, `from`, `from(truncating:)` | spec §Integer Conversions: "**Float** conversions are unchanged." DF-276b / SL-69: "there is NO `Int` -> `Float` conversion in ANY spelling … Wants a design, not a patch — the rounding mode of a wide `Int` -> `Float` is a ruling, and so is whether the conversion is `as`, `from`, or both." Design 173 decision 3 (an "APPROVED direction", but its shapes were "recommended, veto-able before dispatch", and its unit 3 was never built): "`i as Float64` exact-or-panic (53-bit rule), `f as Int` panics on NaN/infinity/out-of-range/fractional part — `Int.from(f)` Optional twin, `Int.from(truncating: f)` truncates toward zero". | refuses every spelling (`cannot cast`) | until a ruling, refuse as Stage 0 does (F2); after it, lower what is ruled | **OPEN (Q1)** |
| `m as Float` on `type Miles = Float` | spec: "`let raw: Float = m as Float`" (a projection) | builds | the alias projection, which works once constants do | **DECIDED** |
| `static X: Float = <literal>` or a negated literal; Float members of struct and array statics | spec §The constant grammar lists "integer and `Bool` literals" and **no float literal**. Statics tier 2: "struct literals, fixed-array literals … built out of those" | accepted; bit-exact (p45, p46) | eval holds the Float's bits (the literal funnel); the backend writes a `double` member | **DECIDED in Stage 0's behaviour; the spec is silent (Q4)** |
| `static X: Float = 1.0 + 2.0` | §3.10 "**Constant arithmetic is ordinary typed arithmetic** (Ruled, Sep 25) … The evaluator runs the same MIR as run-time code", but "The bootstrap slice builds the MIR interpreter scoped to exactly those, straight-line arithmetic with no calls" | refuses | the compiler cannot compute IEEE arithmetic without a soft-float, because the seed has no Float | **OPEN (Q4)** |
| statics of other non-integer types | spec §statics tier 1 (bare = zero, `ZeroInit`) and tier 2 (a constant expression "plus memberwise aggregation") | implemented | eval aggregates, backend constant aggregates, zerofill (SL-685) | **DECIDED** |

## 4. The plan: six units in dependency order

```
U1 (typecheck parity) ─────────────────────────────┐
U2 (Float values: literals, operators, ==) ─┬─ U3 (scalar hooks) ─┐
                                            └─ U4 (statics) ──────┴─ U5 (std.float, numeric, Format)
U6 (Float↔integer conversions) ── blocked on Q1; needs U2
```

U1 must land **before U5**. Otherwise wrapping_requires_integers builds once Format exists and moves to `wrong: accepts a refusal test`. U4 is independent of U2 and U3 except for its Float rows, but it shares `llvm/src/places.saw` with U2, so dispatch it after U2.

Every unit:
- writes one run-lane program per matrix row group (`compiler/tests/run/NAME.saw`, with its Stage 0 record under `stage0/`), each comparing Stage 0 bit for bit;
- states expected outcomes, and stops and reports on any mismatch;
- records `corpusdiff.py run --baseline` for the rows it moves;
- runs only its touched steps of `compiler/tests/run.py --only …`, plus `citations`.

**The matrix rule for Float rows.** Values are printed as `to_bits()` through the pointer helper, which already works (`func bits(f: Float) unsafe -> UInt64 { let v: Float = f; ((&v) as UnsafePointer<UInt64>)[0] }`), and **never a NaN's bits**: a NaN is tested with `x != x`. UNVERIFIED: a default NaN's sign differs by target (x86 produces `0xFFF8…`, arm64 `0x7FF8…`) and between LLVM's constant folding and run time. The linux lane runs x86_64.

### U1: Float typing parity (typecheck) — Opus, small

**Scope.**
- Refuse `&+`, `&-` and `&*` on Float.
- Refuse `as` between Float and any integer type until Q1 is ruled; Stage 0 says `cannot cast`.
- The mixed-operand hint (``convert one with `as` ``, t09) stops teaching `as` for a Float/integer pair.

**Funnels and entry points.**
- `operator_kinds` / `arithmetic_expr` in `typecheck/src/bodies.saw`. Today the wrapping operators fall into `TC_OPS_ARITHMETIC`, which admits numbers. Entry points: `arithmetic_expr`, `check_compound_operands`. The compound form `&+=` does not parse in either compiler.
- `cast_allowed` (its `is_numeric(from) && is_numeric(to)` arm). Entry point: `cast_expr`.

**Matrix** (a typecheck fixture per rule, plus the Stage 0 message):

| construct | Float | Int (control) | Float with Int |
|---|---|---|---|
| `a &+ b`, `a &- b`, `a &* b` | refused | accepted | refused (`type.mismatch`) |
| `x as Float` where `x` is Int, Int8, UInt8, UInt64 or UInt | refused (`type.cast`) | — | — |
| `f as Int`, `f as UInt8`, `f as Int64` | refused | — | — |
| `f as Float`; `m as Float` for `type Miles = Float` | accepted | — | — |
| the `type.mismatch` hint for `a * n` | no `as` advice for Float/Int | unchanged for Int/Int16 | — |

**Corpus moves.** wrapping_requires_integers moves `refused (mono Format)` → `pass`. The plan names no rule for Stage 0's message, so any non-gap rule passes. No other row moves; the two passing Float rows stay passing.

**Blocked by.** Nothing. If Q1 is ruled first, the cast row becomes U6's.

### U2: Float values in the backend (literals, operators, equality) — Opus

**Scope.**
- **The float literal funnel** (new): `tc_float_bits(text) -> (bits: UInt64, fault)`, design 253's exact decimal conversion (the `FloatDecimal` path of `sawc/std/float.saw`: a digit buffer shifted by powers of two, "exact by construction"). It is integer-only and needs no Ryū/Lemire table; its `[Int; 9]` table can be a function. Every compile-time literal takes this path. It strips `_`, saturates to `inf` / `0` and reports a fault.
- Its home is beside `tc_arith_literal` in `typecheck/src/arith.saw`. The compiler's own source carries no float literal (SL:hazards S20), so the seed needs no Float.
- `const_value` gains a `MirConstKind.Float` arm that emits `double 0x…`.
- `binary_into` and `unary_into` gain a `TargetKind.Float` arm: `fadd/fsub/fmul/fdiv`; `fcmp oeq/une/olt/ole/ogt/oge`; `fneg`. Compound assignment arrives as `Binary`.
- `comparable_bits` / `equal_at` gain a Float arm that compares with `fcmp oeq`.

**Funnels and entry points.**
- The literal funnel. Entry points: `LlEmitter.const_value`; `EvalProgram.constant` (U4); the typecheck float-literal check (only if Q2 is ruled).
- The backend operator lowering. Entry points: `rvalue_into` (`Binary`, `Unary`).
- Memory equality. Entry points: `memory_comparison` → `comparable_bits`, `equal_at`.

**Matrix.**
- **Constants** (bits). Values: `0.0`, `-0.0`, `0.1`, `0.30000000000000004`, `1.5`, `3.14`, `1_000.5`, `9007199254740993.0` (ties-to-even), `9007199254740995.0`, `12345678901234567890.0`, the minimum subnormal (the 324-character literal), the maximum finite value (309 digits). Positions: let, struct field, tuple element, Optional payload, enum payload, array literal, `Vector.push` argument, function argument, default parameter value (p47), `extern "C"` argument, return value, `Miles(2.5)` alias.
- **Operators** (bits or Bool). `+ - * /` on ordinary values; `x / 0.0` → inf; `0.0 / 0.0` tested with `x != x`; unary `-` on `0.0` → `0x8000…`. `+= -= *= /=`. The six comparisons over (ordinary, ±0, NaN, ±inf).
- **Equality of aggregates.** s11, s12 and s13 give `false true`.
- **Guards.** `bitwise_requires_integers`, `float_integer_operand_mix` and the p21 `%` refusal stay refused.

**Corpus moves.**

| row | from | expected after U2 |
|---|---|---|
| comparable_float_nan, equatable_nan | the operator refusal | pass |
| send_sync_bounds, tuples_advanced | Float constant | pass (they print only integers) |
| primitive_conformances | Float constant | pass or its next gap (it prints no Float) |

The run lane's `float_field.saw` loses its `// due:` line.

**Blocked by.** Nothing. The range diagnostic waits on **Q2**: the funnel reports the fault, but no rule refuses it until the ruling.

### U3: the Floating row of the scalar hook table (mono) — Opus, small

**Scope.** In THE SCALAR HOOK TABLE / FUNNEL (`mono/src/glue.saw`), the Floating row's `copy()`, `equals`, `compare` and `hash` cells are lowered; Format stays refused until U5.
- `copy()`: bitwise.
- `equals`: `==`, through U2's `fcmp oeq`.
- `compare`: test `<`, then `>`, else `Equal` (Stage 0's `_emit_float_compare`). Adopting the same order for integers is harmless, since integers are totally ordered.
- `hash`: the word is `0` when `f == 0.0`, else the bits. The bits are read through the value's address, as `to_bits` reads them, or through a new `bits` conversion word lowered to `bitcast`. The unit picks one and states why.
- The Format cell's message changes to name what it waits for (std.float).

**Funnel and entry points.** `scalar_refusal` / `build_member_glue`. Entry points: `member_glue_of`, `instantiate`.

**Matrix.** Hook × reaching position × value class.
- Reaching positions: a direct `a.compare(&b)` / `a.equals(&b)`; a generic `T: Comparable` with `<` and `>`; a generic `T: Equatable` with `==` and `!=`; `Set<Float>` and `Map<Float, Int>` with `0.0` and `-0.0` (gives `1`); `Hasher` used directly (`(0.0).hash` against `(-0.0).hash` is equal); the `copy()` bound.
- Value classes: ordinary, ±0, NaN, ±inf.
- The rows for generic `<=` and `>=` on NaN are blocked by **Q3** and are written after the ruling.

**Corpus moves.** comparison_requirement_concrete_receiver moves from mono Compare to pass, or to its next gap.

**Blocked by.** The NaN rows for `<=`/`>=` wait on **Q3**. Everything else is clear.

### U4: statics of non-integer type (eval + backend) — Opus

**Scope.**
- The evaluator holds a Float (its bits, from U2's funnel; a literal or a negated literal) and an aggregate value: a struct, a fixed-array literal, `[v; N]`, a struct holding `Atomic(<int>)`, an alias construction, and an earlier static as a leaf.
- `mono_take_statics` carries these values.
- `static_global` writes LLVM constant aggregates at the target layout's offsets, and `zeroinitializer` for a bare static.
- Fold SL-685 (bare zerofill) into this unit, or sequence U4 after it; the lead decides. It is the same function, and 11 of the 24 rows need it.

**Funnels and entry points.**
- `LlEmitter.static_global`. Entry point: the `Static` arm of `place_addr`.
- Eval's constant evaluation of a `MirFuncKind.Static`. Entry points: `constant`, the aggregate rvalue, `mono_take_statics`.

**Matrix.** Static kind × element type.
- Static kinds: bare; scalar Float; struct; array literal; repeat; struct holding `Atomic`; nested struct in an array; generic struct instance; imported static (`dep.A` and `{A}`); `unsafe static var` mutated after start; a large table (`[UInt64; 1302]`).
- Element types: each Int width, Bool, Float (`-0.0`, `0.1`), UInt64, Int8 byte region.
- A Float arithmetic initializer (p35) is refused by the rule **Q4** names.

**Corpus moves.** The 24 rows leave `a static whose value is not an integer or a Bool` (§1b lists them). If SL-685 is not folded in, the 8 bare-only rows stay. Where each lands depends on its next gap; many use Once, Mutex or slab. std.float's tables are unblocked. The run lane's `lock_statics.saw` flips if zerofill is in scope.

**Blocked by.** **Q4**, for the Float-arithmetic initializer row only.

### U5: std.float, numeric's Float half, and the Format cell — Opus for the cell and the link, Sonnet-able for the port

**Scope.**
- Port `sawc/std/float.saw` to `std/float.saw`:
  - a `self.std_module("float")` line in `load_new_std_modules`;
  - the std lane's allowlist and behaviour pairs, and the std profile;
  - `tools/sawfloat.py`'s `FLOAT_SAW` table check extended to `std/float.saw`, so the `floatvectors` lane guards both copies.
- Port numeric's Float half (the libm externs).
- The driver links `-lm` off Apple, as `sawc.py`'s `math_libs` does.
- The Floating Format cell calls std.float's `StringBuilder.append(value: Float)`. Today `glue_member` prefers the `Int` overload of `append(value:)`, so it needs a lookup by parameter type.
- Reconcile std.float's `Float.to_string` with the prelude's `Printable.to_string` default. They produce the same bytes.

**Funnels and entry points.**
- THE SCALAR HOOK FUNNEL's Format cell. Entry points: as in U3.
- The driver's clang link-argument builder (`driver/src/main.saw`, beside the `-o` pushes). Entry points: `build`, `runtime`.

**Matrix.**
- Rendering position × value class.
  - Positions: `print(f)`, `"{f}"`, `print("{}", f)`, a `panic`/`assert` format argument, `f.to_string()`, `f.format(into:)`, a `T: Printable` generic, a struct printed through its `format`.
  - Values: `0.0`, `-0.0`, nan, `inf`, `-inf`, the minimum subnormal, the maximum finite value, `0.1 + 0.2`, `100.0`, `0.001`, both sides of the `1e16` and `1e-4` switches, `2^53`.
- The two vector programs as run-lane programs over `tests/float_vectors/`: 2897 shortest rows and 175 parse rows, BIT-EXACT. They use the new std's `File`/`SystemError`; the corpus copies import `std.net.IoError`.
- `abs floor ceil round sqrt min max`, including the NaN rows of `float_methods`.
- `-lm` on the linux lane.

**Corpus moves.**

| rows | from | expected after U5 |
|---|---|---|
| the 9 Format rows besides wrapping_requires_integers | mono Format | pass or their next gap |
| float_methods, string_to_float, float_text_format | `member.unknown` / `call.no-match` | pass |
| wrapping_requires_integers | — | stays `pass` from U1 |
| float_text_*_vectors | `no module std.net` | unchanged until std.net or `IoError` exists (SL-569) |
| json's 23 rows | — | unblocked on the Float side only |

**Blocked by.** Nothing ruled. It needs U1, U2 and U4 (tables, `!=`), and U3 for `Set<Float>` and hashing users.

### U6: Float ↔ integer conversions — Opus; blocked on Q1

**Scope.** Exactly what Q1 rules.
- Typecheck admits the ruled spellings, undoing U1's interim refusal.
- `convert_into` gains Float arms. `sitofp`/`uitofp` carry the ruled exactness check. `fptosi`/`fptoui` are always guarded: an out-of-range input makes LLVM's result poison, so a bare instruction is never emitted.
- The `from` twins, beside the integer twins.
- Constant operands get 170's discipline ("Out of range, it is a **compile error**"), which needs eval to fold a Float (Q1d).

**Funnels and entry points.**
- `convert_into`. Entry points: `rvalue_into`'s `Cast` and `Conversion` arms.
- `cast_allowed` and the integer `from` member typing (refusal "an integer's `from` converts an integer").

**Matrix.**
- Source and target: every integer type, both directions.
- Spellings: `as`, `from`, `from(truncating:)`, as ruled.
- Values: 0, -0.0, 0.5, -0.5, 2.5, `2^53`, `2^53 + 1`, `Int.max`, `Int.min`, `UInt64.max`, NaN, ±inf, `1e19`, `-1.0` into an unsigned type.

**Oracle.** The ruling's text, not Stage 0, which refuses everything. New corpus programs are judged by their own directives as a language change.

**Corpus moves.** None. No tracked program converts today.

### The non-Float leftovers SL-722 names: recommend splitting them out

| item | rows | recommendation |
|---|---|---|
| `E.from(raw:)` lowering | 6 | new issue: `convert_into` has no arm for the word `from(raw:)`. It needs a case-value membership test that returns `Some(case)` or `None` (q06 shows Stage 0's `200` / `none`). |
| alias projection of a memory-layout type | 2 | new issue, or the same one: `cast(move _ as String)` has no Int layout. It needs a move-through at the type, and V65 is a conformance row, so the retain has to be right. |
| `N` as a value | 8 | SL-548 (open) already owns it. |
| `#line` / `#file` constants | 1 + 1 | new issue: `const_value` has no arm for a source-location builtin. |

## 5. Questions for the user

**Q1 (SL-69). What do Float↔integer conversions spell, and what do they do?** Four sub-rulings:
- (a) `n as Float` for an `n` that does not fit 53 bits: exact-or-panic, or round to nearest even?
- (b) `f as Int`: panic on NaN, ±inf and out of range — and also on a fractional part?
- (c) The twins: is there `Int.from(f) -> Int?`, `Float.from(n) -> Float?`, and a total named spelling (`from(truncating:)` toward zero for Float → Int, and something for nearest-even Int → Float)?
- (d) Is a constant operand that would panic a compile error, as design 170 rules for integers?

*Lean:* design 173 decision 3 for `as` and `from`.
- `as` is exact-or-panic in both directions, a fractional part included.
- A program writes the rounding as a Float method first: `f.floor() as Int`, `f.round() as Int`. That answers DF-276b's "a truncation, a round, and a floor are three different operations … three names" with names that already exist; it adds `trunc()` to numeric.
- `from` returns `None` where `as` would panic.
- No `from(truncating:)` from Float, since "truncating" means low bits for integers.
- A constant that would panic is a compile error.

*Evidence:*
- p05, p06, p38 and p43: Stage 0 refuses every spelling today.
- Spec: "Saturating conversion is not offered. Clamping is a value-domain policy". This rules out Rust's saturating `as`.
- Design 173 was "APPROVED direction" on Aug 7, with these shapes "recommended, veto-able"; Aug 20 overruled only its `Float64` decision.
- *Until ruled:* U1 refuses `as`, as Stage 0 does. sawc2 accepts it today (F2).

**Q2 (SL-68, SL-393). Is a float literal that cannot be represented a compile error?**

*Lean:*
- A literal that rounds to ±inf is an error.
- A nonzero literal that rounds to ±0 is an error.
- A literal that rounds to a subnormal is accepted. It is a representable value, and the 324-digit minimum-subnormal literal is the only way to write that value.

*Evidence:*
- p41: Stage 0 builds both faces silently, and LLVM does too (`llvm_over.ll`).
- The integer literal beside it is checked: "a literal that does not fit the target word is a compile error *at the literal*".
- U2's funnel reports the fault either way, so the ruling is only whether a rule refuses it.

**Q3. In a generic body, is `a <= b` / `a >= b` on a Float NaN `false` (fcmp) or `true` (`compare != Greater`)?**

*Lean: `false`.* The spec's rule "every ordering operator involving it is `false`" holds in every context. A generic ordering operator then lowers per instance: a scalar instance compares directly, as Stage 0's monomorphized `fcmp` does; any other type desugars to `compare`. The spec's desugaring sentence gains "for a type with a total order".

*Evidence:*
- g01: Stage 0 prints `false false false false false true false`.
- sawc2's MIR for `le<T>` is `Ne(compare(a, b), Greater)`.
- The alternative leaves `nan <= 1.0` true in generic code and false in concrete code.

**Q4. What may a Float static's initializer be?**

*Lean:*
- A float literal, a negated one, and aggregates of them: Stage 0's accepted set (p45, p46).
- The spec's constant grammar gains "float literals".
- Float arithmetic (`1.0 + 2.0`, p35) stays refused, as a gap rule (`slice.not-yet`), until the constexpr widening. The Sep 25 "ordinary typed arithmetic" ruling would then need a bit-exact soft-float in the evaluator, because the seed has no Float.

*Evidence:* no tracked `.saw` declares a Float static.

**For the lead, not the user:**
- Split the non-Float leftovers out of SL-722 (§4, the last table).
- Fold SL-685 into U4, or sequence U4 after it.

## 6. Side findings

- **F1.** sawc2 accepts `&+`, `&-` and `&*` on Float (t01, t02). The spec says the wrapping operators take "**integer operands only** (a `Float` operand is a type error)", and Stage 0 refuses. Today this is masked in wrapping_requires_integers by the mono Format gap; it becomes `wrong: accepts a refusal test` the day Format lands. U1 fixes it.
- **F2.** sawc2 accepts `as` between Float and every integer type (`cast_allowed`: `is_numeric` on both sides). Stage 0 refuses with `cannot cast`; the spec has no such conversion (Q1). It is refused later only by the backend's `this conversion` gap. The `type.mismatch` hint for `Float * Int` teaches `as` for that pair. U1 fixes it.
- **F3.** `sawc2 build` does not surface eval's `slice.not-yet` for a static it cannot evaluate (p09, p33). `eval --check` refuses at the initializer, but `build` refuses later, at the static's use, with the backend's message. It is not unsound; it is a weaker location.
- **F4 (not Float).** sawc2 builds `Wide.Big as UInt8` for a `UInt16`-backed case with value 300, and the program panics at run time (q02). Stage 0 refuses at compile time. The spec says the constant fold "sees through const arithmetic and a raw-backed enum's case value". errors/cast170_const_out_of_range is already `wrong`. File it separately.
- **F5.** sawc2's driver links no `-lm`, but Stage 0 does off Apple (`sawc.py` `math_libs`). The first libm call on Linux, from numeric's Float half or an `extern sqrt`, would fail to link in the linux lane. Covered by U5.
- **F6 (UNVERIFIED).** NaN bit patterns differ by target and between constant folding and run time. No matrix row prints a NaN's bits.
