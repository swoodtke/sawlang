# Design 216 — lifting `T: Copy` off the Vector closure and sort APIs

**Status: PROPOSAL, not scheduled, no units authored.** Every claim below is
probe-verified against the current tree; the probes are named per section and
live in `.build/scratch/` until they become tests.

## The finding

Five `Vector` methods carry a `T: Copy` bound their algorithms do not need:
`map`, `each`, `each_indexed`, `fold` and `sort`. The bound is real for
`iter`/`enumerated` and inherited by everything sharing their extension block —
the code says so itself, above `iter()`:

```
// `T: Copy` — the SAME bound `each`/`map`/`enumerated` carry, and for the
```

The consequence is that a `Vector` of move-only elements — a `Vector<File>`, a
`Vector<Job>` where `Job` owns a handle — cannot be mapped, iterated with a
closure, folded or sorted at all. That is a large hole in the collection API,
and it is not one the ownership model requires.

## Where the bound actually comes from

**For the closure methods, the SIGNATURE, not the body.** `map` is declared
`transform: (T) -> U`, taking the element BY VALUE, so its body reads the
element out of the vector:

```saw
if let elem = self.get(i) {
    result.push(transform(move elem))
}
```

A value read out of a place consults the copy tier, which is what demands
`T: Copy`. Nothing else in `map` needs it.

**For `sort`, one helper.** `sort` itself only calls `swap` — which lives in the
UNBOUNDED extension and moves bytes without duplicating — and `_greater_at`,
which reads both operands out by value:

```saw
func _greater_at(&self, i: Int, j: Int) -> Bool {
    if let a = self.get(i) {
        if let b = self.get(j) { return a > b }
```

So the movement half of sorting was never the problem. The comparison half is.

## What the probes establish

1. **A by-reference `map` works over NoCopy elements** (`map_ref_probe.saw`).
   Written from OUTSIDE std over the public `with_ref`, so it needs no compiler
   change and no new internals. The vector still owns its elements afterwards.

2. **The transform need not be `sync`** (`refclosure_probe.saw`). A closure
   parameter `(&T) -> U` typechecks unmarked and its body may suspend — a
   transform calling `yield_now()` runs correctly. So switching to `&T` does NOT
   trade away suspending transforms. The `sync` on `with_ref` is that method's
   own scoped-window constraint, not a language limit on reference-taking
   closures.

3. **NoCopy elements APPEAR to compare through borrows — via a compiler hole**
   (`sort_cmp_probe.saw`, `sort_cmp_sound.saw`, then `cmp_consume_probe.saw`).
   `a > b` on two `&T` bindings compiles and runs, and 200 repeats leave
   elements holding a refcounted `String` intact. That looked like a capability.
   It is not: see DF-216b. The operator bypasses the transfer checkpoint that
   the identical direct call `a.compare(b)` correctly refuses, and the bypass is
   unsound. **The `sort` half of this proposal cannot rest on it.**

4. **A NoCopy `Vector` sorts end to end** (`sort_nocopy.saw`) using only `swap`
   and borrowed comparison — the same insertion sort std already has, with the
   by-value reads replaced. Five `Job` elements, correct order out, no `Copy`
   anywhere. Correct as written, but it is standing on DF-216b: it compiles only
   because the operator skips the check, and a `Comparable` conformance that
   moved its `other` would corrupt the vector under it.

## Proposal

- Move `map`, `each`, `each_indexed` and `fold`'s element parameter to the
  unbounded extension, with `&T` element closures.
- Rewrite `_greater_at` to compare through borrows and drop `Copy` from `sort`'s
  extension, leaving `T: Comparable` — **but only after DF-216b is fixed.**
  Today that rewrite compiles for the wrong reason, and shipping it would build
  std on top of the hole. `Comparable`/`Equatable` taking `other: &Self` is the
  fix that makes it legitimate, and it is a prerequisite rather than a
  follow-up.
