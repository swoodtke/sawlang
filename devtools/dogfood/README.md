# Dogfood programs (frozen)

The programs under `programs/` were written from the specs under `specs/` by
the naive-implementer instrument (design 203), and built with Stage 0 as the
language stood when each was written. They are kept as a record. Most of them
no longer build with `sawc`, and some no longer build with v0.18.0's compiler
either; nothing in sawlang builds or gates them. The `frozen` step of
`compiler/tests/run.py` holds this directory to the tree
`tools/frozen_trees.tsv` records.
