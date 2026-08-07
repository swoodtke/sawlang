# Design 171 — places get field syntax; Box/Arc payload access becomes a place

**Status: SHAPE APPROVED (user, Aug 7 conversation) with a hard pin: UNIT 0's
PROBES GATE THE FULL IMPLEMENTATION — units 1-4 proceed only on a green probe
report; any red probe (the existential lend above all) STOPS the brief and
returns to the user with options. QUEUE: after 165 integrates (Arc internals +
`with_unique` are in flight there); NOT concurrent with 170 (shared
typechecker surface). Rewrite-track motivation: every bespoke mechanism
deleted here is one the self-hosted typechecker never ports.**

## The idea (two halves, one rule)

1. **"No parens = place."** A ZERO-ARG `borrows` accessor is a virtual field —
   it projects storage, it does not compute a value — and fields and lends
   already behave identically at use sites (both are places: same windows,
   same root charging, same copy-tier reads). Make them LOOK identical:
   `b.value.push(x)`, `b.value = v`, `let v = b.value`. Parens stay mandatory
   for value-returning methods (`s.len()`); general computed properties are an
   explicit NON-GOAL (arbitrary compute/allocation behind field syntax is what
   no-hidden-alloc exists to prevent). The syntax then carries an invariant:
   no parens = storage you can write through and borrow; parens = a call.
2. **Box/Arc payload access rides it, and the design-133 forwarding dies.**
   `arc_forward`/`box_forward` (typechecker attributes + `codegen/calls.py`
   1059-1883 paths) predate places; they special-case what `borrows` now does
   generically. Box declares `borrows value(&self) -> T` (shared + exclusive —
   unique ownership makes both sound); Arc's SHARED lend is unconditional,
   and its EXCLUSIVE lend is the uniqueness-gated CONDITIONAL lend
   (`borrows -> T?`, Some only when `strong_count() == 1`) — 165's
   `with_unique` re-expressed as a place.

## Unit 0 — THE PROBE GATE (report first, then go/no-go)

Probes under `.build/scratch/`, results appended to this brief as findings:

- **Forwarding census:** every call site in tree that resolves via
  arc/box forwarding; split concrete-payload vs `any Trait` payload; count
  what unit 3's sweep must touch.
- **The existential lend** (the likely blocker): can a `borrows` window lend a
  `Box<any Trait>` payload and dispatch a trait method inside it
  (`err.value.describe()`)? Design 110 excluded `&var any Trait` from
  whole-referent replacement — probe whether the place path shares that
  limitation for reads AND writes.
- **Conditional lend + `?.`:** `arc.unique_value?.push(x)` — do optional
  chaining and window machinery compose (one short-circuit skips the window,
  epilogue runs on the taken path only)?
- **Whole-referent replacement (110)** through the place: `b.value = v`
  payload-swap parity with today's Box behavior.
- **Suspension:** a place window held across a suspend point in a coroutine
  (references span suspends per 88/106 — verify the window's prologue/epilogue
  pair survives the frame transform).

**Gate rule: any red → STOP, report options (e.g. keep forwarding for
existential payloads only; extend places; defer), user decides. All green →
units 1-4 proceed.**

## Units 1-4 (on green probes)

1. **Paren-less place syntax.** Member-style access resolves: stored field →
   zero-arg `borrows` accessor (one namespace, no collision). SINGLE SPELLING:
   call-syntax on a zero-arg borrows accessor becomes an error with a fixit
   (drop the parens) — two spellings invite drift; migration is small (borrows
   is a 141/146-era surface). Accessors WITH args keep their spelling
   (`m[k]`, explicit calls).
2. **Box/Arc accessors** per the shapes above. Arc exclusive-spelling
   decision [user, when 165 has landed]: the place (`unique_value`) vs 165's
   closure (`with_unique`) vs both — recommend the place as primary with
   `with_unique` retired IF the probe shows full parity, else both with the
   closure documented as the composition-safe form.
3. **Migration + deletion.** Sweep forwarded call sites to the `.value`
   spelling; DELETE the forwarding machinery (typechecker resolution halves +
   both codegen paths) — minus whatever unit 0 proved must stay, stated
   explicitly in the commit. Compile-speed note: deleting a resolution path
   also removes its cost from every method lookup.
4. **Docs** (design 125 convention): spec places section + Box/Arc pages, the
   saw-lang skill (the no-parens rule is a headline idiom), README. Tracker:
   DF-171x findings, the census numbers, close what this obsoletes.

## Gates

Unit 0's report is its own deliverable (no tree changes beyond probes). Units
1-4: per-unit commits, full battery each (suite zero xfails, lexdiff, astdiff,
irdet --all, bootstrap, gmgate, sos_runner) via the venv interpreter.

## Explicitly out

General computed properties; paren-less for value-returning methods; property
setters distinct from place writes; `Deref`-style auto-coercion chains
(`b.method()` never resolves through the payload again — that is the point).
