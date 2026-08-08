# Design 177 — an infinite `while {}` with no exit types `Never`

**Status: PRE-DECIDED (user, Aug 7 morning — decision 9, tracker commit
3134cf7: "while{} types Never, true-literal excluded"). This brief just
schedules the decided rule. QUEUE: immediately after 176 integrates
(typechecker surface); it UNBLOCKS "172 part 2" (DF-172e — the arena and
the last `__saw_rt_panic` seam body in Saw need a Saw spelling for a
diverging `noreturn` function).**

## The rule (as decided)

- The conditionless infinite loop `while { ... }` whose body contains NO
  `break` (any `break`, valued or not, keeps today's typing: `break v`
  yields `T`) is a DIVERGING expression: it types `Never`, exactly like
  `panic(...)`. A function whose body ends in one satisfies `-> Never`
  (and any `-> T`, since Never flows to everything, matching panic).
- **The true-literal spelling is EXCLUDED** (the decision's carve-out):
  `while true { ... }` keeps its current typing and does NOT become Never —
  the conditionless form is the deliberate "this diverges" spelling; a
  literal-`true` condition stays an ordinary loop a later edit may falsify.
- `cancelled()`/budget instrumentation interplay: inside a TASK body the
  op-budget backedge charge (127) makes the loop suspending — a `Never`
  loop in a `sync` context must still be sync-legal (no charge inserted
  outside task bodies; verify, don't assume).

## Units

1. Typechecker: the divergence rule + `-> Never` satisfaction; the
   reachability consequence (code after the loop is unreachable — reuse
   panic's handling).
2. Tests: `-> Never` with `while {}` (freestanding + hosted), the
   true-literal exclusion pinned, break-forms unchanged, unreachable-after
   diagnostics, a `sync` body case.
3. Docs: spec (beside `panic`/Never), skill digest line.
4. Tracker: close decision 9 + DF-172e; note 172-part-2 is dispatchable.

## Gates

Full battery. Small unit — one agent, short.

## Landed (Aug 7)

Four units, as scheduled. The rule went in as decided, with no deviation.

Divergence is stamped on the loop by whichever checking entry point it went
through, which required one thing the brief did not name: a statement-position
`while` now pushes its own break-tracking frame. It had none, so a `break`
inside a statement loop nested in an EXPRESSION loop wrote to the outer loop's
break type. That was a latent bug of its own; fixing it is what makes "no break
targeting THIS loop" a question the checker can answer per loop.

The three consequences are `panic(...)`'s handling reused rather than
reimplemented — a block whose last STATEMENT is such a loop types `Never`, a
diverging loop is a valid `guard` exit, and codegen terminates the loop's
predecessor-less exit block with `unreachable`, which is what makes every
downstream is-terminated check treat what follows as dead.

**Two pre-existing `-> Never` bugs surfaced and are fixed with it**, both of
them things a Saw-written diverging function makes reachable and neither one
about the loop. A call to a `-> Never` function in VALUE position emitted its
`void` result into the caller's `ret` and took the compiler down inside the
LLVM IR parser (no diagnostic, a traceback); it now terminates the block like an
inline panic. And `let x = panic("m")` crashed the pass with "'NoneType' object
has no attribute 'type'" — a diverging initializer binds nothing, and the block
is already terminated. The bottom type also renders as `Never` now instead of
the enum member name `NEVER`, which had been leaking into hints that named a
type nobody can write.

The op-budget interplay was verified rather than assumed, and the answer is the
one the brief hoped for: design 127 instruments only bodies that become frames,
so a `sync` function is never reached. `while_never_sync_context` pins it the
only way that counts — `halt` is declared `sync`, so an inserted `yield_now()`
would be a compile error, and the program spawns a real task so the transform is
running while `halt` compiles. Its task body carries a diverging loop of its own,
where the charge IS inserted and the loop diverges anyway.
