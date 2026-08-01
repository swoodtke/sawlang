# Design 86 — httpd-runtime cleanup: test-runner timeout, variadic libc audit, append-across-suspend (queued Aug 1)

Three findings from the design-85 salvage; the last one is the final
thing between the safe net API and a RUNNING httpd. Ordered by
blast-radius.

## 1. Test-runner run-phase timeout (INFRA — do FIRST)
A test that HANGS AT RUNTIME wedges the whole suite: the runner has no
effective per-test run-phase timeout (it caught this only because the
orchestrator killed it manually). This is a standing hazard for all
concurrency work. Fix: wrap each test's RUN subprocess in a hard
timeout (e.g. 30s, generous vs the ~seconds real tests take); on
timeout, kill the process group and record the test as FAILED
(timeout), never hang the runner. A deliberately-hanging fixture
(gated so it isn't a normal test, or a unit test of the runner)
proves the timeout fires. This protects every future concurrency
brief.

## 2. Variadic libc declaration audit (CORRECTNESS)
Design 85's hang was `fcntl` declared non-variadic (`int fcntl(int,
int, ...)` in C) → arm64 passed the F_SETFL flag wrong → O_NONBLOCK
heisenbug. AUDIT every libc extern the compiler/std declares for the
same bug: `open` (`int open(const char*, int, ...)`), `ioctl`,
`fcntl` (done), `printf`-family if any, and any other variadic C fn
declared with fixed params. Declare each `var_arg=True` with the
correct fixed-param prefix. Grep codegen `_libc_func` calls + std
extern blocks. Tests where a behavior hinges on the variadic arg
(e.g. `open` with a mode). Report the full list found + fixed.

## 3. `&var self` mutating method on an opt-encoded frame local (BLOCKS httpd runtime)
`net_http_roundtrip` hangs (quarantined in .build/scratch/) because
accumulating the request via `req.append(move chunk)` — a `&var self`
mutating method call on a StringBuilder/Data frame-local held across a
suspend (opt-encoded in the coroutine frame), operating on a moved
temporary — misbehaves. Root-cause: a `&var self` receiver that is an
opt-encoded frame field isn't addressed/written back correctly across
the suspend (relative of design 84's `&(opt!)` addressing + design 62
self_opt). Fix so a mutating method on an owning frame-local across a
suspension mutates the real frame slot (exact-count + content test:
accumulate N chunks across N reads, assert the full buffer). Then
UN-QUARANTINE net_http_roundtrip (move back to examples/), confirm it
RUNS (socketpair HTTP-shaped round-trip, deterministic, time-bounded),
and — acceptance — the migrated `.build/scratch/httpd_sw.saw` serves a
scripted GET (or its socketpair-reduced form is a suite test). Report.

## Docs / tracker
saw-lang skill (remove any stale runtime-limit note once #3 lands);
tracker (design 86 landed; the design-84/85 flagged items closed; the
variadic-audit result recorded).

Bars: full suite (baseline 874) + blade/libs + bootstrap green per
commit; zero xfails. STANDING POLICY: fix user-facing bugs on
discovery unless ambiguous. Interruption-safe per-item commits with
tracker progress notes (this dogfood push has seen repeated API drops
— commit each of the 3 the instant it's green). Run any hanging probe
under a watchdog (macOS has no `timeout`; use background+sleep+kill or
gtimeout). saw-lang skill self-review.
