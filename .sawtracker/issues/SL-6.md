---
{"assignee":"","author":"agent:codex-todo-import","body_bytes":4014,"created":"1788791149","id":"SL-6","labels":["todo-import","backlog","needs-verification","bug","plan"],"priority":"normal","project":"SL","revision":1,"sequence":6,"status":"open","title":"DF-301a: Emit valid frame types for generic-struct closure parameters","updated":"1788791149"}
---


## Description

## Scope and status

DF-301a: Emit valid frame types for generic-struct closure parameters

Imported from repository TODO records on 2026-09-07. The reporter/version, evidence, workarounds and prior rulings are preserved in the source context below. This import is not a fresh reproduction or approval of a proposed design.

Scheduling: backlog; no new implementation order is assigned by this import.

## Proposed plan

1. Reproduce the scoped symptom with the source’s minimal example on the current compiler/pin; record the exact command and expected/actual behavior.
2. Trace the common checker/lowering/runtime path named in the source and fix the mechanism, including the sibling entry points that share it.
3. Promote the reproducer to a regression test, update affected consumers/docs, and run the focused matrix plus the repository’s required checks.
4. Use counted ownership events and, where applicable, an address sanitizer; compare sync/driven and owning/copyable controls. Check error, early-return and teardown edges.

## Acceptance criteria

- [ ] The original case produces the specified behavior or a source-anchored diagnostic, without a compiler crash.
- [ ] The relevant control cases and sibling positions still behave correctly; test/commit evidence is recorded before closure.
- [ ] Each owned resource is released exactly once at the required lifetime boundary, with no lost writes or stale owner.

## Existing design references

- [sawlang/designs/264-closure-param-ownership.md](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/264-closure-param-ownership.md)

## Source context

Historical closed subcases are context, not new work. Legacy DF/SL/SO numbers use a nonbreaking hyphen here to avoid accidental tracker links; the linked source retains the original spelling.

### sawlang TODO lines 45–45

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L45-L45)

- DF‑301a — ICE: a SUSPENDING function whose closure PARAMETER's type is a generic-struct instantiation emits an unparseable coroutine frame (entry below, filed Sep 4 by design 264 U3's census; PRE-EXISTING, verified byte-identical pre-U2). Mechanism is frame type emission, not ownership — `Cell<Int>` fails exactly as `Arc<Res>` does. No corpus site has the shape

### sawlang TODO lines 588–618

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L588-L618)

## DF‑301a — ICE: a SUSPENDING function whose closure PARAMETER's type is a
## generic-struct instantiation emits an unparseable coroutine frame (filed
## Sep 4 by design 264 U3's census; PRE-EXISTING, not 264's)

```saw
struct Cell<T> { inner: T }
func hand(body: (Cell<Int>) -> Void, a: Cell<Int>) { body(move a) }
// group.spawn(hand({ c in print("inside {}", c.inner) }, Cell<Int>(inner: 4)))
```

```
error: internal compiler error: LLVM IR parsing error
<string>:43:42: error: invalid type for function argument
%"__Frame_hand" = type {{i1, {void (i8*, %"Cell$1$Int")*, ...
```

MECHANISM: coroutine-frame type emission. `hand` is not `sync`, so it gets a
`__Frame_`; the frame embeds the closure as a function-pointer FIELD, and that
field's parameter is spelled as the monomorphized named struct
(`%"Cell$1$Int"`) at a point where the named type is not defined in the module,
so LLVM refuses the function type. The trigger is the closure parameter type
being a NAMED GENERIC INSTANTIATION, not ownership: `Cell<Int>` (trivial
payload) fails exactly as `Arc<Res>` does, while `String`, a plain `struct
Point` and `Int` all compile and run.

PRE-EXISTING, verified: byte-identical diagnostic with `codegen/closures.py`
checked out at 7f5c06af (design 264 U1, before the U2 release). No corpus site
has this shape — all 2306 tracked `.saw` files compile rc=0 — so there is
nothing to xfail; the repro above is the pin when this is scheduled.
[218 unit 1, 264 U3]


## Comments

