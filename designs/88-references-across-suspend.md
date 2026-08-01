# Design 88 — References across suspension points (implement D6) (DECIDED Aug 1)

Not a new decision: **D6 was ratified Jul 28 (paper 18)** — "`&var self`
/ reference params may span suspension points freely — sound via task
confinement (refs can't escape their task's call stack; cross-task
sharing is Mutex/channel-mediated)." The implementation never
delivered it: a reference PARAM can't live in a coroutine frame (it
opt-encodes to a reference-typed frame field the re-typecheck
rejects), which forced design 84's net API to go value-based and made
`with_ref` bodies `sync`-only. Deliver D6.

## Scope
1. A reference-typed PARAMETER of a suspending function becomes a
   frame-resident field across suspensions: store the pointer in the
   frame, re-typecheck must ACCEPT a reference-typed frame field, and
   loads/stores through it after resume address the same referent.
   Both `&T` and `&var T`; `&var self` receivers too (design 45 0c
   generalized — a &var self method that suspends and holds self
   across the suspend).
2. Reference-typed LOCALS held across a suspend (same mechanism).
3. Exclusivity/soundness: task-confinement (D6) is the safety
   argument — a ref in a frame is confined to its task's logical
   stack; DO NOT allow it to become Send (a frame crossing threads
   via design-75 spawn must still reject a non-Send-through-ref
   shape — verify the Send gate treats a held reference correctly:
   the referent must be owned by something that outlives the task,
   which for a spawned task means the ref must not point at the
   spawner's stack; keep the existing spawn-strips-references
   behavior for SPAWNED frames, and enable held-references only for
   DRIVEN-in-place frames). Report exactly which frame kinds allow
   held refs (driven-in-place: yes; spawned-cross-task: refs still
   stripped/rejected per confinement). This boundary is the crux —
   get it right, test both sides.
4. `with_ref`/`with_var_ref` across a suspend: with held references
   working, a borrow MAY span a suspension for a DRIVEN-in-place
   borrow — relax the design-81 `sync`-only body IF sound under (3);
   if the confinement boundary makes it unsound for some shape, keep
   the sync restriction there and document precisely.
5. net API: it works value-based and need NOT churn — but ADD a
   reference-taking suspending method/function test (e.g. a
   `read_into(&var Data)` variant) proving the capability end-to-end;
   decide whether to offer the `&var Data` read alongside the value
   `read()` (report; don't force-migrate).
6. Tests: &T param held across a suspend (read after resume); &var T
   param mutated across a suspend (mutation visible to caller);
   &var self method suspending; the SEND-gate boundary (a spawned
   task trying to hold a ref to the spawner's stack = clean
   rejection); deinit/exactly-once unaffected (the ref doesn't own).
   Keep coro_*/taskgroup_*/net_* green.
7. Docs: spec concurrency (D6 now implemented — references may span
   suspensions for driven-in-place frames; the spawned-frame
   confinement rule); saw-lang skill (remove the "references can't
   cross a suspend / net is value-only" limitation notes); tracker.

## Hazards
- The driven-in-place vs spawned-cross-task boundary (item 3) is the
  soundness crux — a held ref into a dead stack frame is a
  use-after-free. Spawned frames MUST keep stripping/rejecting refs;
  only in-place-driven frames (whose referents outlive the drive)
  get held refs. Test the rejection as hard as the acceptance.
- Frame layout with reference fields interacts with drop flags
  (a ref field is never dropped — exempt it) and the design-73
  closure/design-84 method embedding.
Bars: full suite (baseline = post-87) + blade/libs + bootstrap green
per commit; zero xfails. Standing policy; interruption-safe; saw-lang
skill self-review.
