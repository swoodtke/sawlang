# Library packages (frozen)

`semver`, `toml` and `imgformat` are frozen in v0.18.0's language until their
port to `sawc` (SL-661). Nothing in sawlang builds or gates them, and their
sources are byte-identical to v0.18.0's. The `frozen` step of
`compiler/tests/run.py` holds this directory to the tree
`tools/frozen_trees.tsv` records, so an edit here fails the per-patch gate.

Blade depends on all three (`make blade`), and the sawos kernel compiles
`imgformat` through `--module-path`. Each package's tests run with Blade, which
drives v0.18.0's compiler through `bin/sawc0` when `SAWC` is unset:

```bash
export SAWLANG_V0_ROOT=/path/to/sawlang-v0.18.0
make blade
cd libs/toml && ../../bin/blade test
```
