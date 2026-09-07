---
{"assignee":"","author":"agent:codex-todo-import","body_bytes":3482,"created":"1788791149","id":"SL-7","labels":["todo-import","backlog","needs-verification","bug","plan"],"priority":"normal","project":"SL","revision":1,"sequence":7,"status":"open","title":"DF-301b: Infer closure parameters from an annotated function-type let","updated":"1788791149"}
---


## Description

## Scope and status

DF-301b: Infer closure parameters from an annotated function-type let

Imported from repository TODO records on 2026-09-07. The reporter/version, evidence, workarounds and prior rulings are preserved in the source context below. This import is not a fresh reproduction or approval of a proposed design.

Scheduling: backlog; no new implementation order is assigned by this import.

## Proposed plan

1. Reproduce the scoped symptom with the source’s minimal example on the current compiler/pin; record the exact command and expected/actual behavior.
2. Trace the common checker/lowering/runtime path named in the source and fix the mechanism, including the sibling entry points that share it.
3. Promote the reproducer to a regression test, update affected consumers/docs, and run the focused matrix plus the repository’s required checks.
4. Cover bare and explicit types, same-module and imported calls, relevant argument/return/field positions, and genuinely ambiguous or out-of-range negative controls.

## Acceptance criteria

- [ ] The original case produces the specified behavior or a source-anchored diagnostic, without a compiler crash.
- [ ] The relevant control cases and sibling positions still behave correctly; test/commit evidence is recorded before closure.

## Existing design references

- [sawlang/designs/264-closure-param-ownership.md](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/264-closure-param-ownership.md)

## Source context

Historical closed subcases are context, not new work. Legacy DF/SL/SO numbers use a nonbreaking hyphen here to avoid accidental tracker links; the linked source retains the original spelling.

### sawlang TODO lines 46–46

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L46-L46)

- DF‑301b — a closure literal assigned to an ANNOTATED `let` of function type does not infer its parameter type, then reports the mismatch against the `Int` fallback (entry below, filed Sep 4 by design 264 U3; PRE-EXISTING, minor). The PARAMETER position of the expected-type ladder DF‑226a/DF‑232h walked for closure returns

### sawlang TODO lines 619–639

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L619-L639)

## DF‑301b — a closure literal assigned to an ANNOTATED `let` of function type
## does not infer its parameter type (filed Sep 4 by design 264 U3, hit while
## writing conformance row V75; PRE-EXISTING, minor)

```saw
let sink: (Owned) sync -> Void = { o in print("{}", o.w) }
// error: Cannot infer type for closure parameter 'o'
// then: cannot assign `(Int) escaping -> Void` to variable of type
//       `(Owned) sync escaping -> Void`
```

The same literal in ARGUMENT position infers fine, so the expected type reaches
closure parameter inference at a call and not at an annotated binding. The
second diagnostic is the worse half: having failed to infer, the parameter
falls back to `Int` and the mismatch is then reported against a type the author
never wrote. Workaround is the explicit parameter type (`{ o: Owned in ... }`),
which is what V75 spells. Neighbour of the expected-type ladder DF‑226a/DF‑232h
walked for closure RETURN positions — this is the PARAMETER position of the
same question, at the one slot that is a binding rather than a call.
[93, 105, DF‑226a, DF‑232h, 264 U3]


## Comments

