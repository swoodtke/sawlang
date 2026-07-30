# Design 66 — Labeled arguments, lenient model (DECIDED Jul 30 — LANDED Jul 30)

**Ruling (user):** free-function and method calls gain parameter
labels under the **lenient Swift model**: labels are part of a
function's identity for overloading, but positional calls stay legal
wherever they are unambiguous — labels are REQUIRED only at actual
ambiguity, AVAILABLE always for clarity. **Partial labeling is
sufficient** (a single label that uniquely disambiguates resolves the
call — user-confirmed with `f(0, value: 4)`). Lands BEFORE Blade
(design 64) so the dogfood exercises it. Standing policy applies: fix
unambiguous user-facing bugs on discovery.

## The binding rule (the whole model)
Arguments bind LEFT TO RIGHT:
- a POSITIONAL argument binds the next unbound parameter;
- a LABELED argument binds the parameter with that name, provided it
  sits AT or AFTER the next unbound position — labels may skip
  FORWARD only over parameters that have defaults (design 53), never
  backward. No reordering, ever. `f(value: 4, 0)` = error (backward
  binding); a forward skip over a non-defaulted parameter = clean
  "missing argument `<name>`" error.
- A label that names no parameter of the candidate = candidate
  eliminated (call-site error naming the label if no candidate
  survives).
This subsumes: pure positional calls (byte-identical behavior),
fully-labeled calls in declaration order, partial labels as
constraints, and mid-default skipping (`connect(host, retries: 5)`
skips defaulted `port` — closes the trailing-only limitation).

## Overload resolution (extends design 55 — same chokepoint)
1. LABEL FILTER first: eliminate candidates whose parameter names are
   incompatible with the call's labeled arguments under the binding
   rule.
2. Then the existing design-55 exact-type matching + pinned
   tie-breaks on survivors; uniqueness required.
- Positional-only call over same-type different-label overloads =
  ambiguity error LISTING candidates with their labels and suggesting
  the labeled forms.
- Effects/checkpoint/exclusivity unchanged (they consume the resolved
  callee — single chokepoint preserved; assert ordering).

## Declaration-site rules (updates design 55 distinctness)
- Same normalized TYPE signature + same parameter NAMES → decl-site
  error (unchanged in spirit).
- Same types + DIFFERENT names → now LEGAL (`func f(a: Int, b: Int)`
  and `func f(type: Int, value: Int)` coexist; identity is
  name-qualified: f(a:b:) vs f(type:value:)).
- Different types → legal as today regardless of names.
- Mangling: extend `$OL$` with parameter labels for overload sets
  that need them (keep mangled names stable for non-overloaded
  functions — no churn in exported/@export symbols, which use their
  own explicit naming anyway; VERIFY @export + labeled overloads
  composes with design 58's one-export-per-unmangled-name rule).

## Scope of labeled calling
- Free functions, methods (instance + static), module-qualified
  calls. Closures: NO labels (closure types are structural — note in
  spec).
- **Init unification:** init calls already resolve by parameter
  names. ATTEMPT to converge init resolution onto this same
  label-filter + type-match pipeline (one resolution scheme
  language-wide); if it does not fall out cleanly, keep init's
  existing scheme untouched and REPORT why (do not destabilize init —
  its test family is large).
- Enum payload construction already uses named fields — unchanged
  (verify no regression; the named-payload parse path is adjacent).
- `_` external-label opt-out (Swift's positional-only marker) is NOT
  in v1 — positional calling is already the default; nothing to opt
  out of. Note as future work if labeled-only enforcement ever
  arrives.

## Interactions to verify (each gets a test)
- Design 53 defaults: mid-skip via label; decl-site shape expansion
  now label-aware (a defaulted-arity shape collides only if names
  ALSO collide at every position — update the expansion check
  consistently with the new distinctness rule).
- Design 57 DF3 optional auto-wrap: applies to labeled args
  identically (wrap after binding).
- Design 63 named tuples: `f(a: 1, b: 2)` is TWO labeled args;
  `f((a: 1, b: 2))` is ONE named-tuple argument — parser must keep
  these distinct (bounded lookahead; the 63 suites are the oracle).
- Trailing closures: label binding must not disturb the trailing-
  closure argument (it binds the last parameter as today).
- Overload + labels + generics: label filter runs before the
  concrete-beats-generic tie-break; explicit type args unaffected.

## Items (suggested commit units)
1. Binding rule + call-site checking (no overload interplay yet):
   labeled calls on unique functions, mid-default skip, error forms.
2. Overload integration: label filter, decl-site rule update,
   mangling extension.
3. Init unification attempt (or documented keep + report).
4. Docs: spec (calls section — the binding rule verbatim, the
   lenient philosophy: "labels are required only where calls are
   otherwise ambiguous"), CLAUDE.md, tracker (named-args ledger item
   closed, design 66 landed).

## Tests (minimum)
Labeled call on non-overloaded fn (all/partial/none labeled);
mid-default skip + missing-arg error + backward-binding error;
unknown-label error; same-type different-label overload pair —
positional ambiguity error (message lists labeled forms), full-label
resolution, PARTIAL single-label resolution (`f(0, value: 4)`),
label-eliminates-then-type-picks mixed case; same-type same-label
decl error; labels through module-qualified + method + static forms;
defaults shape-expansion with labels; DF3 wrap on labeled arg; named
tuple literal vs labeled args disambiguation (both forms in one
file); trailing closure with labeled leading args; generic + label
filter; effects through labeled overloads (sync/non-sync pair);
@export + labeled overload composition. Full suite regression.

## Hazards
- This touches the design-55 chokepoint AGAIN — its 12-test family
  plus 53's defaults family are locking; run them attentively.
- The parser's call-arg path is shared with init/enum-payload named
  forms — regressions there are user-facing and subtle; the whole
  init/enum suite is the oracle.
- Mangling changes must not alter symbols for NON-overloaded
  functions (object-file/IR spot check).
Full suite per commit; zero xfails.

## Init-unification verdict (item 3) — KEEP init untouched; DID NOT unify
Attempted per the brief; init resolution stays on its own scheme. The
two schemes are **semantically incompatible**:

- **Init/struct-field/enum-payload construction is order-INDEPENDENT,
  set-based name matching.** `Point(y: 4, x: 3)` and a reordered custom
  init `Point(tag: 9, mag: 1)` are both valid TODAY (verified), because
  field/init/payload arguments are matched to their parameter by NAME in
  any order. Init overloading is by the *set* of parameter names (which
  names are supplied selects the init), not by parameter TYPES.
- **The design-66 binding rule is order-DEPENDENT and forbids
  reordering.** Arguments bind strictly left to right; a label may only
  skip FORWARD over defaulted parameters; `f(b:.., a:..)` is a
  backward-binding error.

Routing init through the design-66 label-filter would turn reordered
field/init construction into a backward-binding error — a real
regression against a large, tested feature. So init keeps its existing
set-based resolution; enum payload construction (adjacent, same
order-independent semantics) is likewise unchanged. Both were re-checked
for regressions and pass. The `name(label: value, …)` parse ambiguity is
still handled: the parser builds a StructInit, and when the name is a
FUNCTION (not a struct) the typechecker reinterprets it as a fully
labeled call — a real struct name always resolves to init first, so the
init path is never disturbed. Unifying the two would require init to
adopt ordered binding (breaking reorder) or the call side to adopt
set-based matching (breaking the design-66 no-reorder rule); neither is
desirable, so they remain two schemes by design.
