# Design 209 — string slices: owning windows over immutable bytes

**Status: DRAFT Aug 10, discussion-shaped — decision points marked
[OPEN] are the user's; two points are already RULED from the Aug-10
conversation. Not queued; next-session material. Scope: STRINGS ONLY —
fixed-array/Vector slices are borrowed views over mutable storage, a
genuinely different design (parameter-only, no-escape machinery), split
into their own future brief.**

## Why this is cheap where general slices are hard

A Saw `String` is an immutable, refcounted heap block — so a string
slice is an OWNING value, `{ owner: String (retain), start: Int,
len: Int }`: design 165's `Data` window minus copy-on-write (nothing
can mutate under it). ImplicitCopy (a retain), storable, returnable,
Map-keyable. The no-escape rules are not involved at all. The payoff
is every parser in the tree: `split` becomes one retain + two integers
per piece instead of N allocations and byte copies; `trim`/`trim_start`
/`trim_end` stop allocating.

## RULED (Aug 10)

1. **Slices index `0..len()`** — zero-based like every other Saw value,
   bounds-checked against the SLICE's length, panic out of range.
   Swift's inherited-index model (a slice of `a[2...]` still indexes
   from 2) exists because Swift's generic Collection protocol has
   opaque indices for which "rebase to zero" is inexpressible, and
   index interchange with the base is a protocol guarantee; Saw has
   plain checked `Int` indexing everywhere, so importing that model
   would import the `slice[0]`-traps footgun without its
   justification. The owner-position use case is served EXPLICITLY:
   `start_in_owner() -> Int` (name [OPEN]), so translation is written,
   not ambient.
2. **The Swift two-type shape, not String-becomes-window.** Making
   `String` itself a window (Data-unification; `split` keeps its
   signature, slices ARE strings) was considered and declined: a
   `String` value today IS a NUL-terminated `UnsafePointer<Int8>` and
   the C seams rely on it — a sliced window is not NUL-terminated, so
   every FFI crossing would grow a copy-if-sliced check. Runtime-wide
   blast radius, declined. A separate slice type also keeps Swift's
   good reason: a 10-byte slice pinning a 100MB buffer is visible in
   the TYPE, and the `Data.detached()` precedent names the escape
   hatch.

## RULED (Aug 10, continued)

3. **The name is `StringSlice`** — the fully-named Saw convention
   (`StringBuilder`, `TcpListener`), not Swift's `Substring`. A PUBLIC
   std type; reserves its name knowingly (DF-153b's lesson).
4. **Interchange rides a TRAIT, and the trait IS the implementation.**
   `StringView` (name confirmable at brief-finalization) declares two
   primitives — `len(&self) -> Int`, `byte_at(&self, i: Int) -> Int8` —
   and carries the whole read-only surface as DEFAULT BODIES over them
   (`contains`/`starts_with`/`ends_with`/trims/parsers). `String` and
   `StringSlice` conform by supplying the primitives; one copy of every
   algorithm, provably identical on both. LIMITATION to design around:
   primitives cannot be erased (design 176), so `&any StringView` with
   a `String` inside is impossible — interchange is the GENERIC BOUND
   `<S: StringView>`, monomorphized. POLICY (the Swift StringProtocol
   cautionary tale, adopted): std takes the bound only where READING is
   the contract (parse/search/compare); anything that KEEPS text (a
   field, a Map key, storage) takes `String`, and callers write
   `.to_string()` — the allocation is the detach decision and stays
   visible, per no-hidden-alloc grain. `Printable` on `StringSlice`
   covers interpolation/print, the largest interchange class in
   practice. Map-key interop is a real boundary either way
   (`Map<String, V>` probed by a slice needs conversion; a borrowed-key
   lookup story is its own future design, noted not taken).

## [OPEN] — remaining calls

- **`split`'s signature.** (a) CHANGE `split` to return
  `Vector<StringSlice>` (one blessed spelling, a breaking change with a
  consumer sweep — the toml/blade call sites migrate); or (b) keep
  `split` allocating and add a `split_slices` twin (no breakage, two
  spellings forever). The never-two-spellings instinct leans (a).
- **The exact default-body surface list** (which of `chars`/`bytes`/
  the parsers ride the trait vs stay String-only) — proposed at brief
  finalization, user confirms.
- **Does `String` gain `slice(start, len) -> StringSlice` + a range
  spelling, and does allocating `substring` survive beside it?**

## Sketch of units (firms up when the [OPEN]s close)

Conformance rows first (indexing zero-based rows, bounds panics,
pin-the-hash-equality row, retention behavior — owner outlives slice,
deinit-once); the type + surface in std/string.saw (public, one file);
`split`/trim migration per the [OPEN] ruling + consumer sweep; docs
(spec String section, skill, README) with the detached()-analog
guidance ("slices pin their owner; `.to_string()` to detach").

## Explicitly out

Fixed-array/Vector slices (borrowed views, parameter-only `&[T]` —
own future brief; the Aug-10 conversation's option 3); any String
representation change; mutable slices (strings are immutable, so the
question cannot arise here — which is exactly why strings go first).
