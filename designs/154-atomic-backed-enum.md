# Design 154 — `Atomic<E>` over Int-backed enums

**Status: APPROVED (user, Aug 6: "can we do Atomic<int backed enum>
now?"). Scheduled post-M1b, SOLO-short, dispatched BEFORE [152 ∥ 153]
— 153's sweep depends on it (Atomic state machines convert instead of
DF-flagging; SpinLock's UNLOCKED/HELD is the poster child).**

## Decision [user]

`Atomic<T>` (compiler-known, builtin.saw, v1 = `Atomic<Int>`) widens
to accept `T` = the Int family (unchanged) OR a payload-free
raw-backed enum (145 unit B2). A backed enum pins its representation
(backing width + explicit tag values), so `Atomic<LockState>` lowers
to seq_cst LLVM atomics on the backing integer — same interception,
same `&self` interior-mutation model, same structural Send+Sync.

## Semantics (pinned)

1. **Soundness invariant, stated in docs**: only `E` values can be
   stored, so every `load` returns a valid case by construction — no
   `from(raw:)` in the atomic path. This is the payoff over
   `Atomic<Int>` + manual conversion.
2. **Method surface for enum `T`**: `load`, `store`,
   `compare_exchange` (CAS compares tags). `fetch_add` is REJECTED
   with a teaching error ("states don't add — use `store` or
   `compare_exchange`"). Int `T` keeps all four.
3. **Static const-init**: `static S: Atomic<LockState> =
   Atomic(LockState.Unlocked)` — the static-initializer rule admits a
   backed-enum CASE literal as a plain constant (it is a
   compile-time-known tag; general expressions stay rejected).
   Also legal as a local / struct field, as today.
4. **Any backing width**: `UInt8`-backed enums produce byte atomics;
   LLVM legalizes sub-word atomics to inline masked `lr.w`/`sc.w`
   loops on riscv32 under `+a` (no libcall). Prove with a
   freestanding SOS-target compile test; hosted targets are native.
5. **Unbacked enums stay rejected** (no pinned representation — same
   reasoning as their non-castability, 145).

## Tests / gates

Hosted MT contention: N tasks CAS an enum state machine, assert final
state + transition count. Static-init round trip. `fetch_add` on enum
`T` error; `Atomic<UnbackedEnum>` error; `Atomic<PayloadEnum>` error.
Freestanding riscv32 compile of a `UInt8`-backed atomic (sub-word
legalization). Docs: builtin.saw doc comments + skill systems-corner
line + spec Atomic section. Full battery: suite (zero xfails),
lexdiff, astdiff, irdet --all (venv), bootstrap, sos_runner.
