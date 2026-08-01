# Design 82 — Close the std visibility gap: per-file std modules + prelude discipline (DECIDED Jul 31 / prelude added Aug 1)

**Ruling (user):** retire design 80's std-as-one-module deviation —
it invites accidental (or lazy) invariant abuse by future std code.
std files become ordinary modules to EACH OTHER; genuinely shared
internals are marked **`public(package)`** (std is the package), so
intentional sharing is explicit and `Vector.length` becomes invisible
even to channel.saw. **PLUS (Aug 1): prelude discipline** — shrink the
auto-visible prelude to a curated core; everything else in std
requires an explicit `import std.X` (fixes user↔std name collisions
like the design-84 `IoError` clash without churning core ergonomics).

## Prelude discipline (Part B — the curated set)
- **PRELUDE (auto-visible, no import)** — the core vocabulary only:
  * primitives: `Int`, `UInt`, `Int8`…`Int64`, `UInt8`…`UInt64`,
    `Float`, `Bool`, `String`, `Void`, `Never`;
  * core containers: `Vector`, `Map`, `Set`;
  * core wrappers: `Optional` (the `T?` sugar's type), `Result`,
    `Box`, `Arc`, `GlobalAllocator`/`Allocator`;
  * core traits: the Copy family (`Copy`/`ImplicitCopy`/`ExplicitCopy`/
    `NoCopy`), `Deinit`, `Iterator`, `Equatable`, `Comparable`,
    `Hashable`, `Printable`, `Error`, `Send`, `Sync`;
  * the builtins `print`/`panic`/`assert`/`sizeof`/`alignof`/
    `static_assert` + the concurrency primitives already global
    (`TaskGroup`, `yield_now`, `sleep`, `spawn`, `cancelled`) — keep
    as-is unless the sweep shows a clean reason to move one.
- **IMPORT-REQUIRED (removed from the prelude)**: `File`, `Directory`,
  `Path`, `Data`, `Channel`, `Mutex`, `StringBuilder`?(decide — it's
  common; lean keep-in-prelude, report), `Duration`, `Instant`,
  `IoError`, `Utf8Error`, and the whole `net` surface
  (`TcpListener`/`TcpStream`) + `env`/`process`/`time`/`file`/
  `directory`/`path` module contents. Users write
  `import std.net.{TcpListener}` (or `net.TcpListener`).
- Mechanism: the prelude becomes an explicit ALLOWLIST (not "all of
  std auto-merged"). Non-prelude std types stay compiler-known for
  codegen but are NOT injected into a user module's namespace without
  import. This composes with Part A: once std files import their own
  deps explicitly (per-file modules), the prelude allowlist is the
  only auto-visible set.
- Migration: std files `import` the std deps they use (map.saw imports
  hasher, etc.); blade + libs + every example/test that used a now-
  non-prelude type gains the import; the suite/blade/bootstrap catch
  every miss. A user type named `IoError` no longer collides.
- Tests: a user module defining its own `IoError`/`File` compiles
  (no prelude clash); using `TcpStream` without import = clean
  "unknown type, did you mean `import std.net`?" error; a prelude
  core type (`Vector`) still works bare.

## Scope
1. Flip the visibility module-identity for std from single-module to
   per-file (the design-80 machinery already keys on source file —
   remove the std coalescing special case; ACCESS checks only,
   codegen/compiler-known-ness untouched).
2. Sweep the ~182 std-internal cross-references design 80 counted:
   most become `public`/`public(package)` on the API they already
   were; true internals that another std file touches get
   `public(package)` ONLY if the sharing is legitimate — otherwise
   restructure the toucher to go through the owning module's API
   (report each restructure; that list is the abuse audit).
3. Synthesized-access provenance exemption unchanged.
4. Tests: a std-internal privacy probe (compile a scratch std-like
   module pair? — if std privacy isn't harness-expressible, assert
   via the compiler's own suite staying green + a tracker note on
   the enforcement path), plus the existing visibility family.
5. Docs: spec note (std has no special visibility status; the prelude
   allowlist documented; import-required std modules); saw-lang skill
   (imports section — what's prelude vs `import std.X`); CLAUDE.md
   digest; tracker (design 80 deviation retired, prelude discipline +
   design 82 landed; the design-84 `IoError`-collision item closed).

## Commit order
Part A (per-file std visibility) and Part B (prelude discipline) are
separable — land Part A first (green), then Part B (the prelude
allowlist + import migration) as its own unit(s). Part B is the wider
churn (every non-prelude std user gains an import).

Bars: full suite (baseline = post-88) + blade/libs + bootstrap green
per commit; zero xfails. Mechanical but wide — the suite is the
oracle. Standing policy; interruption-safe commits; saw-lang skill
self-review.
