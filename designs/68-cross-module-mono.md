# Design 68 — DF6(b)/DF9(c): cross-module monomorphization/receiver confusion (queued Jul 31)

The last open miscompile-class bug. Only manifests in Blade's FULL
type population; design 67 built faithful isolated repros that all
pass — read its ruled-out list first (tracker + designs/67 progress
log) so you don't re-walk dead ends.

## Symptoms
- (b) `Vector<Dependency>` element read confused with another Vector
  monomorphization: reverting blade's columnar `DepList` to hold
  `Vector<Dependency>` ICEs "Cannot find field name in struct with
  type i8" (`d` from `guard let d = deps.get(i)` codegen-typed `i8` —
  a `.get` monomorphization collision).
- (c) `import semver` into blade + `semver.parse_version(...)` ICEs
  "Undefined method: Version.version" — a `.version()` call on a
  `Manifest` receiver mis-dispatched onto semver's `Version`
  (receiver-type confusion).

## Investigation direction (hypotheses, not conclusions)
Both smell like NAME-KEYED lookups that lose the module qualifier or
the active monomorphization context when a second module's type
population introduces same-shaped/same-named entries: mangled-name
collisions (`Vector$2$X$Global` where X's name collides across
modules?), a method table keyed by bare type name (`Version` exists in
blade-land as manifest's version STRING getter vs semver's struct),
or a type_param_context leak between per-module passes. The fix must
be at the source (qualify the key / thread the context), not a
point patch. Blade IS the repro: `blade build` with the DepList
revert (67's probe) and with the semver import (67's probe) — recreate
both probe states from the design-67 notes.

## Scope
1. Root-cause + fix (b) and (c) — likely one family. Minimal isolated
   locking tests if the fix makes one expressible; otherwise the blade
   probes become blade tests.
2. Un-work-around: revert DepList to `Vector<Dependency>` (natural
   rows); re-import libs/semver into blade's resolver replacing the
   self-contained matcher (delete it); blade's Saw.toml gains the
   semver path dep; lock regenerated.
3. RIDER — C6 VERIFY (conflicting records): probe method-level generic
   type params on a non-generic-type extension
   (`extension String { func f<R>(...) }`). If fixed (brief-40 note),
   close C6 in the tracker with the proving probe; if open, fix it
   here if it shares the monomorphization family, else re-ledger
   precisely.
4. Tracker: DF6(b)/DF9(c) closed; C6 resolved; design 68 landed.

## Bars
Full suite (baseline 770) + all blade/libs tests + bootstrap green per
commit; zero xfails. Standing policy: fix user-facing bugs on
discovery unless ambiguous. Load the saw-lang skill before writing
.saw code.
