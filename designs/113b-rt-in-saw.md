# Design 113b — the runtime layer in Saw: export loosening + relocation (queued Aug 4)

Continuation of design 113 (ABI freeze + rename LANDED; physical
relocation was deferred on a pin conflict — see the tracker's 113
entry for the full findings). USER DECISION (Aug 4): loosen the
`saw_*` export reservation so the expected runtime symbols can be
AUTHORED IN SAW, and proceed with the relocation on the maximal-Saw
model. Two independent discoveries motivated this: the 113 agent hit
the reservation as a wall for the host runtime, and the 112 agent had
to write `sos/kernel/rt.c` in C for the same reason — the seam bodies
were otherwise expressible in Saw.

## Decisions (user + lead, Aug 4)

1. **Runtime-build compile mode** (pin, veto-able: `--runtime-build`
   flag). Ordinary compiles keep the full reservation — `@export` of
   any `saw_*`/`__saw*` name stays rejected (users must not hijack
   runtime symbols). Under `--runtime-build`:
   - `@export("__saw_rt_<name>")` is allowed for EXACTLY the frozen
     ABI set (sawc/rt/ABI.md) — the compiler already knows the list
     because it declares it; exporting a non-ABI `__saw_rt_*` name is
     an error naming the valid set (typo protection). Other reserved
     names stay rejected even here.
   - The compiler SUPPRESSES its own auto-declaration of the seams
     the module defines (no declaration/definition collision — the
     gap the 113 agent identified as needing "a runtime-build
     profile").
   - The module is SYNC-ONLY: suspending constructs, spawn,
     TaskGroup, channels are rejected — the runtime sits below the
     machinery that needs it. (Deeper discipline — a seam body must
     not transitively depend on its OWN seam, e.g. alloc must not use
     Vector/String/Box — is ABI.md guidance + review, not
     compiler-enforced in v1.)
   - Composes with both hosted and `--freestanding` targets: the SOS
     kernel later authors its seams in Saw the same way.
2. **Maximal-Saw host runtime + a three-symbol C shim.** Everything
   the tracker's "expressible in Saw today" list covers relocates as
   Saw (alloc/dealloc, sleep, clocks, errno family, sin_set_family,
   op-budget, the reactor incl. kevent/epoll structs). The three
   DF-blocked bodies stay in ONE small documented `shim.c` per the
   sanctioned-exception rule: `__saw_rt_write`/`_panic` (extern C
   global `stdout`, DF-113a), `__saw_rt_pthread_create` + the offload
   thunk (C function pointer, DF-113b), `__saw_rt_set_nonblocking`
   (variadic fcntl, DF-113c). The shim shrinks to zero as the three
   FFI features land (queued as future designs in the tracker:
   extern C globals; a C function-pointer type; variadic externs).
3. The ABI itself is FROZEN (113) — nothing here may change a symbol
   name, signature, or contract. Behavior stays byte-identical where
   observable.

## Scope

1. The runtime-build mode (decision 1): flag, reservation loosening
   with the exact-ABI-set check, seam-declaration suppression,
   sync-only enforcement, tests for each rejection (error tests: bad
   export name under the mode, reserved export without the mode,
   suspending body under the mode).
2. `sawc/rt/` sources: `common/` (OS-independent bodies + the shared
   struct decls), `host_macos/`, `host_linux/` (kqueue vs epoll
   reactor, errno symbol, timespec details), `shim.c` (the three
   bodies, heavily commented, each naming its DF-finding). Saw code
   follows the saw-lang skill; the `sync` discipline and design-81
   unsafe markers apply as to any Saw code.
3. Relocation: delete the IR body synthesis for every relocated seam;
   hosted builds declare + link. Per-seam-group commits (misc/alloc/
   clocks first, then reactor, then threads+offload via shim), full
   suite green each.
4. Build/cache/link machinery: runtime objects built with sawc
   (`--runtime-build`) + clang (shim) into `.build/rt/`, keyed on
   source hash, auto-added to hosted link lines; `-v` lists the
   objects; a clear error if the runtime itself fails to build.
5. Negative test: freestanding compile still EXTERNS the seams and
   auto-links NO runtime (the harness symbol-inspection directive the
   113 agent noted as missing — add the minimal form needed).
6. Docs: ABI.md gains an "authoring a runtime in Saw" section
   (runtime-build mode, the shim exceptions + their DF numbers);
   CLAUDE.md repo map + dev usage; tracker 113 entry closed out,
   remaining-scope items moved here. LANGUAGE_SPEC + skill get the
   runtime-build mode noted under @export (it changes an error's
   contract: reserved-name rejection now names the mode).

## Non-goals

The three FFI language features themselves (own designs); the SOS
kernel's rt.c → Saw conversion (rides the next SOS brief, M1, once
this lands); moving the cooperative scheduler; Windows.

Bars: full suite zero xfails + bootstrap green per commit (bootstrap
after every seam-group relocation — blade is the heaviest runtime
consumer); per-unit commits; linear history; no attribution trailers;
foreground suites; interruption-safe; discoveries tracker-flagged,
not scope-crept; every NEW place Saw can't express a runtime body is
a DF-finding. SEQUENCING: dispatch only AFTER design 112 integrates
(112 carries codegen touches in calls.py/core.py that must reconcile
first); designs 114/115 remain queued behind THIS brief.
