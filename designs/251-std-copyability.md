# Design 251 — Map and Set Join the ExplicitCopy Tier (std copyability)

**Status: AUTHORED Aug 27 2026, user-directed** ("we should make all the
types in stdlib at least ExplicitCopy e.g. map, set, etc. so types
containing them can also be ExplicitCopy e.g. JsonValue"). **QUEUED after
design 250** (both touch sawc/std; 250's Byte migration integrates first
and this rebases over it — json.saw is the shared file). Agent DF range:
**DF-271a+**.

## Why, and why the scope is exactly Map + Set (+ the JsonValue proof)

The std.json unit-1 landing was FORCED to make `JsonValue` NoCopy — not a
design choice: `Map<String, JsonValue>` has no ExplicitCopy conformance, so
no containing type can declare one. The Aug-27 survey found the tier map
mostly already right:

| type | today | verdict |
|---|---|---|
| `Vector` | deinit on an UNCONDITIONAL extension (`vector.saw:449`); `Vector<T: ExplicitCopy, A>: ExplicitCopy` (`:479`) with panicking `copy()` + reporting `try_copy` (conformance row A17; DF-257b's naming ruling pending) | THE PATTERN — the oracle this brief replicates |
| `Data` | `extension Data: Copy {}` since design 165 (`data.saw:588`) | done already |
| `Arc` | `Copy` (retain) | done already |
| `Map` | BLANKET `Map<K, V, A>: NoCopy` with the deinit body inside (`map.saw:523`) | **the gap** |
| `Set` | same shape (`set.saw:216`) | **the gap** |
| `String` | Copy tier (compiler-known) | done already |
| `StringBuilder`, `FixedStringBuilder` | NoCopy | STAYS — a builder is an accumulator with identity, not a value |
| `File`, `Mutex`, `SpinLock`, `Once`, `Channel`, `Thread`/`Task`/`TaskGroup` handles, `JsonEncoder`/`JsonDecoder`, `LockRelease` | NoCopy | STAYS — resource/handle semantics; copying is not a value operation |

"At least ExplicitCopy" therefore means: every VALUE-SEMANTIC container is
copyable when its contents are; resource types keep their refusal. If the
user wants StringBuilder or another STAYS row moved, that is a one-line
re-ruling — the brief's machinery covers it.

## The work

**Unit 1 — Map.** Replicate Vector's shape exactly (read `vector.saw`'s
`:440-530` region first — the comments there ARE the spec):
- The deinit body moves from the NoCopy conformance to an UNCONDITIONAL
  extension (every instantiation deinits; Vector's comment explains the
  placement).
- The blanket `: NoCopy` is DELETED; in its place a CONDITIONAL
  `extension Map<K: Hashable + Equatable + ExplicitCopy, V: ExplicitCopy,
  A: Allocator = GlobalAllocator>: ExplicitCopy` — exact bounds per what
  Vector's conformance demonstrates satisfies the tier hierarchy (a Copy or
  trivial member satisfies an ExplicitCopy bound — `Vector<Vector<Int>>`'s
  copy() working is the recorded proof; verify with a probe, don't assume).
- `copy()` is the infallible hook (panics on allocator refusal, exactly
  Vector's spelling and its A17 rationale); `try_copy` is the reporting
  twin. BOTH mirror Vector verbatim in shape; DF-257b's naming ruling, when
  it comes, renames all the twins at once — do not pre-empt it.
- Copy semantics: a NEW table with each key and value copied at its own
  tier (memberwise-deep, matching `@synthesize` semantics); iteration
  order/capacity are not part of the contract.

**Unit 2 — Set.** Same, over `set.saw:216`'s blanket.

**Unit 3 — the proof: `JsonValue` goes `@synthesize ExplicitCopy`.**
Replace `extension JsonValue: NoCopy {}` (its landing report records NoCopy
was forced); the synthesized deep copy recurses through
`Vector<JsonValue>` and `Map<String, JsonValue>` — design 246's row 7
(`recursive_enum_synthesized_deep_copy.saw`) is the recursion precedent.
Tests: deep-copy a nested tree, mutate the copy, prove independence +
exactly-once deinit per tree (the deinit-instrumentation idiom); the six
existing json_value tests stay green (payload-read spellings may need the
tier's idiom — `if let` arms binding NoCopy payloads become Copy-tier
reads; sweep the accessors' `borrows` bodies for spelling changes and
report any that change observable behavior).

**Unit 4 — obligation 2, the consumer sweep, done as probes not prose:**
who relies on Map/Set being NoCopy? Candidates the agent probes: (a) code
moving Maps/Sets that would now silently... nothing — ExplicitCopy still
demands `move` or explicit `.copy()` at transfers, the MOVE rules do not
loosen (that is the point of the explicit tier); (b) `Map`/`Set` inside
NoCopy structs — unaffected (containment allows Copy-tier fields in NoCopy
containers); (c) the design-124/131 synthesized-release paths around
task-owned Maps — the suite's taskgroup rows cover it; (d) any `-W`/doc
text asserting Map is NoCopy (LANGUAGE_SPEC, skill — update per design
125). Record each with evidence in the report.

## Gates

Compiler-tree branch: per-commit full suite + freestanding through the
suite lock (SPLIT pattern in sandboxed worktrees); terminal full battery —
`stdtypes` and the conformance suite are the lanes closest to this change;
`bootstrap` exercises blade's real Maps. Conformance: check
`examples/conformance/INDEX.md` rows touching copy semantics (A17 cited
above) and add the Map/Set rows beside Vector's (obligation 3 — the copy
tier IS a safety-adjacent surface: exactly-once deinit under copies).

## Obligations ledger

1. Funnel: the conditional-conformance pattern is copied from ONE oracle
   (Vector) — no third discipline; the brief forbids inventing one.
2. Unit 4. 3. The conformance rows above, FIRST commit of unit 1.
4. The mechanism that produced the gap: Map/Set predate the conditional-
   conformance machinery Vector adopted (their blanket NoCopy was the only
   spelling once); the survey table above IS the sibling enumeration — no
   other value container remains undeclared.
