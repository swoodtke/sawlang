# Library packages

`semver`, `toml`, `imgformat` and `lz4` are Saw packages built by `sawc`.

Blade depends on `semver`, `toml` and `imgformat` (`make blade`), and the sawos
kernel compiles `imgformat` through `--module-path`. `lz4` is a vendored C
codec behind a safe Saw API and shows Blade's `[native]` inputs (see its
README). Each package's tests run with Blade:

```bash
make blade
cd libs/toml && ../../bin/blade test
```

`tools/blade_lane.py` runs the tests of all four.
