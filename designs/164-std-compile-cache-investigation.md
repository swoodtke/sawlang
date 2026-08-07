# Design 164 — per-module compile caching: the investigation

**Status: APPROVED as an INVESTIGATION (user, Aug 7: "another
investigation should be per-module (or per-file) compile caching...
emit a binary cache of the std module which can be reused by each
binary"). Measurement, feasibility audit, and a costed recommendation
— the implement decision returns to the user. A LOW-RISK prototype of
the cheapest tier MAY land behind a flag if its differential gate is
airtight; anything deeper is design-first.**

## The problem

Every sawc invocation parses, typechecks and codegens builtin.saw +
all of std from scratch. The suite is ~1400 invocations; the remote
worker's jobs pay it; the self-hosting track will pay it worse.
`.build/rt/` already proves the pattern (digest-keyed cached objects,
auto-linked); std is the same idea one layer up.

## Units

1. **Profile where the time goes.** Instrument one compile (and a
   corpus sample): wall time per stage — std parse, std typecheck,
   std codegen, user-code stages, LLVM opt/link — so each cache tier
   has a ceiling attached. Report per-compile and battery-wide
   multiples.
2. **Tier A — AST cache (cheap).** Serialized parsed std ASTs (+ doc
   trivia), keyed by content digest. Assess serializability of the
   AST graph; prototype if clean; measure. Oracle: astdiff between
   cached and fresh must be byte-identical, and irdet cold-vs-warm.
3. **Tier B — typechecked-namespace cache (medium).** Audit the
   namespace/symbol object graph for serializability (type objects,
   conformances, effect info, the design-144 identities, the
   design-82 per-file std modules). Verdict + effort estimate; no
   prototype unless the audit is clean.
4. **Tier C — precompiled std object (the big one).** Analysis, not
   code: what fraction of std codegen is NON-GENERIC (cacheable as a
   .o outright) vs generic templates that must stay per-binary for
   monomorphization? Which prelude instantiations (Vector<Int>,
   Map<String, V> shapes, String machinery) recur often enough to
   pre-instantiate? How does it compose with --gc-sections, the
   design-80/82 visibility gates, and the 144 mangling (stable symbol
   identity should make this FEASIBLE — verify)? Effort estimate.
5. **The cache key, designed once.** (compiler-source digest, std
   digest, target triple, profile flags: freestanding /
   runtime-build / no-hidden-alloc / -O level). Invalidation story;
   where cache lives (.build/stdcache/ beside .build/rt/); how the
   remote worker's digest-keyed scheme extends. A WRONG key is a
   stale-cache miscompile — the differential gate (compile the corpus
   cold and warm, byte-compare every artifact) is non-negotiable for
   any tier that ships.
6. **Recommendation with numbers**: per tier — ceiling, measured or
   estimated win, effort, risk. The user picks the tier(s).

## Constraints

Read-mostly; tier-A prototype may land BEHIND A FLAG (default off)
only with the cold/warm differential green over the whole corpus.
Full battery for any sawc/tools change (suite zero xfails, lexdiff,
astdiff, irdet --all, bootstrap, sos_runner, gmgate). Findings as
DF-164x. Report into the tracker as a design-164 section.
