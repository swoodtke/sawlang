# The freestanding suite

These programs name the compiler's freestanding features directly
(`--freestanding`, `--no-hidden-alloc`, `--runtime`, cross-target codegen,
fixed-address linking) and run under QEMU. `sawc` builds them, and
`tools/freestanding_runner.py` is the harness: it compiles each case with the
three modules here (`rt` is `fsrt`, the runtime provider; `core` is `fscore`;
`data` is `fsdata`) through `--module-path`, links it with `hal/<arch>/boot.S`,
`hal/support.c` and `hal/<arch>/link.ld`, boots it, and matches its console
transcript and exit status. The refusal cases stop at the compile and match
sawc's diagnostic.

```
tools/freestanding_runner.py                # every architecture that is on
tools/freestanding_runner.py hello          # named cases
tools/freestanding_runner.py --tools        # the prerequisite decision alone
```

It needs QEMU (`qemu-system-aarch64`), `ld.lld`, and a clang that compiles for
the target (the one sawc's own record beside the stages names). When one of
them is known absent the suite skips and passes, saying which; when their
presence cannot be determined it fails. It is the battery's `freestanding`
stage and a part of the per-patch gate.

arm64 runs today. The riscv32 rows are off until sawc builds a riscv32 object
(SL-865). A case blocked by a sawc gap is marked `due` in the runner, citing
the issue that owns the gap, and must fail with that gap's diagnostic until
the gap closes.

`bladepkg/` is the Blade case (`blade build --target T`), which is not run:
Blade is frozen in v0.18.0's language until its port (SL-661).
