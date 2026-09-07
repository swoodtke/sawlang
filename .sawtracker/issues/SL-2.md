---
{"assignee":"","author":"agent:codex-todo-import","body_bytes":2735,"created":"1788791147","id":"SL-2","labels":["todo-import","queued","design","plan","design-proposal"],"priority":"normal","project":"SL","revision":2,"sequence":202,"status":"open","title":"Design 259: implement the self-hosted parser in its ruled stages","updated":"1788791293"}
---


## Description

## Scope and status

Design 259: implement the self-hosted parser in its ruled stages

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

## Related tracker work

These are related findings/plans; a reference alone does not imply a blocking dependency.

- SL-74 — DF‑287a: Keep fall-through ownership after a move in a diverging catch

## Existing design references

- [sawlang/designs/258-field-visibility-inheritance.md](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/258-field-visibility-inheritance.md)
- [sawlang/designs/259-selfhost-parser.md](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/259-selfhost-parser.md)

## Source context

Historical closed subcases are context, not new work. Legacy DF/SL/SO numbers use a nonbreaking hyphen here to avoid accidental tracker links; the linked source retains the original spelling.

### sawlang TODO lines 37–38

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L37-L38)

- Design 259 — the self-hosted parser (designs/259-selfhost-parser.md; QUEUED Sep 1 by the user, §3 ruling batch fully RULED same day incl. R7′ statement arms). The brief is the source of the next batch: U0 grammar debt + U1 depth funnel are compiler dispatches and serialize with the pipeline (N10's soundness fix goes FIRST after 218/1.5 integrates, by fix-on-discovery — brief §4); U2–U5 are selfhost/-side and may run CONCURRENT with design 258 in a worktree; the Class-2 fix set (incl. DF‑287a/b) triages at U0 dispatch


## Comments