- `iter`, `enumerated` and `VectorIterator` KEEP `T: Copy`: `Iterator.next()`
  yields an element the consumer owns, which is a real constraint (design 122),
  not an inherited one.

## DF-216a — ICE: a closure naming `self` inside a method — **LANDED**

**Status: FIXED**, unit 1 (with DF-216d and DF-169f). The ruling and what the
probes forced are in *The DF-216a ruling* below; the original report follows.

Found while writing the borrow-based comparison, and it blocks the natural
spelling of it.

```saw
extension Counter {
    func viaFree(&self) -> Int {
        call({ v in self.n + v })
    }
}
// internal compiler error at N:C (SelfExpr): 'self' not found in current scope
```

Twenty-line repro (`ice_self_closure.saw`, `ice_self_variants.saw`). ANY closure
whose body names `self`, inside any method, fails this way. NOT specific to the
closure being an argument to a method on `self` — handing it to a free function
fails identically, so the trigger is the identifier, not the receiver.

Two workarounds, both verified (`ice_workaround.saw`, `self_param_probe.saw`):
hoist `self.field` into a local before the closure, or hand `&self` to the
closure as an explicit parameter (`body: (&Counter, Int) sync -> R` called as
`self.run({ c, v in c.n + v })`). The second is what makes a std-side
`_greater_at` rewrite expressible.

A corpus grep found ZERO closures naming `self` anywhere in std, which is why
this has gone unseen. It is an ICE, so by the design-192 fuzzing oracle it is a
finding on its own terms regardless of this brief.

## The DF-216a ruling (Aug 13 — unit 1 landed)

The fix had to decide what `self` capture MEANS, and the brief's instruction was
that it must mean whatever reference-PARAMETER capture already means, since a
receiver is a reference. Both halves were probed before a line was written.

| Probe | Shape | Verdict |
|---|---|---|
| R1 | `apply({ v in r.x + v })`, `r: &Thing` — direct call argument | COMPILES, runs, correct value |
| R2 | `let g = { r.x + 1 }`, called in-frame | COMPILES (heap env) |
| R3 | `return { r.x + 1 }` out of a function | COMPILES |
| R4/R5 | R3's closure called after the referent's frame died | COMPILES, reads the dead frame |

So the diagnostic the brief expected ("references cannot escape") **did not
exist at this site**, though LANGUAGE_SPEC has always claimed it. R3's `make`
emits `store ptr %r` into a HEAP environment — a raw pointer into a frame that
dies, out of fully safe code, silently. Filed as **DF-216d**.

That ruled out reading the instruction literally in either direction: giving
`self` "the same diagnostic ref params get" would have shipped a second way to
spell a dangling pointer, and refusing only `self` would have been a third
behavior. The landing makes the rule ONE PREDICATE over its three spellings
instead, which is the funnel obligation 1 asks for:

> **A capture that lowers to a pointer into the enclosing frame is legal only in
> a closure passed directly to a non-escaping parameter.**
>
> 1. an explicit `[&x]` / `[&var x]` borrow capture — already checked, at its
>    spec;
> 2. `self` in a method — implicitly `ref` for `&self`, `ref_var` for
>    `&var self`. A CONSUMING `self` receiver is an owned binding and stays a
>    plain value capture;
> 3. a REFERENCE-TYPED binding (a `&T`/`&var T` parameter), whose plain capture
>    copies the pointer itself into the env. This is the spelling that bypassed
>    the rule entirely.

`self` is therefore a BORROW capture, never a value one. A value capture would
have been wrong twice: it would snapshot the receiver, and it would demand of
`self` a copy policy no receiver ever owed (a NoCopy receiver refused outright).
As a borrow it needed NO codegen change — the env-of-reference lowering that
already serves `[&x]` binds the name to the enclosing frame's storage, which is
exactly what `_generate_self_expr` and the `self`-rooted member/method paths
read.

