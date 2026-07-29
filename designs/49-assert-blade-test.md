# Design 49 — panic/assert builtins + `blade test` (D15, DECIDED Jul 29)

**Ruling (user):** zero new language surface for testing. Tests are
ordinary Saw programs in `tests/`; pass = exit 0; `blade test`
compiles, runs, reports. `#[test]` attributes may layer later when
attribute syntax exists for other reasons.

## Items
1. **`panic(message: String) -> Never`** builtin — routes through the
   saw_panic seam (message + newline; freestanding-safe). Retrofit the
   stdlib's panic-shaped force-unwraps where a better message is
   cheap (e.g. Box.make OOM → "allocation failed", the brief-42
   deviation). Also closes tracker M4.
2. **`assert(cond: Bool, message: String)`** builtin — no-op on true;
   panic("assertion failed: " + message context incl. line if cheap —
   probe whether line info is available at the call; report) on false.
   (debug_assert deferred — no build-profile split exists.)
3. **`blade test`** subcommand (in blade/, Saw code — the testbed's
   first new feature): discover `tests/*.saw` in the project, compile
   each with the project's sources (reuse `blade build` machinery),
   run, collect exit codes, report per-test ok/FAILED + summary +
   nonzero exit on any failure. Sequential first; parallel later.
4. Blade's own first tests: seed `blade/tests/` with 2-3 real tests
   (TOML parsing, manifest fields) proving the loop end to end —
   run via the freshly built blade against itself in CI-style
   (scratch-verify; the compiler suite gains a driving test if
   expressible without recursion pain — report).
5. Docs: TESTING.md section for app-level testing; spec builtins
   section; CLAUDE.md.

## Hazards
panic/assert are tiny; the work is Blade plumbing (Saw code — dogfood
discoveries are the point: report every language pain hit). Do not
break the compiler's own EXPECT-based harness semantics.
