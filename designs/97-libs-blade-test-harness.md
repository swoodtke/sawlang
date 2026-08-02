# Design 97 — libs/semver + libs/toml `blade test` harness fix (queued Aug 2)

Recurring flag (designs 84/92/88 all noted it): the `blade test` suites
for `libs/semver` and `libs/toml` FAIL on a clean tree, but each test
compiles + runs GREEN when invoked standalone with the in-tree compiler.
So the LIBS are fine — the `blade test` INVOCATION for them is
misconfigured. Net effect: the lib test suites are NOT actually
validated in the bootstrap (a coverage gap, not a correctness bug),
and they add noise to every "bars" check ("libs fail on clean tree —
pre-existing").

## Investigate + fix
1. Characterize precisely: run `blade test` in `libs/semver` and
   `libs/toml` from a clean tree; capture the actual error. Prior notes
   say the tests `import src.lib.*` and that `blade test` needs
   `SAWC="<venv-python> <repo>/sawc/sawc.py"` set (else it silently
   uses a stale default `sawc` on PATH → all fail). Determine the real
   cause: (a) SAWC env not set/propagated, (b) the module-path for
   `import <libname>` (the package's own lib.saw) not wired for a
   package testing ITSELF, or (c) the `src.lib` import path is wrong.
2. Fix so `blade test` in a library package works from a clean tree
   with no manual env — either blade auto-derives the compiler (the
   bootstrap already sets SAWC for the main build; extend to the lib
   test runs) or the lib test invocation is corrected. A package
   testing itself should resolve its own `import <self>` (lib.saw)
   without a hand-set module-path.
3. Wire the lib test suites into `tools/blade_bootstrap.py` (or the
   bars) so they RUN and are green as part of the standard check —
   closing the coverage gap and removing the recurring "pre-existing"
   caveat.
4. Docs/tracker: design 97 landed; the recurring libs-blade-test flag
   closed; note the fix in TESTING.md if the invocation changed.

Bars: full compiler suite + blade tests + libs `blade test` (now
actually green) + bootstrap green per commit; zero xfails. Standing
policy; foreground; interruption-safe.
