---
{"acceptance":[],"assignee":"","author":"agent:codex-todo-import","body_bytes":4200,"closed":"1790349802","created":"1788791148","id":"SL-4","labels":["superseded"],"order":0,"parent":"","priority":"normal","project":"SL","queue_order":0,"revision":5,"sequence":2502,"stage":"backlog","status":"closed","title":"DF-307b: Design one aggregate layout oracle for all const positions","updated":"1790349810"}
---


## Description

## Scope and status

DF-307b: Design one aggregate layout oracle for all const positions

Imported from repository TODO records on 2026-09-07. The reporter/version, evidence, workarounds and prior rulings are preserved in the source context below. This import is not a fresh reproduction or approval of a proposed design.

Scheduling: backlog; no new implementation order is assigned by this import.

## Proposed plan

1. Reconcile the linked brief and recorded rulings with current consumers. Keep already-landed behavior and stated deferrals explicit.
2. Draft the remaining contract: supported syntax/API, ownership and failure behavior, alternatives, compatibility effects and the exact questions still requiring a decision.
3. Define small implementation units and consumer migrations, then specify the positive, negative and boundary tests before dispatch.

## Acceptance criteria

- [ ] The design names a concrete consumer or retains its recorded revisit trigger.
- [ ] Existing rulings are preserved; unresolved choices and a recommended option are explicit.
- [ ] The proposed API/semantics, migration scope and acceptance tests are reviewable. Drafting this plan does not mark an unruled design approved.

## Source context

Historical closed subcases are context, not new work. Legacy DF/SL/SO numbers use a nonbreaking hyphen here to avoid accidental tracker links; the linked source retains the original spelling.

### sawlang TODO lines 43–43

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L43-L43)

- DF‑307b — `sizeof<Struct>()` folds in a `static_assert` and refuses at the five earlier const positions, because a struct's ABI layout is built during code generation and the front end declines rather than computing a second opinion (entry below, filed Sep 5 by DF‑307a as its own documented boundary; NOT a defect). Costs the wire-struct idiom one restated length; nobody has asked for it. The fix shape is all-or-nothing — a partial one reintroduces the by-position divergence DF‑307a removed

### sawlang TODO lines 342–373

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L342-L373)

## DF‑307b — the front end's layout oracle answers for SCALAR kinds only, so
## `sizeof<Struct>()` still refuses outside a `static_assert` (filed Sep 5 by
## DF‑307a as its own documented boundary; NOT a defect — a deliberate v1 line)

`sizeof<Region>()` folds in a `static_assert` (codegen has the ABI layout) and
is refused at an array length, a repeat count, a `static` initializer, an
`@align` and a const generic argument, by name:

    array length is not a compile-time constant: `sizeof<Region>()`, whose
    layout only code generation knows, is not allowed here

MECHANISM: a struct's layout is built during code generation, later than an
array length is resolved, and `TypeChecker._const_type_metric` refuses rather
than computing a second opinion the backend would then override. That refusal
is the RIGHT default — a wrong size is the one answer nothing downstream could
catch, and it would break the bounds checks conformance rows T10/T14 claim.

WHY IT IS FILED ANYWAY: the wire-struct idiom pins layout with
`static_assert(sizeof<T>() == N)` and then writes N again as a buffer length,
which is the derive-don't-restate duplication DF‑300c existed to remove, one
level up. sos has not asked for it; nothing in the corpus wants it.

FIX SHAPE, if it is ever wanted: NOT a second layout computation. Either (a)
give the front end the real one by building the LLVM type through a mapping
codegen shares — which is the whole `_get_llvm_type` recursion, monomorphization
included, and is why this was not done here; or (b) DEFER the fold, which works
for a `static` initializer (the typechecker needs only a boolean there and
codegen already re-folds with the metric) and does NOT work for an array length,
whose integer is needed at typecheck for type identity and mangling. A partial
(b) would reintroduce exactly the by-position divergence DF‑307a removed, so a
fix is (a) or nothing. [186, DF‑300c, DF‑307a]


## Comments

<!-- sawtracker:comment {"author":"agent:claude-sawlang","body_bytes":412,"created":"1790349802","id":"c1","kind":"landing"} -->
Closed: settled by the user's constexpr ruling (Sep 25; SL:architecture §3.10 r39). The one layout oracle for every constant position is the target-description module that the MIR interpreter and every backend query. sizeof of a struct is legal in constant positions, with layout computed on demand, and one acyclic dependency graph over layouts and constants, so a self-referential size is a clean cycle error.

<!-- sawtracker:comment {"author":"agent:claude-air-sawlang","body_bytes":722,"created":"1790349810","id":"c2"} -->
SL:architecture r39 (user ruling, Sep 25) says this issue is settled. `sizeof` of a struct is legal in constant positions, and the layout oracle is the target-description module (§3.10), with one acyclic graph over layouts and constants. So SL-4 can close with a pointer to that section.

Two LANGUAGE_SPEC passages the ruling overturns need a tracked home, probably SL-393's list of spec corrections:
- design 185's "the fold happens in the signed platform `Int` domain" (and DF-283c's consequences), now ordinary typed arithmetic;
- the refusal of `sizeof<Region>()` in an array length ("array length is not a compile-time constant"), now legal.

The corpus pins of both refusals become "language changed" annotations.


