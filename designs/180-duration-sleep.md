# Design 180 — `sleep(Duration)`, and only that

**Status: APPROVED (user, Aug 7 evening): sleep takes `time.Duration`;
the `sleep(ms: Int)` variant is REMOVED ENTIRELY (no deprecation period —
the tree is young); Duration gets easy unit-named constructors. Closes
DF-170a BY CONSTRUCTION (UInt64 nanoseconds internally — the 32-bit-µs wrap
becomes unrepresentable at the API; the libc bound is chunked inside the
seam as an implementation detail). QUEUE: after the current wave
(179/169p2/172p2) integrates — std + rt + tree-wide example sweep.**

## Units

1. **Duration constructors audit** (std.time): `Duration.ns(_)`,
   `Duration.us(_)`, `Duration.ms(_)`, `Duration.secs(_)` — UInt64-backed,
   whole-range, no float involvement; plus the accessors' consistency
   (existing surface kept). Overflow at construction (secs beyond the u64-ns
   range) follows the 170 discipline: panic with the named constructor,
   `try_` twin only if a real caller needs it (probably not — 585 years).
2. **PRELUDE DECISION [recommended, ratify at review]: `Duration` joins the
   prelude.** `sleep` is a prelude builtin; its only argument type cannot
   require an import without regressing every `sleep(200)` call site to
   needing `import std.time`. The serde precedent (prelude-visible
   vocabulary because derived/builtin surfaces name it bare) applies
   exactly. `Instant` STAYS import-required (not builtin vocabulary).
3. **The signature swap**: `sleep(d: Duration)` lands, `sleep(ms: Int)` is
   DELETED in the same unit; the whole tree migrates in the same commit
   (`sleep(200)` → `sleep(Duration.ms(200))` — mechanical; examples, std,
   blade, devtools, docs snippets). A bare-Int call gets the ordinary
   no-match error listing the Duration signature — verify the hint reads
   well (name `Duration.ms` in it if the machinery allows).
4. **The seam**: `__saw_rt_sleep_ns(UInt64)` added to rt/ABI.md; the Saw
   seam body chunks to the libc 32-bit-µs bound in a loop (total elapsed
   honored — a 40-minute sleep sleeps 40 minutes); the old ms seam retired
   from ABI.md in the same change (runtime-build checks enforce the doc).
   Cancellation behavior across chunk boundaries preserved (a cancelled
   task wakes at the next chunk edge at worst — state the bound in the
   seam doc).
5. **Docs**: spec (sleep + Duration section), skill (the sleep idiom
   changes — `sleep(Duration.ms(200))`), README if it shows sleep.
   Tracker: DF-170a CLOSED by construction. Forward note: M2's Timer
   object and future net timeouts take Duration — this is the vocabulary
   landing ahead of its consumers.

## Gates

Per-unit commits, full battery each (suite zero uncited xfails, lexdiff,
astdiff, Saw-irdet --all, bootstrap, gmgate, sos both arches). The
migration unit's diff is large but mechanical — the battery is the proof.
DF-180x findings as usual.

## Explicitly out

TimeoutMS/TimeoutNS alias family (considered; rejected — design-63 aliases
flow to UInt64 so cross-unit arithmetic silently compiles; Duration is
closed under its own ops); float-taking constructors (pending 173);
Instant/monotonic-clock changes; net/channel timeout parameters (future
consumers, not this brief).
