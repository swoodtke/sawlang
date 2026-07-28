# Design 35 — Partial moves: forbidden on all structs

**Status: DECIDED (Jul 28, user).** Source: tracker L1 (brief-15
deferral). Ruling:

- **`move p.x` is a compile error for every struct** — no
  `Deinit`/non-`Deinit` split, one uniform rule. Only whole bindings are
  movable. Diagnostic: "cannot move out of field `x` of `p`; move the
  whole value or restructure" (wording free; must name the field and the
  base).
- Explicitly deferred, wait-and-see (revisit only with a forcing use
  case; both are purely-additive relaxations):
  - Destructure-move (`let (x, y) = move p`) for derived-cleanup structs
    — the natural first relaxation if `into_parts`-style decomposition
    proves needed.
  - `take()`/`replace()` Optional-field stdlib helpers (Rust
    `Option::take` idiom) — pairs with tracker M1's swapAt-style
    exclusivity escapes.
- **Accepted consequence (informed):** owned structs' owning fields
  cannot be extracted in safe code at all — even inside a consuming
  function (its body would need the forbidden `move p.x`). Mitigations:
  stdlib extraction via unsafe pointer internals (the existing
  Vector.pop pattern) stays available; aggregates needing field handoff
  use Optional fields by design.
- Rationale: uniform rule, zero dataflow cost (no path move-tracking,
  no branch-merge rules, no runtime drop flags), forward-compatible —
  relaxations break nothing, the reverse would.

## Implementation item (small)

Brief-15 noted the parser/checkpoint behavior for `move <member-path>`
was never audited. Make the rule real: probe what `move p.x` (and
`move p.x.y`, `move arr[i]`) does today — parser rejection, checkpoint
rejection, or silent mis-handling; then ensure each form produces the
decided diagnostic at the typechecker level (parser may accept the
syntax; the checkpoint rejects). Error tests for field, nested-field,
and index forms; acceptance test that whole-binding `move p` is
untouched. Fold into any convenient queued brief or land standalone.
