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
- Candidate simplification when Send lands: ship only atomic `Arc` (no
  non-atomic `Rc`), consistent with the String precedent — one shared-pointer
  type, always Send-eligible modulo contents. Revisit only if profiling
  shows single-threaded refcount traffic matters.
- Remaining machinery is standard and small: `Send`/`Sync` as compiler-known
  marker traits with structural auto-derivation (the auto-`Copy` pattern);
  `Arc<T>: Send where T: Send + Sync`; `Mutex<T>: Sync where T: Send`;
  channels are `send(move v)` + `T: Send` (the value-transfer checkpoint
  already does the ownership half).
- Known risk: `escaping` annotation "coloring" through higher-order APIs.
  Swift's experience: the default covers the overwhelming majority; the
  marker surfaces exactly at spawn/async/store boundaries, where it is
  informative. Accepted.

## Open details for the implementation brief (not yet decided)

- Surface spelling of the marker (`escaping` keyword position; whether the
  type or the parameter carries it in written syntax).
- Whether immutable reference captures are implicit while `&var` captures
  require an explicit capture-list-style acknowledgment at the closure
  (Swift requires none; an explicit `{ &var sum in ... }`-style signal is
  worth considering for readability).
- Interaction with trailing-closure syntax and `$0` shorthand (should be
  none, but confirm in the parser).
- Sequencing: after the current dataflow work; the natural forcing function
  is the first stdlib iteration API (`Vector.each`/`map`/`fold`).
