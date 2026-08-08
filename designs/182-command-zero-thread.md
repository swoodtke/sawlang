# Design 182 — Command without threads, and the two honest sentences

**Status: APPROVED (user, Aug 8 — the 181 policy round + the zero-thread
ruling). Scope shrank when DNS became the offload test case (183/184): this
brief no longer touches the offload machinery at all.**

## Units

1. **Command goes zero-thread.** The child's stdout pipe becomes a
   nonblocking fd parked on the reactor (the exact `TcpStream.read`
   machinery — the 181 audit's "model the rest should follow"); the child
   WAIT parks on the reactor too: `pidfd_open` + epoll on Linux,
   `EVFILT_PROC`/`NOTE_EXIT` on kqueue. No offload thread anywhere in
   Command. Seam changes documented in rt/ABI.md (a wait-fd acquire +
   reap seam per host); `run()`/`output()` signatures unchanged.
   ACCEPTANCE: the 181 starvation xfail
   (`examples/process_run_starvation_xfail.saw`) FLIPS — marker off in the
   fixing commit, sibling's first tick asserted early — plus an
   output-variant twin and a cancel-during-child test (the design-102
   discipline: cancel wakes the parked task; the CHILD is not killed —
   document that policy in the docstring).
2. **The fs sentence** (ratified prompt-by-policy): std.file/std.directory
   docs state the contract — synchronous by design, prompt on healthy
   local disks, can stall on network mounts/FIFOs/special files; the
   io_uring note goes in the tracker as the future escape hatch.
3. **The recv sentence**: `Channel.recv` docs state the consequence
   (unbounded thread block; never from a cooperative task — `receive` is
   the cooperative twin).

## Gates

Full battery per unit (suite zero uncited xfails, lexdiff, astdiff,
Saw-irdet --all, bootstrap, gmgate, sos both arches) + ten stable repeats
of the new Command concurrency tests (scheduler surface — the 180
precedent). DF-182x findings as usual.

## Explicitly out

The offload machinery (183); resolution/DF-181d (184); killing the child on
cancel (a future Command.kill design); Windows anything.
