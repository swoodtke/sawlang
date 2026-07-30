# Design 65 — L17: enum/struct copy-with-retain + aggregate payload extraction (queued Jul 30)

Bug-fix brief closing **L17**, the user-facing bug family design 61
diagnosed and deferred (its drop-fix scope couldn't absorb a
copy-semantics feature). Two symptoms, one root area — how enum
payloads are COPIED and EXTRACTED when they contain refcounted or
optional/pointer-shaped fields. Goal state: exactly-once ownership
accounting for every payload shape the containers use, proven by
deinit/refcount counting tests. This closes the last known
user-facing correctness bug (per the "bug-free at end of loop"
policy).

## Symptom 1 — Set/Map owning-KEY over-drop
`Set<String>` (Set = wrapper over `Map<T, SetMark>`) over-counts
drops: `Map._key_eq` (and any probe path) materializes a
NON-RETAINED copy of the stored key to compare, and that copy is then
dropped — releasing a refcount / running a deinit the map still
logically owns (design 61 measured 2 drops vs 1 owed;
`.build/scratch/setval2.saw` if still present, else re-create).
Memory-safe today only by accident of ordering.
Fix direction: when a copy of an owning value is materialized for
inspection, either (a) make it a RETAINED copy (copy-with-retain:
ImplicitCopy fields get their refcount bump, per the type's copy
semantics) and drop it symmetrically, or (b) make the probe path
borrow without materializing an owned copy (preferred where
expressible — by-ref comparison avoids the copy entirely; design 57
noted by-ref enum-payload projection "not expressible yet", so (a)
may be the honest v1). Choose per site; report the choice. All
Map/Set probe paths audited: _key_eq, _slot_state (should touch no
payload), _hash paths, visitors, snapshots, algebra.

## Symptom 2 — aggregate payload extraction garbage
Matching an enum payload whose FIELDS contain an optional or pointer
(notably `Arc<T>` inside a struct payload, `.build/scratch/enumarc.saw`
repro) extracts GARBAGE — wrong bytes reach the binding. Pre-existing
(confirmed on pre-61 baseline). This is an extraction-layout bug in
enum payload GEP/reconstruction for aggregate fields — diagnose
precisely (field offsets vs the payload's stored layout; likely the
extraction treats the aggregate as its first word or mis-sizes the
byte-array reinterpret). Fix extraction to reconstruct the full
aggregate at its correct offsets.

## Interaction with design 61's consume model
61 made match-on-owned-enum CONSUME the scrutinee (bindings own the
payload; arm-scope cleanup). Copy-with-retain must compose: a
retained COPY extraction (where a copy is the semantics, e.g.
ImplicitCopy binding from a borrowed scrutinee) bumps; a CONSUMING
extraction moves without bumping. The pair (retain-on-copy,
no-retain-on-move) must be applied by ownership context, not
uniformly — getting this wrong flips leak<->double-free. The design-61
test battery plus refcount probes are the oracle.

## Tests (exact-count discipline)
- Set<String>: insert/contains/dup-insert/remove/deinit — exact
  refcount balance (Arc-probe or Deinit-counter wrapper).
- Set<OwningStruct> (Deinit counter): the design-61 battery that was
  blocked (insert/dup/remove/deinit exact counts) now lands.
- Map<String, V> keyed operations: get/contains_key/remove on
  present+absent keys — key refcount balanced.
- Enum with struct-payload-containing-Arc: construct, match, read
  through the Arc — correct value, refcount balanced at scope end.
- Enum with optional-bearing payload: Some/None field values
  round-trip through match.
- Set algebra with String elements (union/intersection) — balanced.
- Full regression: design-61 battery, coro_*/taskgroup_* (frames
  embed enums), whole suite.

## Items (suggested commit units)
1. Symptom 2 extraction fix + tests (independent, do first — it's
   load-bearing for symptom-1 verification with Arc probes).
2. Symptom 1 probe-path fixes (per-site borrow-or-retain) + the
   unblocked Set battery.
3. Tracker: L17 closed with root causes; design 65 landed.

## Hazards
- Retain/no-retain by ownership context — leak<->double-free flips
  are the failure mode; every commit runs the full deinit/refcount
  test family.
- Do not regress the design-61 exactly-once wins (its tests are
  locking).
- The Arc atomic refcount is the platform word — count via observable
  Deinit/drop probes, not by peeking internals.
Full suite per commit; zero xfails.
