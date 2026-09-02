# Design 261 — Reference-Passing Uniformity and Aggregate Memcpy

**Status: USER-RULED Sep 2 2026** ("can we pass all references by pointer —
self and otherwise?" → ruled on the lead's analysis; "rule it and write the
brief"). DISPATCHES after the 218/1.5 stage-3 branch integrates (codegen
surface, single owner); stages 4/5 of 218 follow this. Agent DF range:
assigned at dispatch.

## 0. Motivation — the sos image diagnosis (Sep 2, lead-verified end to end)

sos filed "very large" kernel images. The measurement chain, all evidence in
the todo.md backlog entry and reproducible from the scratch clone:
`process_isolation.elf` (riscv32 virt) is ~392KB sawc-attributable loadable,
**92% `.text`**, with single functions at 20–35KB (`end_process` 35,134 B).
The lead REBUILT the image from a scratch clone of sawos against this tree —
byte-identical on every filed symbol size — and disassembled it: 10,119
instructions, only 79 calls. Two compounding emissions:

- **(A) Fully-unrolled field-by-field aggregate copies** — ~5,600 of the
  10,119 instructions are loads/stores walking one struct into another at
  byte/half/word granularity, with an `andi 0x1` bool renormalization per
  flag field; the renorm is what stops LLVM folding the walk into `memcpy`.
  The producers are by-value transfer sites, and the dominant one is the
  PLAIN `&self` receiver, which arrives BY VALUE — every method call on a
  kernel-sized struct (observed ≥1.2KB) pays a full unrolled copy.
- **(B) Far-offset stack addressing** — the copies live in an ≥8KB stack
  frame, and riscv32's ±2KB store immediate turns every deep-frame access
  into a 3-instruction `lui/sub/sw` triplet (~1,720 pairs ≈ 12KB of the
  35KB by themselves). (B) is downstream of (A): no giant stack
  temporaries, no far offsets.

Exonerated by the same measurement: the bt-table (138 bytes, zero frames),
`.rodata`/panic strings (27KB total), drop-glue call ladders (79 calls),
and the naive per-exit-edge deinit story (lead probe: an 8-early-return
function with 6 deep owning locals compiles byte-identical to its 1-return
twin — LLVM tail-merges mergeable cleanup).

## 1. The ruling, and where the tree already stands

**All references pass by pointer.** Most already do — the ruling closes the
one holdout:

| reference | today | after |
|---|---|---|
| `&T` / `&var T` parameters | POINTER (design 88's frame-resident refs, 106's re-borrows) | unchanged |
| `&var self` | POINTER | unchanged |
| `other: &Self` (design 239) | POINTER (`codegen/methods.py:387`) | unchanged |
| cell-carrying `&self` (design 186) | POINTER, via the `self_by_pointer` funnel | unchanged |
| **plain `&self`, aggregate receiver** | **BY VALUE** (`methods.py:286`) | **POINTER** |
| plain `&self`, primitive receiver | by value | by value (unobservable ABI detail — see §4) |

The mechanism is ONE PREDICATE: `ast_nodes.self_by_pointer` /
`_self_by_pointer_for` is already the funnel, and the week-old
monomorphization code keeps itself "in step with `_self_by_pointer_for` by
construction" (`codegen/calls.py:2602`) — the flip is widening the predicate
from cell-carrying to every aggregate receiver.

## 2. Why the flip is SEMANTICALLY SAFE now (and was not always)

By-value's observable meaning was "a write through `&self` lands in the
callee's copy and vanishes." Designs 146/176/200 closed EVERY spelling of
that write as a compile error — the direct write, the `&var self.<field>`
projection, the `&var self` method call on self or a field, and the place-
window write (DF-176c). With all four refused, by-value vs by-pointer is
UNOBSERVABLE in safe code.

The remaining observable lives in the unsafe domain and flips from footgun
to fix: **the documented `FixedBuf.ptr()` gotcha** ("a `&self` receiver
arrives BY VALUE, so a pointer built inside such a method addresses the
callee's copy" — skill + spec) DISSOLVES: a `(&self)`-derived pointer
becomes a pointer to the caller's storage, which is what every author ever
wanted. Code written AROUND the gotcha (declaring `&var self` just to take
a real address) keeps working unchanged. The gotcha text is RETIRED from
LANGUAGE_SPEC + the skill in the landing, replaced by the uniform rule,
with the suspect-in-older-builds note.

## 3. Units

- **U1 — the receiver flip.** Widen the `self_by_pointer` funnel to every
  aggregate `&self`; stamp the pointer `noalias readonly` (statically true
  by the Law of Exclusivity — one `&var` XOR many `&`, call-wide — and
  REQUIRED, because those attributes are what the by-value copy was
  silently buying LLVM). **Obligation 2's consumer sweep is mandatory and
  named — this is the rule's own canonical example** (by-value→by-pointer):
  (a) unsafe code deriving pointers from `&self` receivers (behavior
  improves; sweep confirms nothing depended on addressing the copy);
  (b) the mono/codegen internals' receiver assumptions
  (`calls.py:2561-2602` — the by-construction coupling is the claim; the
  sweep verifies it); (c) `borrows` accessors (already by-pointer — assert
  no double handling); (d) the coroutine transform's frame-resident
  receiver path (already pointer-shaped across suspends — assert).
- **U2 — aggregate copies as `llvm.memcpy`.** The transfer sites that
  remain genuinely by-value — moves, returns, struct assignments, by-value
  parameters, enum payload installs — emit ONE `llvm.memcpy` instead of the
  field walk, dropping the per-field bool renormalization on the STORE-SIDE
  INVARIANT (a Saw `Bool` is stored as 0/1 at every store site; prove it by
  citing the store funnel, then the load-side renorm is redundant for
  copies). Padding copies with the struct — inert. `reemit`/`irdet` are the
  determinism gates that police the IR shape change corpus-wide.
- **U3 — docs + the acceptance measurement.** LANGUAGE_SPEC + skill gotcha
  retirement (§2); README untouched. **The acceptance metric is the sos
  image**: rebuild `process_isolation.elf` from the scratch-clone recipe in
  the backlog entry against the branch, and record before/after — `.text`
  total, the five biggest symbols, and `end_process`'s size specifically.
  The expectation is a multiple, not a percentage; record whatever is true.
  Also record the compile-time delta (fewer IR instructions should SPEED
  compiles — measured, not assumed).

## 4. Fences and non-goals

- Primitive receivers stay by value: `self` IS the scalar, a pointer buys
  nothing, and no safe or unsafe construct can observe the difference (a
  primitive has no field to point into; `(&self) as UnsafePointer` on a
  primitive extension receiver — probe it, and if observable, align it).
- `@export`/C-ABI surface untouched (references are not C-ABI-safe and
  never cross it).
- No conformance rows owed (obligation 3 does not trigger: no safety
  guarantee changes — the write refusals ARE the guarantee and stand;
  passing convention is beneath them). The skill/spec updates are U3's.
- NOT this brief: `-Os`/`-Oz` (backlogged separately; does not fix (A)),
  instance dedup, and anything typechecker-side.

## 5. Gates

Per-commit: full suite + freestanding both arches. Terminal: the FULL
battery, with `reemit` and `irdet --all` called out as the lanes that
police an every-function IR change. U3's image measurement recorded in the
landing note beside the battery counts.
