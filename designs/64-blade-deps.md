# Design 64 — Blade for real: dependencies, semver, lock, git, incremental (DECIDED Jul 30)

**Ruling (user):** App-1 becomes a real package manager. Decisions:
resolver is **max-satisfying, one version per package** (collect all
requirements; highest version satisfying all; hard error naming both
requirers on conflict — no duplicate majors, no backtracking); git
checkouts live **project-local in `.blade/deps/`** (gitignored;
global-cache migration is a later decision); library layout is
**`src/lib.saw`** (`import foo` → dep foo's src/lib.saw, `import
foo.bar` → its src/bar.saw); a bare version string is an **EXACT pin**
(`foo = "1.2.3"` means =1.2.3 — ranges require explicit operators).
Registry: NONE in v1 (path + git sources only).

## B0 — compiler enabler: module search paths (do FIRST, tiny)
sawc resolves imports file-relative + std only. Add a repeatable
`--module-path <name>=<dir>` flag (explicit name→dir mapping, not a
scan): `import foo` resolves to `<dir>/lib.saw`, `import foo.bar` to
`<dir>/bar.saw`, for each mapped name. Precedence: exact std > mapped
packages > file-relative (a mapped name shadowing a local module file
is an error, not a silent pick). Visibility/module semantics unchanged
(the mapped root is just a module file). Tests at the compiler level
(two fixture dirs). This is the only sawc change in the brief.

## B1 — manifest schema: [dependencies]
```toml
[package]
name = "app"
version = "0.1.0"

[dependencies]
mathx = { path = "../mathx" }
jsonx = { git = "https://github.com/u/jsonx", version = "1.2.0" }
tiny  = "0.3.1"          # bare = exact pin; source defaults to... ERROR in v1:
                         # a bare dep with no path/git has no source — reject
                         # with "no registry yet; specify path or git".
```
- Version-requirement grammar (explicit operators; bare = exact):
  `"1.2.3"` exact; `"^1.2.3"` compatible-within-major (0.x: within
  minor); `"~1.2.3"` patch-level; `">=1.2.3"` at-least. Compound
  requirements DEFERRED.
- TOML parser extension: inline tables `{ k = "v", ... }` (one level)
  — blade/src/toml.saw grows this; keep it minimal.
- Path deps: relative to the DEPENDING package's manifest dir;
  version read from the dep's own manifest (a `version` field on a
  path dep, if present, is validated against it).
- Transitive: each dep's own Saw.toml [dependencies] is read and
  resolved into the same graph.

## B2 — semver PACKAGE (pure Saw; the Comparable dogfood)
**Extracted as a real library package** (see B8): `libs/semver/` with
its own Saw.toml (`name = "semver"`) and `src/lib.saw`:
`struct Version { major, minor, patch: Int }`
(pre-release/build-metadata tags DEFERRED — parse-reject with a clear
error), parse via String.to_int/split, Equatable + Comparable +
Printable; `struct VersionReq` (Exact/Caret/Tilde/AtLeast + Version),
parse + `matches(&self, v: Version) -> Bool` + Printable. Unit-style
blade tests (blade/tests/) for parse/compare/match edges (0.x caret
rule included).

## B3 — resolver
- Build the full transitive graph from the root manifest (path deps
  read in place; git deps must be FETCHED to read their manifest —
  see B5; fetch-on-resolve).
- Per package name: collect (requirement, requirer) pairs. Candidate
  versions: for a git dep, the versions available are the repo's
  TAGS matching `v*`/semver (tag → version); for a path dep, exactly
  its manifest version. Pick the HIGHEST candidate satisfying ALL
  requirements; none → error listing every (requirement, requirer).
  Two different SOURCES for one name (path vs git, or two different
  git urls) → error (no source unification in v1).
- Cycles: path-dep cycles are an error (name the cycle). Self-dep
  error.
- Output: a resolution table (name → version, source, rev) feeding
  B4/B6.

## B4 — Saw.lock
- TOML, written next to Saw.toml. Deterministic: packages sorted by
  name (Map.keys + sort — the design-54 discipline).
- Per package: name, version, source (`path = "..."` or `git = url`),
  and for git: `rev = "<full commit sha>"` (the commit the resolved
  tag points at).
- `blade build`: lock present + satisfiable → use EXACTLY the locked
  versions/revs (no re-resolution; error if a manifest requirement now
  contradicts the lock, telling the user to `blade update`). No lock →
  resolve, write lock.
- `blade update`: re-resolve fresh, rewrite lock. `blade update <name>`
  DEFERRED.
- Lock drift (deps edited in manifest): detected via a manifest-deps
  hash stored in the lock; mismatch → instruct `blade update` (build
  does NOT silently re-resolve).

## B5 — git integration (CLI via std/process; no bindings)
- `.blade/deps/<name>-<version>/` checkout layout; `.blade/` is
  created gitignored (blade writes .blade/.gitignore containing `*`).
- Fetch: `git clone --depth 1 --branch <tag> <url> <dir>` for a known
  tag; resolving available tags uses `git ls-remote --tags <url>`
  (parse refs/tags/vX.Y.Z → versions; peeled `^{}` entries preferred
  for rev). Locked builds fetch the exact rev (`git fetch <url> <rev>`
  + checkout) — depth-1 when possible.
- Wait-status discipline: any git failure (network, missing tag) is a
  clean BladeError with the git stderr surfaced (design 59's decoded
  exit statuses).
- Offline: if the checkout for the locked rev already exists, no
  network is touched (this is the incremental-fetch story).

## B6 — build integration + incremental
- Build compiles the root with `--module-path <name>=<checkout>/src`
  per resolved dep (B0). Dep sources are compiled INTO the one
  program (no separate compilation — it does not exist in sawc;
  documented honestly).
- Incremental v1 = build avoidance: hash (all reachable .saw sources
  incl. dep checkouts + Saw.toml + Saw.lock + sawc version string) →
  stored in .blade/build-hash; match → skip compile ("up to date");
  mismatch → rebuild. `blade build --force` bypasses.
- `blade test` uses the same dep flags for tests/*.saw.

## B7 — CLI polish
- `blade add <name> --path <dir>` / `blade add <name> --git <url>
  [--version <req>]`: edits Saw.toml (append to [dependencies]),
  runs resolve+lock.
- `blade test` prints per-test + total timing via std.time (Duration
  Printable).
- `blade tree`: print the resolved graph (name version (source)) —
  small, great for debugging the resolver.

## B8 — self-hosting dogfood: Blade builds and tests Blade (DECIDED)
The dep machinery must be PERMANENTLY exercised by Blade's own build:
- **Extract real library packages**: `libs/semver/` (B2) and
  `libs/toml/` (move blade/src/toml.saw → libs/toml/src/lib.saw,
  imports updated). Blade's own Saw.toml gains
  `[dependencies] semver = { path = "../libs/semver" },
  toml = { path = "../libs/toml" }` — every Blade build now runs the
  resolver, honors/writes Saw.lock (COMMITTED to the repo), and uses
  B0 module paths. The dep features cannot rot without breaking
  Blade's own build.
- **Bootstrap loop** (scripted as a blade test or Makefile target
  `blade-bootstrap`; must pass before the brief is done):
  1. stage0 = sawc builds Blade directly (bootstrap entry, kept).
  2. `stage0 build` → builds Blade through its own
     resolve/lock/module-path/incremental pipeline → stage1.
  3. `stage1 test` → Blade's full test suite passes.
  4. A second `stage1 build` reports up-to-date (incremental hash
     dogfood); `stage1 build --force` rebuilds → stage2; `stage2
     test` passes (closes the loop).
- libs/ packages get their own tests/ (run via `blade test` in each
  package dir — the tester works from any package root).

## Testing (blade/tests/ + fixtures)
- `blade/tests/fixtures/`: small path-dep packages (mathx, a
  transitive chain app→a→b, a conflict pair, a cycle pair).
- End-to-end blade tests: path-dep build runs; transitive resolve;
  conflict error names both requirers; cycle error; lock written
  sorted + stable across two runs (byte-identical); lock honored
  (edit fixture manifest → build errors, update re-resolves);
  build-avoidance (second build prints up-to-date; --force rebuilds);
  semver unit tests. GIT tests: construct a LOCAL git repo in
  .build/scratch (git init + tag in a fixture copy; file:// URL) so
  no network is needed; ls-remote/clone/locked-rev paths covered.
  Compiler tests for B0 module paths.
- Blade's own build + full compiler suite stay green (blade is also a
  compiler-suite consumer via blade tests — keep both green per
  commit).

## Items (suggested commit units)
1. B0 compiler module paths + tests.
2. B1 manifest deps + TOML inline tables + tests.
3. B2 semver + tests.
4. B3 resolver (path-only first) + fixtures + tests.
5. B5 git fetch/ls-remote + local-repo tests; B3 git-candidate wiring.
6. B4 lock write/honor/update + tests.
7. B6 build integration + incremental + tests.
8. B7 CLI (add/tree/test-timing) + docs (README Blade section,
   TESTING.md app-level section, tracker: design 64 landed, App-1
   milestone status).

## Hazards
- The resolver fetches to read manifests (git deps) — keep resolve
  I/O behind a seam so fixture tests can use local repos exclusively;
  NO network in any test.
- Lock determinism is a hard requirement (byte-identical across
  runs) — sorted sections, no timestamps in the file.
- .blade/deps checkouts are inputs to the build hash — hash file
  CONTENT, not mtimes.
- toml.saw inline-table growth must not regress existing manifest
  parsing (blade tests are the oracle).
- Dogfood findings discipline: any language pain hit while writing
  this (DF-style) gets RECORDED in the tracker, not worked around
  silently.
Full compiler suite + all blade tests per commit; zero xfails.
