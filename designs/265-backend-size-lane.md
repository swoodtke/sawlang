# Design 265 — the back-end size lane: `-Os`/`-Oz`, the machine outliner, riscv save-restore, and DF-300a's enum-construction stores

**Status:** SCHEDULED Sep 4 2026 (user: next after design 264 integrates —
"this is bloating the image sizes"). The tier design 263's record named and
left unauthored. Closes DF-300a (or parks it with numbers — see U2's
kill-criterion). Codegen/back-end surface; serial with 264 (both touch
codegen), 207 slides one queue slot.

## The lesson this brief is built around

This family's diagnoses have been REFUTED BY MEASUREMENT twice: design 261's
aggregate-copy diagnosis (A) moved the image -0.3%; design 263's U1 panic
scratch STANDALONE cost +3,122 B and its U3 narrow-field-read moved +14 B,
because the backend was already doing both. The wins came from what
measurement found (U2 outlining -18%, U3b indexed reads -67% cumulative). So:
**U0 is a census, every fix cell carries a kill-criterion, and no cell's
leverage is assumed** — the flags cell (U1) is the only sure thing, because
back-end size levels are LLVM's own, not a diagnosis of ours.

## Baseline + acceptance harness

Post-263 sos baseline: `process_isolation.elf` .text+.data+.rodata
**140,776 B** (riscv32 virt). Recipe (shallow clone already at
`.build/scratch/sawos/`):
`SAWLANG_ROOT=<tree> .venv/bin/python .build/scratch/sawos/tools/sos_runner.py
--arch riscv32 --case process-isolation -j 1`.
Gates every unit: full suite + freestanding (both arches); `bench` lane
(checksums GATE, timing report-only); design 137's observable contract — all
running panic examples byte-identical stdout+stderr at the DEFAULT level
(263's precedent). Terminal: full battery.

## Units

**U0 — the census (no code change).** What is the post-263 image made of?
Disassemble + classify the 25,298 instructions (263's tooling precedent):
specifically attribute (a) byte-wise enum-construction/extraction chains
(DF-300a's `lshr`/`strb` signature and its riscv spelling), (b) remaining
load/store mass by producer, (c) outliner-shaped repetition (candidate
sequences the machine outliner would fold). Output: a bytes-by-producer
table in the landing note — it prices U2 and predicts U1's outliner leg.
Host-side too: count the pattern across 5 representative examples/ binaries
(map's 60/166 instructions is the seed datum, `.build/scratch/dis_map*`).

**U1 — the flags (the sure thing).** `-Os`, `-Oz` — and `-O2` (user asked
Sep 4: "would we get perf from O2?"; the answer is a measurement, and the
plumbing is identical) — on sawc:
- The whole level set maps through the ONE existing funnel
  (`core.py` `create_pipeline_tuning_options(speed_level=1)`): `-O2` is
  `speed_level=2`, the size pair is `size_level` + `optsize`/`minsize`
  attrs. No `-O3` (rarely beats O2; add only if a measurement ever asks).
- `-O2` expectation, stated so the bench numbers land against a
  prediction: wins on sync scalar compute (stronger inlining, GVN,
  vectorization); MUTED on idiomatic checked loops — always-on
  bounds/overflow checks put a side-effecting exit in every iteration,
  which usually blocks the vectorizers, and visitor-boundary closures are
  indirect calls O2 cannot inline in outlined generic bodies (DF-300a's
  map disasm is the shape). Record bench O1 vs O2 vs Os vs Oz in the
  landing note; compile-time cost of O2 recorded too (it will be slower —
  that is why the DEFAULT stays O1 regardless).
- CLI + pipeline: map to LLVM's size levels (function attrs
  `optsize`/`minsize`, pass-builder size level, TargetMachine opt level).
  Default UNCHANGED (O1) — freestanding does NOT imply a size level; sos
  opts in explicitly (lead-recommended, confirm at dispatch).
- The MACHINE OUTLINER enabled under `-Oz` (LLVM's own bundling;
  lead-recommended, confirm at dispatch), plus riscv save-restore
  (`+save-restore` or the function attribute) for the freestanding riscv
  targets under size levels.
- Tests: COMPILE-FLAGS-pinned examples per flag (run + expected output —
  semantics identical at every level); the flag joins `sawc.py`'s
  documented set; README/spec per design 125.
- Measure: sos image at `-Oz` vs baseline; bench at `-Os`/`-Oz` (checksums
  must hold; timing reported, regressions expected and acceptable at -Oz —
  record them).
- IR determinism: the new levels must be deterministic (two compiles
  byte-equal, reemit's in-process double-compile shape) — pinned by a test,
  since irdet's corpus runs the default pipeline and will not police these.

**U2 — DF-300a: typed enum-construction stores (conditional on U0).**
KILL-CRITERION: dispatched only if U0 attributes a material share (lead
guidance: ≥5% of post-263 .text, or the host census shows the pattern
dominating call-boundary code) — otherwise DF-300a is PARKED with U0's
numbers recorded on its entry, not fixed speculatively.
The fix: route the enum payload store through the variant's typed layout
(GEP into the union scratch / memcpy from a typed scratch) instead of the
`[N x i8]` byte spelling, at ONE funnel — the enum-construction emission —
with the SWEEP over the sibling positions DF-300a names: every
payload-carrying construction (`Optional.Some`, `Result.Ok`/`Err`, user
enums), match-arm payload extraction (the read side), by-value enum
argument/return positions. Obligation-1 shape: the emission goes through one
chokepoint whose docstring names its entry points, or the brief's position
matrix is tested row by row. Acceptance: the map instantiation's return
assembly collapses to word stores (the 60 -> ~6 instruction check is the
pin); sos image delta recorded; reemit+irdet mandatory (IR-changing).

**U3 — function-sections + gc-sections census (report-only).**
Emit `-ffunction-sections`-equivalent + link with `--gc-sections` on the
freestanding suite and the sos image; report bytes reclaimed. NO default
flip in this brief — the numbers go to the user, who rules whether
freestanding linking adopts it (a link-contract change owes obligation 2's
consumer sweep over linker-script/section assumptions, sos's `@section`
uses included, so it is its own follow-up if the numbers justify it).

## Ceremony

- Opus agent, isolated worktree, dispatches AFTER design 264 integrates
  (both are codegen; if they ever cross anyway, reemit+irdet in the combined
  integration gate — the 218s45×263 precedent).
- DF range at dispatch (lead assigns; next free after 264's usage).
- Per-commit suite+freestanding; terminal full battery. Suite-lock SPLIT form.
- New CLI flags are user-visible surface: the lead bumps the version at
  integration (0.8.0 if 264's 0.7.0 has been cut by then).
- No workarounds: an LLVM/llvmlite limitation that blocks a leg (e.g. no
  outliner hook) is RECORDED with the probe, the leg re-scoped, never
  hacked around.
