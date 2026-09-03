# Design 263 — Panic Scratch Consolidation and Narrow Field Reads

**Status: USER-RULED Sep 3 2026** (all four §3 cells, same day as the
draft): (1) BOTH L1a and L1b, staged as written — L1b in the recommended
split shape, per-KIND routines for the compiler-raised panic families and
per-format-SHAPE helpers for user-written `panic(...)` sites; (2) L2 in
THIS brief, U3; (3) L2r IS in scope; (4) queue slot: ASAP — dispatched
ahead of the perf batch and 262 U1/U2, concurrent with the in-flight 218
stages 4/5 branch (disjoint surfaces; gates serialize on the suite lock).
IMPLEMENTATION FENCE (lead, at dispatch): the per-KIND routines are
COMPILER-EMITTED internal helpers — sawc emits one module, so
once-per-program is free — NOT new `__saw_rt_*` seams; the seam ABI is
frozen (rt/ABI.md) and extending it is a user-ruling surface. An agent
that concludes a new seam is genuinely required STOPS and reports.

Authored by the lead from design 261's acceptance census, which refuted
the aggregate-copy diagnosis and measured what the sos image is actually
made of. This brief targets the two levers that census named.

## 0. The measured producers (261's landing note, agent-verified Sep 3)

`process_isolation.elf` (riscv32), post-261: `.text` 427,642 B, unchanged
by the receiver flip and the copy memcpy — the kernel IR holds only NINE
adjacent aggregate load->store pairs, so copies were never the mass. What
is:

- **(P) Inline panic-message assembly.** `end_process` (2,157 IR
  instructions -> 35,134 B) carries 49 panic sites, EACH expanding a full
  design-137 formatting sequence with its OWN `alloca [512 x i8]` scratch
  buffer — 33 live allocas = 16.9 KB of stack, 844 of its 1,909
  instructions (44%) are the assembly (`panic_base`/`panic_room`/
  `panic_over`/`panic_take`/`panic_seg`, 130 memcpy calls, 33
  `__saw_fmt_int` calls). The ≥8 KB frame is ALSO the whole origin of
  261's cause (B): riscv32's ±2 KB store immediate turns every deep-frame
  access into a `lui/sub/sw` triplet (~1,720 pairs ≈ 12 KB), downstream of
  the panic scratch, not of copies.
- **(F) Whole-struct field reads.** sawc emits `load <whole struct>` +
  `extractvalue` for every field access — 825 aggregate loads in the
  kernel IR, 58 of them ≥64 B — where a GEP + scalar load reads one
  field. This is what the Sep-2 disassembly misread as copy walks. The
  load-side `andi 0x1` bool renorm rides these loads (2,527 in the image);
  U2 already retired it for COPIES on the store-side invariant.

Panic sites are COLD paths by construction (`-> Never`), so size is the
only currency there; nothing about speed trades against these levers.

## 1. The levers

- **L1a — one scratch buffer per FUNCTION (cheap, unit 1).** Hoist the
  512-byte panic scratch to a single function-entry alloca shared by every
  panic site in the body. Sound because two panic assemblies can never be
  live at once in one frame: a panic diverges, and the assembly of one
  message never suspends or calls user code (design 137's sequence is
  straight-line into the seam). Expected effect: the ≥8 KB frames collapse
  (33 buffers -> 1), which dissolves the far-offset triplet tax across the
  WHOLE function body — the (B) mass — while leaving the assembly
  instructions in place.
- **L1b — OUTLINE the assembly (the .text lever, unit 2).** Two shapes on
  the table; ruling 1 picks:
  - *Per-format-SHAPE helpers*: each panic site calls an outlined helper
    keyed by its sequence of literal-piece/argument-kind steps; (FILE,
    LINE) and the argument values are operands. Helpers shared across
    same-shaped sites.
  - *Per-panic-KIND runtime seams + `.rodata` site records* (the
    Swift/Rust `panic_bounds_check` model, STRONGER and
    lead-recommended): the compiler-raised panic families — bounds,
    overflow, shift, div-zero, cast-out-of-range, tier violations — each
    get ONE runtime assembly routine, and a panic site emits a pointer to
    a static `.rodata` location record (file ptr, line) plus the live
    operands: ~4-5 instructions per site instead of an inline format
    expansion. USER-WRITTEN `panic("...", args)` sites keep the
    shape-helper route (their formats are open-ended). Message bytes,
    alloc-freedom and freestanding behavior are frozen either way —
    only WHERE the assembly code lives moves, into the design-113 seam
    layer where it is emitted once per program instead of once per site.
  Expected effect: ~44% of `end_process`-class bodies collapse to call
  sequences; the helper set is bounded by shapes/kinds, not sites.
- **L2 — narrow field reads (unit 3).** Emit GEP + scalar load where the
  source reads ONE field out of pointer-resident aggregate storage;
  `extractvalue` stays for genuine SSA-value projections. Mechanically a
  codegen funnel change with corpus-wide IR churn — `reemit` and
  `irdet --all` are the police, exactly as for 261 U2.
- **L2r — RIDER, needs its ruling (§3):** with narrow reads in place, the
  load-side bool renorm at field reads can retire on the SAME store-side
  invariant U2 cited (a Saw Bool is stored 0/1 at every store funnel) —
  2,527 `andi`s in this one image. Cheap beside L2, but it widens the
  invariant's load-bearing surface, so it is asked, not assumed.

## 2. Units

U1 = L1a. U2 = L1b. U3 = L2 (+ L2r if ruled in). U4 — the acceptance
measurement: the sos recipe (scratch clone at `.build/scratch/sawos/`,
`SAWLANG_ROOT=<tree>`, riscv32 `process_isolation.elf`), before/after
`.text` total, the five biggest symbols, `end_process`, and the frame-size
story (the `lui/sub/sw` pair count is the direct witness for L1a).
Expectations are stated but NOT promised — 261 taught that lesson — and
the landing note records whatever is true. Compile-time delta recorded
too (L2 touches every field read the corpus emits).

## 3. Rulings owed (the user's, pre-scouted)

1. **L1 shape**: L1a only, or L1a + L1b staged as above?
   Lead-recommended: BOTH, staged — L1a is small and pays (B) immediately;
   L1b is where the .text mass is.
2. **L2 in this brief or its own**: same dispatch (one IR-churn battery
   amortized across both) vs a separate brief after L1's numbers land.
   Lead-recommended: same brief, U3.
3. **L2r**: retire the load-side bool renorm at field reads on the
   store-side invariant? Lead-recommended: yes, with the invariant's
   citation extended in the same place U2 wrote it.
4. **Queue slot**: after the perf batch, or displacing it? (262 U1/U2 is
   also gate-open.) No lead recommendation — sos pressure is the input
   the lead cannot see.

## 4. Fences and non-goals

- Design 137's OBSERVABLE contract is frozen: identical panic bytes,
  alloc-free, freestanding-safe, 508-byte cut + `…`, `{}` slot checking
  unchanged. Only WHERE the assembly code lives moves.
- No `-Os`/`-Oz` (separately backlogged; front-end emission is the mass).
- No panic-site deduplication by (FILE, LINE) folding — the per-site
  identity is the diagnostic's value.
- Not touching: the seam ABI, the bt-table, drop glue (all exonerated
  twice now).

## 5. Gates

Compiler branch: per-commit full suite + freestanding both arches;
terminal FULL battery with `reemit` + `irdet --all` called out (corpus-wide
IR change, twice over). U4's numbers in the landing note beside the
battery counts.
