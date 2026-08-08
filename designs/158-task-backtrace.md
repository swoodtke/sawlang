# Design 158 — logical task backtraces from coroutine frames

**Status: APPROVED + QUEUED TO DISPATCH (user, Aug 8 — "add 158 to the
queue"; do NOT launch until the running queue drains + user restarts).
Devtools/debugger track; PIN: the in-process dump (unit c) lands BEFORE
SOS M2 interrupt bring-up starts — task dumps under QEMU are the payoff
that sold the design. Compiler/tooling surface, disjoint from the net
track (182/183/184) — parallel-eligible once dispatch resumes.**

## Why this is cheap for Saw

A suspended task is ONE flat allocation: the root frame with every
suspending callee's frame embedded BY VALUE at a compile-time-known
offset, each frame carrying a state index naming its resume point. The
logical stack is therefore a pure static table walk — no pointer
chasing: root state index → (parked at line N | active embedded child
C at offset K) → recurse → leaf's state index → the actual parked
line. The compiler HAS the embedding tree and state→line maps during
the coro transform and currently discards them after codegen.

## Units

1. **The tables, in-binary.** Per monomorphized suspending function:
   (state → source line | active child symbol + frame offset), plus
   the frame-layout roots, encoded as ONE compact read-only blob
   linked into its own section (`@section`-style, same mechanism the
   compiler already has). One encoding serves both consumers: the
   lldb script reads the section out of the target, the in-process
   walker reads it at a link-time symbol. Keyed by monomorphized
   symbol (a `Dual_mix$2$T$U` instantiation is its own entry). Behind
   a flag is WRONG here — the tables are small and always-on is what
   makes the panic dump exist when you didn't plan to need it; size
   is measured and reported in the summary (veto point if large).
2. **`tools/lldb_saw.py` — `saw tasks` / `saw bt`.** lldb Python
   command: locate the executor's task table through its known
   globals, walk the slots GENERATION-CHECKED (design 134 reuses
   slots — a stale handle's frame must never be decoded), decode each
   live frame through the section tables, print one logical backtrace
   per task with real `file:line` frames (Go's goroutine dump is the
   model). Process is stopped under lldb, so the walk is safe.
3. **The in-process dump — the SOS seller.** A runtime/debug function
   that walks its own task slots and prints every live task's logical
   backtrace through the ALLOC-FREE path (design 137 format args,
   `__saw_rt_write` seam — must work freestanding and under allocator
   exhaustion). Wired into the panic path: a panicking program prints
   its task dump after the panic line. Hosted AND freestanding; on
   SOS under QEMU this is the kernel task dump. v1 honesty: the walk
   reads slots without cross-thread synchronization — at panic time
   in an MT group that is best-effort by design; say so in the output
   header ("tasks as-of panic, unsynchronized") rather than
   pretending. Single-threaded groups are exact.

## v1 fences

Read-only reconstruction (no stepping across suspends, no resume
manipulation); no variable decoding inside frames (that is DWARF
Part 2's job — design 69's line-tables-only scope note stands);
gdbstub/GDB script variant deferred (the section format is the
contract, so a GDB port is mechanical later).

## Tests / gates

A known nest (task → helper → net read, parked) dumps the expected
three-frame logical stack, exact lines, hosted; the same shape in an
MT group; a slot-reuse case proves generation checking (dump after
churn shows only live tasks); freestanding/SOS: a QEMU test boots,
panics deliberately, and the harness asserts the task dump in the
serial output; lldb script exercised by a scripted lldb batch run in
a test (skipped where lldb is unavailable). Full battery: suite (zero
xfails), lexdiff, astdiff, irdet --all (venv), bootstrap, sos_runner.
