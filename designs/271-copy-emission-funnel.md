# Design 271 — one copy-emission funnel

**Status:** built (SL-265).
**Issue:** SL-265 — `Vector<T>.copy()` bitwise-duplicates an automatic-Copy-tier
struct element, losing every `String` retain.
**Findings filed on the way:** SL-269, SL-270, SL-271 (each independent of this
fix and unchanged by it).

## The defect as filed

`Vector<T: ExplicitCopy>.copy()` spells `result.push(buf[i].copy())`
(`sawc/std/vector.saw:493-509`), which is correct. At `T` = a struct on the
AUTOMATIC Copy tier — design 159's tier, a struct or enum whose members are all
trivial/Copy, declaring nothing and owing nothing — that per-element `.copy()`
lowered to a bare load. The duplicate's `String` fields aliased the original's,
so the original's drop freed storage the duplicate still held: reads returned
empty and the second release aborted with `over-release of a String reference
(refcount underflow)`, exit 134, from fully safe code with no `unsafe` anywhere.

The filed repro runs correctly now and prints exactly what the issue predicts.
It is row V100.

## Root cause: three chains, one rule

The bound is not the problem and member resolution is not the problem. Design
219 is explicit that every `Copy` type satisfies `T: ExplicitCopy`, so
`Vector`'s bound is RIGHT to admit the tier, the call site discharged it against
the concrete argument, and design 218c's `_mono_copy_is_a_retain` skip is right
to let the substituted clone keep the spelling its template wrote. Its docstring
even states the contract this brief had to make true — "codegen lowers the
element copy BY TIER".

Codegen did not. "Duplicate this value at its tier" is a rule quantified over
every position a duplicate is emitted, and it had been written out THREE times:

| chain | where | arms it had | arms it lacked |
|---|---|---|---|
| `_generate_copy` | `resources.py` | array, tuple, escaping closure, real `copy` symbol, **design-159 aggregate**, bitwise | (complete) |
| `_emit_copy_value` | `resources.py` | array, tuple, optional, trivial, real symbol, **design-159 aggregate**, bitwise | escaping closure |
| `.copy()` interception | `calls.py` | array, optional, tuple, DECLARED-tier enum, escaping closure, real symbol | **design-159 aggregate** — and the automatic tier answers no "declares a policy" test, so it fell out of the chain's last line as `return obj_val` |
| derived memberwise `copy()` | `methods.py` | DECLARED-tier enum, optional, conformance-declared field type | **design-159 aggregate, ARRAY fields, TUPLE fields, closure fields** |

Two of the four were miscompiling. The shared ingredient in every gap is the
same confusion: a test for a DECLARED conformance standing in for a question
about a DERIVED tier. The automatic tier is exactly the tier that declares
nothing, so every such test is blind to it by construction.

This is obligation 1's failure mode with the symptom attached. The fix is
obligation 1's remedy: ONE chokepoint whose docstring names its entry points.

## The fix

`_emit_copy_value` (`sawc/codegen/resources.py`) becomes THE funnel. It gains
the escaping-closure arm it lacked, its docstring names all five entry points
and gives the arm order with reasons, and the other three sites delegate:

- `_generate_copy` keeps only its monomorphization substitution, then calls the
  funnel. Its arm list was the same list maintained separately, which is the
  shape that drifts.
- `calls.py`'s `.copy()` interception keeps only its two refusals and calls the
  funnel. The NoCopy refusal is re-keyed from a conformance-name test to
  `copy_tier(...) == 'nocopy'`, which is the accurate predicate — the old one
  also caught every DECLARED-`ExplicitCopy` ENUM, the one shape that
  legitimately has no emitted symbol.
- `methods.py`'s `_generate_derived_copy_body` keeps only its
  declared-policy-STRUCT branch (that resolution fills declared default type
  arguments, which plain mangling does not — DF-128c) and calls the funnel for
  every other field.

ARM ORDER is load-bearing and is pinned by row V103: the real `copy` symbol is
asked for BEFORE the trivially-copyable test, so a POD receiver whose author
wrote a hook still runs that hook.

Nothing in the typechecker changed. No diagnostic changed. No language rule
changed — the automatic tier's copy has always been "retain each member"; this
is the codegen catching up at two of the four places that emit one.

## Obligation 4 — the class

