# Design 255 — Explicit Imports Shadow the Prelude (SL-4/SL-5 Fix)

**Status: AUTHORED Aug 30 2026** (lead; user-approved dispatch same day —
"we should fix that too" — sharing one worktree/agent with design 254;
these units run AFTER 254's, before the shared version bump). Agent DF
range: continues **DF-280a+**.

## The findings (filed sawos-side during its design 5; verbatim entries
at `../sawos/designs/todo.md` SL-4/SL-5)

- **SL-5 — declared-vs-imported precedence asymmetry against the
  prelude:** a locally DECLARED `struct Thread` beats the prelude's
  `std.task.Thread<T>`; a selectively IMPORTED one
  (`import sos.thread.{Thread}`) TIES with it and errors. sawos worked
  around it with the qualifier at five sites.
- **SL-4 — the ambiguity diagnostic anchors at 1:1 with an `<unknown>`
  module:** ``ambiguous struct `Thread`: defined in both `<unknown>` and
  `sos.thread` `` reports at line 1:1 of an arbitrary file; both the
  location and the `<unknown>` are noise.

## Mechanism (obligation 4 — this is a class, and the sweep is unit 0)

`bind_type_name` (`sawc/namespace.py:979`) is FIRST-WINS: the prelude
binds `Thread` early (with NO source label), so a later selective import
of a different identity lands in `ambiguous_types`
(`namespace.py:1005-1009`) instead of shadowing — while the
local-declaration path goes through `rebind_type_name`
(`namespace.py:1027`), which replaces the binding and clears the
ambiguity. Two paths answering one question differently IS the bug.
SL-4 falls out of the same corner: the report
(`typechecker/types.py:352-359`) hardcodes `1, 1` as its position, and
`<unknown>` is `type_provenance.get(local, "<unknown>")`
(`namespace.py:1007`) — the prelude registration path passes no
`source_label`.

**The class:** first-wins-against-the-prelude is not Thread-specific and
not struct-specific. Unit 0 probes the matrix with COMPILE EVIDENCE
before the fix is written (undetermined cells flagged OPEN, never
guessed):

| binding path \ prelude name kind | generic struct (`Thread<T>`) | trait (`Error`) | enum (`Optional`?) | function/static |
|---|---|---|---|---|
| declared locally | known: wins (SL-5) | probe | probe | probe |
| `import x.{Name}` | known: errors (SL-5) | probe | probe | probe |
| `import x.*` (glob) | probe | probe | probe | probe |
| `import x.{Name as N}` | expected no collision (pure rename) — confirm | — | — | — |

Functions were re-keyed by design 249 and may already behave; statics
have DF-140h's overlay; the probe says, the brief doesn't guess. Every
cell that reproduces the asymmetry is covered by unit 1's fix + a test.

## The ruling to encode (unit 1)

**The prelude is the weakest bare-name tier short of qualifiers.** The
design-150 ladder extends to: local scopes → module-level declarations →
explicitly imported bare names → **prelude** → qualifiers. So
`import sos.thread.{Thread}` SHADOWS the prelude's `Thread<T>` exactly
as a local `struct Thread` already does — silently, matching the
local-declaration behavior SL-5 observed. Rationale: the prelude is
ambient vocabulary; an explicit import is the author speaking, and the
same author intent must not produce two different outcomes depending on
whether the type was declared or imported. (Rust precedent: explicit
`use` beats the prelude.)

Unchanged:

- Two EXPLICIT imports binding one name to two identities remain
  genuinely ambiguous — the design-142 use-site error, kept.
- Qualified access to the shadowed prelude name keeps working
  (`task.Thread` after `import std.task`) — sawos's five workaround
  sites must keep compiling.
- Shadowing DIAGNOSIS is out of scope: no new warning category invented
  here (if the user wants a `-W shadowed-prelude` sibling of
  `shadowed-qualifier`, that is a separate ruling).

Implementation shape: the import-binding path detects "previous binding
is a PRELUDE binding" and rebinds (the same act `rebind_type_name`
performs for declarations) instead of recording ambiguity — which
requires prelude bindings to be IDENTIFIABLE, and that is exactly what
SL-4's fix provides (a real provenance label on the prelude path). One
rule, one place: whatever predicate decides "is this binding prelude"
lives beside the tables, not copy-pasted per import form.

## Unit 2 — the diagnostic (SL-4)

- **Real span:** `_report_xmod_ambiguity`-style reporting
  (`types.py:340-360`) anchors at the USE — its callers hold the node;
  thread the span through. Zero remaining `1, 1` anchors on this path.
- **Real names:** prelude registrations pass a source label (spelled so
  a reader can act on it, e.g. `std.task (prelude)`), so any REMAINING
  ambiguity report (two explicit imports; or prelude cells unit 0 found
  that unit 1's rule does not cover) names both sides. No `<unknown>`
  reachable from the import/prelude paths.

## Obligation 2 — consumer sweep

The precedence flip is error→works only — no program could rely on the
error, and no resolution silently changes (the previously-ambiguous name
was unusable bare). The corpus run is the sweep; sawos's qualifier
workarounds are the standing regression case for "qualified access
unaffected" (row below covers it in-tree).

## Tests

1. `import x.{Thread}` beside the prelude: compiles; bare `Thread` IS
   x's (probe a member only x's has); both import-before-use and
   use-in-another-decl-order.
2. Local `struct Thread` beside the prelude: unchanged (regression row).
3. Glob `import x.*` bringing a prelude-colliding name: per unit 0's
   probed cell + the ruling.
4. Shadow + qualified escape: `import std.task` + `import x.{Thread}`;
   `task.Thread<Int>` still names the prelude one.
5. Genuine two-import ambiguity: errors AT THE USE SPAN, both real
   module labels, hint intact.
6. Every additional cell unit 0 found asymmetric, one test each.
7. Docs: LANGUAGE_SPEC's import/prelude precedence text states the full
   ladder; saw-lang skill note (it currently teaches the qualifier
   workaround); README only if it states precedence.

## Gates

Compiler change: per-commit full suite + freestanding both arches;
terminal full battery shared with design 254's dispatch (one battery
after the version-bump commit, which is the dispatch's last).
