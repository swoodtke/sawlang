# Design 122 — Review-sweep fix batch (P0/P1 unambiguous fixes)

Source: `designs/reviews/2026-08-04-stdlib-review.md`,
`.../2026-08-04-language-design-claims.md`, `.../2026-08-04-docs-consistency.md`
(probe repros for every item live there). User triage Aug 4: fix now, no design
ambiguity. Excluded on purpose: the allocator-failure corruption class (design
123 owns it, including `Vector.push`/`grow`), TaskGroup lifetime (124),
op-budget (127), RC-2 substitution bug (126 owns it via the AST contract).

Per-unit commits, full suite green each, regression test(s) per unit.

## Units
- **A. `Vector.iter()` double-free + `set` leak + `byte_at` OOB.** `iter()`'s
  `next()` must not mint a bitwise duplicate of an owning element — follow the
  `StringBytes`/`StringChars` retain model (or return through the
  `with_ref` scoped-borrow shape if cleaner; pick ONE and note why).
  `Vector.set(i, v)` must release the element it overwrites.
  `String.byte_at(i)` gets the same always-on bounds panic as indexing
  (OOB read from a safe signature is never acceptable).
- **B. `Data.to_string()` must not mint invalid UTF-8 Strings.** Route through
  the existing `Utf8Error` surface (same failure type `String` decoding already
  uses); no lossy silent truncation.
- **C. `std.process.Command` becomes real argv spawn.** Replace the
  `system()` string-concat with a spawn seam taking an argv vector (additive
  `__saw_rt_*` seam is allowed — document it in `rt/ABI.md`; posix_spawn or
  fork/exec in the Saw rt bodies + shim only if FFI-blocked). `arg("one two")`
  must pass ONE argument; no shell interpretation anywhere.
- **D. Silent-wrong-answer holes.**
  1. A bare `{ ... }` closure literal as an expression-statement (never
     called, silently discarded) becomes a compile error naming the fix
     (call it, or bind it).
  2. Redefining a builtin (`func print`, `func assert`, ...) is currently a
     silent drop — make it a duplicate-definition error consistent with the
     design-100 shadowing rules.
  3. `let n = <Void expression>` must be rejected by the typechecker (today it
     ICEs in codegen with an empty message).
  4. Escaping-closure mutable capture resetting per call (`make_counter()` →
     1,1,1): diagnose the capture model first. If the fix is a contained
     codegen bug (env slot copied instead of referenced), fix it; if it opens
     a semantics design question, STOP the unit and record the finding with
     the wanted semantics (per the no-workaround policy).
- **E. `--emit-docs` effect field from the effect graph.** Suspending USER
  functions must emit `"suspending"`; delete the hardcoded std-name list in
  `sawc/docs_emit.py`. Golden-test a user suspending function.
- **F. Portability (SOS-relevant).** `Directory.list`'s hardcoded macOS dirent
  offset moves behind the host split (correct Linux value in host_linux);
  `Data`'s hardcoded `sizeof(DataBuffer)=24` becomes `sizeof<>`.
- **G. DF-119b: unsigned `print`/interpolation formatting.** `print(UInt.max)`
  prints `18446744073709551615`, not `-1` — unsigned digit path selected by
  operand kind, threaded through BOTH the `print` call site (codegen/calls.py)
  and `_value_to_string` (codegen/core.py). Closes DF-119b.
- **H. `--freestanding` on the Mach-O host**: replace the uncaught LLVM ERROR
  abort with a clean diagnostic telling the user an ELF cross-target is
  required (and how to pass it).
- **I. Panic source locations (user-approved fold-in).** Overflow / bounds /
  div-zero / shift-check panics currently carry NO location; force-unwrap and
  `try!` carry line but no file. All runtime check panics gain the same
  `panic at FILE:LINE:` prefix asserts already have. Location constants are
  per-site interned strings — measure binary-size cost on the SOS kernel
  build; if it moves the kernel size materially, gate the FILE part behind
  the freestanding profile (line always kept) and record the numbers in the
  commit message.

## Exit criteria
Every unit has a test that fails before / passes after; suite + bootstrap +
lexdiff + sos green; `rt/ABI.md` updated for unit C; spec/skill updated where
user-visible behavior changed (B, C, D1-3, G). Tracker: close the RS-2, RS-4,
RS-5, RC-1, RC-4(n/a), RC-5, P2, DF-119b lines this brief owns.
