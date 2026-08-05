# Design 132 — Review-fix batch 2 (overnight-agent findings)

STATUS: APPROVED (user, Aug 5). The DF-122a unit carries an explicit user
decision; the rest are unambiguous bugs triaged fix-now. Dispatch order:
AFTER design 131 lands (both touch the typechecker; 130 → 131 → 132).
Repros for every item are inlined in designs/todo.md under their DF names.

Per-unit commits, full suite green each, regression test(s) per unit that
fail before / pass after. The 122 brief is the mold.

## Units

- **A. DF-122a — reject assignment to a by-value closure capture.**
  `[user, Aug 5: reject-the-write]` Writing to a plain/move/copy capture is
  accepted today and silently discarded (per-call env copy, no write-back);
  persisting it would break the ratified immutable-env model (designs 71/73)
  and the MT Send audit. Make the assignment a COMPILE ERROR whose hint
  points at `[&var x]` (non-escaping borrow capture — already correct) and
  `Arc<Mutex<T>>` (escaping shared state). Measured blast radius is zero
  in-tree. Closes RS-5's fourth hole. A future opt-in `[box n]` capture mode
  stays open as a possible later brief — this unit decides nothing beyond
  enforcing the spec's existing model. Spec + skill note the rule; the
  make_counter and each3 shapes become error tests.

- **B. DF-123a — ICE: generic-struct static call via the extension's own
  type parameters.** A static method call on the enclosing generic struct
  spelled with the extension's own type params recurses forever in
  `_get_llvm_type` and takes the whole compilation unit down (every program
  stops compiling). Pre-existing; reproduced on a clean tree. Fix the
  recursion (correct instantiation or a clean diagnostic naming the
  unsupported spelling — never an ICE).

- **C. DF-123b — ICE with an empty message: method-generic local at
  `Void`.** A generic local typed by the method's own type parameter, when
  that parameter instantiates to `Void`, ICEs with no message. Either
  compile it correctly (Void-sized local, as Void values work elsewhere) or
  reject cleanly at the instantiation site.

- **D. DF-128d / DF-129a — `print(o)` on an Optional is an ICE.**
  `internal compiler error: Cannot print type: {i1, i64}` instead of the
  clean "not Printable" diagnostic that INTERPOLATING the same value already
  produces. Found independently by two agents. Route `print`'s argument
  check through the same path as interpolation so both give the identical
  clean error. (Whether `T?` should BE Printable is a separate design
  question — out of scope; parity of diagnostics is the fix.)

- **E. DF-128b — a payload-free enum is refused as a Map/Set key.** It
  auto-conforms to Equatable and Hashable (spec: mirrors Equatable's gating
  exactly), but the key-type check rejects it. Accept it; test a
  payload-free enum as both Map key and Set element, incl. a collection
  literal.

- **F. M15 — `Directory.current` truncates at 1024 bytes.** Grow-and-retry
  on the getcwd seam (or query the needed size) so long paths come back
  whole; keep the OOM path separated as design 123 left it. Test with a
  deep scratch directory tree.

- **G. P2 — finish the design-92 sweep in `std.file` / `std.directory`.**
  The no-silent-error-swallow policy was half-applied there (called out at
  122's landing). Audit both modules for remaining swallow/sentinel shapes
  and finish the job; the tracker's P2 entry lists the known spots.

- **H. DF-128c — the drop-glue half of the `_type_method_base` mangling
  miss.** RISKY UNIT, own commit(s), stop-if-it-fights rules apply. The
  copy half was a live double-free and is fixed (design 128, `7fc9fc4`);
  applying the same fix to the drop-glue path is obviously right BUT makes
  blade's self-build segfault — meaning some struct's `Vector` field is
  already being freed by another path, and the current miss is masking it.
  Diagnose that other path first (the segfault is the lead), then land both
  fixes together. If the diagnosis opens a design question, STOP the unit
  and record findings per the no-workarounds policy.

## Exit criteria
Every unit has fail-before/pass-after tests; full gate battery green (suite,
lexdiff, irdet, astdiff, bootstrap, sos); spec/skill/README updated where
user-visible (A, D's error text, F); tracker lines closed: DF-122a (RS-5
hole 4), DF-123a, DF-123b, DF-128b, DF-128d, DF-129a, M15, P2 — and DF-128c
closed or its findings recorded.
