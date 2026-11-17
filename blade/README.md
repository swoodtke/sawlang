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

## Refusing hidden allocations

`sawc --no-hidden-alloc` refuses the allocations the compiler inserts that no
source construct names: string interpolation, an escaping closure's captured
environment, and single-argument `print` of a user type. A package opts in with
a boolean in its `[package]` table:

```toml
[package]
name = "driver"
version = "0.1.0"
no-hidden-alloc = true
```

Blade then passes `--no-hidden-alloc` to every `sawc` it runs for a build of
that package: `blade build`, `blade run`, an image build (`[sos]`), and each
test program `blade test` compiles. Only the package whose directory Blade is
run in counts. A dependency's key does not change the builds of the packages
that depend on it; it applies when that package is itself the one being built
or tested. An absent key is false, any other type than a boolean is an error,
and changing the key rebuilds.
