# Design 109 — silently unchecked trait bounds for primitive type args (queued Aug 3)

Found by the design-108 agent (pre-existing, orthogonal, tracker-
flagged). The generic bound check derives a `concrete_type_name` only
for STRUCT/ENUM type arguments, so a user-trait bound against a
PRIMITIVE arg is silently skipped: `func f<T: Fooable>(...)` accepts
`f<Int>(...)` (explicit AND inferred) even with no
`extension Int: Fooable`. Silent acceptance of an invalid program —
the never-hide-errors class. (Manifest failure today: a body calling
the trait method on T fails later, unanchored or wrongly, or a default
body dispatches that shouldn't exist.)

## Scope
1. Extend the bound check's concrete-type derivation to EVERY type a
   type argument can be: primitives (Int/UInt/fixed widths/Float/
   Bool/String), tuples, Optional/Result/Box/Arc/Vector/Map/Set,
   closures, existentials — anything expressible as a type arg. For
   each, consult the SAME conformance registry the trait-method
   dispatch uses (primitives DO conform via extensions — Equatable/
   Comparable/Hashable/Printable on Int etc. must keep passing;
   built-in synthesized conformances count).
2. The failure is the existing bound-violation diagnostic naming the
   type and the missing trait, anchored at the call (inferred args:
   naming the INFERRED type, per design 93/105 style).
3. AUDIT the fallout: the suite + std/blade/libs compile may surface
   latent violations that were silently accepted (the design-100/107
   sweeps found the corpus clean of shadows; this one may differ).
   Fix real violations found (add the missing conformance or correct
   the bound) — each is a real latent bug. Report the count.
4. Tests: primitive bound violation (explicit + inferred) errors;
   primitive bound SATISFIED via extension passes (`extension Int:
   Fooable` then `f<Int>` ok); Vector/tuple/closure args checked;
   existing prelude-trait bounds on primitives stay green (regression
   heavy — Equatable-bounded generics over Int are everywhere).
5. Docs: tracker (flag closed); skill/spec only if a user-visible
   rule statement changes (the RULE was always "bounds are checked" —
   this fixes the implementation to match).

Bars: full suite (baseline 960, zero xfails) + bootstrap (incl. libs
4+4) green per commit. Standing policy — but per the batch-closure
decision: any NEW discovery is briefed + tracker-flagged for user
review, NOT auto-dispatched. Foreground suites; interruption-safe;
skill self-review.
