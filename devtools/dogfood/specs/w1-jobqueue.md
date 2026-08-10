# Spec w1-jobqueue — worker pool with cancellation

Build a program that runs a fixed workload through a pool of concurrent
workers and cancels part of it mid-flight.

Behavior:
- Jobs are numbered 1..=60. Job k's WORK is: compute the sum 1+2+...+
  (k*97 mod 1000), yielding control to other work at least once during
  the computation.
- A pool of 6 concurrent workers drains a shared queue of the 60 jobs
  in job-number order (a worker takes the lowest un-taken job).
- After dispatching, the coordinator CANCELS jobs 41..=60 (those not
  yet finished when cancellation reaches them must not report a
  result; cancellation of a finished job is a no-op).
- Each worker tallies: jobs completed, jobs observed cancelled.

Output (exactly, in this order):
- One line per worker, in worker order: `worker <i>: completed <n>`
- `total completed <N>` — sum over workers
- `total cancelled <M>` — where N + M == 60
- `checksum <S>` — S = sum of the computed sums of all COMPLETED jobs

Acceptance:
- Runs to completion (no hang, no crash), exit code 0.
- N + M == 60 and M >= 1 (some cancellation must actually land; pick
  work sizes so jobs 41..=60 cannot all finish before the cancel).
- Two consecutive runs print identical N, M, and S if your language's
  scheduler is deterministic; if not, N/M/S may vary but the N+M==60
  invariant and per-run checksum consistency (S recomputed from the
  completed set equals the printed S) must hold.
