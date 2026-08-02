# Design 94 — enum/Result payload scratch sizing (OOB stack read) + land process module (queued Aug 2)

The deep codegen bug design 92 root-caused but couldn't safely fix.
A correctness landmine in a LOAD-BEARING path (enum/Result creation),
dormant on main only because design 92 reverted the process module
that triggered it. Fix it properly, then land the blocked process
module as the acceptance.

## The bug (root cause, from design 92)
The enum/Result CREATE paths — `_create_result_ok_for_return` /
`_create_result_err_for_return`, `_wrap_error_in_union`,
`_generate_enum_init` (codegen) — alloca the SMALLER variant struct but
bitcast-LOAD the FULL `[N x i8]` payload: an out-of-bounds stack read
of whatever follows the smaller alloca. Layout-sensitive arm64
heisenbug (garbage pointer / translation fault, ~40% on blade's large
`build` frame; flaked `blade build --force` before the design-92
8-align fix masked one manifestation).

The KNOWN fix (alloca the FULL payload `[N x i8]`, not the smaller
variant) is suite-green BUT shifts the frame and TIPS ANOTHER latent
`Builder_build` bug (blade went 8→20/20 test outcomes). So this is a
CHAIN of frame-layout-sensitive latent bugs — the classic "fix one
heisenbug, expose the next."

## Scope
1. Fix the create paths to alloca the FULL payload size (`get_abi_size`
   of the biggest variant / the declared `[N x i8]`), never a smaller
   variant, so no create/return path ever reads out of bounds. Audit
   ALL enum/Result create + extract sites for the same smaller-alloca-
   full-load mismatch (extract side too — symmetry).
2. Then CHASE the `Builder_build` bug the fix exposes to its ROOT
   CAUSE — do NOT stop at "suite green but blade flakes." Use
   libgmalloc / guard-malloc + the deterministic repro discipline that
   cracked designs 85/86 (run blade build/--force under the guard
   allocator many times; a heisenbug that's ~1/3 is deterministic
   under gmalloc). Expect it to be the SAME class (a slot sized/
   aligned/offset wrong for a pointer-containing payload). Fix it
   properly. If a THIRD is exposed, keep going — the goal is the whole
   enum/Result frame-layout family correct, verified deterministic
   under gmalloc, not just suite-green.
3. **ACCEPTANCE: re-land the process module** (design 92 item 1,
   reverted): `Command.run() -> Result<Int32, ProcessError>`
   (Ok(code)=exited; Err=couldn't launch) + its forced-failure test
   (run of a nonexistent command → Err). With the payload bug fixed it
   should land clean; blade build/--force must be RELIABLE (run it
   10x + under gmalloc, zero faults) — that reliability IS the proof
   the codegen chain is fixed.
4. Docs: tracker (design 94 landed; the enum/Result payload family
   closed; process module landed); saw-lang skill note if any process
   signature is user-facing.

## Hazards
- Frame-layout changes ripple — every enum/Result monomorphization
  shifts. The full suite + bootstrap + BLADE BUILD RELIABILITY (not
  just one green run) are the oracle; a single green run is NOT proof
  for a heisenbug — run repeatedly + under gmalloc.
- Don't just move the landmine (a fix that greens the suite but shifts
  the fault elsewhere is not done — the design-92 agent already hit
  that once; go to root cause).
Bars: full suite (baseline 897) + blade/libs + bootstrap green per
commit; blade build/--force reliable under gmalloc; zero xfails.
Standing policy; foreground suites; interruption-safe; saw-lang skill
self-review.
