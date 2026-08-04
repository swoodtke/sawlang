# Design 113 — runtime extraction: __saw_rt ABI + per-host runtime (queued Aug 4)

User direction (Aug 4): codegen currently SYNTHESIZES the host-OS
runtime in LLVM IR — kqueue/epoll reactor, pthread wrappers, the
blocking-offload pool — selecting behavior by target triple at IR-gen
time. Move that host knowledge OUT of the compiler into a per-host
runtime library that hosted builds link, so a runtime for SOS (both
kernel-side and SOS-hosted binaries) is a link-time swap, not
compiler surgery.

The seam already half-exists: all OS interaction funnels through a
closed set of named synthesized functions, and the freestanding
profile ALREADY emits those seams as external declarations
(core.py:105) expecting the kernel to supply them. This design
completes the seam: hosted builds get their bodies from a linked
runtime too, and the symbol set becomes a frozen, documented ABI.

## The ABI split (pinned rule; user, Aug 4)

Two symbol tiers, named by prefix:
- **`__saw_rt_*` — the runtime ABI.** Functions a RUNTIME implements;
  the compiler only declares + calls them. Today's inventory (sweep
  for stragglers; names shown post-rename): reactor
  (ensure/fd/register/poll/wake + the wake pipe), pthread wrappers
  (create/join/mutex_init/cond_init), offload pool
  (start/done/take/pipe_fd/thread), clocks
  (clock_monotonic_nanos/unix_timestamp_secs), sleep
  (sleep_ms/blocking_sleep), errno family
  (errno/errno_would_block/errno_connect_state), set_nonblocking,
  sockaddr helpers (sin_set_family — libc STRUCT LAYOUT knowledge is
  runtime material, sweep for more), alloc/dealloc, write, panic
  sink, argc/argv storage.
- **`__saw_*` — compiler-internal helpers.** Synthesized IR with no
  OS knowledge (string retain/release/alloc, atomic helpers,
  op-budget, print_int): stay in codegen, renamed to the uniform
  prefix where they deviate (`saw_module` etc.).

The rename is part of THIS brief — the ABI freezes here, and renaming
after other runtimes implement it would break them. Grep-audit at the
end: no synthesized/declared symbol outside `__saw_rt_*`/`__saw_*`.

## The runtime library

- **Written in Saw** (user + lead call, Aug 4): extern libc
  declarations + `sync` functions + UnsafeMemory for the
  kevent/epoll_event/sockaddr structs. Rationale: dogfood; the `sync`
  effect CHECKS the core runtime rule (nothing in the runtime may
  suspend — it implements suspension); the SOS-hosted runtime will be
  Saw anyway, better as a sibling than a C port. A small C/asm shim
  is the DOCUMENTED exception if a specific body genuinely cannot be
  expressed — each such case gets a tracker entry (it is a language
  gap worth knowing).
- Layout (pin, veto-able): `sawc/rt/` with `host_macos/` and
  `host_linux/` module dirs + shared `common/`; selected by target
  triple at build time (the module-path mechanism — same machinery
  the kernel HAL will use, spec §5b).
- Runtime code compiles with sawc itself under a no-concurrency
  discipline (no TaskGroup/spawn/channels — it sits BELOW them);
  freestanding-profile compile keeps it honest about hidden hosted
  deps. Objects are built + cached per host under `.build/rt/` and
  added to the link line automatically for hosted builds; `-v` shows
  the extra objects. Cache keyed on runtime-source hash — a stale-rt
  bug would be miserable to debug.
- The ABI is documented in `sawc/rt/ABI.md`: every symbol, signature,
  semantic contract (esp. the reactor: one-shot rearm, the design-91
  token = parked frame's wake-word address, poll timeout semantics,
  the design-102 cancel-wake path), and the four intended
  implementations (host_macos, host_linux, sos-hosted, kernel/none).

## Scope

1. Freeze + rename the symbol set (both tiers); sweep codegen for
   OS knowledge hiding outside the named seams (sockaddr layout
   found already; check errno access mode, fd flags, anything
   triple-conditional that is not codegen-shape).
2. Stand up `sawc/rt/` (Saw source, both hosts) implementing the
   `__saw_rt_*` set; delete the IR body synthesis; hosted builds
   declare-and-link exactly like freestanding declares.
3. sawc link step: build/cache/link the runtime objects; clear error
   if the runtime fails to build (it is now part of every hosted
   compile).
4. Tests: the FULL suite is the real test — every concurrency/net/
   spawn test exercises the seams; zero xfails on macOS AND the CI
   linux job is the acceptance bar. Bootstrap loop too (blade is a
   heavy runtime consumer). Add one negative test: freestanding
   compile still externs (no runtime auto-linked).
5. Docs: CLAUDE.md repo map + dev-usage note (`sawc/rt/`, cache
   dir); ABI.md as above; tracker entry closed. LANGUAGE_SPEC/skill
   untouched (no language-surface change).

## Non-goals

The SOS runtimes themselves (kernel briefs); moving the cooperative
scheduler/executor or coroutine frame machinery (OS-independent
codegen, stays synthesized — a later design may lift it into Saw);
Windows; changing any seam's SEMANTICS (this is a mechanical
relocation + rename — behavior byte-identical where observable).

Bars: full suite zero xfails + bootstrap green per commit; per-unit
commits (rename tier-by-tier, then relocate seam-by-seam — reactor,
threads, offload, misc — each with the suite green); linear history;
no attribution trailers; foreground suites; interruption-safe; new
discoveries tracker-flagged, not scope-crept. SEQUENCING: may run
CONCURRENT with design 112 (disjoint trees); design 114 waits for
this to land (both touch the typechecker/codegen intrinsic surface).
