# Design 213 — closures: local `return` typing + the embed identity leak

**Status: AUTHORED Aug 12, awaiting dispatch. Fixes the two compiler
bugs design 212's sweep surfaced (DF-212a, DF-212b — filed with full
bisection notes in `designs/todo.md`, "Design 212 findings"). One
family: both are places the typechecker/embed machinery fails to
account for a closure literal in the tree.**

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

## Gates

Full suite per commit; final gate the tracked battery
(`SAW_PYTHON=<main venv> tools/battery.sh`) — the embed machinery is
in the diff for DF-212b, so `gmgate`, `bootstrap` and `sos` are the
stages that would catch a bad fix, and `irdet --all` polices the
determinism of any new symbol the fix mints.
