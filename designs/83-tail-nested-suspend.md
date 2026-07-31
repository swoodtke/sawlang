# Design 83 — Nested suspending call in tail/statement position (queued Jul 31)

User-facing coroutine-transform bug found dogfooding an httpd. A
suspending function that calls ANOTHER suspending function in
TAIL-expression or bare-expression-STATEMENT position fails with
"undefined function `<callee>`" — the transform only embeds a nested
suspending call's sub-frame when it is LET-BOUND.

## Repro (minimal, characterized)
- FAILS: `func middle() -> Int { yield_now(); inner() }` (nested
  suspending `inner()` in tail position) → "undefined function inner".
  (`.build/scratch/probe_nd_main.saw` / `probe_nested_driven.saw`.)
- WORKS: `func middle() -> Int { let y = inner(); yield_now(); y }`
  (same calls, let-bound) → runs, prints 1
  (`.build/scratch/probe_nd_letform.saw`).
- Independent of driver (suspending `main`, `__drive`, `group.spawn`
  all fail on the tail form); the existing `coro_nested_suspend_two_deep`
  passes only because it let-binds (`let z = mid(3)`) and uses the
  test-only `__suspend`/`__drive`.
- Real blocker: httpd's `worker` loop calls `handle_connection(...)`
  as a bare suspending statement (`.build/scratch/httpd_sw.saw`).

## Scope
1. Root-cause the nested-suspending-call detection/embedding in
   coro_transform.py: it walks `let`-RHS positions for callee
   sub-frame embedding but misses (a) a tail EXPRESSION that is a
   suspending call, and (b) a bare expression-STATEMENT that is a
   suspending call (incl. a Void-returning suspending call — the
   httpd case; and a `let _ =` discard of one). Embed the sub-frame
   in all these positions (the machinery exists; the position scan is
   incomplete).
2. Cover the compositions that fall out: tail nested call inside an
   `if`/`match` arm that is itself the function tail; a bare
   suspending-call statement mid-body (not just tail); the
   Void-return case (no `__result` value to thread — the sub-frame
   still drives to completion, result discarded).
3. Tests (real `yield_now`, driven by a suspending `main` AND by
   `group.spawn` — both, since httpd uses spawn): tail-position
   two-deep (value result), Void-return bare-statement nested
   suspending call in a loop (the httpd shape, reduced), nested call
   in a tail `if` arm, `let _ =` discard of a suspending call. Keep
   the existing coro_* suite green.
4. Recompile `.build/scratch/httpd_sw.saw` as an acceptance check
   (it should reach codegen; any REMAINING httpd errors are separate
   — report them, don't scope-creep).
5. Docs: saw-lang skill (remove/ää adjust any "nested suspending"
   limitation note if now false); tracker (design 83 landed; note
   whether this closes part of A5-rest shape 1 or is orthogonal).

## Hazards
- The transform's state-machine + drop-flag correctness across the
  newly-embedded sub-frames — deinit-exactly-once for owning values
  live across the nested suspension (exact-count test with an Arc/
  Deinit-counter threaded through a tail nested call).
- Do NOT regress the let-bound path or `coro_nested_suspend_two_deep`.
Bars: full suite (baseline 867) + blade/libs + bootstrap green per
commit; zero xfails. Standing policy; interruption-safe commits;
saw-lang skill self-review.
