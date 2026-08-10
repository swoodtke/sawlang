# Design 199 — nested-call references join the Law of Exclusivity

**Status: RULED + AUTHORED Aug 10 (morning review), ready to queue.
Closes DF-188j with the ruling: a by-reference argument created by a
NESTED call in the same argument list joins the OUTER call's access
set, so overlapping roots are an exclusivity error on every copy tier —
mirroring the place rule design 188 unit 2 already landed. Disjoint
roots stay legal (`f(&var x, g(&y))` compiles). Today
`sink(&var p.a, reset(&var p))` compiles with no place in sight and the
answer depends on argument evaluation order (probed: a=107 b=200);
memory-safe but order-dependent, which is exactly what the Law exists
to prevent — and the same shape spelled through an accessor is already
refused, an inconsistency with no principle behind it.**

## Units

1. **Conformance rows first (obligation 3 — exclusivity is a safety
   surface).** X-family rows: the DF-188j shape (reject), the disjoint
   shape (accept), a nested call whose ref targets a DIFFERENT root
   than every sibling (accept), the receiver-position variant
   (`p.m(reset(&var p))` — probe whether the receiver borrow already
   catches it), and the two-nested-calls-one-root shape (reject).
2. **Consumer sweep (obligation 2 — this flips legal-today code).**
   Sweep examples/ + sawc/std + blade/ + libs/ + devtools/ for
   argument lists where a `&`/`&var` argument's root overlaps a
   nested call's `&`/`&var` argument root. Record the list; fix
   offenders in the landing (each is order-dependent code and each fix
   is a hoisted `let`). Expect few; `Vector.fold`'s
   `acc = combine(move acc, ...)` shape is a MOVE, not a borrow, and
   is untouched — 193 u4 already proved that distinction matters.
3. **The check.** Extend 193 u4's `_check_call_exclusivity` funnel:
   argument collection descends into nested calls' by-ref arguments
   (via the `ast_walk` shared walk), each joining the outer access set
   with its own path root. Same overlap test, same diagnostic family,
   naming the two references and their one root. Docstring's entry
   list updates (process rule 1).
4. **Pin + docs.** The DF-188j repro lands as the reject conformance
   row; spec (Law of Exclusivity section: an argument's borrow extends
   over the whole call expression, nested calls included) + skill
   bullet under the 188 exclusivity entry.

## Gates

Per-unit commits, tracked battery each; irdet --all (typechecker-only,
byte-identity expected). The sweep list is the review surface.

## Explicitly out

Borrow lifetimes/regions in general (the Law stays per-statement); the
DF-176c receiver-copy half (design 200); any place-machinery change
(188/193 already cover places).
