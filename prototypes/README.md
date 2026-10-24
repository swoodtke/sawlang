# Prototypes (frozen)

`minivm/` (the paused mini-VM compiler) and `parser/` (the prototype parser
that seeded `compiler/parse/`) are frozen in v0.18.0's language. Both were
built with Stage 0, and their differential tests drive it (`--sawc` defaults to
`sawc/sawc.py` in the checkout). Nothing in sawlang builds or gates them, and
the `frozen` step of `compiler/tests/run.py` holds this directory to the tree
`tools/frozen_trees.tsv` records.

To build or test one as it was, use v0.18.0's compiler: `bin/sawc0` reaches it
through `SAWLANG_V0_ROOT=/path/to/sawlang-v0.18.0`, and the tests take
`--sawc $SAWLANG_V0_ROOT/sawc/sawc.py`.
