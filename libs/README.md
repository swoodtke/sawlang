# Library packages

`semver`, `toml` and `imgformat` are Saw packages built by `sawc`.

Blade depends on all three (`make blade`), and the sawos kernel compiles
`imgformat` through `--module-path`. Each package's tests run with Blade:

```bash
make blade
cd libs/toml && ../../bin/blade test
```

`tools/blade_lane.py` runs the tests of all three.
