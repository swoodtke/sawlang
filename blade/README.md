# Blade (frozen)

Blade, the package manager, is frozen in v0.18.0's language until its port to
`sawc` (SL-661). Nothing in sawlang builds or gates it, and its sources are
byte-identical to v0.18.0's. The `frozen` step of `compiler/tests/run.py` holds
this directory to the tree `tools/frozen_trees.tsv` records, so an edit here
fails the per-patch gate.

It builds with v0.18.0's compiler, `sawc0`, which `bin/sawc0` reaches through
the v0 checkout (`SAWLANG_V0_ROOT`, else v0.18.0 fetched and cached):

```bash
SAWLANG_V0_ROOT=/path/to/sawlang-v0.18.0 make blade    # -> .build/blade
```

`bin/blade test` drives `sawc0` the same way when `SAWC` is unset. The
self-hosting bootstrap is the tag's own `tools/blade_bootstrap.py`, run in the
v0.18.0 checkout.
