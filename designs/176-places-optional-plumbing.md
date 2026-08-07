# Design 176 — the places/optional plumbing batch

**Status: ALL UNITS PRE-DECIDED (user, Aug 7 — each ruling cited inline; no
open design questions in this brief). The batch exists because one afternoon
of probing (DF-146 discussion + design 174's sweep) produced a coherent
cluster of typechecker/parser plumbing defects with rulings already made.
ACCEPTANCE MECHANISM: design 174 landed 12 `// XFAIL: DF-…` pin tests whose
EXPECT directives state post-fix behavior — every unit that fixes a pinned
finding MUST remove the marker in the fixing commit (XPASS breaks the build
otherwise). Queue: dispatched after 170+174 integration. NOT in this batch:
DF-174c's `Int??` SUGAR question (user decision, pile) — but unit 9 gives
nested optionals their generic spelling, so nothing stays unnameable.**

## Units

1. **DF-146l — None-literal expected-type propagation, FOUR sites** (Map
   literal value; `??` RHS against a nested optional; a generic call
   argument; a generic default value) + the HARDENING rule: any remaining
   untyped `None` reaching codegen becomes a clean anchored error, never an
   ICE.
2. **DF-146m — optional auto-wrap at instantiated generic params.**
   `m.insert("y", 7)` on `Map<String, Int?>` wraps like a written `Int?`
   param does.
3. **DF-146j — `Map.get` becomes the borrows-get SYNONYM of `[]`** (both
   conditional lends `-> V?`); the copy-shaped `get` and its Copy bound are
   deleted; audit in-tree `get`-result-fed-to-`&var` uses (expected zero —
   that pattern mutated a temporary).
4. **DF-146n — `m[k]! = v` is a legal assignment target**: whole-value place
   write through the forced conditional lend, panics on absent — symmetric
   with `v[i] = fresh`.
5. **DF-146o — optional-chain assignment accepts place-expression heads**:
   `m[k]?.field = v` — head lends, an absent head skips the write AND the
   RHS (ordinary `?.` short-circuit), types `Void?`. Design 111's head rule
   learns places; both subscript and named-lend heads.
6. **DF-169d — a-lite primitive conformances**: uniform declaration
   acceptance for EVERY primitive (Int/UInt/all widths/Bool/Float/String),
   full generic-bound participation (monomorphized), and `&any`/`Box<any>`
   erasure of a primitive becomes ONE uniform clean error naming the two
   outs (generic bound / wrapper struct) — the String `i8* != i8**` ICE
   path folds into that error.
7. **DF-174a (highest severity) — generic `-> T?` TAIL-expression return
   skips auto-wrap** and emits malformed IR (`ret i64` vs `{ i1, i64 }`);
   reproduces at `T = Int`, so fix the tail path generally, with tests at
   both a trivial and an Optional instantiation.
8. **DF-174b — spawning a task returning an Optional ICEs.** Fix; MT and
   single-threaded group tests.
9. **DF-174d — `Optional<T>` becomes a wired type name** (the `Result`
   precedent — the asymmetry is historical), which also gives `Optional<Int?>`
   as the nested-optional spelling; AND a bare UNKNOWN type name gets a real
   diagnostic (today it passes silently — that half is its own small fix).
10. **DF-174e — `v[i] = <T? value>` element-type error names the wrong
    type.** Fix the diagnostic (and verify the assignment itself works once
    named right).
11. **DF-174f — later-arg fixpoint unifies a bare `None`** with the Optional
    a later argument fixes (`f(None, 5)` where both args type `T?`).
12. **Tracker hygiene**: renumber the colliding Aug 7 DF-146l/m/n/o entries
    against the older Aug 6 design-146 set (174's report flagged it); one
    commit, links updated where cited.

## Gates

Per-unit commits, full battery each (suite — with the XPASS rule enforced —
lexdiff, astdiff, Saw-irdet --all, bootstrap, gmgate, sos_runner both
arches). Every fixed pin flips xfail→pass with its marker removed in the
same commit. Final state: zero xfails citing findings this batch fixed;
xfails citing OUT-of-batch findings (e.g. the `Int??` sugar) remain, cited.
Docs per design 125 where surface changes (146j/n/o and 174d touch
spec/skill). DF-176x findings for anything new, fixed or filed.

## Explicitly out

`Int??` postfix sugar (user decision pending); `#lend_var` (design 175's
investigation); full primitive boxing (the (a) upgrade); DF-170a's sleep
chunking (own decision); anything 172/175 own.
