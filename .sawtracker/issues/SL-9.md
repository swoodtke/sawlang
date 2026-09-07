---
{"assignee":"","author":"agent:codex-todo-import","body_bytes":10167,"created":"1788791150","id":"SL-9","labels":["todo-import","backlog","design","plan","design-proposal"],"priority":"normal","project":"SL","revision":2,"sequence":203,"status":"open","title":"DF-300b: Design type-carried alignment for byte buffers","updated":"1788791294"}
---


## Description

## Scope and status

DF-300b: Design type-carried alignment for byte buffers

@align(N) on locals/statics is already implemented. Only the signature-enforceable aligned storage/type design remains here; keep the SawOS staging copy until the API can guarantee alignment for every caller. Coordinate frame alignment with DF‑306a.

Imported from repository TODO records on 2026-09-07. The reporter/version, evidence, workarounds and prior rulings are preserved in the source context below. This import is not a fresh reproduction or approval of a proposed design.

Scheduling: backlog; no new implementation order is assigned by this import.

## Proposed plan

1. Reconcile the linked brief and recorded rulings with current consumers. Keep already-landed behavior and stated deferrals explicit.
2. Draft the remaining contract: supported syntax/API, ownership and failure behavior, alternatives, compatibility effects and the exact questions still requiring a decision.
3. Define small implementation units and consumer migrations, then specify the positive, negative and boundary tests before dispatch.

## Acceptance criteria

- [ ] The design names a concrete consumer or retains its recorded revisit trigger.
- [ ] Existing rulings are preserved; unresolved choices and a recommended option are explicit.
- [ ] The proposed API/semantics, migration scope and acceptance tests are reviewable. Drafting this plan does not mark an unruled design approved.

## Related tracker work

These are related findings/plans; a reference alone does not imply a blocking dependency.

- SL-81 — DF‑306a: Design alignment for coroutine-frame-resident locals

## Existing design references

- [sawlang/designs/149-runtime-authoring.md](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/149-runtime-authoring.md)
- [sawlang/designs/265-backend-size-lane.md](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/265-backend-size-lane.md)
- [sawlang/designs/80-member-visibility.md](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/80-member-visibility.md)

## Source context

Historical closed subcases are context, not new work. Legacy DF/SL/SO numbers use a nonbreaking hyphen here to avoid accidental tracker links; the linked source retains the original spelling.

### sawlang TODO lines 48–48

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L48-L48)

- DF‑300b — NO ALIGNMENT REQUEST exists in the type system: a `[UInt8; N]` local's alloca carries NO align attribute (probed: `alloca [128 x i8]`, bare), so a byte buffer whose ABI needs word alignment cannot state it and gets whatever the optimizer packs — sos SL‑26's pipe sysapi faulted on riscv32 the first time `-Oz` repacked two frames, arm64 passed by luck (entry below, filed Sep 5 by the lead from sos SL‑26 at the 0.8.0 pin bump; DESIGN GAP, not a bug — the contract was unstatable so it was never stated. **RULED Sep 5 (user): `@align(N)` on locals/statics lands as v1 IN THE 0.10.0 RELEASE — attribute grammar per the `@export`/`@section` precedent, N a const power of two, emitted as the alloca/global's align, with an -Oz riscv32 freestanding test proving it survives; the TYPE-CARRIED aligned-array form (signature-enforceable, deletes sos's staging copy entirely) is its own later brief ruled together. sos's vet shrinks to a never-taken branch at v1**) — **V1 HALF DONE Sep 5** (branch `align-attribute`): `@align(N)` on locals + statics through the existing attribute funnel, const-folded, power-of-two, capped at 4096, emitted as the alloca's and the global's align; two oracles (the `ircontract` lane reads the align off the emitted globals at -O0/-Oz on host AND riscv32; a new riscv32 -Oz freestanding case proves such a program builds and runs); conformance rows N08-N11. **ENTRY STAYS OPEN for the TYPE-CARRIED half** — the signature-enforceable form that actually deletes sos's staging copy. DF‑306a filed (a frame-resident local cannot carry an alignment, so v1 refuses there)

### sawlang TODO lines 180–239

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L180-L239)

## DF‑300b — a byte buffer cannot ASK FOR ALIGNMENT: no `@align(N)`, no
## aligned-array type, and a `[UInt8; N]` alloca is emitted with NO align
## attribute (filed Sep 5 by the lead from sos SL‑26, hit at sawc 0.8.0's
## `-Oz`; PRE-EXISTING design gap — WANTS A RULING on the spelling)

PROBED (`.build/scratch/sl26_align.saw`, -O0 IR): `%"body" = alloca
[128 x i8]` — bare, no align, so the slot gets the type's ABI alignment (1)
and the OPTIMIZER decides the rest. Every alignment a Saw byte buffer has
ever had was accidental. `@align` appears nowhere in LANGUAGE_SPEC.md.

