# Design 233 — `while let`: the drain loop gets its header spelling

**Status: BUILT (Aug 16), every ruling as written. Four commits: the
DF-233a prerequisite the dispatch found, then the three units below.

The parser LOWERS the header into `while { if let x = SCRUT { BODY } else
{ break } }`, which is what makes obligation 1 hold by identity rather
than by discipline — the binding IS an `if let`, so every rule already
written for one governs `while let` with no second position to keep in
sync. Two marker fields (`IfLetExpr.while_let`, `WhileExpr.is_while_let`)
carry the three things the desugared tree can no longer say for itself:
diagnostics must name what the author wrote, the synthesized `else` must
not be judged as a branch, and value position must be refusable.

DF-233a, found probing unit 2's premise: the interim `guard let`-`break`
drain idiom this brief cites as the thing `while let` replaces MISCOMPILED
over a suspension, and so would the desugar. An `if let`/`guard let`
carrying a `break` for a suspension-spanning loop was never CFG-split —
design 96 (DF6) had ruled that case for `if`/`match`/`try` but could not
reach the two optional-binding forms, whose split needs a binding rename
that only the marking pass does. Fixed with an obligation-4 sweep (three
positions: the split predicate, a container descent that missed
`try`/`catch`, and the block TAIL, where a drain loop's `if let` usually
sits). See the tracker.**

## Why now

Design 62 excluded `while let` from the grammar ("does not exist", the
spec says so explicitly) when it had no recurring consumer and the
optional-binding hoist machinery was fresh. Both halves flipped on
Aug 16:

- **The consumer family is real.** M3's boot sequence opens every SOS
  process with a drain loop over `next_boot_handle() -> Record?`
  (designs/232), and the Optional-yielding drain family is general:
  `Vector.pop`, `Channel.try_receive` (still `T?` after 230 — the
  sweep left it untouched), `Optional.take`. `for x in v.iter()` is
  already the compiler-blessed version of this exact loop over a
  `next() -> T?` protocol, so the concept is not new — only the
  manual spelling is missing.
- **The implementation cost dropped.** Design 224 made the `while`
  CONDITION a first-class per-iteration suspension position, and
  `if let`/`guard let` scrutinees already hoist suspending calls
  (design 62 G2). `while let` composes from two tested mechanisms.
- **The doctrine favors the header.** `while let r = src.next() {`
  states source, binding and termination in one line; the interim
  idiom — conditionless `while { guard let r = ... else { break } }` —
  buries termination in the body, and its failure mode when the
  `break` line is lost in a refactor is a HANG, not an error. The
  header spelling makes that bug unwritable. Swift and Rust both have
  it; completing the `if let`/`guard let` family is not a second
  spelling of anything.

## Semantics (all ruled)

```saw
while let r = proc.next_boot_handle() {
    // r bound here, one iteration per Some
}
// falls out on the first None
```

- **The scrutinee re-evaluates EVERY iteration** — that is what makes
  it a drain. (Known footgun, accepted as in Swift/Rust: a non-call
  scrutinee over a variable nothing mutates loops forever.)
- **Binding rules are exactly `if let`'s, looped**: same
  derived-shadow rule (a scrutinee mentioning the outer name is a
  legal derived shadow), same pattern surface (a tuple pattern where
  `if let` takes one), same copy-tier rules on the binding (the
  payload read follows design 131's table), same `move` scrutinee
  treatment as `if let`'s where applicable.
- **`break`/`continue` work as in any loop**; `continue` re-evaluates
  the scrutinee (it is the loop head).
- **Value-position `while let` is REFUSED in v1**, same boundary as
  the value-position `while` whose condition suspends: its result
  would come from `break <value>`, and the conditional-loop value
  story stays as it is.
- **Result sources compose via `try?`**: `while let m = try? f()`
  drains a `Result`-returning source, absorbing `Err` into
  termination. No native Result form — 230's `receive()` callers who
  want error inspection write the `match`; the sugar is for drains.

## Units

1. **Parser + sync semantics.** The production (`while` `let` PATTERN
   `=` expr block — no `else` clause exists), desugaring or direct
   lowering per the parser's existing `if let` shape, shadowing rules
   wired through the same checks `if let` uses (not duplicated —
   obligation 1: the binding/shadowing logic is a FUNNEL shared with
   `if let`, whose docstring gains this entry point). Tests: sync
   drain over Vector.pop; derived-shadow scrutinee; tuple pattern;
   non-derived shadow rejected; value-position refused with a clean
   error; `break`/`continue`; nested `while let`; empty-on-entry
   (zero iterations).
2. **The suspension matrix (obligation 1).** A suspending scrutinee
   rides 224's container-head machinery, per-iteration. The matrix,
   each row a run-verified test in driven AND spawned bodies: plain
   suspending call scrutinee; scrutinee with suspending args; body
   suspends while scrutinee is sync; both suspend; MT (`threads: N`)
   spawned root; nested inside `if let`/`match` arms; `while let`
   containing a suspending `try`/`catch`; tuple pattern over a
   suspension REFUSED with the existing clean error (the `if let`
   limit, inherited verbatim). `Channel.try_receive` as a scrutinee
   is a mandatory row (the drain family's concurrency member).
3. **Docs + the spec line.** LANGUAGE_SPEC.md: the design-62 line
   ("`while let` does not exist in the grammar") is REPLACED by the
   feature's entry; the saw-lang skill's patterns section gains it
   and the interim `guard let`-`break` idiom note is updated to name
   `while let` as the preferred spelling; README per the docs
   convention. The M3-sketch's boot-loop example (designs/232) may be
   updated to the new spelling in a rider.

Obligation notes: obligation 2 — no behavioral contract flips (new
syntax; nothing can rely on its absence except the spec text, updated
in unit 3). Obligation 3 — no safety guarantee is touched (the
binding rules are inherited, not new); no conformance rows owed, and
the brief records that reasoning per the obligation. If the astdiff/
selfhost lanes involve a second parse of the new production, the
dispatched agent surveys and covers it in unit 1 (no new TOKENS are
introduced — `while` and `let` exist — so lexdiff/selfhostlex should
be untouched by construction; verify, don't assume).
