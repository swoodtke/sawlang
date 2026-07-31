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

## LANDED (Jul 30)

Root cause — ONE family, an erased-box default-type-arg mangling
divergence:
- The typechecker canonicalizes an erased `Box<any Trait>` to arity-2
  `Box<any Trait, Global>` (filling the allocator default) on every
  expression/annotation type. Codegen, however, registers composite types
  that EMBED the box — the `Box<any Error>` err arm of `Result<T,
  Box<any Error>>` — from the RAW arity-1 method annotation
  (`_declare_extension_methods` lowers `method.return_type` directly), and
  its `_canonicalize_type_kind` deliberately left erased boxes untouched.
- So a `Result<T, Box<any Error>>` registered under
  `...Box$1$$Any$Error` while a `match`/`try` on the call result (a
  typechecker-stamped, arity-2 type) looked it up under
  `...Box$2$$Any$Error$Global`. The name mismatch fell through to the
  match's LLVM-type fallback, which — because distinct Result
  monomorphizations with same-sized payloads share `{ i32, [N x i8] }` —
  SILENTLY selected a WRONG enum. The Ok/Err payload was then extracted at
  the wrong type: symptom (b) `Vector<Dependency>.get(i)` read as a
  `String`/`TomlValue`; symptom (c) a `Manifest`/`Version` receiver mixed
  up ("Undefined method: Version.version"). Only reproduced in blade's full
  type population because it needs a same-sized sibling Result to collide
  with (the columnar DepList's larger payload happened to be size-unique).

Fix (at the source): normalize an erased box to codegen's native
canonical arity-1 in `_canonicalize_type_kind` (drop a redundant trailing
`Global`; a non-default allocator is preserved), and route the two
lookups that previously mangled a typechecker-stamped arity-2 type
directly — `_generate_match_expr`'s enum-name and `_get_result_enum_name`
(the `try` path) — through that same canonicalizer. Registration and
lookup now agree; the same-sized LLVM-type fallback is no longer reachable
for this class.

Un-work-arounds:
- blade `DepList` holds a natural `Vector<Dependency>` again.
- blade's resolver `import semver.{Version, VersionReq, parse_version,
  parse_req}` (self-contained matcher deleted); `semver = { path =
  "../libs/semver" }` in Saw.toml; Saw.lock regenerated (2 deps);
  `blade_bootstrap.py` maps semver for stage0. Blade self-hosts with
  semver by path.

Rider C6 — VERIFIED FIXED (no compiler change): method-level generic type
params on a non-generic-type extension (`extension String { func f<R> }`
and the same on a plain user struct) work for primitive, Bool, and owning
(`String`) `R`, with extra non-closure params. Locked by
`examples/plain_type_generic_method.saw`.

Flagged: L18 (module-qualified type annotation `v: mod.Type` ICEs codegen)
— orthogonal, worked around with selective import; ledgered in todo.md.

Isolated compiler repro for (b)/(c) is order/same-size-collision
dependent (why design 67 could not build one); the blade build with
natural rows + real semver dep, exercised by the bootstrap and the blade
test suite, is the regression coverage.
