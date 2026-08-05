# Design 131 — payload-read ownership: the policy-driven place rule

STATUS: APPROVED (user, Aug 5) — all decisions recorded below with [user]
markers. Dispatch AFTER design 130 integrates (this touches the transfer
checkpoint, optional codegen, and std; 130 owns the tree until it lands).
Closes DF-124b and DF-128a.

## Problem (two organs, one disease)

An owned value can be read without the ownership system noticing. Everywhere
else the Copy family governs every read — ImplicitCopy retains, ExplicitCopy
demands `move`/`.copy()`, NoCopy demands `move` — enforced by the value-
transfer checkpoint. Two paths slip past it:

- **DF-124b:** every payload extraction from an optional (`o!`, `??`,
  `if let`, a `T?` field read) hands back a NON-OWNING ALIAS — no retain, no
  consume. Five safe lines dangle: `var o: String? = "v{1}"; let a = o!;
  o = None; print(a)` prints NUL bytes. `let g = f!` on a `File?` silently
  duplicates a NoCopy resource. The executor's `TaskHandle.join` deliberately
  EXPLOITS the non-retaining read (`let r = ptr[0]!` + `__saw_forget`) as its
  move-out, so the fix must supply a sanctioned replacement.
- **DF-128a:** a type conforming ONLY to `Deinit` (trivial fields +
  destruction side effect, so the containment rule never forces a policy)
  matches no arm of `_check_transfer` and takes the default bitwise path:
  `let s = r` aliases, both run deinit. Reaches containment too
  (`struct Pair { a: Res }`).

Precedent: the DF-124a frame-field fix (design 124) already gave coroutine
frame reads exactly the retain-on-read / move-via-forget split. This brief
makes that the language rule instead of a coroutine patch.

## Decision 1 — Deinit is non-declarable [user]

`Deinit` remains the base of the policy hierarchy (the deinit method
requirement; `ImplicitCopy`/`ExplicitCopy`/`NoCopy` extend it) but the
STANDALONE conformance form is removed:

- `extension T: Deinit { ... }` is a compile error: "`T` declares a deinit
  but no copy policy — declare `NoCopy` (move-only), `ExplicitCopy`, or
  `ImplicitCopy`".
- A hand-written deinit body lives inside the policy conformance
  (`extension Res: NoCopy { func deinit(&var self) { ... } }`) — the
  requirement is inherited, so nothing else changes; design 128's synthesis
  and prefix-hook semantics are untouched.
- `T: Deinit` as a GENERIC BOUND stays legal (it is still a real trait);
  only the conformance form goes away.
- Consequence: every resource type now has a policy, so the checkpoint's
  missing arm cannot be reached — but add the arm anyway as an internal
  error (defense against a future regression), plus the containment case.
- Migration: every surviving in-tree `extension T: Deinit {...}` moves its
  body into the type's policy conformance (creating `NoCopy` where none is
  declared — that is the semantic today's fallthrough SHOULD have had).

## Decision 2 — the policy-driven place rule for payload reads [user]

Every payload-extraction form — `o!`, the `??` left operand, `if let` /
`guard let` / match payload bindings, and a `T?` field read — denotes a
PLACE (like `s.field`), not a fresh value. Ownership is decided by how the
place is consumed, using the same table as every other read. No extraction
form gets a policy exemption.

| Use of the place | trivial | ImplicitCopy | ExplicitCopy | NoCopy |
|---|---|---|---|---|
| Borrow in place (`o!.m()`, `&o!`, `o!.field`, chain hop) | ok | ok | ok | ok |
| Value read (`let a = o!`, by-value arg, return, operand) | bitwise | retain (payload stays) | ERROR → `o!.copy()` / `move o!` / `o.take()` | ERROR → `move o!` / `o.take()` |
| `o!.copy()` | — | ok | ok (deep, payload stays) | rejected |
| `move o!` | ok | ok | ok | ok |
| `o.take()` | ok | ok | ok | ok |

- **`move o!`** — compile-time transfer. Legal only when `o` is a LOCAL
  binding; statically retires the WHOLE optional binding (no husk state, no
  partial move, no runtime writeback — same meaning as `move o`, spelled at
  the projection). Still unwraps: panics if dynamically None. Zero runtime
  cost.
- **`if let a = o`** binds by the value-read row (retain for ImplicitCopy;
  error-with-hints for ExplicitCopy/NoCopy). **`if let a = move o`** is the
  consuming form and retires `o`. `guard let`/`while let`/match payload
  bindings identical. `a ?? b` follows the value-read row for its result.
- Whole-optional operations are UNCHANGED: `let y = x` already retains via
  the owning-enum arm (needs_copy, the DF12 fix); `move x` already retires
  the binding. Writes (`x?.y = v`) unchanged. Trivial payloads: zero change.
- The ONLY breaking surface is ExplicitCopy/NoCopy payload value-reads —
  each of which is today a latent double-free or silent resource
  duplication.

## Decision 3 — `Optional.take(&var self) -> T?` [user]

The runtime consuming read: swaps `None` into the place, returns the payload
owned. Works on any `&var`-reachable place INCLUDING FIELDS — the move-out
that no-partial-moves otherwise forbids. Exclusivity-checked like any `&var`
method. Checked spelling `o.take()!`. `TaskHandle.join` (and any other
forget-idiom sites in the executor) migrate onto it; `__saw_forget` remains
for the unsafe domain only.

## Implementation shape

Typechecker: ForceUnwrap / if-let / `??` / optional-field reads become place
expressions feeding the EXISTING `_check_transfer` / `_is_aliasing_expr`
checkpoint (all four arms already exist — they have never been shown these
nodes); `move` accepts the `o!` projection of a local; Deinit-conformance
rejection + hint; bound form stays. Codegen: honor `needs_copy` at payload
reads (the DF-124a frame fix is the template); `take()` lowers to tag check +
payload move + None store. std: `take()` on Optional; migrate join; migrate
surviving `extension T: Deinit` bodies. Docs: spec Copy-family + Optional
sections, saw-lang skill, README if user-facing (design-125 convention).

Tests, each failing before / passing after: the DF-124b repro (now retains —
prints "v1"); NoCopy `let g = f!` rejected; ExplicitCopy `let x = v!`
rejected with the three hints; `move o!` retires the local (use-after-move
error); `move o!` on a FIELD rejected; `take()` on a field, observably None
after, exclusivity conflict test; `if let` retain + `if let move` consume;
`??` rows; DF-128a repro rejected (bare Deinit conformance error, and the
migrated NoCopy version demands `move`); `Pair { a: Res }` containment;
double-drop oracles gone. Tracker: close DF-124b, DF-128a; note the join
migration.
