# Design 67 — Blade dogfood bug batch: DF6–DF12 (queued Jul 30)

Bug-fix brief; the design-64 dogfood findings, tracker has details +
repro notes. Fix in VALUE order (DF12 first — it blocks trusting
Blade's own build). Standing policy applies. Full suite + blade tests
+ `tools/blade_bootstrap.py` green per commit; zero xfails.

1. **DF12 (FIRST)** — Blade self-`build` intermittently crashes
   (SIGBUS/SIGTRAP), deterministically when stdout is a pipe; `blade
   test` reliable. Smells like memory corruption in a large program
   (heap overrun / bad retain balance / buffer sizing) surfacing under
   different allocation patterns. Root-cause with the deterministic
   pipe repro; remove the bootstrap's retry/redirect workaround once
   fixed.
2. **DF10** — optional produced in a match-arm in result position not
   wrapped (LLVM verifier error). ICE-class.
3. **DF8** — returning a struct literal with a nested-struct field
   from 2+ branches ICEs.
4. **DF7** — `if let x = opt { return }` in statement position ICEs.
5. **DF6** — generic-with-default-type-param mangling divergence
   (`Vector<T>` as a Result Ok type ICEs); un-work-around the columnar
   Vector<String> site in blade if the fix allows.
6. **DF11** — `manifest_deps_hash` returns "0" in the build flow
   (cross-module `dependencies()` takes the Err branch) → drift
   detection degraded. Root-cause the cross-module call failure (may
   share a cause with DF12/DF9's narrower combination).
7. **Blade follow-ups once the above unblock them:** re-import
   libs/semver as a real blade dependency replacing the resolver's
   self-contained matcher (this was only deferred because of the DF9
   scare — probe; it should work now); strict lock-honoring +
   `blade update` command per the design-64 brief's B4 spec.
8. Tracker: DF6–DF12 closed (or precisely re-ledgered if any resists
   with findings), design 67 landed.

Each fix gets a minimal locking test (compiler suite) + keep blade
tests/bootstrap green. Repros: reduce from blade sources into
.build/scratch first — the tracker notes name the triggering shapes.
