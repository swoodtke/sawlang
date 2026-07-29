# Handoff — Saw language + SOS kernel project

Purpose: let a fresh Claude Code context resume this work after a
`/clear`. Everything durable is in git; this file is the meta-layer
(workflow, queue, in-flight state, caveats). **Read `designs/todo.md`
first — it is the master tracker** (all decisions D1–D16, every brief's
status, all ledger/dogfood findings).

## What this project is
`sawc/` — a compiler (Python + llvmlite) for **Saw**, a systems
language (Rust safety + Swift ergonomics, no lifetimes, deterministic
destruction). Also: **Blade** (`blade/`, package manager in Saw, the
App-1 testbed) and **SOS** (`sos/spec.md`, a capability microkernel
design targeting ESP32-P4/riscv32, App-2).

## How work has been run (the pattern — keep doing this)
- Design decisions are made WITH the user (AskUserQuestion), recorded
  as `designs/NN-*.md` briefs, then implemented by **Opus subagents**
  dispatched via the Agent tool (`subagent_type: general-purpose,
  model: opus`), ONE at a time, sequentially. Each agent works on
  `main`, commits per coherent unit, keeps the suite green (zero
  xfails), and reports back. I record results in `designs/todo.md` and
  dispatch the next.
- **Before dispatching agents: re-arm caffeinate** — the user's Mac
  sleeps on idle and kills long agents (see memory
  `caffeinate-during-agent-runs`). Run `caffeinate -is -t 21600 &` and
  confirm `pgrep caffeinate`. Kill it when the queue is idle.
- **Commit hygiene:** NO `Co-Authored-By` trailer (memory
  `no-coauthored-by-trailer`). Infra/tooling/docs commit to `main`;
  the user prefers small commits. Backtick-bearing messages need
  `-F <file>`.
- **Index-race caveat:** while an agent is committing, DON'T `git add`
  my own doc edits — they get swept into the agent's commit. Either
  wait for the agent to finish, or accept the bundle. Content always
  lands; only the commit boundary blurs.
- **Agents keep slipping on command hygiene** (heredocs, `sed`, inline
  `python -c`, `git add -A`). Remind every dispatch; it's in CLAUDE.md.
- Full test suite ~1 min uncontended; `./.venv/bin/python
  test_runner.py`. Never run two suite invocations at once.

## Current state — CLEAN, recovery complete
- **Suite: 542 passed, 0 xfails.** Both brief 49 (recommit `307f9e4`)
  and brief 48 (`ea3021b`) landed; tree clean (only this handoff.md
  was untracked, now committed). Verify: `git log --oneline -4` +
  `./.venv/bin/python test_runner.py`.
- (History note: brief 49's original commit was silently lost; brief
  48's agent recommitted 49 and landed 48 together — that recovery is
  DONE, nothing pending from it.)
- **NEXT TO DISPATCH: brief 55** (overloading, exact-match model) —
  land before the N-family. Re-arm caffeinate first, then dispatch an
  Opus agent per the pattern below.
- **WATCH:** two agents this session CLAIMED to commit but didn't (or
  a 500 ate it). After every agent lands, VERIFY `git log` shows its
  commits and `git status` is clean BEFORE marking done / dispatching
  next. Don't trust the agent's "committed" claim alone.
- Async stage 2 is COMPLETE (briefs 44/45/52/52b): source-level
  coroutine transform (all control flow), TaskGroup multi-task runtime,
  cooperative spawn/join/cancellation. `any Trait` existentials landed
  (51). UnsafeMemory (46), platform-width Int/riscv32 (47), bitwise
  (50), allocators/Box/slab (28/37/42), statics/Atomic (41).

## The queue (dispatch order, all decided + briefed)
1. ~~48~~ DONE (`ea3021b`). ~~49~~ DONE (`307f9e4`).
2. **55** overloading (`designs/55-overloading.md`) — exact-match
   model; land BEFORE the N-family so stdlib APIs use it. Also does the
   `loop`+`ref` keyword drop and the type-carried-unsafety spec note.
3. **N-family (need-to-have, App-1/App-2 blockers)** — briefs to be
   WRITTEN (see tracker "NEED TO HAVE"): N1 trait default method
   bodies, N2 Display+interpolation, N3 Error trait (on `any`), N4 Map
   iteration + parse helpers, N5 std.time, N6 minimal attributes + C
   exports (kernel `_start`), N7 remaining `extension Int` etc.
   Suggested grouping: N1–N3 "formatting & errors" family, N4/N5/N7
   "Blade enablers", N6 "attributes/exports".
4. **53** ergonomics family (default params, `..=`/enumerate,
   Int.max/min + literal suffixes, `\u{}`, import aliasing,
   static_assert, use-before-init probe, **DF1 `let _` discard**).
5. **54** collections family (Set + collection literals; after 48).
6. **Stale-spec pass** — fix the doc contradictions + verify the four
   spec/TODO conflicts (tracker "Resolved-by-decision / stale-spec").
7. **A1a-remainder / small fixes**: DF2 (Command wait-status /256 bug —
   real std/process fix), DF3 (call-site Int→Int? auto-wrap), the
   52b/52 v1 gaps (TaskGroup-in-suspending-fn, if-let suspension
   split, first-class ch.receive), enum_payload/if-let ledger items.
8. Then **Blade for real** (resolver/semver/lock/git/incremental) and
   the **SOS kernel** (boot protocol + syscall ABI are the next OS
   decisions; §5 of sos/spec.md).

## Open decisions still needing the user (none block the queue above)
- SOS: boot protocol, syscall ABI (sos/spec.md §5.6/§5.10-ish).
- D10 Cortex-M0 atomics (waits for a port).
- A5 effect-polymorphism (blocks generic suspending functions).
- Set/HashMap Map-deprecation timing.

## Key durable references
- `designs/todo.md` — master tracker (READ FIRST).
- `designs/NN-*.md` — every decision + brief (01–55).
- `sos/spec.md` — kernel design.
- `LANGUAGE_SPEC.md`, `CLAUDE.md` — language spec + project rules.
- Memory files (`~/.claude/.../memory/`) — caffeinate, no-coauthored-by,
  commit-location, critique-workflow conventions.
- Pyright diagnostics stream is NOISE (mixin `self.X` false positives);
  ignore unless a real behavior test fails.
