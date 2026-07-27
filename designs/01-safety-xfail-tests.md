# Design Brief 01 — Safety XFAIL Test Suite

**Source:** `todo_jul26.md` § "High-value missing tests"
**Scope:** tests only — no compiler changes. Every new test documents a *known,
real* bug from the critique, so every new test lands as `// XFAIL:`.
**Exit criteria:** `make test` fully green (new tests report as yellow `x`
xfail, zero red). No existing test's behavior changes.

## Background

The test harness (see `TESTING.md`) discovers every `*.saw` under `examples/`
and reads `// EXPECT:` directives. `// XFAIL: reason` marks a known-broken
test: it still compiles and runs every `make test`, reports yellow, and — the
important part — flips to a build-breaking **XPASS** the moment the bug is
fixed. These tests are the mechanical exit criteria for the upcoming fixes to
`todo_jul26.md` must-fix items 1, 4, 5, 6, and 7.

**Rule from TESTING.md that governs everything here:** the `EXPECT` directives
must describe the *correct* behavior (what the compiler *should* do), with
`XFAIL` recording why it currently doesn't. Never write a test that asserts the
buggy behavior.

## Tests to write

Flat files in `examples/`, snake_case names matching existing conventions
(model on `custom_copy_*.saw`, `deinit_*.saw`, `nocopy_*.saw` if present).
One bug per file. Suggested names below; adjust to match house style.

### A. Copy/move enforcement gaps (must-fix #1)

1. `nocopy_call_arg_requires_move.saw` — a `NoCopy` value passed as a plain
   function-call argument without `move`. Correct behavior:
   `// EXPECT: error` + `EXPECT-ERROR-CONTAINS` for a move-required
   diagnostic. Currently compiles (and double-frees). Base it on the critique's
   repro:

   ```saw
   func consume(v: Vector<Int>) { }
   func main() {
       var v = Vector<Int>(capacity: 10)
       consume(v)     // should be a compile error: requires `move v`
       v.push(42)
   }
   ```

   For the ERROR-CONTAINS text, first check what diagnostic the existing
   `let`-binding NoCopy check emits (`sawc/typechecker/statements.py` around
   lines 405–526) and use consistent phrasing.

2. `nocopy_explicit_return_requires_move.saw` — same gap via explicit
   `return x` of a NoCopy value where x is used afterward or where the
   return isn't a move site. Only add this if you can construct a case that
   is genuinely wrong today — verify by compiling. If explicit `return x`
   turns out to be handled, note that in your report instead of forcing a test.

3. `nocopy_struct_field_init.saw` — a NoCopy value used to initialize a struct
   field without `move`, then used again. `// EXPECT: error`, XFAIL.

4. `custom_copy_call_arg.saw` — a `CustomCopy` type passed by value as a call
   argument; `copy()` must be invoked. Make the copy observable: model on the
   existing `custom_copy_*.saw` tests (they evidently print from `copy()` or
   track a counter). `// EXPECT: success` with the output that *would* appear
   if `copy()` ran; XFAIL because call args currently bitwise-copy.

### B. Mangling collisions (must-fix #4)

5. `generic_nested_tuple_mangling.saw` — one program instantiating both
   `Result<(Int, Int), SomeErr>` and `Result<(String, Bool), SomeErr>`
   (e.g., two functions returning them, both called from `main`, results
   matched and printed). Both currently mangle the tuple to the literal
   `"TUPLE"` (`sawc/codegen/results.py:484-507`) and alias one LLVM struct —
   silent miscompile. `// EXPECT: success` + correct outputs; XFAIL.
   If the collision manifests as a compile-time LLVM error rather than wrong
   output, that's still a failure — fine, XFAIL covers both.

### C. String interpolation memory-unsafety (must-fix #5, #6)

6. `interp_large_string.saw` — interpolate a string built to exceed the 1024-
   byte stack buffer (`sawc/codegen/core.py:613-650`). String concatenation
   may be limited in current Saw — building the >1KB payload via repeated
   interpolation of interpolated results is acceptable. `// EXPECT: success`
   + expected output (or at minimum a sentinel print after the interpolation);
   XFAIL: stack-buffer overflow.

7. `interp_escapes_scope.saw` — an interpolated string returned from a
   function / stored and printed after the producing scope exits (dangling
   `alloca` pointer). `// EXPECT: success` + correct output; XFAIL.
   Note: dangling-pointer reads may *appear* to pass by luck. If it passes
   deterministically on this machine, document that in your report and keep
   the test **without** XFAIL only if it genuinely asserts correct behavior
   and passes; otherwise XFAIL. Try to structure the test so the stack slot
   gets clobbered (call another function that writes locals before printing).

8. `interp_hot_loop.saw` — a loop with interpolation in the body, enough
   iterations to blow the stack via per-iteration allocas
   (`sawc/codegen/loops.py`). Use ~1,000,000 iterations printing to a
   variable, not stdout, if possible; if output is unavoidable, keep
   iterations as low as feasible while still crashing (test runner timeouts —
   check `test_runner.py` for a timeout and stay under it). `// EXPECT:
   success`; XFAIL: unbounded stack growth.

### D. Missing runtime/compile-time checks (must-fix #7)

9. `array_const_index_out_of_bounds.saw` — fixed-size array indexed with an
   out-of-bounds *constant* index. The tuple path already rejects this
   (`sawc/typechecker/expressions.py` ~852 vs ~865), arrays don't.
   `// EXPECT: error` + ERROR-CONTAINS matching the tuple diagnostic's
   phrasing; XFAIL.

10. `div_by_zero_panics.saw` — integer division by zero should panic with a
    message (match the `try!` panic machinery's message style,
    `sawc/codegen/results.py:77-98`), not SIGFPE. `// EXPECT: panic` +
    `EXPECT-PANIC-CONTAINS`; XFAIL: currently dies with SIGFPE. Check how the
    runner classifies signal deaths first; the test must land as xfail, not
    as a runner crash.

## Method — verify every test twice

For each test:
1. Write it with correct-behavior EXPECT directives and **no** XFAIL.
2. Run `python3 test_runner.py -f <name>` and confirm it **fails** (proving it
   captures the bug).
3. Add the `// XFAIL: <one-line reason referencing todo_jul26.md item #>`.
4. Confirm it now reports xfail.

If a test *passes* in step 2, the critique may be wrong or the repro
insufficient — investigate briefly; if the behavior is genuinely correct
already, keep the test as a normal (non-XFAIL) regression test and flag it in
your report.

Finish with a full `make test` — zero red, all new tests yellow.

## Report back

List each test with: filename, bug it captures (critique item #), how it fails
today (wrong output / crash / compiles-when-it-shouldn't), and any surprises
(tests that passed in step 2, runner limitations hit, e.g. signal handling or
timeouts).
