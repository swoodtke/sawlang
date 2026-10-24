# bench (frozen)

The warehouse benchmark (`warehouse/`) and its driver (`src/main.saw`) are
frozen in v0.18.0's language. They were the battery's `bench` stage, which
built both with Stage 0 and gated nothing; that stage left the battery with
Stage 0 (SL-666). Their sources are byte-identical to v0.18.0's, and the
`frozen` step of `compiler/tests/run.py` holds this directory to the tree
`tools/frozen_trees.tsv` records.

To run it as it ran, use v0.18.0's compiler through `bin/sawc0`
(`SAWLANG_V0_ROOT=/path/to/sawlang-v0.18.0`), or that checkout's own
`tools/battery.sh bench`.
