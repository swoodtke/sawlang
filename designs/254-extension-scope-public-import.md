# Design 254 — Extension Scope Follows `public import`

**Status: AUTHORED Aug 30 2026** (lead; user-approved dispatch same day,
sharing one worktree/agent with design 255 — 254's units first, the
version bump last, see unit 3). Agent DF range: **DF-280a+**.

## The finding (sawos, hit THREE times — its facade header records all three)

The sysapi facade in the sawos repo (`kernel/sysapi/src/lib.saw`, header
section "WHERE THE LINE FELL") records three method-placement decisions
forced by the module graph rather than by which receiver reads best, and
names the missing tier explicitly: *"an `internal` or forward-declaration
story, or extension lookup that follows `public import`."* The third
occurrence is the sharpest: design 8 (sawos) RULED the surface
`Waiter.add(process:, key:)`; it is unwritable there today, and the tree
carries the receiver-flipped workaround `Process.attach(waiter:, key:)`
plus a placeholder comment in waiter.saw where the fourth overload
belongs.

Verified repro shape (Aug 30, the user's diff in the sawos worktree):

- `main.saw` writes `import sos.{Process, Waiter, ...}` — its one DIRECT
  import is the facade module `sos`, which re-exports the names via
  `public import`.
- `sos.system` (defines `Process`; imports `sos.waiter`, no cycle)
  declares `extension Waiter { public func add(&self, process: &Process,
  key: UInt) ... }`.
- The call `waiter.add(process: &child, key: KEY)` fails: *"no overload
  of `Waiter.add` matches"*, candidates listing only the three overloads
  from `sos.waiter`.

Per spec this is CORRECT behavior: extension lookup (§ Extension scoping,
design 142) consults the current module, the file's DIRECT imports, and
the receiver's defining module — and *"a re-export hands on the NAME"*
(design 229), never extension scope. The receiver is `Waiter`, so rule 3
consults `sos.waiter`, not `sos.system`. The workaround works precisely
because flipping the receiver to `Process` makes rule 3 consult
`sos.system`. This brief makes the ruled spelling writable.

## The rule

**For extension scoping — and ONLY extension scoping — the direct-import
set is closed over `public import` edges, transitively.** If file F
directly imports module M (any form), and M `public import`s module P
(any form — whole-module, selective, `.*`; the MODULE-LEVEL edge is what
forwards), then P's extensions are in scope in F, and so on along chained
`public import` edges.

Nothing else changes:

- **Name binding/re-export semantics (design 229, DF-247b) are
  untouched.** No name becomes bare-visible or qualifier-reachable that
  wasn't; only extension METHODS on already-reachable values come into
  scope. Member visibility (design 80) still gates each method
  separately — a method must pass BOTH `_ext_scope_allows` and the
  visibility gate, exactly as today.
- **Conformances are unaffected** — already global under the orphan rule.
- **A plain (non-public) import in the facade forwards nothing** — the
  design-142 transitive-dependency rule stands.

Why this is sound against design 142's own rationale: the hazard scoping
exists to prevent (spec §9421) is an UNRELATED transitive dependency
changing what a call resolves to. A `public import` is the opposite of
unrelated — it is the facade author deliberately publishing that module
as part of their surface. If the facade hands you the name `Process`, it
hands you Process's neighborhood of API. It is also the consistent
extension of §9890's existing rule ("every import form makes the module
a direct import, so choosing qualified access never silently loses a
module's extensions") — the public re-export is the author's hand-off of
the same. Where the widened scope creates overload collisions, the
existing indistinguishable-signature-at-the-call diagnostic (§9436)
already covers it: nothing new to invent.

## Unit 1 — the mechanism (obligation 1: the funnel exists; keep it one)

The rule is position-quantified over every method-lookup position, and
the funnel already exists: **`_ext_scope_allows`
(`sawc/typechecker/core.py:1306`)**, whose final clause is
`def_module in self.current_direct_imports`. That set is built in ONE
pass per module (`core.py:3295-3537`, one `direct_imports.add(...)` per
import form) and saved per-module into `_direct_imports_by_module`
(`core.py:3840`, restored at `core.py:841` when re-entering a module's
bodies). The change is confined to how that set is computed:

1. **Record the module-level public-import edge.** Today re-export is
   recorded NEGATIVELY — `note_private_import`
   (`sawc/namespace.py:592`) marks ordinary imports, and a public import
   is simply not marked (`is_public` consumed at e.g. `core.py:1888` on
   the std path, with a user-module twin). A positive table
   (module → set of modules it `public import`s, any form) almost
   certainly needs creating, populated at the same points that read
   `imp.is_public`. Every form contributes the edge — a
   `public import m.{A}` re-exports one NAME but forwards module m's
   extension scope whole, mirroring how a selective DIRECT import
   already brings the whole module's extensions (§9890).
2. **Close the set over that graph at ONE chokepoint** — either where
   `direct_imports` is finalized per module, or one query-time closure
   helper that `_ext_scope_allows` calls; NOT scattered per-import-form.
   Transitive (chained facades), cycle-safe (import cycles are DF-232e
   errors upstream, but the closure must not hang on a malformed graph —
   plain visited-set BFS).
3. std modules already bypass the scope check entirely
   (`core.py:1324` — std is one scoping domain); the closure changes
   nothing there.

## Unit 2 — diagnostics + docs that teach the old rule

The compiler currently TEACHES "a re-export hands on the NAME, never
extension scope" in its own hint text. Sweep and update:

- `core.py:1271` and `types.py:2533` ("a `public import` re-export hands
  on the NAME, never a ...") — reword for the new split: names still
  need the re-export to be NAMEABLE; extension scope now follows it.
- The out-of-scope hint ("`bmod` extends `Data` with `u16_at`, but this
  file does not import it — add `import bmod`",
  `expressions.py:10232`) stays correct for the un-forwarded case; add a
  test that it still fires when NO facade forwards the module.
- Spec: §"Import form and extension visibility" (LANGUAGE_SPEC.md:9890)
  gains the rule + one facade example; the §9269 "hands on the NAME"
  sentence gets the extension-scope carve-out; the design-142 scoping
  section's three-place list becomes three-places-plus-closure.
- saw-lang skill's import/extension notes; README only if it states the
  scoping rule (check).

## Obligation 2 — consumer sweep (behavioral widening)

No program can rely on the OLD behavior in the value sense: the old
behavior is a compile error at the call ("no method ... in scope"), so
the flip is error→works. The one real risk is NEW ambiguities — a
facade-forwarded extension joining an overload set an existing program
already resolves. The sweep is the full corpus (suite + bootstrap:
blade/ and libs/ are the heaviest import users) run under the change;
any new ambiguity error is a finding to examine, not to silence.
`grep -rn "public import" --include=*.saw` over the tree first to
enumerate the exposed surface (expected small: std has few, blade/libs
to verify).

## Unit 1 test matrix (examples/, multi-module via the existing
`--module-path` + `{TESTDIR}` pattern the design-142 tests use)

| row | shape | expect |
|---|---|---|
| 1 | facade one-hop: w defines `W`; m defines `P` + `extension W`; facade `public import`s m (and w); main imports facade only | extension visible, call resolves |
| 2 | chained: facade2 `public import`s facade1 which `public import`s m | visible through the chain |
| 3 | selective form: facade writes `public import m.{P}` only | m's extensions still forward (module-granular) |
| 4 | NEGATIVE: facade writes plain `import m` | invisible; hint names m (existing diagnostic) |
| 5 | NEGATIVE: transitive plain dep (design 142 regression row) | invisible |
| 6 | collision: facade forwards m's `extension W.kind()`; main also directly imports m2 with indistinguishable `kind()` | §9436 ambiguity at the call |
| 7 | visibility still gates: forwarded extension method is non-`public` | refused by the member gate, not by scope |
| 8 | the sawos shape end-to-end (waiter/system/facade names neutralized) | `add(process:)` resolves |

## Unit 3 — version bump (lands as the DISPATCH'S final commit, after
design 255's units, so one bump carries both changes)

`SAWC_VERSION` (`sawc/version.py:27`) `0.1.0` → **`0.2.0`** — a
language-semantics addition is a minor bump. `bin/sawc` is a shim over
the real CLI, so `--version` flows through; verify `bin/sawc --version`
prints `sawc 0.2.0` and the `toolchain` battery lane (which parses it)
stays green. sawos-side follow-up (USER-OWNED, ruled Aug 30 — not this
agent, not the lead; recorded here only so the pointer exists): bump `sawlang.pin` to the landed sha, write the fourth
`Waiter.add(process:, key:)` overload where waiter.saw's placeholder
comment sits, flip death-notify's call site, and amend lib.saw's
"missing language tier" paragraph with the resolution.

## Gates

Compiler change: per-commit full suite + `tools/freestanding_runner.py`
both arches; terminal full battery (`tools/battery.sh`) including
`irdet --all`. Suite lock protocol per CLAUDE.md (split form in the
sandboxed worktree).
