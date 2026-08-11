# Design 211 — let-chains: `if let x = opt && cond`

**Status: RULED Aug 11 (user: "let chains are useful, write the brief
with Rust's spelling") + AUTHORED; queue after 208 (parser + binding
machinery family, serial with parser-touching briefs). The motivating
program is the user's own probe — `if let unwrapped = wrapped &&
unwrapped` — which today parses the whole RHS as the scrutinee and
errors "undefined variable `unwrapped`", and which becomes valid
AS WRITTEN under this brief.**

## The rule (Rust's, adopted)

In `if`/`guard` CONDITION position, `let PAT = EXPR` is a chain TERM:
the initializer ends at the first TOP-LEVEL `&&` (bracketed `&&` inside
the initializer stays in the initializer). A condition is then a
`&&`-chain of terms, each either a `let` binding or a boolean
expression, evaluated LEFT TO RIGHT with short-circuit: a `let` term
"passes" when its optional is Some (binding its payload), a boolean
term when true; the first failing term skips everything after it —
side effects and suspensions of skipped terms never run. **Each term
sees the bindings of every earlier term**; all bindings are in scope in
the then-block (`if`) or the continuation (`guard`, whose `else` must
still exit). `||` at chain top level with any `let` term is a CLEAN
ERROR (bindings cannot merge across alternatives — Rust's line, same
reason); `||` fully inside a boolean term's own parentheses is fine.

Existing per-binding rules apply unchanged per term: the design-131
payload-read policy (ImplicitCopy retains; ExplicitCopy/NoCopy demand
the consuming spellings), `move` scrutinees (`if let x = move opt &&
...` — DF-182c's machinery), and the design-100 shadowing mentions-rule
(`if let x = x && ...` stays the derived-shadow idiom). The
suspension-spanning TUPLE-pattern fence carries over per term.

## Units

1. **Conformance/examples first.** The chain matrix: `let && bool`
   (the motivating shape — land the user's probe as the example),
   `bool && let`, multi-`let`, a later term reading an earlier binding,
   SHORT-CIRCUIT rows (a failing early term skips a later let's
   scrutinee side effects — print-instrumented), `||`-with-let refused
   (clean error naming the rule), `guard let` chains (bindings live
   after; else exits), `move`-scrutinee term, the payload-policy rows
   (an ExplicitCopy payload read in a chain term follows 131),
   shadowing-interplay row, and the suspension rows (unit 4's — pinned
   XFAIL here if built before unit 4, per this brief's own sequencing).
2. **Parser.** The condition-position let-term grammar; initializer
   stops at top-level `&&`; `||` restriction; `guard` takes the same
   chain. NOTE the lexer/selfhost parity gates (lexdiff + selfhostlex)
   — no token changes expected, but the selfhost lexer's tests ride the
   battery regardless.
3. **Typechecker.** Sequential term scopes (each term's scope nests in
   the previous); move-dataflow entry/branch states thread through the
   chain exactly as nested `if let` would produce; the design-195
   operand funnel never sees a `let` term (grammar-level, not a Bool
   operand — assert a row proves it).
4. **Coroutine transform.** A chain is CFG-split per term with
   short-circuit preserved — designs 104 (if-let split), 133 (nested
   short-circuit), and DF-182a (suspending scrutinee) are the
   precedent machinery; a suspension in ANY term's scrutinee works, and
   a skipped term's suspension never runs. Under design 210's two-path
   model, chain terms embed like any other scrutinee position.
5. **The diagnostics companion.** The statement-position sibling of the
   motivating confusion: a plain `let x = <expr mentioning x>` with NO
   outer `x` stays an error but gains the targeted hint ("`x` is not in
   scope in its own initializer"); condition-position self-reference
   becomes valid via the chain, so the hint's job shrinks to the
   statement case.
6. **Docs.** Spec patterns/optionals sections (the chain, the `||`
   rule, the scope rule); skill patterns bullet + the `?? false` note
   stays as the Bool?-specific one-liner beside the chain; README's
   pattern example gains one chain line. saw-docs voice.

## Gates

Per-unit commits, full tracked battery each; irdet --all (unit 4 is
lowering); gmgate concurrency lane entries for the suspension-spanning
chain shapes at -n 5; ten-repeat on those. Zero uncited xfails; any
grammar ambiguity beyond the written rule STOPS and files.

## Explicitly out

`while let` and while-chains (Saw has no `while let` at all — its own
future design, noted not taken); `let ... else` statement bindings
(guard covers the need); any `||`-merging semantics; comma-separated
Swift condition lists (one spelling, and it is `&&`).
