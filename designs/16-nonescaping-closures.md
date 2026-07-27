# Design Paper 16 — Non-escaping closures and reference captures

**Status: DIRECTION APPROVED (Jul 27, 2026)** — Swift-style
default-non-escaping closure parameters with reference captures; details
below to be confirmed at implementation-brief time. Extends the decisions in
`designs/08` (exclusivity — whose invariant list explicitly reserved this
carve-out) and composes with `designs/06`/`07`.

## The rule

**A non-escaping closure is to functions what `&` is to values.** If a
closure value is (a) only callable during the dynamic extent of the call it
is passed to and (b) cannot be stored, returned, or captured by an escaping
closure, then its captures are hidden reference parameters of that call —
and every soundness property of Saw's reference system (no-escape,
call-site-static exclusivity, no lifetimes) extends unchanged.

## Design

- **Closure-typed function parameters are non-escaping by default**; an
  `escaping` marker opts out. Closure values elsewhere (returned, stored in
  bindings/fields) are ordinary values and keep today's by-value captures —
  `make_adder`-style code is unaffected.
- **Capture mode is context-directed.** A closure literal passed directly to
  a non-escaping parameter may capture enclosing locals **by reference**,
  including `&var` (this finally makes accumulation work:
  `var sum = 0; vec.each { sum += $0 }` — today that mutates a silent copy).
  In any other position, captures are by value / `ImplicitCopy` /
  move, exactly as today.
- **Exclusivity accounting:** the by-reference captures of a non-escaping
  closure argument join that call's access set in the brief-10 disjointness
  check. `v.each { v.push(x) }` — mutably capturing the collection being
  iterated — is statically rejected: iterator invalidation dies at compile
  time. Decidable at the call site; captures are syntactically local.
- **Forwarding mirrors `var`-param forwarding:** a callee may call its
  non-escaping closure param or pass it as another non-escaping argument;
  storing it, returning it, or capturing it in an escaping closure is an
  error, checked locally.
- **Type-level bit:** function types carry escaping/non-escaping; callee-side
  restrictions and higher-order signatures check against it. This (plus dual
  capture lowering — env-of-values vs env-of-references) is the main
  implementation cost.

## Why it is necessary (not just nice)

By-value captures cannot express mutation of enclosing state — the basic
`each`/`fold` accumulation idiom is silently wrong today. A stdlib iteration
API requires mutable non-escaping captures. Separately, `Mutex` *requires*
this feature: Saw cannot express Rust-style guard objects (references cannot
be stored or returned), so scoped closure access —
`m.lock { &var data in ... }` with a provably non-escaping closure — is the
only sound way to expose `&var T` to locked data.

## Concurrency composition (analysis for the future Send milestone)

