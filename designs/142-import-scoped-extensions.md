# Design 142 — extension visibility is import-scoped; conformance coherence

STATUS: APPROVED (user, Aug 5). Queued after 139 and BEFORE 141 (whose `[]`
borrows methods multiply extension usage — the scoping rule lands first).
Proven gap: `.build/scratch/extvis/` — main imports `amod` only; `bmod`
(reached transitively) declares `public extension Data { func u16_at }`;
main compiles AND RUNS `d.u16_at(0)` (`leaked: 4660`). Any module in the
link injects its public extension methods onto a type for everyone —
one module monkey-patching a type for the whole program `[user: the
exact thing we don't want]`, plus silent cross-dependency collisions and
add-a-dependency changes-resolution hazards.

## The rule — extension METHODS [user]

Method lookup on a receiver consults extensions from exactly:
1. the CURRENT module;
2. modules the current file DIRECTLY imports;
3. the receiver type's own defining module (its inherent API — always in
   scope, since a value may flow to you without the import).

Transitive dependencies inject NOTHING. `public` on an extension then
means "importers of my module get this" — the same meaning `public` has
for every other declaration (you cannot call a public function from a
module you did not import; extensions were the one exception, which was
the bug). `public(package)` unchanged (package-wide). Default stays
module-private. Two extensions of the same name visible in one file (own
+ imported, or two imports) resolve by the existing overload machinery;
a true signature-identical duplicate is the standard duplicate error AT
THE USE SITE naming both defining modules.

## The rule — trait CONFORMANCES (coherence)

`extension T: Trait` is declarable ONLY in the module that defines `T` or
the module that defines `Trait` (the orphan rule; lead recommendation,
veto-able). Rationale: conformances mint per-(type,trait) vtables and
back semantic contracts (Hashable feeding Map, Equatable feeding ==) —
two import-scoped conformances of one pair would let a Map built in one
module and probed in another disagree about hashing, an incoherence no
use-site error can cleanly catch. Rust's rule, adopted for Rust's
reasons. Expected migration: ZERO — std conforms its own types; blade/
libs/selfhost conform their own types (verify with a sweep; any violation
found is design material to bring back, not to code around). A conformance
declared under the rule is visible wherever both the type and the trait
are — no import-scoping needed once coherence is global.

## Work

Typechecker: method-lookup scoping (the extension registry becomes
per-module-view keyed by the import graph instead of global); the orphan
check at conformance registration; use-site duplicate diagnostics naming
modules. Sweep: verify no in-tree code relies on the transitive leak
(expected clean) and no orphan conformances exist. Tests,
fail-before/pass-after: the probe pair (transitive leak now a clean
"no method `u16_at` — `bmod` defines it; import bmod" error with the
teaching hint; direct import works); same-name extensions in two imported
modules (overload-resolved or duplicate-error paths); package-scoped
extension across files; inherent-module rule (calling std methods on a
received Data without `import std.data`); orphan conformance rejected
with the two-owners hint; own-type and own-trait conformances unaffected.
Docs: spec member-visibility section gains the lookup rule + orphan rule;
saw-lang skill (amend the Aug-5 extensions idiom note with the scoping
statement); README if it shows extensions. Tracker: file the probe as the
finding, closed by this brief.
