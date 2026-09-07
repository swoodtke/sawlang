---
{"assignee":"","author":"agent:codex-todo-import","body_bytes":5911,"created":"1788791150","id":"SL-8","labels":["todo-import","backlog","design","plan","design-proposal"],"priority":"normal","project":"SL","revision":1,"sequence":8,"status":"open","title":"DF-297a: Share namespace symbols when snapshotting generic templates","updated":"1788791150"}
---


## Description

## Scope and status

DF-297a: Share namespace symbols when snapshotting generic templates

The user already ruled NO COPY on Sep 4: namespace symbols are identity. The fix is deferred to a performance dispatch; audit every reader of type.symbol on materialized instances and measure the snapshot cost. Do not ask for the same ruling again.

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

### sawlang TODO lines 47–47

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L47-L47)

- DF‑297a — the template snapshot's SECOND namespace back-pointer, a `SawType.symbol` on a DECLARED annotation, which DF‑292b's park does not reach and should not: the capture still rebuilds 1,628 namespace method declarations per driven compile, worth ~0.22 s (targeted memo seeding) to ~0.48 s (symbols decline to be copied) more (entry below, filed Sep 3 by the perf batch). Wants a RULING first — should a namespace symbol ever be deep-copied into a template snapshot? — because either fix changes what the snapshot contains and owes obligation 2's sweep **RULED Sep 4 (user): NO COPY — a symbol is namespace identity and snapshots stop AT it; the fix rides a future perf dispatch and owes obligation 2 (everything reading type.symbol off a materialized instance)**

### sawlang TODO lines 450–502

[Original record](https://github.com/swoodtke/sawlang/blob/fd0b5aa8847e3edce9bdcd7880c9ed68923ca4c5/designs/todo.md#L450-L502)

## DF‑297a — the template snapshot's SECOND namespace back-pointer: a
## `SawType.symbol` on a DECLARED annotation. Filed Sep 3 by the perf batch
## (item 2, DF‑292b's fix). **RULED Sep 4 (user): NO COPY — share the
## symbol; a namespace symbol is identity, not template content.** The fix
## rides a future perf dispatch and owes obligation 2's consumer sweep over
## every reader of `type.symbol` on a materialized instance; measurement
## attached below

DF‑292b's fix parks `resolved_type` for the duration of the snapshot's
`deepcopy`, which is the stamp Amendment C2 named. It is not the only edge out
of a template into the namespace. Measured on `coro_generic_driven_both.saw`
with the stamps already parked (`.build/scratch/probe_copyclasses.py`, 535
snapshots per compile):

    objects copied  213,884   deepcopy 0.543s
    of which        1,702 FunctionSymbol, 263 EnumSymbol, 144 StructSymbol
                    2,153 Method  (525 of those are the templates themselves)

So `deepcopy` is still walking out through symbols and rebuilding 1,628 method
declarations that belong to the namespace rather than to any template.

MECHANISM (obligation 4 — this is the same class as DF‑292b, at a second
position). A `SawType` carries a `symbol` back-pointer, and `resolved_type` was
only ONE field that holds a `SawType`. The DECLARED annotations hold them too —
a `Parameter`'s type, a return type, a `let`'s written type — and those are
STRUCTURAL fields, so they are part of the template by construction and cannot
simply be dropped the way a per-pass conclusion can. `_park_per_pass_types`
therefore does not reach them, and it should not.

THE PRIZE, measured (`.build/scratch/probe_symbolshare.py`, which pre-seeds
`deepcopy`'s memo with identity entries for every symbol reachable from a
`SawType` under the template, so the copy stops AT the symbol):

    objects copied   33,107 (-85%)   deepcopy 0.057s   seed walk 0.265s
    total 0.322s against the parked baseline's 0.543s

The seed walk in that probe is a reflective `__dict__` crawl and eats most of
the win; a targeted walk over `structural_fields` -> `SawType` ->
`type_args`/`element_types`/`inner_type` would be much cheaper, and the memo
seeding disappears entirely if the symbol classes simply decline to be copied.

WHY IT IS NOT FIXED HERE. Either spelling changes what the snapshot CONTAINS: a
shared symbol is the LIVE namespace entry, where today it is a private clone
frozen at capture time. Anything materializing an instance from a template and
reading `type.symbol` would start seeing later passes' edits. That is a
behavioral-contract flip owing obligation 2's consumer sweep, and the
`__deepcopy__`-returns-self spelling is wider still — it would change every
`deepcopy` in the compiler that reaches a symbol, not just this one. The
question underneath is a ruling: SHOULD a namespace symbol ever be deep-copied
into a template snapshot? "No, a symbol is namespace identity" is the answer the
measurement points at, but it is not one an agent gets to make inside a perf
batch. [218c Amendment C, C3's DF‑292b bullet]


## Comments

