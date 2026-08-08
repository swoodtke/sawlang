# Design 181 — investigation: the blocking-call audit

**Status: APPROVED (user, Aug 7 evening: "a sweep of the stdlib to ensure
there are no additional blocking calls which could block our async
runtime"). PROBE/READ-ONLY — the product is an inventory, findings, and
per-class policy recommendations; fixes are follow-up dispatches. Runs
concurrent with anything (no std/rt edits).**

## The contract being audited

Design 103: `extern blocking` marks an unbounded call — it suspends, is
offloaded to a worker thread in suspending bodies, and is illegal in sync
contexts. An UNANNOTATED extern PROMISES promptness. The audit question:
which unannotated externs across sawc/std/ + sawc/rt/ break that promise —
a libc call that can block unboundedly (or for human-visible time) while a
cooperative executor thread is inside it, starving every sibling task.

## Method

1. **Inventory EVERY `extern` declaration** in sawc/std/*.saw, sawc/rt/
   (common + both hosts), and builtin.saw if any. For each: the libc call,
   its worst-case blocking behavior (unbounded / bounded-slow / prompt),
   which std surfaces reach it, and whether the reaching path is
   (a) reactor-integrated (non-blocking fd + park — the net pattern),
   (b) `blocking`-annotated (offload), (c) executor-internal by design
   (the sleep park — being unified by design 180), or (d) NAKED — an
   unannotated potentially-blocking call reachable from a task.
2. **Class (d) is the findings list.** Seeded suspicions to verify first,
   then sweep for the rest: `Command.run`/`output` child-wait (waitpid is
   unbounded — a task running a subprocess may wedge its thread);
   hostname/DNS resolution if any path does it (getaddrinfo has no
   non-blocking form — the classic); std.file/std.directory disk I/O
   (open/read/write/fsync/stat/list — bounded-slow on local disk,
   unbounded on network filesystems); pipe reads in Command.output;
   Mutex (pthread block — bounded by the lock discipline, but VERIFY a
   task-context lock cannot deadlock the executor); Channel's blocking
   `recv` twin (documented — confirm the docs fence it from task context);
   anything in env/process/time.
3. **Verify empirically where cheap**: a two-task probe per suspect — task
   A enters the suspect call (e.g. runs `sleep 5` via Command), task B
   increments a counter — does B starve? Probes under .build/scratch/.
4. **Per-class policy recommendations for the user** (the deliverable's
   spine): which calls should gain the `blocking` annotation (= automatic
   offload; note the design-103 v1 signature whitelist may need widening —
   file that as its own finding if so); which should be reactor-integrated
   properly (fd-shaped ones); which stay prompt-by-policy with a docs
   sentence (local-disk file I/O is the industry-standard candidate — cite
   the tradeoff honestly: offloading file I/O costs a thread hop on every
   read; kernels-first Saw may prefer Rust/Go's "files are prompt" stance
   over tokio's spawn_blocking); and which are executor-internal and
   covered by design 180.

## Deliverables

The inventory table + verdicts appended to this brief; DF-181x findings
for every class-(d) call (severity by starvation impact: unbounded from a
common API = P0-adjacent); the policy menu for the user's ruling; xfail or
pin tests ONLY where a probe demonstrates starvation cheaply and
deterministically (a Command-wait starvation probe is likely pinnable; a
DNS one is not — note, don't flake the suite). NO std/rt edits.

## Explicitly out

Implementing offloads or annotations (follow-up after the user's policy
ruling); the design-103 multi-arg offload widening (file it if needed);
design 180's sleep work.
