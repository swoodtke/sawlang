# Design 159 — the implicit-tier copy miscompile (DF-151b/DF-156b root cause)

**Status: APPROVED (user, Aug 6). P0 — dispatches the moment the
investigation agent's part-2 timing integrates; runs BEFORE the
DF-151a fix and before 150 (nothing tree-wide moves on a broken copy).
Decision [user]: ImplicitCopy STAYS implicit — "let's leave
ImplicitCopy implicit - but let's call it out in the docs clearly."**

## The bug (root-caused, commit 3186810's tracker rewrite)

A struct whose owning members are all trivial/ImplicitCopy (a String
field, an Arc, a closure) is AUTOMATICALLY ImplicitCopy-tier — no
declared policy, by design. But the copy lowering for this undeclared
tier emits a bare load/store with NO field retains, while every
binding's scope-exit drop releases the fields: one allocation, N
releases, freed-block corruption, and libmalloc traps at whatever
allocation comes next. Signal/site/timing looked random; load was
NEVER the cause (idle rates were higher). Affected: local-to-local
copy (`let b = a`) and by-value argument where the callee drops the
parameter. Struct-literal construction is clean. Guard Malloc makes
it 100% reproducible.

## Units

1. **Bisect first — regression or ancient?** Guard Malloc repro at
   `ec9c105^` (pre-P0-pair, before the instantiation-phase copy-
   emission rework) and, if clean there, walk back further. Record
   the answer in the tracker before writing the fix — it decides
   whether this is a revert-and-refix or a from-scratch repair.
2. **ONE lowering path.** The undeclared ImplicitCopy tier routes
   through the SAME copy-synthesis machinery a declared conformance
   uses — there must be exactly one implementation of "copy this
   composite" regardless of how the tier arose (the bug lived in the
   second, conformance-less path that nothing user-visible tested).
   Audit EVERY transfer-class site for the undeclared tier against
   `Namespace.copy_tier` (design 139's oracle): local copy, by-value
   argument, return, field write, enum payloads holding ImplicitCopy
   members, optional/tuple/array wrappers.
3. **Oracle hardening.** (a) Copy/refcount oracles use INTERPOLATED
   (heap) strings — literals are immortal (rc −1), so literal-based
   probes were vacuous, which is how this hid. (b) A per-field
   balance oracle: retains-on-copy == releases-on-drop − 1 original,
   asserted via counts AND validated under Guard Malloc. (c) The
   design-73 closure-env oracle is passing for the wrong reason
   (`strong_count` reads correctly while the env is double-released)
   — give it a detector that actually fails on over-release.
4. **Guard Malloc gate lane.** A small curated set of ownership
   oracles runs under `DYLD_INSERT_LIBRARIES` Guard Malloc as part of
   the standard battery (targeted, cheap — NOT the whole suite, which
   Guard Malloc would slow intolerably). This class of bug must never
   again be able to pass green.
5. **Docs [user decision].** The implicit tier is called out CLEARLY:
   LANGUAGE_SPEC copy-tier section + the skill's ownership section
   state in so many words — a struct/enum whose owning members are
   all trivial/ImplicitCopy is AUTOMATICALLY ImplicitCopy (its copy
   retains each refcounted field; no declaration needed); declaring
   the STRICTER `NoCopy` on such a type is legal and is the API-
   discipline escape hatch (pin with a test if untested today);
   declared-policy ceremony remains reserved for ExplicitCopy/NoCopy
   members, where a genuine choice exists.

## Tests / gates

The two DF-151b binaries (closure_copyable_struct_copied, blade
lock_drift) at 100/100 clean under Guard Malloc; the balance oracle;
by-value-argument and local-copy repros for struct + enum-payload
shapes; NoCopy-override test. Full battery: suite (zero xfails),
lexdiff, astdiff, irdet --all (venv), bootstrap, sos_runner.
