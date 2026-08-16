# Design 229 — export control: imports stop being silently public

**Status: SKETCH for discussion (Aug 16) — a language-surface change; the
user rules the default and the spelling. Motivated by the E/W unit-3
finding: Saw's re-export is INDISCRIMINATE — everything a module imports
is reachable through it (probe-proven: an importer of B names a type B
only imported from A, bare and qualified, same identity). The SOS vDSO
discipline (op numbers are not API) is therefore held by documentation,
not by a wall — `sosabi` is transitively on every process's module path.**

## The inconsistency this fixes

Saw is private-by-default EVERYWHERE except imports: fields (design 80),
extension methods (80), std file modules (82), conformance/extension
scoping (142) — all default-closed, opt-in public. Imports are the one
surface that leaks by default. The E/W convention paragraph ("the
discipline is what userspace is told to write") is the honest statement
of the gap.

## Prior art — the consensus is total

| Language | Default | Re-export spelling |
|---|---|---|
| Rust | imports PRIVATE | `pub use path::Item` (the facade idiom; `pub(crate) use` scopes it) |
| Swift | imports not re-exported | `@_exported import` (unofficial); SE-0409 adds `internal import`/`private import` to keep a dependency OUT of your API |
| Haskell | exports = declared names only | module export list: `module M (X, module Y)` — explicit, fine-grained |
| OCaml/SML | signature-controlled | the `.mli`/signature HIDES by omission — the strongest form |
| C++20 modules | `import` does not propagate | `export import M` |
| ES modules | imports private | `export { x } from 'y'` |
| Zig | decls private | `pub const x = @import(...)` — re-export by public binding |
| Go | no re-export AT ALL | plus the `internal/` PATH WALL: packages under internal/ importable only within the parent subtree |

Every modern module system makes re-export an EXPLICIT act. Two distinct
mechanisms appear: (1) per-name re-export visibility (Rust/Haskell/ES/
Zig/C++), and (2) Go's path-based embargo (`internal/`) — orthogonal and
composable (Rust has both: pub use + the unnameable-crate pattern).

## The proposal space

- **A (recommended): imports become private by default; re-export is
  explicit, spelled with Saw's existing visibility word — `public
  import std.x.{Y}` / `public import std.x` (whole-module facade).**
  Design 80's doctrine extended to its last surface. A non-public
  import binds names for THIS module's use only (exactly today's
  design-150 semantics minus the leak); `public import` adds the
  imported names to this module's own surface. Qualified reachability
  through a NON-public import (`sos.EventMode` from outside) closes
  too — reachability = the visibility chain, the Rust rule.
- **B: a Go-style path wall** (`internal/` or a `[package] internal =
  true` Blade marker) — coarser, no language change, but answers only
  the package case, not the std-facade case. Could COMPOSE with A
  later; not a substitute.
- **C: status quo, documented** — rejected by the motivating finding
  unless the user prefers deferral.

## Consequences under A

- The SOS wall becomes real: `sos` writes `public import
  sosabi.{EventMode, WaitResult, WaitPayload, ...}` for exactly the
  user-chosen encodings; op numbers/rights/ObjType become UNREACHABLE
  from a process in the typed layer. The convention paragraph upgrades
  from discipline to mechanism.
- The prelude (82) and the design-150 import forms are untouched —
  this changes what an IMPORTER of a module can reach through it, not
  what the module itself sees.
- MIGRATION (unit 0, obligation 2): a corpus census of transitive
  bare/qualified naming — who names a type through a module that only
  imports it today? Expected small (the E/W probe was the first
  deliberate use); every hit is a one-line `public import` addition at
  the facade module. std's own files need the same census (82's
  file-modules import each other freely).
- Diagnostics: the design-150 member-lookup failure message gains the
  case "X is imported by M but not re-exported — add `public import`
  in M or import M's dependency directly."

## Open questions (user)

1. The default flip itself (A) — pre-1.0, breaking-by-design, census
   sizes the cost.
2. Spelling: `public import` (lean — the existing visibility vocabulary,
   no new keyword) vs `export import` (C++ flavor).
3. Selective-only? (`public import m.{A, B}` allowed, whole-module
   `public import m` allowed or refused — Rust allows both; Haskell's
   experience says whole-module facades are the common good case. Lean:
   allow both.)
4. Does B (path walls) ride along now or wait for demand?
