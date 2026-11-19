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

## Limiting a task's frame

`sawc --max-task-frame=SIZE` sets the most bytes a spawned task's frame may
take (1MiB hosted and 4KiB freestanding by default); a task over it is a compile
error naming its largest slots. A package sets it with a string in its
`[package]` table, in the flag's spelling: bytes, or a whole number then `KiB`,
`MiB` or `GiB`.

```toml
[package]
name = "driver"
version = "0.1.0"
max-task-frame = "64KiB"
```

Blade passes `--max-task-frame=64KiB` to every `sawc` it runs for a build of
that package, as it does `no-hidden-alloc`: `blade build`, `blade run`, an image
build and each test program. Only the package whose directory Blade is run in
counts, and its limit covers every task in the image, its dependencies' too. A
dependency's key applies when that package is itself the one being built or
tested. Blade refuses a value that is not a string of that shape, naming the key;
sawc judges the size (zero, or past an `Int`). Changing the key rebuilds.
