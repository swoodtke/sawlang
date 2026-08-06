# Design 147 — soundness batch: the decided DF backlog

STATUS: APPROVED (user, Aug 5 — every unit individually decided in the
DF review session; see each tracker entry's DECIDED/APPROVED header).
Slots AHEAD of 135/138/144, after the in-flight 145 and 146-C integrate.
Units A-C are the soundness core; D-F are unambiguous bug pulls. Repros:
units A/D/E/F live on the PARKED SOS M1 branch's tracker — file each
fresh in main's tracker as part of landing (the 142/DF-140f pattern);
units B/C have main-tracker entries with inlined repros.

## Units

- **A. DF-140e (P0, THE LEAD UNIT) — the diverging-arm miscompile.** A
  tail `match` with one diverging arm drops the auto-wrap into `Err` and
  returns a RAW error value (caught only by the LLVM verifier). Fix the
  tail-position auto-wrap to place wraps per-arm (skipping diverging
  arms) rather than post-match. The verifier repro becomes the
  regression; sweep for sibling shapes (tail `if` with a diverging
  branch, tail match under Optional auto-wrap).

- **B. DF-139a (P1) — assignment releases a value a live copy still
  owns.** `let c = h.s; h.s = build(2)` leaves `c` dangling (plain
  String field; also whole-binding and enum-payload shapes; repro in the
  tracker). Diagnose first: the read's marked retain either never
  reaches codegen on the assignment path or the release runs without
  consulting it — trace checkpoint → codegen for BOTH the
  field-assignment and whole-binding paths, then fix at the true joint.
  Oracle tests: copy-then-overwrite prints both values correctly for
  String / String? / owning-enum shapes; drop counts exactly balanced.

- **C. DF-133a — the hoist preserves source evaluation order** [user:
  fork (i)]. Side-effecting LEFT siblings of a hoisted suspending child
  are lifted into temps, bounded by a conservative purity filter
  (literals + plain identifier reads exempt; anything containing a call
  or `&var` use hoists). Transfer checkpoints and diagnostics KEEP
  source positions (the design-120 temp discipline). Tests: the
  noisy/slow print-order repro; the STATE shape (`add(v.pop()!,
  slow(v.len()))` sees post-pop len); a `move v` argument's checkpoint
  still reported at the written position; irdet-all clean after the
  corpus-wide IR churn.

- **D. DF-134a — the `__saw_rt_reactor_unregister` seam** [user:
  approved into the frozen ABI]. rt/ABI.md gains the seam; kqueue
  EV_DELETE / epoll EPOLL_CTL_DEL bodies in host_macos/host_linux
  reactor.saw (no C shim); called on the park loop's cancellation exit
  and at frame `__release` for any registered-but-unfired token.
  Regression: park on an fd, cancel, escape the fd through the result,
  poke it — no stale-token delivery (post-134 this was a use-after-free
  vector: the frame box frees at Done).

- **E. DF-137d + DF-140a — literal range checks are target-width-aware.**
  `0x80000000` silently wraps to negative on a 32-bit platform `Int`;
  `static B: UInt8 = 256` skips checking entirely. Extend the existing
  literal range check to platform `Int`/`UInt` under the EFFECTIVE
  triple, and route static initializers through the same check. Tests
  under an explicit riscv32 --target (compile-error assertions;
  {TESTDIR}/COMPILE-FLAGS machinery).

- **F. The parked-branch bug pulls.** DF-140b: `import a.{x,\n y}` lists
  wrap — a narrow newline allowance inside the import-list braces ONLY
  (they are not statement containers; 129's `{}` significance rule
  otherwise stands). DF-140c: a module-qualified type resolves in TYPE
  position, and the failure diagnostic points at the qualified name, not
  a downstream `guard let`. DF-140d: `Result<T?, E>` auto-wrap ICEs both
  directions — fix the wrap-insertion to see through the Ok-payload
  optional; clean error if genuinely ambiguous.

## Gates
Per-unit commits, full suite green each; final battery: suite, lexdiff,
`make irdet-all`, astdiff, bootstrap, sos. Spec/skill touched where
user-visible (unit C's evaluation-order promise becomes TRUE — keep the
spec sentence and add the test reference; unit F's import wrapping joins
the 129 line-break section). Tracker: DF-140e, DF-139a, DF-133a,
DF-134a, DF-137d, DF-140a, DF-140b, DF-140c, DF-140d all closed.
