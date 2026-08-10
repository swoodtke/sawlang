# Design 204 — a private std type reserves nothing

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
