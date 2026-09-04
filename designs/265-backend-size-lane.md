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

**U2 — DF-300a: the enum payload union is typed at the max payload's
ALIGNMENT (RULED Sep 4, UNGATED; amended same day from "words for all" to
the alignment rule, user-confirmed).** The user ruled the fix in regardless
of U0's share ("even if the improvement is less than 5%"). The rule: the
union's element type is the integer of the LARGEST VARIANT PAYLOAD'S natural
alignment — `[M x i64]` for pointerful/Int payloads on 64-bit hosts
(`[M x i32]` on riscv32), `[M x i32]`/`[M x i16]` for Int32/Int16-class
payloads, `[N x i8]` UNCHANGED for Byte/Bool-class payloads. Because an ABI
allocation size is always a multiple of its alignment, payload ROUNDING
COSTS ZERO under this rule — an aligned payload is already an exact multiple
of the element width — so the only growth anywhere is the tag-alignment
padding on enums whose payload alignment exceeds 4, and `Optional<Byte>`-
class enums keep today's exact layout. No name-based special case: `Result`,
`Optional`, and every user/kernel enum get the granularity their own payload
earns.
This fixes BOTH sides at the type: SROA over a word array decomposes to word
stores/loads, so construction, extraction, moves and by-value passing all
copy at word granularity with no per-site conversion, and the byte-shred
pattern cannot regrow at a missed position (the type IS the funnel —
obligation 1 satisfied structurally; the docstring on the union-type builder
names it).
WHY THE BYTE COPIES EXIST TODAY (verified in -O0 IR, Sep 4, the lead's
`dis_map_o0.ll` probe): the `[N x i8]` payload member has align 1, so the
payload sits UNDER-ALIGNED at offset 4 — and codegen compensates by
round-tripping every payload access through a SEPARATE `align 8` scratch
alloca via `extractvalue`/`store [N x i8]` array copies
(`err_payload_alloca` et al.), doing typed access only on the scratch.
Those array copies are DF-300a's shred. Once the union is typed at the
payload's alignment, the slot is correctly placed IN SITU and the scratch
round-trip loses its purpose: the fix should DELETE the scratch dance
(direct typed access through a payload GEP), not merely re-type the copies
— fewer allocas, fewer copies, and the shred's producer gone. Any scratch
that must remain (a genuinely by-value round-trip) is word-granular by
construction.
Sweep still owed (obligation 4's siblings, now as VERIFICATION rows rather
than conversion sites): construction (`Optional.Some`, `Result.Ok`/`Err`,
user enums), match-arm extraction, by-value argument/return — each checked
word-granular in the emitted code.
LAYOUT-CHANGE DILIGENCE (the ruling's cost, made visible):
- U0 gains a row: enumerate every std/corpus enum's size delta under the
  alignment rule. Payload rounding is ZERO by construction (alloc size is
  a multiple of alignment), so the only component is TAG-ALIGNMENT
  padding: `{i32, [N x i8]}` packs the payload at offset 4; an
  8-aligned payload moves to offset 8 on 64-bit hosts (~+4 B per such
  enum; zero on riscv32, where word alignment is 4 and the tag already
  pads to it — CHECK this claim per-enum in the census rather than
  trusting it). `Optional<Byte>`-class enums are byte-for-byte unchanged.
  Growth propagates to CONTAINERS of the enum (a field, an element
  stride), never to the bare payload type, which is unchanged everywhere.
  Report the sos image movement. Report, not gate: the trade is accepted;
  the numbers still land.
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

## U0 — THE CENSUS (measured Sep 4 2026, agent, no code change)

### The baseline, and a correction to the brief's number

Recipe as written (`sos_runner.py --arch riscv32 --case process-isolation
-j 1`, sawlang HEAD `3b5e2012`, sawos clone at `.build/scratch/sawos/`):

| artifact | measurement |
|---|---|
| `.build/riscv32-unknown-none-elf/sos/process_isolation.elf` | `.text` 68,184 + `.rodata` 24,404 + `.data` 9,904 = **102,492 B** |
| same elf, `llvm-size` berkeley | text 127,780 + data 9,904 = 137,684 B (text there folds in `.payload` 32,768, `.childimg` 2,368, `.regions` 56) |
| `.text` instruction count | **21,434 instructions in 103 functions** |

The brief's stated baseline of 140,776 B does not reproduce. It is NOT a
regression or an improvement in between: rebuilding the same case against
the PRE-264 compiler (`4f2b73e4`, its own detached worktree) gives
**byte-identical section sizes**, so nothing in design 264 moved the image
and the difference is an accounting one on the earlier measurement (the
instruction count, 21,434 here against the brief's 25,298, says the two
counts are of the same image family but not the same section set — the
closest sum available here, text+data berkeley, is 137,684 B). **Every
delta this brief reports is against 102,492 B / 21,434 instructions,
measured with the recipe above.**

### (a)+(b)+(c) — bytes by producer, riscv32 sos image

`.text` = 68,184 B / 21,434 instructions. Classified from
`llvm-objdump -d` (`probe_census.py`, `probe_census2.py`):

| producer | insns | bytes | % .text |
|---|---|---|---|
| address + constant materialization (`auipc` 2,660, `li` 2,434, `addi` 1,191, `lui` 221) | 6,506 | 21,028 | **30.8%** |
| loads (`lw` 3,923, `lbu` 607, `lhu` 180) | 4,710 | 17,320 | 25.4% |
| branches + jumps (`j` 1,397 leads) | 3,867 | 12,384 | 18.2% |
| stores (`sw` 1,353, `sb` 216, `sh` 99) | 1,668 | 5,266 | 7.7% |
| calls (`jalr`) | 1,163 | 2,326 | 3.4% |
| shifts | 832 | 2,740 | 4.0% |
| masks/logic | 455 | 1,434 | 2.1% |
| everything else (ALU, compares, csr, mul) | ~2,233 | ~5,686 | 8.3% |

Memory traffic by base register: **pointer-based 4,832 ops / 18,840 B
(27.6%)**, stack-based (sp/fp) 1,551 ops / 3,766 B (5.5%) — design 261's
far-offset-frame story (B) is gone from this image, as 263 predicted when
it removed the per-site panic scratch.

**(a) byte-wise enum chains — 1,408 B, 2.1% of `.text`** (105 runs, 382
instructions; a run = a maximal window of byte/half memory ops plus
shift/mask glue holding at least two byte ops). Concentrated in
`dispatch$m$kcore_dispatch` (738 B), `end_process` (162 B),
`deliver_attachment` (150 B). **This prices U2's direct riscv32 image win
at ~1.4 KB before any secondary effect** — the user ruled U2 in regardless
("even if the improvement is less than 5%"), and the census confirms it is
a small direct win on THIS image. The host-side pattern is much larger
(below), and riscv32's `[N x i8]` payloads are already word-aligned
(`palign` 4 = the ISA word), which is exactly why the shred is small here.

**(c) outliner-shaped repetition — up to 34 KB.** Identical instruction
windows (operands normalised, non-overlapping occurrences) that the machine
outliner is built to fold:

| window | distinct repeated windows | foldable bytes (upper bound) |
|---|---|---|
| 6 insns | 305 | ~33,962 B (49.8% of `.text`) |
| 10 insns | 182 | ~24,244 B |
| 20 insns | 76 | ~14,042 B |

Upper bounds: they ignore the call+return each outlined body costs and the
register constraints the real outliner honours. Even discounted heavily
this is the largest single lever in the census, and it is U1's `-Oz`
outliner leg — the census PREDICTS the flags cell, not U2, carries this
image's size win. One function, `dispatch$m$kcore_dispatch`, is 21,708 B =
32% of `.text` on its own; `end_process` 5,484, `free_object` 2,932,
`deliver_attachment` 2,390.

### The per-enum size-delta table under the ALIGNMENT rule

Computed by instrumenting `_register_concrete_enum` and asking LLVM's
DataLayout for both the current `{i32, [N x i8]}` and the proposed
`{i32, [M x iK]}` (`probe_enum_layout.py`, `probe_enum_kernel.py`).

**riscv32 (the sos kernel compile, every module path the runner passes):
40 payload enums, 39 of them BYTE-FOR-BYTE UNCHANGED, total +4 B.** The
brief's riscv32 claim holds. The single grower is `JsonValue`, whose
`.Number` payload is an `f64`: payload alignment 8 on a 32-bit target, so
the tag pads 4→8 and 28/4 becomes 32/8. It is a std type the kernel image
does not instantiate.

**The SOS kernel declares NO payload-carrying enum of its own** — grepping
every `kernel/`, `rt/` and `hal/` source for a payload case finds exactly
one file, `kernel/sysapi/src/pipe.saw`, which is the userspace-facing `sos`
module and is not in the kernel image's compile. Every payload enum in the
image comes from std. Predicted image growth from the layout change: ~0.

**Host (arm64, `dis_map.saw`'s compile): 40 payload enums, all 40 grow,
total +160 B of per-type size.** 38 grow by exactly +4 (tag padding to
offset 8, as the brief predicted). Two rows do NOT fit the brief's "payload
rounding costs zero" claim, and this is the census's correction to it:

| enum | payload max size | payload max align | cur | new | delta |
|---|---|---|---|---|---|
| `Result<JsonValue, DecodeError>` | 52 | 8 | 56/4 | 64/8 | **+8** |
| `Result<Void, EncodeError>` | 1 | 1 | 8/4 | 8/4 | +0 (`[1 x i8]`, the Byte-class row) |
| the other 38 | — | 8 | n/4 | n+4/8 | +4 |

The mechanism behind the +8: the rule takes the max SIZE over variants and
the max ALIGNMENT over variants INDEPENDENTLY. "An allocation size is a
multiple of its alignment" is true per variant struct, but the largest
variant need not be the most-aligned one — `JsonValue` is 52 B at align 4,
`DecodeError` is align 8, so `[7 x i64]` rounds 52 up to 56 and then the
tag padding adds its 4. Payload rounding is zero for every enum whose
largest variant is also its most-aligned variant, which is 39 of 40 here.
Recorded as an accepted cost, not a blocker: the ruling is ungated and the
worst case observed corpus-wide is +8 B on one type.

### Host-side pattern count (5 examples/ binaries, arm64)

`probe_shred.py` over `llvm-objdump -d` of each linked binary:

| program | functions | insns | shred-run insns | share |
|---|---|---|---|---|
| `dis_map.saw` (the DF-300a seed) | 85 | 3,966 | 173 | 4.4% |
| `result_basic.saw` | 18 | 412 | 0 | 0% |
| `json_value_roundtrip.saw` | 344 | 29,537 | 3,576 | 12.1% |
| `cbor169_roundtrip.saw` | 304 | 21,678 | 3,556 | 16.4% |
| `json_roundtrip_struct.saw` | 238 | 16,780 | 2,140 | 12.8% |

The json/cbor rows are UPPER BOUNDS — those programs do legitimate
byte-granular work (parsing), and the run detector cannot tell a parser's
`ldrb` from a shredded payload word. `dis_map` is the clean signal: it does
no byte-level work at all, so all 97 `strb` + 51 `ldrb` in its runs are
enum payload traffic. The host shred is an order of magnitude bigger than
riscv32's because arm64 payloads want align 8 and `[N x i8]` gives them
align 1.

**The acceptance pin's baseline.** `_Vector$2$Int$GlobalAllocator_map$1$Int`
at HEAD is **160 instructions, 75 of them (47%) shred-family**: 34 `strb`,
22 `lsr`, 19 `ldrb`. (DF-300a filed 166/~60 at `4f2b73e4`; the shape is
unchanged, the count moved with 263/264.)

## U1 — MEASURED (Sep 4 2026, agent)

### The sos image at each level

Every level BOOTS AND PASSES under QEMU (`process-isolation`, riscv32 virt),
which is the semantics claim measured rather than argued. Kernel elf,
`.text` + `.rodata` + `.data`:

| level | .text | .rodata | .data | total | vs default |
|---|---|---|---|---|---|
| default (`-O1`) | 68,184 | 24,404 | 9,904 | **102,492** | — |
| `-O2` | 66,422 | 24,172 | 9,904 | 100,498 | **-1.9%** |
| `-Os` | 44,124 | 25,780 | 9,616 | 79,520 | **-22.4%** |
| `-Oz` | 43,202 | 24,900 | 9,792 | **77,894** | **-24.0%** |

`.text` alone goes 68,184 -> 43,202, **-36.6%**. `-Os` grows `.rodata` by
1,376 B (less inlining leaves more constant pools) and still wins by 22%.

Re-censusing the `-Oz` image: 14,320 instructions in 43,202 B (from 21,434 in
68,184), the byte-shred down to 362 B (0.8%), and outliner-shaped repetition
down to ~16 KB at W=6 from ~34 KB. Function count goes UP, 103 -> 165: at a
size level LLVM stops inlining, which is where most of the win is.

### The machine outliner fires on arm64 and NOT on riscv32

`minsize` alone turns the outliner on for the host (601 outlined bodies by
`llvm-nm` in `json_value_roundtrip.o`; the earlier "783" counted disassembly
REFERENCES, not bodies). The riscv32 kernel object at `-Oz` has **zero**, and
stays at zero — byte-identical, 42,486 B of `.text` — when LLVM's own
`-enable-machine-outliner` is set, at its default value and at `=always`.

That is not a plumbing failure, and the negative control proves it:
`-enable-machine-outliner=never` on the host takes 601 bodies to 0, so
llvmlite's `set_option` reaches the pass. RISC-V simply does not outline
here. **RECORDED AS AN LLVM-SIDE LIMITATION, leg re-scoped**: nothing is
wired to the cl::opt, which is process-global and would contaminate a
second in-process compile at a different level for no measured gain. The
image's 24% still arrives, from inlining and codegen decisions rather than
from outlining — so U0's outliner prediction was right about where the mass
is and wrong about who collects it.

### riscv save-restore: available by name, never automatic

Probe: a riscv32 freestanding compile with `--target-features
+m,+a,+c,+save-restore` emits undefined `__riscv_save_0` / `__riscv_save_1`.
Those routines live in libgcc/compiler-rt; the freestanding profile links
`-nostdlib` and has neither, so auto-enabling at a size level would turn
`-Os` into an unresolved link on exactly the targets the feature is for.
The flag stays user-reachable (it already worked) and is documented in
LANGUAGE_SPEC's optimization-levels section. Leg re-scoped, per the
no-workarounds clause.

### bench, against the brief's `-O2` prediction

Warehouse benchmark, host arm64, min of 5 runs. **Checksums held at every
level** (the driver gates them; timing is report-only).

| level | min | vs default |
|---|---|---|
| default (`-O1`) | 182 ms | — |
| `-O2` | 173 ms | **-4.9%** |
| `-Os` | 275 ms | +51% |
| `-Oz` | 864 ms | +375% |

The brief predicted `-O2` would win on scalar compute and be MUTED by the
always-on checks and the visitor-boundary indirect calls. 4.9% on a
collection-heavy benchmark is that prediction landing: a real win, an order
of magnitude short of what O2 buys unchecked C-shaped code. `-Oz`'s 4.7x is
the size trade stated out loud.

Compile time is NOT a reason to keep the default at O1: on the warehouse
benchmark the levels are 1,971 / 1,980 / 1,947 / 1,932 ms (default / O2 / Os
/ Oz, best of 3) and on `json_value_roundtrip.saw` 2,906 / 2,961 / 2,769.
The Python front end dominates a sawc invocation so completely that the
backend pipeline's cost is inside the noise. The default stays O1 on the
merits above, not on compile time.

## U2 — MEASURED (Sep 4 2026, agent). DF-300a CLOSED

### The seam fence: CLEARED, no ruling needed

`rt/ABI.md` says every seam signature fits the design-58 `@export`
whitelist — fixed-width integers, `Int`/`UInt`, `UnsafePointer`,
`Void`/`Never` — and that whitelist admits no aggregate by value at all. The
one error vocabulary that crosses the seam, `SysError`, crosses as a NEGATED
INTEGER TAG in a single word, never as an enum value. So no seam-crossing
type carries a payload enum by value and the layout change cannot reach the
frozen ABI. The `abidoc` lane gates the claim independently and is green.

### The acceptance pin

`_Vector$2$Int$GlobalAllocator_map$1$Int`, host arm64:

| | before | after |
|---|---|---|
| instructions | 160 | **69** (-57%) |
| shred-family | 75 (47%) | **6 (9%)** |
| `strb` / `lsr` / `ldrb` | 34 / 22 / 19 | 2 / 1 / 3 |

The brief asked for the ~60-instruction return assembly to collapse to about
six word stores. It did.

### The sweep: every sibling position, before and after

`.build/scratch/sweep300a.saw` puts all four rows in one program — a
three-case user enum constructed and matched, a multi-field payload
extracted, an enum passed BY VALUE and returned by value, a `Result`
constructed out of a match arm, and an `Optional` built and read. Compiled
with the pre-change compiler and with this one:

| function (what it covers) | shred insns before | after |
|---|---|---|
| `widen` (construction + match extraction + by-value arg and return) | 124 | **0** |
| `measure` (Result Ok/Err construction from match arms) | 40 | **0** |
| `main` (Optional construct/read, enum literals, printing) | 327 | **5** |
| `Vector.push` | 16 | **0** |
| whole program | 545 (9.3% of 5,859 insns) | **14 (0.4% of 3,334)** |

The five that remain are `StringBuilder`'s genuine byte handling, which is
byte work because the data is bytes.

### Host corpus, five binaries

| program | insns before | after | delta | shred before | after |
|---|---|---|---|---|---|
| `dis_map.saw` | 3,966 | 3,195 | -19.4% | 173 (4.4%) | 9 (0.3%) |
| `result_basic.saw` | 412 | 407 | -1.2% | 0 | 0 |
| `json_value_roundtrip.saw` | 29,537 | 19,891 | **-32.7%** | 3,576 | 144 |
| `cbor169_roundtrip.saw` | 21,678 | 14,889 | **-31.3%** | 3,556 | 186 |
| `json_roundtrip_struct.saw` | 16,780 | 11,730 | **-30.1%** | 2,140 | 45 |

U0 called the json/cbor shred shares upper bounds, because a parser's `ldrb`
and a shredded payload word look alike to the detector. The after-numbers
settle it: most of that mass really was payload shred.

### The sos image: `.text` byte-identical, the root image a region smaller

The riscv32 kernel is **unchanged to the byte** (`.text` 68,184, `.rodata`
24,404, `.data` 9,904 — a fresh rebuild, not a cache hit), which is U0's
riscv32 prediction landing exactly: word alignment there is 4, the payload
was already word-granular, and 39 of 40 enums keep their layout. The
embedded root image (`.payload`) went 32,768 -> 24,576 B, an 8 KB region
step, so the root server — ordinary Saw code full of Results — did shrink.
`bench` is unchanged within noise (181 ms against 182, 174 at `-O2` against
173) with checksums holding, which is DF-300a's own cost shape: once per
construction, never per element.

### The cost, made visible

One corpus test pinned the pre-change layout and had to be updated, which is
the clearest statement of what this costs: `alloc_map_set_reports_oom`
reports its refused allocation by size, and `MapSlot<Int, Int>` went from 20
bytes at align 4 — under-aligned for the two `Int`s it holds, which is the
bug — to 24 at align 8. A 16-slot table asks 384 bytes where it asked 320,
**+20% on that table on a 64-bit host** and nothing on riscv32. That is the
tag-padding cost the ruling accepted, in the one place the corpus could see
it.

### What stayed, and why the brief's "delete the scratch dance" reads as it does

The brief asked the fix to delete the scratch-alloca round-trip rather than
re-type it. It is re-typed and kept, deliberately, and the reason is a
property of LLVM rather than a preference: **LLVM has no bitcast between
aggregate VALUES.** Every site that round-trips is handed the enum as an SSA
aggregate with no pointer to GEP into — `_generate_enum_init` builds one,
`_extract_result_ok_value` and the match-arm extractor are given one — so
converting between the union's array type and the active variant's field
struct is a store at one type and a load at the other, and that needs
storage. Deleting it would mean making enum construction and extraction
memory-based throughout, a much larger change than this brief scopes.

The brief's own next sentence is what the code now satisfies: "Any scratch
that must remain (a genuinely by-value round-trip) is word-granular by
construction." All seven sites route through one named
`_payload_scratch_alloca`, whose docstring says why it remains and which
takes its alignment from the union TYPE rather than the hard-coded `align=8`
that used to paper over the under-alignment. The IN-PLACE paths — the
release walk, the retain walk, the copy walk — GEP into the payload directly
and always did; they simply reach an aligned payload now.
