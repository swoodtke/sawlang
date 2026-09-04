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

**U2 — DF-300a: the enum payload union is WORDS, not bytes (RULED Sep 4,
UNGATED).** The user ruled the fix in regardless of U0's share ("even if the
improvement is less than 5%"): the payload union's storage type becomes a
WORD array — `[M x iW]`, W the TARGET word width (i64 on the 64-bit hosts,
i32 on riscv32) — instead of `[N x i8]`, accepting that every
payload-carrying enum rounds up to at least word size and word alignment.
This fixes BOTH sides at the type: SROA over a word array decomposes to word
stores/loads, so construction, extraction, moves and by-value passing all
copy at word granularity with no per-site conversion, and the byte-shred
pattern cannot regrow at a missed position (the type IS the funnel —
obligation 1 satisfied structurally; the docstring on the union-type builder
names it).
Sweep still owed (obligation 4's siblings, now as VERIFICATION rows rather
than conversion sites): construction (`Optional.Some`, `Result.Ok`/`Err`,
user enums), match-arm extraction, by-value argument/return — each checked
word-granular in the emitted code.
LAYOUT-CHANGE DILIGENCE (the ruling's cost, made visible):
- U0 gains a row: enumerate every std/corpus enum whose size or alignment
  GROWS under word-rounding (`Optional<Byte>`/`Optional<Bool>` and small
  raw-payload enums are the candidates) and report the deltas — including
  the sos image's .bss/RAM movement, since arrays of small optionals get
  wider. Report, not gate: the trade is accepted; the numbers still land.
- The `__saw_rt_*` seam: rt/ABI.md's frozen contract — check whether any
  seam-crossing type carries a payload enum by value; the `abidoc` lane
  gates it, and a genuine seam-layout change STOPS the unit for a ruling
  (the seam is the one frozen layout in the language).
- Layout readers: `--emit-frame-layout` / bt-table regenerate (sizes may
  shift — fine); UnsafeMemory corpus uses swept for anything assuming enum
  size/alignment; serde encodes logically and is unaffected by layout.
Acceptance: the map instantiation's 60-instruction return assembly collapses
to word stores (~6 — that check is the pin); sos image + bench deltas
recorded; reemit+irdet mandatory (IR-changing).

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
