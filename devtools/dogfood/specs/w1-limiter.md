# Spec w1-limiter — bounded-concurrency executor

Build an executor that runs many small jobs while PROVABLY never
letting more than R of them be in flight at once.

Behavior:
- 40 jobs, numbered 0..=39. Job k's body: record entry, yield control
  at least twice (so other jobs can interleave), compute
  s = k*k + 7, record exit, deliver s.
- The executor runs all 40 with a concurrency BOUND of R = 5: at most
  5 jobs between entry and exit at any moment. Jobs beyond the bound
  wait their turn; the executor must not busy-spin while waiting.
- Instrument: a shared in-flight counter incremented at entry and
  decremented at exit; track its maximum observed value. Also tally a
  per-job-start order list.
- After all jobs complete, report the results.

Output (exactly):
- `jobs 40`
- `max in flight <M>` — must print M == 5
- `results sum <S>` — sum of all delivered s values
- `done`

Acceptance:
- M == 5 exactly (the bound is reached — with 40 jobs and yields it
  must be — and never exceeded).
- S == 20820 (sum of k*k for k in 0..=39 is 20540, plus 7×40).
- Identical output across runs; exit code 0.
- The bound must be enforced by a reusable mechanism (a semaphore-like
  or queue-based limiter you build), not by chunking the jobs into
  batches of 5.