- Non-escaping closures never cross threads (cannot outlive a call), so
  reference captures never need `Send` analysis. Escaping closures capture
  by value/move by construction, so `spawn` needs only `F: Send` — Saw
  structurally guarantees what Rust's `'static` bound exists to check.
- `Arc` being `ImplicitCopy` removes Rust's clone-before-spawn ceremony:
  capturing an Arc in an escaping closure is a transfer site; the checkpoint
  inserts the refcount bump. `String`'s day-one atomic refcount makes it
  `Send`-eligible with no migration.
- **DECIDED (Jul 27): ship only atomic `Arc` — no non-atomic `Rc`** (user
  preference, consistent with the String precedent): one shared-pointer
  type, always Send-eligible modulo contents. Add `Rc` later only if
  profiling proves single-threaded refcount traffic matters.
- Remaining machinery is standard and small: `Send`/`Sync` as compiler-known
  marker traits with structural auto-derivation (the auto-`Copy` pattern);
  `Arc<T>: Send where T: Send + Sync`; `Mutex<T>: Sync where T: Send`;
  channels are `send(move v)` + `T: Send` (the value-transfer checkpoint
  already does the ownership half).
- Known risk: `escaping` annotation "coloring" through higher-order APIs.
  Swift's experience: the default covers the overwhelming majority; the
  marker surfaces exactly at spawn/async/store boundaries, where it is
  informative. Accepted.

### The Swift `self`-capture idiom, translated (recorded Jul 27)

Swift captures `self` in async callbacks because classes are implicitly
shared mutable references — the source of the `[weak self]`/retain-cycle
bug class. Saw's equivalents, by case:
- **Request/response (the dominant case): async/await, no capture at all.**
  `let data = try await fetch(...); self.items = parse(data)` — mutation is
  linear inside a method already holding `&var self`. Design item for the
  async milestone: a suspending method's `&var self` spans suspension
  points — this is where Swift needed actor isolation; decide deliberately.
- **Fire-and-forget callbacks that outlive their scope: shared state is
  declared shared.** Hoist into `Arc<Mutex<State>>`; the escaping closure
  captures the Arc by value (silent retain — `ImplicitCopy`), and mutates
  via the non-escaping lock closure:
  `button.on_tap { state.lock { &var s in s.count += 1 } }`.
- **Read-only callbacks**: capture the value; snapshot semantics are a
  feature.
- **Future needs this implies**: `Weak<T>` (Arc cycles are constructible
  via stored callbacks, though far rarer than in Swift since sharing is
  opt-in); possibly an actor construct as sugar over Arc+Mutex+queue, much
  later. Trade accepted: Saw requires deciding "is this shared?" at design
  time, in exchange for deleting the `[weak self]` bug class.
- **Weak/Arc design notes (recorded Jul 27, for the eventual Arc brief):**
  Rust's model: one control block `{strong, weak, payload}`; two-phase
  destruction (payload deinit at strong-zero — deterministic, on the
  releasing thread; allocation freed at weak-zero, strong refs collectively
  hold one weak count). `weak.upgrade() -> Arc<T>?` composes with
  `guard let`; both types are `ImplicitCopy + Deinit`; payload teardown
  uses the brief-17 `__deinit_in_place` intrinsic. Atomics: `upgrade()` is
  a CAS loop ("increment strong iff nonzero") — NEVER a blind fetch_add
  (resurrection race); all other ops follow the String protocol.
  **Constraint binding NOW: Arc's control block must reserve the weak
  count from day one** — retrofitting changes the allocation layout (same
  ABI-break class as String SSO). Ship `Weak` itself later, when stored
  callbacks give it a forcing use case.

## Open details for the implementation brief (not yet decided)

- Surface spelling of the marker (`escaping` keyword position; whether the
  type or the parameter carries it in written syntax).
- ~~Capture explicitness~~ **DECIDED (Jul 27, revised — user preference:
  fully explicit reference captures, consistent with `&self`/`&var self`):
  ALL by-reference captures are declared at the closure — `{ &v in ... }`
  for an immutable borrow, `{ &var sum in ... }` for a mutable one.** This
  yields the clean unification: **captures follow exactly the transfer-site
  rules of call arguments.** Trivial types are captured silently (bitwise
  copy); `ImplicitCopy` types silently (retain — their contract);
  `ExplicitCopy`/`NoCopy` demand an explicit `move v` or `v.copy()`; and
  borrows are spelled `&v`/`&var v`, legal only in non-escaping closures,
  exactly as at a call site. "Captures are hidden arguments" is thereby
  true in the syntax, not just the semantics. Accepted cost: reading an
  owning type needs its `&v` marker where implicit borrowing wouldn't —
  the same explicitness trade Saw made at call sites.
  Exact capture-list syntax (merged with the param list before `in`, or a
  separate list) is for the implementation brief, including interaction
  with `$0` shorthand closures.
- Interaction with trailing-closure syntax and `$0` shorthand (should be
  none, but confirm in the parser).
- Sequencing: after the current dataflow work; the natural forcing function
  is the first stdlib iteration API (`Vector.each`/`map`/`fold`).
