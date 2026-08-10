# Design 204 — a private std type reserves nothing

**LANDED Aug 10**, all four units, tracked battery green. DF-153b and
DF-153a closed; DF-204a and DF-204b filed. The decisions the units
needed beyond the brief's text are recorded at the bottom.

**Status: RULED + AUTHORED Aug 10 (check-in), dispatch beside 196.
Closes DF-153b (probe-confirmed severe: a user `enum State` is REFUSED
on main today, reserved by std/once.saw's PRIVATE `State` since Aug 9)
and DF-153a (two std FILES cannot declare the same type name). One
root: the std sources type-check as one `builtins` unit, so every
std-internal type name lands in a single flat namespace that both
collides internally and leaks into every user program. The ruling is
design 144 applied to std itself: TYPE IDENTITY is (defining module,
name), and each std FILE is its own module (design 82) — so a private
std type's identity is its file-module's, it reserves nothing in user
programs, and two std files may each own a private `State`. Public std
types (prelude + import-gated) keep their existing exposure exactly.**

## Units

1. **Conformance rows FIRST (obligation 3 — this is a namespace
   contract the docs promise).** Rows: a user `enum State: Int`
   compiles and matches (the DF-153b severity probe); a user
   `enum SysError`/`struct File`-style name beside the gated std type
   (the design-82 promise, likely already covered — dedup via INDEX);
   flip `examples/user_enum_name_vs_private_std_enum.saw` (XFAIL
   DF-153b) in the unit that lands the fix. DF-153a's two-files case
   is std-authoring-internal — cover it with a compiler-level test
   (the builtins unit itself declaring two same-named private types
   once the fix allows it, or a tools/ test if no natural std case
   exists yet; note which).
2. **The identity fix.** Key std-internal type registration by
   (file-module, name) through the design-144 identity machinery
   rather than the flat builtins table; user-program lookup must not
   see private std types AT ALL (visibility, not just collision — the
   design-80/82 gate finishing the job for types). Survey the
   registration/lookup sites with the census discipline (probe, don't
   grep-trust): `namespace` registration, `get_enum_info`/struct
   lookups, `_resolve_type`, the design-194 provenance path. The
   entry-point list goes in the funnel docstring (process rule 1).
3. **Mangling + codegen follow.** Two same-named types need distinct
   mangled identities (design 144 already solves this for user
   modules — reuse its spelling for std file-modules). irdet --all is
   the gate: emission must stay DETERMINISTIC; a one-time wholesale
   IR-name shift for std-internal types is acceptable IF byte-stable
   across runs — record the before/after in the commit. The bench
   stage's checksums must be unchanged.
4. **Docs + close-out.** Spec design-144/82 sections state the rule
   ("a std file's private types reserve nothing; two std files may
   each own a name"); tracker closes DF-153b + DF-153a; the 153 brief's
   blocked net.saw SYS_* conversion becomes UNBLOCKED — note it as
   ready for a mech follow-up (do NOT do the conversion in this brief).

## Gates

Per-unit commits, full tracked battery each; irdet --all mandatory at
every unit (identity changes touch mangling). Zero uncited xfails.
Anything revealing a deeper identity question (e.g. extension lookup or
conformance coherence interacting with the new keys) STOPS and files —
the orphan rule and extension scoping must be provably unaffected.

## Explicitly out

Any change to PUBLIC std type exposure (prelude and import gate stay
exactly as designs 82/150/194 left them); the net.saw SYS_* conversion
itself (mech follow-up); user-module identity (144 landed it; this
brief only extends its key to std file-modules).

## What the units decided (Aug 10)

1. **"Private" had to become a DECLARED fact.** The brief's key is
   `(defining module, name)` for a std type that is private, and std had
   no way to say which those were: the parser defaults a top-level type
   to `Visibility.PRIVATE` and std ignored the answer, so `Vector` and
   `MapSlot` were equally "private" and equally exposed. The surface was
   sorted BY HAND — read the std sources against the prelude gate and the
   documented API, mark what a program may name — and 40 `public` markers
   now say what std publishes. That is the design-80/82 gate finishing the
   job for types, and it is why `--emit-docs` on std reads
   `public struct Vector` from here on.

   Counted from the compiler's own view after the fact: **101** type
   declarations (29 in `builtin.saw`, 72 in `std/`), of which **48** are
   declared public (40 markers this brief added, 8 already there) and
   **24** are file-private. The classification itself rests on the suite
   and the battery, not on a survey: a type wrongly marked private breaks
   loudly, which is the failure mode this approach was chosen for.

2. **`builtin.saw` is exempt wholesale.** It declares the compiler's own
   vocabulary, holds no private type, and every name in it is either
   published or reached by string from `sawc/`. Qualifying anything there
   would be pure churn.

3. **Four internals stay `public` because the compiler spells them.**
   `__TaskCell`/`__ResultCell`/`__VoidCell` and `RangeInclusive` are
   selected by string in `coro_transform.py` and `codegen/loops.py`. They
   keep the plain identity, with a comment saying why. Filed as DF-204a:
   the ruling holds for 24 of 28 genuinely internal types, and closing the
   last four means teaching those sites to resolve through the identity
   map.

4. **The lookup needed a MODULE, and it is one funnel.**
   `Namespace.module_type_names` is `module_statics` (DF-140h) for types;
   `TypeChecker._type_lookup_module` is the single decision procedure for
   "whose private names are in scope", and its docstring names its five
   entry points (`_canonical_type_name` plus the four `get_*_info`).
   `_canonicalize_module_types` became PER FILE and now runs in `check()`
   too, which is what lets the whole-program passes read a signature with
   no file in hand.

5. **Two design-144-era bugs were in the way**, both invisible until std
   qualified: `name.split('$')[0]` at seven sites read a module qualifier
   as a monomorphization suffix (the symptom was `Data` losing its
   `Send`ness and 27 net/process tests failing), and a coroutine frame
   struct must never be qualified because it is named by string.
   `type_identity.declaration_base` and `Struct.is_synthesized` are the
   two fixes.

6. **The IR shift, measured** (`examples/alloc_data_tiers.saw`, pre-fix
   compiler vs this one): 120 top-level symbols before and after, 25
   renamed one-to-one, every rename a std-internal family
   (`DataBuf_*` -> `DataBuf$m$std_data_*`). Eleven further differences are
   not renames — closure symbols carrying the source LINE they were
   written on, moved by a three-line comment. Filed as DF-204b.
