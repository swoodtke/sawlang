# Design 123 — One answer to "the allocator said no" (std-wide policy pass)

Source: `designs/reviews/2026-08-04-stdlib-review.md` Part 1 (RS-1 + the
cross-cutting root-cause section). User decision Aug 4: one unifying policy
pass per design 19's three-tier model — not point fixes.

## Problem
std currently has ~9 different behaviors on allocation failure: `Box.make`
panics; `Vector.try_with_capacity` returns `Err`; `Vector.init(capacity:)`
silently degrades; `Vector.push` CORRUPTS (writes past the buffer and bumps
length when `grow()` fails — proven heap overflow, same code shape in
`StringBuilder.append`/`append_char`, `Data.push`/`append`/`append_bytes`,
`Command.append_arg`); `Data.fromBytes` returns `Ok("")`; `Path.join` returns
the un-joined path; `Channel.send` drops the message; `Mutex.lock` returns a
`false` that collides with legal data; `Arc`/`Channel`/`Mutex` constructors
can build silently-inert objects.

## Policy (design 19's tiers, applied uniformly)
1. **Default (hosted convenience) tier:** infallible signatures PANIC on
   allocation failure — loudly, with location (never corrupt, never degrade,
   never inert). This is the tier `push`/`append`/constructors sit in.
2. **Fallible tier:** a `try_`-prefixed variant returning `Result` exists for
   every growth/construction operation a freestanding/kernel caller
   plausibly needs (`try_push`, `try_with_capacity`, `try_make`, ...). Naming
   is uniform (`try_` prefix, no third spelling).
3. **Allocator-parameterized types** (the freestanding toolkit) get the
   fallible tier as their PRIMARY documented surface.

The brief's own first task: sweep every allocation-failure site in std
(the report's table is the seed, not the bound), classify each into a tier,
and record the table in the design doc section of the tracker entry before
changing code.

## Non-negotiables
- No silent degradation and no inert objects remain anywhere.
- `Mutex.lock`-style boolean collisions are replaced by non-colliding
  surfaces per the never-hide-errors rule.
- `Channel.send` never silently drops.
- Tests: a denying/counting allocator fixture (the review's probe technique)
  exercising every tier-1 panic and tier-2 `Err` path for the listed types.
- Spec + saw-lang skill gain one section stating the policy; module docs
  updated where signatures change.

## Exit criteria
The classification table exists; every listed shape conforms; suite +
bootstrap + sos green; tracker RS-1 (and the report's C1/H2/H3/H7/H8 rows)
closed against this design.
