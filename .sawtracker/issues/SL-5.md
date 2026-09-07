---
{"assignee":"","author":"agent:codex-todo-import","body_bytes":4565,"created":"1788791148","id":"SL-5","labels":["todo-import","backlog","needs-verification","bug","plan"],"priority":"normal","project":"SL","revision":1,"sequence":5,"status":"open","title":"DF-303b: Discover generic methods even when a free function has the same name","updated":"1788791148"}
---


## Description

## Scope and status

DF-303b: Discover generic methods even when a free function has the same name

Imported from repository TODO records on 2026-09-07. The reporter/version, evidence, workarounds and prior rulings are preserved in the source context below. This import is not a fresh reproduction or approval of a proposed design.

Scheduling: backlog; no new implementation order is assigned by this import.

## Proposed plan

1. Reproduce the scoped symptom with the source’s minimal example on the current compiler/pin; record the exact command and expected/actual behavior.
2. Trace the common checker/lowering/runtime path named in the source and fix the mechanism, including the sibling entry points that share it.
3. Promote the reproducer to a regression test, update affected consumers/docs, and run the focused matrix plus the repository’s required checks.

## Acceptance criteria

- [ ] The original case produces the specified behavior or a source-anchored diagnostic, without a compiler crash.
- [ ] The relevant control cases and sibling positions still behave correctly; test/commit evidence is recorded before closure.

## Existing design references

- [sawlang/designs/266-incremental-front-half.md](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/266-incremental-front-half.md)

## Source context

Historical closed subcases are context, not new work. Legacy DF/SL/SO numbers use a nonbreaking hyphen here to avoid accidental tracker links; the linked source retains the original spelling.

### sawlang TODO lines 44–44

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L44-L44)

- DF‑303b — ICE: a generic METHOD whose name collides with a generic FREE FUNCTION is never discovered by the monomorphization fixpoint, so codegen's registry lookup misses and reports "monomorphization did not discover the instance" (entry below, filed Sep 5 by design 266; PRE-EXISTING and unrelated to 266 — both trees ICE identically). One line at a named funnel; the mechanism is that `_method_call_demands` arm (a) disambiguates the module-qualified free call by NAME rather than by the stamps that tell the two shapes apart

### sawlang TODO lines 403–449

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L403-L449)

## DF‑303b — a generic METHOD whose name collides with a generic FREE FUNCTION
## is never discovered by the fixpoint. Filed Sep 5 by design 266 U1;
## PRE-EXISTING and NOT 266's — probed identical on both trees. NOT FIXED

Repro, no optionals, no coroutines, no modules
(`.build/scratch/methgen3.saw`):

```saw
func carry<T>(v: T) -> T { v }
struct Holder { tag: Int }
extension Holder { func carry<T>(&self, v: T) -> T { v } }
func main() { print("{}", carry(9))  print("{}", Holder(tag: 0).carry(10)) }
```

    internal compiler error: monomorphization did not discover the instance
    `Holder_carry$1$Int` of generic method `Holder.carry`, demanded while
    lowering main

MECHANISM (obligation 4), named at `monomorphize.py:_method_call_demands` arm
(a). That arm exists for the MODULE-QUALIFIED free-function call, which the
checker parses as a member access — but it identifies one by NAME:

```python
for candidate in (sym, name):
    if candidate and candidate in self.generic_functions:
        self._demand_function(candidate, targs, subst, depth, chain, where)
        return
```

so an ORDINARY instance-method call whose method name happens to match a
generic free function is routed to `_demand_function` and RETURNS, never
reaching arm (b), where the method instance would be demanded. The
discriminators that actually tell the two shapes apart are stamped on the node
(the arm's own comment says the qualified call is "stamped like a
`FunctionCall`"); the name fallback is the bug.

POSITIONS THE MECHANISM REACHES, probed (`.build/scratch/methgen4.saw`): the
instance-method call and the STATIC-method call both fail (the static one is
what that file reports first). Every `MethodCall`-shaped generic call whose
method name collides is a candidate, so the fix is to gate arm (a) on the
qualified-call stamp rather than on the name — one funnel, one predicate.

NOT FIXED HERE: it is pre-existing, it does not block design 266, and it is a
different funnel from the one 266 touches. Design 266's own regression test
names its method `hold` rather than `carry` to stay off the collision, with a
comment citing this entry.


## Comments

