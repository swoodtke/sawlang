# Design Brief 20 — Freestanding stage 1: runtime seams, --target, --freestanding

**Source:** `designs/19-freestanding-profile.md` §2 (seams), §3 (mechanics),
§6 staging steps 1–2 (minus CI/QEMU — deferred). Read paper 19 in full
first; it is the design.
**Prime directive:** on hosted targets this refactor is INVISIBLE — the
full suite must pass with byte-identical outputs (print formatting, panic
messages). The suite is the oracle; treat any output diff as your bug.

## Work items (commit order)

### 1. The four seam symbols
Introduce as the only runtime boundary:
- `saw_alloc(size: i64, align: i64) -> i8*`
- `saw_dealloc(ptr: i8*, size: i64, align: i64)`
- `saw_write(ptr: i8*, len: i64)`
- `saw_panic(msg: i8*, len: i64)` (noreturn)
Hosted defaults emitted as **weak/linkonce_odr definitions** in the module
(so a user object can override at link time without flags): saw_alloc →
malloc (alignment note: malloc guarantees ≤16; assert/ignore align for
now, document), saw_dealloc → free, saw_write → `write(1, ptr, len)` or
fwrite, saw_panic → saw_write(msg) then abort. Verify llvmlite 0.48
supports the chosen linkage on functions (probe first).

Migrate every allocation/free the COMPILER emits (String buffers,
interpolation, Arc-to-be, closures env if heap? — audit `malloc`/`free`
call sites in codegen/) to saw_alloc/saw_dealloc **with size and align**
(dealloc size is available at all current sites — thread it; if a site
genuinely lacks size, pass 0 and document).

Migrate the STDLIB: `sawc/std/*.saw` and `sawc/builtin.saw` declare extern
malloc/free — switch the alloc-layer modules (string, vector, map, data,
stringbuilder, path) to `extern func saw_alloc(...)` etc. Hosted-only
modules (file, process, env, directory) may keep libc externs — they are
gated in item 4.

### 2. `print` unified onto saw_write
Replace printf-based lowering for **Int family, UInt family, Bool, String,
and string interpolation output** with: format into a small stack/heap
buffer (compiler-emitted itoa for integers — decimal, negative handling,
i64 range; Bool → `true`/`false`; String → ptr+len direct) → one
`saw_write` per print (plus the newline). Interpolation already builds a
complete String — printing it is ptr+len+newline.
**Float printing stays printf-based** (dtoa is out of scope): in hosted
mode unchanged; under `--freestanding`, `print` of a Float is a
compile-time error ("Float formatting requires the hosted profile" —
typechecker-level, clean message). Existing float-printing tests keep
passing hosted (same printf path, same format).
OUTPUT MUST BE BYTE-IDENTICAL for the migrated types — the suite checks
exact expected output everywhere.

### 3. Panic sites unified onto saw_panic
All panic emissions (try! unwrap, force-unwrap None, div/mod-by-zero,
tuple/array bounds, `__deinit_in_place` misuse if any) currently
printf+abort — build the message (constant strings; keep EXACT current
text, tests match on it) and call saw_panic. Delete direct abort calls
outside the hosted saw_panic default.

### 4. `--target <triple>` and `--freestanding`
- `--target`: pass the triple to llvmlite target machine + module triple +
  data layout. Default unchanged (host). Verify: `--emit-ir` shows the
  triple; object emission succeeds for `x86_64-unknown-none-elf` and
  `aarch64-unknown-none-elf` on a seam-free scratch program.
- `--freestanding`:
  - Seam symbols become **declarations only** (no hosted defaults) — the
    user's environment provides them at link time.
  - Hosted std modules are import errors: file, process, env, directory
    (message names the module and the profile). Core + alloc-layer modules
    remain importable (they now depend only on seams).
  - Output is an **object file** (`-o foo.o` semantics; skip the link
    step entirely — freestanding users own linking). Entry remains the
    `main` symbol for now; custom entry points are stage-2+ (note it).
  - Float-print gating from item 2.
  - `--freestanding` without `--target` is allowed (host triple, still
    unlinked object).

### 5. Verification (in lieu of suite tests for the new flags)
The runner can't drive CLI flags (known limitation — do NOT modify the
runner). Verify via scratch and record in the report:
- Full suite green, zero output diffs (items 1–3).
- `--emit-ir` on a scratch program shows saw_* calls and (hosted) weak
  defaults / (freestanding) declarations only.
- A minimal freestanding scratch program (no std imports, prints an Int
  via a provided-in-IR... no — can't link without a saw_write; instead:)
  compile `.build/scratch/free_min.saw` with `--freestanding --target
  x86_64-unknown-none-elf` to an object; confirm success and that the IR
  contains no malloc/printf/abort references and no defined saw_*.
- Grep the emitted hosted IR of one full-suite example for direct
  `@malloc`/`@printf` calls from compiler-lowered code — there should be
  none outside the weak defaults and hosted-module FFI.

## Out of scope (note, don't do)
QEMU/CI smoke target; Allocator trait/Global (paper 19 stage 3); custom
entry symbols; linker scripts; M0 atomics lowering; dtoa. LANGUAGE_SPEC
gets a short "Profiles" note (hosted default; freestanding = seams +
core/alloc only) — keep it to a paragraph with a pointer to designs/19.

## Report back
Seam call-site inventory (compiler-emitted and stdlib, migrated vs
justified); the itoa design and how byte-identity was proven; panic
message preservation; linkage choice and llvmlite verification; the
freestanding IR audit results per item 5; any place dealloc size was
unavailable; deviations; non-allowlisted commands (ideally none).
