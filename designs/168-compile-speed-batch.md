# Design 168 — the compile-speed batch

**Status: APPROVED (user, Aug 7: "we should really focus on any
recommendations by the compile-cache investigation - the test
runtimes are really slowing down development"). Priority-jumped:
dispatches with/after DF-163a, ahead of 166/167, concurrent with the
post-M1 wave (disjoint surfaces). Built from design 164's FINDINGS
section (read it first — the numbers and the run-1 miscompile lesson
are the contract's foundation).**

## The shape of the problem (164's profile)

LLVM opt+object 47% + codegen IR build 17% = the back half is ~64% of
every compile, and 90.1% of emitted IR is std — `hello.saw` (4 lines)
emits 27,922 IR lines / 449 defines. The front half (std parse 14% +
typecheck 10%) re-enters 2-3x per compile. Caching only ever touches
the front half (~19% best case); the back half needs EMISSION to
shrink, not caching.

## Units, in order

1. **DF-164b — the link dead-strip (trivial, first).** The hosted
   link line has no dead-strip: add function/data sections +
   `-Wl,-dead_strip` (darwin) / `--gc-sections` (linux) to the clang
   link. Verified by hand at 218,216 → 62,712 bytes for hello
   (52-76% of every binary is dead std today). Size win, ~zero risk;
   assert sizes in a test.
2. **The pre-LLVM reachability strip — the compile-TIME win, and it
   needs NO cache.** Emit (codegen + LLVM) only the REACHABLE subset:
   walk the checked program from the entry points (main, `@export`s,
   runtime-seam references) through calls, monomorphized
   instantiations, CONFORMANCE vtables of instantiated types, drop
   glue, and the coro-transform's synthesized callees — then codegen
   only that set. hello's 449 defines should collapse to dozens,
   taking the 64% back half down proportionally FOR EVERY COMPILE —
   suite, blade, bootstrap, irdet, the remote worker, all of it.
   SOUNDNESS RULE: when in doubt, keep it — an over-kept symbol
   costs bytes the link strip now removes anyway; an over-stripped
   one is a link error (loud) or a missing vtable entry (make it
   structurally impossible: vtables pull their methods, not the
   reverse). The full suite + gmgate + bootstrap + sos are the
   behavior oracle; irdet --all gets FASTER and stays byte-identical
   per seed-pair by construction (the reachable set is deterministic).
3. **DF-164a + DF-164c — deterministic symbol names (prerequisite
   for tier B, and irdet hygiene NOW).** Node-id-derived generated
   names (`__collit_<id>`, ...) and the four synthesized-symbol
   counters make std's emitted IR program-dependent. Re-key from
   stable coordinates (defining file + position + kind, or a
   content hash) so identical input produces identical names
   regardless of allocation order. 164's run-2 differential (43
   .ll-only divergences, objects byte-identical) is the acceptance
   test: after this unit, that differential is 1114/1114 identical.
4. **Tier B — the front-half cache (after unit 3, with 164's
   lessons).** Serialized parsed+typechecked std restored BEFORE the
   entry file parses (the run-1 miscompile was restoring after —
   node-id collision merged two functions' suspend analysis; the fix
   is order + counter seeding from a stored bound). The ONE cache
   key from 164's unit-5 design: whole sawc/*.py digest + std digest
   + triple + profile flags, content-addressed, atomic publish,
   never keyed on the blob's own bytes. Gate: the STRICT whole-corpus
   differential (rc, stdout, stderr, .o, AND .ll) green, plus the
   battery. Expected: ~19% off CLI-path compiles (blade, bootstrap,
   sos_runner, irdet, remote worker); the suite's smaller win
   (deepcopy → loads) comes free.
5. **DF-164d — the re-entry typechecks (cheapest wins only).** std
   is re-typechecked on each of the 2-3 front-half re-entries;
   establish what actually invalidates std analysis on re-entry
   (user-driven instantiations do; std's own bodies should not) and
   skip what provably cannot change. If nothing is provably
   skippable at small cost, record why and stop — unit 2 already
   moved the big number.

Tier C (precompiled std object, ~87% of IR) stays PARKED on the
user's design-144 exemption decision — unit 2 gets most of its win
per-compile without reopening type identity.

## Gates

Per-unit commits, full battery each (suite zero xfails, lexdiff,
astdiff, irdet --all, bootstrap, sos_runner, gmgate), plus unit-
specific: size assertions (1), the strict differential (3, 4).
Report before/after wall-clock for: hello CLI, full suite, bootstrap,
irdet --all. Findings as DF-168x.
