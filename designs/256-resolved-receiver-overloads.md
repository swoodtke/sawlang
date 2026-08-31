# Design 256 — The Overload Set of a Resolved Receiver (the DF-280a Fix)

**Status: AUTHORED Aug 31 2026** (lead; user-approved "fix those issues" same
day — dispatches with design 257 in one worktree, 256 first). Fix brief for
DF-280a, all three faces. Agent DF range: **DF-283a+**.

## The finding (tracker entry DF-280a has the full text + position matrix)

TWO paths answer "which methods does this receiver have", keyed on different
things. `_scoped_method` (`sawc/typechecker/expressions.py:8025`) reads
`struct_info.methods` / `struct_info.method_overloads` off the SYMBOL the call
already resolved; `_scoped_method_overloads` (`expressions.py:8039`)
re-resolves the set BY NAME through `Namespace.lookup_method_overloads
(struct_name, …)`, where `struct_name` is the receiver's WRITTEN SPELLING.
Whenever that name lookup misses, the `len(...) > 1` guard at
`expressions.py:10135` is False and the call collapses onto the
first-registered representative; every sibling overload is unreachable, and
the diagnostic blames the argument list.

Three faces, all probed (two hit in the wild by sawos):
1. a receiver reached through a module QUALIFIER (`pc_leaf.Panel` →
   ``` `add` has no parameter named `knob` ```);
2. the qualified-STATIC route (`expressions.py:9730`), which consults no
   overload set AT ALL (`pc_stat.Bag.make(from:…)` refused);
3. a receiver whose type NAME IS UNBOUND in the file — `import dep.{hand}`,
   the value arrives through the call, `c.make(top: 1)` demands `entry`
   (sawos SL-11, `tests/waiter-revoked`). The workaround imports a name the
   file never writes: DF-247b's phantom-dependency shape.

Also riding the same broken list: `_instance_method_alternative` (DF-217q's
static-vs-instance disambiguation finds no alternative), and the design-142
call-site ambiguity check — so a qualified receiver SILENTLY takes one of two
indistinguishable extension methods where the bare receiver reports the
ambiguity.

sawos SL-11's framing, adopted here: this is design 249's rule at the other
declaration kind. Design 249 ruled an import binds the WHOLE overload set a
free-function name stands for (DF-242b fixed the first-member-only bare form);
extension methods were never swept, and a method is not imported by name at
all — it is reached through the design-142 extension neighbourhood — so the
set must be keyed on the RECEIVER TYPE, never on which of its names an import
happened to mention.

## The fix (obligation 1 — one funnel, entry points named)

**One resolver answers "the overload set of this RESOLVED receiver, in scope
here", keyed on the receiver's type identity** (design 144: defining module +
name), never on a written spelling:

1. Read the full set off the resolved `struct_info` (`methods` +
   `method_overloads` — whatever `_scoped_method` already reads), NOT through
   a namespace name lookup.
2. Filter each member through the two existing predicates, exactly as the
   bare-receiver path does: `_ext_scope_allows` (design 142/254 scope) and
   the design-80 member gate. Nothing about VISIBILITY changes — only which
   candidates exist to be judged.
3. Route every entry point through it. The known ones (DF-280a's matrix —
   the agent verifies this list is complete by sweeping
   `lookup_method_overloads` callers): `_scoped_method_overloads`
   (`expressions.py:8039`), `_instance_method_alternative`, the
   qualified-static route (`expressions.py:9730` — which today takes
   `struct_info.methods[name]` and must consult the set like the bare static
   route at `expressions.py:9896` does), and the design-142 call-site
   ambiguity check.
4. The funnel's docstring NAMES its entry points.

Enums take the same treatment as structs wherever their extensions carry
overloads — probe, don't assume.

## Obligation 2 — consumer sweep

Error→works for faces 1-3 (no program could rely on a refusal). ONE real flip:
the ambiguity face — a qualified receiver that today SILENTLY resolves one of
two indistinguishable extension methods starts reporting the design-142
ambiguity error. That is the finding's soundness half, not a regression; the
corpus run is the sweep, and any newly-ambiguous in-tree call is a finding to
examine.

## Tests

- The cited XFAIL pin `examples/overload_set_reaches_unnamed_receiver.saw`
  FLIPS — remove the marker in the landing (XPASS policy), keep the file.
- New rows: instance call through a qualifier reaching BOTH overloads;
  qualified static with overloads (both members callable); the
  static-vs-instance alternative face; the ambiguity face (two
  indistinguishable extensions, qualified receiver, error AT THE CALL naming
  both modules — the bare-receiver twin already exists in the 142 tests);
  an unbound-name receiver whose method arrives through rule 3 only
  (no import of the defining module at all — the facade shape).
- `examples/ext254_facade_forwards.saw` carries a header note restricting
  itself to un-overloaded methods because of DF-280a — amend the note (and
  optionally the calls) once the restriction is dead.

## Docs

Skill + spec: wherever the qualifier/overload interaction is described
(design 150's "a qualifier works in every position" promise now extends to
the method-call position — say so where DF-280a would have been the caveat).
README untouched.
