# Design 165 — Data rebuilt as a CoW value type over Arc

**Status: APPROVED (user, Aug 7). Queue: concurrent-eligible next
slot (std + examples surface — runs beside M1b/155 once M1
integrates). Closes tracker items DATA-1 and DATA-2 BY CONSTRUCTION.**

## Decision [user]

Data stops hand-rolling the shared-mutable quadrant. It becomes the
Swift-style CoW value type: **Arc-owned storage + offset/length**,
where a slice is a RETAIN (Arc's job — the manual refcount layer and
its `unsafe` allocation bookkeeping are DELETED), and every mutation
passes a uniqueness gate — `strong_count() == 1` → write in place;
shared → clone-then-write (`isKnownUniquelyReferenced`, the pattern).
Data's tier changes **NoCopy → ImplicitCopy** (a copy is a retain;
byte independence arrives lazily at first write). This makes the std
triangle clean: String = shared-immutable, Vector = unique-mutable,
Data = shared-until-written value semantics.

## Consequences (the point)

- **DATA-2 dissolves**: `set`, `push`, `append` all take the same
  uniqueness gate, so CoW-everywhere is the only path that exists —
  not a policy. BEHAVIOR CHANGE, ratified: a byte `set` through a
  slice-sharing Data no longer writes through to siblings.
- **DATA-1 dissolves**: DataIterator holds a Data, and holding a Data
  IS holding a retain.
- `copy()` semantics are observably preserved (value semantics):
  callers copying for isolation still get isolation, lazily. The
  eager spelling remains for anyone who wants bytes NOW (keep
  `copy()` eager or document the laziness — agent's call, note it).
- NoCopy → ImplicitCopy is API-LOOSENING: existing code compiles.
  Docs: the 138-pinned tier lists (skill NoCopy list, spec) move Data.

## Units

1. **The Arc uniqueness gate** (small std/Arc addition, generally
   useful): safe access to the payload exactly when unique — e.g.
   `Arc.with_unique(&var self, body: (&var T) sync -> R) -> R?`
   (None when shared) or an equivalent the existing forwarding
   machinery (design 133) supports cleanly. Design it once; SpinLock/
   Mutex are not involved (single-threaded uniqueness — MT sharing of
   a Data across tasks already goes through Send/Arc rules).
2. **The rebuild**: `Data { storage: Arc<...buffer...>?, offset,
   length }` — payload type is the agent's call (a Vector<UInt8> or a
   dedicated buffer struct), empty-Data representation included. The
   whole public surface preserved: push/append/append_bytes/get/set/
   `[i]` place/slice/copy/try_ twins/len/capacity/iter/fromBytes-era
   constructors. slice() stays O(1) (same Arc, narrower window).
3. **Call-site revalidation**: std.net (read/read_into buffers),
   std.file, std.process, blade + libs (bootstrap is the real-world
   gate — blade leans on Data), sos on the candidate branch is NOT
   touched (it adopts later like every std change).
4. **Tests**: adapt examples/data_cow_slice.saw (the write-through
   expectation inverts per DATA-2's ratified answer); add
   uniqueness-gate shapes (mutate unique = in place, mutate shared =
   isolated), iterator-outlives-Data (the DATA-1 UAF becomes a
   correct retain), Guard Malloc lane entries; deinit-balance
   oracles (Arc counts make these HONEST now — no manual refcount to
   miscount).

## Gates

Full battery (suite zero xfails, lexdiff, astdiff, irdet --all,
bootstrap, sos_runner, gmgate) via ./.venv/bin/python. Docs per
design 125 (spec Data section, skill tier lists, README if it shows
Data). Tracker: close DATA-1/DATA-2, file DF-165x findings.
