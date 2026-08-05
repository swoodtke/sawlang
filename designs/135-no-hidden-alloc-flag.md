# Design 135 — `--no-hidden-alloc`: enforce the no-hidden-allocations claim

STATUS: APPROVED (user, Aug 5; REORDERED Aug 5 — the soundness set 139 →
142 → 141 runs first). Queued after 141, before 138 (original pipeline
note follows: 130 → 131 → 132 →
133 → 134 → 135); diagnostics-only, so it may be pulled earlier if a slot
opens. Restores the guarantee design 125 had to soften into "names its two
exceptions".

## The principle

The flag forbids allocations the COMPILER inserts that no source construct
names. A `Vector.push` call allocates, but the allocation is named in
source — a method whose contract says so, allocator in the type. What the
flag targets is the compiler allocating on its own authority. "Named in
source" means named by the EXPRESSION or by a TYPE the user wrote.

## Decisions
- **Uniform ban, no carve-outs.** `[user]` Under the flag, string
  interpolation is rejected EVERYWHERE — including `panic`/`assert` message
  arguments. No special case for diagnostics; the workarounds (interned
  constant messages, explicit `StringBuilder`, fixed-buffer formatting) are
  the point. The runtime's own check panics already lower to interned
  constants (design 122 unit I) and are unaffected.
- **Orthogonal to `--freestanding`.** A kernel with a slab allocator may
  legitimately use allocator-backed `String`s; freestanding does not imply
  the flag. The pairing is recommended in the docs, not forced.
- Flag name `--no-hidden-alloc` (per-invocation). A per-function
  `@no_hidden_alloc` attribute is explicitly a possible LATER brief, not
  this one.

## Units

- **A. The audit (first, and the brief's contract).** Enumerate EVERY
  compiler-emitted allocation site and classify it against the named-in-
  source line. Known/expected entries: escaping-closure env (design 73;
  hidden), string interpolation (hidden), erased-error auto-wrap
  (`Result<T, Box<any Error>>` conversion boxes on the error path —
  classify against the line: the `Box` is in the written type; record the
  call either way), `any Trait` existential creation, spawn/TaskGroup
  machinery (expected visible: spawning is an API call), collection
  literals (visible: the literal names the collection). The final
  classification TABLE lands in the spec next to the restored claim; any
  newly-discovered hidden site gets gated in unit B.

- **B. The flag.** `--no-hidden-alloc` turns every hidden-classified site
  into a clean compile error naming the visible alternative:
  - escaping closure creation → "an escaping closure allocates its
    environment; make it non-escaping, or store state in an explicit
    `Box`/`Arc`" (the escaping bit is already stamped at typecheck,
    designs 16/29 — this is a site check, not new analysis);
  - interpolation → "string interpolation allocates; use an interned
    literal, an explicit StringBuilder, or fixed-buffer formatting";
  - plus whatever unit A adds. Errors carry the design-122 location
    prefix conventions. No codegen changes — diagnostics only.

- **C. SOS kernel dogfood.** Build the SOS kernel with the flag in the sos
  gate (COMPILE-FLAGS in the kernel build or sos_runner option). Either it
  is already clean or the errors show exactly where the kernel allocates
  without saying so — fix those sites (or record findings per the
  no-workarounds policy if a fix needs design). The gate keeps the flag
  honest permanently.

- **D. Docs.** The spec's allocation claim returns to guarantee form: "no
  hidden allocations — enforced by `--no-hidden-alloc`; without the flag
  the two named constructs allocate" + the unit-A table. Skill + README
  (the flag is a headline feature for the kernel/embedded audience —
  design-125 convention, saw-docs voice).

## Tests
Fail-before/pass-after per unit: each hidden site errors under the flag
(escaping closure, interpolation in ordinary code, interpolation in a
`panic` argument `[user: no carve-out]`, any unit-A additions); the same
programs compile WITHOUT the flag; a non-escaping closure and an explicit
StringBuilder compile UNDER the flag; SOS kernel builds under the flag in
the gate. Full battery green.

## Exit criteria
Audit table in spec; flag + errors landed; sos gate carries the flag;
tracker line for the 125 claim-softening closed with a pointer here.
