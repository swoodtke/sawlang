# Design 59 — Small-fixes batch (queued Jul 30)

One agent-sized batch of accumulated bugs + ledger hygiene. No new
language surface; house rules (panics are for bugs, no phantom
overflow, exactly-once deinit) govern every call. VERIFY-FIRST
discipline: several tracker items may already be fixed by later work —
probe each before writing code; if fixed, close the tracker/ledger
entry with the proving test named instead of re-fixing.

## A. DF2 — process wait-status decode (std/process)
`Command`/`system()`/`.run()`/`.output()` divide the raw wait status
by 256, so signal deaths (SIGABRT from a failed assert, SIGSEGV)
read as exit 0 = success. Fix with proper decode: exited normally →
status >> 8 (0..255); killed by signal N → report 128 + N (shell
convention); stopped/other → nonzero. Keep the decode in ONE helper
used by every wait path. Blade's `blade test` relies on exit codes —
a killed test binary must count as FAILED (add a blade-relevant
compiler test: a .saw child that panics via abort path reports
nonzero). Update the DF2 ledger entry.

## B. Custom-allocator deinit leak (Map/Vector, designs 37/48)
`Map`/`Vector` with a custom allocator (e.g. `Vector<Int, LoudAlloc>`)
never deallocates the backing buffer on deinit (found in 54; repro is
plain explicit construction). Root-cause: the deinit path presumably
frees through Global or skips the dealloc when `A != Global`. Fix so
deinit routes the dealloc through the value's own `A` (the design-37
contract). Add LoudAlloc-style tests proving alloc/dealloc pairing for
Vector AND Map (and check Box/slab still pair — those tests exist).
Also verify grow: the OLD buffer on reallocation must be freed
through `A` too.

## C. Void-phi ICE (codegen)
A `match` in tail position of a Void-returning closure ICEs (invalid
void phi); a void if/else-chain in tail position had the same shape
(worked around twice in 57: Duration.format early-returns, enum-value
test). Fix the phi construction: a Void-typed merge must not build a
phi at all. Un-work-around one of the 57 sites (Duration.format can
keep early returns if clearer — but add a direct regression test:
match-in-void-closure and if-else-chain-in-void-tail both compile and
run).

## D. riscv32 stdlib literal overflow
The FNV-1a 64-bit hash constant in the Hasher is typed as platform
`Int`, which overflows the 32-bit word on riscv32 (`--emit-ir` repro
from 58). Design 53's literal suffixes now make this cleanly fixable:
type the constants fixed-width (u64 / UInt64) where the hash math
needs 64-bit, or make the Hasher word platform-sized if that is the
design intent (decide by reading design 48's Hasher notes; report the
choice). Verify with a riscv32 `--emit-ir` scratch probe over a
Hashable-using program; hosted suite must stay byte-identical-green.

## E. Literal loose ends (from 54)
1. Duplicate-key map literal with owning values leaks the shadowed
   value (the discarded insert-return isn't dropped in the synthetic
   lowering). Fix: drop the returned old value like a discarded call
   result. Deinit-count test with String values.
2. Set-literal lookahead misclassifies `{a > 0, b > 0}` (unparenthesized
   comparison first element — `<`/`>` treated as depth markers). Fix
   if a bounded-lookahead refinement exists that cannot regress closure
   parsing (the closure suite is the oracle); otherwise KEEP the
   documented parenthesize-workaround and add the error-message test
   that guides the user to it. Report which.

## F. Ledger verify-and-close sweep (probe FIRST, fix only what's real)
For each: write/locate the proving test, then fix or close.
- **L13** UInt division/modulo sdiv/srem — `uint_division_signedness` /
  `uint_modulo_signedness` now PASS in the suite; verify they assert
  high-bit-value correctness (not just compile) and close, else fix by
  signedness like the overflow intrinsics.
- **L5** array-mutation gaps — `array_elem_field_assign` /
  `array_elem_overwrite_deinit` now PASS; same verify-then-close.
- **L10** ImplicitCopy tail-return auto-wrap premature free —
  `autowrap_*_no_premature_free` tests PASS; verify-then-close.
- **L6** module-qualified MemberAccess missing `resolved_type` — 56 hit
  it AGAIN (defensive getattr workaround in the print path). Close it
  properly: annotate in the module member-access checker, then remove
  the defensive fallback (or leave the fallback but assert-log). Test:
  module-qualified struct field in interpolation + signedness-sensitive
  context.
- **L4** `Vector<File>.copy()` diagnostic — verify it is a clean
  typechecker error (not the ICE wrapper); if ICE-wrapped, emit the
  proper "T is NoCopy" error at the bound-check site.
- **L3** typechecker cross-module get_struct_info fallback ignores
  visibility — probe with a two-module private-struct collision; add
  the visibility check + ambiguity diagnostic if the hole is real.
- **C4** non-spawn escaping-closure env teardown — probe deinit counts
  for a stored escaping closure dropped without being called; record
  verdict (fix only if a leak/double-free is proven).
- **A1 tracker text** still says "brief 52b (in flight)" — 52b LANDED;
  fix the stale line while in the file.

## G. 52/52b v1 gaps — SCOPE ONLY, do not implement
TaskGroup-inside-a-suspending-fn, if-let-over-suspending-call split,
first-class `ch.receive()` suspension. For each: reproduce the current
rejection, estimate the change surface (files/mechanism), record the
estimate in the tracker under A1. These are feature work for a later
brief — implement NOTHING here unless the fix is genuinely a
few-line rejection-message improvement.

## Items (suggested commit units)
1. A (DF2) + tests + ledger.
2. B (allocator leak) + tests.
3. C (void phi) + tests.
4. D (riscv32 hasher) + probe evidence in the report.
5. E (literal loose ends).
6. F sweep (one commit per real fix; one closing commit for the
   verified-already-fixed batch with tracker edits).
7. G scope notes → tracker (with the A1 stale-line fix).

## Hazards
- B touches every deinit of the two workhorse containers — the full
  suite plus the LoudAlloc distinctness tests are the oracle; do not
  change the Global fast path's IR (spot-check --emit-ir on a hosted
  Vector program before/after).
- A changes observable exit codes: blade tester and process tests
  encode current behavior — update them deliberately, not by
  loosening assertions.
- C touches phi construction used by EVERY merge — run the suite at
  -O0 and default pipelines if the runner allows only one, prefer
  default.
Full suite per commit; zero xfails.
