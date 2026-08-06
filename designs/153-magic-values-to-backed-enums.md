# Design 153 — magic-value families become Int-backed enums

**Status: APPROVED (user, Aug 6): "there should be a pass to convert
them all to Int inheriting Enums and update the skill to recommend this
pattern going forward." Skill ruling landed same day (SKILL.md STYLE
bullet, systems corner). Scheduled AFTER the current queue, post-M1
(so the sweep covers sos/ on main), concurrent-eligible with 152
(disjoint surfaces: this touches .saw code, 152 touches the
compiler).**

## Decision [user]

A closed named set of integer values — states, tags, modes, op ids,
rights bits — is a raw-backed enum (design 145 unit B2), not a family
of `static Int` constants and not inline literals. This pass converts
the existing tree; the skill ruling governs new code from today.

## The conversion rule (per site)

- **Converts**: any parallel family of named integer constants forming
  a closed set (`UNLOCKED`/`HELD`, `TAG_*`, `STATE_*`, `OP_*`), and
  any inline magic literal compared against one (`status == 3`).
  Backed enum with EXPLICIT values (145 requires them); fixed-width
  backing when the values cross a wire/ABI boundary (design-47
  discipline), `Int`/`UInt` acceptable for purely internal states.
  Wins to preserve in the rewrite: exhaustive `match` over the set,
  `E.from(raw:) -> E?` at read boundaries (never a trap on unknown
  input), `as` only where the raw number is genuinely needed.
- **Stays a static**: a genuine standalone quantity — sizes,
  capacities, alignments, budgets, lone constants (`AF_INET`).
- **Judgment sites**: state machines over `Atomic<Int>` (e.g.
  SpinLock's UNLOCKED/HELD) convert with `as` at the compare-exchange
  boundary IF the result reads clearly; where the `as` ceremony swamps
  the clarity gain, leave the site and record a DF-153 finding instead
  of forcing it — the findings list is a product of this pass (it
  tells us whether e.g. enum-typed `Atomic` is worth a design).
  Bitflag sets convert only where the 145-C precedent (backed enum +
  bitwise at the boundary) fits cleanly; inventing new abstractions
  (an OptionSet type) is OUT of scope.

## Scope

All Saw code on main at dispatch time: `sawc/std/`, `sawc/rt/`,
`sawc/builtin.saw`, `blade/`, `libs/`, `selfhost/`, `sos/` (post-M1
it is on main; 145-C already converted SysError/ops/rights/SegFlags —
this pass catches what it didn't), and `examples/` ONLY where the
static family is incidental to what the example demonstrates (never
rewrite an example whose point is the static form itself). Behavior
change: none — every conversion is representation-identical (explicit
values match the old constants).

## Docs

The skill ruling is already in. Spec/README examples that model the
old parallel-statics pattern get the enum spelling (claim-by-claim
consistency is 138's job; this pass just avoids adding new
contradictions).

## Tests / gates

No new feature surface — the bar is NO behavior change: full suite
(zero xfails), lexdiff, astdiff, irdet --all (venv), bootstrap,
sos_runner, blade test. New tests only where a conversion exposed an
untested value (e.g. a `from(raw:)` None path a sentinel silently
absorbed before).
