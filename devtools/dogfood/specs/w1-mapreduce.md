# Spec w1-mapreduce — multi-threaded map-reduce

Build a map-reduce over a generated dataset where the map phase runs on
multiple OS THREADS (true parallelism, not cooperative interleaving on
one thread).

Behavior:
- Generate 800,000 pseudo-random 64-bit values with this LCG, seeded
  x=42: x = x * 6364136223846793005 + 1442695040888963407 (wrapping),
  value = x >> 33.
- Split into 8 equal chunks IN ORDER. Map, on 4 OS threads: each chunk
  reduces to (count of even values, sum of values mod 1000000007).
- Reduce: combine the 8 chunk results in chunk order into a total even
  count and a combined mod-sum (fold the chunk sums with the same mod).
- Ownership: each chunk's data must be handed to exactly one mapping
  unit; the reduce must consume each chunk result exactly once.

Output (exactly):
- One line per chunk, in chunk order: `chunk <i>: evens <e> sum <s>`
- `total evens <E>`
- `total sum <S>`

Acceptance:
- Identical output across runs (the values are deterministic; chunk
  order is fixed; only the SCHEDULE may vary and it must not affect
  any printed number).
- Must demonstrably use multiple OS threads for the map phase (use
  your language's native mechanism; do not fake it with sequential
  execution).
- Exit code 0.