The issue named `Vector.try_copy` and design 251's `Map`/`Set` conformances as
unverified siblings. The sweep went wider, because the mechanism is a
copy-EMISSION chain rather than anything about generics or about std.

Probed with heap strings (a string LITERAL is immortal and passes vacuously —
the issue's own gotcha, and the reason row V25 could never have caught this),
each pre-fix and post-fix:

| cell | pre-fix | post-fix |
|---|---|---|
| `Vector<Rec>.copy()`, `Rec` auto-tier struct | empty reads, SIGABRT 134 | correct |
| `Vector<Tag>.copy()`, `Tag` auto-tier ENUM | payload corrupted | correct |
| `Vector<Rec>.try_copy()` | empty read, exit 133 | correct |
| `Map<String, Rec>.copy()` | value's text aliased the KEY's buffer, SIGABRT 134 | correct |
| `Map<String, Rec>.try_copy()` | same | correct |
| user generic `dup<T: ExplicitCopy>` at `Rec` | corrupt | correct |
| `@synthesize` copy, auto-tier STRUCT field | empty read, exit 133 | correct |
| `@synthesize` copy, auto-tier ENUM field | corrupt | correct |
| `@synthesize` copy, `[String; 2]` field | SIGABRT | correct |
| `@synthesize` copy, `(String, Int)` field | bitwise in IR | correct |
| `Vector<Rec?>` / `Vector<(Rec, Int)>` / `Vector<[Rec; 2]>` | already correct | unchanged |
| `Vector<String>`, `Vector<declared ExplicitCopy>` | already correct | unchanged |

The two that widened the finding past its filing are the `@synthesize` rows:
one `@synthesize` line and a struct literal reproduce it, with no bound, no type
parameter and no `Vector` in the program. "A generic bug" was the wrong reading
throughout.

Two cells could NOT be probed, and both are recorded rather than worked around:

- `Set<Rec>` and `Map<Rec, Int>` are refused at the instantiation, the element
  and key gates calling the automatic tier "move-only, not retainable" while the
  `Map` VALUE gate accepts it. **SL-270** — the same DECLARED-vs-DERIVED
  confusion in a third kind of predicate, which is why it is filed with a sweep
  note rather than as a one-off.
- A DIRECT `Vector<closure>` element is unusable as a refcount oracle: the
  vector never releases its element's env, and a by-value capture does not
  survive the frame that built the closure. Both reproduce with NO copy anywhere
  in the program and are identical pre-fix and post-fix, so both are
  drop/capture lowering. **SL-269.** The closure arm is counted through a STRUCT
  member instead, where the glue does release and the count moves.

## Obligation 3 — conformance rows, written first

- **V100** — a `T: ExplicitCopy`-bounded `copy()` duplicates an automatic
  Copy-tier element at its own tier. Struct and enum, heap strings, plus a
  COUNTING oracle: the element owns an escaping closure whose env holds an `Arc`
  reference, so a missing retain drops the count early (pre-fix it reads 1) and
  a doubled one never drops it.
- **V101** — the whole bounded-generic family carries the tier:
  `Vector.try_copy`, `Map.copy`, `Map.try_copy`, and a user-level generic.
- **V102** — a `@synthesize`d memberwise `copy()` duplicates EVERY field at its
  own tier: auto-tier struct field, auto-tier enum field, array field, tuple
  field.
- **V103** — control, the double-retain guard: a hand-written `copy()` hook
  counts duplications directly and pins the arm order; a declared-tier enum
  element and an `ExplicitCopy` element keep independent buffers.

V100–V102 FAIL on the pre-fix compiler (133/134 or corrupted output) and pass
after, so each is a real regression test rather than a restatement.

**Row V25 is noted, not changed.** It is the tier's other behavioural row and
its oracle is a string literal, so it passes with or without the retain. The new
rows use heap strings for exactly that reason.

## Workaround removed

`prototypes/minivm/src/frontend.saw` cloned the token stream element by element
through its own `clone_token` with a comment citing SL-265. That is now
`tokens = r.tokens.copy()`, and minivm's 346-case differential harness passes —
end-to-end validation on the code that reported the bug. `clone_token` keeps its
two other callers.

## Gates

Per-commit: full suite 2486 passed / 10 xfailed, freestanding 36 passed across
riscv32 + arm64. Terminal: the full battery.
