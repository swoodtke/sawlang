# Design 185 — bitwise operators in const expressions (+ flag enums)

**LANDED Aug 8** in five commits (units 1, 2, the DF-185a fix, units 3+4
together, docs). All five units built as written, with one deviation and one
finding:

- **Unit 3's `static RW: UInt8 = Perm.Read | Perm.Write` example does NOT
  work, and is filed as DF-185b.** A static initializer takes only literals
  (design 41's const-init list), which is a separate rule from the const
  evaluator and has its own ordering questions — widening it would also have
  to teach DF-172j's pre-registration static pass to evaluate, in declaration
  order, with a cycle rule, before any enum is registered. The rest of unit 3
  landed: the fold works in every position that CONSUMES a constant (array
  length, repeat count, const generic argument, `static_assert`). Pinned by an
  XFAIL that flips to XPASS when the initializer rule widens.
- **Units 3 and 4 landed in one commit**: the flag-enum reading and the
  `as` fixit are two branches of one `if` in `_check_binary_op`.
- **DF-172l CLOSED, both halves** — the parse half by unit 2 and the
  resolution half by unit 3's stamping walk, which reached the qualified
  spelling with the ordinary name-resolution machinery.
- **DF-185a found and fixed on discovery**: a hex enum raw value
  (`case Debug = 0x100`) was an uncaught parser crash, i.e. the notation the
  raw-backing feature exists for.

Original brief follows.

**Status: APPROVED + QUEUED, NOT launched (user, Aug 8: "brief that and add
it to the queue" + "ensure the brief handles enums since it's a usability
win when uint-based enums are bits"). Small typechecker/const-eval unit —
no new semantics, arithmetic over compile-time-known integers. Queue: after
the net track or in parallel (const_eval/typechecker surface; disjoint from
182/183/184 net work, shares surface with nothing else queued).**

## The gap

`sawc/const_eval.py` folds `+ - * / %`, the six comparisons, and `&& ||`,
plus `sizeof`/`alignof` and (DF-172j) module statics + enum cases + Int.max.
It does NOT fold shifts or bitwise ops — `<< >> & | ^` reject at the
BinaryOp fallthrough, `~` has no unary case. And the two const POSITIONS
accept different grammars: a repeat count `[v; N]` takes a full const
expression (semantic reject on `<<`), while a type length `[T; N]` parses
only the design-148 const-generic subset (a PARSE error on `<<`, before
const-eval runs — the same narrow grammar behind DF-172l/DF-172j's qualifier
gap). Both hurt exactly the code Saw targets: wire-layout and register math
(`1 << BIT`, `FLAGS << 8`, mask composition, `WIDTH & ~ALIGN_MASK`).

## Units

1. **Const bitwise + shift.** Add `<< >> & | ^` to the `const_eval` BinaryOp
   handler and `~` to the unary handler, evaluated at the expression's
   WIDTH (the evaluator already carries `width` for Int.max) so a shift/
   complement masks to the target width rather than Python's unbounded int.
   Negative shift count and shift >= width are clean rejections (the panic
   the runtime would give, caught at compile time). Composes with everything
   already foldable.
2. **Unify the two const-position grammars.** The type-length position
   `[T; N]` should accept the SAME expression grammar the repeat-count
   position does, so `[Int8; BASE << 2]` parses and then folds (or gives a
   SEMANTIC reject), instead of a parse error. This subsumes the grammar
   half of DF-172l (member access in type position) — fold that finding's
   qualifier case in if the unified grammar reaches it cleanly; if the
   qualifier half opens the separate visibility question DF-172l named,
   keep it filed and do the operators + local-name grammar only.
3. **Flag enums — the usability win, scoped honestly.** A raw-backed enum
   case already folds to its backing value in const-eval (the MemberAccess
   path). With unit 1, `Perm.Read | Perm.Write` and `Flags.A << 2` FOLD in
   any const position — so `static RW: UInt8 = Perm.Read | Perm.Write` and
   `[UInt8; Cfg.Mask & 0x0F]` just work. **The result type is the BACKING
   INTEGER, not the enum** — this is the load-bearing rule: a combined flag
   value (0x03) need not be a declared case, so typing it as the enum would
   break `from(raw:)`/exhaustiveness (design 145). Document it: an enum is a
   closed set of tags; a bitSET over those tags is the backing integer. That
   is Swift's OptionSet / Rust's bitflags boundary, stated once.
4. **Runtime bitwise on enum VALUES stays EXPLICIT — RATIFIED (user, Aug 8:
   "explicit is good — generally doing math on enums is a no-no").** A
   bitwise operator applied to an enum-TYPED value (`a | b` on two `Perm`s)
   is NOT added; the spelling is `(a as UInt8) | (b as UInt8)`, and the
   typechecker's existing "operator not defined on enum" error stands (verify
   it reads well — name the `as` fixit if the machinery allows). The `as`
   names the enum→bitset crossing exactly as design 145 made `e as UInt8`
   the explicit total projection, and it keeps the invariant "a raw-backed
   enum value is always a declared case" TRUE. This is a stated language
   principle now — doing arithmetic on an enum value is a no-op the language
   declines to make silent. (Const-position folding in unit 3 is a separate
   matter and unaffected: there the operands are CASE NAMES whose values are
   compile-time constants, and the result is already the backing int.)
5. **Docs + tests.** Spec (const-expression grammar list + the flag-enum
   boundary), skill (the wire-math idiom: `1 << BIT`, `A | B` flag consts).
   Tests: each operator folded in both positions, width-masking edges
   (shift-by-width, `~0` at each width), the flag-enum const, the
   still-rejected cases (non-const operand, out-of-range shift), and a
   negative array length can't sneak through a `<<` (DF-172k's class).

## Gates

Per-unit commits, full battery each (suite zero uncited xfails, lexdiff,
astdiff, Saw-irdet --all, bootstrap, gmgate, sos both arches). irdet
matters here — folded lengths feed mangling, so two files with the same
folded bit-expression must mangle identically. DF-185x findings as usual.

## Explicitly out

A typed OptionSet/bitflags WRAPPER type (the real "flag enum" type with
`.contains()`, set algebra, exhaustive-safe storage) — a genuine std
design, not this unit; this brief only makes the const arithmetic and the
backing-int rule work. Float const-eval (pending 173). Runtime const-fn /
general comptime (a large separate design if ever).
