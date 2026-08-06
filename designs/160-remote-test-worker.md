# Design 160 — remote test worker (sandboxed, no SSH)

**Status: APPROVED (user, Aug 6). The user's pin shapes the whole
design: NO SSH — "i would prefer to not do this via ssh so i can
sandbox the process in which the tests run." The Studio runs a fixed
daemon the USER launches under a sandbox; only jobs cross the wire.
Concurrent-eligible with 159 (runner/tools surface); integrates
SECOND if both touch test_runner.py.**

## Architecture

1. **`tools/test_worker.py` — the daemon.** Binds a configurable
   address/port (LAN), bearer-token auth (token FILE, default
   `~/.config/saw-worker/token`; env var override). Two operations:
   submit job (a tree snapshot — tar of the repo minus `.venv`/
   `.build`/`.git` — plus a shard spec or battery spec) and stream
   results (JSONL verdicts as they complete). The daemon is small,
   fixed, and inspectable; it NEVER executes shipped code in its own
   process. Every job runs in a CHILD process tree the daemon spawns
   — which is the user's sandbox boundary. Worker keeps its own venv
   (path in its config); jobs use it.
2. **`tools/test_worker.sb` — the shipped sandbox profile** for
   `sandbox-exec`, allowing exactly what the suite needs and nothing
   else: the job work directory (fresh per job, purged after),
   loopback-only networking (net tests bind localhost ports),
   subprocess exec (std.process tests spawn children), read of the
   worker venv. Comments in the profile explain each allowance — it
   doubles as the suite's security-surface documentation. The
   recommended launch line (README + TESTING.md):
   `sandbox-exec -f tools/test_worker.sb python3 tools/test_worker.py
   --bind <lan-ip>:PORT`. A dedicated low-privilege account composes.
3. **Client: `test_runner --remote URL`.** Deterministic HASH-based
   shard assignment weighted by core count (a failing test always
   lands on the same machine — reproducibility beats balance); local
   and remote shards run CONCURRENTLY; one merged summary keeping the
   exact tail format; per-test origin marked in failure output.
   **Graceful degradation is a hard requirement**: unreachable/
   timed-out/token-refused worker → the run completes locally with a
   note, never a hang, never a red caused by infrastructure. Remote
   compile AND execute stay on the worker (both machines arm64 macOS
   — binaries never cross the wire).
4. **`irdet --all --remote URL`** — same sharding (per-file
   independent; the second-longest gate roughly halves).
5. **Battery mode**: submit a whole worktree + "run the battery" spec
   (suite, lexdiff, astdiff, irdet --all; SOS stays LOCAL in v1 —
   QEMU on the worker is a follow-up the user can opt into). This is
   the agent-workflow win: a finishing agent's gates run on the
   Studio while the next agent starts locally.

## Validation (no Studio required)

The agent proves everything against a LOCALHOST worker launched under
the shipped sandbox profile: sharded suite matches a local-only run
verdict-for-verdict; kill-the-worker-mid-run degrades gracefully;
token refusal degrades; the battery mode round-trips. Deployment to
the Studio is then: copy repo, create venv, run the launch line —
documented in TESTING.md, no inbound SSH ever enabled.

## Tests / gates

The validation above scripted as runner self-tests where feasible;
full battery on the final tree: suite (zero xfails), lexdiff,
astdiff, irdet --all, bootstrap, sos_runner (all local). TESTING.md +
README document the worker; tracker notes the deployment steps for
the user.
