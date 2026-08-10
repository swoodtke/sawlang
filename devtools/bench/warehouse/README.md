# The warehouse benchmark

A deterministic coordination workload: a dispatcher assigns orders to 100
robots on a 64×64 grid over 200k ticks; robots run a mission state machine
(idle → to-pickup → to-dropoff, battery drain, corner charging). Seeded
LCG, fixed traversal order — every implementation must print the exact
lines in `EXPECTED.txt`, which is what makes the timing comparable and the
suite entry a behavioral pin.

Four implementations, one design axis:

- `warehouse.saw` — the tracked benchmark. Structs in a `Vector`, mission
  enum carrying an order index, place-based mutation. THE BATTERY TIMES
  THIS ONE (`bench` stage, driver in `devtools/bench/src/main.saw`):
  checksums gate, wall time is report-only.
- `warehouse.rs` — idiomatic Rust; the same design (that is the point —
  the borrow checker pushes to indices exactly as Saw's ownership does).
  Manual baseline: `rustc -C opt-level=3`.
- `warehouse2.swift` — struct-idiom Swift, same design. Manual baseline:
  `swiftc -O -wmo`.
- `warehouse.swift` — class-idiom Swift (`final class` robots/orders, ARC
  references in the mission enum). Manual baseline for the
  value-vs-ARC-objects comparison.

Reference numbers and the lowering diagnosis live in the tracker's
"Measured performance" entry (Aug 10). Re-run the manual baselines on a
quiet machine when quoting numbers; the battery's figure is for
trend-watching, not headlines.
