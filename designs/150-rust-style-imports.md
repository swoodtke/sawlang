# Design 150 — Rust-style imports: delete the std bare-exposure special case

**Status: APPROVED (user, Aug 6). Queued after 148/149 + the P0 pair,
SOLO (tree-wide migration), before the [138 ∥ M1-adoption] finale.**

## Decision [user]

`import std.file` grants **qualified access only** (`file.File`,
`task.yield_now()`); `import std.file.*` exposes every public name
**bare**; `import std.file.{A, B as C}` stays selective-bare. Rust's
model, stated by the user directly: "i prefer rust's style file.File if
import std.file and just File if importing std.file.*".

This is a *deletion*, not a new mechanism. User modules already behave
exactly this way (design 53): a bare `import mypkg.io` registers a
ModuleSymbol for qualified access only (`typechecker/core.py` ~1226),
`.*` globs bare, braces select bare. The only deviation is design 82
Part B's `_process_std_import`, which bare-exposes whole-module std
imports and supports neither `.*` nor qualified access. Design 150
makes std go through the same three forms as everyone else.

## Semantics (pinned)

1. **Whole-module** `import std.X` (and `import pkg.X`): binds the
   qualifier `X` (last path segment; `as Y` overrides) to the module.
   Access is `X.Name` / `X.func()` — no bare exposure. Works in every
   position a name can appear: type annotations (`let f: file.File`),
   call heads, static-method chains (`time.Instant.now()`), generic
   arguments, pattern heads, extension receivers. The user-module
   ModuleSymbol machinery is the substrate; any position it does not
   already handle is fixed here (record DF-150x findings).
2. **Glob** `import std.X.*`: every public name of the module enters
   scope bare — the explicit opt-in that replaces today's implicit
   bare exposure. Glob is no longer spec-"discouraged" wholesale: it
   is the legitimate "give me this module's vocabulary" form; idiom
   guidance (skill) still prefers braces in library code.
3. **Selective** `import std.X.{A, B as C}`: unchanged. Uniform with
   user modules, the selective form ALSO binds the `X` qualifier for
   reaching non-imported names (core.py ~1218 already does this for
   user modules).
4. **Qualifier bindings are weak** [pin, ratified in discussion]: a
   local, param, or field named `data`/`net`/`path`/`time` may shadow
   a module qualifier without tripping the shadowing-error rule; value
   bindings win at resolution (order: local scopes → module-level
   declarations → imported bare names → qualifiers last). The shadow
   is lexical: outside the declaring scope, `task.` reaches the module
   again. Rationale: std leaves are extremely common locals — this was
   design 82's original reason for not creating the alias. Applies
   uniformly to user-module qualifiers (verify current behavior;
   normalize if it differs). Diagnostic contract: when member lookup
   fails on a value that shadows a qualifier, the error names the
   shadowing declaration and offers the three outs (rename,
   `import ... as`, selective import).
4b. **First compiler warning + the `-W` surface [user, Aug 6]**: sawc
   gains `-W <name>` (repeatable) and `-W all`; warnings are OFF by
   default, never affect the exit code (no `-Werror` yet). The
   reporter's warning path exists (`errors.py`) but has zero call
   sites — this brief adds the first category, `shadowed-qualifier`:
   emitted at the DECLARATION of a name that shadows a visible module
   qualifier, noting qualified access is unavailable in that scope.
   The use-site error above is unconditional; the warning is the
   opt-in early flag.
5. **Qualifier collisions**: two imports binding the same qualifier is
   an import-site error naming both paths; fixed with `as`.
6. **Extension/conformance visibility (142) unchanged**: ANY import
   form — qualified, glob, selective — makes the module a direct
   import, activating its extensions and conformances. Choosing
   qualified access must not silently lose extension methods.
7. **Prelude untouched**: the curated core stays bare with no import.
   `import std.vector` now binds a `vector` qualifier like any other
   module — harmless, uniform.

## Migration

Mechanical, semantics-preserving: every whole-module std import in the
tree (`examples/`, `blade/`, `libs/`, `sos/`, `selfhost/`, std-internal
cross-imports) is rewritten `import std.X` → `import std.X.*`. No idiom
churn in this brief — moving files to braces/qualified is future
polish, not migration. New-code idiom guidance goes to the skill.

## Docs

Spec §8 Imports rewritten around the three uniform forms (the
"Python-style semantics" framing and the std-forms caveat both go);
saw-lang skill import section + idiom note; CLAUDE.md digest line.
Design 138 (all-sources sweep, queued after) verifies consistency.

## Tests / gates

Qualified access in every syntactic position; std glob; selective +
qualifier combo; `as` on whole-module std; qualifier-collision error;
weak-shadowing probe (local named `data` beside `import std.data`) —
both the failing-member-lookup diagnostic (names the shadowing decl +
three outs) and the `-W shadowed-qualifier` emission (and its silence
without the flag); negative: bare use under qualified-only import
errors with a did-you-mean naming the three forms. Full battery: suite
(zero xfails), lexdiff, astdiff, irdet --all (venv), bootstrap,
sos_runner.
