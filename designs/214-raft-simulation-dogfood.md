# Design 214 — Raft under deterministic simulation: the integration dogfood

**Status: FUTURE WORK. Not scheduled, not ruled, no units authored.** This
brief exists to record the intent, the proposed architecture, and the
enabling work the Aug-12 investigation found missing — so that when it is
scheduled, the ruling session starts from facts rather than from scratch.
Detailed per-stage briefs are deliberately NOT written yet.

## Intent

Every dogfood program the tree has so far (semver, toml, blade, the design-203
wave-1 specs) exercises parsing, data structures, and one axis of the runtime
at a time. None of them puts the whole language under simultaneous load, and
none of them has a correctness oracle stronger than "it ran and the output
matched".

Raft does both. It is the standard distributed-consensus algorithm — a
cluster agreeing on one ordered log despite crashes, delays, drops, and
reordering — and it has four published safety invariants that a test can
actually assert. It is also, specifically, the shape that stresses the bet
Saw has made:

- **Ownership without lifetimes, under concurrency.** A Raft node is a tick
  loop, N outstanding peer RPCs, and a client apply path, all wanting the
  same node state. This is exactly where Rust reaches for lifetimes and
  where Saw has instead bet on the Law of Exclusivity plus
  references-across-suspend (88/106/199/201). If the bet is wrong, Raft is
  where it breaks. If it is right, Raft is the demonstration.
- **The concurrency model end to end** — suspension in expression position
  (120), cancellation of in-flight RPCs when a term advances (102/180),
  eager TaskGroup teardown when a leader steps down (124), the op budget on
  loop backedges (127).
- **The fallible surface.** Raft is mostly error paths: network errors
  distinct from EOF (92), disk errors, `Result`-discard as a compile error
  (151).
- **The wire.** Raw-backed enums (145) plus std.cbor (169) plus
  Serialize/Deserialize, which is the combination 145 was justified by and
  has never carried a real protocol.

The motivating remark: "Go still has not yielded a correct implementation of
Raft or Paxos." The word doing the work there is *correct*, and the honest
reading is that a decade of production use is not the same as correctness.
We are not going to close that gap either — see "What we do not claim" — but
the attempt is a better language test than anything else on the dogfood list.

## Proposed architecture

**The governing rule: the Raft node is pure and I/O-free.** Node code never
calls `Instant.now()`, never calls `sleep`, never touches `std.net` or
`std.file`. It is a state machine — inputs in, outputs out, time supplied.
Everything else is a seam with two implementations.

```
raft/node      the state machine: step(Input) -> [Output]. No I/O, no clock,
               no allocation policy of its own. THE thing under test.
raft/wire      Message enum, raw-backed tags (145) + cbor (169)
raft/seams     Clock / Transport / Storage — the three traits
raft/live      real clock, TCP transport (std.net), file log (std.file)
raft/sim       virtual clock, in-memory network with scripted drop / delay /
               reorder / partition, seeded RNG
raft/check     the invariant checker: election safety, log matching, leader
               completeness, state-machine safety; plus a linearizability
               check over the client history
```

The test loop is: pick a seed → build N nodes on the simulated seams → run a
generated fault schedule → assert every invariant after every step → on
failure, print the seed and replay it exactly. That is the
FoundationDB/TigerBeetle method, and it is the only version of this project
worth doing. A live three-process cluster proves almost nothing; a million
seeds against the paper's invariants proves something.

The seam split is not incidental scaffolding — it is itself the language
test. Abstracting time and transport behind traits, with a suspending
implementation on one side and a synchronous one on the other, is the
trait/existential/generic surface under real load.

## What Saw already has (investigated Aug 12)

- **Suspension through existentials already works, and colorlessly.** An
  unmarked trait method dispatched through `any` conservatively suspends
  (`examples/errors/any_sync_suspend.saw`, design 51). So `Transport.send`
  can suspend in the live implementation and not suspend in the simulated
  one, behind one trait, with no coloring problem and no signature change.
  This is the single most important enabler and it needs no work.
- **The executor's clock is ALREADY relative.** `sawc/std/taskgroup.saw:20-21`
  — "Earliest-deadline scheduling over relative sleeps (no wall clock
  needed)"; `__saw_exec_advance_sleep` (`taskgroup.saw:1304-1329`) subtracts
  a deadline from every sleeper. Real time enters at exactly one place: the
  reactor park at `taskgroup.saw:845-855`, which turns the earliest deadline
  into an actual nap and corrects by what elapsed. A virtual-clock mode is
  therefore a small surgical change to one branch, not a simulator built
  from nothing. This was the investigation's best news.
- **Single-threaded is the default.** `TaskGroup()` and `TaskGroup(threads: 1)`
  run the single-threaded engine with no OS threads and no lock
  (`taskgroup.saw:387-393`); MT is opt-in. Determinism has a chance.
- **Preemption is counted, not timed.** The design-127 op budget charges loop
  backedges, so the fairness backstop is deterministic by construction rather
  than a timer interrupt.
- **Cancellation reaches parked tasks** — io-parked (102) and sleeping (180
  unit 5) — which is what a term change has to do to in-flight RPCs.
