# Design 213 — closures: local `return` typing + the embed identity leak

**Status: DF-212a LANDED Aug 13 (units 1-4). DF-212b minimized + pinned
(units 5-6); unit 7's FIX is STOPPED pending a ruling — see "What the
sweep changed about DF-212b's shape" below, which retires two of this
brief's premises. Fixes the two compiler
bugs design 212's sweep surfaced (DF-212a, DF-212b — filed with full
bisection notes in `designs/todo.md`, "Design 212 findings"). One
family: both are places the typechecker/embed machinery fails to
account for a closure literal in the tree.**

## What the sweep changed about DF-212a's shape (Aug 13)

Obligation 4 applied: the mechanism is **the checker keeps ONE answer to
"what callable am I in" and a closure body is checked without pushing a
new one**. DF-212a is one of SEVEN positions that read it, found by
probing every reader of the enclosing callable's state:

| # | site | symptom before |
|---|------|----------------|
| 1 | `_check_return_statement` | DF-212a: closure `return` checked against the outer fn — and, post-transform, against the frame's `resume() -> Poll` |
| 2 | value-`if` arm Result auto-wrap (`_check_if_expr`) | a closure declared `-> Result<T,E>` could not auto-wrap its arms |
| 3 | `match` arm Result auto-wrap | same |
| 4 | `_validate_error_propagation` | a `try` in a non-Result closure ACCEPTED whenever the outer fn returned a Result → **LLVM ICE** (`value doesn't match function result type 'i64'`) |
| 5 | `in_try_catch_block` / `_try_catch_error_types` | a closure's `try` routed to the OUTER frame's catch → **LLVM ICE** (`use of undefined value '%caught_error'`) |
| 6 | `found_return_with_value` | a `return` in a closure silently satisfied the OUTER function's "body yields a value" check |
| 7 | codegen `current_return_type` (`_generate_closure`) | `return`/`try` in a `-> Result` closure asked the enclosing signature (`Cannot create Result.Err outside Result-returning function`) |

Per the ELABORATION PRINCIPLE (design 218) the fix is not a
classification patch at seven sites: it makes the checker's notion of
"the callable I am in" correct, and every site asks the one funnel
(`_return_target` in `core.py`, whose docstring names its entry points).
Codegen gets the symmetric one-line context save.

**Unit 1's probe answer: codegen was already RIGHT.** With agreeing
types (`func f() -> Int` containing a `(Int) -> Int` closure with
`return 99`) the return exits the CLOSURE's frame — the caller resumed
after `body(5)` with `r=99` and the outer function returned 100. So
DF-212a proper is diagnostic-only and **no `examples/conformance/` row
is owed** (the brief's own carve-out). The two ICEs at siblings 4 and 5
are the mechanism's miscompile-class members, and they are compile-time
rejections now, not conformance rows.

**Unit 4's sweep: ZERO.** A brace-scanning census over all 2003 tracked
`.saw` files finds no `return` written inside a closure literal
anywhere in the corpus — so nothing was relying on the agreeing-types
accident, and the codebase's value-expression closure idiom is
confirmed corpus-wide, not just in std.

Two adjacent findings this work opened, both filed in the tracker:
**DF-213a** is the pair of ICEs above (closed by this landing);
**DF-213b** is a pre-existing gap this work exposed but did NOT close —
a closure declared `-> Result<T, E>` does not auto-wrap its TAIL value
the way a named function does (`return v` works, a bare `v` tail does
not).

## The ruling this brief carries

A `return` inside a closure literal returns FROM THE CLOSURE and is
checked against the CLOSURE's own return type. This is what the
compiler's own model already assumes (DF-187c's coro_transform notes
say "a closure's own `return` is untouched"), what every mainstream
language does, and the only reading under which the closure-as-value
semantics compose. If the user wants the Swift-style "no early return
from closures at all" instead, that is a one-line veto — the pin's
EXPECT directives are the only thing that changes.

## DF-212a — closure `return` checked against the wrong function

`_check_return_statement` (`sawc/typechecker/statements.py:2825`)
reads `self.current_function`/`self.current_method` and never tracks
entry into a `ClosureExpr`, so a `return` textually inside a closure
is checked against the enclosing NAMED function's return type. When
the types disagree: a loud, wrong error. When they AGREE: it compiles
— and nobody has established what the emitted code does.

Units:
1. **Probe first.** Same-type case (`func f() -> Int` containing a
   `(Int) -> Int` closure with `return 99`): compile, run, and answer
   WHICH frame the return exits at runtime. If control escapes the
   ENCLOSING function's frame (or corrupts it), this is a miscompile,
   not a diagnostic bug — record the answer in this brief, and add an
   `examples/conformance/` row for "a closure's return exits the
   closure" (obligation 3 applies the moment the probe shows a
   safety-relevant answer; skip the row if it turns out to already
   behave correctly and the bug is diagnostic-only).
2. **Pin** (XFAIL citing DF-212a): the minimal repro from the tracker
   entry, EXPECT directives asserting the ruling above.
3. **Fix.** The checker tracks closure entry (a stack, not a flag —
   closures nest) and `return` resolves against the innermost
   enclosing callable: closure param/return types when inside a
   `ClosureExpr`, the named function otherwise. Suspending bodies:
   verify against coro_transform's existing model (which already
   treats closure returns as local) — the fix should make the
   typechecker AGREE with the transform, not add a second opinion.
   Codegen: whatever unit 1 found wrong gets fixed at its own site.