**Consumer sweep (obligation 2), owed because spelling 3 flips a contract:**
zero consumers across 1938 tracked `.saw` files. No closure in std, blade, libs,
sos, devtools or examples captures a reference parameter or `self` —
self-capture was mechanically impossible, and escaping ref-param capture had no
authors. `spawn` routes through the same funnel and fires this beside the
pre-existing `not Send` error, so it is not a second entry point.

**DF-169f fell out with it, and corrects the sweep's "not a class" verdict.**
Its pin `place_write_self_rhs` went XPASS: place lowering hoists a place write's
RHS into the window's closure, so a COMPILER-SYNTHESIZED closure was reaching
the same missing `SelfExpr` case. The sweep had enumerated the source spellings
that reach the funnel and found no siblings; it had not enumerated the funnel's
own CALLERS, where the sibling was. That is the obligation-4 refinement this
landing earned.

**Left open, deliberately — DF-216e.** `borrow_ok`'s `as_call_argument`
heuristic cannot tell "the callee RUNS this closure" from "the callee STORES
it", so a borrow capture handed to `Vector.push` is still classified
non-escaping and still compiles a stack-env pointer that dangles (IR-confirmed,
found by the consumer sweep). It predates this landing and reaches all three
spellings equally. Closing it needs a non-escaping parameter TYPE, which is
design 21's already-named future work, so it is its own brief rather than
something to invent here.

Conformance rows: R35 (spelling 3 — a DEVIATION until now), R36 (`self`
escaping), R37 (`self` non-escaping, the acceptance beside R30).

## DF-216b — SOUNDNESS: the comparison operators bypass the transfer checkpoint

The sharp one, and it is independent of everything above.

`Comparable.compare(&self, other: Self)` and `Equatable.equals(&self, other: Self)`
take the second operand BY VALUE. On a NoCopy type the two spellings of the same
call disagree:

```saw
a.compare(b)    // correctly refused: "cannot copy value of type `Tag`
                //   which implements NoCopy"; hint: use `move`
a > b           // COMPILES — same call, same operands
```

The operator path then passes `other` by REFERENCE: ten comparisons of a
two-element vector produce exactly two deinits, so nothing is being consumed
(`cmp_consume_probe.saw`). That is why it looked harmless.

It is not harmless, because the signature entitles the callee to own what it was
given. A conformance that exercises that right corrupts the caller
(`cmp_move_probe.saw`):

```saw
func compare(&self, other: Tag) -> Ordering {
    let taken = move other      // legal for a by-value parameter
    ...
}
```

