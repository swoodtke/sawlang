---
{"assignee":"","author":"agent:codex-todo-import","body_bytes":2382,"created":"1788791131","id":"SL-1","labels":["todo-import","queued","design","plan","design-proposal"],"priority":"normal","project":"SL","revision":1,"sequence":1,"status":"open","title":"Design 245: implement the ruled Scalar v1 surface","updated":"1788791131"}
---


## Description

## Scope and status

Design 245: implement the ruled Scalar v1 surface

Imported from repository TODO records on 2026-09-07. The reporter/version, evidence, workarounds and prior rulings are preserved in the source context below. This import is not a fresh reproduction or approval of a proposed design.

Scheduling: retain the source’s queue order and prerequisites; seed/scoping tasks do not authorize implementation.

## Proposed plan

1. Reconcile the linked brief and recorded rulings with current consumers. Keep already-landed behavior and stated deferrals explicit.
2. Draft the remaining contract: supported syntax/API, ownership and failure behavior, alternatives, compatibility effects and the exact questions still requiring a decision.
3. Define small implementation units and consumer migrations, then specify the positive, negative and boundary tests before dispatch.

## Acceptance criteria

- [ ] The design names a concrete consumer or retains its recorded revisit trigger.
- [ ] Existing rulings are preserved; unresolved choices and a recommended option are explicit.
- [ ] The proposed API/semantics, migration scope and acceptance tests are reviewable. Drafting this plan does not mark an unruled design approved.

## Existing design references

- [sawlang/designs/238-sawos-split.md](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/238-sawos-split.md)
- [sawlang/designs/245-unicode-scalar-type.md](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/245-unicode-scalar-type.md)

## Source context

Historical closed subcases are context, not new work. Legacy DF/SL/SO numbers use a nonbreaking hyphen here to avoid accidental tracker links; the linked source retains the original spelling.

### sawlang TODO lines 36–36

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L36-L36)

- Design 245 v1 — `Scalar` + `scalars()`, `chars()` and `append_scalar` REMOVED (designs/245-unicode-scalar-type.md §6; ruled Aug 27 — no literals in v1, prelude placement). The Aug-27 dispatch NEVER LANDED and is presumed STALE (no Scalar in the tree, Aug-28 check); RESCHEDULED AFTER design 238 (user, Aug 28: sos does not depend on string/character work). Re-dispatch then. Literals + patterns stay open as later units


## Comments

