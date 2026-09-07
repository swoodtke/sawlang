---
{"assignee":"","author":"agent:codex-todo-import","body_bytes":4200,"created":"1788791148","id":"SL-4","labels":["todo-import","backlog","design","plan","design-proposal"],"priority":"normal","project":"SL","revision":1,"sequence":4,"status":"open","title":"DF-307b: Design one aggregate layout oracle for all const positions","updated":"1788791148"}
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

