# Design 139 — the enum policy tier: no policy-exempt wrappers

STATUS: APPROVED (user, Aug 5). Queued after 138. Closes DF-131a by
generalizing, not special-casing: enums join the same policy discipline
structs got in designs 9/128/131. End state: every type — struct, enum, or
builtin generic — has exactly one transfer class, and every read consults
it.

## Problem (DF-131a)

The checkpoint's owning-enum arm handles an aliasing whole-enum read with a
payload RETAIN — correct for ImplicitCopy payloads (`String?`), meaningless
for NoCopy/ExplicitCopy payloads, which fall through to a bitwise copy:
`let p = o` on a `Res?` aliases and double-drops. Design 131 fixed every
payload PROJECTION; the whole-value read of the wrapper is the last open
door, and user-defined enums with owning payloads have the identical hole.

## Decided model

1. **Builtin generics declare bounded policy tiers** `[user]` — the
   `Vector` pattern (deinit on the plain unconditional extension;
   conformances bounded), spelled in builtin.saw:
   ```saw
   @synthesize
   extension Optional<T: ImplicitCopy>: ImplicitCopy {}
   @synthesize
   extension Optional<T: ExplicitCopy>: ExplicitCopy {}
       // derives copy(): None -> None, Some -> Some(payload.copy())
       // (design 128's payload-deep enum synthesis)
   extension Optional<T: NoCopy>: NoCopy {}    // marker tier; move-only
   ```
   Trivial `T` needs no conformance (trivial copies freely — `Int?`
   unchanged). Bounds are mutually exclusive, so exactly one tier matches
   any instantiation. Same treatment for `Result` (both parameters) and
   `Box`. `.copy()` on an optional stops being rejected — it exists
   exactly when the tier provides it.
2. **User enums get struct parity** `[user]` — an enum with an
   ExplicitCopy or NoCopy payload must DECLARE its policy
   (`extension E: NoCopy {}`, or `@synthesize extension E: ExplicitCopy
   {}`); a bare owning enum is the same teaching error structs give.
   Enums with only trivial/ImplicitCopy payloads keep working undeclared
   (parity with String-field structs).
3. **The checkpoint arm becomes a policy lookup.** The owning-enum arm's
   bespoke retain-on-alias is replaced by the ordinary four-way policy
   branch; retain remains the ImplicitCopy tier's lowering. Compiler-built
   remainder: Optional's unconditional deinit + the retain op itself.

## Work
Typechecker: bounded-conformance policy resolution for enum transfer
class; the declare-your-policy error for owning user enums; checkpoint arm
rewrite. builtin.saw: the tiers above for Optional/Result/Box. Synthesis:
none new (128's enum path). Migration sweep: in-tree user enums with
owning payloads declare their tier; containment cascade (structs holding
`File?`-class fields now need their policy) — count and record. Tests,
fail-before/pass-after: the DF-131a repro rejected then correct under
`move`; `Optional<Vector<Int>>` value-read rejected with three hints;
`o.copy()` on ExplicitCopy tier deep-copies (payload independence
asserted); NoCopy tier move-only incl. `take()`; trivial/ImplicitCopy
tiers behaviorally unchanged (retain oracle); bare owning user enum
errors; `Result` and `Box` tier spot-checks; containment cascade test.
Full gate battery. Docs: spec Copy-family + Optional/Result sections,
skill, README if examples change. Tracker: DF-131a closed.