WHERE IT BIT (sos SL‑26, their words verified against their probe): the pipe
sysapi takes `body: &[UInt8; PIPE_BODY_BYTES]` and the kernel's copy-in door
faults an unaligned source. Under `-O1` every test program's local happened
to land word-aligned; design 265's `-Oz` repacked two riscv32 frames and
`pipe_donate` faulted on both riscv32 profiles — arm64 passed by luck.
Neither `-Oz`'s bug nor the kernel's: the ABI requirement is UNSTATABLE in
the type system, so no diagnostic could ever have fired. Their in-tree
workaround: the four send-side sysapi funnels vet the address and stage
through a `[UInt64; 16]` frame-local (naturally 8-aligned) when the caller's
storage is unaligned.

RESOLUTION SHAPE (theirs, endorsed): an alignment request the TYPE SYSTEM
carries — `@align(N)` on locals/statics, or an aligned-array type — so the
requirement is statable and the staging copy becomes deletable. A RULING
picks the spelling; freestanding/kernel use is the motivating case, per the
kernels-first doctrine. Repro: sawos `tests/pipe-donate` at `-Oz` on riscv32,
any sawos commit before their sysapi fix.

**V1 HALF DONE Sep 5** (branch `align-attribute`): `@align(N)` on LOCALS and
STATICS, through the `@export`/`@section` grammar funnel — no new attribute
machinery. `N` folds through the ONE const evaluator on an array length's
terms (literal / module `static` / const arithmetic), must be a power of two
and at most 4096 (one page on every target; documented). Emitted as the
alloca's align (`_entry_alloca`, whose `align` parameter already existed) and
the global's (`_emit_static_global`), MAX'd with the type's own so it can only
strengthen; composes with `@section`, and design 149's zerofill rule holds (an
all-zero `@align`ed static still costs no image bytes). Refusals, each clean
and each tested: non-const, non-power-of-two, zero, negative, over the cap,
`let _`, a `Void` binding, a destructuring `let`, a function, an extension, a
method, a struct FIELD and a PARAMETER (the last two naming the type-carried
form as the reason, since that is where an author reaches first). Two ORACLES,
complementary: the `ircontract` lane reads the `align` off the emitted globals
at `-O0` and `-Oz` on host AND riscv32 (the direct "it reached the object"
claim — a runtime address check cannot make it, because at a size level LLVM
folds `addr % N == 0` to a constant), and a new riscv32 `-Oz` freestanding case
proves such a program builds, links and runs on the target and level that
faulted (`extra_flags` is a new per-case runner hook). Conformance rows
N08-N11 + INDEX. DF‑306a filed for the one refusal that is a real gap.

**THE ENTRY STAYS OPEN** for the TYPE-CARRIED half, which is the part that
deletes sos's staging copy: an alignment a signature can ENFORCE
(`&[UInt8; N] align 8`, or an aligned-array type), so a caller passing an
under-aligned buffer is a compile error at the call rather than a fault in the
callee. v1 gives the callee no way to demand it — sos's vet shrinks to a
never-taken branch, as the ruling anticipated, but does not disappear. Owed:
the spelling ruling, a field/parameter position matrix, and the layout work a
frame field would need (see DF‑306a, which is the same missing mechanism seen
from the local side).
[186, 265, design 80 attribute grammar, sos SL‑26, DF‑306a]

### sawos TODO lines 413–413

[Original record](https://github.com/swoodtke/sawos/blob/754ec9570aef54609820cc7e28457c7623547670/designs/todo.md#L413-L413)

- SL‑26 — SAW CANNOT ASK FOR ALIGNMENT ON A BYTE BUFFER: a `[UInt8; N]` local has an alignment of ONE, no alignment attribute or aligned-array spelling exists, and the alignment a stack local actually gets is the optimizer's business — so an API whose ABI needs word-aligned bytes (`&[UInt8; N]` into a kernel copy door) cannot state that requirement anywhere in the type system, and every caller compiles into a latent fault (sawc 0.8.0 @ `449d2485`, found at the seventh pin bump, Sep 5). WHERE IT BIT: the whole pipe sysapi surface takes `body: &[UInt8; PIPE_BODY_BYTES]` and the kernel's copy-in door faults an unaligned source; every one of ~20 test programs' `var body: [UInt8; 128]` locals happened to land word-aligned at -O1 and below, and `-Oz`'s frame packing landed TWO of them odd on riscv32 (`pipe_donate`, both riscv32 profiles; arm64 by luck) — the first optimization-level change ever taken, and the gate caught it same-day. Neither a bug in -Oz nor in the kernel: the contract was unstatable, so it was never stated. IN-TREE RESOLUTION (the vDSO discipline): `kernel/sysapi/src/pipe.saw` grew `body_addr_for_kernel` — the four send-side funnels stage the body through a word-typed `[UInt; PIPE_STAGE_WORDS]` frame-local (word-aligned BY TYPE) when and only when the caller's storage is unaligned; aligned callers pay one branch, unaligned ones a 128-byte copy. The receive side was always safe (bodies ride inside word-aligned structs). Resolution shape upstream: an alignment request the type system carries — an `@align(N)` on locals/statics, or an aligned-array type — so a byte buffer with an ABI can say so; the staging copy then becomes deletable. Probe: `tests/pipe-donate` at `-Oz` on riscv32, before the sysapi fix.


## Comments

