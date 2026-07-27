# Design Brief 11 — Refcounted immutable String

**Source:** the DECISION section of `designs/07-string-model.md` — read it
first; it is the spec (representation, atomic ordering protocol, immortal
literals, conformances).
**Prerequisite:** brief 09 (Copy trait family) landed — String declares
`ImplicitCopy`. Can run alongside brief 10 (exclusivity — typechecker
territory) but NOT alongside any other codegen-heavy package.
**Scope discipline:** this brief changes String's representation and
lifetime. API *expansion* (`fromBytes`, `bytes()`/`chars()` views,
`withCString`) is follow-up work — do not add it here.

## Work items (commit order)

### 1. Runtime representation + retain/release
- Heap layout: `{refcount: i64, len: i64, bytes…, NUL}`; `String` lowers to a
  single pointer (decide and document: pointer to header, or to bytes with
  negative header offsets — pick whichever keeps existing `char*`-consuming
  code simplest during migration).
- Emit two IR-level runtime helpers, e.g. `__saw_string_retain(ptr)` /
  `__saw_string_release(ptr)`, implementing EXACTLY the ordering protocol
  from 07: immortal-sentinel check via plain load + branch first; retain =
  `atomicrmw add monotonic`; release = `atomicrmw sub release`, and on
  old==1 an `fence acquire` then `free`. llvmlite exposes `atomic_rmw` and
  `fence` — verify against 0.48 with a scratch probe before writing codegen.
- New-buffer constructor helper (malloc, refcount=1, len, copy bytes, NUL).

### 2. Literals become immortal static blocks
String literals emit a static global `{refcount: -1, len, bytes, NUL}` and
lower to a pointer to it. Dedupe identical literals per module if trivial;
don't build interning infrastructure.

### 3. Conformances + transfer sites
Register `String` as `Deinit` (release) + `ImplicitCopy` (retain) with the
compiler — likely compiler-known rather than stdlib-declared, since the
copy/deinit bodies are IR helpers, but if the existing `Rc` stdlib pattern
(`sawc/std/`) can express it cleanly, prefer that; document the choice.
Consequence to verify: every transfer site the value-transfer checkpoint
marks for `ImplicitCopy` now emits retain; every scope exit the cleanup
stack tracks emits release. Strings must flow through let/assign/call-args/
returns/aggregates with balanced retain/release — the existing `deinit_*` /
`implicit_copy_*` ordering tests are the oracle shape; add string-specific
ones (below).

### 4. Migrate string operations
- Interpolation (codegen/core.py): build result via the new-buffer helper
  (refcount=1) — DELETE the brief-05 leak comment; result participates in
  cleanup like any Deinit value.
- `std/string.saw`: `len()` reads the header field (O(1)) instead of
  `strlen`; audit every `UnsafePointer<Int8>` cast / `strlen` call and
  migrate or justify in the report. String equality/comparison: compare
  `len` then `memcmp` if implemented; if equality doesn't exist today,
  don't add it here.
- Concatenation `+` (if implemented today): new buffer from both parts.
- FFI boundary: C functions currently receiving `String` as `char*` — the
  bytes remain NUL-terminated, so passing the bytes pointer stays valid;
  adjust for the header offset decision from item 1.

### 5. Spec note
Add the 07 spec note (atomic rationale + ordering protocol) to
LANGUAGE_SPEC.md's string section. Fix the "UTF-8 string" claim to state
what is actually guaranteed as of this brief (byte string; UTF-8 validation
arrives with `fromBytes`/literal validation follow-up).

## Tests
- `string_implicit_copy.saw` — pass a string to functions, store in
  bindings, print original after — all without `move` (this is THE
  ergonomics win; would have been errors under ExplicitCopy).
- `string_lifetime.saw` — strings created/dropped in a loop (hot loop with
  fresh interpolated strings; stable memory, correct output).
- `string_literal_immortal.saw` — copy a literal into bindings that die,
  use the literal after; also literal passed to functions repeatedly.
- `string_interp_owned.saw` — interpolated result stored, returned across
  scopes, printed later (the old dangling/leak cases, now with balanced
  refcounting).
- `string_len_o1.saw` — `len()` correct including after concat/interp
  (and with an embedded scenario once fromBytes exists — not now).
- Re-check `process_simple`'s xfail after migration: if its stdout-capture
  bug was ownership-related it may flip — investigate briefly either way
  and report; remove the marker only if it genuinely passes for the right
  reason.
- Watch for regressions in every existing test that touches String (large
  surface — interp, print, FFI/directory/file modules).

## Report back
Standard: header-vs-bytes pointer choice and why; how conformances were
registered; the llvmlite atomics API used (verified how); every
strlen/UnsafePointer site migrated or justified; retain/release balance —
how you convinced yourself there is no over-release (crash) or leak;
`process_simple` verdict; deviations.
