# Design 252 — The DF-270d Fix: Unsigned Ordered Comparisons Lower Unsigned

**Status: AUTHORED + DISPATCHED Aug 28 2026** (lead; user: "brief DF-270d
and slot it at the head of the queue" — the Aug-26 correctness precedent
applied). CORRECTNESS: wrong answers at runtime today. Agent DF range:
**DF-275a+**.

## The finding (tracker entry DF-270d has the full text; filed by design 250)

ONE mechanism, TWO faces:
- **(a)** `_emit_int_compare` (`sawc/codegen/operators.py:818`) hard-codes
  `icmp_signed`, and the operator dispatch at `operators.py:478` mis-kinds a
  DISTINCT ALIAS over a primitive (it carries `TypeKind.STRUCT`) into the
  `compare()` path instead of the icmp branch that consults
  `_int_is_signed` — so `<`/`<=`/`>`/`>=` with such an alias on the LEFT
  compare signed: `Byte(255) <= Byte(127)` is TRUE.
- **(b)** `Comparable.compare()` on ANY unsigned integer, alias-free:
  `UInt.max.compare(&1)` answers `Less`. Pre-existing; reaches every
  `Comparable`-bounded generic, every sort over unsigned keys, and
  `sos/kernel/abi`'s eight `type XHandle = UInt`.

Recorded sound on the same values (design 250's evidence): `==`/`!=`, `/`,
`%`, `>>`, widening casts, printing. Pin:
`examples/unsigned_ordered_comparison.saw` (XFAIL, cited — flips with this
fix, marker removed in the fixing commit).

## The fix

1. **The icmp chokepoint learns signedness**: `_emit_int_compare` consults
   `_int_is_signed` on the OPERAND TYPE and emits `icmp_unsigned` for
   unsigned integers — both the operator path and whatever emits
   `Comparable.compare`'s ordering for primitive integers (find the actual
   emission site for face (b); it may be a synthesized compare body or an
   intrinsic — fix it AT its chokepoint, not per-call).
2. **The alias dispatch stops mis-kinding**: an alias over a primitive
   underlying resolves to its underlying BEFORE operator-lowering kinds it
   (one resolution, at the dispatch — not scattered per-operator). A
   distinct alias has no operator surface of its own; the underlying's is
   the contract (spec: one-way flow covers operators — design 250 §1's
   probes are the recorded behavior for the cells that already worked).

## Obligation 4 — the sweep (the fix brief targets the mechanism)

Two enumerations, both probed with compile/RUN evidence:
- **Every operator lowering that consults or should consult signedness**:
  ordered compares (the finding), division, modulo, right-shift (recorded
  sound — the sweep RE-PROVES them at the boundary values), `as` narrowing/
  widening in both signednesses, overflow checks on unsigned arithmetic
  (`UInt8(255) + 1` must panic, not wrap to -0 semantics), unary negation
  on unsigned (what does the checker say?), and `abs`/`min`/`max`-family
  std helpers over unsigned.
- **Every consumer of the STRUCT-kinded alias dispatch**: which other
  operator families does a `Byte`-shaped alias route down the struct path
  (arithmetic, bitwise, shifts, equality — equality is recorded sound;
  prove the rest), and does fixing the kinding change any of their
  behavior. 250's discrimination-grid test is the do-not-break contract.

## Tests

The pin flips (marker removed). New matrix rows in `examples/`: all four
ordered operators x {`UInt8`, `UInt`, `Byte`, a user alias over `UInt16`}
x boundary values (max vs small, high-bit-set vs clear); `compare()` face
on bare unsigned + through a `Comparable`-bounded generic sort (a
`Vector<UInt>.sort`-shaped probe if std has one, else a hand-written
generic min); the sos handle-ordering cell as a compile+run example (plain
`UInt` aliases, no sos build needed). CONFORMANCE: check
`examples/conformance/INDEX.md` for comparison-semantics rows and add the
unsigned row (obligation 3 — ordered comparison correctness is a claimed
language behavior).

## Reopening design 250's held rows (the consequence unit)

With the fix in, complete 250's cbor flip: `std.cbor`'s `byte_at` + the
UTF-8 table move to `Byte` per the census row, and `compare_in`'s
canonical map-key ordering is re-verified — `cbor169_vectors` must REJECT
`bad_utf8` again (that regression is what held the rows; both call-site
comments naming the pin come out). This unit is the fix's live in-tree
proof.

## Gates

Compiler branch: per-commit full suite + freestanding via the suite lock
(SPLIT pattern, every step foreground — NEVER background a gate or stop
mid-wait); terminal FULL battery — a codegen lowering change owes
reemit/irdet corpus-wide, and `sos` still boots. Obligation 2: the only
behavior that changes is wrong answers becoming right ones plus the two
cbor rows; the corpus lanes police the rest.
