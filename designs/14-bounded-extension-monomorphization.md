# Design Brief 14 — Honor bounds when monomorphizing extensions

**Source:** brief-12 report (new issue #2 in `todo_jul26.md`'s status block):
a brief-09 regression. Read `designs/09-copy-trait-family.md` item 5 and the
DECISION in `designs/06-copy-semantics.md` for context.

## Problem

`extension Vector<T: Copy>` declares a *conditional* conformance: `copy()`
exists only when `T` satisfies `Copy`. But extension monomorphization
instantiates every extension method for every `Vector<X>` regardless of the
bound — so merely **constructing** `Vector<R>` for a non-Copy resource type
`R` fails at codegen with `cannot copy value of type R`. Vector (and
anything using the bounded-extension pattern) is unusable for resource
element types. This is what "conditional conformance" must actually mean:
the methods simply don't exist for unsatisfying instantiations.

## Fix

1. **Skip unsatisfied extensions at instantiation.** Wherever specialized
   extensions are selected/instantiated for a concrete instantiation
   (`codegen/generics.py` — extension monomorphization; check the
   typechecker's specialization path too), evaluate the extension's declared
   type-param bounds against the concrete type args first. Bound
   satisfaction: `Copy` = trivially-copyable | ImplicitCopy | ExplicitCopy
   (the typechecker has this logic from brief 09 — reuse it via a shared
   helper, do NOT reimplement in codegen; expose through the namespace if
   needed); any other trait = existing conformance lookup. Unsatisfied →
   that extension's methods are not instantiated, and any conformance it
   declares is not registered for that instantiation.
2. **Calling a nonexistent conditional method errors cleanly.** For
   `Vector<File>.copy()`: prefer a typechecker-time diagnostic naming the
   unmet bound (e.g. ``type `Vector<File>` has no method `copy`: requires
   `T: Copy`, and `File` does not conform``). If typechecker-time is
   disproportionate, the codegen-intercept error from brief 09 may remain
   as backstop, but it must not be a raw Python traceback if you can route
   it through the existing error reporting cheaply — judgment call,
   document it.
3. **Audit siblings.** `Map`'s `ExplicitCopy` delegation (brief 09), and any
   other bounded extensions in `sawc/std/`: verify `Map<K, NonCopy>` (if
   expressible) and similar cases behave — constructible, methods gated.

## Tests

- `vector_nocopy_elem_construct.saw` — construct a `Vector<R>` for a
  Deinit/NoCopy `R`, use non-copy-requiring methods (len, push with `move`
  if the signatures allow — probe what actually works and test that);
  `// EXPECT: success`. This is the regression test.
- `errors/vector_copy_nocopy_elem.saw` (existing) must still fail on the
  explicit `.copy()` — update its EXPECT-ERROR-CONTAINS if you improved the
  diagnostic (that's a diagnostic improvement, not a meaning change —
  say so in the report).
- **Brief-12 item 5 becomes expressible once construction works**: add
  `vector_elem_deinit.saw` — `Vector<R>` with Deinit-printing `R`, push
  elements (`move`), drop the vector, element deinits should print. Expected
  to still fail (elements aren't deinit'd — that gap is separate and NOT in
  scope to fix here): land it `// XFAIL:` per the verify-twice protocol,
  extending the tech-debt ledger.
- Full suite green: baseline 240 passed / 10 xfailed; expect +2 passing,
  +1 xfail, and NO existing xfail flips (if one flips, investigate — your
  change may have fixed or masked it; report).

## Report back

Where the bound-check landed (shared helper location, call sites);
typechecker-time vs codegen-backstop diagnostic choice; the Map audit
result; exact suite tally movement; anything the eager-instantiation fix
changed beyond Vector (search for other bounded extensions); deviations;
non-allowlisted commands (ideally none).
