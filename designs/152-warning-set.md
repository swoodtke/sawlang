# Design 152 — the first `-W` warning set

**Status: APPROVED (user, Aug 6), scheduled AFTER the current queue
(post-M1b, head of the demand-driven backlog). Depends on design 150's
`-W <name>` / `-W all` surface (off by default, never affects exit
code, no `-Werror`).**

## Principle

The `-W` namespace is for things that are *legitimately sometimes
fine*. Real hazards keep becoming errors or design changes through the
DF pipeline (shadowing, silent closure statements, no-op accessors,
Result discard in 151 — all errors). A warning that fires on the
chosen idiom is noise; each category below names its noise control.

## Categories

1. **`unused-import`** — an import none of whose effects are used: no
   qualifier use, no bare/selective name use, AND no extension method
   or conformance from that module applied (design 142 makes imports
   carry extension visibility, so a naive "name never mentioned" check
   would flag load-bearing imports; the extension check is the hard
   part and the reason this postdates 150's qualified model).
2. **`task-frame-size=N`** — the compiler knows every coroutine
   frame's exact size at compile time; warn when a task's frame
   exceeds N bytes (flag takes the threshold; pick a default ~16KB
   when bare). Audience: kernel/embedded (the primary targets), where
   a deep embed chain or large locals spanning a suspend silently
   inflates every spawn. Gives visibility now while frame-overlay
   sizing sits on the backlog.
3. **`hidden-alloc`** — advisory twin of 135's `--no-hidden-alloc`:
   identical detection (already landed), warn instead of reject, so
   hosted code can watch allocation creep without adopting the hard
   mode. Mutually exclusive with the flag (the flag's error
   supersedes).
4. **`unused-variable`** — a local/param never read; the `_` name (or
   `_`-prefix) is the out. Unused private functions/fields are NOT in
   scope here (separate dead-code category, only if demand appears).
5. **`window-promotion`** — audit aid for the DF-146b docs callout:
   fires where a `borrows` window promotes to mutable **through a
   `&self` method** — the inconsistency the user asked to document
   loudly ("decorating a function with borrows can promote to
   mutability"). Scoped to `&self`-method promotions ONLY: plain
   `v[i] += 1` element promotions are idiomatic and everywhere, and
   flagging them would be noise.

## Not included (considered, rejected)

Sync-function starvation (design 127 deliberately exempts sync callees
as the speed escape hatch — warning on it nags the chosen idiom);
float `==`; unreachable-code (nothing has bitten us). Result discard
is an ERROR (151), not a category here.

## Tests / gates

Per category: fires on the footgun, silent without its flag, silent
on the documented out (`_` name, `let _ =`, extension-only import,
sub-threshold frame). `-W all` enables all five. Full battery: suite
(zero xfails), lexdiff, astdiff, irdet --all (venv), bootstrap,
sos_runner.