4. **Sweep** (obligation 2 discipline, though this is a bugfix, not a
   contract flip): grep all tracked `.saw` for `return` inside closure
   literals. The 212 agent reports std's closures are all
   value-expression style; confirm corpus-wide and record the count in
   this brief. Any offender that compiled before was relying on the
   agreeing-types accident — reason through each (expect zero).

## DF-212b — a closure-literal argument mints a second type identity

The sharp one, and it BLOCKED 212's unit 4 as designed. Shape (fully
bisected against real blade, each leg re-verified; both files were
restored — the tree carries no trace): a free function taking a
closure parameter, called with a closure LITERAL argument from a
module that gets CROSS-MODULE-EMBEDDED because its caller transitively
suspends (design 210's machinery), makes an UNRELATED enum declared in
that same module fail type identity against itself — ``field `command`
expects type `BladeCommand` but got `BladeCommand` `` on a line
textually BEFORE the closure call. Same printed name, two identities:
design 144's signature for one type resolved under two different
(module, name) answers. Load-bearing legs: the closure literal
argument AND the transitively-suspending `main`. Not load-bearing:
the closure's own signature (reference-free `(Int, Int) -> Int`
triggers it), 212's units 2/3 content.

Units:
5. **Minimize.** A standalone multi-file repro is still OWED — the
   isolated two-file attempt without a suspending call did NOT
   reproduce, so the embed condition must be constructed: module A
   declares an enum + a struct holding it + a closure-taking free
   function + a function calling it with a literal; module B's `main`
   imports A and transitively suspends. Start from the tracker entry's
   bisection legs; the repro goes under the pin.
6. **Pin** (XFAIL citing DF-212b) once minimized, EXPECT directives:
   it compiles and runs.
7. **Root-cause + fix.** The reading on file: registering the
   closure-typed parameter's argument at the call site, during the
   pass that builds or re-resolves the embedded frame, re-resolves the
   enum under the wrong module answer. Suspects, in order: the
   design-210 embed path's annotation handling for closure-typed
   values (a closure argument is one of the shapes the six-family
   embed contract must carry — check whether a `ClosureExpr`'s
   annotations survive the splice or get re-derived), then design
   204's `_type_lookup_module` funnel (is the closure's synthesized
   symbol resolved in the HOME module or the embedder's?). Fix at the
   identity chokepoint; the astgraft gate and the embed contract
   docstring (coro_transform.py) must both stay true afterwards.
8. **Optional, after the fix**: 212 unit 4's original closure-based
   `scan_args` becomes writable. Do NOT rewrite cli.saw (the landed
   Set/Map design is fine and tested) — instead the pin from unit 6
   plus one closure-argument-in-suspending-caller example is the
   regression coverage.

## What the sweep changed about DF-212b's shape (Aug 13, units 5-7)

**Units 5-6 LANDED; unit 7 STOPPED and reported.** Two of this half's
premises did not survive contact:

1. **The closure is INCIDENTAL.** The minimized repro contains none.
   A non-`sync` function-typed parameter is conservatively
   suspending, so the original `scan_args({...})` was just the
   cheapest way to make `parse` suspend; a plain `yield_now()` in its
   place reproduces identically. The brief's title for DF-212b ("a
   closure-literal argument mints a second type identity") names a
   coincidence, not the mechanism. Unit 8 is therefore MOOT — there is
   no closure-argument shape to re-enable.
2. **There is no second identity.** Instrumenting the comparison:
   expected is `TypeKind.STRUCT` / `struct_name='Cmd'` / `symbol=None`
   — an UNRESOLVED field annotation carrying the parser's default kind
   for a bare named type — against the real `TypeKind.ENUM` with its
   `EnumSymbol`. Same printed name, same module; a KIND mismatch. A
   STRUCT-typed field of the identical shape compiles and runs, which
   is exactly why only enum-typed fields bite.

Root cause, as far as unit 7 took it: design 84's cross-module embed
splices the frame struct + resume method into the ENTRY AST
(`coro_transform.py:6448-6456`), and the `post_transform=True`
re-entry re-checks that spliced body as entry-module code. The `Cli`
symbol found there has the bare/root identity and
**un-canonicalized field types** — module A's own registration
resolved them, the merged/entry one did not.

The brief's nominated suspect was wrong: the fix is NOT at design
204's `_type_lookup_module`. Teaching `_vis_module_for_source` to
answer from `_module_scope_by_file` for user files (the map
`_home_module_scope` already keeps for the generic path) makes the
lookup module correct — verified — and does NOT fix the bug, because
the failing comparison never depended on it. That change was reverted
unlanded. The fix belongs where an imported module's declarations are
registered into the merged namespace, and it rides the path
`gmgate`/`bootstrap`/`sos` all exercise — hence STOPPED for a ruling
rather than attempted under a suite gate this session could not
honestly clear.

`examples/crossmodule_embed_type_identity.saw` (+ its
`examples/modules/embed_provider.saw`) is the XFAIL pin, carrying the
verified load-bearing legs in its header.

## Gates

Full suite per commit; final gate the tracked battery
(`SAW_PYTHON=<main venv> tools/battery.sh`) — the embed machinery is
in the diff for DF-212b, so `gmgate`, `bootstrap` and `sos` are the
stages that would catch a bad fix, and `irdet --all` polices the
determinism of any new symbol the fix mints.
