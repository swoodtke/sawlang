# Design 197 — declaration-position name resolution

**Status: RULED + AUTHORED Aug 10 (morning review, cluster B), ready to
queue. The ruling: design 150's promise — a qualifier works in EVERY
position a name appears — extends to the three raw declaration slots
(struct field, enum payload, `type` alias RHS), and DF-194a is
position-incompleteness, not a design-144 identity question: the
identity answer is the one every already-resolved position uses. Folds
in design 190 rule 7's parse_type bypasses (six positions with loud
WRONG errors) — same neighborhood, declaration-position type resolution
done six half-different ways. UX debt, not soundness: everything here
is a wrong/confusing diagnostic on code that should compile (or a
refusal of a legal spelling), never a wrong program.**

## Units

1. **The position matrix, probed.** One row per declaration position a
   type name can appear in: the three DF-194a slots (struct field,
   enum payload, type-alias RHS — qualified name does not resolve) and
   rule 7's six parse_type bypasses (trait-conformance header,
   receiver spellings, and their kin — enumerate from the census in
   `designs/190-quality-program.md`, then PROBE each; the census's
   grep-shaped claims have been wrong before, see 190's errata).
   Record actual behavior per row before touching anything.
2. **One qualified-name resolution funnel.** The six duplicate
   qualified-name parsers collapse to one, and the three raw slots
   route their type names through the same `_resolve_type` path 194's
   provenance work already funnels — the std annotation gate then
   covers them for free (retiring the hand-wired slot code 194 u4
   noted). Docstring names every entry point (process rule 1).
3. **Pins + conformance.** `examples/qualified_type_in_declaration_slot.saw`
   flips (XFAIL DF-194a removed); each matrix row gets an example or
   conformance row; the std-gate W-family rows gain the three slots.
4. **Docs.** Spec (imports section: the "every position" list gains the
   declaration slots explicitly); skill import bullet likewise.

## Gates

Per-unit commits, tracked battery each. The unit-1 matrix is the review
surface. Consumer risk is low (new capability + better errors), but the
std gate reaching three new slots is a contract flip on those slots —
the unit-2 landing sweeps for signatures relying on the old leniency
exactly as 194 u4 did (expect near-zero; record it).

## Explicitly out

The parser port (this shrinks its surface; the port is its own brief);
any change to design-144 type identity (the ruling says none is
needed); expression-position resolution (already uniform).
