# Design 107 — shadowing follow-ups: same-scope derived redefinition + for-loop vars (queued Aug 2)

Final pre-SOS batch, part 6 of 6. The two design-100 flags.

## Item 1 — same-scope derived redefinition becomes legal
`var data = read(); let data = parse(move data)` in ONE scope
currently hits the pre-existing "already defined in this scope" error;
design 100's leniency only applied across scopes. Open same-scope
redefinition under the SAME mentions-rule: legal iff the initializer
references the binding being replaced (derived); otherwise keep the
duplicate-definition error. Semantics: the new binding REPLACES the
old in that scope (the old value is moved/copied/consumed by the
initializer per normal rules; if the old binding still owns a value
at replacement — e.g. derived via `.copy()` — the old value drops AT
the redefinition point, deterministically, and the design-100 codegen
shadow-safety machinery (captured alloca+flag cleanup) must cover the
same-scope case too — extend `shadow_owning_lifetime`-style tests).
let->let, var->var, and let<->var transitions are all allowed (the
new binding's mutability is its own).

## Item 2 — for-loop iteration variables join the rule
DECISION MADE WITHOUT THE USER (review tomorrow): `for x in xs` under
an outer `x` gets the SAME mentions-rule, with the SEQUENCE expression
as the initializer analog — `for x in x.lines()` (derived) is legal;
`for x in ys` under an outer `x` is an error (rename). Rationale:
consistent single rule, and the sequence mention proves the same
intent the initializer mention does. Pattern-style loop bindings
(`for (a, b) in pairs`) shadowing an outer name: flat error (patterns
bind — same as design 100's match rule).

## Tests
Same-scope: derived let->let / var->let / let->var legal (move,
.copy(), call-wrapped); non-derived same-scope still the duplicate
error (message unchanged); deterministic drop-at-redefinition for an
owning .copy() derivation (deinit-count oracle); across-scope design-
100 suite untouched. For-loops: derived sequence legal; non-derived
error with the design-100 hint style; tuple-pattern loop binding
error; loop var vs same-name loop var in a NESTED loop (outer loop
var is an enclosing binding -> non-derived inner = error).
MIGRATION: sweep std/blade/libs/examples for newly-illegal for-loop
shadows (report count); same-scope item only ADDS legality, no
migration.

Bars: full suite (zero xfails) + bootstrap (incl. libs) green per
commit. Standing policy; foreground; interruption-safe; skill
self-review; docs = spec bindings section + skill rule/gotcha +
tracker (both design-100 flags closed).
