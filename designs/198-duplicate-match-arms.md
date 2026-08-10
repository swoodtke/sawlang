# Design 198 — an exact duplicate match arm is an error

**Status: LANDED Aug 10 — all three units, tracked battery green, DF-192d
closed. Two of the brief's premises were wrong about today's compiler and
the units corrected them; both are recorded under "What the units found"
below. One finding filed: DF-198a.**

**Originally: RULED + AUTHORED Aug 10 (morning review), ready to queue.
Small. Closes DF-192d (duplicate enum arm = LLVM-level ICE today) with
the ruling: an EXACT duplicate arm — enum variant or literal — is a
clean compile error naming both arms; overlapping ranges and guarded
arms stay legal, because first-match-wins is match's real, documented
semantics and overlap is how those are written. The deciding fact: the
enum lowering is a switch, which HAS no arm order, so "first wins" was
never today's semantics there — there is nothing to stay consistent
with, only a crash to replace.**

## Units

1. **The check.** Enum path: `_check_match_expr` already collects the
   matched-variant set — a re-add is the error, anchored at the second
   arm and naming the first's line. General path: an arm whose pattern
   is an exact duplicate of an earlier arm's (same literal value, same
   variant with same-shape bindings, same tuple of literals — TEXTUAL
   pattern equality after literal normalization, NOT overlap analysis)
   errors the same way. Two wildcard arms already error today —
   verify, and fold that check into the same place if it is separate.
   Ranges, guards, and distinct-binding-name duplicates of the same
   variant are untouched.
2. **Pins + ledger.** `examples/match_duplicate_enum_arm.saw`
   re-authors to the ruling (EXPECT: error at the duplicate `Green`
   arm; its literal sibling becomes a second error row rather than a
   first-wins run); the DF-192d signature leaves
   `tools/sawfuzz_known.txt` in the same landing. Consumer sweep
   (rule 2, cheap): the suite plus a corpus grep for duplicate arms —
   an exact dup in existing code is dead code and gets deleted, not
   grandfathered.
3. **Docs.** Spec patterns section (one sentence: exact duplicate arms
   are errors; overlap resolves first-match); skill patterns bullet.

## Gates

Tracked battery per unit; irdet unaffected in principle, run as usual.

## What the units found

Two premises in unit 1's text did not hold against the compiler, and the
implementation follows the ruling rather than the premise.

1. **Two wildcard arms did NOT already error.** They compiled, and the
   first won. There was no separate check to fold in — there was no check.
   `case _` twice is now the `('any',)` key, and a wildcard and a bare
   binding key alike, since one catch-all under two spellings is still one
   catch-all.
2. **Binding names are NOT part of the key, so
   "distinct-binding-name duplicates of the same variant are untouched"
   could not stand.** `case Move(x, y)` beside `case Move(a, b)` is
   EXACTLY the shape that crashed: the enum lowering is a switch keyed on
   the tag, so the second arm emitted a duplicate case value whatever it
   called its payload. A rule that read binding names would have left
   DF-192d's ICE alive under its most natural spelling, which is the one
   thing this brief exists to remove. Unit 1's own prescription — "the
   matched-variant set, a re-add is the error" — is keyed by variant name
   and says the same thing, so the two clauses disagreed and the operative
   one won. Every irrefutable hole therefore keys the same, uniformly on
   both paths, and REFINEMENT still distinguishes arms: `case Filled(0)`
   ahead of `case Filled(n)` is two patterns, not one.

The rule lives at one chokepoint, `_check_duplicate_match_arms`, called
from `_check_match_expr` before it picks a lowering — so both entry points
into arm checking are behind one call (obligation 1). The consumer sweep
(obligation 2) parsed every .saw file in the tree, 1882 of them, and found
zero duplicate arms outside the pin: the rule breaks no existing code.

## Explicitly out

Overlap/subsumption analysis (a `case 1..=9` shadowing a later
`case 5` stays legal and is guard/range semantics, not a defect);
usefulness/reachability warnings (a `-W` category is future material,
not this brief).
