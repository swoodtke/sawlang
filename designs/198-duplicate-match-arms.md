# Design 198 — an exact duplicate match arm is an error

**Status: RULED + AUTHORED Aug 10 (morning review), ready to queue.
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

## Explicitly out

Overlap/subsumption analysis (a `case 1..=9` shadowing a later
`case 5` stays legal and is guard/range semantics, not a defect);
usefulness/reachability warnings (a `-W` category is future material,
not this brief).