- Data structures (Vector/Map/Set, places/borrows for the log), std.net TCP
  (84-92), std.file, std.time, std.cbor, Blade packaging and `blade test`.

## What is missing — the enabling work

1. **A seeded RNG. There is none anywhere in the tree.** Needed twice over:
   randomized election timeouts (Raft's liveness depends on them) and the
   simulator's fault schedule. Library-only, small. The contract matters more
   than the algorithm: explicitly seeded, reproducible, no implicit entropy
   read — a `Random()` that seeds itself from the OS would silently poison
   every replay. Should be freestanding-safe (no libc).
2. **Durability: `std.file` has no `fsync`.** The surface is
   open/create/open_append/read/write/seek/position/exists/remove/rename
   (`sawc/std/file.saw`) and nothing that forces a write to stable storage.
   Raft's durability rules are vacuous without it. Needs an `os_ops` seam
   plus `File.sync() -> Result<Void, IoError>`, and macOS needs `F_FULLFSYNC`
   rather than `fsync` to actually reach the platter. Small, but it crosses
   the frozen `rt/ABI.md` seam contract, so it is a real brief with a real
   consumer question (does every buffered writer owe a sync story?).
3. **A virtual-clock executor mode.** The logic exists (see above); what is
   missing is a way to say "advance time rather than sleep" when no task is
   io-parked. The open design questions are how a program opts in, and what
   happens if a real fd IS registered — error, or fall back to real time?
   Touches the executor, which is load-bearing for every program in the tree,
   so this is the one piece with genuine blast radius.
4. **VERIFY: is the single-threaded scheduler deterministic?** Round-robin
   over slots reads deterministic, but nothing in the tree asserts it. Owed a
   probe: same seed, same program, identical event order, repeated. If it
   does not hold, the gap is itself the finding and it blocks everything
   downstream.
5. **Waiting on one of several sources.** There is no `select`. `Channel`
   offers send / try_send / receive / try_receive / recv
   (`sawc/std/channel.saw`) — no receive-with-timeout and no first-of-these.
   A Raft node waits on {peer reply, election timeout, client request,
   shutdown}. It is expressible today by spawning a task per source that
   forwards into one channel, but that is a workaround carrying allocation
   and cancellation cost. **This is a language-design ruling, not a library
   gap:** does Saw want a `select`, or is fan-in-to-one-channel the blessed
   idiom? Probably the most interesting question on this list, and it is
   worth answering whether or not Raft ever gets built.
6. **VERIFY: `Map` iteration order.** `each`/`keys`/`values` must be a pure
   function of the insertion sequence for replay to be exact. No random
   seeding was found, so this is likely already true — but "likely" is not
   what a replay guarantee can rest on.
7. **Deadlines on I/O.** `TcpStream.read` has no timeout; the live transport
   needs one. Probably falls out of cancellation plus a timer task, but it
   has not been tried.

Items 1, 2 and 6 are cheap. Item 4 is a probe. Items 3 and 5 are the real
work, and both are worth doing on their own merits.

## Staging

Each stage is independently valuable and independently landable; the project
can stop after any of them.

- **A — Enablers.** RNG, fsync, the two VERIFY probes. No Raft code.
- **B — Simulation substrate.** Virtual-clock mode, the in-memory network,
  the seeded fault scheduler. Proven on a toy protocol (broadcast, or
  two-phase commit) — deliberately not on Raft, so the substrate is trusted
  before the thing being tested arrives.
- **C — Raft core.** Log, hard state, `step()`. Single node, no network.
  Property tests on log matching and truncation.
- **D — Leader election** under the simulator, with election safety and
  leader completeness asserted.
- **E — Replication**, commit index, apply. Full invariant set plus a
  linearizability check on the client history.
- **F — Membership changes** (the part the paper itself got wrong) and
  snapshot/compaction.
- **G — Live backend.** TCP transport, file log, real clock. **The
  acceptance criterion is that `raft/node` compiles unchanged.** If going
  live requires editing the state machine, the seam design failed and that
  is the finding.

## What we do not claim

Not a verified Raft. No machine-checked proof, no TLA+ refinement, no
implication that this closes the gap the motivating remark points at. The
claim on offer is "simulation-tested against the published invariants with
reproducible seeds", which is what the good implementations claim, and
saying more than that would be the exact overreach the remark is mocking.

## Open questions for the ruling session

- **`select` vs. the fan-in idiom** (item 5) — a language ruling with reach
  well beyond this project.
- Where does the virtual clock live: std, devtools, or a compiler mode?
- Where does the package live: `libs/raft` as a real library, or
  `devtools/dogfood/programs/`? Argues for `libs/` — it would be the largest
  real Saw program in the tree and should be built like a library, under
  `blade test`.
- Lead-authored or a design-203 dogfood target? The specs are naturally
  language-agnostic and stages C-E are exactly the 203 instrument, at a
  scale it has not been tried at. Stages A-B are lead work regardless.
- Does it join `tools/battery.sh`? It is slow. Likely a fixed small seed set
  in the ordinary suite plus a separate soak lane, on the `sawfuzz --soak`
  model, rather than a per-commit gate.
