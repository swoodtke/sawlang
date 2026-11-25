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

## Git dependencies

A dependency names a `git` URL where a path dependency names a `path`:

```toml
[dependencies]
jsonx = { git = "https://github.com/u/jsonx", version = "^1.2.0" }
```

Blade lists the repository's tags with `git ls-remote --tags`. Only a tag named
`vX.Y.Z` or `X.Y.Z` is a version; any other tag is ignored. It picks the highest
version that satisfies `version`, then clones that tag with `--depth 1` into
`.blade/deps/<name>-<version>`, a directory it keeps ignored by git and reuses
on later builds. A bare `version = "1.2.0"` is an exact pin; ranges are written
with `^`, `~` or `>=`. Without `version`, any tag matches and the highest wins.
`blade add NAME --git URL [--version REQ]` writes the entry.

`Saw.lock` records each package's version, source, location and the commit the
tag pointed at. An application commits it; a library does not. A lock that is
out of date for `[dependencies]` fails the build with a pointer to
`blade update`.

What Blade does not do yet:

- It does not check out the locked commit. A build re-resolves the tags, so a
  tag moved upstream, or a newer one that still satisfies `version`, is what
  the next fresh clone gets, and an existing `.blade/deps/<name>-<version>` is
  reused without a check of its commit (SL-1099).
- It does not take a package from a subdirectory of a repository (SL-1099).
- It does not fetch submodules: the clone is `git clone --depth 1 --branch TAG`
  and nothing more.

## C sources and libraries

A package calls C through `extern "C"` and tells Blade where the C comes from in
a `[native]` table. Blade compiles C sources, hands every package's objects,
archives and libraries to the link, and tracks them for freshness.

```toml
[package]
name = "lz4wrap"
version = "0.1.0"

[native]
c-sources    = ["vendor/lz4/lib/*.c", "c/glue.c"]
include-dirs = ["vendor/lz4/lib"]
defines      = ["LZ4_STATIC_LINKING_ONLY", "NDEBUG"]
libraries    = ["z"]
archives     = ["prebuilt/libextra.a"]

[native.arm64-apple-darwin]
frameworks   = ["Security"]
```

Every value is a list of strings. The keys:

| Key | Meaning |
|---|---|
| `c-sources` | `.c`, `.S` and `.s` files Blade compiles. Any other extension is an error. |
| `include-dirs` | Passed as `-I` to this package's compiles. |
| `defines` | Passed as `-D`: `NAME` or `NAME=VALUE`, NAME a C identifier. A function-like macro is an error. |
| `objects`, `archives` | Prebuilt object files and static archives, linked as given. |
| `libraries` | Library names for `-l`, without `lib` or an extension. A name links however the system ships it, which on macOS is dynamic. |
| `library-paths` | Directories the names are searched in. |
| `frameworks` | Mach-O frameworks, in a `[native.<triple>]` table of an `-apple-` triple only. |

An unknown key is an error that lists the known ones. There are no raw compiler
flags and no `pkg-config`, and a package does not export its include
directories to the packages that depend on it.

**Per-target tables.** `[native.<triple>]` holds the same keys for one target
and appends to the base table. The triple must be one `sawc` knows, or the build
stops naming the table. A host build applies the table of the host's triple,
`blade build --target T` applies `T`'s, and every other table is left alone.

**Paths.** A path is relative to the package that declares it, so a dependency's
files resolve inside the dependency; absolute paths and `..` work. A missing
path, or a directory where a file is expected, stops the build before anything
compiles, naming the package, the key and the value. A `*` in the last segment
of a `c-sources`, `objects` or `archives` path matches the files of that one
directory, sorted, and a pattern that matches nothing is an error. A `*` never
crosses a directory: `**` in the last segment matches as `*` does, and a `*`
anywhere else is an error.

**Propagation and order.** The root's inputs and every resolved dependency's
reach the one link, unlike `no-hidden-alloc` and `max-task-frame`, which only the
root sets. The root comes first, then each package before the packages it
depends on, so an archive follows the objects that need it. Within a package
the compiled C objects come first, then `objects`, then `archives`. A repeated
object, library directory or framework keeps its first occurrence; a repeated
archive or library keeps its last. Blade passes the result to `sawc` as
`--link-object`, `--link-archive`, `--link-library-path`, `--link-library` and
`--link-framework`, and `blade test` links the same inputs into each test
program.

**Compiling.** A hosted build runs the `clang` that `sawc tools` names, as
`-target <triple> -O2 -g -c SRC -o OBJ -MD -MF OBJ.d`, then `-I` and `-D`. The
triple is the one `sawc tools` prints, so the C object agrees with the Saw half
on the deployment target. Objects go under `native/<package>/` in the root's build
directory (`.build/host` for a host build), never inside a dependency. Compiles run side by side, at most three quarters of
the processors (`SAW_GATE_JOBS` lowers it), and after a failure no new compile
starts. Blade reuses an object when its key matches: clang's path and version,
the arguments, the source, and every file the depfile lists, system headers
included. So a header edit recompiles only the objects that include it, and a
change to `defines` recompiles the package.

**Freshness.** `blade build` hashes each object's key and the bytes of every
prebuilt object and archive, so a changed `.o` or `.a` rebuilds. The contents of a
named system library are not tracked: `--force` rebuilds.

**Images.** An `[sos]` package gets the same plan. Its C sources compile with
the image's flags (the `[sos]` native units' flags, so a `+windowed` Xtensa
image gets C built for the windowed ABI), then `ld.lld` links
`SAW.o`, the `[sos]` native units, each package's files in plan order, `-L`
and `-l`. A `[native]` source for a bare-metal triple with no `[sos]` table is an
error. An image links no framework. For aarch64 both halves are compiled without
NEON or floating point (`-neon,-fp-armv8`), so no C code touches the FP/SIMD
registers; the features reach the compiler and not the assembler, so a `.S`
unit that saves FP state still assembles.

**Debug info.** A hosted build keeps `-g`, and sawc's link leaves a `.dSYM` that
holds the C compile units beside the Saw ones. Its debug map names the objects
relative to the output directory, so a separate `dsymutil` run from another
directory cannot find them: run it in the output directory, or use the one the
link made.

**Linux.** `tools/lima/sawlang-linux.yaml` pins `zlib1g-dev` for both
architectures, which the run lane's `--link-library z` case needs. A VM
provisioned before the pin needs reprovisioning.
