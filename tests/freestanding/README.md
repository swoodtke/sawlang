# The freestanding suite (frozen)

These programs name the compiler's freestanding features directly
(`--freestanding`, `--no-hidden-alloc`, `--runtime-provider`, cross-target
codegen, fixed-address linking) and ran under QEMU on riscv32 and arm64. They
are frozen in v0.18.0's language until their port to `sawc` (SL-661). Nothing
in sawlang builds or gates them, and their sources are byte-identical to
v0.18.0's. The `frozen` step of `compiler/tests/run.py` holds this directory to
the tree `tools/frozen_trees.tsv` records, so an edit here fails the per-patch
gate.

They do not pass at v0.18.0 either: the runtime ABI changed under them in
v0.16.0 (`__saw_rt_write` returns a status; `__saw_rt_write_line`, the output
lock pair and `executable_path(status_out)` are new), and `rt/src/lib.saw` and
the seam cases still declare the older signatures. The harness is the tag's own
`tools/freestanding_runner.py`, run in a v0.18.0 checkout.

`sawc` cannot build a freestanding object yet (SL-865).
