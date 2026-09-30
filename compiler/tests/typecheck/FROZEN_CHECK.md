# The one-time check against the frozen compiler

The record of `frozen_check.py`, run once for SL-447's U6b1. The frozen
compiler's answers are checked and recorded here; they are never the
definition of what typecheck must answer.

## Signatures and Copy tiers (`frozen_check.py`)

Over the sawc2 build, the driver and the lex, parse, resolve and typecheck
packages, as they stood when U6b1 was written:

- **459 field types agree**, struct by struct, and none differs.
- **1009 signatures agree**, each free function's and method's parameter
  types and result type, by file, line and name, and none differs.
- **93 Copy tiers agree**, each struct's and enum's, and none differs. Every
  one is a concrete type: no struct or enum of `compiler/` is generic.

Three translations make the two comparable, and the script applies each:

- sawc2 spells a nominal type by its identity, module and path (design 144),
  and fills every defaulted argument; the frozen compiler renders the short
  name and the arguments as written. So the module qualifiers are dropped,
  and so is `GlobalAllocator`, `Vector`'s default and the only one the
  compiler's types leave out.
- An alias is transparent to sawc2, so `Byte` is `UInt8`; the frozen
  compiler keeps the alias's name. Two functions' results differ by that
  alone: `to_byte` in `compiler/lex/src/lib.saw` and `byte_of` in
  `compiler/parse/src/reader.saw`.
- The frozen compiler synthesizes a `deinit` method into each `NoCopy`
  conformance, twelve in the build. sawc2 records the same fact in the
  conformance table, `(deinit implicit)`, and adds no method.

The frozen tiers `free` and `implicit` are both Copy (design 219), and its
`abstract`, a type naming a parameter, would be compared with sawc2's rule
over the arguments; no type of the build needs it.