Three comparisons of a two-element vector, and the run prints FIVE deinits —
three during the comparisons, two at teardown. The same element is destroyed
four times, from fully safe code with no `unsafe` at the call site. With a
refcounted or heap-owning field that is a use-after-free. It is the DF-132a
shape (`Vector.get`'s own regression note) reappearing at the operator lowering.

Two things are wrong and they want fixing together:

1. **The check is missing on the operator path.** Whatever `a.compare(b)` runs
   through, `a > b` does not. That is a funnel problem in design 190
   obligation 1's terms: one rule, two entry points, and the second bypasses it.
2. **The signature is wrong.** `other: Self` claims ownership the lowering never
   transfers. `other: &Self` on `Comparable` and `Equatable` would make the
   declaration describe what actually happens, legitimise NoCopy comparison, and
   remove the callee's ability to move the operand — closing the hole by
   construction rather than by adding a check.

Fixing only (1) would make `a > b` a clean error on NoCopy types and leave them
uncomparable. Fixing (2) is what the collection API wants. It changes a core
trait signature and every conformer with it, so it is its own brief; this one
records the evidence and the dependency.

**Status: (1) is LANDED as the stopgap** (see "The stopgap" under Class sweeps
below) — and it is narrower than "leaves them uncomparable": only a comparison
reaching a HAND-WRITTEN body is refused, so a `@synthesize`d NoCopy type keeps
every operator. **(2) is still owed**, and now carries two dependencies rather
than one: the `sort` half of this brief, and matrix row 7 (the operators inside
a generic body), which the stopgap's chokepoint cannot see.

## Class sweeps (Aug 13 — obligation 4, run before any dispatch)

Two probe-backed sweeps, agent-run, every verdict from a real compile/run.
Probes live in `.build/scratch/sweep216a/` and `sweep216b/` (gitignored).

### DF-216b IS a class: seven unsound positions, one mechanism

Every position that desugars to `equals`/`compare` through the operator path is
unsound — probed with a NoCopy conformance whose body does `move other`, deinit
counts proving the double-release:

| Position | Verdict |
|---|---|
| `a > b` / `<` / `>=` / `<=` | UNSOUND (the found instance; 5 deinits / 2 values) |
| `a == b` / `a != b` | UNSOUND (8 / 2) |
| `==` in a match-arm guard | UNSOUND (ordinary expression `==`) |
| `@synthesize` memberwise body reaching a NoCopy member's hand-written conformance | UNSOUND (8 / 2) |
| enum payload deep-equality | UNSOUND (5 / 2) |
| tuple equality over a user-Equatable element | UNSOUND (5 / 2) |
| `==` / `>` in a generic body under `T: Equatable`/`T: Comparable` | UNSOUND (8 / 2) |

Sound positions are each sound for their OWN independent reason, not because
the checkpoint catches them: the direct call `a.equals(b)` (clean refusal — the
original contrast), Map/Set keys (design 65's key-must-be-copyable gate; an
ExplicitCopy key with a moving `equals` probed sound through insert/lookup),
existentials (`any Equatable` already refused — by-value `Self` is not
object-safe), and Printable/Hashable/Deinit/Iterator (no by-value `Self`
operand exists in their signatures). Match literal/range patterns cannot reach
user types (Int/Bool/String scrutinees only).

The mechanism: `_check_binary_op` (typechecker/expressions.py:1629-1704) never
constructs a call node — it returns `Bool` directly — and codegen's
`_emit_equals`/`_emit_compare` (codegen/operators.py:480-520, 755-769) call the
user's method with two already-loaded values, so `_check_value_transfer`
(types.py:3102) never sees the right operand. Every recursive emitter
(memberwise, enum payload, tuple, optional/array) reduces to that same pair,
which is why the whole matrix falls together. The OTHER synthesized-call family
(coro_transform, place rewrites) builds real AST call nodes that re-enter the
ordinary checker and routes through the checkpoint correctly.

Funnel verdict: the one chokepoint seeing every comparison operator is
`_check_binary_op`'s Equatable/Comparable gating (expressions.py:1659, 1686) —
a stopgap check there makes NoCopy comparison a clean error at every position
at once. The `other: &Self` signature change remains the real fix: it closes
the entire matrix by construction, including the recursive codegen paths.

### The stopgap: LANDED (units 1-2), six of seven positions

The refusal fires where BOTH hold: the operand's copy tier is ExplicitCopy or
NoCopy (a checked call site could not have passed it by value without
`move`/`.copy()`), and the comparison TRANSITIVELY reaches a hand-written
`equals`/`compare` — the operand's own, or one reached through a member, enum
payload, tuple element, optional payload or array element that a synthesized
comparison recurses into. A fully synthesized tree stays legal, because a
synthesized body never consumes its operand; that is what keeps `@synthesize`d
NoCopy types comparable instead of making move-only comparison impossible.
One helper (`_consuming_comparison_conformer`) holds the rule and its docstring
names its single entry point; the synthesized-vs-hand-written question is
answered from the registered method's `is_derived_equals`/`is_derived_compare`
AST flag (an enum's derived body mints no method symbol at all, which reads the
same way). Conformance rows C01-C11.

**The matrix claim above was wrong on one row, and the correction is the
stopgap's real boundary.** Tracing every probe through the chokepoint: rows 1-6
(`>`-family, `==`/`!=`, match guards, `@synthesize` memberwise, enum payload,
tuple) deliver the CONCRETE operand type there at tier `nocopy`, and all six
close. Row 7 (a generic body under `T: Equatable`/`T: Comparable`) delivers only
`T` at tier `abstract` — a generic body is checked ONCE with `T` abstract and is
NOT re-checked per instantiation (probed independently: `func passthrough<T>(x:
T) -> T { let y = x  move y }` compiles when instantiated at a NoCopy type), so
the concrete conformer never reaches `_check_binary_op` at all. Closing it means
judging the type ARGUMENT where the bound is discharged, and that is SIX
independent callers of `_bound_satisfied` (expressions.py:2865, 3838, 3851,
3868, 3910, 5947) rather than a funnel — six new check sites is what obligation
1 exists to refuse, and putting the rule inside `_bound_satisfied` itself would
also refuse `Map<Tag, V>` keys, which the sweep established are SOUND. So row 7
stays open, pinned as conformance row C07 (XFAIL citing DF-216b), and
`other: &Self` is what closes it.

**An EIGHTH position, and the stopgap does NOT cover it: an ImplicitCopy
operand.** The ruling's tier condition excludes ImplicitCopy on the stated
grounds that retain semantics make the borrow sound. Probed after the stopgap
landed, that premise is FALSE — the operator lowering adds no retain at ANY
tier, it just hands the callee two loaded values. An auto-ImplicitCopy `struct
Held { name: String }` whose hand-written `equals` does `move other` releases a
reference nobody took on every comparison; 200 of them and the process dies with
SIGTRAP (`.build/scratch/probe_implicitcopy_consuming2.saw`), while the
identical body READING `other` survives (`probe_implicitcopy_control.saw`) — the
difference is exactly the `move`. A first probe using string LITERALS showed
nothing, which is why the sweep's shapes missed it: a literal is immortal, so
the over-release is invisible until the String is heap-allocated. The class
sweep tested NoCopy operands throughout and never asked this question.

Widening the tier condition to `!= 'free'` would close it, but that is a
ruling, not a stopgap: it would refuse the operator on ordinary value types
(`struct Ticket { code: String }` with a hand-written `equals`), which is the
gratuitous breakage the ruling was written to avoid, and the honest alternative
— retain the operand at the lowering — is a codegen change in the emitters this
brief deliberately did not touch. Pinned as conformance row C12, which states
the GUARANTEE (a comparison does not destroy its operands) rather than any one
mechanism. `other: &Self` satisfies it at every tier at once, which is one more
argument for that brief being the real fix.

**Consumer sweep (obligation 2), run before the fix, ZERO tracked breakage.**
Across examples/, sawc/std/, sawc/builtin.saw, sawc/rt/, blade/, libs/, sos/,
devtools/ and tools/ there are exactly five hand-written `equals`/`compare`
bodies: `String` (std/string.saw:324, 347) and four example types (`Doc`,
`Reverse`, two `AK`s). Every one is on an ImplicitCopy or builtin-String type,
which condition (a) excludes. The only NoCopy types carrying an Equatable
conformance are three `Counted` fixtures (examples/map_nocopy_key_error.saw and
siblings), all `@synthesize`d — and independently refused earlier by design 65's
Map/Set key-copyability gate, so their `==` never type-checks. Std's generic
comparison sites (`map.saw:102`, the `vector.saw` sort family) are `Copy`-bounded
or key-gated and reach the chokepoint as abstract `K`/`T` regardless.

### DF-216a is NOT a class: one funnel, one missing case

Root cause located: `collect_names` (typechecker/expressions.py:10206-10308),
the single funnel `_analyze_closure_captures` walks closure bodies with, has an
`isinstance` arm for `Identifier` and ~twenty other node types but NONE for
`SelfExpr` — which falls to the structural walker, contributes nothing, so
`self` never enters `expr.captures`, and codegen's `_generate_self_expr`
(codegen/calls.py:2659-2665) raises the exact ICE string. Every other binding
kind probed green through the same funnel: params, locals, generic type params
(type position, `sizeof<T>`, call args, nested-closure param types), const
generics, `#file`/`#line`/`#function` (`#function` names the ENCLOSING
function), module globals, three-deep nested closures, captured-`var`
read/write/move, suspending bodies. The ICE reproduces in every context where
`self` is expressible — enum extension, generic method, trait default body,
hand-written deinit, and all three closure kinds (direct-arg, bound-then-
called, escaping) — confirming the brief's "any closure, any method" claim
row by row.

One second entry point for the fix to decide about: the explicit capture-list
grammar also rejects `self` at the PARSER (parser/expressions.py:1503 expects
an IDENT token; `self` is a keyword), so `{ [self] in ... }` is unwritable
today. **Decided: left as a parse error** (`Expected capture name`, re-probed
after unit 1). The implicit capture is the whole feature — nothing needs the
explicit spelling, and the mode `[self]` would ask for is the one the receiver
already dictates.

**This verdict was WRONG about siblings, and unit 1 says how** — see *The
DF-216a ruling* above. Every other SOURCE spelling probed green, but the funnel
has a second CALLER: the place transform's synthesized closure (DF-169f).

### DF-216c — found by the sweep, verified by hand, then REDRAWN by the
Aug-13 labeled-call sweep: generic METHOD calls are broken on EVERY spelling

First filed as "inference fails on labeled arguments"; the follow-up sweep
(`.build/scratch/sweep_labeled/RESULTS.md`) refuted the labeled framing —
positional `h.probe(99i64)` produces the BYTE-IDENTICAL inference error, and
explicit type arguments produce two further distinct wrong diagnostics
(`no parameter named other` labeled; `takes at most 0 argument(s)`
positional). The fault axis is METHOD-vs-FREE-FUNCTION: the method-side
inference path (expressions.py:8367-8440) is a second, independently written
caller of the label-mapping funnel (`_infer_label_mapping`/`_bind_args`,
expressions.py:2311-2700), defective as a whole — suspect the `off`-adjusted
parameter slice it feeds the funnel. Sharpest family member is **DF-217d**:
`func probe<U = Int>(other: U = 7)` on an extension, called `h.probe()`,
ICEs (`Type of #1 arg mismatch: i64 != %"Plain"`); the free twin is clean.
Sibling found by the same sweep: **DF-217e** — method DECLARATION
duplicate-signature checking ignores labels (label-only-distinguished method
overloads refused; free functions fine; contradicts LANGUAGE_SPEC.md:389).
Repros: `sweep216a/probe_dbg4.saw`, `probe_dbg5.saw`, `probe_ctl_free.saw`,
plus the `sweep_labeled/` probe set.

Unconfirmed lead (agent-reported, does NOT reproduce in the plain shape —
`probe_esc_return.saw` compiles and runs): contradictory diagnostics when
annotating an escaping-closure return type on an extension method. Needs
isolation before it becomes a finding.

## Open questions

- **Source compatibility of the `&T` switch.** `{ $0 * 2 }` and
  `{ $0.to_string() }` are unaffected: reading a reference binding yields the
  value, and method calls work through it. The sharp edge is forwarding — a
  closure passing its element to another `&T` parameter needs `&n`, not `n`
  (hit while writing `refclosure_probe.saw`). A corpus sweep is owed before the
  change, per obligation 2.
- **Borrow across suspension.** A non-`sync` transform lets a borrow into the
  vector's buffer span a suspend. Exclusivity should cover it — `map` holds
  `&self`, so no concurrent `&var self` — but that is a ruling, not something
  these probes establish.
- ~~**Does DF-216b reach further than the comparison operators?**~~ ANSWERED
  by the Aug-13 sweep (section above): seven unsound positions, one mechanism;
  no arithmetic operator traits exist, so comparison/equality is the whole
  operator surface. The matrix is the fix's test plan.
- **Sequencing.** The `map`/`each`/`fold` half stands alone and could land
  first; the `sort` half is blocked on the `&Self` change. Splitting them is
  probably right.
