# Design 72 — Small fixes: L12, L9, erased-error downcasting (queued Jul 31)

## 1. L12 — extension methods on fixed arrays
`extension [Int; 8] { ... }`? No — the useful form is generic-length.
PINNED (orchestrator; user may veto): builtin members on fixed arrays
rather than user extensions v1: `arr.len()` (compile-time constant N)
and `arr.swap(i, j)` (the M1 escape hatch for dynamic-index
exclusivity, mirroring Vector.swap). User-defined extensions on array
types stay a clean "not supported" error (parse error today — keep,
but make the diagnostic say so). Spec: fixed-array section updated;
`.len()` de-illustrativized.

## 2. L9 — `==` over Optional-/array-bearing members
Extend the Equatable synthesis: a synthesized memberwise `==` now
lowers Optional fields (None==None, Some==Some via payload equals) and
fixed-array fields (element-wise). Auto-conformance rules UNCHANGED
(trivial-only); this only widens what opt-in synthesis can lower.
Clean error remains for genuinely non-Equatable members. Tests: struct
with `Int?` field, with `[Int; 4]` field, with `String?`; enum payload
carrying an Optional; still-clean error for a non-Equatable member.

## 3. Erased-error downcasting (type-ids) — MINIMAL v1
PINNED design (orchestrator; user may veto in the morning):
- Every vtable gains a TYPE-ID slot: a unique per-concrete-type
  constant (the mangled type name's interned address or a global
  counter — pick the simplest stable scheme; no reflection surface).
- API (builtin, on `Box<any Trait>`): `b.is<T>() -> Bool` and
  `b.take<T>() -> T?` (CONSUMES the box on success — moves the
  payload out, frees the box shell; returns None and leaves the box
  intact on mismatch... if leave-intact fights the move checkpoint,
  make take() consume unconditionally — mismatch drops the box — and
  report the choice; `is<T>()` first lets callers branch).
- Explicit type args (no inference); T must be a concrete conforming
  type. Works for any `Box<any Trait>`, motivated by `Box<any Error>`
  (retry-on-IoError after erasure — the Blade-adjacent use case).
- catch-side sugar (match-on-concrete over an erased box) is OUT of
  scope v1 — note as future.
- Tests: is/take hit + miss, take moves payload (deinit exactly once,
  box shell freed), mismatch path balanced, works through
  `Box<any Error>` from an erased Result, generic-context use.
- Spec: existentials + error sections; saw-lang skill: replace the
  "NO downcasting" note.

Bars: full suite + blade/libs + bootstrap green per commit; zero
xfails. Standing policy applies. Tracker: L12/M1, L9, downcasting
closed; design 72 landed.
