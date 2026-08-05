# Design 141 — `borrows` functions and `lend`: element places

STATUS: APPROVED (user, Aug 5; DF-132a fold + queue reorder confirmed
Aug 5). Queue position: after 139 → 142 (reordered: soundness ahead of
polish — 135/138 follow this brief). Promotes the P4 "element places /
generalized accessors" entry. Closes the with_ref-closure-ceremony class
AND the DF-132a / DF-128c pair (P0: `Vector.get` aliases NoCopy elements —
two gets double-free; the drop-glue fix that exposes it lands HERE, as the
proven pair). Adjacent to G3 slices (same construct, later brief).

## The decisions [user]

1. **`borrows` is an EFFECT-SLOT keyword** on declarations and function
   types — `func [](i: Int) borrows -> T`, type `(Int) borrows -> T` —
   because the lend-shape is signature-level: a borrows function yields a
   PLACE of T for a window, not a T value. Slot order extends the
   documented sequence: `unsafe sync escaping borrows` (pin, veto-able).
2. **`lend <place-expr>` is the body keyword** marking the borrow window:
   statements before it are the prologue (run at entry), statements after
   are the epilogue (run at window end). Lend-EXACTLY-ONCE on every
   control-flow path, or the path diverges first (panic-before-lend is
   the bounds-check shape) — checker-enforced like return coverage.
3. **Mutability comes from the USE SITE**, never the declaration — one
   body serves both flavors. `v[i].n += 1` opens an exclusive (&var)
   window; `print(v[i].n)` a shared (&) window; `f(&v[i])` a shared
   window spanning the call; `f(&var v[i])` exclusive ditto.
4. **`[]` becomes a declarable method name** (subscript) via borrows; any
   NAMED method may also be `borrows` (`func first() borrows -> T`).
5. **Conditional lend — `borrows -> T?` is the optional place** `[user,
   Aug 5]`. A `borrows -> T?` body's paths each either `lend <place>`
   (the present path — lends real storage as a Some-place) or plainly
   `return None` (the absent path — no storage, an immediate value) or
   diverge; the lend-coverage rule is amended accordingly. The caller
   sees an optional place consumed by 131's rules: `v.get(i)!.m()`
   chains a borrow; `if let x = v.get(i)` value-binds by the policy
   table. This is the semantics behind Map's `[](key) borrows -> V?`.
6. **`Vector.get` becomes `func get(&self, i: Int) borrows -> T?`**
   `[user, Aug 5 — closes DF-132a]`: the non-panicking optional place
   beside `[]`'s panicking place. Trivial/ImplicitCopy value reads keep
   today's owned-`T?` behavior (retained — no caller breakage);
   NoCopy/ExplicitCopy value reads become the policy-table error instead
   of today's silent non-retained alias (two `get`s of one NoCopy
   element double-free on the pre-141 compiler — the 132 unit H repro is
   the regression test). Same conversion for Map's optional accessors.
7. **The DF-128c drop-glue fix lands in this brief, paired** `[user]`:
   the `_type_method_base` mangling fix for drop glue (132 unit H
   diagnosed it correct-but-blocked; its 13-field instrumentation list
   and 60-line repro are in the tracker) ships in the SAME unit as the
   `get` conversion — each is unsound without the other. toml/blade
   migrate STRAIGHT to places (`doc.section("package")!.get_string(...)`
   — `section(name) borrows -> TomlTable?`), one migration, no closure
   interim.

## Semantics (from the design discussion, settled)

- **Window extent**: the smallest enclosing statement/expression; for a
  reference argument, the call expression — Saw references are call-scoped
  and non-escaping, so no lifetime inference exists anywhere in this
  design. A place is never a value and never escapes.
- **Root attribution**: a place borrow charges its ROOT (`&v[i]` borrows
  `v`; shared for &, exclusive for &var) — the design-8/10 path-borrow
  attribution extended one projection kind. Index values are ignored
  (conservative: any `v[i]` borrows all of `v`; the swap-two-elements
  shape is an exclusivity error and `swap` stays a method — Rust's same
  retreat).
- **Conflicts** are the existing Law-of-Exclusivity shapes: passing
  `&var v` beside `&v[i]` in one call; a closure capturing `[&var v]`
  passed alongside — the exact with_var_ref probe the claims review
  verified. No new checker rules, one new projection feeding them.
- **Invalidation safety**: while a window is live its root is borrowed,
  so `v.push(x)` inside the window is a compile error — with_ref's
  guarantee via the law instead of the closure scope.
- **Value reads follow design 131's table**: `let s = v[i]` retains for
  ImplicitCopy elements, errors with hints (`v[i].copy()`, `v.swap_out(i)`)
  for ExplicitCopy/NoCopy. Places COMPOSE with 131's optional places and
  field access: `m["k"]!.items[2].flag = true` is one chained window.
  `v[i] = x` is the whole-element write (set semantics).
- **Multiple place arguments**: prologues in argument evaluation order,
  epilogues LIFO. Two SHARED windows on one root coexist; two exclusive
  error.
- **Accessor rule (130 r8) applies**: a borrows body on a safe type must
  check its index in the prologue (panic out of range) — no unchecked
  places.
- **Lowering**: the borrows body is split at `lend` by the coro
  transform's existing state-split machinery, driven SYNCHRONOUSLY
  (prologue/epilogue = with_ref's shape). No new runtime.

## v1 scope fences (each a possible follow-up, none in this brief)
- borrows functions are `sync`-only (no suspending lend bodies); a place
  window never spans a suspend — with_ref/with_var_ref REMAIN as the
  explicit long-window/multi-statement spellings and as the lowering
  vocabulary. Deprecation is NOT part of this brief.
- No borrows function VALUES or existentials (a borrows method cannot be
  bound or erased in v1).
- No trait participation (generic `T: IndexPlace` is the follow-up);
  v1 lands `[]` borrows methods on Vector, Map (`func [](key: K) borrows
  -> V?` — composes with 131's optional places), Data, and user structs.

## Work
Lexer: `lend` keyword + `borrows` keyword (BOTH lexers — lexdiff parity;
selfhost/lexer mirrors). Parser: effect-slot `borrows` (declarations +
function types, 136 discipline: consistent slot, clean errors), `[]`
method names, `lend` statement. While in the slot parser: `escaping` on a
DECLARATION gets a teaching error ("`escaping` applies to function types,
not declarations — a named function has no environment and may always
escape") instead of today's bare `Expected LBRACE` parse error (probe
`.build/scratch/probe_escaping_decl.saw`; 136's fixit standard). Typechecker: place expressions from
borrows calls (extending 131's place machinery), root attribution
projection, lend-coverage check, use-site mutability resolution, the v1
fences as clean errors. Coro-transform: synchronous lend split.
Codegen: window lowering onto the with_ref shape. std: `[]` for
Vector/Map/Data (bodies from the existing pairs' internals). Tests per
semantic bullet above, incl. the review's invalidation probe as a place,
chained-window composition, LIFO epilogue oracle, lend-coverage errors,
both-flavor use sites from ONE declaration, 131-table value reads.
Docs: spec (new Places section unifying 131 + this), skill, README
(headline ergonomics — saw-docs voice). Tracker: close the P4 entry.
