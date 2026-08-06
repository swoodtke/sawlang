# Saw — Open Work Tracker

Open items ONLY. Landed work lives in `designs/NN-*.md` + git history
(this file was pruned Jul 30; see git history of this file for the old
landed recaps). Conventions: cite source designs in [brackets]; VERIFY
items need a probe before being treated as real work.

## Review sweep (Aug 4) — TRIAGED (user, Aug 4 evening), briefs 122-127
Four reviewer reports in `designs/reviews/2026-08-04-*.md`; probe repros live
there. Triage outcome: **122** fix batch (RS-2/4/5, RC-1/4/5, P2, DF-119b —
wave 1); **123** allocator-failure policy pass, design-19 tiers (RS-1 — wave
2); **124** TaskGroup EAGER teardown (RS-3, user chose scope-not-extender —
wave 2); **125** docs sweep + README catch-up + README joins the docs
convention + soften no-hidden-allocations (P3 — wave 1); **126** pre-port trio
R1/R2/R11 incl. the RC-2 substitution bug (wave 1); **127** op-budget loop-
backedge preemption (RC-3, user chose fix-not-soften — wave 2); **128/129
DRAFTS** (Deinit/ExplicitCopy synthesis — LANDED, see below;
newlines-in-brackets) awaiting user
review — DO NOT DISPATCH. Original ranked findings follow for reference.

**146 PARTIAL (Aug 5) — units A, B and D landed; unit C is NOT started and the
brief's P0 pair is STILL OPEN.** Read this before the 141 entry below, which it
supersedes on the use-site question.

- **Unit A DONE.** `_prepare_codegen` re-enters over the ASTs it already parsed
  (`parsed=`: module map, module sources, and the builtin+std AST from before
  `_filter_std_ast` narrows it). Front half on a re-entering program: 451 -> 310
  ms, 503 -> 359 ms, 485 -> 345 ms, 483 -> 320 ms across the sample — 29-34%
  off; a non-re-entering program is unchanged (242 -> 252 ms, noise). Reuse
  means the second pass re-checks objects the first pass touched, which
  surfaced two latent defects, both FIXED here: **DF-146a** (below) and the
  coroutine transform DESTROYING imported std method bodies — a nested
  suspending std method's frame is built by a builder that hoists/ANF/state-
  splits the body IN PLACE, and the code relied on the re-parse to undo it
  ("it re-parses fresh on the recursive pass anyway"). Imported methods now
  build from a copy. Commit 9f7e5dd.
- **Unit B LANDED for UNCONDITIONAL accessors, fenced elsewhere.** A place use
  is recognized by the checker (`typechecker/places.py`: `v[i]` against a `[]`
  accessor, `v.name(...)` against a named one — the window closures are
  compiler-added trailing parameters, so the ordinary arity path would count
  them against the author) and lowered post-typecheck by the new
  `sawc/place_uses.py`. Working, with `examples/place_use_sites.saw` as the
  oracle: both flavors from ONE declaration, window extent = the smallest
  expression that turns the place back into a value, chained windows
  (`b[0][1].count += 10` is two nested windows), `f(&var v[i])` call-spanning
  windows, value reads through the copy-tier table, and the LIFO epilogue
  ordering (which comes free from nesting). `__R` is passed EXPLICITLY as the
  accessor's one type argument, taken from the replaced expression's
  `resolved_type` — nothing about the window has to be inferred. Exclusivity
  needed NO new checker rule: a place use is still syntactically `v[i]` when
  `_build_access_path` runs, so `f(&var v, &v[i])` and the `[&var v]`-capture
  probe are already the existing Law-of-Exclusivity shapes. TWO FENCES, each a
  clean teaching error, each a design question below: DF-146b (exclusive window
  through a `&self` accessor) and DF-146c (calling a conditional lend).
- **Unit C NOT STARTED.** No std conversion, no `Vector.[]`/`Vector.get`, no
  Map/Data, no `_type_method_base` drop-glue fix, no toml/blade migration, no
  docs. **DF-132a and DF-128c remain OPEN and unpaired** — and note that unit
  C now depends on DF-146b/DF-146c being decided first: `Vector.get` is a
  CONDITIONAL lend (DF-146c blocks it outright) and `Vector.[]` as 141 spells
  it takes `&self` (DF-146b blocks writing through it).
- **Unit D DONE.** See the DF-126b entry below for the strengthened gate and
  its measured cost.

- **DF-146a — FIXED (design 146 unit A). A `@synthesize` type in a program that
  uses concurrency did not compile.** Registration was not idempotent: each
  derivation writes its synthesized `copy`/`equals`/`compare`/`hash` back into
  the extension, and the coroutine transform re-runs the whole front half over
  the entry AST, so the second registration read the compiler's own body as a
  hand-written one and reported "``@synthesize`` on `extension T` derives
  nothing" against a correct program. Live on main since design 128 met design
  44. `_derivation_slot` now separates "an author wrote one" from "we derived
  one already". Regression test:
  `examples/synthesize_across_coro_reentry.saw` (fails before the fix).

- **DF-146b — DECIDED (user, Aug 5): OPTION (a), use-site-derived window
  mutability, confined to the lend expression.** The rule: a borrows body is
  a `&self` body whose LEND inherits the window's flavor; the general
  `&var self.<field>`-under-`&self` fence stays a hard error everywhere else.
  **DOCS MANDATE [user]: call the inconsistency out VERY clearly** — spec
  Places section gets a prominent callout + the skill a gotcha entry:
  "`borrows` changes what `&self` means: the receiver is borrowed with the
  window's flavor, decided at each use site — the one place a `&self`
  spelling does not mean shared-only" — and `--emit-docs` renders a borrows
  receiver honestly (window-flavored, not `borrows`=shared). Owned by the
  146-C continuation. Original finding follows: `&var self.<field>`
  inside a `&self` method compiles and silently writes to a COPY** (found by
  design 146 unit B, Aug 5; PRE-EXISTING, nothing to do with places). A `&self`
  receiver is passed by value, so every `&var` projection out of it addresses
  the callee's copy. No error, no warning, no write. Repro:

  ```saw
  struct Cell { count: Int }
  struct Bag { slot: Cell, cells: [Cell; 3] }

  extension Bag {
      func shared_field<R>(&self, body: (&var Cell) sync -> R) -> R {
          body(&var self.slot)          // writes a copy
      }
      func shared_elem<R>(&self, i: Int, body: (&var Cell) sync -> R) -> R {
          body(&var self.cells[i])      // writes a copy
      }
      func var_field<R>(&var self, body: (&var Cell) sync -> R) -> R {
          body(&var self.slot)          // writes the real thing
      }
  }

  func main() {
      var b = Bag(slot: Cell(count: 0),
                  cells: [Cell(count: 1), Cell(count: 2), Cell(count: 3)])
      b.shared_field { c in c.count += 10 }
      print("{b.slot.count}")       // 0   -- want 10, or a compile error
      b.var_field   { c in c.count += 10 }
      print("{b.slot.count}")       // 10  -- correct
      b.shared_elem(1) { c in c.count += 10 }
      print("{b.cells[1].count}")   // 2   -- want 12, or a compile error
  }
  ```

  Design 106 already says a `&` may not upgrade to `&var` and gives a clean
  error for a reference PARAM; `self` was never covered. On its own the fix is
  "make it that same error" — but it is load-bearing for design 141 decision 3
  ("mutability comes from the USE SITE, never the declaration — one body serves
  both flavors"), because the shape 141 blesses is exactly
  `func [](&self, i: Int) borrows -> T` with `lend self.buffer![i]`, which
  lowers to `__window(&var self.buffer![i])`. So the landed
  `examples/borrows_declaration_lowers.saw` declares accessors that would
  silently not write. THE DECISION: either (a) an accessor's receiver is
  borrowed per the USE SITE — the checker half of that is already implemented
  (`place_window_exclusive` makes an exclusive window demand a `var` root and
  join the access set as a mutable path), and what is missing is passing the
  receiver by pointer rather than by copy; or (b) retreat from decision 3 and
  let a `borrows` accessor declare `&var self` when it lends writable storage,
  which is what the landed fence already requires and what
  `examples/place_use_sites.saw` is written against. Until it is decided, an
  exclusive window on a `&self` accessor is a clean error naming the `&var
  self` spelling (`examples/errors/place_exclusive_shared_accessor.saw`).

- **DF-146c — OPEN. Calling a CONDITIONAL lend (`borrows -> T?`) is not
  implemented** (design 146 unit B). Declaring one works (design 141); using
  one is a clean "not implemented yet" error naming `with_ref`/`with_var_ref`
  as the interim. What blocks it: the absent path's closure takes no parameters
  and its `__R` does not survive to codegen — the synthesized `{ None }` body
  reaches the backend with `current_return_type=Void`, so the `None` has
  nothing to be a `None` OF (internal error rather than a wrong answer). The
  present path (`{ __p in __p }`, auto-wrapping into a pinned `__R = T?`) is
  believed right; the parameterless twin is where the type is lost. Blocks
  `Vector.get`, hence blocks the DF-132a/DF-128c pair.
 Units A and B are in: `lend` and
`borrows` are reserved in BOTH lexers (selfhost mirrored, lexdiff clean over
1326 files); `borrows` joins the declaration effect slot in canonical order
`unsafe sync borrows`, matching the type grammar's
`unsafe sync escaping borrows`; `[]` is a declarable method name; `lend <place>`
is a statement; the coverage rule, the conditional-lend absent path, and both v1
fences (no borrows function TYPES, no trait requirements) are enforced with
teaching errors. The brief's `escaping`-on-a-declaration fixit landed with them.

THE LOWERING THAT WORKS, and why. A borrows declaration is rewritten into the
window-closure shape — `func [](&self, i: Int) borrows -> T` becomes
`func [](&self, i: Int, __window: (&var T) sync -> __R) sync -> __R`, with
`lend X` becoming `return __window(&var X)` — so the common case emits exactly
what `with_ref` emits today. An EPILOGUE (statements after the `lend`) is
spliced in AT the lend site rather than left where it was written; that keeps
every prologue local in scope for the epilogue that reads it (the
lock-and-release shape) with no frame struct and no state machine, and
duplicating the tail is sound precisely because the coverage rule forbids a
second lend on that path. The transform runs inside `parse_source`, the one
funnel every compilation path takes, so registration, inference,
monomorphization and codegen all see an ordinary generic method and it costs no
second front-end pass. `tools/dump_ast.py` builds its own parser, so the
parser-stage oracle still dumps the authored form.

**WHY USE SITES STOPPED — two findings, both load-bearing for whoever picks
this up.**

(1) **The address form is not expressible in Saw source.** The obvious use-site
lowering is a prologue returning the place's address
(`__place_addr(&self, i) -> UnsafePointer<T>?`), which would let codegen treat a
place as an ordinary lvalue — no closures, no AST surgery, and the fastest
possible code. It cannot be written: `&var` is *only* legal as a call argument,
so `&var X as UnsafePointer<T>` in return position is rejected, and the `&`
variant is refused too (`can only take reference to a variable, field, or array
element`). This is exactly why `with_ref` takes a closure and why the brief
calls the pair "the lowering vocabulary" — a place can only be handed out AS A
CALL ARGUMENT. So a use site must synthesize a closure call
(`v.[](i) { __p in ... }`), which needs the receiver's type and therefore must
run after type checking.

(2) **The coro transform's "mutate the AST, re-enter the front end" pattern
cannot carry a mutation into std.** `_prepare_codegen` re-resolves and
RE-PARSES every module and every builtin from disk on the recursive
`post_transform=True` pass (`sawc.py:700-772`, `build_builtin_namespace`), so
anything the transform wrote into an imported AST is thrown away. The coro
transform never noticed because it only ever mutates `entry_ast`. Places are
different: `Vector.[]` and `Vector.get` live in std, and so do their use sites
inside std itself.

WANTED, as the first unit of the follow-up: teach `_prepare_codegen` to reuse
already-parsed module ASTs (and a builtin AST) on re-entry instead of re-reading
them, then do use-site rewriting in the transform slot exactly as the coro
transform does. That refactor pays for itself twice — it also removes a full
redundant parse of std from every program that uses concurrency. It is a change
to the most load-bearing function in the driver and was not something to start
at the end of a session, which is why this stopped here rather than half-landing
a second mechanism.

NOT DONE, and still owned by this brief: use sites of every shape (value read,
whole-element write, `v[i].n += 1`, `f(&v[i])`, chained windows), root
attribution into `_build_access_path`, the exclusivity/LIFO-epilogue work, the
std `[]` methods, **the DF-132a / DF-128c P0 pair and the toml/blade
migration**, and the spec/skill/README docs. LANGUAGE_SPEC, the skill and README
were deliberately NOT updated: a user can declare a borrows accessor but cannot
yet call one, and documenting that as a language feature would be false.
Brief: designs/141-borrows-lend-places.md. [141]

**143 LANDED (Aug 5)** — Blade build-output directories + lockfile policy.
Origin: the SOS M1 review finding that `sos/root/sos-root.sosimg` sat next to
its `Saw.toml` [user]. Blade built IN PLACE, so artifacts lived beside source,
every package grew artifact ignore patterns, and two TARGETS of one package
would have fought over one filename (load-bearing with M1b/arm64 queued).
Decision 1: everything a build produces goes under `<package>/.build/<target>/`
— `<target>` is the sawc `--target` triple with `host` for the default hosted
build (the brief's pin, taken as written). `blade/src/layout.saw` is the one
place that knows the shape (`BuildLayout` + `Path.ensure_dir`/`remove_tree`);
builder and tester both hold one. The up-to-date check is per-target on BOTH
halves (stamp AND artifact), which is what makes a stale in-place artifact from
the old layout unreachable rather than merely unlikely. Riders the layout made
expressible: `blade build --target <triple>`, `blade clean [--target]` (new
command; `.blade/deps/` survives — it is source, not output), Blade creating
its own output directory (sawc does not create one), `blade new` scaffolding a
`.gitignore`. Decision 2: the app/lib distinction has NO manifest field — the
source layout IS the declaration (`src/main.saw`/`main.saw` = application,
`src/lib.saw` alone = library), recorded as `Builder.is_application()`. An
application commits `Saw.lock`; a library does not, so `blade build` no longer
writes one in a library at all (`blade update` still does, the explicit ask)
and `libs/toml` + `libs/semver` carry a one-line `.gitignore` for that case.
Sweep: blade conformant already; selfhost/lexer is application-shaped but has
zero deps and is built by tools/lexdiff.py through sawc directly, so no lock
exists or can appear; `sos/root/Saw.lock` is on the PARKED M1 branch — that
branch should commit it (sos/root is an application). Gates: suite 1174,
lexdiff, irdet, astdiff, bootstrap (three new layout stages), sos (now building
into `.build/riscv32-unknown-none-elf/sos/`). Found and fixed on the way: the
Blade suite was ORDER-DEPENDENT — `dep_build` and `lock_roundtrip` write into
`.build/scratch/` and nothing created it, so whichever ran first failed on a
clean tree. NOT moved (deliberate): `tools/lexdiff.py`'s `.build/sawlex` and
`tools/irdet.py`'s `.build/<stem>.ll` are repo-root scratch for host-only
harnesses, not package output, and the repo root is not a Blade package.
Brief: designs/143-blade-build-dirs.md. [143]

**139 LANDED (Aug 5)** — the enum policy tier; no policy-exempt wrappers.
Closes **DF-131a**. `Namespace.copy_tier` is the single oracle: every type has
exactly one transfer class, and a WRAPPER is never weaker than what it wraps —
`Optional<T>`, tuples, fixed arrays, enum payloads and `Result<T, E>` all JOIN
their parts' tiers, with a declared conformance winning over the join. The move
checkpoint is one lookup into it, which retired the bespoke owning-enum arm.
Owning ENUMS now declare a policy like owning structs (`extension E: NoCopy {}`
/ `@synthesize extension E: ExplicitCopy {}`), a bare one being the same
teaching error; only the two OWNING tiers are demanded, so a trivial/
ImplicitCopy enum stays undeclared. `.copy()` on an optional exists exactly when
the payload's tier provides one, and a refused optional transfer names three
spellings (`.copy()` / `move` / `.take()`) rather than the struct's two.

Migration, whole tree: FIVE enums declared a tier (`Slot` twice, `Crate`,
`Payload`, blade's `BladeCommand`) and ONE struct was hit by the containment
cascade (blade's `Cli`); compiler-synthesized `__Frame_*` structs are exempt
rather than migrated. The brief assumed design 128's enum synthesis already
covered copy — it did not (128 gave enums a payload-deep DEINIT and the
Equatable/Comparable/Hashable derivations), so `_emit_enum_deep_copy` was
written here. The tiers are COMPUTED rather than spelled as bounded
conformances in builtin.saw as the brief sketched: `Optional` is a `TypeKind`,
not an enum or struct, so it cannot carry an extension; and `Result`'s two
parameters make the brief's "bounds are mutually exclusive, so exactly one tier
matches" false — the join over (T, E) is not a rectangle, so no set of bounded
conformances expresses it. Observable behaviour is the brief's.

Five latent defects surfaced and were fixed on the way: the coro transform's
sub-frame `__result` read was unstamped (a retain against a paired
`__saw_forget` — a leak); the `__saw_drive_*` wrapper relied on a retain that
has no analogue for a move-only result, and is now a move; `__Frame_*` structs
lacked the ExplicitCopy containment exemption their NoCopy sibling had; the
derived memberwise struct copy raised on an ENUM field and silently
BITWISE-ALIASED an OPTIONAL field. Filed rather than fixed: **DF-139a** below
(overwriting a binding releases its old value while a live copy exists —
pre-existing, reproduces on a plain `String` field, identical before and after).

**133 LANDED (Aug 5)** — two capability completions. Unit A: `Arc<T>`/`Box<T, A>`
payload-method forwarding reaches a METHOD-GENERIC payload method, closing
**DF-123c**, and `Mutex.lock` then became `lock<R>(body: (&var T) sync -> R) -> R`
— review **M1** closed, a value can be computed under the lock and carried out of
it. The fix was codegen-only: both forwards now share `_forward_target_symbol`,
which substitutes the resolved method type args and requests the monomorph the
way the ordinary call path does. DF-123c's second named cause (the typechecker's
`_resolve_arc_forward` not solving method-level type args) was not real — the
forward hands off to the shared downstream, which already runs the design-93/105
inference. Unit B: the design-120 ANF hoist lifts a NESTED short-circuit, closing
**DF-125a** — `f(a ?? slow())`, `return 1 + (a ?? slow())`, `not (a && slow())`,
`g(f(a ?? slow()))` and the blocking-extern versions all transform, and the RHS
still runs only when the LHS does not decide. The mechanism is the one design 120
already had: hoist the WHOLE conditional to its own statement, which is the
outermost form the branch lowering handles, and recurse.

`lock<R>` keeps `body` in TAIL position (a `LockRelease` scope guard does the
unlock) because binding the result would need a local typed `R`, and `R` is
`Void` for every critical section that computes nothing — **DF-123b**, still
open, and the same reason `Vector.with_ref<R>` is written that way. Found on the
way and filed rather than fixed: **DF-133a** (the stage-1 hoist reorders a
suspending child ahead of a side-effecting sync sibling).

**131 LANDED (Aug 5)** — payload-read ownership. Every payload-extraction form
(`o!`, the `??` left operand, an `if let`/`guard let` binding) is now a PLACE,
governed by the payload's copy tier like every other read, and `Deinit` is
non-declarable so no type can carry a destructor without a transfer rule. Closes
**DF-124b** and **DF-128a** (both detailed below). The consuming reads are
`move o!` (compile-time, retires the whole binding, locals only) and the new
`Optional.take(&var self) -> T?` (runtime, swaps `None` in, reaches a FIELD);
`TaskHandle.join` migrated onto `take()`, retiring the tree's last
`__saw_forget` call site. 108 types migrated off standalone `Deinit`
conformances — 74 of them had no copy policy at all and are now `NoCopy`.

Found and fixed on the way: `??` never checkpointed its DEFAULT operand, so
`let s = opt ?? other` aliased `other` and double-freed it (the ExplicitCopy
repro aborted with SIGTRAP). One related hole is filed rather than fixed —
**DF-131a** below (a whole-optional read of a NoCopy/ExplicitCopy payload).

**130 LANDED (Aug 5)** — the unsafe model is rebuilt and design 81's marking
rules are superseded (that brief now carries a SUPERSEDED header). Marking is
per-DECLARATION: `unsafe struct` for a type (with the `Unsafe*` name enforced),
`unsafe func`/`unsafe init` for a function whose body or signature names, binds,
receives or returns one of its values. Type unsafety is not transitive, closures
are judged on their own body, and calling an unsafe function from safe code
needs no ceremony. The line-level `unsafe` expression marker is GONE from the
grammar — 287 of them deleted, and writing one now gets a parse error that says
the model changed. 250 declarations marked (std 133, rt 47, examples 60, blade
5, sos 5); `libs/` and `selfhost/` needed none. Shipped in six staged commits
per the brief's q4 plan, full suite green at each.

Closed here: **M5** (`Vector.set`/`swap` were silent no-ops out of range — both
panic now, and `examples/vector_set_oob_still_noop.saw`, which asserted the old
contract, is deleted) and **M3** (`String.substring` clamped — it panics on a
reversed or out-of-range range; an empty `substring(i, i)` is still legal). Both
are the accessor rule (brief rule 8); RS-6's part of that rule — the three
genuinely UNCHECKED accessors `with_ref`/`with_var_ref`/`swap_out` — had already
landed in design 122 and is unchanged. The rule's audit of `Data` (the brief's
exit criteria name it alongside Vector and String) found `get`/`slice` already
`get`-shaped and compliant, and one third shape neither M3 nor M5 had named:
`Data.set` returned a `Bool` that NOTHING in the tree read, so an out-of-range
write silently did nothing. It panics now, like `Vector.set`.

Fixed on the way: the trigger-rule verdict runs during teardown, after
`current_method`/`current_function` are cleared, so `_error`'s source-file
auto-detection fell back to the ENTRY module — a blade diagnostic about
`Tester.shell_ok` printed a blank line from `main.saw`. It now names the
declaration's own file. Still open: the oversized-`unsafe`-function
decomposition already filed below.

**136 LANDED (Aug 5) — 130's spelling correction.** `unsafe` moved out of the
declaration prefix and into the post-parameter effect slot beside `sync`
(`func f(...) unsafe -> T`, canonical order `unsafe sync`), so a declaration's
signature reads identically to its function TYPE; `unsafe struct` keeps the
prefix (no parameter list, no slot). All 262 declarations re-spelled tree-wide,
IR unchanged apart from the debug-info column of each moved keyword. The prefix
is now a parse error carrying the mirror of 130's fixit, and so is the reversed
`sync unsafe`. Unit B settled the two things 130 left unstated: the `unsafe`
effect on a function TYPE is well-formed iff the signature names an unsafe type
(both halves error, the spurious one teaching rule 7), checked on the type as
written so generic slots are never re-judged per instantiation; and a closure
INHERITS its enclosing function's unsafe domain — no closure-level marker, its
type derived from its own signature, and body contact beyond that signature
charged to the enclosing declaration. The design-130 variance gates
(closure-into-safe-slot, unsafe-value-into-safe-slot) are deleted: with the
effect derived from the signature, the pair of spellings they compared cannot
exist.

**128 LANDED (Aug 5)** — the P4 structural-synthesis line is closed. Deinit is
implicit (a synthesized memberwise `deinit` for any owning struct/enum, dropping
in reverse declaration order; enums payload-deep on the active variant), the
"does not implement Deinit" containment error is gone, and the copy/equality
derivations are gated on a new `@synthesize` extension attribute — uniformly
across ImplicitCopy/ExplicitCopy/Equatable/Comparable/Hashable, with
auto-conformance untouched. Riders done: the four bad-receiver hints, and
`var self` is now a compile error (the audit found TEN in-tree uses, not the
expected zero — blade, libs/toml and selfhost/lexer among them). Nine
transcribed empty deinits deleted from the real Saw packages.

Four things it did NOT close, each recorded below: **DF-128a** (a `Deinit`-only
type aliases and double-frees — pre-existing, found while probing), **DF-128b**
(a payload-free enum cannot be a Map/Set key despite auto-conforming),
**DF-128c** (the drop half of a mangling miss whose copy half WAS a live
double-free and is fixed here), and **DF-128d** (`print(o)` on any optional is
an ICE). Also worth flagging to the reader of the brief: it describes a
hand-written deinit as REPLACING the field drops. It does not — it prefixes
them, and always has; the spec now documents the real behavior.

**132 LANDED (Aug 5)** — units A-G; suite 1140 -> 1149. Closes DF-122a (with
RS-5's fourth hole), DF-123a, DF-123b, DF-128b, DF-128d, DF-129a, review M15 and
P2. Unit A carried the user's reject-the-write decision and unit C the user's
compile-instantiated-Void decision. Unit H — the flagged risky one — is STOPPED
with findings, per its own stop-if-it-fights rule: its fix is correct but would
introduce a live double-free, because DF-128c's missing drop glue is CANCELLING
a second bug. That second bug is new and filed as **DF-132a** (P0): `Vector.get`
has no `T: Copy` bound, so a NoCopy element is handed out as a non-retained
alias and two lookups free it twice, in safe code, today. The pair must land
together and needs its own brief — fixing `get` breaks libs/toml and blade at
the source level.

**127 LANDED (Aug 5)** — RC-3 closed; the op budget now covers pure-compute
loops, so the README claim holds as written. Nothing left open, but the fix
carries four deliberate bounds (sync callee, collection `for`, closure body,
std's own io loops) — all in LANGUAGE_SPEC + the saw-lang skill.

**124 LANDED (Aug 5)** — RS-3 closed; a group is a scope, not an extender.
Landing it needed a frame-field ownership fix (DF-124a, folded in). Two things
it did NOT close: the general `opt!` read-out-of-optional gap DF-124a's root
cause belongs to (DF-124b, closed by design 131) and the brief's item 3 box
reclamation, unimplementable as written (DF-124c) — **closed by design 134**,
which moved the result and cancel word into group-owned cells so the frame box
could go at Done.

**134 LANDED (Aug 5)** — closes DF-124c. Three moves: group-owned result/cancel
cells, the frame box released at completion, and a generation-counted slot free
list. A group now costs O(live + unjoined-result tasks); measured 200,000 slots
/ 31.0 MB -> 4 slots / 1.5 MB on 200k short tasks through one group. Found and
fixed on the way: writing to a field of a GENERIC struct instance was rejected
outright (the write path resolved the field against the generic symbol and saw
the abstract `T` while the read path substituted) —
`examples/generic_struct_field_assign.saw`.

**122 LANDED (Aug 5)** — units A-I plus the folded-in RS-6, per-item closures
inline below. Two things it did NOT close: RS-5's fourth hole (DF-122a, stopped
for a user decision) and P2's design-92 half-application in
std.file/std.directory.

**123 LANDED (Aug 5)** — units A1-A3, B-J. Closes RS-1 and the report's C1, H2,
H3, H7 and H8. Two things it did NOT close: review M1 (`Mutex.lock`'s result
should be the closure's own type) was blocked on **DF-123c** — both closed by
design 133 — and **DF-123b** is a second ICE found on the way (closed by
design 132 unit C); both are recorded under "Design 123 — DF-findings".
review M15 (`Directory.current` truncates at 1024 bytes) was untouched there —
only its OOM path was separated out — and is **FIXED by design 132 unit F**
(Aug 5): the buffer doubles from 1024 up to a 1 MiB ceiling and getcwd is
retried until the path fits, so a long working directory comes back WHOLE
instead of as a `None` indistinguishable from a real failure. errno is not
readable from std (rt/ABI.md keeps `__saw_rt_last_syserror` runtime-internal,
and getcwd is a bare libc call), so the retry cannot tell ERANGE from EACCES and
does not try — it grows until the path fits or the ceiling is reached, which
costs a handful of doublings on a path that was already failing. The OOM path
stays separate: allocator refusal still panics (design 123). Test
`examples/directory_current_long_path.saw` builds its own ten-component,
200-bytes-each tree by entering one component at a time (a single `mkdir` of the
whole path would hit PATH_MAX — 1024 on macOS, 4096 on Linux), which puts the
working directory past 2000 bytes on either host; it asserts the path comes
back, exceeds the old fixed buffer, and is intact at both ends, then unwinds the
tree and restores the original directory. Measured at 2036 bytes on macOS, where
it returned `None` before.

**P0 — proven memory-safety / correctness (stdlib + runtime):**
- **RS-1 — FIXED (design 123, Aug 5).** std now has ONE answer to "the allocator
  said no", in two tiers, applied to every site below. An infallible signature
  PANICS naming its method (`Vector.push: allocation failed`) through
  `__saw_rt_panic`; each such operation has a `try_`-prefixed twin returning
  `Result<_, AllocError>` that is all-or-nothing — on `Err` the container is
  exactly as it was. `try_` is the one spelling (`Box.make_or` -> `try_make`).
  `AllocError` conforms to `Error`/`Printable` and carries the refused
  size/align. `String` gets no fallible tier: every producer returns a plain
  `String`, so the single allocator behind them panics, which covers the whole
  layer in one place. Original finding follows: `Vector.push` writes past the
  buffer and bumps length when `grow()` fails silently; same shape in
  `StringBuilder.append/append_char`, `Data.push/append/append_bytes`,
  `Command.append_arg`. Root cause is systemic: std has ~9 different answers to
  "the allocator said no" (panic / Err / degrade / corrupt / drop / inert
  object). One design-19-three-tier pass would subsume five other findings.

  **The classification table** (the brief's first task — every allocation-failure
  site in std and in the compiler's own emitted code, its behavior BEFORE, and
  the tier it now sits in). "corrupt" = out-of-bounds write from safe code.

  | Site | Was | Now |
  |---|---|---|
  | `Vector.push` | corrupt (OOB write + length past capacity); dropped the element on the first-alloc path | tier 1 panic; `try_push` |
  | `Vector.grow` | silent no-op | private `_reserve -> Bool` |
  | `Vector.init(capacity:)` | degraded to an EMPTY vector | tier 1 panic; `try_with_capacity` (existed) |
  | `Vector.copy` / `map` | short/empty result vector | tier 1 panic; `try_copy` |
  | (new) | — | `Vector.try_reserve` |
  | `Box.make` | tier 1 panic (already correct) | unchanged; `make_or` renamed `try_make` |
  | `StringBuilder.append` / `append_char` | corrupt | tier 1 panic; `try_append` / `try_append_char` |
  | `StringBuilder.grow` | silent no-op | private `_reserve -> Bool` |
  | `StringBuilder.init(capacity:)` | capacity-0 builder | tier 1 panic; `try_with_capacity` |
  | `StringBuilder.build` / `as_str` | `""` | tier 1 panic (via `__saw_string_alloc`) |
  | `StringBuilder.append_scalar` | corrupt, still returning `Some(1..4)` | tier 1 panic; `None` means invalid scalar only |
  | `Data.push` / `append` / `append_bytes` | corrupt | tier 1 panic; `try_push` / `try_append` / `try_append_bytes` |
  | `Data.ensure_capacity` / `allocate_buffer` / `ensure_unique_capacity` | silent no-op, `public` | private `_reserve` / `_allocate_buffer` / `_reserve_unique`, all `-> Bool` |
  | `Data.copy` | `len() == N` with `capacity() == 0`, every `get` None | tier 1 panic; `try_copy` |
  | `Data.init(capacity:)` | capacity-0 buffer | tier 1 panic; `try_with_capacity` |
  | `Data.make_unique` | silent data loss | private `_make_unique`; tier 1 through `copy` |
  | (new) | — | `Data.try_reserve` |
  | `__saw_string_alloc` (codegen) | NULL -> every String producer degraded to `""` | tier 1 panic; declared non-optional in std |
  | `String._substring` (and `trim`/`trim_start`/`trim_end`/`substring`) | `""` | tier 1 panic |
  | `String.to_uppercase` / `to_lowercase` | returned `self`, UN-cased | tier 1 panic |
  | `String.replace` | returned `self`, NO replacements | tier 1 panic |
  | `String.fromBytes` | `Ok("")` — success reported on failure | tier 1 panic; `Err` means invalid UTF-8 only |
  | `String.split` / `to_data` | short/empty, or corrupt via push | tier 1 panic |
  | `Vector<String>.join` | `""` | tier 1 panic |
  | `Path.join` / `join_path` | returned the UN-JOINED parent path | tier 1 panic |
  | `Map._grow` | first grow: `cap = 8` over an EMPTY vector; later grows: INFINITE LOOP | `_try_grow -> Bool`, reserving the table up front |
  | `Map.insert` | dropped key+value, incremented `count`, returned None | tier 1 panic; `try_insert` |
  | `Map.keys` / `values` | short/empty snapshot | tier 1 panic (via push) |
  | `Set.insert` | dropped the element, counted it, returned `true` | tier 1 panic; `try_insert` |
  | `Set.of` / `init(from:)` / `to_vector` / union / intersection / difference | short/empty | tier 1 panic |
  | `Set.is_subset` / `is_superset` | vacuously `true` | tier 1 panic |
  | `Arc.init(value:)` | INERT: value dropped, `strong_count() == 0`, forwarded calls deref null | tier 1 panic; `try_make` |
  | `Mutex.init(value:)` | INERT: `lock` returned `false` without running the body | tier 1 panic; `try_make` |
  | `Mutex.lock` | `false` collided with the inert case | collision gone (no inert mutex exists); result is the closure's own type since design 133 (M1 closed) |
  | `Mutex.get` | `T?` whose None meant "built by a failed allocation" | returns `T` |
  | `Channel.init` | INERT: `send` swallowed, `recv` panicked on a None unwrap, `receive` hung | tier 1 panic; `try_make` |
  | `Channel.send` | SILENTLY DROPPED the message | tier 1 panic; `try_send` over a reporting `_enqueue` |
  | `Channel.recv` (no block) | `empty!` — a force-unwrap saying nothing | named panic (unreachable) |
  | `TaskGroup.init(threads: N>=2)` | INERT: no task ever ran; `join` unwrapped an unwritten result | tier 1 panic |
  | `TaskGroup.__enqueue` / `__saw_exec_run_root` | corrupt / desynced 4 vectors; root: main's frame dropped, exit 0 | tier 1 panic (through `Vector.push`) |
  | spawn control block (codegen `calls.py`) | stored through NULL -> segfault, no message | tier 1 panic (`_alloc_or_panic`) |
  | escaping closure env (codegen `closures.py`) | stored through NULL -> segfault, no message | tier 1 panic (`_alloc_or_panic`) |
  | `Command.output` read buffer | `Some(CommandOutput(stdout: "", exit_code: real))` | tier 1 panic |
  | `Command.output` grow | corrupt | tier 1 panic |
  | `Command.build_argv` | `None` -> reported as "could not launch process" | tier 1 panic; return non-optional |
  | `Command.arg` | corrupt / dropped an argv element | tier 1 panic (through `Vector.push`) |
  | `File.read` / `File.write` | `None`, colliding with the syscall failure; short reads | tier 1 panic; `None` means the syscall failed |
  | `Directory.current` | `None`, colliding with getcwd failure AND truncation | tier 1 panic; `None` means getcwd failed (M15 truncation FIXED in design 132 unit F) |
  | `Directory.list` | name -> `""`, entry -> the parent dir, entries dropped | tier 1 panic (through String/Path/Vector) |
  | `Env.arg` / `get` / `args` | `Some("")` for a real value; short argv | tier 1 panic (through String/Vector) |
  | `net.net_buffer` | tier 1 panic (already correct) | unchanged |
  | `net.net_read_once` / `read` / `read_into` | `Err(IoError)` + corrupt via `append_bytes` | `Err(IoError)` kept; the corrupt half is tier 1 |
  | `TcpStream.write(String)` | short/empty write reported as `Ok` | tier 1 panic (through `to_data`) |
  | `Allocator.alloc` / `slab_alloc` | `None` (the reporting primitive) | unchanged — this is what the tiers are built on |
- **RS-2 — FIXED (design 122 units A + B, Aug 4; commits 3b68703, b8f9969).**
  `iter()`/`EnumeratedIterator` carry the `T: Copy` bound `each`/`map` already
  had and `next()` yields an explicit `.copy()` (a NoCopy element is reached
  through `with_ref`/`with_var_ref` instead — now a clean bound error naming
  it); `set` routes through `swap_out`, so the overwritten element deinits
  exactly once; `String.byte_at` bounds-checks; `Data.to_string` delegates to
  `String.fromBytes` and returns `Result<String, Utf8Error>`. Original finding
  follows: `Vector.iter()` double-frees owning elements (safe code, no unsafe,
  proven deinit-twice). `set` also leaks the overwritten element;
  `String.byte_at` reads OOB heap from a safe signature; `Data.to_string`
  mints invalid UTF-8.
- **DF-132a — OPEN, P0. STILL OPEN after design 146 (Aug 5): use sites now work
  for UNCONDITIONAL accessors, but `Vector.get` is a CONDITIONAL lend and
  calling one is not implemented (DF-146c); `Vector.[]` as design 141 spells it
  takes `&self`, which cannot lend writable storage (DF-146b). Both are named
  in the 146 PARTIAL entry at the top, and both want a decision before unit C
  is dispatched. This pair remains the first thing the follow-up must land. `Vector.get` has NO `T: Copy` bound, so a
  NoCopy element
  is handed out BY VALUE as a non-retained alias — proven double-deinit in safe
  code (found by design 132 unit H, Aug 5; PRE-EXISTING).** RS-2's unfinished
  half: design 122 gave the `T: Copy` bound to `iter`/`enumerated`/`each`/`map`
  and routed `set` through `swap_out`, but `get` was never touched. Its
  signature is bare — `public func get(&self, index: Int) unsafe -> T?`
  (`sawc/std/vector.saw:91`) — and the body returns `buf[index]`, a bitwise read
  through the raw pointer with no retain. For an ImplicitCopy element the
  surrounding machinery balances it; for a **NoCopy** element there is no
  `copy()` to call, so the caller receives an alias it then OWNS and DROPS,
  while the vector still holds the same element. Every lookup frees it again:

  ```saw
  struct Item { name: String, payload: Vector<Int> }

  extension Item: NoCopy {
      func deinit(&var self) { print("Item.deinit {self.name}") }
  }

  extension Item {
      init(n: String) -> Item {
          var v = Vector<Int>()
          v.push(41)
          Item(name: n, payload: move v)
      }
  }

  struct Box2 { items: Vector<Item> }
  extension Box2: NoCopy {}

  extension Box2 {
      init() -> Box2 { let v = Vector<Item>()  Box2(items: move v) }
      // `get` on a NoCopy element compiles. It should not.
      func find(&self, want: String) -> Item? {
          var i = 0
          while i < self.items.len() {
              if let e = self.items.get(i) {
                  if e.name.equals(want) { return e }
              }
              i = i + 1
          }
          None
      }
  }

  func main() {
      var b = Box2()
      b.items.push(Item(n: "one{1}"))
      if let first = b.find("one1") { print(first.payload.len()) }
      if let second = b.find("one1") { print(second.payload.len()) }
  }
  // Item.deinit one1   <- the first alias frees the payload buffer
  // Item.deinit one1   <- the second frees it AGAIN; the vector still holds it
  ```

  Two lookups, two frees of one `Vector<Int>` buffer, no `unsafe` anywhere. It
  does not crash today only because the freed block is usually not reused before
  the process exits. libs/toml is built on this alias (`TomlDoc.get_section`,
  `TomlSection.get_table`, `TomlTable.get`) and so is blade's manifest reader.

  This is also what blocks **DF-128c** above: the missing `Vector<T>`-field drop
  glue is the second half of a cancelling pair, and fixing either alone breaks.
  FIX WANTED, as one brief: give `get` the bound the docs already claim it has
  (the saw-lang skill says "`Vector.get(i)` returns a COPY (needs copyable
  element)"), decide what replaces it for NoCopy elements (a `with_ref`-shaped
  scoped borrow, an index-returning lookup, or `ExplicitCopy` on the toml
  types), migrate libs/toml + blade, and land DF-128c's drop-glue fix in the
  same change. Repros: `.build/scratch/p132_h_alias.saw`,
  `.build/scratch/p132_h_uaf.saw` (gitignored; inlined above).
- **RS-3 — FIXED (design 124, Aug 5).** A task's owned values are now released
  when THE TASK completes: the coro transform synthesizes a `__release` per
  frame and calls it at every `return Done` site, dropping params and
  across-suspend locals in the same LIFO order an ordinary scope exit uses
  (including a frame-resident nested `TaskGroup`, whose own children are
  structured-joined first). The result slot is the single exception — `join()`
  moves it out, or the frame drops it once at group teardown. Both proven
  defects are gone and fenced by tests that HANG on the pre-124 compiler:
  `net_sibling_eof_no_deadlock` (the EOF pattern) and
  `net_accept_loop_eager_fd_close` (the README server, client-observed EOF as
  the fd oracle). Resource accounting is covered by
  `taskgroup_eager_teardown{,_live_count,_mt}` (baseline leaked 8, and the MT
  group accumulated across waves) and the double-drop edges by
  `taskgroup_result_{joined,unjoined}_once`. Landing it required making
  frame-field ownership honest — see DF-124a. Six existing deinit-oracle tests
  were re-baselined to the eager ordering. Original finding follows: TaskGroup
  is a lifetime EXTENDER, not a scope. Task-owned values are released at group
  teardown, not task completion — the README's own accept-loop server leaks one
  fd + frame per connection for the group's life, and the sibling reader/writer
  EOF pattern deadlocks (verified hang). Contradicts the
  deterministic-destruction claim. [design-claims #1]
- **RS-4 — FIXED (design 122 unit C, Aug 4; commit facebad).** `Command` holds
  `args: Vector<String>` and spawns a real argv through three additive seams
  (`__saw_rt_proc_spawn`/`_read_stdout`/`_wait`, fork + execvp in
  rt/common/proc.saw, documented in rt/ABI.md). No shell sees the bytes, so
  there are no quoting rules to get wrong; `wait` returns the RAW POSIX status
  so signal death cannot read as exit 0. Original finding follows:
  `std.process.Command` is `system()` string-concat with no quoting —
  `arg("; echo INJECTED")` executes; `arg("one two")` word-splits.
- **RS-6 — FIXED (design 122, Aug 5).** `Vector.with_ref`, `with_var_ref` and
  `swap_out` now check `0 <= index < length` and panic on a miss — the same
  always-on bounds check indexing has, carrying (since unit I) the same
  `panic at FILE:LINE:` prefix. The location names vector.saw rather than the
  caller: Saw has no caller-location facility, so each message names its METHOD
  (`Vector.swap_out: index out of range`) to stay diagnosable. `set` filters the
  index itself before delegating to `swap_out`, so its documented
  no-op-when-out-of-range contract is UNCHANGED — asserted by
  examples/vector_set_oob_still_noop.saw, since a panic leaking through that
  delegation would have been a silent behavior break. `String.byte_at`'s unit-A
  message was re-worded from "out of bounds" to "out of range" so one failure
  class reads one way. Tests
  examples/vector_{with_ref,with_var_ref,swap_out}_oob_panic.saw, each verified
  failing before the fix (the OOB read returned 0 and exited 0, exactly the
  probe). M5's tolerant `set`/`swap` and M3's clamping `substring` were NOT
  covered here and are now CLOSED by design 130's accessor rule (both panic);
  this closed only the three UNCHECKED accessors. Original finding (lead probe, Aug 4; the review under-rated it as
  M5/medium) follows: they checked only that the buffer is non-null, so an
  arbitrary `Int` index reached `buf[index]` through a `public`, non-`unsafe`
  signature — the same shape as the C4 `byte_at` bug filed critical, in the API
  the skill and design 122 unit A both name as the sanctioned way to reach
  `NoCopy` elements. `swap_out` was worse than C4: an out-of-bounds **WRITE**,
  i.e. heap corruption from fully safe code. PROVEN on main
  (`.build/scratch/wr_oob.saw`, 2-element `Vector<Int>`):
  ```
  len = 2
  with_ref(99) = 0            // OOB read, exit 0, silent
  swap_out(99) returned = 0   // OOB WRITE of 7 past the end, exit 0, silent
  ```
- **RS-5 — FIXED (3 of 4 in design 122 unit D, Aug 4, commit 3aabc9f; the
  fourth in design 132 unit A, Aug 5).** A bare `{ }` statement, a builtin
  redefinition and `let n = <Void expr>` are all clean errors now. The FOURTH —
  an escaping closure's captured mutable state resetting per call — is closed
  the way the user decided: the WRITE is rejected, so the silent-wrong-answer is
  gone rather than papered over (see **DF-122a** below). Original
  finding follows: silent-wrong-answer holes (vs the never-hide-errors rule): a
  bare `{ }` statement is a discarded uncalled closure (statements never run, no
  warning); an escaping closure's captured mutable state resets per call
  (`make_counter()` → 1,1,1); a user `func print`/`assert` is silently
  dropped; `let n = <Void expr>` typechecks then ICEs with an empty message.

**P1 — compiler bugs found by review:**
- **RC-1 — FIXED (design 122 unit E, Aug 4; commit a904bcb).** Root cause was
  not a hardcoded name list: the docs path type-checks with `object_only=True`,
  so the whole-program effect FIXPOINT never ran and every `SuspendNode.suspends`
  bit was still False. `finalize_effects()` now runs on the docs path and
  `_effect` consults the program's own graph first (the std sets remain the
  documented fallback for bodies this typechecker never checks). Golden test
  examples/doc_emit_effect.saw covers direct, TRANSITIVE, plain-sync and
  declared-`sync`. Original finding follows: `--emit-docs` labels every
  suspending USER function `"sync"` (only hardcoded std names emit
  `"suspending"`, docs_emit.py) — design 121 bug.
- **RC-2 monomorphization misses grafted types**: `substitute_ast_types` walks
  `dataclasses.fields()` only, so ~10 runtime-grafted `SawType` annotations
  survive un-substituted (compiler-preport hazard 1; live bug).
- **RC-3 — FIXED (design 127, Aug 5).** The coroutine transform charges every
  loop iteration of a task body against a frame-resident counter: each loop gets
  `__saw_loop_budget = __saw_loop_budget &- 1; if __saw_loop_budget <= 0 {
  __saw_loop_budget = 128; yield_now() }` prepended to its body, over a
  `var __saw_loop_budget: Int = 128` at the body top. Ordinary Saw — the existing
  frame-local collection makes the counter a field and the existing splitter
  handles the suspending `if`, so nothing downstream is special-cased. Top of the
  body rather than after the last statement, so a `continue` reaches it. A body
  that used to compile as a straight sync run-to-completion frame becomes
  suspending, which is how it gains a place to yield. Scope: entry-module task
  bodies, the suspending callees the transform embeds, entry-module driven
  methods. Four documented bounds — a SYNC callee is not instrumented; a `for`
  over a non-range iterable is not (nor any loop nested inside it — `_split_for`
  can only state-split a range `for`, and instrumenting one would turn working
  programs into compile errors); a closure body is not; std's io loops keep the
  89-c charge. Cost measured before any tuning, per the brief: 1.53x on 200M
  iterations of an LCG chain in a spawned task (194 ms -> 296 ms, arm64), nearly
  all of it the loop joining the frame's state machine rather than the check;
  the wrapping `&-` instead of a checked `-` is worth 1.74x -> 1.53x. No gating
  on provably-finite loops — the shape that starves (`while i < n`, runtime `n`)
  is exactly what such an analysis cannot prove finite. Tests
  examples/taskgroup_compute_preemption{,_mt}.saw and
  examples/taskgroup_budget_loop_semantics.saw. Original finding follows:
  op-budget does NOT stop a pure-compute spinning task — starves siblings
  completely; README claims otherwise. (Budget counts only I/O-ish ops.)
- **RC-4 — FIXED (design 122 unit I, Aug 5).** Every compiler-raised panic now
  carries the design-69 `panic at FILE:LINE: ` prefix: overflow, division by
  zero, shift range and bounds gained a location they never had, and
  force-unwrap / `try!` gained the file half (their bespoke `... at line N`
  texts are gone). The location folds into the message constant — now interned
  by text through `_raw_bytes_ptr` — so a site still lowers to one constant and
  one `saw_panic` call. LINE is the TRAPPING EXPRESSION's line: threaded from
  the AST node where the check has one (binary/unary ops, index, `!`, `try!`),
  else the line of the statement being lowered, tracked per llvm FUNCTION
  (`_di_stmt_lines`) so a nested body cannot bleed its line onto its parent; a
  closure inherits its enclosing function's basename so the FILE:LINE pair stays
  consistent in a multi-module build. One format in both profiles — a
  freestanding FILE gate was measured and rejected: it saves only
  `len(basename) - 4` bytes per site, because the size cost is per-site LINE
  uniqueness, which the brief keeps unconditionally. Numbers: SOS M0 kernel
  unchanged at 1420 text / 168 rodata (it has no runtime-check panic sites at
  all); a synthetic 30-distinct-site freestanding riscv32 kernel 2224 -> 3181
  text (+957 rodata), of which the FILE half is 482. Tests
  examples/panic_location_{overflow,bounds,divzero,shift}.saw. Original finding
  follows: overflow/bounds/div-zero/shift have no location at all;
  force-unwrap/`try!` lack the file.
- **RC-5 — FIXED (design 122 unit H, Aug 4; commit a5f36c1).** The driver
  refuses `--freestanding` at a Mach-O EFFECTIVE triple up front, before any
  codegen, and names the ELF cross-targets to pass instead — replacing the
  uncaught LLVM abort over design 112's per-function `.text.<name>` sections
  (which Mach-O rejects) and the 0-byte object it left behind. Test
  examples/errors/freestanding_macho_target_rejected.saw names the triple
  explicitly, so it asserts the same thing on every host. Original finding
  follows: `--freestanding` on the Mach-O host dies as an uncaught LLVM ERROR
  abort (ELF cross-targets fine).
- (Re-confirmed, already open: DF-119b `print(UInt)` renders signed.)

**P2 — CLOSED. Portability (SOS-relevant): the two hardcoded numbers were fixed
by design 122 unit F (Aug 4, commit 6c29cfa); the design-92 half-application in
std.file/std.directory is finished by design 132 unit G (Aug 5).**

Unit G's half: `File.open`/`create`/`open_append` -> `Result<File, IoError>`,
`File.read` -> `Result<Data, IoError>` (an empty Ok means the file had nothing
left — distinct from a failure, which used to share `None` with it and with
"the allocation failed"), `File.write` -> `Result<Int, IoError>`,
`File.seek_start`/`seek_current`/`seek_end`/`position` -> `Result<Int, IoError>`,
`Directory.list` -> `Result<Vector<Path>, IoError>`. `Directory.current` stays
`Path?` on purpose: `None` there means getcwd(2) failed, and unit F removed the
truncation that used to share that answer. `File.exists`/`Directory.exists` stay
`Bool` — genuine boolean questions.

That needed new seams, because std had no way to read the CAUSE: `open`, `read`,
`write`, `lseek` and `opendir` were bare libc calls, and rt/ABI.md forbids std
from calling `__saw_rt_last_syserror` after one (errno may already be clobbered).
Five additive `__saw_rt_fs_*` seams now carry it, on the design-117 convention —
the natural non-negative result or `-tag` — with `opendir` taking a status
out-parameter because a `DIR*` cannot fold a tag into its return. ABI.md
documents them and gains an additions-since-v2 table.

Call sites migrated: blade (builder, main, manifest, resolver, lock, tester),
selfhost/lexer, and three examples. Two of them were silently discarding a
failure and no longer can — `write_lock` returned `true` without checking the
write, and blade's build-hash stamp ignored both halves. Note for anyone doing
this again: Saw has no `if let` over a Result, so every site became `match` or
`try`, and a `return` inside a match arm needs its own block.

Unit F's half (design 122): the dirent offset moved behind the host split as
`__saw_rt_fs_dirent_name` (macOS 21 / Linux 19, rt/ABI.md documents the additive
seam) and `Data` uses `sizeof<DataBuffer>()`/`alignof<DataBuffer>()` instead of
a literal 24 — the riscv32 block is 12 bytes, so it had been over-allocating and
then handing the allocator a size that was a lie. Test
examples/directory_list_names_exact.saw round-trips a file it creates itself, so
a wrong offset fails on ANY host.

**P3 — docs debt (20 findings): CLOSED (design 125, Aug 4).** 18 of the 20
were doc fixes and all landed; findings 3 (`--emit-docs` effect field) and 5
(`print(UInt)` renders signed) are compiler bugs the docs describe correctly,
owned by design 122 units E and G. README is current through 121 and now joins
the docs-update convention (CLAUDE.md workflow section); "no hidden
allocations" names its two exceptions. Appendix A picked up two names the
review missed (`deinit`, `Self` were listed reserved and are not). Left
untouched on purpose: the op-budget claim (127) and the `panic at FILE:LINE:`
claim (122 unit I), both being made true rather than softened. Both are now
true; 127 added the qualifying clause that says HOW (loop iterations of a task
body are charged).

**Follow-up filed by design 127:** the compute budget cannot reach a loop the
coroutine transform cannot state-split. `_split_for` rejects a suspension inside
a `for` over a NON-RANGE iterable ("use a `while` loop"), so 127 skips such a
loop and everything nested inside it — instrumenting one would turn working
programs into compile errors. A long `for x in v.iter()` in a task body
therefore still starves siblings. Lifting it means teaching `_split_for` to
state-split an arbitrary iterator (hold the iterator in the frame and split
around `next()`), which also retires the existing rejection. Same shape, lower
value: a compute loop inside a SYNC callee is likewise unreachable — that one
wants the instrumentation to follow sync call edges out of a task body, which
would make sync helpers suspending and needs a design decision first. [127]

**Follow-up filed by design 130 (now OPEN — 130 landed Aug 5):** decompose the
oversized functions the unsafe migration marked wholly-unsafe —
`__saw_exec_worker` (~150 lines), the `rt/host_*/reactor.saw` bodies,
`rt/common/os_ops.saw` (15 of the runtime's 47 marks on its own) — so the "an
unsafe function is short enough to review as a unit" policy is actually true.
Shape: extract the raw-pointer bookkeeping into small `unsafe` helpers and leave
the surrounding loop safe. Deliberately NOT in 130 (mechanical migration kept
separate from judgment-heavy refactoring of the executor's hot paths). [130]

**P4 — design/gap briefs to consider:** ~~structural `Deinit`/`ExplicitCopy`
synthesis~~ DONE (design 128: deinit is implicit, copy/equality derivations are
`@synthesize`-gated); ~~DF-121a newline-in-brackets~~ (LANDED as design 129,
Aug 5 — the 210-char `blade/src/resolver.saw` signature that was the evidence
is now wrapped); std gaps ranked G1 bit intrinsics (S–M), G2
checked/saturating arithmetic (S, tracker already wants it), G3 slices
(L, language-level), G4 radix/hex formatting (S), G5 iterator adaptors (M);
compiler pre-port restructures R1 declared AST contract + R2 stable NodeId +
R11 astdiff oracle as the port-order prerequisites (then AST+parser next,
coro_transform last).

**~~P4 — element places / generalized accessors~~ PROMOTED to design 141
(user, Aug 5): `borrows` effect-slot keyword + `lend` bodies; queued after
139.** Original entry follows:
**(user question, Aug 5):**
`with_ref`/`with_var_ref` are `_read`/`_modify` accessors spelled as closure
ceremony because indexing yields VALUES, not places. The successor design:
`v[i]` becomes a PLACE backed by the existing scoped-borrow machinery, with
shared-vs-exclusive picked from the USE SITE (`v[i].n += 1` borrows `&var`;
`print(v[i].n)` borrows `&`) — Swift's accessor model, built on design
131's place vocabulary. SUBSUMES the with_ref pair (they become the
lowering) rather than deduplicating it; adjacent to G3 slices (also wants
place semantics). Considered and REJECTED: mutability-generic parameters
(`<M: mut>` — a new generic kind threading through exclusivity/inference/
monomorphization for a handful of std pairs; Rust lived without it, D's
`inout` is a cautionary tale) and name-overloading the pair (unannotated
closure params make the overload solver tie, forcing per-site annotations).
Until then the pair stands as the honest Rust-`_mut`-style convention.

**P4 — coro frame-size optimization (user idea, Aug 5):** today the flat
frame gives every driven CALL SITE its own embedded sub-frame field, so a
task pays the SUM over all sites even though only one nested chain is ever
live at once. Because suspending recursion is banned, the high-water mark
(the deepest simultaneously-live drive chain) is statically computable —
sub-frames with disjoint lifetimes (sequential drives, if/else branches)
can be OVERLAID union-style at fixed offsets, shrinking `sizeof(frame)` to
exactly the high-water mark with zero runtime cost (keeps one-allocation-
at-spawn, zero-alloc suspend, pinned frames — the design-91 wake token and
design-88 interior pointers need frames that never move, which rules out a
DYNAMIC grow/shrink frame stack unless chunked). Companion to design 44's
noted live-range packing of locals; do both in one sizing brief.

- **DF-125a — FIXED (design 133 unit B, Aug 5).** The stage-2 lowering lifts a
  suspension-spanning value-conditional out of a NESTED expression position into
  its own `let __vchN = <conditional>` — the outermost form it already lowered to
  a branch shape — and reads the temp in its place. Laziness survives by
  construction (the temp's own lowering is the guard), nesting recurses because
  the hoist re-enters `_vc_stmt`, and the blocking-extern variant rides along.
  `_anf_children`'s child-position dispatch was factored into
  `_map_uncond_children` so both passes walk the same positions in the same
  order. Tests: `examples/expr_suspend_nested_shortcircuit.saw` (argument,
  operand-in-`return`, under `not`, doubly nested, interpolation, each with the
  RHS-skipped counter assertion) and `examples/expr_suspend_nested_blocking.saw`.
  The spec + skill limitation notes design 125 added are deleted. Original
  finding follows: **design-120 short-circuit nesting limit (found by design
  125, Aug 4).** A suspending call in a `??`/`&&`/`||` operand
  transforms only when the short-circuit operator is the OUTERMOST expression
  of its statement. `let x = a ?? slow()`, `return a ?? slow()` and a tail
  `a ?? slow()` all work; `return 1 + (a ?? slow())`, `f(a ?? slow())` and
  `not (a && slow())` hit "appears in a nested/expression position". Same for a
  blocking extern, with its own diagnostic. Errors cleanly and never blocks
  silently, so this is a capability gap, not a correctness bug — design 125
  documented the limit on both the spec and the skill rather than paper over
  it. Repros: `.build/scratch/d125_120_return.saw`, `d125_120_return2.saw`,
  `d125_120_shortcircuit.saw`, `d125_blocking_sc.saw` (gitignored; the shapes
  are inlined above). Worth a follow-up brief if the ANF hoist can be taught to
  lift a nested short-circuit.

## Design 145 — DF-findings (enum methods; the std private-symbol reach)

- **DF-140h — FIXED here (unit A). Originally filed on the parked SOS M1
  branch's tracker during the round-3 module-system stress; refiled in main's
  tracker as found-and-fixed, same as DF-140f before it.** A module-PRIVATE
  `static` inside a std FILE reserved its simple name for every Saw program.
  A five-line hello-world declaring `static ASCII_ZERO` was rejected with
  "static `ASCII_ZERO` is defined multiple times" — against a private constant
  in `sawc/std/stringbuilder.saw` the author cannot see, import, or find. No
  dependency involved.

  A sweep found the blast radius is the whole set, not one name: every private
  std static tested was reserved — `ASCII_ZERO`, `MINUS_SIGN`, `MARKER_LEN`,
  `MIN_FIXED_CAPACITY` (stringbuilder), `SEEK_SET`/`SEEK_CUR`/`SEEK_END`,
  `O_RDONLY`, `MODE_RW_R_R` (file), `AF_UNIX`, `SOCK_STREAM`, `READ_CHUNK`,
  `INVALID_FD`, `NET_ERROR` (net), `GETCWD_MAX_BYTES` (directory),
  `EXEC_FAILED_CODE`, `PROC_READ_CHUNK` (process). Exactly the names a systems
  program wants for its own constants.

  Cause — and it is NOT the one the brief predicted. Private std statics already
  carried DF-140f's module-qualified codegen symbol (`saw.static.ASCII_ZERO$m$
  std_stringbuilder`), so the LLVM half was never broken. The break was the
  NAMESPACE half: `Namespace.statics` is one flat dict keyed by simple name, and
  std is merged wholesale into every module's namespace, so a private std static
  occupied the shared slot and `_register_static`'s duplicate check hit it.
  Design 82 gives each std file its own module identity; the namespace had not
  been taught to use it.

  Fix: private statics of a non-root module live in a per-module overlay
  (`Namespace.module_statics`, keyed by defining module then name) instead of
  the shared `statics` slot, and every lookup is asked FROM a module
  (`get_static(name, module)` / `has_static(name, module)`, threaded through the
  five typechecker call sites via `_accessor_vis_module()`). The accessor
  module's own privates win, so std keeps reading its own constants — the
  non-regression the tests pin. Public and root-module statics are untouched, so
  a genuine cross-module public ambiguity is still reported. Regressions:
  `examples/df140h_std_private_static.saw` (the repro, plus digit rendering
  through std's own `ASCII_ZERO`),
  `examples/df140h_std_private_static_two_files.saw` (three std files' privates
  in one program, with `std.net` imported and exercised). The design-142
  collision tests are unchanged.

- **DF-140h-fn — OPEN, stopped deliberately (unit A, design 145). Wants its own
  brief.** The same reservation exists for private std FREE FUNCTIONS, and the
  fix is a materially bigger change than the statics half. Repro:

  ```saw
  func tcp_socketpair() -> Int { 77 }   // private in sawc/std/net.saw
  func main() { print(tcp_socketpair()) }
  // error: function `tcp_socketpair` is already defined with an
  //        indistinguishable signature
  ```

  Also `unix_timestamp` (std/time.saw — which is separately worth a look: it is
  a DOCUMENTED std.time API function declared without `public`). The
  `__saw_exec_*` family in std/taskgroup.saw is worse than reserved: redefining
  one reports `internal compiler error: Undefined function: __saw_exec_run`
  rather than any diagnostic.

  Why it did not land with the statics half: statics have one identity (a name),
  so a per-module overlay is contained. Functions carry OVERLOAD SETS, and
  design 55/66/105 built the `$OL$` symbol scheme assuming one flat set per
  name. Filtering the set by accessor module was tried and gets the front end
  right, but two same-named functions from mutually-invisible modules then reach
  codegen as one overload set and ICE (`internal compiler error:
  tcp_socketpair$OL$`). Doing it properly means making overload-set IDENTITY
  module-scoped — a per-module overlay for private functions, a std-side
  symbol-stamping pass (`_stamp_module_private_functions` runs only from
  `check_module` and guards on `def_module == own_module`, so std never reaches
  it), and a decision about whether a module's private function overloads with a
  public one visible in that module. That is a design question design 145 does
  not settle, so the front-end change was reverted rather than landed half-done.

## Design 142 — findings (import-scoped extensions; conformance coherence)

- **DF-142-leak — FIXED by design 142 (the brief's own proving repro).** Any
  module in the link injected its `public` extension methods onto a type for the
  whole program. `main` imported `amod` only; `bmod` (reached transitively
  through `amod`) declared `public extension Data { func u16_at }`; `main`
  compiled AND RAN `d.u16_at(0)`, printing `leaked: 4660`. One module could
  monkey-patch a type for every consumer, with silent cross-dependency
  collisions and an add-a-dependency-changes-resolution hazard behind it.
  Lookup now consults the current module, the file's DIRECT imports, and the
  receiver type's own module; the transitive case is a clean error naming the
  module to import. Regression: `examples/ext142_transitive_leak_error.saw`
  (plus `ext142_direct_import` for the positive side).

- **Sweep result (Aug 5): ZERO migration**, as the brief predicted. All 416
  conformances across `blade/`, `libs/`, `selfhost/`, `sos/`, `examples/`,
  `sawc/std/` and `builtin.saw` were checked: no orphans (412 declare the type
  locally; the other 4 declare the trait locally — `extension Int/Float:
  Fooable` in the file declaring `Fooable`). Only 13 of 601 extensions target a
  foreign type, and the single user-code cross-package case, blade's
  `public extension Path { public func ensure_dir }`
  (`blade/src/layout.saw:35`), is called only inside its own module. Two notes
  for anyone touching this again: `Allocator` lives in `sawc/std/alloc.saw`,
  NOT `builtin.saw`; and a type-declaration grep must accept the `unsafe`
  prefix (`unsafe struct UnsafeMmioReg`) or it reports false orphans.

- **std is ONE scoping domain, deliberately.** Design 82 makes each std file its
  own module, but std files extend each other's types on purpose —
  `sawc/std/string.saw:932` defines `join` on `Vector<String>`, whose type lives
  in `sawc/std/vector.saw`. A literal reading of rules 1-3 would have demanded
  `import std.string` to call `v.join(", ")`. The scope predicate exempts
  `("<std>", *)`; the prelude rules already govern which std NAMES a file may
  write unimported.

- **DF-140f — FIXED here (originally filed on a parked SOS branch; refiled in
  main's tracker as found-and-fixed).** A module-PRIVATE `static` in a
  dependency collided with a same-named static in the importer —
  "ambiguous static `PT_LOAD`: defined in both `dep` and `<entry>`" — even
  though neither module can see the other's. Private extension methods stayed
  correctly invisible, so the hole was in top-level declarations. A fresh sweep
  found private FUNCTIONS had it too. Every private constant (and helper) in a
  dependency was a reserved word for its consumers.

  Cause: the typechecker resolves against the importing module's own namespace,
  which never received the private symbol, so name resolution was always right.
  Codegen works from ONE merged namespace keyed by simple name, so the two
  definitions landed on one key, and the merge reported that to the author as
  their ambiguity. Fix: private statics and private free functions in non-root
  modules take a module-qualified codegen symbol (`$m$<module>`), the merge stops
  flagging a collision it no longer has, and identifier references carry the
  resolved static symbol so codegen loads the right global. Public declarations
  are untouched — they are importable by simple name, so two under one name is a
  real ambiguity and still reported. Regression:
  `examples/df140f_private_static_collision.saw`; the public-collision tests
  (`test_static_collision`, `module_import_collision`) still pass.

- **DF-142a — APPROVED (user, Aug 5): design 144 owns the fix**
  (module-qualified type identity end to end; queued after 138). Original
  finding follows: **Private TYPES still collide across modules.**
  Two modules each declaring a private `struct Header` is still
  "ambiguous struct `Header`: defined in both `dep` and `<entry>`", the same
  shape as DF-140f. It was left out of that fix deliberately: a static's or
  function's codegen identity is a symbol NAME, which is why module-qualifying
  it was contained. A type's identity is threaded through `SawType.struct_name`,
  `Codegen.struct_types`, monomorphization keys and method mangling
  (`Struct_method`), so module-qualifying it is a structural change. Suppressing
  the report WITHOUT that change would be worse than the error: codegen would
  emit one layout under the shared name and silently miscompile the other
  module's code against it. The error stays until the identity change is done.
  Repro (two files):

  ```saw
  // dep.saw
  struct Header { kind: Int }
  public func dep_kind() -> Int { 1 }

  // main.saw
  import dep.{dep_kind}
  struct Header { kind: Int }
  func main() { print(dep_kind()) }
  // error: ambiguous struct `Header`: defined in both `dep` and `<entry>`
  ```

  Same hole for private enums, traits and type aliases (the merge treats all
  five categories alike). Wants its own brief.

## Design 137 — DF-findings (fixed-capacity formatting)

**Deny window REMOVED.** Design 123's `__saw_rt_alloc_deny_after(allow, deny)`
lost its second parameter: the bounded window existed only because a panic
assembled its message into a fresh allocation, so blanket denial swallowed every
panic message. Panic messages come off the stack now
(`alloc_panic_under_full_denial` is the test 123 could not write), and the four
OOM-panic tests that used the window run under blanket denial and still report
their real messages. Denial is a plain MODE; a test that keeps running past its
failure calls `deny_after(-1)`. ABI.md and `sawc/rt/common/mem.saw` updated.

**Storage mechanism chosen: a caller-provided pointer + a compiler-allocated
scratch.** `StringBuilder(bytes: UnsafePointer<Int8>, capacity: Int)` is the Saw
surface, and `print`/`panic`/`assert` alloca their scratch in CODEGEN. Both of
the brief's nicer options are unwritable today — see DF-137a and DF-137b — and a
shared `static` scratch was excluded by the brief (MT groups exist; the panic
path must be per-stack). The generics model was not touched.

- **DF-137a — FILED, not fixed (found probing design 137's storage question,
  Aug 5). There are no VALUE (const) generics, so a capacity-generic
  `FixedStringBuilder<N>` is unwritable — and the near-miss spelling is accepted
  in SILENCE.** `struct FixedBuf<N: Int> { len: Int }` compiles: the parser reads
  `N` as an ordinary type parameter and `Int` as its bound, and a bound naming a
  non-trait is never checked. The declaration is then unusable from both sides:

  ```saw
  struct FixedBuf<N: Int> { len: Int }
  extension FixedBuf<N> {
      func cap(&self) -> Int { N }     // error: undefined variable `N`
  }
  func main() {
      let f = FixedBuf<16>(len: 0)     // error: undefined variable `FixedBuf`
      print(f.cap())
  }
  ```

  Two gaps, one cheap and one not. (1) No const generics — the feature. (2) A
  type-parameter BOUND naming a non-trait is silently accepted, so the diagnosis
  surfaces at the use site as "undefined variable" instead of at the declaration
  as "`Int` is not a trait". (2) is what makes (1) read as a compiler bug rather
  than a missing feature, and is worth fixing on its own.

- **DF-137b — FILED, not fixed (same probe). A LOCAL fixed array cannot be
  zero-initialized, so caller-provided stack scratch is only writable at tiny
  sizes.** A `static` may be declared bare and lands zero-initialized in .bss
  (LANGUAGE_SPEC.md:3360), but a local may not, and there is no repeat literal:

  ```saw
  func main() unsafe {
      var scratch: [Int8; 256]              // Parse error: Expected '=' in
                                            //   variable declaration
      var other: [Int8; 256] = [0; 256]     // Parse error: Expected ']' after
                                            //   array elements
  }
  ```

  The only spelling that works is 256 literal zeros. This is why
  `StringBuilder(bytes:capacity:)` takes an `UnsafePointer<Int8>` rather than a
  `&var [Int8; N]`, and why the panic/print scratch is allocated by the COMPILER
  rather than in Saw: a stack buffer of a useful size is not writable in the
  language today. A `static` is not the answer — the panic path must be MT-safe.
  Either half would close it: bare local declarations (matching statics), or a
  `[0; N]` repeat literal.

- **DF-137c — FIXED here (found writing `StringBuilder.append(value: UInt)`).
  A platform `Int`/`UInt` overload pair was ambiguous at EVERY call site.**
  Platform `Int` and `UInt` are mutually compatible in `_types_compatible` so an
  unsuffixed literal can initialize either (design 53). Overload ranking had no
  exactness tiebreak, so both candidates scored equally even where one was an
  exact match:

  ```saw
  func take(value: Int) -> String { "int" }
  func take(value: UInt) -> String { "uint" }
  let i: Int = 5
  take(i)   // was: ambiguous call to `take`: multiple overloads match (Int)
  ```

  Free functions and methods alike; the pair was simply unwritable, which
  blocked the unsigned append overload the alloc-free path needs (the signed one
  cannot represent the top half of `UInt`). Fixed with a penalty in
  `_resolve_overload` limited to the platform `Int`/`UInt` pair. Deliberately
  narrow: a bare literal's WIDTH stays flexible, so `h(Int)` vs `h(Int8)` called
  `h(5)` remains the design-55 ambiguity (`overload_call_ambiguous_error` still
  passes — 5 really could be either). Test: `overload_int_uint_exact`.

- **DF-137d — FILED, not fixed (found dogfooding the SOS kernel, Aug 5). An
  integer literal is NOT range-checked against a 32-bit platform `Int`.**
  LANGUAGE_SPEC promises a bare literal is range-checked at the literal against
  its expected fixed-width type, and design 47 makes platform `Int` 32-bit on
  riscv32. `0x80000000` exceeds `Int.max` there and is accepted anyway, wrapping
  to `-2147483648`:

  ```saw
  static BIG_STATIC: Int = 0x80000000     // accepted; wraps negative
  @export("kmain")
  func kmain() {
      let big_local: Int = 0x80000000     // accepted; wraps negative
      print("{} {}", BIG_STATIC, big_local)   // -2147483648 -2147483648
  }
  ```

  Built with `--freestanding --target riscv32-unknown-none-elf`. This bites the
  exact audience the freestanding profile is for: an address constant is the
  most ordinary thing a kernel writes, and `0x80000000` is QEMU `virt`'s RAM
  base. Surfaced because the SOS kernel's first formatted log line printed its
  RAM base as a negative number. Worked around correctly rather than papered
  over — `Region` holds `UInt`, which is what an address is — but the literal
  check should reject the signed spelling instead of wrapping it. The likely
  cause is that the literal range check does not know the target's platform
  width. Repro: `.build/scratch/probe_range32.saw` (gitignored; inlined above).

- **Follow-up (not a bug): the `{}` Printable scratch is per call site.** Each
  user-`Printable` format argument gets its own 512-byte entry alloca, because
  every segment of a `panic` message is built before any is concatenated — two
  arguments sharing one buffer would print the second value twice
  (`format_args_panic` pins this with two of them). Across SEPARATE format calls
  the buffers could be shared, since each call consumes its segments before the
  next runs, so a function with N such arguments costs N x 512 bytes of stack
  where it could cost (max args in one call) x 512. Not pooled here: the win is
  bounded and the failure mode of getting it wrong is silent wrong output. Worth
  doing for the embedded profile, ideally alongside LLVM lifetime intrinsics so
  stack coloring can do it rather than the frontend.

- **`--target-features` added (not a finding, a gap closed).** sawc passed only a
  triple, which names an architecture but not which optional extensions the part
  has. The SOS kernel built its C half `-march=rv32imac` and its Saw half as base
  rv32i, where there is no divide instruction — so the first kernel log line
  carrying a number failed to link on `__divsi3`/`__modsi3`/`__udivsi3`, libcalls
  the freestanding profile has no library to satisfy. The flag is explicit rather
  than a riscv32 default: which extensions a part has is the board's fact.
  `tools/sos_runner.py` passes `+m,+a,+c`, derived from the `-march` it already
  used for clang.

## Design 133 — DF-findings (capability completions)

- **DF-133a — DECIDED (user, Aug 5): FIX THE TRANSFORM (fork i) — design 147
  owns it.** The hoist preserves source evaluation order by lifting
  side-effecting left siblings into temps, bounded by a conservative purity
  filter (literals/plain reads exempt; anything containing a call or `&var`
  use hoists); transfer checkpoints and diagnostics KEEP source positions
  (the 120 temp machinery's discipline). Fork (ii) — documenting the reorder
  — rejected: it poisons the `v.pop()!`/`v.len()` class forever. Original
  finding follows: **(found while implementing design 133 unit B, Aug
  5; PRE-EXISTING, design 120). The stage-1 ANF hoist reorders a suspending child
  ahead of a side-effecting SYNC sibling to its left.** `_anf_children` walks
  child positions left to right and lifts only the children that span a
  suspension; a sync sibling stays in place, so the lifted `let __anfN = ...`
  lands ahead of side effects that source order puts first:

  ```saw
  func slow(n: Int) -> Int { yield_now()  print("slow")  n * 2 }
  func noisy(n: Int) sync -> Int { print("noisy")  n }
  func add(a: Int, b: Int) sync -> Int { a + b }

  func body() -> Int {
      let r = add(noisy(1), slow(3))     // prints "slow" then "noisy"
      r
  }                                      // spawned; the hand-unchained spelling
                                         // prints "noisy" then "slow"
  ```

  This contradicts what LANGUAGE_SPEC.md claims for design 120 ("evaluation
  order, the deinit timing of the intermediates, and the ownership rules are the
  ones the hand-unchained spelling gets"), so either the transform or the
  sentence is wrong. Silent, not diagnosed.

  NOT fixed here because the repair is out of unit B's scope and has a real blast
  radius: preserving order means hoisting every side-effecting sibling to the LEFT
  of a lifted child into its own temp, which changes emitted IR for a large slice
  of the suite (the irdet/astdiff gates), and hoisting an owned operand into a
  temp moves the transfer checkpoint — a `move v` or an ExplicitCopy argument
  would be checked at a different point than the user wrote it. Deciding which
  siblings are "side-effecting" enough to hoist is the design question. Design
  133 unit B inherits the behavior rather than adding to it: a nested
  short-circuit is lifted on the same terms as the calls stage 1 already lifts.
  Repro: `.build/scratch/d133_order.saw` (gitignored; inlined above).

## Design 139 — DF-findings (the enum policy tier)

- **DF-139a — FILED, not fixed (found while implementing design 139, Aug 5;
  PRE-EXISTING and INDEPENDENT of the copy tier). Overwriting a binding
  RELEASES its old value even when a live copy of it exists**, so the copy is
  left dangling. The copy tier is not involved: it reproduces on a plain
  `String` field, on a `String?` field, and on an undeclared owning enum, and
  it reproduces IDENTICALLY before and after design 139 (only the flavour of
  garbage differs — a stale buffer before, an empty string after).

  ```saw
  func build(n: Int) -> String {
      var b = StringBuilder()
      b.append("val-")
      b.append(n)
      b.build()
  }

  struct Plain { s: String }

  func main() {
      var h = Plain(s: build(1))
      let c = h.s              // a retain IS marked here
      h.s = build(2)
      print("c={c} h={h.s}")   // prints `c=c= h=val-` — c dangles
  }
  ```

  The same shape one level up, with an enum: `var d = Dep.Path(name: build())`,
  `let e = d`, then `d = Dep.Ver(n: 3)` — `e`'s String is gone. Reading is fine
  (a copy that outlives nothing prints correctly); it is the ASSIGNMENT over the
  source that releases a payload the copy still owns. Both the field-assignment
  path and the whole-binding path are affected.

  Suspected: the assignment's release of the old value runs without consulting
  the retain the transfer checkpoint marked at the read, or the marked retain is
  not reaching codegen on this path. Wants its own brief — it is a
  memory-safety bug on the ImplicitCopy tier, where design 139 changed nothing.
  Repro: `.build/scratch/o_field_retain.saw` (gitignored; inlined above).

## Design 131 — DF-findings (payload-read ownership)

- **DF-131a — FIXED (design 139, Aug 5).** A WHOLE-optional read of a NoCopy or
  ExplicitCopy payload aliased and double-dropped. Closed by giving every type
  exactly one copy tier: `Namespace.copy_tier` joins a wrapper's tier from its
  parts, so `Optional<T>`, tuples, fixed arrays, enum payloads and `Result<T, E>`
  are each no weaker than what they wrap, and the move checkpoint is one lookup
  into it. The original filing follows.

  Design 131 made the PAYLOAD read policy-driven, but
  the optional ITSELF still has no tier: `_is_no_copy_type` / `_is_explicit_copy_type`
  key off a struct/enum name, and `Optional<T>` has neither, so the checkpoint
  falls through to the default bitwise path:

  ```saw
  struct Res { id: Int }
  extension Res: NoCopy {
      func deinit(&var self) { print("drop res {self.id}") }
  }

  func main() {
      let o: Res? = Res(id: 1)
      let p = o                 // no move required, no copy performed
      print("ok")
  }                             // prints "drop res 1" TWICE
  ```

  This is DF-128a's disease one wrapper out. The brief said whole-optional
  operations were unchanged because `let y = x` "already retains via the
  owning-enum arm" — true for an ImplicitCopy payload (`is_implicit_copy_enum`
  covers it, and codegen's `_transfer_needs_copy` retains an owning OPTIONAL read
  out of a container slot), but there is no corresponding arm that REFUSES when
  the payload is move-only. An `Optional<Vector<Int>>` behaves the same way.

  NOT fixed here because the natural fix — an `Optional<T>` inherits T's copy
  policy at the checkpoint — has a blast radius the brief did not scope. It makes
  `let y = x` on a `Vector<Int>?` demand `move x`, and `.copy()` on an optional is
  currently rejected outright ("type `Vector<Int, GlobalAllocator>?` is not
  Copy"), so the only spelling left would be `move`. Whether containment should
  follow (does `struct H { r: Res? }` become move-only?) is the same design
  question one level up. Worth a small brief; the repro above is five lines.
  Repro: `.build/scratch/p131_e.saw` (gitignored; inlined above).

## Design 124 — DF-findings (TaskGroup eager teardown)

- **DF-124a — FIXED (design 124, Aug 5).** Frame-field reads had no ownership
  discipline. A coroutine frame holds an owned local in a `T?`-encoded field and
  reads it as `self.name!`; the ForceUnwrap hid the underlying field access from
  BOTH the typechecker's transfer checkpoint and every codegen copy predicate
  (they match bare place expressions — Identifier / MemberAccess / ArrayIndex /
  TupleIndex). So a transfer out of the frame took a non-retaining alias AND left
  the field's drop flag set: neither the retain branch nor the move branch ran.
  Latent before eager teardown (the frame outlived every reader, and a joined
  task's take cleared `__result`, so the stale flag cost one late drop), it
  became an immediate use-after-free once the field was released at task
  completion — `func w() -> Wrap { let s = "v{n}"; yield_now(); Wrap(s: s) }`
  handed back a `Wrap` whose String the frame then freed. Fix: `_read_field`
  marks a non-`move` whole-binding read `frame_owning_read`, and codegen applies
  the same read-out-of-storage retain the closure-capture materialization already
  spells with `.copy()` — at call/return transfers (`_transfer_needs_copy`),
  struct-literal fields (`_needs_copy_for_struct_init`) and both assignment paths
  (`statements.py`). A `move` read is deliberately unmarked: it keeps
  transferring the frame's own reference via `__saw_forget`. Retains are typed
  against the VALUE's type, not the destination field's, since an opt-encoded
  destination is `T?` while the read is the bare payload.

- **DF-128a — FIXED (design 131, Aug 5).** `Deinit` is non-declarable:
  `extension T: Deinit {...}` is a compile error naming the three copy policies,
  and a hand-written `deinit` body lives inside the policy conformance (the
  requirement is inherited). That makes the unpoliced state unreachable rather
  than diagnosed — a type with a destructor now always has a transfer rule, so
  the checkpoint's missing arm cannot be entered; it was added anyway as an
  internal-error tripwire. Containment follows for free: the migrated `Res` is
  `NoCopy`, so `struct Pair { a: Res }` hits the existing NoCopy containment
  error. Migration was 108 types — 74 with no policy at all became `NoCopy` (the
  semantic the fallthrough should have had), 34 folded into a policy they already
  declared; `Vector` was the one judgment call, keeping its `deinit` on the plain
  unconditional extension because its destruction covers every `T` while its
  `ExplicitCopy` conformance is bounded `<T: Copy>`. Tests:
  `errors/deinit_needs_copy_policy`, `errors/deinit_policy_migration_moves`,
  `deinit_policy_containment`. `T: Deinit` as a generic BOUND is untouched.
  Original finding follows: **a `Deinit`-only type aliases and
  double-frees (found while probing for design 128, Aug 5; PRE-EXISTING —
  reproduces with design 128 reverted).** A type whose only resource conformance
  is `Deinit` falls through every arm of the value-transfer checkpoint, so a
  plain `let s = r` bitwise-aliases it and both copies run `deinit`:

  ```saw
  struct Res { id: Int }
  extension Res: Deinit {
      func deinit(&var self) { print("drop res {self.id}") }
  }

  func main() {
      let r = Res(id: 7)
      let s = r                 // no move required, no copy performed
      print("alive {r.id} {s.id}")
  }                             // prints "drop res 7" TWICE
  ```

  `_check_transfer` (typechecker/types.py) branches on NoCopy / ExplicitCopy /
  ImplicitCopy / owning-enum and has no arm for "carries a deinit but declared no
  copy policy", so the transfer takes the default path — a bitwise move that
  never retires the source. It also reaches one level up: `struct Pair { a: Res }`
  behaves the same, and today `extension Pair: Deinit { ... }` satisfies the
  containment rule without making `Pair` move-only.

  NOT fixed here because it is a language-semantics call, not a patch. The sound
  answer is that `Deinit` alone implies move-only (Rust's model): a value that
  owns a resource and has no copy policy can only be moved. That is a one-line
  change at the checkpoint, but it retires an accepted spelling — roughly fifteen
  in-tree examples declare a bare `extension X: Deinit` on a type they then copy
  freely, and each would need `move` or a policy. Design 128 explicitly left the
  copy-policy containment rule unchanged, so widening it was out of scope. What
  128 DID change is reachability: with the Deinit containment error gone, a
  struct holding a `Deinit`-only field now compiles with no declaration at all,
  so the hole is easier to fall into than it was. Repro:
  `.build/scratch/p5_deinit_alias.saw` (gitignored; inlined above).

- **DF-128c — STOPPED, needs its own unit. `_type_method_base` does not fill
  default type arguments, so a struct FIELD's generic type mangles to a symbol
  that does not exist (found by design 128, Aug 5; PRE-EXISTING).** A field
  written `Vector<Int>` denotes `Vector<Int, GlobalAllocator>`, and the
  monomorphized methods are registered under the full form
  (`Vector$2$Int$GlobalAllocator_copy`). `_type_method_base` calls `mangle_type`
  on the written form directly, producing `Vector$1$Int`, and every consumer
  treats the resulting miss as "this type has no copy/deinit of its own" and
  falls back to structural glue. generics.py:131-154 documents exactly this
  chokepoint ("every mangling of a named type funnels through
  `_fill_default_type_args` ... the dual-identity hazard is closed") — this
  caller skips it. It bites only types with a DEFAULTED type param, i.e.
  Vector/Map/Set/Box.

  The copy half was a live memory-safety bug and IS fixed here, narrowly: a
  derived memberwise `copy()` over a `Vector` field bitwise-aliased the buffer,
  so `let b = a.copy()` gave two holders sharing one allocation, mutations were
  visible through both, and both freed it. `_field_copy_fn` (codegen/methods.py)
  now fills the defaults before the lookup and RAISES rather than silently
  aliasing if the symbol is still missing. Test:
  `examples/synthesize_explicit_copy_holder.saw` (fails before, passes after).

  The DROP half is **STOPPED — design 132 unit H diagnosed it and did NOT land
  it** (Aug 5), per the brief's stop-if-it-fights rule. The fix itself is
  confirmed correct and is a two-line change (fill the defaults in
  `_type_method_base`, exactly as `_field_copy_fn` already does). What blocks it
  is the OTHER path, now identified: **DF-132a below — `Vector.get` has no
  `T: Copy` bound, so it hands out a non-retained bitwise ALIAS of a NoCopy
  element.** libs/toml's `TomlDoc.get_section` / `TomlSection.get_table` and
  blade's manifest reader are built on that alias. The two bugs currently
  CANCEL: the alias runs the element's deinit at scope exit, and the container's
  `Vector<T>` field drop glue never runs, so each element is freed once and the
  program looks correct. Fixing the drop glue alone makes the container free the
  element a SECOND time — which is the stage1 SIGSEGV.

  Proven both directions on a 60-line repro (`.build/scratch/p132_h_alias.saw`,
  inlined under DF-132a): with the drop-glue fix `Item.deinit` prints twice for
  one element, without it exactly once. Localized from the bootstrap down to a
  single test by bisection: `blade tree` and `blade/tests/manifest_dependencies`
  both SIGSEGV with zero output, and a probe showed the crash inside
  `Manifest.load_from`, at `doc.get_section("package")` — a `TomlSection?`
  returned by value out of a `Vector<TomlSection>` whose element type is
  `NoCopy`. Instrumenting `_emit_drop_at` listed exactly the 13 fields that
  newly acquire drop glue: `TaskGroup`'s three vectors, `Command`, `DepList`,
  `GitTags`, `LockData`, `ReqList`, `Resolution`, `TomlDoc`, `TomlSection` (x2),
  `TomlTable`.

  **These two must land together, and the pairing is a DESIGN QUESTION, not a
  patch.** Giving `Vector.get` the bound the docs already claim it has breaks
  libs/toml and blade at the source level: `get_section`/`get_table` cannot
  return a NoCopy element by value at all, so they need a redesign (a
  `with_ref`-shaped scoped borrow, an index-returning lookup, or making the toml
  types `ExplicitCopy`), and blade's callers move with them. That is a std API
  change plus two package migrations — RS-2's unfinished half (design 122 gave
  the bound to `iter`/`enumerated`/`each`/`map` and to `set`, but never to
  `get`). Wants its own brief with the API shape decided up front.

- **DF-141a — FIXED in place (design 141 unit B, Aug 5). `move x` on a local
  whose type INSTANTIATED to `Void` raised `internal compiler error: Undefined
  variable: x`.** Design 132 unit C made a Void-instantiated binding a
  zero-sized one — no alloca, and `visit_Identifier` reads it back as no value —
  but only taught the READ path. `_generate_move_expr` still went looking for
  storage and raised, so a generic body that type-checked fine produced an
  internal error at one instantiation, which is precisely what unit C's
  instantiation-uniformity rule ("a body that type-checks generically compiles
  for every instantiation") exists to prevent. Moving a zero-sized binding
  transfers nothing: it yields no value and suppresses no deinit. Found while
  looking for a lowering for a borrows epilogue's `let __wr = __window(...); ...;
  return move __wr`, where `__R` is unbounded and Void is an ordinary
  instantiation. Test `examples/generic_local_move_at_void.saw` covers `R` =
  Void, Int, String and a NoCopy type (the last asserting exactly one deinit, at
  the CALLER's scope exit). The transform itself ended up not needing `move` —
  a plain return of a local at its last use is already a transfer and stays
  sound for a NoCopy `R`, proven by probe — but the ICE was real either way.

- **DF-128b — FIXED (design 132 unit E, Aug 5).** `Namespace.is_trivially_copyable`
  gained the ENUM branch it never had: a payload-free enum that declares no
  resource trait is a bare tag, so it copies bitwise and has no deinit to
  double-run. The gate is `is_equatable`'s auto-conformance gate verbatim,
  which is what the spec promises — the auto-Copy set and the auto-Equatable set
  are one set. An enum WITH a payload keeps its old classification (derived
  structurally by `is_implicit_copy_enum`); widening triviality to "all payloads
  trivial" would change copy tiers for `enum Msg { case Move(x: Int, y: Int) }`
  and is a separate question, not needed here. Test
  `examples/enum_payload_free_as_key.saw`: Set element by insertion and by
  collection literal, Map key by literal and by `insert`, plus `contains` /
  `contains_key` / `get` round-trips. Original finding follows.
  `Set<Color>` on a payload-free enum is rejected with "set
  element type `Color` must be copyable ... owns a Deinit without a copy (it is
  move-only, not retainable)", which is false — the enum owns nothing.

  ```saw
  enum Color { case Red, case Green }

  func main() {
      var palette: Set<Color> = Set<Color>()   // error: must be copyable
      palette.insert(Color.Red)
      print(palette.len())
  }
  ```

  `Namespace.is_trivially_copyable` handles STRUCT, tuple, optional and array
  kinds and falls off the end returning False for `TypeKind.ENUM` — unconditionally,
  payload or not. `_key_copyable_reason` then reads that False as "owns a Deinit"
  and reports the misleading reason. The gap is visible in the docs too: `Color`
  is documented as auto-`Hashable`, and `examples/map_each_string_enum.saw` uses a
  payload-free enum only as a VALUE, never a key. Fixing it means teaching
  triviality about enums (payload-free, or all payloads trivial), which touches
  copy classification everywhere and wants its own unit rather than a drive-by in
  128. Repro inlined above.

- **DF-128d — FIXED (design 132 unit D, Aug 5), together with its duplicate
  DF-129a.** `print` now asks the renderability question interpolation asks:
  both call `_check_renderable_operand` (typechecker/expressions.py), which
  passes a builtin kind or a `Printable` conformance (a `T: Printable` bound
  included) and otherwise reports at the argument. `print(o)` on an `Int?` gives
  `cannot print value of type `Int?`: it is not `Printable``, with the same
  `extension Int?: Printable` hint interpolation already gave; the verb is the
  only difference between the two messages, so the interpolation text is
  unchanged. The open design question — whether `T?` should BE Printable at all
  (Swift renders `Optional(5)` / `nil`) — is untouched and still open; this only
  makes the refusal a diagnostic instead of a crash. Test
  `examples/errors/print_optional_not_printable.saw` covers the bare optional,
  the `v.get(0)` shape both findings hit, and the interpolation twin.
  Original finding follows: three lines, no generics:

  ```saw
  func main() {
      let o: Int? = 5
      print(o)          // error: internal compiler error: Cannot print type: {i1, i64}
  }
  ```

  An ICE is never the right answer. What the right answer IS is a small design
  question, which is why it is filed rather than patched: either `T?` is not
  Printable and this is a clean "does not conform to `Printable`" error at the
  call site, or optionals render (Swift prints `Optional(5)` / `nil`) and the
  formatter grows a case. Hit while writing a test that printed
  `v.get(0)` — `Vector.get` returns `T?`, so this is easy to reach by accident.

- **DF-124b — FIXED (design 131, Aug 5).** Every payload-extraction form — `o!`,
  the `??` left operand, an `if let`/`guard let` binding — now denotes a PLACE,
  and the Copy family governs the read exactly as it governs every other read.
  `_is_aliasing_expr` sees through a force-unwrap (`o!` aliases iff `o` does, so
  `f()!` stays a fresh temporary), and the retain lands AT the extraction rather
  than at the enclosing transfer site, because a `let` initializer never reaches
  the transfer-site copy path. `??` also gained a checkpoint on its DEFAULT
  operand, which had never been checked at all — `let s = opt ?? other` aliased
  `other` and double-freed it (found while implementing; the ExplicitCopy repro
  aborted with SIGTRAP). The consuming forms are `move o!` (compile-time, retires
  the whole binding, locals only) and `Optional.take(&var self) -> T?` (runtime,
  swaps `None` into the place, reaches a FIELD). `TaskHandle.join` — which
  EXPLOITED the non-retaining read via `let r = ptr[0]!` + `__saw_forget` —
  migrated onto `self.result_ptr[0].take()!`; no .saw file calls `__saw_forget`
  any more, though it stays a builtin for the unsafe domain. The coroutine
  transform's frame reads are exempt (`frame_place_read`): the transform runs
  after the type-check that already judged those reads un-projected, and the
  whole program is then re-checked, so weighing in again would double-retain an
  ImplicitCopy payload and reject a NoCopy one the frame is moving out.
  Original finding follows.
  DF-124a's root cause is not confined to coroutine frames: reading a payload out
  of ANY optional with `!` neither retains it nor clears the source's ownership,
  so the reader gets a non-owning alias. Five lines, no coroutines, no unsafe:

  ```saw
  func main() {
      var o: String? = "v{1}"     // interpolation => a heap-allocated String
      let a = o!                  // reads the payload WITHOUT retaining it
      o = None                    // releases the payload
      print(a)                    // `a` dangles: prints NUL bytes
  }
  ```

  Same for a `T?` STRUCT FIELD (`let b = h.s!`, then `h.s = None`), for an
  `if let` binding out of a field, and for `??`. `_generate_force_unwrap` is a
  bare `extract_value` and `_ALIASING_EXPR_TYPES` does not include `ForceUnwrap`,
  so nothing along the path accounts for the payload.

  NOT fixed here because the obvious fix (teach `_is_aliasing_expr` to see through
  `ForceUnwrap`) would break an idiom the executor itself depends on:
  `TaskHandle.join` does `let r = self.result_ptr[0]!` followed by
  `__saw_forget(self.result_ptr[0])` — a deliberate MOVE out of a container,
  which only works because `!` does not retain today. So the question is a design
  one, not a patch: does `opt!` COPY the payload (and how is a move-out then
  spelled — a `take()` on Optional? `move o!`?), or does it MOVE (and then `o`
  must be marked moved-from, which the checker does not do either)? Either answer
  needs the NoCopy case decided too: `let g = f!` on a `File?` is currently
  accepted and silently duplicates. Design 124 scoped itself to the frame
  encoding it owns; this wants its own brief. Repro:
  `.build/scratch/probe_df124b.saw` (gitignored; inlined above).

- **DF-124c — CLOSED (design 134, Aug 5).** Mechanism, as the brief specified it:
  `__result` and `__cancel` moved OUT of the coroutine frame into a per-task CELL
  the group owns, allocated at spawn beside the slot (`__ResultCell<T>` /
  `__VoidCell`, held erased as `Box<any __TaskCell>` so the group never names
  `T` and the box teardown still runs the right destructor). A spawn-root frame
  carries only a `__cellp` pointer to it, so NOTHING outside the frame points
  into it and `TaskGroup.__complete` releases the frame box at Done — design 124
  item 3, now implementable. The slot then goes on a free list, and handles
  became `(slot, generation)` pairs so a stale handle is a defined outcome rather
  than a read of its successor: `TaskHandle.join` panics ("this task's result was
  already joined"), `VoidTaskHandle.join` returns, `cancel` no-ops.
  `cancel_addr()` — the case that motivated the finding — PINS its slot: the raw
  address it hands a peer must outlive the task and carries no generation to
  check, so that one slot keeps its cell and gives up reuse. Measured on 200k
  short tasks through one group: 200,000 slots / 31.0 MB peak RSS before,
  4 slots / 1.5 MB after. Fences: `taskgroup_slot_reuse_o_live`,
  `taskgroup_slot_reuse_mt`, `taskgroup_stale_handle_join`,
  `taskgroup_stale_handle_cancel`, with the design-124 fences green throughout.
  Original finding follows: **design 124
  item 3 was NOT implemented as written; the frame box is retained (Aug 5).** The brief asked
  that "the `tasks` vector slot become reclaimable at Done (drop the Box
  eagerly)". That is unimplementable alongside the brief's own items 1-2, which
  require the never-joined `__result` to survive until group teardown: `__result`
  lives INSIDE the frame, and `TaskHandle`'s `result_ptr` and `cancel_ptr` are
  raw pointers into it. Freeing the box at Done would dangle both — and
  `cancel_addr()` hands a raw frame address to a peer task precisely so it can
  write the cancel word LATER, which no done-check can guard. What design 124
  does deliver is that every RESOURCE the frame held is released at Done; what
  the slot keeps afterward is the frame allocation itself (the result slot plus
  the scheduler words). For a long-lived accept-loop server that is still O(tasks
  ever spawned) memory, bounded by frame size — the bookkeeping vectors are
  already O(tasks ever spawned) by the brief's own "do NOT compact, indices are
  handles" rule. Reclaiming the box needs `__result` and `__cancel` relocated out
  of the frame into group-owned, type-aware cells (the erased `Box<any Resumable>`
  cannot free a payload it no longer describes), which is a protocol change
  across the spawn lowering, `TaskHandle`, and design-102's `__is_cancelled`.
  Worth a follow-up brief; not a correctness bug.

## Design 134 — DF-findings

- **DF-134a — APPROVED (user, Aug 5): the `__saw_rt_reactor_unregister` seam
  joins the frozen ABI — design 147 owns it** (kqueue EV_DELETE / epoll
  EPOLL_CTL_DEL in the Saw reactors; called on the park loop's cancellation
  exit + belt-and-braces at frame `__release` for registered-unfired tokens;
  regression: park, cancel, escape the fd via the result, poke it. Post-134
  severity note: the frame box frees at Done, so a stale one-shot's token is
  a POINTER INTO FREED MEMORY — this is a use-after-free vector, not a
  leak). Original finding follows: **(reactor-token lifetime vs fd
  lifetime; found landing design 134, Aug 5).** The design-91 reactor token is
  the ADDRESS of the root frame's `__wake` word: `io_wait` arms
  `EV_ADD|EV_ONESHOT` with `udata = &frame.__wake`
  (`sawc/rt/host_macos/reactor.saw:85`) and the poll writes the latch through it.
  Nothing ever DE-registers. A park loop that exits WITHOUT its event firing —
  the cancellation path, `std/net.saw:438` `if cancelled() { ... }` at the loop
  top — therefore leaves the kevent armed. Normally that is harmless because the
  task's own `TcpStream` deinits at completion and closing the fd drops the
  kevent with it. It is NOT harmless when the fd OUTLIVES the frame, which
  happens when the task returns its stream as its RESULT: the fd stays open, the
  kevent stays armed, and the next readiness event writes into memory the frame
  used to occupy.
  This is pre-existing (design 91), not introduced here, but design 134 narrows
  the safe window: the frame box used to live until group teardown, and now it is
  released at task completion. Exposure is narrow — it needs cancel-while-parked
  AND the fd escaping through the result — and the write is a single word into a
  freed block, so it is silent rather than crashing (the repro below runs clean;
  that is not evidence of safety).
  The fix belongs to the runtime ABI, not to the slot lifecycle: a
  `__saw_rt_reactor_unregister(r, fd, dir)` seam the frame's `__release` calls
  for any fd it armed and did not consume. rt/ABI.md freezes the seam set, so
  adding one is a user decision — hence stopped here rather than patched.
  Repro (`.build/scratch/probe_stale_token.saw`, gitignored; inlined):
  ```saw
  func reader(s: TcpStream) -> TcpStream {
      match s.read() {            // parks, armed EV_ONESHOT on s.fd
          case Ok(_) -> print("reader-read"),
          case Err(_) -> print("reader-cancelled")
      }
      return move s               // the fd leaves with the RESULT, kevent armed
  }
  func canceller(addr: Int) unsafe { let p = addr as UnsafePointer<Bool>  p[0] = true }
  func writer(s: TcpStream) { try! s.write("hello") }
  func run() {
      let (a, b) = TcpStream.pair()
      var group = TaskGroup()
      let hr = group.spawn(reader(move a))
      let addr = hr.cancel_addr()
      let _ = group.spawn(canceller(addr))
      var back = hr.join()        // frame box freed here; token still armed
      // ... churn the group so new frames reuse that memory ...
      let w = group.spawn(writer(move b))   // makes the old fd readable
      w.join()                              // stale kevent fires -> latch write
      let _ = move back
  }
  ```

## Design 116 — DF-findings (self-hosting lexer pilot, IN PROGRESS)
The lexer port (`selfhost/lexer`) is the pilot's measurement instrument;
language pain hit while writing it is the explicit product. Policy (user, Aug 4):
NO workarounds — an unambiguous compiler bug STOPS the affected unit + is
recorded here; a limitation is recorded with the wanted spelling. Repros are
inlined (the `.build/scratch` probes are gitignored).

- **DF-116a — FIXED (lead, Aug 4, same-day).** Root cause:
  `_needs_copy_for_struct_init` (codegen/resources.py) gated copy-on-init on
  the field type's LEAF conformance being ImplicitCopy, so an owning AGGREGATE
  with no whole-type copy() (`Optional<String>`, owning tuples/structs/enums)
  fell through to a bitwise copy with no payload retain. Fix: the gate now also
  fires when `_needs_cleanup(field_type)` (excluding NoCopy — typechecker-gated
  to `move` anyway); `_generate_copy` already dispatched such aggregates to the
  design-65 `_deep_copy_value` retain path. Regression test
  examples/optional_field_store_retain.saw covers the struct-field shape, the
  bare `v.push(opt)` call-path shape, and local-still-valid-after-copy. Suite
  999 green, bootstrap ok. FOLLOW-UP DONE (design 119 Part D, Aug 4): the
  `suffix` field is restored on selfhost/lexer's `Token` (populated from
  `try_read_int_suffix`, None elsewhere) and the canonical dump's 4th column is
  emitted by BOTH dumpers (tools/dump_tokens.py + `format_token` in lib.saw) —
  `255u8` dumps `INT<TAB>1:1<TAB>255<TAB>u8`; README format section updated;
  `make lexdiff` re-swept 0 mismatches; tests/literals.saw asserts the suffix
  column. Original finding follows:
  **MISCOMPILE (headline): an `Optional<String>` held in a named
  local loses its payload when copied into a struct field whose struct is pushed
  into a `Vector`.** The stored copy is not retained; the local's end-of-scope
  release then frees the buffer → the Vector element reads empty/garbage (often
  aliasing a later allocation). A PLAIN `String` local in the same position is
  fine, and an INLINE `sb.build()` (fresh temp) is fine — the bug is specific to
  an `Optional`-of-ImplicitCopy value that is (a) a named local and (b) copied
  (not moved) into the aggregate. Minimal repro:
  ```saw
  struct Tok { value: String, suffix: String? }
  func lexy() -> Vector<Tok> {
      var v = Vector<Tok>()
      var sb = StringBuilder(); sb.append("u8")
      let opt: String? = sb.build()          // Optional<String> local
      v.push(Tok(value: "x", suffix: opt))    // copied into a struct-in-Vector
      move v
  }
  func main() -> Int {
      let toks = lexy()
      if let b = toks.get(0) { if let s = b.suffix { print("suffix=[{s}]") } }
      0                                        // prints "suffix=[]" (should be [u8])
  }
  ```
  Contrast (both correct): `let plain: String = sb.build(); Tok(value: plain,...)`
  works; `Tok(value: "x", suffix: sb.build())` (inline, moved) works. Likely the
  copy-into-aggregate path for an `Optional<ImplicitCopy>` field emits a bitwise
  copy without the payload retain (compare the design-67 read-out-of-container
  double-free class). IMPACT ON THE PILOT: this is exactly the shape of the
  integer-literal-suffix path (`let suffix = self.try_read_int_suffix()` → stored
  in the `Token`). Per the no-workaround policy the suffix-in-the-token unit is
  STOPPED: the Saw `Token` omits the `suffix` field and the canonical dump omits
  the 4th suffix column (both dumpers), so suffixed literals are still lexed as a
  single INT token with the correct boundary/value and range-checked, but the
  suffix attribute is not surfaced until this is fixed. Token positions/kinds/
  boundaries (the lexer's core) are unaffected.

- **DF-116b — CLOSED (design 119 Part A, Aug 4).** Added the checked unsigned
  parse `String.to_uint() -> UInt?` / `to_uint(radix: Int) -> UInt?`
  (sawc/std/string.saw): whole-string, no-trimming, panic-free, overflow past
  `UInt.max` → `None`, detected with wrapping arithmetic + divide-back (multiply)
  and carry (add) checks — the unsigned mirror of the existing `_parse_int`. The
  integer bounds the WANTED note asked for already exist as compiler builtins
  (`UInt.max`, `Int8.max` … `UInt64.max`, design 53); no new bounds surface was
  needed. selfhost/lexer's `literal_fits` now parses with `to_uint(base)` and
  compares against the width's unsigned max — the digit-count + lexicographic
  `fits_u64`/`capped_fits`/`str_greater`/`strip_leading_zeros` workaround is
  deleted. Landing this required fixing an unrelated codegen bug (unsigned `<`/
  `>`/`<=`/`>=` used `icmp_signed`; see DF-119 below). Tests:
  examples/int_parse_to_uint.saw (radixes 2/8/10/16, the u64 ceiling + overflow,
  rejections) and the lexer's tests/literals.saw + `make lexdiff` (0 mismatches).
  Original finding follows:
  **no bignum and no checked integer parse forces digit-string
  magnitude comparison for literal range checks.** `sawc/lexer.py` computes
  `int(digit_str, base)` (arbitrary precision) and compares to `2**64-1` /
  `2**width-1`. Saw `Int`/`UInt` are 64-bit and arithmetic PANICS on overflow, so
  the widest legal literal (`UInt64.max == 2**64-1`) cannot be accumulated to be
  compared. The port instead range-checks by digit COUNT + an equal-length
  lexicographic compare at the boundary (and a capped accumulation for the small
  8/16/32-bit widths). WANTED: a checked/overflow-returning parse in std, e.g.
  `UInt64.parse(s: String, radix: Int) -> UInt64?` (None on overflow) or checked
  arithmetic (`a.checked_mul(b) -> Int?`), plus a `UInt.max` constant. Non-
  blocking (the magnitude approach is correct), but it is a hand-roll the obvious
  spelling can't replace.

- **DF-116c — CLOSED (design 119 Part B, Aug 4).** Added
  `StringBuilder.append_scalar(scalar: Int) -> Int?` (sawc/std/stringbuilder.saw):
  UTF-8-encodes one Unicode scalar and appends it, returning the byte count
  (1..4); an invalid scalar (negative, surrogate 0xD800..0xDFFF, or > 0x10FFFF)
  returns None and appends nothing (never a silent drop — the failure surface is
  an Optional per the never-hide-errors rule; the byte count is the Some payload).
  It is the encoding inverse of chars(), so an encode/decode round-trip is the
  identity on valid scalars. selfhost/lexer's hand-rolled `encode_utf8` is deleted
  in favor of it. Docs: LANGUAGE_SPEC String section + saw-lang skill. Test:
  examples/string_append_scalar.saw (the length-transition boundaries 0x7F/0x80/
  0x7FF/0x800/0xFFFF/0x10000/0x10FFFF via round-trip + byte count, plus the
  invalid cases). Original finding follows:
  **no scalar→UTF-8 / `StringBuilder.append_scalar` affordance.**
  `String.chars()` DECODES UTF-8 to `Int` scalars, but there is no inverse:
  nothing appends a Unicode scalar (an `Int` code point) to a `StringBuilder` or
  builds a String from one. A `\u{...}` escape whose scalar is >= 0x80 therefore
  needs a hand-rolled UTF-8 encoder in the lexer (`encode_utf8` in lib.saw).
  WANTED: `sb.append_scalar(cp: Int)` (or `String.from_scalar(cp) -> String?`,
  None on an invalid scalar) as the mirror of `chars()`. Non-blocking (encoding a
  code point is arguably lexer work), but the asymmetry is a real std gap the
  pilot surfaces.

- **DF-116d — CLOSED (design 119 Part C, Aug 4).** Both lexers now track the
  first interpolation-open `{` position in a string literal and, when the string
  fails to terminate (the interpolation runs to EOF, or a later `}` was consumed
  as its close and the string then runs off the end), report AT that brace —
  "unterminated interpolation in string literal, opened at this `{` (write `\{`
  for a literal brace)" — instead of "Unterminated string" at EOF. Landed in
  sawc/lexer.py AND selfhost/lexer/src/lib.saw in one commit (error positions are
  the lexdiff parity contract). Error positions match byte-for-byte; `make
  lexdiff` stays at 0 mismatches. Tests: selfhost/lexer/tests/errors.saw (the
  brace-position case), examples/lexer_unterminated_interpolation.saw (the
  compiler-level message). Original finding follows:
  **diagnostic quality: an unbalanced interpolation `{` in a string
  literal reports "Unterminated string" at EOF, not at the offending brace.**
  Writing `"...{..."` (a stray `{`, meaning interpolation, with no matching `}`)
  makes the lexer consume the rest of the file — the error surfaces as
  `Lexer error at <lastline+1>:1: Unterminated string`, pointing at EOF with no
  hint of where the `{` was. Hit while writing an error-message string literal
  that contained a bare `{`. (A literal brace is spelled `\{`, which works
  correctly and does NOT leak the internal 0x01 marker into the runtime string —
  verified. So this is purely a diagnostic-locality nit, not a correctness bug.)
  WANTED: track the interpolation-open position and report there ("unterminated
  interpolation, opened at L:C").

- **DF-116e — FIXED (lead, Aug 4, same-day):** sawc/lexer.py now captures
  `start_line` before `read_string()` and stamps the STRING/INTERP_STRING
  token with it (probe: a multi-line interpolated string dumps at its start
  line; lexdiff parity with the Saw port holds, 0 mismatches). Original
  finding follows:
  **sawc/lexer.py BUG (spec-vs-implementation disagreement): a
  MULTI-LINE string token gets the END line with the START column.** In
  `Lexer.tokenize` the `"` arm captures `start_col` BEFORE `read_string()` but
  builds the token with `self.line` AFTER it — and `read_string`/the
  interpolation copy advance `self.line` over every newline they consume. So a
  string literal that spans lines (a literal newline in the content, or a
  multi-line interpolation) is emitted at `(end_line, start_col)` — an
  inconsistent position. Minimal repro (`a` / `"{` / `}"` / `b` on four lines):
  the Python lexer reports the INTERP_STRING at `3:1`; the `"` is on line 2. The
  spec (LANGUAGE_SPEC.md: "`#line` → the 1-based line of the token") makes a
  token's line its START, so the Saw port uses the start line (`2:1`) — it is
  CORRECT where Python is buggy. Per the brief this is flagged rather than
  silently matched: the port does NOT reproduce the bug. The whole tracked corpus
  (1109 files) has zero multi-line string literals, so lexdiff stays green; the
  disagreement only manifests on a constructed multi-line string. FIX (in sawc):
  use the pre-read line for the string token (capture `start_line` alongside
  `start_col`). Until then the two lexers differ on this one rare construct by
  design.

## Design 123 — DF-findings

- **DF-123a — FIXED (design 132 unit B, Aug 5).** Both halves the finding asked
  for. (1) `calls.py::_generate_static_method_call` now substitutes the written
  type arguments against `type_param_context` before
  `_ensure_monomorphized_struct`, exactly as the constructor path
  (`structs.py::_generate_struct_init`) always did — which is the whole reason
  `Holder<T>(v: v)` survived where `Holder<T>.make(...)` did not. (2)
  `types.py::_get_llvm_type` now REFUSES a self-mapping type-param binding
  (`T -> T`) with a named error instead of recursing: an unsubstituted parameter
  reaching codegen is a bounded, diagnosable failure of the one construct at
  fault rather than `maximum recursion depth exceeded` failing the entire
  compilation unit. Test `examples/generic_static_call_own_type_params.saw`
  covers the static call from an instance method and from another static method,
  two instantiations of the same struct, a two-parameter struct, and a static
  call that flips its parameters. Original finding follows. Writing
  `Vector<T, A>.try_with_capacity(n)` inside a `Vector<T, A>` extension body
  compiles to `internal compiler error: maximum recursion depth exceeded` and
  takes the WHOLE compilation unit with it: because std is merged in, every
  program in the suite then fails to compile, including `hello.saw`. The
  constructor spelling of the same thing (`Vector<T, A>(capacity: n)`, used by
  `copy`/`map` for years) is fine — only the STATIC-METHOD path is affected.
  Minimal repro (`.build/scratch/probe_static_self.saw`):
  ```saw
  struct Holder<T> { v: T }
  extension Holder<T> {
      public func make(v: T) -> Holder<T> { Holder<T>(v: v) }
      public func remake(&self) -> Holder<T> { Holder<T>.make(self.v) }  // ICE
  }
  func main() { let h = Holder<Int>.make(3)  print(h.remake().v) }
  ```
  Diagnosis from the traceback: `calls.py::_generate_static_method_call` calls
  `generics.py::_ensure_monomorphized_struct("Holder", [T])` with the type
  ARGUMENT still being the type PARAMETER `T`, and `types.py::_get_llvm_type`
  line 136 resolves `T` through `self.type_param_context["T"]`, which maps `T` to
  itself — an unbounded self-recursion. The constructor path never reaches
  `_ensure_monomorphized_struct` with an unsubstituted parameter, which is why it
  survives. Two things to fix: substitute through `type_param_context` before
  monomorphizing, and give `_get_llvm_type` a self-mapping guard so any future
  variant is a clean error rather than an ICE that fails every compilation.
  design 123 did NOT code around this — `Vector.try_copy` reserves through the
  instance method `try_reserve` instead, which is the better implementation
  anyway (one allocation, no intermediate) and never needed the static spelling.

- **DF-123b — FIXED (design 132 unit C, Aug 5): it COMPILES, rather than being
  rejected.** USER DECISION (Aug 5) on the brief's either/or, and the rule it
  sets: **syntactic Void errors, instantiated Void compiles.** A `Void` you can
  SEE in the source is a visible mistake and stays the design-122 D3 error; a
  `Void` that arrives by INSTANTIATION is a legitimate use and becomes a
  zero-sized binding — no storage, and reading the name yields no value. The
  point is that generic code stays INSTANTIATION-UNIFORM: a body that
  type-checks generically compiles for every instantiation, so no call site ever
  produces a post-monomorphization error at a distance from the definition. This
  is how a unit type binds in Rust and Swift, and it is what unblocks the
  `lock<R>` shape M1 wants. Three changes, all in codegen. (1)
  `statements.py::_generate_let_statement` skips the alloca when the value's
  LLVM type is void and records the name in the new `void_variables` set, which
  `core.py::visit_Identifier` reads back as no value (the block-tail and return
  paths already treat a valueless result as `ret void`). (2)
  `methods.py::_generate_function` decides void-vs-value from the EMITTED
  signature rather than `func.return_type`: for a generic instantiation the
  declared type is still the type PARAMETER, so an `R = Void` free function took
  the value branch and asserted building an `undef` of void. The generic METHOD
  path (`generics.py`) already substituted its return type and needed nothing.
  (3) A `Void`-instantiated local that the coroutine transform gives a frame
  field hit two more `{i1, void}` producers, both fixed at the source: the None
  literal now lowers the OPTIONAL type through `_get_llvm_type` instead of
  assembling `{i1, payload}` around it, so design 111's `Void?` i8-placeholder
  rule applies; and `_wrap_in_optional` sets the is_some flag and stops when the
  payload is void, since there is no payload to insert.
  The typechecker is untouched — the design-122 error for a CONCRETE
  `let n = <Void expr>` still stands; only the per-instantiation case, which the
  abstract body check cannot see, now lowers. Test
  `examples/generic_local_at_void.saw`: a generic method at `R = Void` and at
  `R = Int`, statements on both sides of the void binding, an inferred `R`, a
  free generic function whose void-valued local is read twice, a NoCopy guard
  whose deinit runs between the binding and the tail read at BOTH instantiations
  (the `lock<R>` shape), and the same binding inside a SUSPENDING body spawned
  into a TaskGroup. `examples/errors/let_void_expression_rejected.saw` keeps
  asserting the syntactic half. The decision line is recorded in LANGUAGE_SPEC
  beside the design-122 statement rules and in the saw-lang skill. design 133's
  `lock<R>` is NOT rewritten here — this only proves the shape compiles.
  Original finding follows.
  `Mutex.lock<R>`'s natural body binds the closure result so the unlock can
  run before the return:
  ```saw
  public func lock<R>(&self, body: (&var T) sync -> R) -> R {
      pthread_mutex_lock(block)
      let result = body(payload_ptr)     // R = Void -> ICE
      pthread_mutex_unlock(block)
      result
  }
  ```
  At `R = Void` — a critical section that computes nothing, i.e. the common case
  — codegen reaches `statements.py::_generate_let_statement` ->
  `_entry_alloca(VoidType)` and llvmlite asserts, surfacing as
  `internal compiler error:` with an EMPTY message. The typechecker accepts the
  body (R is a type parameter there), so nothing catches it earlier.
  `Vector.with_ref<R>`/`with_var_ref<R>` survive only because their `body(...)`
  call is in tail position with no binding. Two things to fix: a `let` bound to a
  `Void`-instantiated generic should be the same clean design-122 error a
  concrete `let n = <Void expr>` already gets, and codegen should not build an
  alloca for a zero-sized/void local.

- **DF-123c — FIXED (design 133 unit A, Aug 5).** `_generate_arc_forward_call`
  and `_generate_box_forward_call` share `_forward_target_symbol`, which
  substitutes the resolved method type args against the active monomorphization
  context, requests the monomorph through `_ensure_monomorphized_generic_method`,
  and composes the symbol from them — what the ordinary method-call path already
  did. `Mutex.lock<R>` shipped on top of it (M1). The finding named a second
  cause that was not real: `_resolve_arc_forward` does not need to solve
  method-level type args itself, because it returns the payload method and its
  struct substitution to the SHARED downstream, which runs the design-93/105
  inference and the bound checks for the forward site as for any other call.
  Verified across inferred and explicit type args, generic and non-generic
  payload structs, both wrappers, and a forward whose method type argument is the
  enclosing generic's own parameter (`examples/arc_forward_generic_method.saw`).
  Original finding follows: **`Arc<T>` payload-method forwarding cannot
  reach a METHOD-GENERIC payload method (found by design 123 unit G, Aug 5).** Making `Mutex.lock`
  generic over the closure's result (review M1, "you cannot compute a value under
  the lock") is a one-line signature change that compiles fine on its own and
  then breaks every `Arc<Mutex<T>>` user with
  `internal compiler error: 'Mutex$1$Int_lock'`. Cause:
  `calls.py::_generate_arc_forward_call` mangles the payload method with
  `_mangle_method_name(base, name)`, the NON-generic form, so it looks up a
  symbol the method-generic monomorphizer never emits (`..._lock$1$Void` etc.);
  the typechecker's `_resolve_arc_forward` likewise does not solve method-level
  type arguments at a forward site. Reproduced by `examples/mutex_counter.saw`,
  `task_join_on_deinit.saw` and `net_budget_fairness.saw`, all of which lock
  through an `Arc<Mutex<Int>>`.
  design 123 did NOT code around this: `lock` KEEPS its `Bool` result and the
  brief's actual non-negotiable is met a different way — the `false` collision is
  gone because the INERT mutex that produced the second meaning cannot be
  constructed any more (`Mutex(value:)` panics). **M1 stays open and is blocked
  on this**: forwarding needs to solve and monomorphize method-level type args
  before `lock<R>` (or any other generic payload method) can ship.

## Design 122 — DF-findings

- **DF-122a — FIXED (design 132 unit A, Aug 5), closing RS-5's fourth hole.**
  The write is now a compile error: `cannot assign to `n`: it is captured by
  value, so the write would be discarded when the closure returns`, hinting
  `[&var n]` and `Arc<Mutex<T>>`. The checker keeps a stack of the scopes closure
  bodies open (`TypeChecker._closure_scopes`); an assignment target whose ROOT
  binding resolves past the innermost entry arrived by value capture, and
  `_capture_write_root` (typechecker/statements.py) reports it from both
  `_check_assign_statement` and `_check_compound_assign_statement`. Three things
  it deliberately does NOT flag, because each write reaches real storage: a
  borrow capture (defined right in the closure scope, so it never resolves past
  the boundary), a capture whose TYPE is already a reference (the env copies the
  pointer), and an index into a heap-backed container (`v[i] = x` on a captured
  `Vector` shares the buffer). It DOES cover the in-storage path — `x = v`,
  `x += v`, `x.f = v`, `x.0 = v`, a fixed-array element — which matters beyond
  the lost write: `x.f = v` on a captured struct also drops the OLD field value
  the env copy still points at, i.e. a double free. Blast radius was zero as
  measured: the suite, blade, libs and SOS all stayed green with no source edit.
  Riders: a REJECTED `[&var x]` borrow capture now still binds the name (error
  recovery), so the borrow diagnostic stays the only complaint instead of being
  buried under one capture-write error per mutation. Tests
  `examples/errors/capture_assign_escaping.saw` (the `make_counter` shape),
  `examples/errors/capture_assign_non_escaping.saw` (the `each3` shape plus
  `+=`), `examples/capture_write_allowed_forms.saw` (the forms that still work).
  A future opt-in `[box n]` capture mode stays open as a separate brief.
  Original finding follows:
  **(design 122 unit D4, Aug 4.)**
  Mutating a BY-VALUE closure capture is accepted and silently does nothing
  observable. The brief's D4 said fix it if it is a contained codegen bug and
  STOP if it opens a semantics question. It opens one; the diagnosis:

  **Model.** `codegen/closures.py::_generate_closure` builds an *env of values*
  for every capture mode except `ref`/`ref_var`. At closure-body entry each such
  capture is LOADED out of the env into a fresh local alloca
  (`cap_value = load(field_ptr); alloca; store`), and the name is bound to that
  alloca. So every write inside the body hits a PER-CALL copy that is discarded
  when the call returns; the env field is never written back. Two consequences,
  both silent:
  ```saw
  func make_counter() -> () -> Int {
      var n = 0
      { n = n + 1
        n = n + 10
        n }                  // escaping closure, plain capture of `n`
  }
  // c() three times -> 11, 11, 11   (mutation visible WITHIN a call, lost after)

  func each3(body: (Int) -> Bool) { body(1) body(2) body(3) }
  var sum = 0
  each3({ n in sum = sum + n  true })
  print(sum)                 // 0 — the real `sum` never moves
  // `each3({ [&var sum] n in ... })` prints 6 — the borrow capture is correct
  ```

  **Why the named "contained codegen fix" is NOT available.** Binding the name
  straight to the env field (so writes persist) contradicts a RATIFIED property:
  LANGUAGE_SPEC.md (designs 71/73) states an escaping closure is `ImplicitCopy`
  over a refcounted env that "is immutable and shared … there is no observable
  mutation through a shared env, so the sharing is semantically invisible."
  Persisting writes makes `let g = f` (a refcount bump) share MUTABLE state, and
  an MT `TaskGroup`/`spawn` copy would share it across threads with no
  synchronization — the Send audit checks capture TYPES, not env aliasing. So
  "persist" is a new capture semantics (a boxed/shared capture mode + Send
  rules), not a bug fix.

  **The two candidate semantics.**
  1. REJECT (recommended): assigning to a by-value capture is a compile error
     pointing at `[&var x]` (non-escaping) or `Arc<Mutex<T>>` (escaping). This
     ENFORCES the immutable-env model the spec already ratifies rather than
     deciding anything new. **Measured blast radius: ZERO** — an instrumented
     build that flags assignment to a plain/move/copy capture reports no hit in
     the 1041-test suite, blade + libs/toml + libs/semver, the selfhost lexer, or
     the SOS kernel. Cost: the counter-closure idiom stays unwritable without an
     `Arc<Mutex<Int>>` (and `Box` has no mutable access path today — stdlib M2).
  2. PERSIST via a new capture mode (e.g. `[box n]`): a per-closure mutable cell
     in the env. Needs a Send story for copies and an answer for what two copies
     of one closure observe. A design brief, not a fix.
  Whichever is chosen, the current behavior (accept the write, discard it) is the
  one option the reviewer called "the worst of the three".

## Design 119 — DF-findings (lexer-pilot follow-ups)

- **DF-119a — FIXED (design 119 Part A, Aug 4).** Unsigned integer relational
  comparisons (`<` `>` `<=` `>=`) lowered with `icmp_signed`, so a `UInt` with
  the high bit set read as negative: `UInt.max > 1` was `false`, and any
  magnitude check against a `UInt` bound was wrong above `2^63`. codegen bug in
  `_generate_binary_op` (codegen/operators.py): the integer-compare path always
  used `icmp_signed`. Fix: split on operand signedness via `_int_is_signed`
  (`icmp_unsigned` for the `UINT*` kinds), mirroring the udiv/sdiv split already
  present for `/` and `%`; `Int` and raw pointers stay signed. Test
  examples/int_parse_unsigned_compare.saw. (Blocker for Part A — the ported
  lexer's `literal_fits` and `to_uint`'s overflow check both need unsigned
  compares. Note for integration: this touches codegen/operators.py, which
  overlaps design 120's declared area; the change is a single call site.)

- **DF-119b — FIXED (design 122 unit G, Aug 4).** `print` now selects its
  formatter by the operand's KIND: codegen emits two width-parametric itoa
  bodies — `__saw_print_int` (unchanged) and `__saw_print_uint` (the same body
  with the sign logic dropped; the digit loop was already unsigned udiv/urem) —
  and the print call site (codegen/calls.py) picks the unsigned one for the
  `UINT*` kinds. The interpolation path (`_value_to_string`, codegen/core.py) was
  already correct (`%llu`), which is exactly why the two disagreed; the test
  asserts print, interpolation and `to_string()` agree. Signed printing is
  untouched, `Int.min` included. Test
  examples/print_unsigned_full_width.saw. Original finding follows:
  A
  full-width `UInt`/`UInt64` value with the high bit set (`>= 2^63`) misformats
  under `print` / string interpolation: `print(UInt.max)` emits `-1`, not
  `18446744073709551615`. `__saw_print_int` (codegen/core.py) formats every
  integer as SIGNED (`neg = icmp_signed('<', n, 0)` then a `-` prefix); the
  print/interpolation call site only zero-extends narrower-than-word unsigned
  values, so a same-width `UInt64` reaches the signed formatter unchanged. Values
  below `2^63` (incl. every narrower unsigned type after zext) print correctly,
  so this surfaced only now that `to_uint`/`UInt.max` make `2^63..2^64-1` values
  routine. Repro:
  ```saw
  func main() { print(UInt.max) }   // prints -1; want 18446744073709551615
  ```
  WANTED: an unsigned formatting path — either a second `__saw_print_int`-shaped
  runtime that skips the sign logic (magnitude = the value, unsigned udiv/urem
  digits) selected when the operand kind is one of the `UINT*` kinds, threaded
  through BOTH the `print` call site (codegen/calls.py) and the interpolation
  `_value_to_string` path (codegen/core.py). NOT fixed here: it lives in
  codegen/core.py + calls.py (design 120's concurrent area) and is orthogonal to
  the pilot (the lexer never prints a `UInt`; design 119's tests assert through
  comparisons). Non-blocking.

## Executor — open items

- **EXEC-1 — VERIFY (flagged during the ST lost-wakeup fix, Aug 4, lead).**
  Cross-poller one-shot consumption beyond the fixed case: every poller of the
  process-global reactor (an MT group's workers; a 21b `spawn {}` OS thread
  whose body runs its own cooperative io; the ambient ST sweep) can consume +
  latch a one-shot event belonging to a frame parked by a DIFFERENT poller's
  scheduler. The ST sweep now recovers via its pre-poll latched scan
  (`__saw_exec_any_latched_io`), but only for latches that land while it is
  scanning — a latch that fires while the sweep is already blocked in
  `poll(-1)` (only possible if another OS thread polls concurrently) would
  still wedge it: the event is consumed, the sweep's poll never returns, the
  latch is never read. The MT worker is bounded (50 ms) so it always re-scans;
  the ST sweep is not. NEEDS A PROBE to establish whether the window is
  reachable today (is a concurrent poll possible while the main thread is in
  the ST sweep's poll? MT drains block the main thread; a 21b OS-thread task
  doing reactor io concurrently with main-thread ST io looks like the
  candidate). If reachable: either bound the ST sweep's poll like the MT
  worker's, or self-wake the reactor whenever a poller latches a token it does
  not own. [design 91 / 102 / 118]

## Design 121 — DF-findings (doc comments + --emit-docs)

- **DF-121a — CLOSED by design 129 (Aug 5).** A call's argument list could not
  span lines: a newline anywhere inside the parentheses was a parse error, so a
  long call had to be split into extra bindings or run past any line-width
  convention. Hit while writing the `selfhost/lexer` doc-comment test (an
  `assert(cond, "message")` whose two arguments did not fit on one line). Repro,
  which now compiles and prints `3` (`examples/newline_wrapped_call.saw`):
  ```saw
  func add(a: Int, b: Int) -> Int { a + b }

  func main() {
      let x = add(
          a: 1,
          b: 2)
      print(x)
  }
  ```
  Design 129 took the question in one pass, as the finding asked: a parser-side
  bracket-depth discipline suppresses NEWLINE inside `(`/`[` and inside a
  COMMITTED generic `<...>`, `{}` stays newline-significant, a trailing comma is
  allowed in the `()`/`[]` forms and rejected in `<>`, and an unclosed bracket is
  reported at its opener. The lexer is untouched, so lexdiff parity with
  `selfhost/lexer` was never in play.

## Design 129 — DF-findings (newlines in brackets)

- **DF-129a — FIXED (design 132 unit D, Aug 5).** Same bug as DF-128d, found
  independently; see that entry for the fix. Original finding follows.
  `print(x)` where `x` is an Optional ICEs instead of producing the clean
  "not `Printable`" error that string interpolation of the same value gives.
  Reproduced identically on the pre-129 parser, so it is not a regression:
  ```saw
  func main() {
      let v: Vector<Int> = [1, 2, 3]
      print(v.get(0))            // v.get(i) returns `Int?`
  }
  // error: internal compiler error: Cannot print type: {i1, i64}
  ```
  Interpolating the same value is already clean — `"{v.get(0)}"` reports
  "cannot interpolate value of type `Int?` in a string: it is not `Printable`",
  with the `extension T?: Printable` hint. WANTED: the builtin `print` checks its
  argument for `Printable` the way interpolation does and reports the same
  anchored error. Easy for a user to hit, since `Vector.get` returning `T?` is
  the common source of a stray Optional. Not fixed inside design 129 — it is a
  typechecker/codegen issue with no bearing on the bracket rule, and the brief's
  gate battery was the priority. [needs a small brief or a fix-on-discovery pass]

## Design 126 — findings (pre-port AST contract)

- **DF-126a — RC-2 is LATENT, not a live bug (measured, Aug 4).** The pre-port
  review called the un-substituted grafted annotations "a live bug, not just a
  port hazard": `substitute_ast_types` walks `dataclasses.fields()`, so while
  `resolved_type` and the ~50 other annotations were grafted at runtime, the
  monomorphizer could not see them, and every `SawType`-valued one was carried
  into an instantiation stale. R1 declares them, so the substituter sees them —
  but the claimed miscompile could not be reproduced. Repro method (kept here
  because it is the way to re-test this cheaply): make the loop at
  `typechecker/effects.py:51` skip `resolved_type` and every field whose
  metadata carries `saw_annotation`, i.e. reproduce exactly what the grafts hid,
  then run the suite. Result: **1034/1034 pass**, including
  `examples/coro_generic_mono_type_subst.saw`, which was written specifically to
  exercise the path (a driven generic-struct method at three instantiations,
  with a `match` over a `T`-parameterized enum and a `Vector<T>` literal live
  across the suspension). So the corpus cannot currently reach a shape where the
  stale annotation changes the emitted code. WANTED: either a shape that does
  distinguish (then it becomes a real regression test), or acceptance that R1's
  value here is contract correctness for the port rather than a bug fix. Do NOT
  describe RC-2 as a fixed miscompile without such a shape.

- **DF-126b — reproducible builds were broken; two causes fixed, no guard yet
  (Aug 4).** Compiling one unchanged source twice produced different IR
  (`examples/hello.saw` differed by thousands of lines). Causes: a `set` of type
  names seeding the codegen topological sort, and a `set` of capture names
  fixing closure environment field order. Both fixed under design 126 R2, and
  `make irdet` now guards a corpus sample. Note the general hazard remains
  unpoliced: any future `set`-of-`str` iteration that reaches emission order
  reintroduces this class silently, because Python randomizes string hashing per
  process and a single run always looks self-consistent.

  **The warning came true — TWO MORE INSTANCES, both in the coroutine transform,
  both FIXED (design 141, Aug 5).** Found by accident, which is the point:
  `tools/irdet.py` samples 40 examples via `random.sample` over the tracked file
  LIST, so simply ADDING two unrelated examples reshuffled the sample and pulled
  in a file that had been non-reproducible all along. Both causes are
  `set`-of-`str` iteration reaching emission order in `coro_transform.py`:
  (a) `promoted` — the set of promoted generic instantiations — was iterated
  into the work list at `transform_program`, which orders `closure`, which
  orders `fbs`, which orders the emitted frame structs and resume methods
  (`examples/coro_nested_generic_deep.saw`); (b) `modes` — the drive modes
  recorded per root by `_effect_record_driven`, a `set` — was iterated when
  emitting the `__saw_drive_*` / `__saw_drive_steps_*` wrappers, at three sites
  (`examples/coro_tuple_across_suspend.saw`). Both now sort. Verified with
  `irdet --all` rather than the 40-file sample.

  **GATE STRENGTHENED (design 146 unit D, Aug 5).** `make irdet` keeps the
  40-file sample as the cheap per-commit check; `make irdet-all` sweeps the
  whole corpus and is now the documented standard for a brief's FINAL gate
  battery (CLAUDE.md's testing section says so). Measured cost of the full
  sweep: **728 examples compiled twice under differing PYTHONHASHSEED, 102
  skipped (they need module paths or a host), 1128.6s of tool time / 18m49s
  wall** on the dev Mac. That is affordable once per brief and not once per
  commit, which is exactly the split. Still open as a cheaper guard: a static
  check for `set`-of-`str` iteration that reaches an emission list — the sweep
  catches instances, not the class.

## Milestones
- **App-1 Blade: DONE** (design 64 + 67; real resolver/lock/git/
  incremental/self-hosting bootstrap; `make blade-bootstrap`).
- **App-2 SOS kernel (ESP32-P4, riscv32): IN PROGRESS.** M0 DONE (design
  112): Saw kernel boots + prints a UART banner + exits cleanly under
  QEMU `virt` riscv32 (`make sos-test`). Ultimate milestone: UART "blink"
  on real P4 hardware. See sos/spec.md §5b (M0 recap) + designs/112.
- **Docs website (sawlang.com): VISION (user, Aug 4) — "eventually", not
  scheduled.** A complete site: installation, usage/tutorial, stdlib API
  reference extracted from source. Component (1) doc comments and (2)
  `--emit-docs` are **DONE** (design 121, Aug 4): `///`/`//!` are lexed as
  trivia in both lexers under the lexdiff parity contract, the parser attaches
  them, and `sawc <entry> --emit-docs` writes the typechecked surface as JSON
  (signatures, conformances, suspending-vs-sync effect, self ownership;
  design-80 gate on members). The pipeline is proven end to end on std.task +
  std.time. Remaining component designs to brief when scheduled:
  (3) `sawdoc` — the JSON→HTML generator WRITTEN IN SAW (surface-area strategy:
  markdown/string/file-IO heavy dogfood); (4) the std docstring pass across the
  rest of std (per-module content work, agent-friendly, follow the saw-docs
  skill); (5) site shell + hosting (static; README "Building from a fresh
  clone" section is the near-term precursor). Open questions for (3)/(4):
  Markdown validation and doc-example testing (`sawdoc test`?), and whether
  blade/libs sources join the documented set. [website]

## Queued briefs (Aug 4) — awaiting dispatch
- **Design 116 — self-hosting pilot: the lexer in Saw (dispatched Aug 4).**
  First permanent stage1 module + rewrite-decision instrument: `selfhost/lexer`
  Blade package mirroring sawc/lexer.py's token model, canonical token-dump
  format, `tools/dump_tokens.py` + `tools/lexdiff.py` differential harness over
  the WHOLE .saw corpus (zero mismatches = bar), LOC/perf metrics, DF-116
  findings as the explicit product. Full rewrite DEFERRED (user, Aug 4) until
  design churn slows; surface-area growth is the chosen mechanism. [116]
- **Design 119 — lexer-pilot follow-ups (queued; dispatch AFTER 118
  integrates; user-authorized Aug 4).** Closes the remaining 116 findings:
  (A) radix-aware overflow-checked string->int parse unified with to_int() +
  integer min/max bounds (DF-116b); (B) StringBuilder.append_scalar UTF-8
  encoding (DF-116c); (C) unbalanced-interpolation-brace diagnostic at the
  brace, BOTH lexers same commit — error positions are lexdiff contract
  (DF-116d); (D) restore Token.suffix + the dump's 4th column in both dumpers
  (the DF-116a stopped unit; 116a itself fixed Aug 4). Brief:
  designs/119-lexer-pilot-followups.md. [119]
- **Design 121 — doc comments + --emit-docs. LANDED (Aug 4).** The sawlang.com
  pipeline foundation. Per-unit commits, full suite green each:
  (A) `///`/`//!` captured as TRIVIA in both lexers — the default token dump is
  byte-identical, a new `--docs` dump emits `DOC<TAB>line:col<TAB>kind<TAB>text`
  from `tools/dump_tokens.py --docs` and `sawlex --docs`, and `tools/lexdiff.py`
  runs both sweeps (`--mode tokens|docs|both`, default both);
  (B) parser attachment — a `doc` field on every documentable node,
  `Program.module_doc`, blocks keyed by the first real token after them (so a
  `public` prefix or `@export` line between changes nothing), and a clean
  "doc comment is not followed by a documentable declaration" for any block
  nobody claims;
  (C) `--emit-docs` / `--emit-docs-all` JSON (schema_version 1) from the checked
  program — rendered signatures off resolved types, conformances off the
  namespace, effect (suspending|sync) off the effect graph, self
  borrows/borrows-var/consumes + `&var` params; entry module plus every imported
  module, std included, so a driver file selects what to document. Members
  follow the design-80 gate; top-level items are not gated by the compiler so
  they are all listed with their declared visibility. Test runner gained
  `// EXPECT: docs` (golden: examples/doc_emit_json.saw);
  (D) std.task + std.time docstringed end to end.
  Brief: designs/121-doc-comments.md. NOT done here (out of scope, see the
  Milestones entry): the `sawdoc` HTML generator, the full std docstring pass,
  Markdown validation / doc-example testing, doc comments in blade/libs. [121]
- **Design 117 — runtime ABI v2 minimization. LANDED (Aug 4).** Errno
  accessors DELETED; the reactor is INSTANCE-based and relocated to Saw
  (DF-113d dissolved); the thread surface is spawn/join. Per-unit commits:
  thread_spawn/join; instance reactor (rt/host_*/reactor.saw kqueue/epoll,
  compiler `__saw_reactor` singleton getter injected at seam call sites);
  errno→SysError (net, then file/dir/env). Full suite 998 + bootstrap + sos
  green each. `sawc/rt/ABI.md` rewritten as v2 (minimization principle,
  SysError tag table, instance-reactor contract, v1→v2 deprecation table).
  - **SysError tag space (pinned, ABI.md):** 0=Ok, 1=WouldBlock, 2=InProgress,
    3=IsConnected, 4=Interrupted, 5=ConnReset, 6=ConnRefused, 7=ConnAborted,
    8=BrokenPipe, 9=NotConnected, 10=NotFound, 11=PermissionDenied, 12=Exists,
    13=AddrInUse, 14=Invalid, 15=Exhausted, 16=Other. A failing op returns the
    NEGATED tag (Linux `-errno` convention → 1:1 with the SOS (status,value)
    pair). The errno→tag mapping is the ONE host-divergent seam
    `__saw_rt_last_syserror()`; the status-carrying OS ops (tcp/fs/env) call it
    right after a failing syscall, so std never sees a raw errno.
  - **Pin deviation (recorded):** the brief's `Other(errno)` — preserve the raw
    hosted errno for diagnostics — is NOT done. A single negated-word return
    cannot carry a tag AND a raw errno, and SOS has no errno; `Other` is tagless
    and diagnostics come from mapping the common failure errnos to named tags.
    `__saw_rt_last_syserror` is a runtime-INTERNAL seam (common os_ops → host
    net_os), not a std-facing errno accessor, so the errno CHANNEL still dies.
  - **DF-117a — `if let {}` block absorbs a following leading-`-` line as binary
    subtraction.** A function whose body is `if let x = y { … }` immediately
    followed by a line beginning with a unary minus, e.g.
    `func f() -> Int { if let p = alloc() { … return r }\n    -SOME_CONST }`,
    parses the trailing `-SOME_CONST` as `(if let {…}) - SOME_CONST` and ICEs
    (`'NoneType' has no attribute 'type'` in operators.py — the if-let value is
    None). A plain `if {}` block does NOT absorb it (the newline terminates),
    so it is an if-let-specific inconsistency in block-expression statement
    termination. Wanted code: `… }\n    -SYS_OTHER` as the fallback value.
    Worked around cleanly with an explicit `return 0 - SYS_OTHER` (net.saw
    net_read_once; os_ops.saw trailing tags). Recorded per the do-not-work-
    around policy: the fix is a parser change to block-terminated-statement
    handling; deferred as out-of-proportion + genuinely ambiguous (blocks are
    expressions, so `block - x` is arguably valid) — flagged for a lead call.
  [117]
- **Design 118 — the executor in Saw (queued; dispatch AFTER 117).** The last
  synthesized runtime layer (cooperative executor/scheduler, MT engine,
  offload parking) relocates to Saw consuming a `Reactor` trait (per-host
  kqueue/epoll types; future SOS-hosted impl over the Waiter) + minimal
  thread surface; compiler keeps frames + a small documented entry-point
  boundary. Staged (map/carve → ST core → reactor trait → threads/MT/
  offload), each stage suite-green, clean stop at a boundary acceptable.
  Resolves the deferred design-114 io_wait gating (white-box reactor tests
  become reactor-impl unit tests). Brief: designs/118-executor-in-saw.md.
  [118]
- **Design 113 — runtime extraction. IN PROGRESS (Aug 4).**
  - **LANDED — ABI freeze + rename (the time-critical, irreversible piece).**
    Both symbol tiers renamed to the uniform scheme: `__saw_rt_*` =
    runtime-implemented (reactor register/poll/wake, pthread create/join/
    mutex_init/cond_init, offload start/done/pipe_fd/take + blocking_sleep,
    clocks, sleep, errno family, set_nonblocking, sin_set_family, op-budget,
    alloc/dealloc/write/panic, get_argc/argv); `__saw_*` = compiler-internal
    (string, atomic, print_int — unchanged). Renamed across codegen, stdlib
    `.saw`, and the offload example tests; LLVM module id → `__saw_module`.
    Full suite green (993). The full symbol contract is documented in
    `sawc/rt/ABI.md` (reactor one-shot rearm, design-91 token = parked frame
    wake-word addr, design-102 cancel-wake, poll timeout, offload discipline,
    the four intended implementations). CLAUDE.md repo map updated.
  - **Physical relocation: LANDED via design 113b (Aug 4).** The `saw_*` export
    reservation was loosened under `--runtime-build` and the seam bodies moved
    to `sawc/rt/` (Saw) + `shim.c` (the DF-113a/b/c bodies) — all seams except
    the IO reactor (DF-113d, see the 113b entry below). See designs/113b-rt-in-
    saw.md. DF-findings stay open as language gaps:
    - **DF-113a — no extern C global.** `__saw_rt_write`/`_panic` need the libc
      `stdout` FILE* (`__stdoutp` macOS / `stdout` Linux) for the `fwrite +
      fflush` that keeps `print` ordered against the still-`printf` Float path.
      Saw has no `extern static` / extern-global syntax, so the body can't be
      Saw. (Switching to `write(2)` would reorder against buffered float text —
      not byte-identical.)
    - **DF-113b — no C function-pointer type.** `__saw_rt_pthread_create` and
      the offload thunk (`word(word)`) pass a raw C function pointer to
      `pthread_create`. Saw's surface has no bare C function-pointer type
      (closures are fat pointers), so threads + offload can't be Saw bodies.
    - **DF-113c — no variadic extern.** `__saw_rt_set_nonblocking` must call
      `fcntl(fd, F_SETFL, ...)`, which is variadic in C (an arm64 ABI
      requirement — a fixed-arity decl reads the flag off the stack). Saw
      extern decls have no `...`, so the reactor's nonblocking-socket path
      can't be a pure-Saw body.
    - **Expressible in Saw today** (for the eventual relocation): alloc/dealloc
      (malloc/free), sleep_ms (usleep), the clocks (clock_gettime + a Saw
      timespec struct), the errno family (extern `__error`/`__errno_location`
      returning `UnsafePointer<Int32>` + `unsafe` deref), sin_set_family (byte
      stores), op-budget + reactor init CAS (`Atomic<Int>.compare_exchange` —
      seq_cst, i.e. stronger ordering than the synthesized monotonic; observably
      equivalent), and the kevent/epoll structs (Saw structs, natural ABI). The
      reactor's `set_nonblocking` dependency (DF-113c) is the only gap in an
      otherwise-Saw reactor.
    - Remaining scope when unblocked: build/cache/link machinery
      (`.build/rt/`, keyed on source hash, auto-linked for hosted builds, `-v`
      shows the objects, clear error if the rt fails to build); delete the IR
      synthesis; the negative test (freestanding still externs, no runtime
      auto-linked — needs a test-harness symbol-inspection directive, which
      doesn't exist yet, and only bites once hosted auto-links); `sawc/rt/`
      module-dir layout selected by target triple. [113]
- **Design 113b — runtime layer in Saw. LANDED (Aug 4)** except the reactor.
  Runtime-build mode (`--runtime-build`: reservation loosening for the exact
  frozen ABI set with a typo-checked valid-name error, seam-declaration
  suppression via the design-58 unify, sync-only via the `@export`-is-sync-
  context check, builtin-only load, internalize+globaldce) + error tests.
  Relocated to `sawc/rt/` (Saw) + `shim.c` (the 3 sanctioned DF bodies):
  alloc/dealloc/sleep/clocks, errno family, sin_set_family, op-budget, pthread
  mutex/cond/join, the blocking-extern offload (start/done/pipe_fd/take +
  blocking_sleep); shim.c holds write/panic (DF-113a), pthread_create + the
  offload thread thunk (DF-113b), set_nonblocking (DF-113c). rt build/cache/link
  machinery (`.build/rt/<hash>/`, flock-guarded, auto-linked, `-v` lists them,
  hard error on rt build failure). Freestanding negative test via a new
  `EXPECT: object` + `EXPECT-SYMBOL-UNDEFINED:` harness directive. Full suite
  (997) + bootstrap + sos green at every commit.
  - **The IO reactor — RELOCATED TO SAW by design 117 (Aug 4).** **DF-113d
    (per-call stack event buffer) is DISSOLVED, not fixed:** making the reactor
    INSTANCE-based (a `create`d instance owns its fd + wake pipe) let `poll`
    allocate its 64-element `kevent`/`epoll_event` buffer as a per-call HEAP
    `malloc`/`free` — which Saw CAN express — so `rt/host_*/reactor.saw` (kqueue/
    epoll) replaced the last synthesized seam. The heap alloc preserves v1's
    concurrent-poll independence exactly (each MT poller gets its own buffer, no
    shared buffer, no poll mutex). The array-repeat/uninitialized-local language
    nicety remains a future convenience but is no longer load-bearing. [113b/117]
- **Future designs — language gaps blocking a pure-Saw runtime** (each removes a
  113b shim body or unblocks the reactor when it lands): (1) extern C globals
  (`extern static stdout: ...`) — DF-113a, shrinks shim.c; (2) a bare C
  function-pointer type (closures are fat pointers; thread_spawn/offload thunk
  need thin ones) — DF-113b; (3) variadic extern declarations (fcntl-class arm64
  ABI requirement) — DF-113c. (DF-113d — the array-repeat/uninitialized-local
  poll-buffer gap — is no longer load-bearing: design 117 dissolved it with the
  instance reactor's per-call heap buffer; the language nicety is optional now.)
  General C-interop / low-level value beyond the runtime. [113/113b/117]
- **DECIDE: infinite loops should type as `Never` (probe Aug 4, lead).**
  `func f() -> Never` is satisfiable ONLY by ending in a Never-typed
  EXPRESSION (`panic(...)` / a Never call); a no-`break` infinite loop —
  `while { }` conditionless AND `while true { }` — is rejected with
  "should return `NEVER` but body has no value" (probe
  .build/scratch/probe_never_spin.saw). Bare-metal spin/WFI/hang idioms
  (design 112's exit_pass/exit_qemu, kernel idle loops) therefore cannot be
  typed honestly and fall back to Void + a comment. Proposed rule: a
  conditionless no-`break` `while { }` types as `Never` (Rust: `loop {}`
  is `!`); whether the literal `while true { }` joins it is part of the
  call. Rider: the diagnostic leaks the internal kind spelling `NEVER`
  (should say `Never`). [49, 58, 112]
- **Design 114 — intrinsic scoping + naming. Part A LANDED (Aug 4); Part B
  LANDED (Aug 4); io_wait gating DEFERRED (see FLAG).**
  - **Part A (yield_now) — LANDED.** `std/task.saw` gained a public
    `func yield_now()`; `import std.task` (already an import-required module —
    it owns `Task`) un-gates it. The bare `yield_now` name stays the
    compiler-recognized cooperative-yield intrinsic but is GATED: allowed only
    in std bodies (`_checking_builtins`), synthesized coro output,
    `--runtime-build` (no std loaded), or when `std.task` has been imported
    (name in `directly_accessible`). A bare un-imported call is a clean
    `UNDEFINED_FUNCTION` error naming the import.
    - **WRAPPER MECHANISM (decision recorded per brief):** chose the
      *intrinsic-preserving gate* (brief's fallback: "typechecker-recognizing
      the qualified name") over the *real suspending wrapper the embedding
      machinery drives* (brief's primary). Reason: the real-suspension effect
      LABEL and the coro-closure / main-suspend detection are recorded at the
      DIRECT call site under the ENTRY typechecker, which never analyzes std
      bodies (this is exactly why `_std_suspending_methods` has to be
      cross-carried for methods). Routing yield_now through a std free-function
      wrapper would drop the real-suspension signal at the entry boundary
      (main wouldn't auto-wrap; nested embedding wouldn't trigger). The gate
      keeps the user call site the exact same intrinsic node it is today, so
      lowering is byte-identical and every embedding position (statement,
      nested if/loop, MT TaskGroup, spawned+nested) works unchanged. The
      `public func yield_now()` body is a transparent `{ yield_now() }` — it
      exists solely as the importable name anchor (never actually called: the
      recognizer intercepts the call before function resolution).
    - Migration: 43 example files gained `import std.task`
      (`source_location_suspending` EXPECT-OUTPUT line numbers bumped +1).
      New negative test `examples/errors/yield_now_bare_gated.saw`.
  - **FLAG (brief premise wrong — io_wait gating DEFERRED, needs lead
    decision).** The brief's Aug-4 audit stated io_wait is "used by std.net"
    (internal only) and budgeted NO io_wait migration. FALSE: **11 example
    programs call `io_wait(...)` directly** — white-box reactor tests that
    drive the FULL raw private seam (`tcp_socketpair`/`tcp_try_read`/
    `tcp_try_write`/`net_buffer`/`net_would_block`/`io_wait`) with controlled
    socketpairs to exercise park/precise-wakeup/cancel/deinit-across-parks at
    the reactor level: `net_io_main_entry`, `net_threads_io`,
    `net_loopback_echo`, `net_socketpair_echo`, `net_io_sleep_interleave`,
    `net_deinit_across_parks`, `net_nested_parks_roundtrip`, `net_io_cancel`,
    `net_precise_wakeup`, `net_precise_n_readers`, `net_three_park_sequence`,
    `net_cancel_parked_mt`. Gating io_wait to std bodies would break all of
    them; there is no public-API equivalent that still tests io_wait itself
    (the public TcpStream examples exercise the seam only indirectly). So
    honoring "io_wait outside std errors" requires a COVERAGE decision the
    brief did not authorize: either DELETE these 11 white-box reactor tests
    (relying on the public-API net tests for regression coverage) or KEEP
    io_wait ungated. Left io_wait exactly as-is (ungated) pending that
    decision; the yield_now gate is independent and complete.
  - **Part B (__saw_ rename) — LANDED.** See the Part B commit.
- **Design 115 — test runner: persistent compile workers. LANDED (Aug 4).**
  Amortize the measured ~250 ms/test fixed compiler-bootstrap overhead (python
  + llvmlite/sawc imports + builtin namespace) via N long-lived worker
  processes compiling in-process; binaries still run as isolated
  subprocesses; identical pass/fail/xfail set both modes (997 passed each).
  Merged-binary consolidation REJECTED (user, Aug 4) — breaks error tests,
  abort tests, per-test EXPECT/COMPILE-FLAGS, attribution. Builtin namespace
  built once/worker, deep-copied per compile (62 ms vs 147 ms rebuild). Pool
  is Process + Pipe (`connection.wait`), NOT `multiprocessing.Pool`, which
  needs POSIX named semaphores a locked-down sandbox refuses (`sem_open`
  EPERM). Error tests run in-process (reporter text has no isatty color
  gating → byte-identical to CLI capture). Old spawn-per-test path kept
  behind `--subprocess`.
  - **DF-115a — codegen relied on llvmlite's process-global context.**
    The re-entrancy audit found (and this design FIXED) two latent
    dependencies on `ir.context.global_context` that would also bite a future
    compile-server/LSP: (1) `ir.Module` defaults to the global context, whose
    `identified_types` registry persists across compiles → a 2nd in-process
    compile raised "`<Struct>` is already defined"; fixed by a fresh
    `ir.Context()` per `CodeGenerator`. (2) `ir.Type.get_abi_size/alignment`
    render a throwaway module in the global context, so once (1) moved a
    compile's identified types into a private context the size probe rendered
    an undefined-type reference; fixed by routing every ABI query through
    `_abi_size`/`_abi_align`, which pass `context=self.module.context`. The
    broader audit found NO other module-level mutable leaks (counters/caches
    are per-`CodeGenerator`; type-ids are a deterministic hash; llvmlite
    `initialize_*` is idempotent).

## Design 120 — suspension in expression position (LANDED, Aug 4)
Brief: designs/120-expression-suspension.md. A suspending call may now sit
anywhere an expression may. Stage 0 landed the known-unsupported matrix as XFAIL
tests first (`examples/expr_suspend_*`); every marker is flipped, zero XPASS, and
the carve-outs below are the only survivors.
- **Mechanism (coro_transform.py).** `_anf_hoist` rewrites a statement whose
  expression tree contains a suspension source into evaluation-ordered
  `let __anfN = …` temps, so each suspending call lands in a top-level statement
  the existing 96/101/104 embedding machinery drives unchanged. Sync code is
  untouched. `_lower_value_conditionals` runs first and turns a suspension-
  spanning CONDITIONAL construct into the branch shape (value `if`/`match`, `??`,
  `&&`/`||`, a `?.` chain, a chained assignment), so a conditional position keeps
  its short-circuit: an arm that is not taken never runs its suspension or its
  side effects.
- **Composition.** `_vc_head_hoist` lifts a conditional nested in another
  conditional's unconditionally-evaluated head (a `??` LHS, an `if` condition, a
  `match` scrutinee, an `&&`/`||` left operand) into its own statement first, and
  `_vc_chain_prefix_hoist` peels a multi-hop `?.` chain one hop at a time. Both
  exist because an `if let` nested inside an `if let` is a shape the state split
  cannot express; as statements they lower fine. `o?.susp() ?? -1` is the case
  that needs both.
- **Rides along.** Blocking `extern` calls (design 103) and cooperative
  `Channel.receive()` (design 62 G3) hoist for free — their statement-bound
  restriction existed for the same buried-suspension reason. Tests
  `expr_suspend_blocking`, `expr_suspend_channel_recv`.
- **Closes:** the design-104 buried-in-a-larger-expression rejection list, the
  design-111 suspending-hop/suspending-chain carve-out, and the
  suspension-mid-chain future-work item. `examples/errors/
  optional_chain_suspend_method.saw` moved to `examples/` as the positive case;
  `errors/coro_reject_anchored.saw` re-pointed at suspending recursion (the
  shape it asserted now compiles).
- **CARVE-OUT (recorded): multi-hop chained assignment with a suspending RHS.**
  `a?.b?.c = stream.read()` still rejects cleanly; the single-hop
  `a?.c = stream.read()` works. The lowering is a None-guarded
  read-modify-writeback of ONE payload (`var __wp = a!; __wp.c = rhs; a = __wp`);
  more than one hop needs the writeback nested per level. Wanted spelling: the
  multi-hop form lowering the same way. Workaround: `if let` the inner optional
  first. [120, 111]
- **DF-120a — ICE: spawn + join a task whose function returns an Optional.**
  PRE-EXISTING (reproduces at the design-118 tip, before any 120 commit), so it
  is recorded rather than fixed here. `internal compiler error: cannot store
  {i1, i64} to {i1, {i1, i64}}*` — an `Optional<T>`-typed value stored into a
  frame slot typed `Optional<Optional<T>>`. The optional-wrap-on-store heuristic
  in `_generate_assign_statement` (codegen/statements.py, the MemberAccess
  branch) wraps only when the VALUE is not already an optional, so a genuinely
  optional value going into an opt-encoded slot is stored raw. Repro:
  ```saw
  import std.task
  func run(n: Int) -> Int? { yield_now(); n }
  func main() {
      var g = TaskGroup()
      let h = g.spawn(run(5))
      print(h.join() ?? -1)     // ICE
  }
  ```
  `__saw_drive(run(5))` on the same function is fine; only the spawn/join path
  hits it. Wanted fix: compare the value's type against the slot's PAYLOAD type
  rather than asking whether the value is optional at all. [120, 52b]
- **FLAG (minor): a NoCopy payload under a suspending chained assignment
  reports at 0:0.** `var local: NC? = …; local?.x = s(7)` inside a driven
  function is a clean error (`cannot copy value of type ... which implements
  NoCopy`) — the lowering's `local!` read duplicates the payload — but the
  diagnostic carries no source position. The sync form compiles, so the shape is
  legal outside a coroutine. A guard in `_lower_optchain_assign` cannot fix it:
  the transform's typechecker handle has not merged the entry module's namespace
  yet, so `_is_no_copy_type` answers False there. Cosmetic; the program is
  rejected either way. [120, 111]

## Doc-sync audit findings (Aug 3) — two DECIDE items
Surfaced by the four-source consistency audit (README / spec / skill /
CLAUDE.md digest vs code); docs were updated to match the implementation,
these two need a design call:
- **DECIDE: method call on an integer literal.** `7.doubled()` is a parse
  error — the lexer consumes `7.` as a float-literal prefix; `(7).doubled()`
  and a bound name work. `Int(7).doubled()` does NOT work (probe Aug 3:
  "struct initialization requires named arguments" — constructor-call syntax
  is structs + distinct aliases only). Decide whether INT `.` IDENT should lex
  as a method call, or whether `(7).method()` is the blessed spelling
  (README's Type Extensions example now uses a binding meanwhile). [57]
  **PUNTED (user, Aug 4):** stays an error for now; `(7).method()` is the
  workaround spelling. Revisit on demand.
- **LANDED (design 110): plain assignment through `&var` — unified permissive.**
  Whole-referent replacement `x = v` through a `&var T` function/method param and
  `self = v` in a `&var self` method are now legal (RHS `move` + `self = v` both
  in, per the Aug-3 scope call), matching closures and Swift `inout`: RHS takes
  the ordinary transfer checkpoint, old referent deinits once, new value installs,
  caller stays valid. Immutable `&T` assignment and `move` out of a ref stay
  banned (own diagnostics); a `&var any Trait` ERASED referent is excluded with a
  specific Box-level diagnostic; `&var Box<any Trait>` payload swap works; generic
  `&var T` works per instantiation (deinit-once verified). Rider fixed: a bare
  trait name behind a ref (`&Shape`/`&var Shape`) was an ICE, now a clean
  unsized-trait error naming `&any Shape`/`&var any Shape`. Spec/skill/README
  caveats reverted to the uniform rule. [110, 34, 88, 106]
- **LANDED (design 111): full optional chaining.** Brief at
  designs/111-optional-chaining.md. Swift-style `?.` reads (multi-hop
  `?.field`/`?.method()`, call-result heads, arbitrary length, one short-circuit
  skips the rest of the postfix chain INCLUDING skipped-call args, flattening
  never `U??`, final field must be copyable); chained assignment `x?.y = v` writes
  the payload field in place (RHS skipped on short-circuit, ordinary transfer +
  deinit-once of the old value, `Void?` result discardable / consumed via the
  `_`-blessed `if let`/`guard let`); a suspending hop or a suspending CHAIN was a
  clean buried-suspension error (CLOSED by design 120 — both now lower). Parser: OptionalEvalExpr +
  BindOptional spine, OptionalChainAssign. Codegen: address-based short-circuit
  walk reusing `_generate_method_call(receiver_ptr=…)`; `Void?` = `{i1, i8}`.
  Tests under examples/optional_chain_*, optional_binding_underscore, and
  examples/errors/optional_chain_*. Docs: spec Optionals + Argument Evaluation
  Order, skill, README, this digest.
- **VERIFY (agent claim, Aug 3): two-suspend helper embedding failure.** The
  design-110 agent reported that a non-driven helper with TWO suspend points
  ("plain `yield_now(); print; yield_now()`, no references") fails to embed
  under a driven body with the nested/expression-position error. NOT reproduced
  by the lead: statement-position `let a = helper()` with two suspends compiles
  AND runs at depth 1 and depth 2 (probes `.build/scratch/probe_two_suspends*.
  saw`, Aug 3). The failing shape, if real, is more specific — extract the
  exact repro from the agent transcript before treating as work. [104, 96]
  **Deferred (user, Aug 4):** revisit only if it reproduces during the SOS
  work (design 112 onward flags suspending-shape oddities on discovery).
- **Future work: suspension mid-chain — CLOSED by design 120 (Aug 4).** The
  compiler unchains the statement for you; a suspending hop inside a postfix or
  `?.` chain lowers. [111, 104, 120]
- **FLAG (minor, design 111 discovery): buried-suspend diagnostic wording —
  MOOT (Aug 4).** The message's "an `if let`/`guard let` body" clause no longer
  reaches the chain case: design 120 lowers suspending chains instead of
  rejecting them. The clause is accurate for the design-104 shapes that still
  reject. [111, 104, 101, 120]

## Design 109 — silently unchecked trait bounds for primitive type args (LANDED)
- **Root cause (typechecker + one namespace gap).** The free-function bound-check
  loop in `_check_function_call` (expressions.py) derived a `concrete_type_name`
  only for STRUCT/ENUM type args and special-cased Copy/Send/Sync/Equatable; a
  Comparable/Hashable/Printable/user-trait bound on a PRIMITIVE (or tuple/Optional/
  closure/existential — anything with no struct/enum name) fell through its final
  `elif concrete_type_name:` UNCHECKED, silently accepting an invalid program (both
  explicit and inferred args). The generic-METHOD path (`_check_type_param_bounds`)
  already routed every non-Copy bound through `_bound_satisfied` uniformly, so only
  the free-fn loop had the hole.
- **Fix 1 (the loop): an `else` safety net** — a type arg with no struct/enum name
  is routed through the SAME `_bound_satisfied`/conformance registry (the diagnostic
  is the design-93/105/108 "type `X` does not satisfy the `B` bound", anchored at the
  call, naming the INFERRED type for inferred args). Structural traits pass where the
  primitive structurally conforms; a user trait passes only via a registered
  `extension Int: T`.
- **Fix 2 (namespace): primitive → pseudo-struct conformance key.**
  `type_satisfies_bound` derived a conformance NAME only for STRUCT/ENUM/STRING, so
  `extension Int: Fooable` (keyed under `"Int"`, the same key trait-method dispatch
  uses) was invisible — a satisfied primitive user-trait bound would have FALSELY
  failed. Added `_PRIMITIVE_CONFORMANCE_KEYS` (INT→`"Int"`, FLOAT→`"Float"`; only
  these register as extensible pseudo-structs) so a primitive user-trait conformance
  is honored (fixes the method path's latent false-negative too).
- **Fix 3 (codegen, in scope for the satisfied-via-extension test): substitute the
  monomorphized receiver.** Calling a type-param trait method whose `T` resolves to a
  primitive (`run<Int>` with `extension Int: Fooable`) ICE'd ("Cannot determine struct
  type for method call") — in a mono'd generic body the receiver's stamped type is
  still the abstract `T`, so the design-57 primitive-pseudo-struct detection missed.
  `_generate_method_call` (calls.py) now substitutes `recv_saw` against the active
  `type_param_context` before naming the `Int`/`Float` pseudo-struct. Pre-existing
  (independent of the typecheck change), but blocked the required item-4 test, so
  fixed here to deliver it end-to-end (`run<Int>` / `run(5)` → 105).
- **AUDIT: ZERO latent violations.** The full suite + std + blade + libs were already
  clean of silently-accepted primitive user-trait bounds (mirrors the design 100/107
  sweeps) — no missing conformance to add, no bound to correct.
- Tests: `generic_primitive_bounds` (user trait satisfied via `extension Int/Float:
  Fooable`, explicit + INFERRED; prelude Comparable/Printable/Equatable over Int/
  Float/String; tuple arg via Equatable recursion), `errors/generic_primitive_bound_
  explicit` + `errors/generic_primitive_bound_inferred` (Int violates a user trait,
  explicit + inferred naming the inferred type), `errors/generic_tuple_bound_violation`
  (tuple type arg checked). Suite 964 (960 + 4), zero xfails; bootstrap ok (blade
  17+17, libs toml 4 + semver 4). Docs: NONE beyond this tracker — the RULE was always
  "bounds are checked"; this fixes the implementation to match (no user-visible rule
  statement changed). [109, 108, 93, 105, 57, 32, 48]

## Design 108 — ICE: generic parameter with a default VALUE (LANDED)
- **Root cause (codegen, post-typecheck).** `func f<T>(a: Int, b: T = 0)` called
  with the default OMITTED (`f<Int>(1)`, and after this fix also `f(1)`) emitted
  the LLVM call with too FEW args → llvmlite `IndexError: list index out of range`.
  A generic instantiation registers its defaults under the MANGLED name
  (`f$1$Int`), but the free-fn call-site default-fill keyed by the PLAIN name
  (`expr.name`), so the lookup missed and no default was materialized; a generic
  METHOD mono (`_declare_monomorphized_method`) never registered `method_defaults`
  at ALL. Both paths ICE'd. Fixes: calls.py keys the generic free-fn fill by the
  mangled instantiation name; generics.py registers `method_defaults` in
  `_declare_monomorphized_method`.
- **Semantics — DEFAULT-DRIVES-INFERENCE landed (the preferred branch, not the
  clean-error fallback).** `_solve_call_type_args` gained a default-driven phase
  (threaded a new `default_values` arg at the free-fn / method / design-105
  overload solve sites): an OMITTED default-valued parameter drives inference from
  the default's own type when the parameter is otherwise undetermined — `f(1)`
  infers `T = Int` from `b: T = 0`. Consulted only AFTER argument-driven solving
  (a supplied argument always wins — `f(1, 2.0)` infers `Float`), inside the
  inference snapshot (the default's moves/effects roll back — they already tainted
  the callee at its declaration).
- **Per-call default type check.** `_check_generic_call_defaults` validates each
  omitted default against the INSTANTIATED parameter type at every generic call
  (the design-53 declaration check runs against abstract `T` and is a no-op). A
  bare integer literal adopts an integer instantiation (range-checked) and is
  cleanly REJECTED against a non-integer one — `f<Float>(1)` with `b: T = 0` is a
  clean call-anchored error (bare `0` doesn't adopt `Float`), never an ICE. An
  inferred default that violates a bound (`b: T = Widget()` → `T = Widget`, not
  `Fooable`) is caught by the existing bound check naming the inferred type. Every
  failure mode is a clean anchored diagnostic; no path ICEs.
- **Design-105 overload sets compose.** A defaulted generic overload in a mixed
  set binds `g(1)` by filling `b` and infers its `T` from the default
  (`_try_infer_overload_candidate` now passes `default_values`); the concrete
  sibling `g("hi")` still wins by exact match.
- **FLAG (pre-existing, orthogonal — CLOSED by design 109).** A generic
  bound of a USER trait against a PRIMITIVE type argument was silently UNCHECKED —
  `func f<T: Fooable>(...)` accepts `f<Int>(1, 5)` even though `Int` has no `foo`.
  The bound-check loop in `_check_function_call` derives a `concrete_type_name`
  only for STRUCT/ENUM args (a primitive has none) and only special-cases
  Copy/Send/Sync/Equatable, so Comparable/Hashable/Printable/user-trait bounds on
  a primitive fall through unchecked. Affects EXPLICIT calls too (not a design-108
  regression; design 108's default-inference mirrors the explicit behavior
  consistently). The brief's "Int doesn't satisfy SomeTrait" bound test therefore
  uses a STRUCT default (`Widget`) to exercise the bound check that DOES fire. Fix
  is a route of the primitive case through `_bound_satisfied`/structural checks —
  broad, own change.
- Tests: `generic_default_value` (default used / overridden / explicit Int8
  adoption / generic method / defaulted generic overload in a design-105 set —
  output proves the default value flows), `errors/generic_default_value_float`
  (bare `0` vs `Float`), `errors/generic_default_value_bound` (inferred `Widget`
  default violates `Fooable`). Suite 960 (957 + 3), zero xfails; bootstrap ok
  (blade 17+17, libs toml 4 + semver 4). Docs: spec generics/inference paragraph +
  saw-lang skill inference bullet. [108, 93, 105, 53, 37, 55, 66]

## Design 107 — shadowing follow-ups: same-scope derived redefinition + for-loop vars (LANDED)
- **Item 1 (same-scope derived redefinition) — LANDED.** `var data = read();
  let data = parse(move data)` in ONE scope is now legal iff the initializer
  MENTIONS the binding being replaced (the design-100 mentions-rule extended from
  across-scope to same-scope); a non-deriving `let data = fresh()` after a
  `let data = …` stays the pre-existing DUPLICATE_VARIABLE error (message
  unchanged). let->let / var->var / let<->var all legal (new binding's mutability
  its own). Typechecker (statements.py `_check_let_statement`): the same-scope
  duplicate check is deferred until AFTER the initializer is checked, then gated on
  `_init_mentions_name`; a derived redefinition overwrites the scope entry directly
  (fresh VariableInfo id -> clean move state). Codegen: the old value drops AT the
  redefinition point — `_drop_redefined_same_scope` (resources.py) retires the old
  binding's innermost-scope cleanup entry and emits a flag-guarded drop (a
  `.copy()`-derived old value drops here; a `move`-derived one already cleared its
  flag -> no-op), extending design 100's captured-alloca cleanup to same-scope so
  there is no double-free. `_cleanup_scope`'s per-entry drop factored into
  `_emit_scope_var_drop` (shared). Tests: `shadow_redef_same_scope` (deinit oracle
  proves old drops at redefinition + new at scope exit, all mutability
  transitions, clean under libgmalloc), `errors/shadow_redef_nonderived`.
- **Item 2 (for-loop variables join the rule) — LANDED.** A for-loop var that
  shadows an enclosing binding is a rename error UNLESS the SEQUENCE (iterable)
  references the shadowed name (the initializer analog) — `for x in x.iter()` /
  `for i in 0..i` legal, `for x in ys` under an outer `x` an error; an enclosing
  LOOP VAR is an enclosing binding (nested inner same-name loop var non-derived =
  error). Typechecker: both `_check_for_loop` + `_check_for_loop_as_expression`
  call `_check_shadowing(variable, iterable, …)` with the loop scope active.
  Codegen (loops.py): the loop var is now shadow-safe — both generators snapshot
  the name->storage maps and `_restore_shadow_snapshot` after, so a derived
  `for x in x.iter()` no longer lets the post-loop `del` drop the OUTER binding's
  entry (the design-100 block-shadow hazard applied to loops); the outer binding
  (incl. an owning Vector, deinit-once) is restored + usable after the loop.
  Tuple-pattern loop bindings (`for (a,b) in pairs`) are NOT a parseable form (the
  parser binds a single IDENT) -> any tuple for-loop is a PARSE error before the
  shadow check, so the brief's "flat error" is satisfied at parse time (no for-loop
  pattern path to guard). Tests: `shadow_for_derived` (range + owning-Vector-iter +
  nested-loop-var, clean under libgmalloc), `errors/shadow_for_nonderived`,
  `errors/shadow_for_nested_loop` (exact positions), `errors/shadow_for_tuple_pattern`.
  Cross-cut: `shadow_redef_nested_owning` (a same-scope owning redefinition nested
  inside an across-scope derived shadow — the double-free hazard class — all three
  values deinit exactly once, clean under libgmalloc).
- **MIGRATION: ZERO** newly-illegal for-loop shadows across std + blade + libs +
  examples (the whole corpus was already clean — mirrors design 100's audit).
  Same-scope item only ADDS legality (no migration).
- **Both design-100 flags CLOSED:** (a) the headline `var data = read();
  let data = parse(move data)` now works in ONE scope; (b) for-loop iteration
  variables are covered by the rule.
- Suite 957 (950 + 7), zero xfails; bootstrap ok (blade 17+17, libs toml 4 +
  semver 4). Docs: spec bindings section + saw-lang skill (rule + gotcha). [107, 100, 42, 65, 99]

## Design 106 — reference forwarding: pass a received `&T`/`&var T` onward (LANDED)
- **Largely ALREADY WORKED; one real gap fixed + acceptance + tests + docs.** The
  design-96 flag (inside `f(r: &var Data)`, `g(&var r)` impossible → read_into
  routed through inlined helper bodies) was STALE: the design-56 `&var ref`
  re-borrow acceptance (`is_mut_ref_binding`, typechecker/expressions.py) + the
  codegen re-borrow (operators.py `_generate_reference_expr`: an Identifier bound
  to a REFERENCE type LOADs the held pointer, not `&alloca`) + design 88's
  frame-resident ref pointer already delivered forwarding end-to-end. VERIFIED at
  runtime across every brief shape: 1- and 2-level (f->g->h) for `&` and `&var`,
  mutation through a twice-forwarded `&var` visible at the root, `&var`->`&`
  downgrade, exclusivity-by-root-path (`&var r` + `&r` in one call → clean
  EXCLUSIVITY_VIOLATION at exact position via the Identifier-root access path), and
  a held ref forwarded ACROSS a suspend in a driven (nested-spawned) callee (value
  visible after resume). **PROJECTION-FORWARDING VERDICT: IN scope, works** —
  `g(&var self.field)` / deeper `&var self.a.b` fall straight out of the existing
  MemberAccess path machinery (`_build_access_path` / `_get_member_pointer`), no
  new code.
- **The ONE real gap (fixed): whole-`&var self` forwarding.** `g(&var self)` in a
  `&var self` method was rejected ("cannot take mutable reference to immutable
  `self`") — `self`'s VariableInfo is always registered `mutable=False`
  (self-mutability lives on `method.self_mutable`, not the binding), and the
  SelfExpr branch of `_check_reference_expr` only checked `self_info.mutable`. Fix:
  consult `self.current_method.self_mutable` — a `&var self` receiver is a mutable
  reference binding, so re-borrowing the whole self is sound (mirrors the `&var
  ref` param case); a `&self` method still cleanly rejects `&var self` (no upgrade).
- **Upgrade rejection message improved** (fix-on-discovery, clean-not-generic): an
  immutable reference param `r: &T` forwarded as `&var r` now gets a
  forwarding-specific diagnostic ("cannot forward `&` reference `r` as `&var`: a
  shared `&` reference cannot be upgraded to `&var`" + hint) instead of the
  misleading generic "declare with `var`" (the referent is not the caller's to
  re-var). Upgrade was already REJECTED; only the message was wrong.
- **ACCEPTANCE (design-96 flag CLOSED):** `std/net.saw` `read_into` re-simplified
  from the inlined-`net_read_once`-body workaround (manual scratch buffer alloc +
  `tcp_try_read` + `append_bytes` + free) to direct helper forwarding — the park
  loop now calls `net_read_once(self.fd, &var into)`, forwarding the held `&var
  into` onward across the internal io_wait park (net_read_once owns the scratch
  buffer + append). Same `while { … break }` shape as value `read()`; net_read_into
  + coro_spawn_nested_ref still green over real sockets.
- Tests: `ref_forwarding` (1-/2-level `&`+`&var`, twice-forwarded mutation,
  downgrade, whole-`self` + `self.field`/`self.a.b` projection), `ref_forwarding_
  suspend` (held ref forwarded across a suspend in a spawned worker's nested driven
  callee → 40), `errors/ref_forwarding_upgrade` (`&`-param → `&var`),
  `errors/ref_forwarding_self_upgrade` (`&self` method → `&var self`),
  `errors/ref_forwarding_exclusivity` (`&var r` + `&r` overlap), `ref_forwarding_
  suspend_nested` (forward a held ref INTO a suspending nested callee — the 106x88
  sub-frame ref-seeding path → 40). Suite 950 (944 + 6), zero xfails; bootstrap ok
  (blade 17+17, libs toml 4 + semver 4). [106, 96, 88, 56, 42, 34, 16]

## Design 104 — coro embedding: if-let/guard-let bodies + remaining generic shapes (IN PROGRESS)
- **Item 1 (suspending calls in `if let`/`guard let` bodies) — LANDED.** The
  design-101 clean-error residue: an optional-binding branch could not be CFG-split.
  Fix (coro_transform.py): `_mark_optional_binding_splits` (new prepare pre-pass,
  after the condition/try/match hoists) marks every `if let`/`guard let` whose body
  spans a suspension and renames its binding to a UNIQUE frame field (`__obN`),
  rewriting body uses — so design-100's `if let x = x` keeps inner `x: T` and outer
  `x: T?` in DISTINCT fields (a nested re-bind of the name, or a tuple pattern, is a
  clean anchored error, not a miscompile). `_collect_frame_locals` + `_collect_calls`
  gained IfLetExpr/GuardLetStatement branches (binding→frame field; recurse into the
  bodies so nested suspending calls embed). CFG split (`_split_if_let`/
  `_split_guard_let` via one `_optbind_dispatch`): emits the dispatch as an ordinary
  `if let` whose branches ONLY set `__state` (reuses codegen's has-value test+unwrap
  over `T?` — no synthesized Some/None match, which the parser rejects for `None`),
  stores the unwrapped binding into its frame field, then re-dispatches to the body
  states; guard-let's Some path flows to the continuation (the enclosing stmt loop
  lowers the rest into it), None path lowers the else-exit. IR-verified: nested
  `work()`/`s.read()` drive as `__Frame_*_resume`, zero plain `@work`/`@TcpStream_read`
  calls. Incidental: a statement-position blocking-extern (design 103) in a spanning
  if-let/guard body now offloads too (the branch is split). Tests: `net_iflet_guardlet_bodies`
  (socketpair recirc in an if-let then-body, a guard-let continuation, a guard-let
  else-body, and the `if let ok = ok` shadow — exact per-shape recirc counts); the
  two `errors/coro_suspending_method_in_{iflet,guardlet}_body` tests removed (shapes
  flipped ERROR→EMBED). Suite 940 (941 −2 err +1), bootstrap 17+17 + libs 4+4. [104, 101, 100, 84, 74]
- **Item 3 (struct-generic AND method-generic suspending methods) — LANDED.**
  `Dual<T> { func mix<U>(&var self, ...) }` where `mix` suspends was a clean design-74
  A5-rest error; now it drives. The `__drive` dispatcher routes a method that is BOTH
  struct-generic and method-generic to the generic-STRUCT path (was: any `inner.type_args`
  went to the method-only path, which has no template for a generic-struct method →
  the old rejection). `_drive_generic_struct_method` (expressions.py) resolves the
  method's OWN type args from the call, keys the mono by `mangle_named(method, struct_args
  + method_args)`, and threads `method_args` through `_effect_queue_generic_struct_method_mono`
  → `_build_generic_struct_method_mono` (effects.py), which now applies a COMBINED
  substitution (struct type params T→Int for `self`'s fields + the method's own
  params U→Bool for its params/locals) before + after the effect re-check.
  **Frame-key shape:** `_method_frame_key(struct, mangle_named(method, struct_args +
  method_args))` = `Dual_mix$2$<T>$<U>` — design 95's resolved-signature key extended
  with the method's type args. Test `coro_generic_struct_and_method` (2 struct × 2
  method = 4 distinct `__Frame_Dual_mix$2$*$*` frames, IR-verified; each combines a
  frame-resident `self.value.tag()` across a `yield_now` with the U arg → 11/12/21/22,
  so a collision would misprint); `errors/coro_generic_struct_and_method_generic_unsupported`
  removed. Suite 940, bootstrap 17+17 + libs 4+4. [104, 95, 74, 70]
- **Item 2 (cross-module generic driven templates, design-74 shape 4) — ALREADY
  WORKS; regression test added.** The brief's premise (the `_pristine_` capture is
  module-local) is STALE: all modules in one compilation unit are checked by ONE
  shared typechecker (sawc.py's per-module loop in dependency order), so
  `_pristine_generics` / `_pristine_generic_struct_methods` accumulate templates from
  EVERY module (in-tree and `--module-path`). `_splice_fn_mono` /
  `_build_generic_struct_method_mono` therefore find a template regardless of its
  defining module. VERIFIED by probes + the new test `coro_cross_module_generic`
  (module `modules/coro_provider.saw` defines a generic suspending free fn
  `amplify<T: Seed>` + a generic struct `Cell<T: Seed>` with a suspending `charge`;
  entry drives `amplify` NESTED at two types → 211 and `Cell.charge` directly at two
  types → 207/208; IR: distinct `Frame_amplify$1$Lo/$Hi` + `Frame_Cell_charge$1$*`,
  zero plain calls). The stale `_promote_nested_generic_calls` comment ("cross-module
  = shape 4 → reject") corrected. Docs: spec + skill shape-4 now supported.
  **FLAG (discovered, orthogonal — NOT fixed):** a NESTED generic call whose template
  suspends UNCONDITIONALLY without calling a type-param method (`func g<T>(x: T) -> T
  { yield_now(); x }` called nested) fails SAME-MODULE too — the template is not
  `poly_candidate`, so `_process_effect_monos` never builds its instantiation's
  suspend node, so `_promote_nested_generic_calls` can't promote it and it lowers as
  a plain call → a clean (not silent) sync-violation error on the synthesized resume.
  Precise blocker: build a generic instantiation's effect node when the TEMPLATE
  structurally suspends (a direct `__suspend`/`yield_now`/`sleep`, not gated on a
  type-param method), not only when `poly_candidate`. Workaround: drive it directly
  (`__drive`/`spawn`), or give the template a type-param method call. Suite 941 (+1),
  bootstrap 17+17 + libs 4+4. [104, 74, 70, 96]

## Design 105 — generic inference: overloads, later-arg solve, labeled args (LANDED)
- **Extends design 93 past its three explicit-args boundaries.** One feature
  commit + docs. Suite 944 (941 + 3), zero xfails; bootstrap ok (blade 17+17,
  libs toml 4 + semver 4). Bootstrap wall unchanged (baseline ~71.4s / 62.1 user;
  after ~71.1s / 61.9 user — within noise; generic overloaded calls are absent
  from the bootstrap corpus so the per-candidate sandbox adds ~0).
- **Overload sets.** `_resolve_overload` (all four callers: free/module fn +
  instance/static method) gained `expr`/`base_subst`. When no concrete (or
  explicit-type-arg generic) candidate matches, inference runs PER generic
  candidate via `_try_infer_overload_candidate` -> `_solve_call_type_args(...,
  silent=True, known_arg_types=...)` (each fully sandboxed; `known_arg_types`
  reuses the already-checked `_overload_arg_types` so no double `move`/effect —
  a failed candidate leaves ZERO residue). Exactly one solving-and-type-matching
  candidate is picked (solved args stamped on `expr.type_args`); >=2 -> clean
  ambiguity error listing candidates + solved type args (`<T=Int>`) + explicit-
  args/labels hint; 0 -> the existing no-match diagnostic. Concrete beats generic
  is untouched (design 55) — an inferred overload never changes a call that
  already resolved.
- **Later-arg solve.** `_solve_call_type_args` fixpoints over the arg list
  (bounded by param count): phase-1 non-closure args unify against `base_subst`
  ONLY (so a two-args-one-param conflict is still detected), phase-2 closures
  improve as `out` grows — a param gated by an arg to its RIGHT (incl. a closure
  before the value that fixes its `T`) now solves.
- **Labeled args.** `_infer_label_mapping` pairs args to params BY LABEL (design
  66 binding) before unifying; the per-candidate label FILTER also disambiguates
  a label-distinguished generic overload. NOTE: under Saw's trailing-defaults +
  forward-only-binding rules a *legal* labeled call cannot actually reorder a
  type-param-carrying argument, so the design-93 "mis-map" was latent-only; the
  mapping is threaded for the general model and for the overload type-match.
- **Codegen (the real enabler).** Two+ GENERIC overloads of one name previously
  collided (both -> `name$<args>`; the clean tree mis-resolved them even with
  EXPLICIT args — pre-existing, verified by probe). Registration now stamps each
  a distinct `$OL$` base (declared param-type sig; `$LB$` labels when they share
  a sig); codegen `generic_functions` + typechecker `_pristine_generics` + the
  call/spawn/`__drive` mono sites key by that base via `resolved_symbol`. A lone
  generic in a set keeps its plain name (byte-identical) -> inert for all existing
  code (no std/blade/libs set has 2+ generic overloads). Inferred args are marked
  `type_args_inferred` so a spawn/drive/coro RE-CHECK re-infers instead of
  mistaking the stamped args for an explicit-generic selection (`_has_explicit_
  type_args`). Inferred + explicit generic-overload args are now bound-checked.
- **FLAG (scoped limitation, clean not silent):** a driven/spawned generic
  *METHOD* OVERLOAD (2+ generic method overloads of one name, suspending) is NOT
  supported — only free-function generic overloads carry the per-overload codegen
  symbol; the coro/method-mono path still resolves a generic method template by
  `(struct, name)`. Free-fn generic overloads spawn/drive per resolved candidate
  (tested). Two generic overloads that BOTH solve at a call are an ambiguity
  error by design (give `<...>`).
- Tests: `infer_overload` (unique-solve generic-fallback + concrete; two-generic
  container-shape Wrap/Vector both instantiated; label-distinguished; later-arg
  closure-first; explicit selects the generic), `infer_overload_driven` (two
  suspending generic overloads spawned -> own bodies; a driven inferred generic),
  `errors/infer_overload_ambiguous`. Design-93 suite stays green. [105, 93, 55,
  66, 38, 95, 70, 74]

## Design 102 — runtime edge bugs: spawn-Void ICE + cancel wakes an io-parked task (LANDED)
- **Item 2 (cancel wakes an ALREADY-io-parked task — A3 remainder) — LANDED.** A task
  parked in `io_wait` on a permanently-idle fd, cancelled by a peer, never observed the
  cancel (the landed model only checked BEFORE parking; a blocked reactor poll never
  returned). FIX, layered + precise (no herd wake):
  1. Reactor self-wake pipe (portable self-pipe on kqueue/epoll; codegen/core.py):
     `saw_reactor_wake()` writes one byte to a process-global self-pipe whose read end
     `saw_reactor_poll` registers (one-shot, token 0 -> the latch loop skips it) each
     cycle and drains on return. `handle.cancel()` / `VoidTaskHandle.cancel()` call it,
     so a blocked poll returns promptly.
  2. Precise wake by cancel flag: a new `Resumable.__is_cancelled()` frame reader (reads
     `__cancel`); `__ambient_wake_io` + the MT worker wake scan now make an io-parked
     frame runnable when `__wake_reason() >= 0 OR __is_cancelled()` — so ONLY the
     reactor-latched frame(s) and the cancelled frame(s) wake; a non-cancelled sibling
     parked on another idle fd stays parked (net_precise_* unaffected).
  3. ST liveness for a `cancel_addr` peer cancel (which sets the flag WITHOUT a
     self-wake): `__ambient_run` scans (`__ambient_any_cancelled_io`) BEFORE blocking in
     poll and wakes a cancelled parked frame instead of polling an idle fd forever.
  4. Cancel propagation down the frame chain: the nested-sub-frame drive now copies the
     root's `__cancel` into the sub-frame each drive (mirroring the design-91 `__io_tok`
     propagation), so a `cancelled()` check INSIDE a nested `stream.read()` sub-frame
     observes a cancel set on the ROOT frame the handle points at. Without this the
     parked reader re-parked forever.
  5. net.saw: `read`/`read_into`/`write` (both overloads)/`connect` now re-check
     `cancelled()` at their park-loop top (accept already did) and return `Err(IoError)`.
  Tests (time-bounded; a hang -> runner failure): `net_cancel_parked_read` (ST parked
  reader peer-cancelled via cancel_addr; deinit-once oracle), `net_cancel_precise`
  (cancelled reader wakes while a sibling on another idle fd stays parked until its own
  data arrives -> `-1 2`), `net_cancel_parked_mt` (`TaskGroup(threads: 2)`, stable 5x).
  Closes the design-76 A3-remainder flag. Suite 937, bootstrap 17+17, libs 4+4. [76, 18, 90, 91, 89-b]
- **Item 1 (spawn-Void ICE — cooperative TaskGroup) — LANDED.** `group.spawn(void_body)`
  ICE'd: the frame correctly omits `__result` for a Void body (a `{..., void}` struct
  field is illegal LLVM), but the `__spawn_<f>` helper still built `__rp =
  &__fp[0].__result` and the handle was `TaskHandle<Void>` (join force-unwraps a
  zero-size `T?`). FIX (proper omission, no placeholder): a Void spawn now yields a
  dedicated non-generic `VoidTaskHandle` (cancel_ptr + group_ptr + slot, no
  result_ptr) whose `join()` drives to completion and returns Void; the spawn helper
  skips the `__rp` capture entirely for a Void frame. Typechecker `_check_taskgroup_spawn`
  returns `VoidTaskHandle` when the body is Void. SWEEP: `__drive_<f>` had the same
  hazard (read `__f.__result` unconditionally) — now returns Void with no result read
  for a Void driven body. The design-75 executor return-Int workaround is now DEAD and
  removed: `__tg_worker` returns `Void` (21b `spawn { void }` works since design 77) and
  `__drain_mt` holds `Vector<Task<Void>>`. Channels of Void are not a void-slot hazard
  (the type constructs; there's just no Void literal to `send` — a front-end value gap,
  orthogonal). Tests `taskgroup_spawn_void` (single- + multi-threaded, explicit-join +
  drop-drain, sum oracle 60), `coro_drive_void_body`. Closes the design-75 spawn-Void
  flag. Suite 934, bootstrap 17+17, libs 4+4. [75, 77, 21b]

## Design 103 — A6 runtime offload: `extern blocking` calls RUN in tasks (LANDED)
- **The last A6 half.** A blocking FFI call inside a suspending body (driven /
  spawned / a suspending `main`) no longer REJECTS — it OFFLOADS to a worker thread
  and PARKS on the job's pipe like any socket read, so siblings keep running while
  it blocks and the single cooperative reactor thread is never wedged. Closes the
  design-76 A6 remainder (thread-per-call v1 in place of the ledgered "pool").
- **Runtime shims** (`codegen/core.py _declare_io_runtime`, hosted-only weak seams).
  `saw_offload_start(fn, arg) -> job` mallocs a job record `{ fn, arg, result, done,
  pipe_r, pipe_w, thread }`, pipes it, and `pthread_create`s a worker running
  `__saw_offload_thread`: it calls the extern via the raw fnptr (`i64(i64)` thunk),
  stores the result, PUBLISHES `done` (atomic release), then writes one byte to the
  job's self-pipe. `saw_offload_done` (acquire-load the flag), `saw_offload_pipe_fd`
  (the readable fd), `saw_offload_take` (pthread_join = full barrier -> read result
  -> close pipe -> free). HAZARD discipline: the worker touches ONLY its own job +
  pipe write end; ALL wake routing stays in the reactor; the pipe byte + the join
  are the release/acquire boundary, so the result transfers single-owner with no
  data race (start owns -> thread fills -> take transfers). `saw_blocking_sleep(ms)
  -> ms` is the reference blocking primitive the tests drive via a `blocking func`.
- **Lowering** (`coro_transform.py`). A top-level blocking-extern call boundary
  (`let x = slow(arg)`, a bare/`let _` discard, or a design-83 tail `return
  slow(arg)`) is classified (`_classify_blk`) BEFORE frame layout and desugars in
  `_emit_blk_call` to `self.__blkjobN = __blk_start(slow(arg))` -> park loop
  `while __blk_done(job)==0 { saw_reactor_register(__blk_pipe_fd(job), read);
  suspend(IO_PARK) }` -> `<x> = __blk_take(job)`. `__blk_start` is a CODEGEN
  intrinsic (calls.py) that resolves the extern's `ir.Function` (a function address
  is not expressible in Saw) and bitcasts it to i64 + evaluates the Int arg; the
  three wrappers thin over the shims. The blocking-extern call is now a suspension
  point for `_spans_suspension` (its result local becomes frame-resident) and gets a
  frame-resident `__blkjobN: Int` handle (+ `_build_frame_init` seeds it 0). The
  typechecker (`__blk_start`/`__blk_done`/`__blk_pipe_fd`/`__blk_take` handlers)
  types them as Int and — crucially — `__blk_start` does NOT re-record the blocking
  effect (the offload REPLACES the direct call), so the synthesized `resume` stays
  suspension-free of the blocking source. Precise wake tokens + budget reset-on-park
  apply unchanged (the park reuses the design-91 `__io_tok` routing).
- **Cancel compose (design 102).** The park loop re-checks `__cancel` at its loop
  top and BAILS — a peer cancel writes the reactor self-pipe (design 102 item 1) or
  is caught by the pre-poll cancelled scan (item 3), which rouses the poll; the
  re-check exits the loop. The in-flight blocking call cannot be aborted, so take()
  still joins its worker on the cancel path (documented v1 limit: no leak, no race).
- **Anchor fix (item 3).** A blocking-extern call in a position the desugar cannot
  occupy (buried in an expression, a `try!`, an `if let`/`guard` body) is rejected
  in the transform ANCHORED AT THE USER CALL SITE (source_file threaded), never left
  to lower as a direct call and trip the synthesized `resume`'s sync check anchored
  at `__Frame_*.resume`. v1 also rejects a non-`(Int) -> Int` blocking extern
  (`_check_blk_whitelist`, anchored) — the offload thunk is `i64(i64)`; multi-arg +
  non-Int + a real pool are future work. The `sync`-context + freestanding
  rejections are UNCHANGED (correct).
- **Tests.** `offload_spawn_interleave` (a spawned task blocks on a real offload
  call while main's sleep-loop provably runs — 0,1,2 then 61; the 60 -> 61
  round-trip proves the Int flowed into the worker and back; a plain block would
  hang -> runner-timeout FAILURE; stable 8x), `offload_cancel_parked` (a task parked
  on an offload job is peer-cancelled via `cancel_addr`, wakes, observes cancel ->
  -1, deinit-once oracle; stable 8x), `errors/offload_buried_reject` (buried call ->
  user-anchored error, asserts the source basename), `errors/offload_freestanding_
  reject` (`--freestanding` COMPILE-FLAGS). Suite 941 (937 + 4), bootstrap 17+17,
  libs toml 4 + semver 4, zero xfails. [103, 76, 18, 22, 58, 102, 90, 91, 89-b]

## Design 101 — DF7: no silent blocking for suspending method calls in nested/trailing positions (LANDED)
- **Root cause (precise boundary).** The coro transform's wrapper hoists
  (`_hoist_suspending_conditions`/`_hoist_suspending_try`/`_hoist_suspending_match`)
  and the collect/reject walk key on `block.statements` and never look at
  `block.final_expr`. The parser parks a block's LAST bare expression there, so a
  suspending METHOD call buried in a TRAILING `if`/`else`/`match`/nested-`if` (the
  loop body's `final_expr`, e.g. `while going { …; if c { let x = try! s.read() } }`)
  was never statementized in time for the try/condition/match hoist to see it —
  it stayed wrapped in a `TryExpr` `_collect_calls` could not classify, slipped past
  every rejection, and lowered as a PLAIN blocking call (`call @TcpStream_read`), the
  silent DF7 miscompile (cooperative park a no-op). `_normalize_suspending_tails`
  (design 83) lifts trailing exprs to statements but ran AFTER two of the three hoists.
- **Fix (one canonical structural pass).** (1) Run `_normalize_suspending_tails`
  FIRST in `prepare`, before all three wrapper hoists — every suspending call then
  sits in statement position within some block, so the hoists + collect/split walk
  are exhaustive by construction. (2) `_split_match`: preserve the design-63
  `pattern` + `guard` (and carry pattern-derived binding names via a new
  `_pattern_binding_names`) — reconstructing arms from `variant_name`/`bindings`
  alone DROPPED literal/range/tuple patterns, so a suspension-spanning `match` over
  literal/range arms lost its patterns → spurious "match is not exhaustive" at 0:0.
  (3) `_reject_buried_suspend_call`: also flag suspending METHOD calls (not only
  free-fn/`receive()`) — a buried method call in an `if let`/`guard let` body
  (branches the split does NOT CFG-split) slipped through here and lowered plain;
  now a clean anchored rejection. Split-capable containers (if/while/for/match)
  never reach that method, so no over-rejection.
- **Shape matrix — every position now EMBEDS or ERRORS cleanly; no silent third
  outcome.** top-level stmt / trailing if / trailing else / trailing match arm
  (literal+range) / if-in-if depth 2 / if-in-while → EMBED (`net_nested_shape_matrix`,
  exact per-shape recirc counts). `if let` body / `guard let` body → clean anchored
  ERROR (`errors/coro_suspending_method_in_{iflet,guardlet}_body`). Closure body
  capturing a stream → clean NoCopy-capture ERROR. Verified with IR
  (`@__Frame_TcpStream_read_resume` drive, not `call @TcpStream_read`), not just exit
  codes.
- **Acceptance.** `net_budget_fairness` re-simplified from the DF7 workaround
  (read/write hoisted to the loop top level) back to the natural nested form (under a
  trailing `if`); still prints 5, still cedes to the sibling on the op-count budget
  (IR: driven sub-frames — a plain block would hang). Suite 932 (929 + 3); bootstrap
  ok (blade 17+17, libs toml 4 + semver 4); zero xfails. Docs: saw-lang skill's
  supported-shape story corrected (nested/trailing control-flow method calls now
  work; only if-let/guard BODIES reject). [101, 96, 84, 83, 74, 89-c, 92]

## Design 100 — shadowing: error unless derived from the shadowed binding (LANDED)
- **Rule.** A `let`/`var`/pattern/param binding that SHADOWS an enclosing binding
  (an outer local/param/capture in a parent scope, or an accessible module
  `static`) is a compile error UNLESS it is a visible refinement. Typechecker
  helpers in `statements.py` (`_shadowed_binding_pos` walks the current scope's
  PARENT chain + `namespace.get_static`; `_init_mentions_name` is a generic
  dataclass walk for any `Identifier`/`MoveExpr` use of the name; `_check_shadowing`
  the entry, `site=binding|pattern|param`). Wired at every binding-introduction
  site: let/var (`_check_let_statement`, main rule on the initializer), destructuring
  let (per bound name), single-name if-let/guard-let (main rule on the scrutinee —
  so `if let x = x` / `guard let x = x` stay legal), tuple/match PATTERN bindings
  (flat error — patterns bind, not compare; the hint says so), function/method
  params vs module statics, closure params vs enclosing locals. Same-scope
  redefinition is unchanged (still the pre-existing DUPLICATE_VARIABLE error);
  prelude/std names are not bindings. Diagnostic: `` `x` shadows the binding
  declared at FILE:L:C `` + a rename/derive (or patterns-bind) hint; positions
  exact (design 99).
- **MIGRATION AUDIT: only 1 illegal shadow in the ENTIRE corpus** (std + blade +
  libs + examples all compiled green; only `examples/use_after_move_shadow.saw`,
  a test that DELIBERATELY shadowed a moved-from binding to prove move-state is
  per-identity — migrated to a distinct inner name, intent preserved). Accidental
  shadowing was effectively nonexistent — the codebase was already clean.
- **CODEGEN double-free FIXED (pre-existing, fix-on-discovery).** Design 100 makes
  a derived SAME-name shadow of an OWNING binding idiomatic (`let nums = nums.copy()`,
  `if let x = x`), which exposed a latent codegen bug: scope-exit cleanup and the
  if-let path resolved a binding's storage/drop-flag by NAME, so a shadowing inner
  binding redirected the OUTER scope's cleanup to the inner (already-dropped)
  storage → double-free (SIGABRT/SIGTRAP), and `if let x = x` deleted the outer
  binding outright (ICE on later use). Repro'd on the clean tree (not my change —
  typecheck-only). Fix: (1) `_register_cleanup`/`_cleanup_scope` (resources.py) +
  the guard-let producer (conditionals.py) now CAPTURE the alloca+flag at
  registration and `_emit_drop_at` the captured pointer (never re-resolve by name);
  (2) if-let restores the shadowed enclosing binding instead of deleting it
  (conditionals.py); (3) `_generate_block` (methods.py) snapshots + restores the
  name→storage maps at block exit so a use of the outer name after a shadowing
  block is sound. Tests: `shadow_owning_lifetime` (derived owning shadow + outer
  reused; `if let x = x` + outer reused).
- **FLAG for the user — CLOSED by design 107 (both halves).** (a) The design
  brief's headline example `var data = read(); let data = parse(move data)` in ONE
  scope was left as the pre-existing "already defined in this scope" error (the
  dispatch scope pinned "same-scope redefinition: if already an error, unchanged").
  Design 107 item 1 opened same-scope redefinition under the SAME mentions-rule —
  it is now legal when derived. (b) For-loop iteration variables were DEFERRED by
  scope (the design-100 brief enumerated let/var/patterns/params, not for-loop
  vars). Design 107 item 2 brought them under the rule (sequence = initializer
  analog). See the design 107 tracker entry.
- Tests (OK): `shadow_derived` (derived let bare/move/call-wrapped/`.copy()`, var,
  if-let, guard-let unwrap — all run). Tests (ERROR, exact positions on both the
  shadowed decl and the shadow site): `errors/shadow_inner_let`,
  `errors/shadow_match_pattern`, `errors/shadow_param`, `errors/shadow_closure_param`.
  Docs: LANGUAGE_SPEC bindings section + saw-lang skill (rule bullet + gotcha).
  Suite 928 (922 + 6), bootstrap ok (blade 17+17, libs 4+4). [100, 99, 15, 42]

## Design 98 — `#file`/`#line`/`#function` source-location literals (LANDED)
- Magic literals expanding at their DEFINITION site to compile-time constants
  (zero runtime cost, freestanding-safe): `#file` → source basename (String,
  matches the design-69 panic prefix), `#line` → 1-based token line (Int),
  `#function` → enclosing fn/method BARE name (String; module scope → `<module>`).
  Lexer reads `#`-directives (unknown `#foo` = clean lex error); parser emits a
  `SourceLocationLiteral` atom carrying the file (stamped from the parser's
  source_file; interpolation sub-parser now inherits it) + token line; typechecker
  `visit_SourceLocationLiteral` freezes the value ONCE (idempotent — the post-coro
  re-check must not re-resolve, so `#line`/`#function` in a suspending body report
  the ORIGINAL source, not the frame method), returns String/Int; codegen emits a
  plain Int/String literal; `#line` is const-init-able (`_is_const_init` +
  `_const_from_expr`) so a top-level `static X: Int = #line` works. Generics report
  the generic's own file/line identically across instantiations; defaults report
  the default's definition site. Builds on design 99 (interpolation position
  rebasing) so `#line` inside `{...}` reports the real line. Tests:
  source_location_literals (method/generic×2/closure/default/top-static/main, exact
  pinned lines), source_location_suspending (spawned worker straddling two suspends
  → original line + bare name), errors/unknown_directive. Docs: spec Source-location
  literals section + skill debug-print idiom. Suite 922 (919+3), bootstrap ok. [98, 99, 69]

## Design 96 — nested suspending reactor methods at any depth (LANDED)
- The depth-2+ hang was NOT the design-91 wake token (token threading is correct
  at every depth). ROOT CAUSE: the effect fixpoint cannot see suspension arising
  SOLELY from a nested std METHOD call (a std method's effect node is absent — the
  gap `_scan_method_callees` works around), so a FREE fn whose only suspension
  source is a buried `stream.read()` was left `suspends=False`; the driven-closure
  walk skipped the caller→callee edge, the fn never joined the closure or got a
  frame, and it was emitted as a PLAIN blocking call whose buried `io_wait` wedged
  the single thread. 1-deep worked only because `_scan_method_callees` sees a
  method call directly in the root body. FIX (coro_transform.py): compute
  `structurally_susp_fns` (a free fn structurally suspends if its body calls a
  suspending method or reaches — via free-fn edges — one that does; transitive
  fixpoint) and follow such edges in the closure walk even when `suspends=False`.
- SECOND gap fixed same area: a suspending call in a `match <call> { … }`
  SCRUTINEE was never hoisted (hung even at DEPTH 1) — added
  `_hoist_suspending_match` mirroring the if-let/try hoists.
- DF6 (break/continue in a non-spanning if inside a spanning loop) root-caused +
  fixed here — see the DF6 entry below (now CLOSED).
- read_into: design-88-deferred `TcpStream.read_into(&var Data) -> Result<Int,
  IoError>` now works (the depth limit was the blocker) — OFFERED alongside value
  `read()` (accumulate into one buffer, no per-chunk alloc). Value read() NOT
  migrated.
- Tests: net_nested_method_two_deep / _three_deep (spawned worker → free fn(s) →
  read(), socketpair, deterministic), net_read_into, coro_break_reentered_in_loop.
  Suite 919 (was 915 + 4); bootstrap ok.

## Design 97 — libs/semver + libs/toml `blade test` harness fix (LANDED)
- Root cause of the recurring "libs blade test fail on a clean tree" flag
  (noted by designs 84/88/92): candidate (a). `blade test` compiles each test
  with `sawc` unless SAWC overrides it; the tester ran that compile through
  `system()` with `> /dev/null 2>&1`, so on a clean tree (no SAWC, no installed
  `sawc`) the "command not found" was swallowed and all tests reported FAILED.
  The tests + `import src.lib.*` self-path were always fine — the invocation hid a
  missing compiler.
- Fix (tester.saw, never-hide-errors): loud preflight — SAWC unset AND no `sawc`
  on PATH → one clear actionable error, stop (not N silent FAILEDs); compile+run
  via `shell_ok_loud` which suppresses only stdout and lets stderr through (sawc
  writes success to stdout, diagnostics to stderr; panic/failed-assert aborts to
  stderr) → a passing run stays clean, a compile error or a test's failure reason
  is surfaced.
- Coverage gap closed (blade_bootstrap.py): `libs/toml` + `libs/semver`
  `blade test` now run as a standard bar (SAWC set via ENV, as the main build
  already does), green (toml 4, semver 4); their gitignored `.blade/` cleaned
  after. TESTING.md updated. A user runs a lib's tests with nothing but
  `blade test` when `sawc` is installed / SAWC is set; on a clean tree the
  bootstrap sets SAWC for them.
- Suite 919 / 0 xfail; bootstrap ok incl. both lib suites.

## Design 93 — generic type-argument inference (LANDED)
- **NOTE:** no `designs/93-*.md` brief file exists on disk (the dispatch brief was
  the authoritative spec; recorded here). Retired the "type inference is not yet
  supported" rejection for generic free functions AND methods. `v.map({ $0.to_
  string() })` / `v.fold(0){...}` / `wrap(5)` / `first(7,"hi")` now infer their
  `<...>` from argument types; a method's own `<U>` is solved from the closure's
  inferred RETURN type (closure params come from the struct + phase-1 arg
  solutions). Commit 1 (feature + tests): unify abstract param types against
  actual arg types (`_unify_infer`, structural over function/optional/ref/ptr/
  array/tuple/struct-enum-args); a sandboxed pre-pass (`_infer_snapshot`/`_infer_
  restore` roll back moves + per-instantiation mono queues + `_poly_call_edges`,
  a throwaway suspend node catches enclosing-node effect edges) discovers arg
  types, then the SOLVED args are stamped onto `expr.type_args` (default-filled)
  so the existing explicit-path machinery (bounds, effect-poly recording, codegen
  monomorphization, coro-transform driven/spawned rewrite) runs BYTE-IDENTICALLY
  to an explicit call. Explicit `<...>` always allowed + wins; a partial explicit
  prefix pins its leading params and the rest infer; an unconstrained trailing
  param with a default type fills from the default. Clean diagnosable failure:
  underdetermined ("cannot infer type argument `T`" + explicit-args hint) and
  conflict ("required to be both `Int` and `String`") — never a silent wrong pick.
  Inferred args are bound-checked naming the inferred type; the generic-METHOD
  path previously did NO bound checking at all — added `_check_type_param_bounds`
  (Copy structural + `_bound_satisfied` for the rest), run on BOTH explicit and
  inferred method calls (fix-on-discovery). Driven (`__drive(run(move s))`) +
  spawned (`group.spawn(work(x))`) inferred generics monomorphize per INFERRED
  instantiation identically to explicit (the `__drive`/`spawn` handlers check the
  inner call first, so inference stamps `inner.type_args` before the mono
  rewrite). BOUNDARY (for the skill/spec): inference is single-pass left-to-right
  (non-closure args, then closures) — a param determinable only by a LATER arg
  than one it gates is not solved (give it explicitly); labeled + out-of-order +
  inferred is treated positionally (rare; give explicit args if it mis-maps).
  Overloaded-call generic inference (design-55 `_check_overloaded_*` paths) NOT
  wired — those still require explicit `<...>` on a generic overload (the design-55
  concrete-beats-generic model is unchanged; inference there would risk new
  cross-overload ambiguity — deferred). Retired obsolete
  `generic_method_requires_explicit_args` test. Tests: `infer_type_args` (free
  single/multi, method map/fold, mixed explicit+inferred, defaults, explicit-wins),
  `errors/infer_underdetermined`, `errors/infer_conflict`,
  `errors/infer_bound_violation`, `infer_generic_driven`, `infer_generic_spawned`.
  Suite 915 (910 −1 obsolete +6), bootstrap ok. [93, 36, 55, 70, 74, 37]

## Design 82 — per-file std visibility + prelude discipline (IN PROGRESS)
- **Part A (per-file std visibility) — LANDED.** Retired design 80's std-as-one-
  module deviation: `_vis_module_for_source` now keys each std/builtin file to its
  OWN member-gate module `("<std>", "<leaf>")` (was the single `("<std>",)`), so a
  private field/method of one std file is invisible to another — same rule as user
  modules. `_member_gate_allows` roots the package at `("<std>",)` for std-defined
  members so `public(package)` shares across std files (and excludes user code).
  Synthesized-provenance exemption unchanged; codegen/compiler-known-ness untouched
  (ACCESS check only). ABUSE AUDIT: **ZERO restructures / zero new `public(package)`
  needed** — design 80's public sweep already exposed every legitimate cross-std-
  file surface, so per-file gating is a pure tightening with no code churn. Gate
  verified live: temporarily un-`public`-ing `Vector.push` makes the builtin check
  reject its cross-file callers (directory.saw/env.saw/…) with a clean member-
  visibility error naming both std files; restored. Suite 905 (unchanged), bootstrap
  17+17 green. [82, 80]

## Design 82 Part B — prelude discipline (LANDED)
- **The prelude is now a CURATED ALLOWLIST, not "all std auto-merged".** Defined
  by its complement in sawc.py: `IMPORT_REQUIRED_STD_MODULES` (file, directory,
  path, data, channel, mutex, time, net, process, env, task — whole modules) +
  `IMPORT_REQUIRED_STD_SYMBOLS` (`Utf8Error` from string). `build_builtin_namespace`
  makes ONLY prelude symbols `directly_accessible`; the rest stay registered
  (compiler-known) but hidden. `import std.<mod>[.{A,B}|.*]` is a PRELUDE import —
  resolution is SKIPPED in the resolver (`imp.path[0]=='std'` → `continue`, symbols
  already in builtins) and `_process_std_import` un-gates the requested names (no
  `mod.Name` module alias — it would shadow common locals like `data`).
- **Gate + hint.** A bare source reference to a hidden std symbol (static call,
  struct init, free-fn call) errors: "`X` is not in the prelude and must be
  imported" + hint `add import std.<owner>.{X}`. `_std_name_gated` is exempt for
  std's own bodies (`_checking_builtins`) and synthesized coro output. A std-
  sourced method/function body re-checked in a user compile (design-84 spliced
  suspending std method) is checked permissively (`_decl_is_std_sourced` →
  allow_all_access) so it reaches its own internals.
- **No codegen collision (the design-84 IoError clash CLOSED).** Non-imported
  import-required std modules are EXCLUDED from codegen: `compute_std_codegen_exclusions`
  computes the compiled set = prelude ∪ imported ∪ transitive-dep-closure (comment-
  stripped source scan; `string`→`data`, `taskgroup`→`task` stay), `_filter_std_ast`
  drops excluded decls, and the merged-ns collision check skips them (`merge_into`
  `exclude=`). So a user may define its own `struct IoError`/`File`; `_shadows_hidden_std`
  lets the user decl replace the (uncompiled) merged builtin without a "defined
  multiple times" error. StringBuilder VERDICT: KEPT in prelude (borderline, common).
- **Migration.** 56 examples + 8 blade/src + 15 blade/tests gained `import std.X.{...}`
  for the non-prelude types they use (libs/sos needed none). New suite tests:
  `prelude_user_ioerror` (user IoError+File compiles/runs), `errors/prelude_tcp_needs_import`
  (bare TcpStream → clean import error), `prelude_import_makes_visible` (import
  un-gates Duration; Vector bare works). Suite 908 (905→+3), bootstrap 17+17. [82, 84, 80]

## Design 88 — references across suspension points (implement D6) (IN PROGRESS)
- **Core LANDED (commit 1).** A reference PARAM/LOCAL of a suspending function
  is now a frame-resident RAW POINTER across suspensions (`_enc_of` REFERENCE ->
  "ref"; field `UnsafePointer<T>`, pointer mut mirrors the ref; read rewritten to
  `self.name[0]` — the `__recv[0]` mechanism of 45-0c generalized). Drive site
  casts `&x`/`&var x` -> `UnsafePointer<T>` (`_ref_arg_to_ptr`), driver param is
  the pointer, frame seeds it directly. Re-typecheck ACCEPTS it (member access /
  mutation / method calls flow through the deref lvalue); synthesized resume is
  exempt from the design-81 `unsafe` marker. Ref field is NON-owning — exempt from
  drop flags, never dropped (deinit stays exactly-once). Both `&T`/`&var T` and
  `&var self`. Frame kinds allowing held refs: **DRIVEN-in-place = YES;
  SPAWNED-cross-task = NO** (`_reject_spawn_frame_refs` — a spawned frame with a
  ref param/across-suspend ref local is a hard error for BOTH single- and
  multi-threaded groups, confinement not merely Send). Tests:
  coro_ref_param_read/_mut/_self_method/_deinit_once + coro_spawn_ref_rejected.
  Suite 904 (was 899); bootstrap green.
- **Item 5 (nested ref + capability) LANDED (commit 2).** A NESTED suspending
  call's reference argument is seeded into the callee sub-frame as a pointer into
  the TASK frame (`_build_sub_frame` casts `&self.<field>` -> `UnsafePointer<T>`);
  a reference to a task-CONFINED local inside a spawned body is sound and allowed.
  The spawn rejection now fires ONLY on the spawn ROOT's own ref params/locals
  (its referent is the dead spawner stack) — NOT on embedded callees (refs can't
  escape owned values, so a nested callee can only get a task-frame pointer once
  the root carries none). Tests: coro_spawn_nested_ref (read_into-shaped helper
  holding a `&var` across a `yield_now` in a spawned worker, through the real
  multi-task scheduler). NET `read_into` over a real socket is BLOCKED by an
  orthogonal PRE-EXISTING limit: a suspending `stream.read()` buried TWO frames
  deep (spawn-root -> nested free fn -> nested method) HANGS — reactor token
  propagation reaches only one nesting level (value-based control hangs
  identically; NOT a design-88 issue). VERDICT: keep the value-based `read()`;
  defer a `&var Data` net read until that depth limit is fixed. Suite 905.
- **Items 4 + 7 LANDED (commit 3).** Item 4 VERDICT: KEEP the `sync`-body
  restriction on `Vector.with_ref`/`with_var_ref` — unlike a D6 held reference
  (task-confined stack/frame referent unreachable by other tasks), a container
  borrow projects into shared reachable storage a concurrent task could realloc
  across a suspension (iterator invalidation); confinement does not cover it.
  Documented in vector.saw. Item 7: spec concurrency updated (D6 implemented +
  driven/spawned boundary + with_ref caveat); saw-lang skill concurrency note
  added (references-across-suspend capability + spawn-root rejection + net stays
  value-based). **Design 88 COMPLETE** (scope items 1-7 all addressed).
- **FLAG (pre-existing, unrelated) — CLOSED by design 97.** `libs/semver` +
  `libs/toml` `blade test` suites fail on a CLEAN tree. Root cause: the tester ran
  the compile through `system()` with `> /dev/null 2>&1`, so with no SAWC set it
  silently fell back to a `sawc` that isn't on a clean PATH and swallowed the
  "command not found" — every test reported a mysterious FAILED. Not the
  `import src.lib.*` self-path (fine). See the design 97 entry.

## Design 94 — enum/Result payload sizing + temp-drop-at-merge (IN PROGRESS)
- **Codegen chain LANDED (commit 1).** Two frame-layout-sensitive bugs, both
  root-caused with a deterministic `-O0` repro (`blade build --force` 12/12
  SIGBUS at -O0; ~40% at -O1) + the design-85/86 discipline. (1) enum/Result
  CREATE paths (`_create_result_ok/err_for_return`, `_wrap_error_in_union`,
  `_generate_enum_init`) alloca'd the SMALLER variant struct but bitcast-LOADED
  the FULL `[N x i8]` payload — an OOB stack read past the slot; fixed to alloca
  the full payload (align 8), store the variant struct into its front, load the
  whole array. (2) The create-fix shifted the frame and exposed the real
  `Builder_build` crash: a statement TEMP created in a block's `final_expr` (an
  unbound method receiver — here `read_file(".blade/build-hash")` in the inner
  `if …equals(hash)`, itself the tail-expr of the outer `if not force` body) was
  registered in the ENCLOSING statement's temp list and dropped at the outer
  `if`'s MERGE block — reachable from the not-taken `else` where the temp was
  never initialized → `String_deinit` released an uninitialized (garbage) pointer
  → EXC_ARM_DA_ALIGN on the refcount atomic. Fix: `_generate_block` now drains
  the statement temps created during its `final_expr` at block end, on the paths
  that create them, before the merge. Suite 897 green; bootstrap green; `blade
  build`/`--force` reliable 15x + under libgmalloc (0 faults, O1 and O0).
- **Process module LANDED (commit 2 — the acceptance).** `Command.run() ->
  Result<Int32, ProcessError>`: Ok(code)=the command launched and exited with
  `code` (signal death still decodes to 128+signum via decode_wait_status);
  Err(ProcessError)=could not launch (`system()` returned -1, or the shell
  reported 127 "command not found"). `ProcessError` conforms to `Error`
  (Printable), names the failed program. Callers migrated: blade `builder.build`/
  `builder.run` (match; a launch failure → BuildError), `git` clone/checkout
  (Err → false). Forced-failure test `examples/process_error_surfaced.saw`
  (nonexistent command → Err, error names the program). Suite 898; bootstrap
  green; blade `build`/`--force` reliable 10x + gmalloc 6x at O1 AND O0, zero
  faults — that reliability WITH the process module back in build()'s frame (the
  original design-92 trigger) is the proof the codegen chain is fixed. The
  design-92 `write(s: String)` overloaded-suspending-method fix stays deferred
  (design 95).

## Design 92 — failable calls return Result: no silent swallow (IN PROGRESS)
- **net module LANDED** (commit 1): `TcpStream.write(bytes: Data)`,
  `read() -> Result<Data, IoError>`, `TcpListener.accept() -> Result<TcpStream,
  IoError>` all surface failure; the swallowing `write_all`/`write_all_str`
  removed. read's EOF is `Ok(empty)`, DISTINCT from `Err` (was: empty Data meant
  both). Forced-failure test `net_error_surfaced` (connect-to-closed-port → Err;
  peer-closed read → Ok empty). Enabling compiler work: `Result<Void, E>` support
  (enum void-payload filter + Ok/void create/extract + bare `return`→Ok(Void) +
  match `Ok(_)` on void); `ResultOkWrap`/`ResultErrWrap` re-typecheck visitors (the
  post-coro-transform re-check was skipping their rewritten inner expr → ICE);
  coro-transform TRY-HOIST (a `try! recv.m()` in a driven body now hoists to a
  driven temp + `try move __t` — the tried suspending call was hidden inside a
  `TryExpr` the nested-call scan couldn't see, so its `io_wait` park never
  integrated with the executor → hang; the `move` consumes the temp so its owning
  payload is not double-dropped/closed).
- **CLOSED by design 95 — coro-transform now drives OVERLOADED suspending
  methods.** Driven/embedded suspending-method frames are keyed by the design-55
  RESOLVED SIGNATURE (the overload-mangled `$OL$`/`$LB$` symbol the typechecker
  stamps: `mangled_symbol` on the method AST, `resolved_symbol` on the MethodCall)
  via one canonical `_method_frame_key` helper — a non-overloaded method has no
  symbol and keeps its plain `{struct}_{method}` key (unchanged). `write(s: String)`
  is re-added as the text overload of `write(bytes: Data)`; the `.to_data()` call-
  site workarounds are reverted (httpd/echo/net examples).
- **file/directory/env LANDED** (TIER 2, Bool→`Result<Void, IoError>`): `file`
  {`remove`,`rename`}, `directory` {`create`,`remove`,`set_current`}, `env`
  {`set`,`unset`,`set_cwd`} now surface the errno; `exists`/`contains` stay
  genuine boolean questions, `list`/`current`/`get` stay `T?`. Public
  `IoError.from_errno(syscall)` factory added (net.saw) as the cross-std-module
  constructor. blade callers migrated (`match`/`let _` on the Result). Forced-
  failure tests: file/directory/env `_error_surfaced`.
- **codegen LANDED (design-92 dogfood):** enum/Result payload SCRATCH allocas are
  now 8-aligned (`_entry_alloca(..., align=8)` on the extract byte-arrays). The
  payload is `[N x i8]` (ABI align 1) but is bitcast-and-loaded as the variant's
  field struct (8-aligned pointers/i64); the 1-aligned slot faulted on arm64
  depending on frame layout — a heisenbug the added Result monomorphizations
  tipped (`blade build --force` SIGBUS ~1/3; deterministic under MallocScribble).
  This alone made the bootstrap reliably green again.
- **process DEFERRED — a SECOND, DEEPER latent codegen bug.** `Command.run() ->
  Result<Int32, ProcessError>` is implemented + all callers migrated (blade
  git/builder, process examples + `process_error_surfaced`) and the full suite
  passes 898 — BUT it re-tips a distinct crash in blade's large `build` frame (a
  garbage-POINTER read / translation fault at teardown, ~40% normal). ROOT (found,
  NOT yet safely fixed): the enum/Result CREATE paths (`_create_result_ok/err`,
  `_wrap_error_in_union`, `_generate_enum_init`) alloc the (smaller) VARIANT struct
  but bitcast-load the FULL `[N x i8]` payload → an out-of-bounds stack read past
  the slot. The obvious fix (alloc the full payload, store the variant into its
  front) is suite-green but shifts the frame and tips YET ANOTHER latent issue in
  `Builder_build` (blade went 8→20/20) — so it needs a focused codegen
  investigation, not a design-92 rider. Process change is reverted; std stays at
  `run() -> Int32` until the codegen bug is fixed. (Evidence: crash reports show
  `Builder_build` garbage/alignment reads at teardown; masked under lldb + normal
  heaps; MallocScribble makes it deterministic.)
- **TODO:** land process once the codegen OOB/uninit bug is fixed; borderline
  `file.write`/`seek` `Int?`→Result (report); the overloaded-suspending-method
  fix that restored `write(s: String)` is DONE (design 95, below).

## Design 95 — driven-method frames keyed by resolved signature (LANDED)
- Coroutine transform keyed a driven suspending METHOD's frame by
  `(struct, method-name)`, so two OVERLOADS of one name collapsed to a single
  frame (design 92's deferred `write(s: String)`). Fix: one canonical
  `_method_frame_key(struct, name, resolved_symbol)` helper keys every driven/
  embedded/direct-drive method frame by the design-55 resolved-signature symbol
  (`mangled_symbol` on the method AST at the definition side; `resolved_symbol` on
  the MethodCall at call sites); non-overloaded methods carry no symbol → plain
  key, byte-for-byte unchanged (coro_*/taskgroup_*/net_* families untouched).
  `_driven_method_roots` re-keyed by frame key so a directly-driven overload also
  gets its own frame; `_find_method` disambiguates by symbol. `net.TcpStream`
  re-gains `write(s: String)` (whole-string bytes) alongside `write(bytes: Data)`;
  `.to_data()` workarounds reverted at the net examples. New regression test
  `net_write_overloads` (spawned worker calls BOTH overloads back to back).
  Suite 899 (+1), bootstrap green, libs (toml/semver) green.

## Design 90 — reactor lost-wakeup on the 2nd sequential connection (LANDED)
- **Root cause (VERIFIED with an instrumented repro, NOT the brief's guessed
  suspects).** It was NOT one-shot re-registration, wake-all clearing the wrong
  frame, an fd-map collision on a reused fd, or a poll/deadline skip. The reactor
  wakes ALL io-parked frames on ANY readiness event (coarse level-triggered
  retry), so EVERY parking op must re-verify its OWN fd and re-park on a spurious
  wake. `read`/`write`/`accept` already loop on would-block; **`TcpStream.connect`
  did NOT** — it parked ONCE on `io_wait(fd, 1)` then called `tcp_connect_check`,
  a v1 STUB that unconditionally returned 0 (success). In a multi-connection
  workload a client's connect-park was spuriously roused by the reactor's wake-all
  on a DIFFERENT fd's event (the listener becoming readable) BEFORE its own socket
  was writable; it trusted the wake, wrote on the still-unconnected socket →
  ENOTCONN (errno 57, confirmed via instrumentation), and `write_all_str` silently
  bailed on the hard error. The request was never sent, so the accepting server
  parked forever on the read of that connection. Single-connection round-trips
  (`net_accept_roundtrip`) work because no other fd triggers an early spurious wake.
- **Fix.** `connect` now LOOPS like the other ops: after each `io_wait(fd, 1)` it
  RE-VERIFIES completion by re-issuing the nonblocking `connect()` and classifying
  the result — connected (`EISCONN`/0), still-connecting (`EINPROGRESS`/`EALREADY`
  → re-park), or a real failure. Classification lives in a new compiler shim
  `saw_errno_connect_state()` (OS-divergent errno values stay in the compiler,
  mirroring `saw_errno_would_block`); `tcp_connect_check(fd, port)` gained the port
  arg to rebuild the sockaddr for the re-connect. This makes an arbitrary SEQUENCE
  of io-parks across multiple accepted fds (incl. fd-number reuse across connection
  turnover) each get their wakeup; the never-block invariant + earliest-deadline
  poll are untouched (no scheduler change).
- **FLAG (pre-existing, orthogonal — NOT fixed here, API-change scope):**
  `TcpStream.write_all`/`write_all_str` SILENTLY bail on a hard write error
  (`w < 0` -> `going = false`, no signal) — this is exactly what MASKED the connect
  bug (the ENOTCONN write vanished with no error). Their return type is `Void`, so
  surfacing the error means changing the signature to `Result<Void, IoError>` (a
  public-API change touching every call site) — deferred as a genuine design
  decision rather than silently widened here. With connect fixed the socket is
  connected before any write, so this path no longer fires in practice, but a real
  broken-pipe mid-stream would still be swallowed. [90, 84]
- **Result.** `probe_loopdiag` (server serves N=2 + 2 clients, one group) now
  round-trips fully (both connections read+write; result 2,1,1). Tests (all
  deterministic on content, time-bounded — the design-86 runner timeout catches a
  regression as a FAILURE not a wedge): `net_serve_two_connections` (N=2),
  `net_serve_three_connections` (N=3), `net_fd_reuse_across_connections` (one
  client, two strictly-sequential connections reusing the freed fd number on both
  ends), `net_two_concurrent_parked_reads` (two readers parked on different
  socketpair fds both wake). Updated `examples/net_loopback_echo.saw` to the new
  `tcp_connect_check(fd, port)` re-verify loop. Docs: saw-lang skill net note
  rewritten (multi-connection accept-loop now works; the per-op re-check is
  internal). Suite 888 (from 884), all net_*/coro_*/taskgroup_* green, bootstrap +
  libs green. [90, 76, 84, 89]

## Design 91 — precise reactor wakeup (retire wake-all) (IN PROGRESS)
- **Core landed.** The reactor no longer wakes ALL io-parked frames on any
  readiness event. `saw_reactor_register(fd, write, token)` carries a udata
  pointer (kevent.udata / epoll_event.data) = the parked frame's `__wake`-word
  address; `saw_reactor_poll` reads back each ready event's udata and LATCHES
  that word to 0 (ready), so only the frame(s) whose (fd, direction) fired wake.
  The latch is a persistent word (not an edge) → a fire that races the park is
  caught on the next scan (no lost wakeup, ST or MT). The scheduler
  (`__ambient_wake_io` + MT `__tg_worker`) wakes an io-parked frame only when its
  `__wake_reason()` has become >= 0. Nested-call routing: a new frame field
  `__io_tok` holds the ROOT frame's `__wake` address (a driven root sets it on
  first resume; each nested drive propagates it down), so an `io_wait` buried in a
  sub-frame routes its wakeup to the top-level frame the scheduler schedules.
  design-90 connect re-verify KEPT (belt-and-suspenders). Many-frames-one-fd:
  different directions = independent registrations (both precise); same direction
  = last-registrant-wins (documented, unsupported pattern). [91, 76, 90, 89b]

## Design 89 — executor unification: one ambient scheduler (IN PROGRESS)
- **Prep — LANDED (612e53d).** Coro-transform **static-visibility fix**: a
  suspending std method that names a module-private `static` (e.g.
  `TcpListener.accept` -> `INVALID_FD`) now compiles when spawned/driven — the
  const initializer is inlined at the reference site during the transform
  (`_inline_static_refs`). Before this, `accept()` could not be embedded at all,
  so NO accept-loop program compiled (`net_fd_leak` never exercised `accept()`,
  masking it). `read`/`write` reference only free functions, hence unaffected.
  Test: `net_accept_roundtrip.saw` (spawned server accepts ONE loopback conn +
  serves a GET; deterministic). Suite 884, bootstrap 17+17, libs 4+4. [89, 84]
- **Core unification (items 1-6) — DEFERRED to a follow-on (design 89-b),
  re-ledgered with analysis.** Evidence-based risk call (the brief's "defer if
  large/risky" escape). PROVEN this session: (1) the gap is real — `probe_gap`:
  a spawned child runs ONLY at `join`, never while main parks (today's split
  executors). (2) A SECOND, INDEPENDENT blocker gates the accept-loop
  acceptance: a **design-76 reactor lost-wakeup** in the multi-connection
  accept-loop — `probe_loopdiag` (server serves N=2 + 2 clients, ONE group)
  accepts conn#0, serves it, accepts conn#1, then the **read on the 2nd
  connection never wakes** (hangs at marker 911). A SINGLE accept round-trip
  works. Unifying the executor does NOT fix this — the accept-loop acceptance
  needs BOTH the unification AND the reactor fix. **The reactor lost-wakeup is
  now CLOSED (design 90, LANDED — see below); it unblocks the 89-b accept-loop
  acceptance, which now only needs the executor unification.** Why the core is large/risky + the recommended per-commit
  plan (ambient heap-singleton via a `static Atomic<Int>` addr, per-frame
  group-id membership, active-frame reentrancy skip, deinit-exactly-once box
  hand-off, MT bifurcation, then the reactor fix, then the op-count budget):
  see the STATUS section of `designs/89-executor-unification.md`. Repro files
  under `.build/scratch/` (`probe_gap`, `probe_loopdiag`, `probe_accept*`).
  [89, 45, 52b, 76, 75, 86]

## Design 89-b — executor unification core (WORKTREE, IN PROGRESS)
- **Steps a+b+c — LANDED (worktree).** The ambient cooperative scheduler:
  ONE per-thread sweep over an intrusive list of every live single-threaded
  TaskGroup (`static __saw_exec_head`, threaded through a new group `next`/
  `registered` field pair). Realized the design-89 "one shared run queue" as a
  registry-of-group-queues (each group keeps owning its boxes) — this keeps the
  battle-tested per-group deinit-exactly-once machinery intact and DISSOLVES the
  flat-queue box-ownership-hand-off hazard the STATUS flagged, while being
  behaviorally the pinned model (eager spawn, structured join, nested groups,
  reentrancy). One parameterized sweep `__ambient_run(term_group, term_slot)`
  reused verbatim at all three drive points: ALL (entry), GROUP (Deinit),
  FRAME (join); each SKIPS frames `active` on the C stack (reentrancy guard —
  task-joins-task yields to the one scheduler, never re-enters a live coroutine).
  A suspending `main` that also spawns is boxed as the ROOT member and driven by
  the shared sweep (`__exec_run_root`), so a spawned sibling runs whenever main
  parks (the core gap: `probe_gap` now INTERLEAVES `0,100,101,1,102,2,7` instead
  of `0,1,2,100,101,102,7`). Design-45 single-task main (no spawn) keeps the
  lighter single-frame executor; MT groups (workers>=2, design 75) keep their own
  worker pool + queue and never join the ambient list (bifurcation preserved).
  Bars green: suite 888, bootstrap 17+17, libs toml 4/4 + semver 4/4. NOTE: one
  non-reproducible `dep_build` SIGABRT flake observed under load (that test shells
  out to compile+run subprocesses; its path uses no concurrency, so unrelated to
  this change — baseline + reruns all green). [89, 45, 52b, 76, 75]
- **Test matrix — LANDED (worktree).** Three NEW tests for behavior the old split
  executors could not produce (suite 888->891): `net_accept_loop_concurrent`
  (ACCEPTANCE — a server task accept-loops N=3, SPAWNING a handler per connection
  into its OWN group that runs eagerly on the shared scheduler while the server
  parks, + 3 concurrent client tasks; round-trips all N, deterministic 3/3);
  `taskgroup_spawn_and_loop` (the core gap — main parks in a sleep-loop while its
  spawned child INTERLEAVES `0,100,101,1,102,2,7`, not the old
  `0,1,2,100,101,102,7`); `taskgroup_nested_ambient` (nested groups + a task
  joining its own inner children = the reentrancy hazard, cross-group eager
  interleave). Existing coverage survives and validates the rest under the ambient
  scheduler: `taskgroup_sleep_ordering`/`structured_join`/`unjoined_drop`/
  `two_task_yield`/`cancel_check`, `net_io_sleep_interleave`, `net_serve_two/three_
  connections`. Updated the now-stale per-group-executor comments in
  `taskgroup_nested_groups` + `taskgroup_suspending_parent_sleep` (results kept).
  **DF finding (pre-existing, reproduces on parent):** spawning a function whose
  param transitively references a std struct (e.g. `f(h: TaskHandle<Int>)`) ICEs
  "Undefined struct: TaskGroup" during frame layout — unrelated to executor
  unification; reentrancy is instead tested via nested-group joins. [89, 52b, 76]

## Design 89-c — cooperative op-count budget (LANDED — CLOSES the 89 family)
- **The fairness backstop.** A task that keeps completing suspending io ops WITHOUT
  ever parking (an always-ready socket) can no longer monopolize the single-threaded
  ambient scheduler — the design-89 item-6 starvation caveat. Op-count, not
  wall-clock (kernel-friendly, deterministic); no preemption, no language surface,
  purely at existing suspension points.
- **Mechanism (codegen/core.py `_declare_io_runtime`).** A process-global op counter
  `__saw_op_budget` (default 128) + two weak/monotonic-atomic seams: `saw_op_budget_
  tick()` decrements and returns non-zero (self-resetting to the default) when
  exhausted; `saw_op_budget_reset()` restores it. Each net io primitive
  (accept/connect/read/read_into/write×2), on its NON-parking success path, ticks and
  force-`yield_now()`s when the tick fires (park-and-immediately-reschedule → cede to
  siblings), and calls reset after a genuine `io_wait` park (already ceded). The
  counter is self-resetting on exhaustion, so it works uniformly under the
  ambient/MT/single-task/`__drive` executors with NO scheduler or synthesized-executor
  edits; monotonic-atomic keeps MT workers race-free (shared budget there, benign).
- **Zero overhead for sync code.** Only a suspending io primitive ever charges the
  counter — code that makes no such calls never touches it. Well-behaved tasks (<128
  non-parking ops between parks, which reset the budget) never hit the forced yield,
  so existing coro_*/taskgroup_*/net_* interleavings are UNCHANGED (suite green, no
  interleaving test needed adjustment). Channel receive was deliberately NOT
  instrumented: in the ST cooperative runtime a channel consumer that outruns its
  producer DRAINS the channel and then parks on empty (the producer only runs when
  the consumer cedes), so an always-ready channel monopoly is impossible — only io,
  fed by the kernel/peer independent of the local scheduler, is the real vector.
- **Test `net_budget_fairness`.** A `recirc` task reads one socketpair end and writes
  the bytes back into the OTHER (refilling the read side) → every read is always-ready
  and never parks, an endless io loop whose only exit is a stop flag a sibling sets
  after its own turns. Without the budget `recirc` never cedes → the program hangs
  (the design-86 runner timeout turns that into a FAILURE); with it, `recirc`
  force-yields every 128 ops, the sibling completes and sets stop, and it prints 5.
  Deterministic (pure op-count) + time-bounded. Verified discriminating: neutering
  the tick makes it hang (SIGKILL 137), the real budget prints 5.
- ~~**DF7 (pre-existing coro-transform silent miscompile).**~~ CLOSED (design 101). A
  suspending METHOD call buried under a nested/TRAILING `if`/`else`/`match` in a
  driven/spawned body lowered as a PLAIN blocking call (cooperative park a no-op).
  Root cause: the wrapper hoists + collect/reject walk ignored `block.final_expr`
  and ran before `_normalize_suspending_tails`, so a call in a trailing-expression
  position was never statementized in time to be hoisted/classified/rejected.
  Fixed by running tail normalization FIRST; also preserved match `pattern`/`guard`
  in `_split_match` and taught `_reject_buried_suspend_call` to flag buried
  suspending METHOD calls (if-let/guard bodies now reject cleanly). See the design
  101 section above. [101, 96, 84, 83, 74, 89-c]
- Suite 929 (928 + `net_budget_fairness`); bootstrap ok (blade 17+17, libs toml 4 +
  semver 4); zero xfails. Docs: saw-lang skill concurrency caveat replaced with the
  landed backstop + residual pure-compute limit; LANGUAGE_SPEC concurrency gained an
  implicit-yield + op-count-budget bullet. **The design-89 executor-unification family
  (89 / 89-b / 89-c) is now COMPLETE.** [89-c, 89, 89-b, 45, 52b, 76]

## Design 87 — consolidate literal coercion + stable type-ids (IN PROGRESS)
- **Item 1 (ONE literal-coercion pass) — LANDED.** Integer-literal fixed-width
  typing now routes through the EXISTING expected-type propagation
  (`_apply_literal_expected_type`), which became the single recursive pass that
  pushes a fixed-width expectation to a bare literal AND through the transparent
  constructs that forward a value: unary minus (range-checks the FOLDED value so
  Int32.min's magnitude is admitted), if/match/block arm results, and
  array/tuple/map/set element positions. `visit_IntLiteral` (typechecker) adopts
  the expectation; codegen `visit_IntLiteral` materializes at the resolved
  fixed-width width. AUDIT (all were BROKEN pre-87): array-literal elements into
  `[IntN;M]` (stored platform-wide, no range check), tuple elements (same),
  if/match arm results (narrowed but NO range check), compound-assign RHS
  (`x += 1`, Int8 → i8-vs-i64 ICE), default parameter values (silently wrapped),
  Map/Set literal keys+values (unchecked) — now all coerce + range-check
  uniformly. DELETED the per-position `_check_fixed_width_literal` calls the
  central pass subsumes: method/func tail-return, `return <expr>`, regular +
  overloaded call args, struct-field + custom-init args, enum payload. KEPT
  `_check_fixed_width_literal` + `_fixed_width_binop_type` for the two
  SIBLING-OPERAND positions (comparison `b < 200`, arithmetic `b + 0`) — the
  expectation there is the other operand's type, discovered only AFTER checking,
  so it genuinely can't route through a declared-slot expected type. INVARIANT
  held: no fixed-width expectation ⇒ platform Int (`let x = 5`, Int/Int
  arithmetic byte-identical); full suite is the oracle. Tests:
  `literal_coercion_positions` (all positions round-trip) +
  `array_element/tuple_element/compound_assign/if_arm/default_param/map_literal_key`
  `_..._out_of_range_error` (6 clean range errors). Suite 883 (from 876),
  bootstrap 17+17, libs 4+4. [87, 65, 53, 77, 81, 54, 29]
- **Item 2 (stable erased-error type-ids) — LANDED.** Replaced design-72's
  per-compilation MONOTONIC COUNTER (memoized by mangled name, order-dependent)
  with a deterministic FNV-1a 64-bit hash of the mangled type name (same
  constants as the runtime Hasher in builtin.saw), masked to the platform word so
  it fits the vtable's `int_type` type_id slot. The id is now a pure function of
  the type NAME, so the SAME concrete type gets the SAME id in EVERY compilation —
  a future separate-compilation boundary would agree on `is<T>()`/`take<T>()`, not
  just the current whole-program build. `is<T>`/`take<T>` behavior identical (both
  the vtable bake and the downcast compare call the one `_type_id_for`); existing
  downcast tests green. COLLISION POSTURE (documented in `_type_id_for`): a 64-bit
  FNV space over distinct mangled names makes an accidental clash negligible (a
  birthday clash needs ~2^32 conformers in one program); ids are compared only for
  EQUALITY (never as a sentinel), so `0` is now a legal id (the old counter
  reserved it). Test: `tools/test_stable_type_id.py` (IR-level, in the
  `test_debug_info.py` family) — compiles two programs that conform `Circle: Shape`
  in DIFFERENT declaration positions among DIFFERENT companion types, extracts the
  type_id baked into Circle's vtable from `-O0` IR, and asserts (a) the two are
  IDENTICAL (the old counter would give Circle id 1 vs id 3 → order-dependent, and
  this test would fail) and (b) it equals FNV-1a("Circle") (pins the scheme).
  Docs: spec Integer-Types section (a bare literal adopts a fixed-width expected
  type everywhere) + saw-lang skill literal note. Suite 883, bootstrap 17+17,
  libs 4+4. [87, 72, 51, 48]

## Design 86 — httpd-runtime cleanup (IN PROGRESS)
- **Item 3 (`&var self` mutation on an opt-encoded frame-local across a suspend)
  — LANDED.** ROOT CAUSE: in `_generate_method_call` (codegen/calls.py), the
  `is_mutable_self` receiver-addressing chain handled `Identifier`/`SelfExpr`/
  `MemberAccess`/`ArrayIndex` but NOT `ForceUnwrap`. A `Data`/`StringBuilder`
  frame-local accumulated across a suspend is opt-encoded (design 62), and the
  transform rewrites a bare receiver `acc` → `self.acc!` (`_rewrite_node` →
  `ForceUnwrap`). That `ForceUnwrap` receiver fell through to the `else` branch
  that STORES a loaded copy into a fresh `self_temp` alloca and mutates the copy —
  so `acc.push(...)` / `req.append(move chunk)` across a park wrote to a discarded
  temporary and the real frame slot never changed. Silent in a pure loop (probe
  printed 0 instead of 3); a HANG in net_http_roundtrip (the empty `req` never
  matched the request terminator, so the handler re-`read()`s forever while the
  peer waits for a response → deadlock). FIX: add a `ForceUnwrap` branch that
  addresses the optional payload IN PLACE via `_generate_reference_expr(Reference
  Expr(mutable=True))` — the design-84 `&(opt!)` addressing (None-checked GEP to
  the payload slot) — so the `&var self` mutation lands on the real frame field
  and survives the suspend. Safe: `ForceUnwrap` is not an owned-temporary, so no
  stmt-temp double-free. TESTS: `net_accumulate_across_reads` (server appends 5
  lock-step "abc" chunks into a frame-resident Data across read+ack parks, asserts
  the FULL "abcabcabcabcabc" buffer + len 15) and the UN-QUARANTINED
  `net_http_roundtrip` (moved scratch → examples/; a socketpair read→build→write
  HTTP round-trip, now RUNS 5/1). Suite 876 (from 874), bootstrap 17+17, libs 4+4,
  zero xfails. [86, 84, 62, 44]
  - **httpd acceptance = the socketpair-reduced suite test (net_http_roundtrip).**
    The live `.build/scratch/httpd_sw.saw` now COMPILES + its `handle_connection`
    (`req.append(move chunk)` across `read()`) is unblocked, but the infinite
    `accept`-loop server as written does NOT serve a live GET — verified: it binds
    + prints "Serving …", but a `curl` GET returns empty. FLAG (separate
    architectural gap, NOT item 3): the loop does `let _ = group.spawn(handle…)`
    and NEVER `join()`s, so the spawned handlers only run at the group's Deinit
    (never, the loop is infinite); main's `accept`-park entry-executor does not
    drive a sibling group's run queue. net_http_roundtrip works because it
    `join()`s (which drives the group to completion). The fix is executor
    unification (main's park should drive spawned siblings) — a real concurrency-
    architecture design, out of scope here; the brief explicitly accepts the
    socketpair-reduced form as the acceptance. Skill runtime-limit note rewritten. [86]
- **Item 2 (variadic libc declaration audit) — LANDED (CLEAN, no fix needed).**
  Swept every libc declaration the compiler/std makes: all `_libc_func` call
  sites + all direct `ir.Function` decls in `sawc/codegen/*.py`, and every
  `extern "C"` func across `sawc/std/*.saw`. Cross-referenced each name against
  its C prototype. The COMPLETE set of variadic-in-C functions the toolchain
  declares is exactly FOUR — all ALREADY declared variadic:
  - `printf` — codegen core.py:336, `var_arg=True` ✓ (Float print path; Saw
    Float is f64 so no float→double promotion gap).
  - `snprintf` — codegen core.py:348, `var_arg=True` ✓ (int/float→string; ints
    promoted to i64 for `%lld`/`%llu`).
  - `fcntl` — codegen core.py:1354, `var_arg=True` ✓ (fixed in design 85 — the
    bug that motivated this audit).
  - `open` — std/file.saw:13, declared `func open(path, flags: Int32, ...)` ✓
    (variadic since introduction f6ebd80; called with the variadic mode arg by
    File.create/append `open(ptr, 577, 420)`).
  Every OTHER extern is genuinely fixed-arity in C and correctly declared
  non-variadic (malloc/free/fwrite/fflush/usleep/clock_gettime/memcpy/pthread_*/
  close/kqueue/epoll_*/kevent/strlen/strcpy/strcat/abort/socket/bind/listen/
  accept/connect/read/write/lseek/access/unlink/rename/mkdir/rmdir/opendir/
  readdir/getenv/setenv/system/popen/fread/strlcpy/strlcat/fabs/… + the saw_*
  seams). NO mis-declared variadic function remains after the design-85 fcntl
  fix — nothing to change. Behavioral variadic coverage already in the suite:
  the design-85 net tests (fcntl→O_NONBLOCK, the load-bearing case),
  `file_simple` (open-with-mode create→write→reopen→read-back roundtrip), and
  the float print/format tests (printf/snprintf varargs). Suite 874 unchanged. [86, 85]
- **Item 1 (test-runner run-phase timeout) — LANDED.** `run_executable` now
  runs each test's binary under a hard, process-GROUP-aware wall-clock cap
  (`RUN_TIMEOUT_SECS = 30`): `subprocess.Popen(..., start_new_session=True)` +
  `communicate(timeout=)`, and on expiry `os.killpg(SIGKILL)` the whole group
  (not just the child) then reap. This closes the wedge where a hung test that
  spawned OS threads / a grandchild holding the inherited stdout pipe would
  block the post-timeout reaper forever — a live hazard for every concurrency
  brief. A timed-out test is recorded FAILED (timeout), the runner never hangs.
  Proof: `tools/test_runner_selftest.py` (NOT globbed by the .saw suite) — 4
  cases incl. the grandchild-inherited-pipe wedge, all return < 10s under a 2s
  cap; plain hang + nonzero-exit + normal-exit paths covered. Suite 874,
  bootstrap 17+17, libs 4+4. [86]

## Design 84 — Safe net API: TcpListener/TcpStream owning types (IN PROGRESS)
- **Coro lift landed (commit 1):** nested suspending METHOD call embedded
  as a sub-frame in a driven/spawned body (`let s = recv.m()`, bare
  `recv.m(...)`, tail `return recv.m(...)`), driven across the caller's
  resumes exactly like a nested free-function call. Method frame keyed
  `{struct}_{method}`, `__recv` points at the receiver's caller-frame
  storage; `&self`/`&var self` both work; result threading + Deinit-once
  verified. CLOSES design 74 A5-rest shape 1 (the old `examples/errors/
  coro_buried_suspending_method.saw` rejection became the positive
  `examples/coro_nested_suspend_method.saw`, value 1012). Enabler: `&(opt!)`
  is now an addressable lvalue (address of the optional payload, None-checked)
  — a general language addition (typechecker `_is_lvalue` + codegen
  `_generate_reference_expr`) that lets an opt-encoded owning receiver in a
  frame be addressed.
- **Cross-module std method embedding landed (commit 2):** `TcpStream.read` /
  `TcpListener.accept` etc. live in std.net (imported), which is checked under a
  SEPARATE builtin typechecker — so the main one cannot infer their suspendability
  or reach their effect nodes. Fixes: (a) `build_builtin_namespace` computes the
  suspending (struct, method) set from the builtin typechecker's finalized graph
  and carries it forward (`typechecker._std_suspending_methods`); (b) the transform
  scans the MERGED extensions (not just entry_ast) for method ASTs + a structural
  body-scan (`_iter_method_calls`) discovers std method callees the edge-walk can't
  reach; (c) the std method frame + resume splice into entry_ast; the original std
  method stays as harmless dead code. Verified: a spawned worker's `stream.read()`
  parks on io_wait internally and wakes via the reactor (single-nested-call
  round-trip `examples/net_owning_echo.saw` — reliable, 5/5).
- **std.net owning types landed:** `TcpListener` (listen/local_port/accept) +
  `TcpStream` (connect/pair/read/write_all/write_all_str), both NoCopy with
  Deinit-closes-once; `IoError: Error` (errno via a new `saw_errno` seam). fd is a
  private `Int32`; the public surface has ZERO raw fds/pointers. Raw `tcp_*`/`net_*`
  layer kept as the private impl. `Data.append_bytes(ptr,len)` + `Data.byte_ptr()`
  added (pointer-signature = design-81 marked domain) for the socket read/write path.
- **DEVIATION from the pinned read/write signatures (flag):** `read(&self) -> Data`
  (empty = peer closed) + `write_all(&self, bytes: Data)` by move +
  `write_all_str(&self, s: String)`, NOT the brief's `read(&self, into: &var Data)
  -> Int` / `write_all(&self, bytes: &Data)`. Reason: a `&`/`&var`-reference PARAM
  cannot yet live in a coroutine frame (references opt-encode to a struct field of
  reference type, which the re-typecheck rejects). Reference-params-across-suspend
  is a separate, larger coro lift; deferred. The value API meets the GOAL.
- **⚠ PRE-EXISTING coroutine bug BLOCKS a true echo / the httpd runtime (FLAG,
  fix-on-discovery deferred with analysis):** a driven/SPAWNED worker whose body
  makes a SECOND nested suspending call AFTER the FIRST one PARKS on io_wait hangs
  at runtime (heisenbug — a `print` in the worker body perturbs it away). CONFIRMED
  PRE-EXISTING and NOT design-84: it reproduces with plain suspending FREE functions
  (`.build/scratch/probe_freefn.saw`) and hangs on the tree BEFORE this brief's first
  commit (checked out HEAD~1). Two nested calls where neither parks work
  (`probe_two_write`), and TWO nested yield_now calls work (`probe_two_nested`); the
  failing combination is specifically first-call-parks-then-second-call under the
  TaskGroup executor + reactor. Almost certainly an uninitialized frame field / run-
  queue re-entry issue (design 52b/76 territory). Effect: the socketpair ECHO
  (server: read→write) and the httpd worker (read_request→write) hang at RUNTIME; the
  deterministic suite test is therefore a single-nested-call-per-worker send+verify
  round-trip (reliable). Needs a dedicated fix pass.
- **httpd migrated (commit 3):** `.build/scratch/httpd_sw.saw` rewritten to the
  owning API — accept-and-`group.spawn`-per-connection, handler reads the request +
  writes the response over `TcpStream` methods. Compiles + reaches codegen with ZERO
  `unsafe`, ZERO raw fds, ZERO pointers (acceptance met). Kept in scratch (not
  examples/): it is an infinite accept-loop server AND its handler hits the
  read→write two-nested-call runtime bug, so it is not a suite smoke.
- **Tests landed:** `examples/net_owning_echo.saw` (single-nested-call send+verify
  round-trip in a TaskGroup, reliable) + `examples/net_fd_leak.saw` (Deinit-closes-
  exactly-once probe: 600 open+drop with no fd exhaustion). Suite 870.
- Deferred tests (blocked by structure / the pre-existing bug): peer-close→read 0
  (a completed child's fd only closes at group teardown, so a parked reader can't
  observe EOF in-flight); connect-failure→IoError (design-76 `tcp_connect_check` is
  a v1 stub that never reports failure); full echo (read→write = the two-nested-call
  bug). IoError:Error is exercised by the httpd's `{e}` interpolation (compiles).
- Docs: LANGUAGE_SPEC net section rewritten to the owning API (raw layer = private);
  saw-lang skill net section rewritten (+ the runtime-limit warning). CLAUDE.md not
  touched (it never documented std.net).

## Design 81 — Unsafe surface (`unsafe` marker + escape rules + with_ref) (IN PROGRESS)
- **String-escape rider (silent backslash-drop) — LANDED.** `"\r\n"` mis-lexed as
  `"r\n"` (len 2, bytes 114/10): the lexer dropped the backslash on any UNKNOWN
  escape and kept the raw char. Fixed in `read_string`: added `\r` (CR 13) and
  `\0` (NUL 0, counted by len — interior NULs are representable), and any OTHER
  unknown escape is now a clean lex error (``unknown escape `\d` ``) — never a
  silent drop. Supported set is exactly `\\ \" \n \t \r \0 \u{...}` + `\{ \}`.
  CRLF-in-SOURCE already lexes cleanly (a `\r` between tokens is skip_whitespace);
  verified (a real-CRLF .saw compiles + runs). Tests: `string_escapes` (\r\n =
  13/10, \0 counted, \t = 9), `errors/string_unknown_escape`. Docs: spec string
  section + saw-lang skill escape list. Suite 856, bootstrap 17+17, libs 4+4. [81, 07]
- **Fixed-width arithmetic literal-coercion rider — LANDED.** Arithmetic mixing a
  fixed-width local with a bare int literal (`b + 0` for `b: Int32`; suffix locals
  too) ICE'd "i32 != i64" (the checked-arith intrinsic saw i32 vs the platform i64
  literal). Design-77 item 9 covered COMPARISON position only; now extended to
  general ARITHMETIC (`+ - * / %`, both operand orders, all fixed-width kinds): the
  literal adopts the fixed-width operand's type (typechecker `_fixed_width_binop_type`
  range-checks it + types the result as the fixed-width type; codegen reconciles the
  literal's width via the existing `_reconcile_int_width`). Out-of-range literal =
  clean error; Int/Int mixing unchanged. Tests: `fixed_width_arith_literal` (5 ops,
  both orders, suffix local, Int/Int untouched), `errors/fixed_width_arith_literal_
  out_of_range`. Un-flags the design-77 item-8 note. Suite 858, bootstrap 17+17,
  libs 4+4. [77, 65, 53, 81]
- **CORE (marker + escape rules + with_ref) + std/example sweep — LANDED** (commit
  da64eb0). `unsafe <expr>` marks a raw-pointer op whose pointer flows INVISIBLY
  (deref/index/write, pointer arith, binding a pointer produced by a call) in a
  function whose own signature carries no `Unsafe*` type; a cast naming
  `UnsafePointer<T>` (and any op transitively inside it), a pointer field/param/arg
  are already VISIBLE (no marker). Marked domain = signature carries a raw pointer
  OR a `self`-receiver method of a struct with a raw-pointer field (field decl is
  the marker → container access methods stay marker-free; a no-`self` factory like
  Box.make shows the marker). `unsafe`-on-nothing = clean error. Grammar: `unsafe`
  just below assignment, looser than every operator; `unsafe p[0] = 5` marks the
  whole store (parser lifts off the lvalue). `Vector.with_ref`/`with_var_ref`
  (generic-R, `sync` body, non-escaping lend) REPLACE the removed `ref_at`;
  taskgroup executor migrated (returns a `__ResumeOutcome` struct out of the
  borrow). Synthesized coro code exempt by provenance. TESTS (commit follows):
  unsafe_surface_ok + errors/unsafe_{deref,write,arith,binding}_no_marker +
  unsafe_marker_on_nothing (rule rows), vector_with_ref + errors/
  with_var_ref_invalidation + vector_ref_at_removed. DOCS: spec Unsafe Code
  section rewritten (visibility rule + table; the `poke` example now marks its
  store), saw-lang skill unsafe section + ref_at gotcha, CLAUDE.md digest.
  DEVIATION (documented + defensible): the `self`-method-of-a-pointer-field-struct
  domain rule is a faithful reading of "the field decl is the visible marker" that
  keeps the sweep proportionate (container ACCESS methods marker-free, factories
  marked) — it matches the brief's item-3 list exactly (Box.make marked; Vector/
  Arc access not). Suite 867, bootstrap 17+17, libs 4+4. [81, 80, 46, 42, 29]
- **CI rider (Linux `_NSGetArgc`/`_NSGetArgv` link failure) — LANDED.** The first
  GitHub Actions run failed on ubuntu: `std/env.saw` used Apple-only crt_externs
  `_NSGetArgc`/`_NSGetArgv`, so every Linux link died with "undefined reference to
  `_NSGetArgc`". Fixed by UNIFYING (not forking per-OS): the C entry `main` is now
  declared `main(i32 argc, i8** argv)` and its codegen prologue stashes both into
  private module globals `@__saw_argc`/`@__saw_argv` at startup; two seam functions
  `__saw_get_argc()`/`__saw_get_argv()` (in `_declare_argv_runtime`) read them on
  EVERY platform. env.saw's `argc`/`arg` read those seams; the `_NSGet*` externs are
  deleted. Verified: env_simple + an args probe run correctly on macOS (argc/argv +
  argv[i] strings); `--target x86_64-unknown-linux-gnu --emit-ir` shows ZERO
  `_NSGet*` references and `main(i32, ptr)` + the argv globals. Suite 854, bootstrap
  17+17, libs 4+4 green (macOS). Remaining CI verdict awaits the next Actions run
  (Linux link). [81, 41]

## Design 80 — Member visibility (fields + methods) + std under the gate (LANDED)
- **Commit 1 (feature + std/libs/blade sweep + tests) — LANDED.** Struct FIELDS
  and extension METHODS (incl. init/static) are now private-by-default OUTSIDE
  the defining module, same modifier family as top-level (`public`/
  `public(package)`/`public(parent)` per member); same-module unrestricted.
  **Probe verdict: the hole was REAL** — on baseline `v.length = 1000` was
  accepted and a bounds-checked `v.get(500)` read OOB through safe code
  (returned garbage, exit 0). Now a clean compile error (headline lock
  `vis80_vector_length_invariant`). Mechanics: parser/AST visibility on
  StructField + Method; namespace StructSymbol.field_visibility+def_module,
  FunctionSymbol.def_module+satisfies_trait; typechecker gate at field read
  (`_check_member_access`), field WRITE (assignment lvalue in statements.py —
  the headline), memberwise struct literal (after design-66 reinterpretation),
  and method/static/init calls. Module identity keyed on SOURCE FILE so the
  merged prelude is distinguishable: std/builtin = one module `("<std>",)`,
  user code keeps its module_path — kills the prelude bypass for the ACCESS
  check only (codegen compiler-known-ness untouched). Trait-conformance methods
  exempt (satisfies_trait). SYNTHESIZED-ACCESS EXEMPTION BY PROVENANCE:
  coro-transform output (spawn/drive wrappers, synthesized main, frame
  resume/__wake_reason) carries `is_synthesized`; its member access skips the
  gate (reaches std/frame internals by construction — this cleared ALL the
  taskgroup/coro/net breakage: 66× TaskGroup.__enqueue + 66× TaskHandle.result_ptr
  were the tell). **Bypass audit (worked only via the prelude bypass before):**
  every std public method (Vector/Map/Set/String/StringBuilder/Data/Path/Arc/
  Box/Channel/Mutex/Task/TaskGroup/numeric/net/…, 231 methods annotated
  `public`), plus public error/result FIELDS that user code reads — AllocError
  (size/align), Utf8Error (offset), CommandOutput (stdout/exit_code), SlabHead
  (bump/free), Range/RangeInclusive; and cross-module fields in libs+blade —
  semver Version (major/minor/patch), toml TomlError (message/line), blade
  Dependency/Manifest.root_dir/Cli/BuildError/ParseError/LockData.manifest_hash.
  **DEVIATION (documented):** std is ONE module for its internal boundary — the
  user↔std boundary is what closes the hole; std-internal cross-file access
  stays unrestricted rather than per-file-gated (per-file surfaced 182 mostly
  public-API cross-references; the single-module choice is lower churn/risk with
  the identical security guarantee). NOTE: Saw has no struct-destructuring
  patterns, so the brief's "pattern" case reduces to enum-variant matching
  (follows enum visibility, unchanged). Tests: vis80_field_read/write/literal
  _error, vis80_method/static_private_error, vis80_public_members_ok
  (public field/method/static/init + public(package) + trait-conformance),
  vis80_same_module_ok, vis80_vector_length_invariant. Suite 851 (from 843),
  bootstrap 17+17, libs 4+4. [80, 66, 44, 52b]

## Design 77 — Generics & closures completion + accumulated riders (LANDED, subset)
**Status:** items 1 (spawn-Void), 2 (generic-bound propagation), 3 (DF-C2 closures
satisfy Copy) + its get-UAF follow-up, 4 (DF-C1 closures in frames), 7 (Global
rename), 8 (unary minus fixed-width), 9 (comparison literal coercion), 10 (tuple/
destructure across suspend) — **LANDED**. Items 5 (buried suspending method
sub-frame) and 6 (cross-module generic driven) — **RE-LEDGERED** (central
transform surgery, budget spent on item 4; rejections stay clean + anchored).
Item 11 (docs) — spec + skill limits updated below. Two pre-existing bugs FLAGGED
(not regressions): `__drive(f(move owning_arc))` double-frees the moved param
(gmalloc-only; item 4 note); a bare-literal fixed-width LOCAL stores at platform
width (item 8 note). Suite 843 (from 825 baseline), bootstrap 17+17, libs 4+4,
zero xfails throughout.
- **Item 7 RIDER (rename `Global` -> `GlobalAllocator`) — LANDED.** TRUE rename
  (not a `type` alias — that would shatter allocator identity). Swept all `.saw`
  (std alloc.saw struct + `Allocator` conformance, every `= GlobalAllocator`
  default and `GlobalAllocator()` construction across vector/map/set/box/arc/
  channel/mutex/task/taskgroup/stringbuilder/data/net, blade/manifest, libs,
  examples) and the compiler's hardcoded `struct_name="Global"` sites
  (existentials/results/generics/expressions/statements) -> `"GlobalAllocator"`.
  Mangled names shift `$Global` -> `$GlobalAllocator` uniformly (nothing external
  links them; registration + lookup agree since the mangler keys on the struct
  name). `Global` no longer resolves (clean `undefined function` /
  does-not-conform error). Spec + saw-lang skill updated (CLAUDE.md on disk
  carries no `Global` mention). Test `errors/global_renamed_unknown`. Suite 835,
  bootstrap 17+17, libs 4+4. Standing policy oracle: whole suite green.
- **Item 8 RIDER (unary minus on fixed-width ints) — LANDED.** `_check_unary_op`
  now accepts signed fixed-width `Int8`..`Int64` (was `Int`/`Float` only);
  unsigned negation is a clean error ("an unsigned integer has no negation").
  Codegen negates via the existing checked subtract at the operand's WIDTH, so
  `-Int8.min` panics ("integer overflow") like `Int`. A negated integer LITERAL
  const-folds to the negated constant at width (`-128i8` = Int8.min directly,
  not a runtime negation of the bit pattern), and the typechecker range-checks
  the FOLDED value (`-200i8` is a clean error). Un-dodged the platform-Int
  `0 - 1` sites (map/taskgroup) and `0.0 - mantissa` (string) to `-1`/`-mantissa`.
  Tests: `unary_minus_fixed_width`, `unary_minus_int8_min_panics`,
  `errors/unary_minus_unsigned`, `errors/unary_minus_literal_out_of_range`.
  - **FIXED (design 80 run, rider):** a fixed-width int LOCAL from a BARE literal
    is now NARROWED to its annotated storage width. `_generate_let_statement`
    coerces the RHS int value to the annotation's LLVM width before the alloca
    (trunc/sext/zext by signedness); the typechecker already range-checked the
    literal, so it is value-preserving. `-a` on a bare-literal Int32.min local now
    overflow-panics at i32; a wire-format struct built from narrowed locals
    round-trips. Tests fixed_width_let_narrow, fixed_width_let_negate_panic. STILL
    FLAGGED (separate pre-existing): arithmetic mixing a fixed-width local with a
    bare literal (`b + 0` for `b: Int32`) ICEs "i32 != i64" — reproduces with a
    suffix local too; belongs with a fixed-width arithmetic-coercion pass. [53, 65, 80]
  Suite 839, bootstrap 17+17, libs 4+4. [59, 76, 53]
- **Item 9 RIDER (comparison-position literal coercion) — LANDED.** Codegen
  already coerced a bare literal to the other comparison operand's fixed-width
  type, but WITHOUT a range check — `fd < 200` for `fd: Int8` silently compared
  against the wrapped value -56. The comparison typecheck now runs the design-65
  `_check_fixed_width_literal` range check on both operands (a no-op unless one
  side is a bare literal and the other a fixed-width int), so an out-of-range
  literal is a clean error. Un-dodged the seven `(0 as Int32)` comparison casts in
  std/net.saw (`fd < 0`, `!= 0`, `>= 0`, `== 0`). Tests
  `comparison_literal_coercion`, `errors/comparison_literal_out_of_range`. Suite
  841, bootstrap 17+17, libs 4+4. [65, 76]
- **Item 10 RIDER (tuple / destructuring across a suspend) — LANDED.** Two frame
  opt-encoding gaps from design 76: (a) a TUPLE local held across a suspend ICE'd
  ("cannot store {i64,i64} to {i1,{i64,i64}}*") — already fixed incidentally by
  item 4's `_is_optional_type` optional-wrap change (a tuple is a
  LiteralStructType the old "not a struct" guard skipped); locked by
  `coro_tuple_across_suspend`. (b) `let (a,b) = f()` destructuring across a
  suspend DROPPED the bindings ("undefined variable a") — the transform's
  `_collect_frame_locals` only saw plain `let name`, not `DestructuringLet`.
  Now each tuple-pattern leaf is collected as a frame local (typed from the
  source tuple's position) and `let (a,b)=v` lowers to a fresh temp +
  `self.a = __t.0; self.b = __t.1` (auto-wrapping opt-encoded fields). Wildcards,
  nested patterns, and direct-tuple sources all work. Test
  `coro_destructure_across_suspend`. Suite 843, bootstrap 17+17, libs 4+4. [44, 62, 76]
- **Item 5 (A5-rest shape 1: buried suspending method sub-frame) — RE-LEDGERED
  (per the brief's escape hatch; rejection stays clean + anchored).** The FEATURE
  (embed a nested suspending METHOD call `let r = c.step()` as a sub-frame — the
  Part-0b method twin) still needs the design-74 triad: (a) make the phase-1
  frame-prep a FIXPOINT that discovers method callees while preparing (today
  `_collect_calls`/`closure` is a fixed set of free-function names; method
  sub-frames aren't in `fbs`), (b) receiver addressing — `__recv = (&var
  self.recv) as UnsafePointer<Struct>` into the CALLER frame's field (only a
  simple frame-local receiver is addressable; `foo().m()` / `self.f.m()` need
  spilling), (c) build the method frame + thread it into `fbs` so
  `_build_sub_frame`/`_emit_nested_call` (which already accept a `recv_value`)
  drive it. `_build_frame_init` already supports a method `__recv`. Bounded but
  it touches the central transform flow — and item 4's closure-in-frame surgery
  (this same territory) surfaced several subtle exactly-once/UAF hazards that took
  the bulk of this brief's budget, so bundling shape 1 too risks the 834-test bar.
  Workaround is exact and the rejection names it (drive the method directly, or
  wrap in a nested free fn). [74, 44, 45]
- **Item 6 (A5-rest shape 4: cross-module generic driven) — RE-LEDGERED (per the
  escape hatch; rejection stays clean + anchored).** `_pristine_generics` /
  `_pristine_generic_methods` capture ENTRY-module templates only, so
  `_build_fn_mono` / `_splice_fn_mono` return False for an imported template and
  the nested/driven generic call is rejected (anchored) by `_classify_call`.
  Lifting needs: (a) snapshot imported-module generic templates into the pristine
  maps (keyed to avoid cross-module name clashes), (b) design-68 canonicalization
  — the mangled instantiation key computed in the transform must agree
  byte-for-byte with codegen's cross-module monomorphization symbol, or the
  frame's callee and codegen's mono double-define / mismatch. The
  mangling-agreement surface is exactly design-68 territory and risky against
  bootstrap (blade is generic- and multi-module-heavy). Deferred with the same
  budget reasoning as shape 1. [74, 68]
- **Item 1 (spawn-Void ICE) — LANDED.** `spawn { void_body }` ICE'd building the
  `{i8*, i8*, void}` control block (a `void` struct field is illegal LLVM). The
  result slot becomes a 1-byte placeholder for a Void body (never stored/read in
  the trampoline); `UnsafePointer<Void>` now lowers to `i8*` (C `void*`) and
  `sizeof<Void>()` folds to 0, so the GENERIC `Task<Void>.join`/`deinit` stdlib
  paths (result cast/load/dealloc-size) monomorphize cleanly. Both explicit-join
  and drop-joins-it exercised. Test `spawn_void_body`. Suite 826, bootstrap 17+17,
  libs 4+4. [75]
- **Item 2 (generic-bound propagation) — LANDED.** A generic forwarding its own
  bounded type param to another generic's bound (`inner<T>(w)` inside
  `middle<T: Seed>`) errored "type `T` does not implement trait `Seed`". Fix:
  the general-trait bound check in `_check_generic_call` now routes an ABSTRACT
  type-param argument through `_bound_satisfied` (bounds-environment lookup —
  satisfied iff the enclosing signature declares the bound), matching the
  existing Send/Sync/Equatable handling. Codegen twin: a generic call inside a
  generic body substitutes its type args through the monomorphization context
  before instantiating (else it recursed over the abstract `T`). Negative case
  (forward without declaring the bound) still a clean anchored error. Tests
  `generic_bound_propagation`, `errors/generic_bound_propagation_unmet`. Note:
  un-dodging design-74 shape-3 tests to forward a type param into the coro
  promotion path is left to items 5/6 (that combines with the promotion surface,
  not the standalone bound check fixed here). Suite 828, bootstrap 17+17, libs
  4+4. [74]
- **Item 3 (DF-C2: closures satisfy `Copy`) — LANDED.** An escaping closure is
  ImplicitCopy (design 73) and now satisfies the umbrella `Copy` bound
  (`type_satisfies_copy_bound` accepts `TypeKind.FUNCTION`), so
  `Vector<() -> Int>` is ExplicitCopy and its `.copy()`/`.get()` work. Three
  wiring fixes to make it BALANCED (the naive enable exit-133'd): (a) codegen
  `.copy()` on a closure receiver emits the env retain (`_emit_closure_env_retain`)
  instead of a bitwise alias; (b) the ROOT cause of the leak/double-free — the
  `escaping` bit is not part of the mangling and was lost when a container's
  closure type arg was reconstructed from the mangled key, so `_needs_cleanup`
  and the Copy-bound predicate (both gate on `func_is_escaping`) treated the
  element as non-owning. `_ensure_monomorphized_struct` now re-marks a stored
  closure type arg escaping (`_mark_stored_closure_escaping`, recursing through
  Optional/array/tuple), which is safe (a function type reaching a container
  type-param slot is always a stored value, never a borrowed param). Exact-count
  Arc-capture probe: deinit runs exactly ONCE through copy+get. Tests
  `closure_vector_copy_get`, `closure_vector_deinit_once`,
  `closure_satisfies_copy_bound`. Suite 831, bootstrap 17+17, libs 4+4. [73, 54]
- **Item 3 follow-up (get use-after-free) — LANDED.** The item-3 commit had a
  latent flake: `Vector<() -> Int>.get` returned a closure element WITHOUT
  retaining its env, because `_transfer_needs_copy`'s copy-with-retain branch
  only covered ImplicitCopy STRUCT/ENUM/OPTIONAL — a closure (no conformance
  name, so `_get_cleanup_behavior` = "none") fell through to bitwise. The
  read-out copy's teardown released an env it never retained: a use-after-free
  that intermittently crashed (exit 133 under load; deterministic under
  libgmalloc). Fix: `_transfer_needs_copy` retains an escaping-closure element
  read out of a container slot (ArrayIndex/MemberAccess/TupleIndex), mirroring
  the design-65 aggregate copy-with-retain; a bare Identifier closure
  (move/borrow-lend) is untouched. Verified deterministic-clean under
  libgmalloc + MallocScribble (20x). Suite 831, bootstrap 17+17, libs 4+4. [73]
- **Item 4 (DF-C1: closures in coroutine frames) — LANDED.** A closure created in
  a driven body is now supported: (1) closure-typed frame field via a new
  `opt_closure` encoding (Optional-wrapped, drop-flag = None/Some, forced `sync`
  since a stored closure cannot be driven; frame re-registration no longer trips
  "redundant escaping" — `_clear_escaping` clears the bit on the field type so
  re-stamping is clean); (2) a CALL `f(args)` on a frame closure local rewrites to
  an indirect field call `self.f(args)` (typechecker force-unwraps the opt field
  on a `__Frame_*` struct; codegen extracts the inner closure); (3) captured frame
  locals are MATERIALIZED as real locals before the closure (`let x = self.x!.copy()`
  + a `move` capture) so the closure captures by value — crucially `move`, not a
  persistent function-local, because a resume state machine would re-drop an owning
  local on every re-entry. Codegen `MemberAccess`-to-optional wrap now uses
  `_is_optional_type` so a struct/closure inner wraps to Some. Tests
  `coro_closure_local_call`, `coro_closure_deinit_once` (exact deinit-once,
  gmalloc-clean), `coro_closure_taskgroup` (spawned frames own closures). All 3
  verified clean under libgmalloc. Suite 834, bootstrap 17+17, libs 4+4. [73, 74, 44, 52b]
  - **FIXED (design 80 run, rider): `__drive(f(move owning_arc))` no longer
    double-frees the moved param.** The `__drive_<f>`/`__spawn_<f>` wrapper now
    `move`s each non-reference param into the frame (`_frame_param_arg`), so the
    frame is the sole owner (dropped once at teardown) and the wrapper param's drop
    flag is cleared. Exact-count lock coro_moved_arc_param_deinit_once (3 refs, no
    UB); single-ref case verified clean under libgmalloc. Original note follows.
  - **FOUND (pre-existing, FLAGGED): `__drive(f(move owning_arc))` double-frees the
    moved param.** A driven function taking an owning ImplicitCopy value (Arc) as a
    param, moved in at the drive site, DOUBLE-DROPS it: the synthesized
    `__drive_<f>` wrapper builds the frame from the param `Identifier` WITHOUT
    retaining into the opt-encoded field (`_needs_copy_for_struct_init` sees the
    field type `Arc?` = Optional -> `_get_cleanup_behavior` = "none", so no retain),
    yet the param binding keeps its drop flag AND the frame drops its field. Benign
    under the normal/scribble allocator (the 2nd Arc deinit reads a freed-but-mapped
    strong word and no-ops), but a real read-after-free (deterministic SIGSEGV under
    libgmalloc). Repro: `func run(a: Arc<Res>){...__suspend()...}; __drive(run(move a))`
    — NO closure needed. Reproduces at HEAD (pre-item-77-4). An owning value created
    as a frame LOCAL (not a moved param) is clean. Fix belongs with the frame-init
    retain path (opt-encoded ImplicitCopy field construction must retain, or the
    driver must move-clear the param). Deferred from item 4 (orthogonal to closures;
    the deinit-once test uses a frame-local Arc to stay clean). [44, 52b]

## Design 76 — A4 IO reactor + A6 extern-blocking + A3 remainder (IN PROGRESS)
- **Commit 1 (A4 reactor + std.net + A3 io-cancel; ST + entry executor):** A
  process-global **kqueue (macOS) / epoll (Linux)** reactor (compiler seams in
  codegen/core.py, `_declare_io_runtime`): a single lazily-created, race-safe
  (atomic cmpxchg) reactor fd; `saw_reactor_register(fd, write)` arms ONE-SHOT
  read/write interest; `saw_reactor_poll(timeout_ms)` blocks in kevent/epoll_wait
  (< 0 = forever) and returns the ready count — the kernel owns the interest set,
  so register/poll are each ONE syscall (why kqueue/epoll beats poll(2) for a
  global reactor). OS-divergent socket bits stay in shims (`saw_set_nonblocking`,
  `saw_errno_would_block`, `saw_sin_set_family`); hosted-only (freestanding: extern
  decls, net never loaded). **`io_wait(fd, write)`** is a new suspend INTRINSIC
  (like `yield_now`): the coro transform lowers it to `saw_reactor_register` +
  suspend with a NEGATIVE (io-park) wake reason; codegen fallback (outside a frame)
  is register + blocking poll. The ST group executor (`__run_all_st`) + the entry
  executor gained an io phase: when nothing is runnable, poll the reactor with the
  earliest sleep deadline as the timeout (never busy-wait, never block while a
  frame is runnable), wake ALL io-parked tasks on return (coarse level-triggered
  retry — a still-not-ready task re-registers via oneshot), advance sleepers only
  when the poll TIMED OUT (events==0). **std/net.saw**: minimal nonblocking TCP as
  the channel-style idiom (NON-suspending `tcp_try_read`/`tcp_try_write`/
  `tcp_try_accept` + `io_wait` in the caller task body — a suspending std free fn
  CANNOT embed as a sub-frame since the transform is entry-module-only, same reason
  `Channel.receive()` is inline-lowered); `tcp_listen`/`tcp_local_port`/
  `tcp_connect_start`/`tcp_connect_check`/`tcp_socketpair`/`tcp_close`/
  `net_buffer`/`net_bytes_to_string`. Zero per-call heap in the socket paths: a
  typed `SockAddrIn` stack struct (design-58 natural layout) + `(&sa) as
  UnsafePointer` (design-42), htons/ntohs in Saw. A3: cancellation observed at the
  io suspension point via the cancel-check-before-`io_wait` idiom (mirrors the
  channel cancellation-aware receive). Tests (loopback/socketpair only,
  deterministic on counts/contents, time-bounded): `net_socketpair_echo`,
  `net_loopback_echo` (listen/accept/connect/read/write), `net_io_sleep_interleave`
  (never-block: sleeper honored while an fd is idle + io wake), `net_io_main_entry`
  (entry-executor reactor path), `net_io_cancel` (A3 + deinit oracle). Suite 823,
  bootstrap 17+17, libs 4+4.
  - **FOUND (pre-existing, flagged): a TUPLE local held across a suspend ICEs**
    ("cannot store {i64,i64} to {i1,{i64,i64}}*") — the coro frame opt-encodes the
    tuple slot but the store site doesn't wrap it; reproduces with plain
    `yield_now` (NO io). `let (a,b) = f()` DESTRUCTURING across a suspend also
    drops bindings. Orthogonal to design 76 (frame opt-encoding of non-POD-but-
    cleanup-free locals). Worked around in tests (keep only `Int` across the
    suspend; confine tuples to non-suspending helpers). Fix belongs with the coro
    frame-encoding work. [44, 76]
  - **DEFERRED (A4 remainder, re-ledgered): first-class inline-lowered
    `tcp_read`/`tcp_accept`/`tcp_write`/`tcp_connect`** (receive()-style, so the
    park loop is not hand-written in the task body). The transform being
    entry-module-only forces the channel-idiom shape today; the ergonomic lift is a
    `recv_by_id`-style recognition + `_emit_io_call` inline lowering. [62, 76]
  - **DEFERRED (A3 remainder): waking an ALREADY-io-parked task on cancel.** A task
    parked in `io_wait` on a permanently-idle fd, cancelled by a peer, won't observe
    `cancelled()` until the reactor poll returns (needs a self-pipe/eventfd wake).
    Same liveness class as the design's "join on a task that never observes
    cancellation blocks"; the landed model observes cancel at the check BEFORE
    parking. [18, 76]
    - **CLOSED** by design 102 item 2 (reactor self-wake pipe + `__is_cancelled()`
      precise wake + pre-poll cancelled scan + cancel propagation into sub-frames).
- **Commit 3 (A6 honest subset: `extern blocking` sync-reject + freestanding
  reject):** the A6 FRONT-END was already wired (parse `extern "C" { blocking func
  ... }`, `is_blocking` on the AST, blocking-extern as an effect suspension
  source). This commit closes the two type-system halves: (1) a blocking-extern
  call in a `sync` context is rejected by the effect checker, anchored, naming the
  extern + suspension path (locked by `errors/blocking_extern_sync_reject`); (2)
  declaring an `extern blocking func` in the FREESTANDING profile is a clean
  registration-time error (no hosted pool). Suite 825, bootstrap 17+17, libs 4+4.
  - **CLOSED by design 103** (thread-per-call offload + coro lowering; see the design
    103 entry). The worked-out design below is what landed (thread-per-call v1 in
    place of a pool; `__blk_start` codegen intrinsic + pre-frame-builder classify).
  - **DEFERRED (A6 runtime offload — re-ledgered with the worked-out design):** the
    hosted pool + coro lowering that makes a blocking call actually RUN in a task.
    Today a blocking call inside a driven/spawned body is REJECTED (the synthesized
    `resume` is `sync`, so the blocking suspension source trips the sync check — an
    honest rejection, not a miscompile, though the message points at
    `__Frame_*.resume`). Design (reuses ALL the A4 infra): C shims
    `saw_offload_start(fnptr, arg) -> job` / `saw_offload_done(job)` /
    `saw_offload_pipe_fd(job)` / `saw_offload_take(job)` — start spawns a
    thread-per-call that runs the extern, stores the result, and writes a byte to
    the job's pipe; the call site desugars (BEFORE typecheck, so the frame builder
    sees the new locals) to `let j = __blk_start(slow(arg)); while __blk_done(j)==0
    { io_wait(__blk_fd(j), 0) }; let r = __blk_take(j)`. The two frictions that make
    it non-trivial: (a) function-address is NOT expressible in Saw (`slow as Int`
    errors), so `__blk_start` must be a CODEGEN intrinsic that resolves the extern's
    ir.Function and bitcasts it to i64; (b) the desugar must run pre-typecheck (or
    register `__job` with the frame builder) so the offload locals are
    frame-resident. v1 restriction: blocking externs typed `(Int) -> Int` (the
    offload thunk is `i64(*)(i64)`); multi-arg is future. [18, 22, 76]
- **Commit 2 (MT reactor integration + std.net named constants):** the design-75
  multi-threaded worker (`__tg_worker`) gained the io phase. CHOICE (reported):
  **poll on an idle worker with a BOUNDED timeout** (earliest sleep deadline, else
  a 50 ms cap) — bounded because with EV_ONESHOT + concurrent pollers only one
  worker receives each event, so a worker that missed it must retry rather than
  block forever (no lost-wakeup hang). The scan tracks io-parked (`remaining < 0`)
  separately from sleepers; when nothing is runnable and no peer is resuming, an
  idle worker polls the reactor OUTSIDE the lock, then (idempotently) wakes ALL
  io-parked tasks and advances sleepers only if the poll timed out. Redundant
  concurrent polls are harmless (wake-all is idempotent); a dedicated single poller
  thread is a future refinement. NOTE: the Send-on-frames gate poisons
  `UnsafePointer`, so an MT-spawned frame cannot hold a read buffer across a
  suspension — MT io parks on write-readiness (Int-only frame). std.net magic
  numbers are now named module statics (`AF_INET`/`SOCK_STREAM`/`WOULD_BLOCK`/
  `LOOPBACK_BE`/...); std-module statics are NOT visible cross-module (a known
  export gap), so the `io_wait` direction stays a literal 0/1 in user code. Test:
  `net_threads_io` (`TaskGroup(threads: 2)`, two io-parked frames woken; stable
  25x). Suite 824, bootstrap 17+17, libs 4+4.

## Design 75 — A2: multi-threaded work-stealing executor + Send-on-frames (LANDED)
- **Commit 1 (surface + Send-on-frames gate; execution still single-threaded):**
  `TaskGroup(threads: N)` labeled init landed (a second `init(threads: Int)`; the
  default `TaskGroup()` and `threads: 1` stay the byte-identical single-threaded
  engine — `workers` field clamps to >=1). The Send-on-frames gate: a `let/var
  group = TaskGroup(threads: ...)` binding is flagged `is_mt_group` in the
  typechecker (`_check_let_statement` via `_is_multithreaded_taskgroup_init`,
  handles the `StructInit [resolved: init(threads)]` form); `group.spawn(f(...))`
  into such a binding records `f` in `typechecker._mt_spawn_roots`; the coroutine
  transform (`_check_spawn_frame_send`) then walks the spawn root frame's params +
  across-suspend locals + embedded callee sub-frames and rejects the FIRST non-Send
  value, naming it + its type, anchored at the function (design 74 A8). Reuses the
  same structural `namespace.is_send` as the 21b `spawn { }` capture audit
  (`UnsafePointer`/bare `Vector` poison; Int/Bool/Float/String/Arc/Mutex/Channel
  pass). Single-threaded groups skip the gate entirely. DEVIATION (documented):
  mt-ness is tracked on the group's local binding, so a `TaskGroup(threads:)`
  spawned into DIRECTLY is gated; passing the group through an opaque helper before
  spawning is not yet traced (spawn directly for the gate — future interprocedural
  lift). Tests: `taskgroup_threads_send_accept` (Int/String/Channel accepted, sum
  oracle), `errors/taskgroup_threads_nonsend_reject` (Vector param named). Suite
  813, bootstrap 17+17, libs 4+4.
- **Commit 2 (the multi-threaded fork-join executor):** `TaskGroup(threads: N)`
  with N>=2 now really runs on N OS threads. CHOICE (reported): the sanctioned
  simpler shape — ONE mutex-protected SHARED run queue (injector) drained by N
  workers, NOT per-worker lock-free deques (simplicity/soundness over throughput
  v1). Model = FORK-JOIN: a drain is triggered lazily by `join()`/Deinit (via
  `__run_all` -> `__drain_mt` when workers>=2 && lock present), spawns N `Task<Int>`
  workers through the 21b engine (each running the free fn `__tg_worker(addr: Int)`;
  the group's own address crosses the `spawn` boundary as a Send `Int`), then joins
  them all — pthread_join is a full barrier making every `__result` visible before
  `join()` force-unwraps. Each worker LOCKS, claims the first runnable (not-done,
  not-active, remaining==0) frame by setting an `active[i]` flag, UNLOCKS, calls
  `resume()` outside the lock, then re-locks to record Pending(remaining=wake) /
  Done. D6 confinement holds: `active[i]` guarantees one worker per frame; `tasks`
  is read-only during a drain (enqueue is main-thread-only, main is blocked joining
  workers, so the queue never resizes) — only done/remaining/active are mutated,
  always under the lock; frames live at stable heap addresses inside their boxes.
  Sleep: when no frame is runnable and none active, ONE worker advances the clock by
  the earliest deadline UNDER the lock and subtracts it from all sleepers (shared
  timer, no per-worker wheel); when a peer is mid-resume, free workers spin+nap 1ms
  (no cond var -> no lost-wakeup class). Cancellation across tasks:
  `TaskHandle.cancel_addr() -> Int` hands the `__cancel` word's address (Send) to a
  canceller task, which sets it; the victim observes via `cancelled()` (set-once
  monotonic byte -> race-free, eventually consistent). The default `TaskGroup()` and
  `threads: 1` still route to `__run_all_st` (the byte-identical pre-75 loop, no
  threads/lock). Send gate extended to the spawn root's RETURN type (it crosses
  worker->main via join). Battery (all deterministic on counts/sums, time-bounded,
  each verified stable 30-50x): `taskgroup_threads_parallel_sum` (100 tasks/4
  workers, sum 4950 — stress), `_producer_consumer` (channel receive across
  workers), `_sleep` (cross-worker earliest-deadline), `_cancel` (cancel from
  another task), `_deinit_once` (result dropped exactly once under stealing, static
  atomic count = 6). Suite 818, bootstrap 17+17, libs 4+4, -O0 spot-checked.
- **FOUND (pre-existing, flagged): `spawn { void_body }` ICEs.** A 21b `spawn { }`
  whose closure returns `Void` builds a task control block `{i8*, i8*, void}` — an
  invalid LLVM struct ("void type only allowed for function results"). Worked
  around in the executor (worker bodies return `Int`); a proper fix is to omit the
  result slot for a Void spawn body. [21b, 75]
  - **CLOSED** — 21b `spawn { void }` fixed by design 77 item 1; the cooperative
    `group.spawn(void)` + the executor return-Int workaround closed by design 102 item 1.

## Design 74 — A5-rest: finish effect-polymorphism shapes + A8 anchors (IN PROGRESS)
- **Commit 1 (A8 — diagnostic anchoring):** A coroutine-transform rejection
  (`CoroTransformError`) now anchors at the user's `file:line:col` with a source
  snippet through the shared `ErrorReporter`, exactly like a type error — it was
  a bare message pointing nowhere. `CoroTransformError` carries `source_file`;
  `_FrameBuilder` stashes `self.src_file` from its function; sawc.py surfaces the
  rejection via `reporter.error(...)` (falling back to the entry file for a
  single-file program). Locked by `examples/errors/coro_reject_anchored.saw`
  (asserts the `file:line:col` anchor on a buried-suspend rejection). Suite 808,
  bootstrap 17+17, libs 4+4. [74, 69]
- **Commit 2 (shape 2 — driven method on a GENERIC struct):** `__drive(b.run())`
  for `b: Holder<Int>` now works. The typechecker monomorphizes the method over
  the STRUCT's type params (T->Int): pristine generic-struct-extension methods are
  snapshotted (`_pristine_generic_struct_methods`), the drive site queues a
  clone+substitute+re-check (deferred to `_process_effect_monos` so it never
  clobbers the mid-body scope), and records the concrete driven method carrying
  the concrete receiver SawType (`Holder<Int>`). The coro transform reads that
  table, builds the frame with `__recv: UnsafePointer<Holder<Int>>` (new
  `recv_saw_type` param on `_FrameBuilder`), and `_rewrite_drive_sites` casts to
  the type-arg-preserving pointer. Two instantiations coexist (Int + Bool). A
  general fix fell out: member access on a concrete instantiation of a generic
  struct whose `struct_info` is the generic symbol now substitutes the field type
  by the receiver's type args (`self.value: T` -> `Int`) — normal instantiations
  keep their monomorphized symbol and skip it. Combined struct-generic AND
  method-generic driven methods stay a clean, anchored rejection (still A5-rest).
  Tests: `coro_generic_struct_method` (both instantiations),
  `errors/coro_generic_struct_and_method_generic_unsupported`. Suite 809,
  bootstrap 17+17, libs 4+4. [74, 70]
- **Commit 3 (shape 3 — nested suspending generic calls):** A driven body can now
  make NESTED suspending generic calls (`let a = leaf<Slow>(...)`). A new
  transform pre-pass `_promote_nested_generic_calls` runs after the effect fixpoint
  (so per-instantiation `.suspends` is known): it walks each driven body (and,
  transitively, spliced instantiation bodies) for a drivable-position generic call
  whose instantiation suspends, splices the concrete instantiation via a new
  typechecker helper `_splice_fn_mono` (clone+substitute+register+re-check under
  the stashed entry-module namespace `_entry_module_ns`, so locals get resolved
  types), rewrites the call site to the mangled symbol, and seeds it into the
  driven closure. The existing Part-0b sub-frame embedding then handles it. The
  closure walk now SKIPS a template reached via an effect edge (its suspending
  instantiations were promoted + seeded); an un-promotable nested generic call
  (cross-module = shape 4) keeps its generic call and is rejected — with a
  workaround + user-anchored line — by `_classify_call`. Multiple instantiations of
  one generic coexist; non-suspending nested generic calls are left for codegen.
  Tests: `coro_nested_generic_call` (two instantiations + a non-suspending generic
  left alone), `coro_nested_generic_deep` (two-deep nesting). Suite 810,
  bootstrap 17+17, libs 4+4. [74, 44]
- **DISCOVERED (pre-existing, NOT shape 3): generic-bound propagation gap.** A
  generic fn forwarding its own type param to another generic (`func middle<T:
  Seed>(w: T) { inner<T>(w) }`) errors "type `T` does not implement trait `Seed`"
  even though the bound is declared — reproduces with NO driving (orthogonal to
  coroutines; a typechecker generics issue). Nested shape-3 tests use concrete type
  args at each level to avoid it. Fix is disproportionate to design 74 — flagged
  for a generics brief. [74]
- **Commit 4 (shape 1 rejection + A8 for methods + docs):** A BURIED suspending
  METHOD call in a driven body (`let r = c.step()`, `Counter.step` suspends) is now
  a CLEAN, user-anchored rejection at the exact call site naming the workaround
  (`__drive(recv.step())` directly, or wrap in a nested free fn) — it previously
  lowered in place and tripped a confusing sync-violation on the synthesized
  `__Frame_*.resume`. The transform builds a (struct, method) suspend set from the
  effect nodes and `_collect_calls` detects the buried call. Docs: spec concurrency
  limits + saw-lang skill limits updated for shapes 2/3 landed and shapes 1/4 (+
  combined struct-and-method-generic) remaining. Test:
  `errors/coro_buried_suspending_method` (asserts message + `file:line:col`). [74]

## Design 74 — RE-LEDGERED remainder (attempted, deferred with analysis)
- **Shape 1 FEATURE (method sub-frame embedding) — DEFERRED.** The rejection is now
  clean + anchored (commit 4). The FEATURE (embed a nested suspending method call
  as a sub-frame, the Part-0b method twin) needs: (a) making the phase-1 frame-prep
  a FIXPOINT that discovers method callees while preparing (today `closure` is a
  fixed set of free-function names; method sub-frames aren't in `fbs`), (b)
  receiver addressing — `__recv = (&var self.recv) as UnsafePointer<Struct>` into
  the CALLER frame's field for the receiver (only a simple frame-local-identifier
  receiver is addressable; `foo().m()` / `self.f.m()` need spilling), (c) building
  the method frame + threading it into `fbs` so `_build_sub_frame`/`_emit_nested_
  call` (which already accept a `recv_value`, see `_build_frame_init`) drive it.
  `_build_frame_init` already supports a method `__recv`; the missing piece is the
  discovery/prep fixpoint + receiver addressing. Bounded but touches the central
  transform flow — deferred to keep the 810-test bar safe; workaround is exact and
  the rejection names it. [74, 44, 45]
- **Shape 4 (cross-module generic driven templates) — DEFERRED.** `_pristine_
  generics` / `_pristine_generic_methods` capture ENTRY-module templates only, so
  `_build_fn_mono` / `_splice_fn_mono` return False for an imported template and the
  nested/driven generic call is rejected (anchored) by `_classify_call`. Lifting
  needs: (a) snapshot imported-module generic templates into the pristine maps
  (keyed to avoid cross-module name clashes), (b) design-68 canonicalization — the
  mangled instantiation key computed in the transform must agree byte-for-byte with
  codegen's cross-module monomorphization symbol, or the frame's callee and
  codegen's mono double-define / mismatch. Deferred: the mangling-agreement surface
  is exactly design-68 territory and risky against bootstrap (blade is generic- and
  multi-module-heavy). Rejection stands with a workaround. [74, 68]
- **Rider DF-C1 (closures inside driven/suspending frames) — DEFERRED (attempted).**
  Confirmed both shapes still error on this tree (as design 73 flagged): a closure
  local CALLED in a driven body errors "undefined function `f`" (the resume method
  doesn't rewrite `f(n)` on a frame-local closure to an indirect `self.f(n)` call),
  and a closure HELD across a suspend errors "redundant `escaping`" (the frame
  struct field for a closure trips the typechecker's "closure types outside
  parameter position are always escaping" check). The fix is a genuine multi-part
  feature: (1) type the closure frame field without tripping the escaping check,
  (2) rewrite a frame-local-closure CALL to an indirect closure call on `self.f`,
  (3) closure env retain/release exactly-once across the suspend + at frame drop.
  This is closure-in-frame representation surgery in both the typechecker and the
  transform — disproportionate to bundle safely here; re-ledgered per the rider's
  own escape clause. Blocks a TaskGroup frame that OWNS a closure. [73, 74, 44, 52b]
- **Rider DF-C2 (`Vector<closure>` satisfies the generic `Copy` bound) — DEFERRED.**
  Unchanged from design 73: the container element-copy path must route through the
  closure-env retain (a naive enable crashed exit 133). Independent of the coroutine
  transform work in this brief; belongs with the container-Copy-glue work. [73, 54]

## Design 72 — Small fixes: L12/M1, L9, erased-error downcasting (LANDED)
- **Commit 1 (L12/M1 — fixed-array builtins):** Fixed arrays `[T; N]` gained two
  builtin members and only these two: `.len()` (folds to the compile-time
  constant N as `Int`) and `.swap(i, j)` (the M1 escape hatch — bounds-checked
  in-place element swap, mirroring `Vector.swap`; requires a `var` receiver). The
  typechecker intercepts array-typed method calls (`_check_array_method`) before
  the old "non-struct type" error: `len`/`swap` typed + tagged, anything else a
  clean "fixed array has no method X; only .len()/.swap are available, user
  extensions on array types are not supported" error. Constant `swap` index OOB is
  a compile error (mirrors `a[const]`); dynamic index gets the always-on runtime
  bounds check. Parser: `extension [Int; N]` now emits "extension methods on array
  types are not supported" instead of the generic "Expected type name". Codegen
  `_generate_array_builtin`: `len` -> const; `swap` addresses the array in place
  via `_get_lvalue_pointer` + GEP, loads/stores the two slots (no element copy).
  Spec fixed-array section updated; `.len()` de-illustrativized. Tests:
  `array_len_builtin`, `array_swap_builtin`, `array_swap_immutable_error`,
  `array_no_extension_error`, `array_unknown_method_error`,
  `array_swap_const_oob_error`, `array_swap_dynamic_oob_panic`. Suite 796,
  bootstrap 17+17, libs 4+4. [72]
- **Commit 2 (L9 — Equatable over Optional/array members):** The synthesis
  widening was ALREADY landed (commit e60d189: `is_equatable` holds for `T?` iff
  `T` is and `[T; N]` iff its element is; codegen `_emit_optional_equals` /
  `_emit_array_equals` wired into the recursive `_emit_equals`, so struct-field,
  tuple, and direct comparisons all reach them; tests
  equatable_optional_field/_direct/_string_synth/_array_field). Design 72 closes
  the remaining brief case — an enum whose payload is an Optional — with
  `equatable_enum_optional_payload` (`Filled(value: Int?)`: Some==Some,
  Some!=Some-diff, None==None, None vs Some). Suite 797. [72]
- **Commit 3 (erased-error downcasting via type-ids):** Every vtable gains a
  `type_id` HEADER slot (layout now `[dtor, size, align, type_id, methods…]`;
  dispatch base 3->4). Type-id scheme: a monotonic counter memoized by MANGLED
  NAME (`_type_id_for`), so the id the vtable bakes in matches the id `is`/`take`
  compute for the same concrete type in this module (simplest stable scheme; no
  reflection surface). Builtins on `Box<any Trait>` (explicit type arg, no
  inference): `b.is<T>() -> Bool` (loads/compares the vtable type-id; a borrow)
  and `b.take<T>() -> T?` — CONSUMES the box: on an id hit it moves the payload
  out and frees the shell WITHOUT the dtor, `Some(T)`; on a miss it runs the full
  box drop, `None`. take-on-miss CHOICE: consumes UNCONDITIONALLY (leave-intact
  fights the move checkpoint), so `is<T>()` first is the branch-without-consume
  path — the typechecker marks the receiver moved, codegen clears its drop flag.
  Deinit is exactly-once on both paths (hit: at the moved-out value's scope; miss:
  in take). T must be a concrete conforming type (clean error otherwise). Codegen
  drop refactored into `_erased_run_dtor` + `_erased_dealloc_shell`. Catch-side
  match-on-concrete sugar OUT (future). Tests: erased_downcast_is_take,
  _deinit_once (hit+miss balance), _error_retry (Box<any Error> from an erased
  Result — the motivated case), _generic (downcast in a monomorphized body),
  _nonconforming_error, _use_after_take_error. Spec existentials + error sections
  + saw-lang skill updated. Suite 803, bootstrap 17+17, libs 4+4. [72, 51, 56]

## Design 73 — Closures become ImplicitCopy (refcounted env) (LANDED)
- **Commit 1 (core + tests):** An escaping closure's heap env now leads with an
  atomic refcount word (platform-width, String-style monotonic retain / release
  ordering + acquire fence at zero). Closures joined the **ImplicitCopy** family:
  `_is_no_copy_type(FUNCTION)` -> False, `_is_implicit_copy_type`/`_check_*_containment`
  treat an escaping closure like `String`. `let g = f` is legal again (retired
  71's NoCopy binding rejection + `closure_copy_requires_move_error`). Retain
  (`_generate_copy`/`_emit_retain_at` FUNCTION) bumps the env refcount; drop
  (`_emit_closure_drop_at`, now via `_emit_closure_env_release`) decrements and
  runs the dtor (captures release + free) only at zero; the spawn trampoline uses
  the SAME release (frame owns +1, exactly-once across the thread boundary). Null
  env (capture-less) => no refcount word, trivially copyable (retain/drop null-
  guarded). **RESIDUAL GAP CLOSED:** an owning closure in a copyable struct copied
  N times -> dtor once at the last owner (positive test). Also fixed a pre-existing
  leak the model surfaced: an escaping closure LENT into a non-escaping param must
  not clear the caller's drop flag (`closure_lend` marker). Tests:
  `closure_copy_binding`, `closure_copyable_struct_copied`, `closure_spawn_arc_balance`,
  `closure_captureless_copyable`, `closure_borrow_lend_balance`; 71's battery
  updated to refcounted expectations (all exactly-once). Suite 807, bootstrap
  17+17, libs 4+4. [73, 71]
- **Commit 2 (docs):** spec closures section rewritten (ImplicitCopy, refcounted
  env, exactly-once teardown, lend, null-env fast path); saw-lang skill Copy-tier
  table + gotcha updated. [73]
- **Findings (flagged, NOT fixed — out of design-73 scope):**
  - **DF-C1 (pre-existing coro-transform gap).** A closure LOCAL called inside a
    driven/suspending function (`let f = {...}; ... f()`) errors "undefined
    function f"; a closure held across a suspend in a frame errors "redundant
    `escaping`". Both fail identically on baseline (confirmed via stash) — a
    coroutine-transform frame-building limitation, unrelated to refcounting. Blocks
    expressing a TaskGroup frame that OWNS a closure; the thread-`spawn` balance
    test covers the cross-boundary exactly-once claim instead. [44, 45, 52b, 73]
  - **DF-C2 (deferred).** Closures deliberately do NOT satisfy the umbrella `Copy`
    bound yet: `Vector<() -> Int>.copy()`/`.get()`, Set/Map with closure elements
    need the container element-copy path routed through the refcount retain (a
    naive enable crashed exit 133). Clean compile error until wired. [54, 73]

## Design 71 — Closure Deinit (LANDED)
- **Commit 1 (core):** Closures now carry their own env destructor
  (`{fn_ptr, env_ptr, dtor_ptr}`, design 71). An escaping closure binding is an
  OWNING value: `_needs_cleanup(FUNCTION-escaping)` + `_emit_closure_drop_at`
  (null-dtor no-op) run the env destructor at the closure's own drop (LIFO +
  drop flags), releasing owned captures exactly once and freeing the heap env.
  Removed the creating-frame EARLY RELEASE: a `move` capture now clears the
  source binding's drop flag (this ALSO fixed a latent thread-`spawn`
  double-free of a move-captured NoCopy — deinit ran at frame exit AND in the
  trampoline). Copy class: escaping closures are NoCopy (move-only) — a bitwise
  copy aliased the heap env (double free, exit 133); forwarding an escaping
  closure into a NON-escaping/borrowing slot stays a lend (no move). Closure
  FIELDS excluded from NoCopy CONTAINMENT so capture-less-closure structs stay
  copyable. Exact-count battery: `closure_deinit_{drop_order,arc_balance,
  struct_field,vector,returned,dropped_uncalled,called_then_dropped,
  conditional_move}` + `closure_copy_requires_move_error`. Suite 789, bootstrap
  17+17, libs 4+4 green. RESIDUAL GAP (was: an owning closure in a COPYABLE
  struct that is then copied double-freed) — **CLOSED by design 73**: closures
  became ImplicitCopy (refcounted env), so the struct copy retains the env and the
  dtor runs once at the last owner. The NoCopy binding rejection above was retired
  in the same move. [71, 73]

## Decisions needed (user input required)
- **D10.** Cortex-M0-class atomics (ARMv6-M has no CAS) — decide with
  the first such port. [19, 20]
- **SOS**: design session Aug 3 ratified spec §7–§10 — scheduling
  (8 levels, band enum + immutable manifest-declared launcher-approved
  map, LAUNCH capability, no inheritance, direct-switch, UP v1),
  thread/process lifecycle (fault→process-exit, no join/thread-kill,
  Thread+Process handles waitable, get_status/kill rights-gated),
  interrupt delivery (mask-on-fire/ack-to-rearm, ack-is-release,
  one-task-per-IRQ v1, `wait(ack:)` combined form), and the userspace
  runtime model (TaskGroup unchanged; NEW `HandlerGroup` = handles on
  a task pool, move-in/coat-check API, per-attachment non-reentrancy,
  borrow-per-invocation, wake-word key bridge). REMAINING before the
  kernel briefs (spec §11): ONE user design session — root server
  responsibilities + v1 userspace protocol; then the veto-able
  orchestrator pins (rights bits/op tables, memory layout, refcount
  placement, sosimg constants incl. priority-map field) land inside
  the M1/M1b briefs (numbers assigned at dispatch; the spec's old
  78/79 references are stale).

- **DF4 (meta).** Blade bit-rots as the compiler tightens — re-validate
  periodically (the bootstrap target is the canary). [49]
- **DF5.** Keywords (`extension` etc.) can't be identifiers — fine, but
  an eventual contextual-keyword sweep is noted. [49]
- ~~**DF6 (latent coro-transform bug, found in the post-92 net idiom
  skim, Aug 2).**~~ CLOSED (design 96). Root cause was NOT the
  infinite-loop shape but a `break`/`continue` inside a NON-spanning
  `if`/`match` nested in a suspension-spanning loop: `_lower_inplace`
  kept the raw jump, which breaks the resume method's `while true`
  DISPATCH loop instead of the logical loop → re-entry hangs. net
  read()'s break form triggered it via its `else if …else {break}`
  (a non-spanning inner if in the else of the spanning io_wait if).
  Fix: `_has_loop_ctrl` forces a CFG split of such an if/match when in
  a spanning loop, routing the jump to the loop state via `loop_ctx`.
  read() converted to the break form, NOTE removed; regression
  `coro_break_reentered_in_loop`.
- **B4 limit.** A git dep's locked REV isn't pinned without
  re-resolution (build-from-lock path reconstruction is future work);
  path deps unaffected. [64, 67]
- ~~**L18 — module-qualified type annotations (found in design 68).**~~
  FIXED (design 69). The typechecker resolved a dotted annotation
  (`v: mod.Type` / `let x: mod.Type` / `-> mod.Type`) for checking but
  left the dotted `struct_name` on the AST, so codegen ICE'd "Undefined
  struct: mod.Type". Fix at the source: write the resolved (qualifier-
  stripped) type back onto the AST — free-function params (registration),
  let annotations + method params/return (a guarded `_resolve_type` when
  `_annotation_has_module_qualifier` holds, so generic/Self are untouched).
  A related typechecker gap fell out (a method with a qualified param
  errored "body has no value" because the param scope kept the dotted
  type) — fixed by the same write-back. Locked by
  `examples/l18_module_qualified_annotation.saw`. [68, 69]
- **L2.** Return-type reconciliation for type-param/associated-type
  returns in generic bodies — documented deferred looseness. [02, 24]
- ~~**L9.** `==` over Optional-/array-bearing members: deliberate clean
  error; extend the equals derivation when needed.~~ CLOSED (landed e60d189;
  enum-Optional-payload case closed under design 72): the Equatable synthesis
  lowers `T?` (None/Some-aware) and `[T; N]` (element-wise) members. [32, 72]
- ~~**L12.** Fixed arrays can't take extension methods (parse error);
  also blocks fixed-array `.len()` (spec-illustrative).~~ CLOSED (design 72):
  fixed arrays get builtin `.len()` + `.swap(i, j)` (M1 escape hatch); user
  extensions on array types stay rejected with a clear diagnostic. [40, 72]

## Deferred features (decided or triaged, not scheduled)
- ~~Erased-error DOWNCASTING (needs a type-id design; catch-all boxes are
  opaque until then).~~ CLOSED (design 72): vtable `type_id` slot + `Box<any
  Trait>.is<T>()`/`take<T>()`. Catch-side match-on-concrete sugar still deferred
  (future). [56, 72]
- Debug trait (synthesized structural formatting) — own design. [56]
- Enum-direct Printable (enum method dispatch is a general gap). [56]
- Named tuple PATTERN form `(x: a, y: b)`. [63]
- Map `entries()` snapshot; Map ExplicitCopy/.copy(). [54, 57]
- Labeled-arg `_` opt-out; labeled-only enforcement. [66]
- Integer range-cover exhaustiveness. [63]
- Generic-method type-arg inference. [36]
- ~~Closure-Deinit: wire `codegen_env_dtor` into closure drop glue (C4).~~
  **CLOSED (design 71 landed):** escaping closures carry their env destructor
  and drop it at the closure's own drop (exactly once); early frame release
  removed; escaping closures are NoCopy. Residual owning-closure-in-copyable-
  struct-then-copied gap tracked under the design-71 section. [21b, 59, 71]
- `Weak<T>` (Arc slot reserved). [16, 21]
- Slices (needs own design vs no-escape refs); `\x` byte escapes;
  where clauses; extension sugar (computed properties, conditional
  extensions); submodule directories; std.io traits (Blade-driven).
  [user triage Jul 29]
- S5 small-string optimization — ABI-gated ("before separate
  compilation or never"). [07]
- Registry for Blade (salvaged sketch, old pm design): static HTTP
  index or git repo; `GET /api/v1/crates/{name}` metadata +
  `/{version}/download` tarball; `blade login/publish`. [pm_design,
  deleted Jul 30 — see git history]

## Async (post-52b roadmap)
- ~~**A5.** Effect polymorphism via monomorphization-time re-inference —
  BLOCKS generic suspending/driven functions.~~ DONE (design 70): effect
  inference runs PER instantiation (keyed by mangled symbol); the coroutine
  transform accepts suspending instantiations of generic functions/methods by
  monomorphizing them to concrete functions/methods before frame synthesis
  (driven free fn, `TaskGroup.spawn`, and `&var self` method all land). A `sync`
  context calling an instantiation that suspends is a violation reported AT the
  call, naming the instantiation + suspension path (minimal A8). Still rejected
  with precise diagnostics: a buried suspending method-on-`T` call inside a
  driven body, nested suspending generic calls, generic-struct-extension driven
  methods, and cross-module generic templates (re-ledgered below). [18, 22]
  - **A5-rest.** PARTLY DONE (design 74): driven methods on GENERIC structs
    (shape 2) and nested suspending generic calls (shape 3) LANDED; A8 diagnostic
    anchors LANDED (coroutine-transform rejections anchor at the user's
    file:line:col). Remaining, now CLEAN user-anchored rejections (re-ledgered
    under the design-74 section with analysis): buried suspending METHOD-call
    embedding (shape 1, the Part-0b method twin); cross-module generic driven
    templates (shape 4, design 68 territory). [70, 74]
- ~~**A2.** Multi-threaded work-stealing executor + Send-on-frames check.~~ DONE
  (design 75): `TaskGroup(threads: N)` runs N OS workers over a single
  mutex-protected shared queue (fork-join drain; per-worker lock-free deques
  deferred as documented — the sanctioned simpler shape). Send-on-frames gate on
  spawn into a multi-threaded group (params + across-suspend locals + result). D6
  confinement preserved (one worker per frame; frames move only between
  suspensions). Cross-task cancel via `TaskHandle.cancel_addr()`. [18, 52b, 75]
- **A3.** Explicit-only cancellation points (`Task.cancelled()`, select).
  MOSTLY DONE (design 76): cancellation observed at the io suspension point via the
  cancel-check-before-`io_wait` idiom (+ the existing channel/yield checks).
  Remainder: waking an ALREADY-io-parked task on cancel (self-pipe) — re-ledgered
  under design 76.
- ~~**A4.** IO reactor (poller-only v1, kqueue/epoll, never-block).~~ MOSTLY DONE
  (design 76): global kqueue/epoll reactor + `io_wait` intrinsic + std.net
  nonblocking TCP; ST group + entry executor never-block poll. Remainders
  re-ledgered under design 76 (MT integration, first-class inline-lowered
  read/accept/write). [18, 76]
- ~~**A6.** `extern blocking` offload pool.~~ DONE (design 76 front-end + the two
  type-system rejections; design 103 the runtime offload + coro lowering — a
  blocking call inside a suspending body now RUNS on a worker thread and parks on
  its pipe; see the design 103 entry). **A7.**
  Separate-compilation interface format w/ suspends bit. ~~**A8.** Suspension-path
  diagnostic anchors.~~ DONE (design 74): coroutine-transform rejections + sync
  violations anchor at the user's file:line:col with a source snippet, naming the
  instantiation + suspension path. ~~**A9.** Actor sugar.~~ DROPPED from the
  roadmap (user, Jul 31). [18, 74, 76]
- Two runtimes coexist (thread-engine spawn/Task vs cooperative
  TaskGroup) — unification unscheduled. [21b, 52b]

## App-2 / freestanding path
- ~~**F7** remainder: assembly boot shim + wiring. **F8** linker scripts.
  **F9** QEMU riscv32 smoke ("blink") + CI.~~ DONE (design 112, Aug 4):
  `sos/kernel/` boot.S + virt.ld + rt.c runtime seams + `main.saw` (UART
  driver over `UnsafeMemory<_, Device>`); boots under `qemu-system-riscv32
  -M virt -bios none`, prints a banner, exits 0 via `sifive_test`; trap
  stub + freestanding panic seam both FAIL the run (never hang);
  `make sos-test` (tools/sos_runner.py) + ubuntu CI job. **F10** fence/
  barrier primitives for DMA ordering. [20, 46, 58, 112]
- ISR conventions; riscv32 target completion (i32 word landed, 47).
- **DF-112a (design-112 discovery, FIXED in this brief — sawc touch, flag
  for the lead vs concurrent design 113):** two freestanding-riscv32
  blockers surfaced on first bare-metal use. (1) An ICE — `_generate_spawn`
  (codegen/calls.py) hardcoded `i64` for the `saw_alloc` seam args instead
  of `self.int_type`, so ANY freestanding riscv32 compile ICE'd ("i32 !=
  i64") because codegen emits every loaded stdlib method incl. a spawn-using
  one (last un-migrated design-47 site; closures were already migrated).
  Fixed to platform-width. (2) Dead-code strip — codegen emits every loaded
  stdlib method + its closure/vtable descriptors + backend constant pools
  regardless of reachability, and freestanding still loads channel/mutex/
  task/float-print methods referencing pthread/snprintf/float/atomic
  symbols a bare-metal target can't satisfy. Added a freestanding-only
  post-pass (`_apply_freestanding_sections`) that internalizes non-`@export`
  defs (so O1 `globaldce` deletes everything unreachable from `kmain` +
  `@llvm.used` — the primary mechanism, reaches fused constant pools that
  IR-level sections cannot) + per-symbol sections for `--gc-sections`.
  Host suite 993/993 green (freestanding-guarded, hosted byte-identical).
- **DF-112b (pin deviation, design 112):** the pinned ISA was
  `rv32imac_zicsr`, but llvmlite emits `rv32i` (base, ilp32 soft-float)
  for the `riscv32-unknown-none-elf` triple — sawc exposes no CLI feature
  string to request imac. rv32i runs fine on QEMU's default `virt` rv32
  CPU (a subset); boot.S/rt.c are assembled `rv32imac_zicsr` and link
  cleanly. If a kernel needs mul/div/atomics inline (not libcalls), sawc
  needs a `--target-features` surface — future work, not M0-blocking.
- **DF-118a (design-118 stage-3 discovery, FIXED in that brief — sawc touch):**
  the IO reactor seams (`__saw_rt_reactor_create/register/poll/wake/destroy`) were
  declared with a hardcoded `i64` in `codegen/core.py::_declare_io_runtime`, but
  they carry `Int` (platform word). Latent since design 117 — freestanding never
  referenced a reactor seam (the compiler-synthesized `__saw_reactor()` getter was
  `internal` + unreachable → stripped before the width mattered). Design 118 stage 3
  moved the reactor singleton into the prelude std (`__saw_host_reactor()` /
  `SystemReactor` in taskgroup.saw), so the seams are now CALLED from Saw and their
  IR is generated on the freestanding riscv32 target too — where `Int` is i32,
  producing an invalid `cmpxchg i32 … i64` against the `Atomic<Int>` cell (IR
  parse error). Fixed to `self.int_type` (platform word) — byte-identical on the
  64-bit hosted targets, correct i32 on riscv32 (same class as DF-112a). The
  sos_runner (freestanding riscv32 QEMU) is the regression test.
- **F5.** `Once`/`Lazy<T>`, `PerCpu<T>`, UnsafeCell-equivalent story.
- **F6.** dtoa/Float printing under freestanding. [20]
- ~~**T1f.** Debug info (line tables → backtraces).~~ DONE (design 69):
  DWARF line tables on by default; lldb breakpoints + `file:line`
  backtraces; panics/asserts name their source location. [tier-1]
- `AllocatedBy<Slab>` sugar. [19, 42]

## Testing & infra
- **M2.** Unit tests for lexer/parser/typechecker internals; fuzz/
  differential testing; property tests over copy/move rules. [critique]
- ~~CI: GitHub Actions workflow for suite + bootstrap.~~ DONE (design 69):
  `.github/workflows/ci.yml` (ubuntu + macos) runs the compiler suite,
  the debug-info test, the blade bootstrap, and semver/toml lib tests;
  README badge. Linux is a new target — first CI run may surface small
  follow-ups (PIC-reloc + sys.executable portability fixes landed).
- ~~Runtime error messages with source locations (subsumed by T1f).~~
  DONE (design 69): panics carry `FILE:LINE`.

## Research tier (post-both-apps)
Const generics; const fn; macros; compile-time reflection (PMP
generation consumer, 46); Char/Int128/Float32; `**`/`::` operators;
Deque; RwLock/Barrier; std.net (after A4); async select;
Sender/Receiver split; §11 futures (effect system, dependent/linear/
refinement types, first-class modules); REPL/LSP/formatter; `defer`/
`do` reserved-word decisions.
