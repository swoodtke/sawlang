# Option Paper 08 — Exclusivity for `&var` references

**Status: DECISION NEEDED (user). Independent of 06/07 — can decide any
time.** Source: `todo_jul26.md` design concern 2: the spec never says what
`swap(&x, &x)` or passing `&v` and `&var v` in one call means, and "memory
safety by default" is a claim about exactly these cases.

## Why Saw is in an unusually good position

Rust needs lifetimes and Swift needs runtime checks because in those languages
references/inout can flow into places the compiler can't see from one call
site. **Saw's references cannot escape**: they exist only as function
parameters — they can't be stored in structs, returned, or captured (closures
capture by value — verified in `codegen/closures.py`: captures are copied
into the environment struct). Therefore, at any moment, every live reference
in the program was created in some single call expression on the stack.

Two references can only alias if they were passed **in the same call chain**
— and the only way a callee can pass on a reference is to forward its own
`var` parameter. So the alias question reduces to per-call-site argument
disjointness plus transitive forwarding, all statically visible. No lifetimes,
no runtime flags — *if* we keep the no-escape property. This is the payoff of
the language's core design bet, and it deserves to be stated as a theorem in
the spec.

## What can go wrong today (unspecified, currently allowed)

1. `swap(&x, &x)` — two `var` params alias; "swap" corrupts.
2. `f(&var v, & v)` — mutation invalidates what the read side assumes
   (for future Vector: reallocation UB).
3. Overlapping paths: `g(&p, &p.x)` — parent and field alias.
4. Forwarding: `func outer(var a: T, var b: T) { inner(&a, &b) }` called as
   `outer(&x, &x)` — aliasing arrives one level down.

## Options

### A. Static call-site exclusivity (Law of Exclusivity, fully static)  ⭐ recommended
Rule for the spec — **many readers XOR one writer**: *in a single call, an
access path passed by `&var` (including the receiver of a `var self` method)
must be disjoint from every other by-reference path in that call, mutable or
not. Immutable `&` paths may overlap each other freely* — with no writer in
the call, the overlapping storage is immutable for the callee's duration, so
aliasing is unobservable. (Bonus: guaranteed-unaliased `&var` params can be
marked `noalias` in LLVM.) By-value arguments overlapping a `&var` are
permitted with snapshot semantics — the copy happens at call setup — which
requires the spec to also pin argument evaluation order (already an open item
from design concern 5); `move x` overlapping any reference in the same call
is an error (value-transfer checkpoint territory).
Disjointness of access paths (`x`, `x.f`, `x.f.g`, `x[const i]`) is decidable
at the call site: same-root prefixes overlap, different roots don't. Dynamic
indices `x[i]`/`x[j]`: conservatively treated as overlapping when one side is
`&var` (error) — escape hatch below.
- Forwarding (case 4) is covered by applying the same rule at *every* call
  site: `inner(&a, &b)` is checked in `outer`'s body where `a`,`b` are
  distinct roots — sound because parameters are distinct storage unless the
  caller aliased them, which the caller's own call-site check rejects.
- **Pro:** zero runtime cost; small, explainable rule; implementable as one
  typechecker brief (a sibling of the value-transfer checkpoint — same
  call-argument walk); makes the safety claim real.
- **Con:** conservative on dynamic indices (`swap(&a[i], &a[j])` rejected
  even when `i != j`). Escape hatch: an `unsafe`-marked variant or a stdlib
  `a.swapAt(i, j)` that does the check dynamically — recommend the stdlib
  method, no language feature.

### B. Swift's hybrid: static where provable, dynamic checks elsewhere
Per-value "being accessed" flag checked at runtime when static analysis is
inconclusive.
- **Pro:** accepts more programs (dynamic-index case works, panics only on
  actual aliasing).
- **Con:** runtime cost + a runtime machinery Saw otherwise doesn't need;
  in Saw the "inconclusive" set is *only* dynamic indexing on the same root —
  buying a whole enforcement regime for one case A handles with a stdlib
  method. Swift needed this because of classes/globals/escaping closures;
  Saw deliberately has none of those aliasing sources.

### C. Specify aliasing as permitted (defined interleaving, no UB claim)
Document that `&var` args may alias and mutations are visible through both.
- **Pro:** no checks, no rejections.
- **Con:** surrenders the memory-safety claim precisely where it was
  advertised; future Vector/String invalidate-on-realloc makes aliasing
  *actually* unsafe (dangling interior pointers), so this option gets worse
  as the stdlib matures. Not really on the table; listed for completeness.

## Interaction warning (spec-level invariant to write down)

Option A's soundness rests on the no-escape property. Three future features
would break the closed world and silently convert A from "sound" to "wishful":
1. closures capturing by reference (today: by value — keep it that way, or
   require such closures to be non-escaping and include their captures in the
   call-site disjointness check);
2. returning references / reference fields in structs (don't);
3. global mutable variables accessible from callees (today none exist —
   if added, a callee could reach `x` while holding `&var x`; either forbid
   passing globals by reference or forbid callee global access — decide when
   globals are proposed, but record the constraint NOW in the spec).

## Recommendation

**A**, written into the spec as: the exclusivity theorem (why it's fully
static in Saw), the disjointness rule, the dynamic-index conservatism +
`swapAt`-style stdlib escape, and the three invariant-preserving constraints
above. Implementation: one typechecker brief (call-site path-disjointness
check), a set of error tests (`swap(&x,&x)`, `f(&p,&p.x)`, forwarding case),
and positive tests for disjoint fields (`f(&p.x, &p.y)` must be ACCEPTED —
the rule is path-disjointness, not one-ref-per-root).
