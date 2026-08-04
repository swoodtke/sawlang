# Design 120 — suspension in expression position: chains, args, and beyond (queued Aug 4)

USER DECISION (Aug 4): support suspending calls anywhere an expression
can appear — `a().b().c()` with any of a/b/c suspending, suspending
arguments, receivers, operands — ending the buried-suspension error
class. Usability win, and it deletes documented limitations rather
than adding features: the design-104 rejection list, the spec's
"chains of suspending calls" section, the design-111 suspending-hop
carve-out, and the tracker's suspension-mid-chain future-work item
all close.

## The mechanism: the compiler unchains for you

The blessed manual workaround IS the transform: rewrite any statement
containing nested suspending calls into evaluation-ordered temporaries
(A-normal-form style) — `let r = a().b().c()` becomes internally
`let __t1 = a(); let __t2 = __t1.b(); let r = __t2.c()` — then the
EXISTING design-96/101/104 statement-level embedding machinery handles
each step unchanged (frame-resident locals, refs across suspends,
CFG-split branches: all reused, none rebuilt). This runs inside
coro_transform, only for statements whose expression tree actually
contains a suspension source; sync code is untouched (zero codegen
diff for programs with no buried suspends — verify on the suite).

## Pinned semantics

1. **Evaluation order preserved exactly.** Left-to-right (spec
   "Argument Evaluation Order"); everything ordered BEFORE a hoisted
   suspend point hoists with it, in order. Side-effect tests pin this
   (counter functions at each position).
2. **Deinit timing preserved.** Chain intermediates die at statement
   end today; hoisted temps must too (not scope end). Deinit-once
   tests with Deinit-carrying intermediates on suspending AND
   non-suspending paths.
3. **Conditional positions stay conditional.** A suspend in a
   position whose evaluation is conditional must NOT be hoisted above
   the condition: `?.` tails after a short-circuit, `??` RHS,
   `&&`/`||` RHS, if/match arms in value position. These lower to the
   branch shape first (if-expression → if-statement assigning a
   temp, the design-104 pattern), THEN hoist within each arm.
   Short-circuit skip-side-effect tests pin it (the design-111
   counter pattern).
4. **Ownership/borrow semantics unchanged.** The hoisted form must
   typecheck exactly as the manual unchaining would: exclusivity,
   move checkpoints, ref-across-suspend (design 88/106) all apply to
   the temps. A shape the MANUAL unchaining cannot express (e.g. an
   exclusivity conflict the temp introduces) stays a clean error
   anchored at the original expression — never a silent semantic
   change.
5. **`sync` contexts unchanged**: a suspending call anywhere in a
   sync fn stays an error. Effect inference unchanged (position never
   mattered to it). Design-74 suspension-path diagnostics must still
   anchor at the ORIGINAL source position (temps carry source spans).
6. **Blocking externs (design 103) ride along where free**: their
   statement-bound restriction exists because of the same buried
   rule; if the ANF hoist lifts them for free, flip their xfails too;
   if the offload lowering needs extra work, leave those xfails
   standing and tracker-flag the remainder (do not force it).

## Stage 0 — the XFAIL contract (FIRST commit, before any transform work)

Land the full known-unsupported matrix as `examples/` tests, each
with correct `// EXPECT-OUTPUT:` for the post-fix behavior plus
`// XFAIL: design 120 pending` (the runner treats xfail as OK, and
XPASS flags a stale marker the moment a case starts passing).
Matrix (one focused test per case; extend with anything else found in
the design-104 rejection list or spec/skill "clean error" mentions):

- suspending HEAD of a chain: `a().b()` (a suspends, b sync)
- suspending LATER hop: `x.b().c` and `x.b().c()` (b suspends)
- every-hop suspending: `a().b().c()`
- suspending call as function/method ARGUMENT: `foo(s.read())`;
  argument-of-argument; labeled args; multiple suspending args in
  one call (order test)
- binary operand: `1 + f()`, `f() + g()` (order), comparison operand
- return expression: `return f().g()`
- string interpolation: `print("{f()}")`
- collection literal element: `[f(), g()]`; Map value
- struct literal field: `T(x: f())`
- tuple literal element: `(f(), 2)`
- `try!`/`try?`/`try ... catch` over a suspending Result chain
- value-position if/match: `let x = if c { s.read() } else { ... }`,
  match arms yielding suspending calls
- `??` RHS suspending (+ skip-side-effect counter)
- `&&`/`||` RHS suspending (+ skip counter)
- `?.` chain with a suspending method hop (design-111 carve-out) +
  chained-assignment RHS `x?.y = f()` (f suspends, skip counter)
- optional-binding scrutinee: `if let v = maybe_suspending()` /
  `guard let` (if these already pass, land WITHOUT the XFAIL marker
  as positive controls)
- deinit-once: a Deinit intermediate held across the hoisted
  suspension; exclusivity: a shape where hoisting must still error
  (expected-error test, not xfail)
- blocking-extern buried forms (design 103): argument position,
  binary operand (per pinned-semantics 6)
- sync-context rejection regression (stays an error — error test)

SUCCESS CRITERION: every stage-0 XFAIL marker is REMOVED by the end
(test passing), except any explicitly moved to a recorded carve-out
list in the tracker with the reason — no silent survivors; zero
XPASS (a passing test must have its marker removed in the same
commit that makes it pass).

## Stages (each suite-green; per-unit commits)

- **Stage 0**: the XFAIL matrix above (lead reviews the contract in
  history).
- **Stage 1**: unconditional positions — chains, receivers,
  arguments, operands, literals, return/interp — via the ANF hoist.
- **Stage 2**: conditional positions — `?.` mid-chain + chained
  assignment, `??`, `&&`/`||`, value-position if/match.
- **Stage 3**: sweep — old rejection-shape error tests flipped or
  retired (the ones that now WORK), docs: spec (Argument Evaluation
  Order + the concurrency section's buried-suspension prose), skill
  (the "clean error" bullets), README if it mentions unchaining,
  CLAUDE.md digest line, tracker closes (104 list, 111 carve, the
  suspension-mid-chain future-work item).

## Non-goals

Changing WHEN things suspend (only where the calls may appear);
scheduler/executor changes; new syntax; making `sync` contexts accept
suspension; generic-template effect-node gaps (the design-104
same-module nested-generic limit is its own item — if the hoist
changes its shape, tracker-flag, don't fix here).

LANGUAGE-ISSUE POLICY (user, Aug 4): do NOT work around language
bugs/limitations. Unambiguous compiler bug → fix with tests (sawc/ is
in scope). A design gap that blocks a stage → STOP at the previous
boundary, DF-120 tracker entry with repro + wanted code, report
prominently. XFAILs that cannot flip within scope are recorded
carve-outs, never silently reworded.

Bars: full suite zero UNEXPECTED failures per commit (stage-0 xfails
are expected until flipped; zero XPASS at every commit); bootstrap +
sos_runner at stage boundaries; per-unit commits; linear history; no
attribution trailers; foreground suites; interruption-safe.
SEQUENCING: dispatch only AFTER design 118 lands and integrates
(both rewrite coro_transform); MAY run concurrent with design 119
(disjoint files — 119 is std + lexers; both add examples/, distinct
filenames).
