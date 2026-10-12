# sawc2 coroutines: the implementation plan (SL-545)

**Status: DRAFT, being written.** Nothing here is approved until the user says so. The Air reviews each section as it lands.

The authorities, in order:
1. LANGUAGE_SPEC §6 (Concurrency) for meaning, and GRAMMAR.md for spelling;
2. SL:architecture §3.9 for the agreed design;
3. `sawc/rt/ABI.md` for the runtime seams;
4. Stage 0 (`sawc/coro_transform.py`, `sawc/coro_shapes.py`, design 275's ledger) as the behavioural oracle, not the template.

## 1. Scope and non-goals
_(to be written)_

## 2. What sawc2 has today
_(to be written: the suspension summaries in typecheck, the accessor split's state records in MIR, mono, the backend, the runtime's reactor and task seams, and the std's task surface)_

## 3. The target
_(to be written: what "done" means, as a shape matrix from `coro_shapes.py` with each cell's intended lowering, and the Stage 0 differential that proves it)_

## 4. Units
_(to be written: an ordered list; each unit with scope, dependencies, the stages and files it touches, pins, and open questions)_

## 5. Open questions for the user
_(to be written)_

## 6. Risks
_(to be written)_
