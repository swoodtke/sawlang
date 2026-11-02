# Blade

Blade is the Saw package manager, written in Saw. It resolves a package's
dependencies, writes `Saw.lock`, and drives `sawc` to build and test the
package and the libraries under `libs/`.

It builds with `sawc`:

```bash
make blade    # -> .build/blade
```

`bin/blade` runs that binary, with `SAWC` set to the `bin/sawc` beside it
unless `SAWC` is already set. Blade builds itself the same way:

```bash
cd blade && ../bin/blade build
../bin/blade test
```

`tools/blade_lane.py` runs these steps, plus `blade new` and `blade run` in a
temporary directory, and the per-patch gate and the battery both run it.
