# Design 61 — Container element-drop fixes: L14 + L15 joint, L16 (queued Jul 30)

Bug-fix brief; no new language surface. These are the two bugs design
59 discovered and deliberately deferred BECAUSE they need a joint fix
(a partial fix converts the leak into a double-free — 59 reverted it),
plus the L16 ICE design 60 found. House rules govern: exactly-once
deinit, no phantom drops, full suite green per commit.

## L14 — owning enum-payload container elements are never dropped
`Map<K, V>` (and therefore `Set`, and any container whose slots are a
generic ENUM with owning payloads — MapSlot's `Occupied(k, v)`) leaks
its values on deinit when V is an owning type: per 59's diagnosis, the
SUBSTITUTED element type reaches the drop-glue path tagged STRUCT, so
enum drop glue (tag-switch + payload drops) never runs. Fix where the
monomorphized type's kind is recorded/substituted so an enum stays an
enum through drop-glue selection — do it at the source of the wrong
tag, not by re-tagging at the consumption site (59's reverted attempt
shows point-patching shifts the bug).

Cover ALL the value-drop sites once the glue fires:
- container deinit (occupied slots drop k and v);
- `remove()` → returned value moves out, slot payload NOT double-dropped;
- tombstoning drops nothing extra;
- `insert` over an existing key (the E1-fixed return-drop path) still
  drops exactly once;
- `_grow`/rehash moves slots — no drops during migration, old buffer
  freed (59 Part B), values dropped exactly once at final deinit.

## L15 — collection-literal tmp/binding aliasing double-free
With owning elements, the literal lowering (`{k: v}` / `{a, b}` /
Vector-context `[...]`) aliases a temporary and the bound value such
that enabling element drops (L14) double-frees. Fix the lowering so
each element value is transferred exactly once (the literal's inserts
must consume the element expressions like ordinary `insert(move x)`
calls — no residual tmp that drop-glue also sees). L14 and L15 must
land TOGETHER (one commit or two adjacent, but the suite must be green
at every commit — if L14-alone breaks literal tests, it's one commit).

## Tests (deinit-count discipline — use a Deinit-counting struct
and/or Arc refcount probes; assert EXACT counts)
- Map<Int, OwningV> plain inserts → deinit: every value dropped once.
- Map with owning values: remove (moved-out value drops at its new
  binding, not in the map), overwrite-insert (old value once),
  grow-past-capacity then deinit (all values once).
- Set<OwningT> insert/dup-insert/remove/deinit.
- Map literal `{1: v1, 2: v2}` with owning values → deinit: exact
  counts; duplicate-key literal (E1 test extended to L14 world).
- Set literal + Vector-context literal `[ov1, ov2]` with owning
  elements: exact counts, use-after-move errors still fire on the
  moved element bindings.
- Regression: the whole existing suite (esp. enum_payload_deinit,
  vector_elem_deinit*, hashmap/map family, E1's test).

## L16 — `.value` on a distinct `type` ICEs
Design 60 probed: `type MyInt = Int; x.value` ICEs. The spec labels
the `.value` accessor NOT landed (planned/illustrative). Fix = clean
typechecker error ("`.value` is not supported; distinct types flow to
their underlying type implicitly" or similar naming the alias), NOT an
implementation of the feature. Error test. Update the L16 ledger.

## Items (suggested commit units)
1. L14+L15 joint fix + the deinit-count test battery.
2. L16 clean error + test.
3. Tracker: L14/L15/L16 closed with root-cause notes.

## Hazards
- Drop glue is shared by EVERYTHING (structs, enums, arrays, frames);
  the fix must not add drops where none ran for POD/ImplicitCopy
  payloads — the existing deinit-order tests are the oracle.
- Coroutine frames embed enums (the __state machinery + Optionals) —
  run the coro_* and taskgroup_* families attentively; a frame
  double-drop would look like a refcount underflow.
- The 54-literal lowering also feeds DF3-wrapped and default-param
  paths; keep those green (design 53/57 test families).
Full suite per commit; zero xfails.
