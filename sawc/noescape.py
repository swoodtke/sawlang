"""The no-escape walk: does a written type NAME a reference?

References in Saw are PARAMETERS ONLY — a `&T`/`&var T` borrows storage the
caller owns for the duration of one call, and the Law of Exclusivity is
statically sound only because every live reference belongs to a call still on
the stack (designs 88/106, LANGUAGE_SPEC "no-escape invariant"). Every position
that stores or hands back a type therefore refuses one, and each refusal asks
the same question: what is the first reference reachable from this type?

ONE walk answers it now (design 193 unit 5). There were three, and they agreed
— which is the dangerous kind of duplication: each new position was added to
whichever copy the author was reading. Its entry points:

* `parser/types.py:_first_reference_in` — the WRITTEN form, at the position
  where it is written (return clause, struct field, enum case payload, generic
  argument). No aliases exist yet in the parser, so it passes no resolver.
* `typechecker/types.py:_first_laundered_reference` — the same walk once
  aliases ARE known (DF-188b), so `type R = &Int` is not a way past any of it.
* `typechecker/expressions.py:_first_reference_in_type` — a closure's INFERRED
  return type, which no declaration wrote down.

The walk stops at a nested function TYPE: its parameters take references
legitimately (`(&T) sync -> R` is the `with_ref` callback), and its own return
type was checked where it was written.
"""

from ast_nodes import TypeKind

# An alias cycle (`type A = B`, `type B = A`) is a separate diagnostic's job;
# this walk just refuses to spin.
_MAX_ALIAS_DEPTH = 12


def first_reference_in(t, resolve_alias=None, depth: int = 0):
    """The first reference type reachable from `t`, or None.

    Pre-order, so an outer `&T` names itself and a diagnostic can tell "is a
    reference" from "names a reference". `resolve_alias` (optional) maps a
    named type to what it aliases, or None when it names no alias.
    """
    if t is None or depth > _MAX_ALIAS_DEPTH:
        return None
    if resolve_alias is not None and t.kind == TypeKind.STRUCT:
        aliased = resolve_alias(t)
        if aliased is not None:
            return first_reference_in(aliased, resolve_alias, depth + 1)
    if t.kind == TypeKind.REFERENCE:
        return t
    if t.kind == TypeKind.FUNCTION:
        return None
    parts = []
    if t.kind == TypeKind.OPTIONAL:
        parts.append(t.inner_type)
    if t.kind == TypeKind.ARRAY:
        parts.append(t.array_element_type)
    parts.extend(t.element_types or [])
    parts.extend(t.type_args or [])
    for part in parts:
        hit = first_reference_in(part, resolve_alias, depth + 1)
        if hit is not None:
            return hit
    return None
