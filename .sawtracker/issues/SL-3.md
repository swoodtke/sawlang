---
{"assignee":"","author":"agent:codex-todo-import","body_bytes":2445,"created":"1788791148","id":"SL-3","labels":["todo-import","backlog","design","plan","design-proposal"],"priority":"normal","project":"SL","revision":1,"sequence":3,"status":"open","title":"Index the existing both-ways generic suspension conformance test","updated":"1788791148"}
---


## Description

## Scope and status

Index the existing both-ways generic suspension conformance test

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

## Existing design references

- [sawlang/designs/191-conformance-suite.md](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/191-conformance-suite.md)
- [sawlang/designs/266-incremental-front-half.md](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/266-incremental-front-half.md)

## Source context

Historical closed subcases are context, not new work. Legacy DF/SL/SO numbers use a nonbreaking hyphen here to avoid accidental tracker links; the linked source retains the original spelling.

### sawlang TODO lines 42–42

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L42-L42)

- CONFORMANCE GAP (flagged Sep 5 by design 266 U0's obligation-3 check): the design-70 both-ways refusal — `run<Slow>` suspends so a `sync` caller refuses, `run<Fast>` stays sync — has NO `examples/conformance/` row, though its covering test exists (`examples/errors/sync_generic_instantiation_suspends.saw`, now also 266's acceptance test). The fix is an INDEX.md row naming that test (design 191's "existing test" form); rides the next brief that touches the effect surface, or a docs batch


## Comments

