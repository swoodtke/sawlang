# Design 164 — per-module compile caching: the investigation

**Status: APPROVED as an INVESTIGATION (user, Aug 7: "another
investigation should be per-module (or per-file) compile caching...
emit a binary cache of the std module which can be reused by each
binary"). Measurement, feasibility audit, and a costed recommendation
— the implement decision returns to the user. A LOW-RISK prototype of
the cheapest tier MAY land behind a flag if its differential gate is
airtight; anything deeper is design-first.**

## The problem

Every sawc invocation parses, typechecks and codegens builtin.saw +
all of std from scratch. The suite is ~1400 invocations; the remote
worker's jobs pay it; the self-hosting track will pay it worse.
`.build/rt/` already proves the pattern (digest-keyed cached objects,
auto-linked); std is the same idea one layer up.

## Units

1. **Profile where the time goes.** Instrument one compile (and a
   corpus sample): wall time per stage — std parse, std typecheck,
   std codegen, user-code stages, LLVM opt/link — so each cache tier
   has a ceiling attached. Report per-compile and battery-wide
   multiples.
2. **Tier A — AST cache (cheap).** Serialized parsed std ASTs (+ doc
   trivia), keyed by content digest. Assess serializability of the
   AST graph; prototype if clean; measure. Oracle: astdiff between
   cached and fresh must be byte-identical, and irdet cold-vs-warm.
3. **Tier B — typechecked-namespace cache (medium).** Audit the
   namespace/symbol object graph for serializability (type objects,
   conformances, effect info, the design-144 identities, the
   design-82 per-file std modules). Verdict + effort estimate; no
   prototype unless the audit is clean.
4. **Tier C — precompiled std object (the big one).** Analysis, not
   code: what fraction of std codegen is NON-GENERIC (cacheable as a
   .o outright) vs generic templates that must stay per-binary for
   monomorphization? Which prelude instantiations (Vector<Int>,
   Map<String, V> shapes, String machinery) recur often enough to
   pre-instantiate? How does it compose with --gc-sections, the
   design-80/82 visibility gates, and the 144 mangling (stable symbol
   identity should make this FEASIBLE — verify)? Effort estimate.
5. **The cache key, designed once.** (compiler-source digest, std
   digest, target triple, profile flags: freestanding /
   runtime-build / no-hidden-alloc / -O level). Invalidation story;
   where cache lives (.build/stdcache/ beside .build/rt/); how the
   remote worker's digest-keyed scheme extends. A WRONG key is a
   stale-cache miscompile — the differential gate (compile the corpus
   cold and warm, byte-compare every artifact) is non-negotiable for
   any tier that ships.
6. **Recommendation with numbers**: per tier — ceiling, measured or
   estimated win, effort, risk. The user picks the tier(s).

## Constraints

Read-mostly; tier-A prototype may land BEHIND A FLAG (default off)
only with the cold/warm differential green over the whole corpus.
Full battery for any sawc/tools change (suite zero xfails, lexdiff,
astdiff, irdet --all, bootstrap, sos_runner, gmgate). Findings as
DF-164x. Report into the tracker as a design-164 section.

---

# FINDINGS (Aug 7) — the investigation, answered

**The headline is not the one the brief expected.** Caching std's
front half is real but small: parse + typecheck is 24% of a compile
and the re-entry structurally cannot be cached, so tiers A and B are
worth ~11% and ~19% respectively. The compile is dominated by the BACK
half — codegen + LLVM is 65%, and **90.1% of the emitted IR is std**.
Only tier C touches that, and tier C turns out to be feasible on
identity grounds (design 144 delivers program-independent symbol
names — verified) but blocked on ONE thing that is a design question,
not an engineering one: `compute_std_codegen_exclusions`.

Two findings that are worth more than any cache tier fell out on the
way, and neither needs this brief to land: **the hosted link line has
no dead-strip, so every Saw binary carries 52-76% dead std**
(DF-164b), and **four synthesized-symbol counters make std's emitted
IR program-dependent for no reason** (DF-164c).

## Unit 1 — where the time goes

Method: `probe_stageprof.py`, an exclusive-time profiler wrapping the
pipeline seams (inner time never double-counts into an outer stage).
7 examples spanning trivial / collections / string / concurrency /
net, in-process, one compile per measurement.

| stage | cold | warm (in-process cache) |
|---|---|---|
| std parse | **14.3%** | 0 (cached) |
| std typecheck | **9.8%** | 6.9% |
| user parse + typecheck | 0.4% | 0.5% |
| place lowering | 5.0% | 5.4% |
| coro transform | 0.3% | 0.3% |
| codegen (IR build) | 17.3% | 20.4% |
| IR text emit | 0.7% | 0.8% |
| **LLVM opt + object** | **47.3%** | **52.0%** |
| link (clang) | 1.7% | 2.1% |
| deepcopy (the cache's own cost) | — | **7.2%** |

Cold CLI `hello.saw` is 2.56-2.74 s wall; interpreter startup + every
compiler import is only 150 ms of it, so process-per-compile overhead
is NOT the problem — the work is.

Three structural facts the table encodes:

1. **The front half runs 2-3 times per compile.** `_prepare_codegen`
   re-enters after place lowering (`sawc.py:1005-1024`) and again
   after the coroutine transform (`:1040-1075`). Design 146 already
   removed the re-PARSE (the re-entry hands its own AST back), but std
   is **re-typechecked every pass** — 2 passes normally, 3 when the
   coro transform fires. Any cache serves the FIRST build only.
2. **The back half re-does std wholesale.** Sub-profiling
   `compile_to_object`: `str(module)` 1.5%, `parse_assembly` 3-4%,
   `verify` 0.1%, **O1 passes 29-37%, `emit_object` 58-67%**.
3. **`hello.saw` — four lines of user code — emits 27,922 IR lines /
   449 defines / a 265 KB object / a 218 KB binary with 503 text
   symbols.** Adding up std's share of a hello compile (parse 384 +
   typecheck 289 + place 168 + codegen 430 + LLVM 1239 ms) gives
   **~93% of the compile spent on std**.

The warm in-process path — the floor a cross-process cache competes
with — still pays ~20% per compile on std: the uncacheable re-entry
typechecks (~180 ms) plus the cache's own `deepcopy` (~190 ms). Note
that the deepcopy costs almost half of what it saves; `pickle.loads`
is ~2.3-2.5x cheaper than `deepcopy` on the same graph, so **the
suite's own warm path would get faster from this work too** — a point
the brief asked to be honest about, and it lands the other way than
expected.

## Unit 2 — tier A (serialized std ASTs): CLEAN, ~11%

- **Serializable as-is.** 44,236 reachable objects, no lambdas, no
  bound methods, no llvmlite, no `re.Pattern`, no file handles, no
  `__slots__` hazards. `pickle.dumps(protocol=5)` = **1.59 MB**.
- **Round-trips exactly.** The restored AST is **byte-identical to a
  freshly parsed one under the `ast_dump` oracle** (666,626 chars on
  both sides) — the astdiff-grade check the brief asked for.
- **Load is 4-6x cheaper than parse**, and deserialization IS the
  per-compile copy (no `deepcopy` needed on top).
- **Ceiling: 14.3% of a compile. Measured win: ~11%** (parse ~385 ms
  replaced by a ~55-110 ms load).
- **Differential:** see the gate section below.

Prototype built OUT OF TREE at `.build/scratch/sawc_cached.py` —
`sawc.load_builtins` wrapped with a digest-keyed pickle cache, ~40
lines. Nothing in `sawc/` was modified. See the recommendation for why
it did not land as a flag.

## Unit 3 — tier B (typechecked namespace): CLEAN, ~19%, one real hazard

Audited the `(builtin_ast, builtin_ns)` pair returned by
`build_builtin_namespace`.

- **Picklable as-is**: 2.08 MB at protocol 5 (gzip-1 → **0.30 MB** in
  20-45 ms, worth doing). 31,097 objects; exactly one `Namespace`;
  `ns.modules` is empty, so no `ModuleSymbol → Namespace` chain is in
  the blob. No `TypeChecker`/`ErrorReporter`/`CodeGenerator` leaks in.
  Works at the DEFAULT recursion limit — the graph is wide, not deep.
- **Every identity invariant survives a single-blob round trip**, and
  they were checked rather than assumed: `SawType` aliasing between
  the AST and the symbol tables (`shared=106 broken=0` — the invariant
  design 144's in-place canonicalization at `typechecker/types.py:100`
  depends on), `StructSymbol.ast_node` (`ok=19 broken=0`),
  `FunctionSymbol.ast_node` (`in=348 out=0`), and enum singletons
  (`TypeKind`/`Visibility`/`SymbolKind` restore `is`-identical).
- **9/9 sample examples emit byte-identical IR** with the namespace
  restored from a blob written by an earlier process.

**The one real hazard — `node_id` (this is also DF-164a's cousin).**
`ast_nodes.py:618-629`: node identity is a process-global counter, and
`__deepcopy__` deliberately FRESHENS it. Pickle preserves it verbatim.
Because `compile_saw` parses the USER file first (`sawc.py:1203`) and
builds builtins second (`:769`), a restored std graph carrying ids
1..14,321 **collides with user node ids** — measured ~0.6% per entry
extension. What a collision corrupts is silent, not loud:
`effects.py:255` merges two functions' suspend analysis under one key;
`coro_transform.py:5152` decides "entry extension or std?" purely by
node-id membership, so a std extension gets reclassified as user code.
Two fixes: renumber the restored graph on load (~170 ms — eats most of
the win), or **restore the blob BEFORE parsing the entry file and seed
the counter past it (free)**. The latter is correct and cheap.

**Mutation is heavy, which argues FOR pickle and against cleverness.**
Place lowering rewrites std method bodies in place (`ForceUnwrap` →
`MethodCall`, `ArrayIndex` gains five attributes); and user code
mutates the shared builtin SYMBOLS — `examples/generic_primitive_bounds.saw`
adds `foo` + `Fooable` to the cached `Int` and `Float` symbols. So a
cache must hand out a pristine graph per compile. There is no
incremental "reset the mutated bits" design to be had — **the restore
IS the reset**, and that is exactly what `pickle.loads` gives.

- **Ceiling: ~24%; realistic win ~19%** (the first build only; the
  ~50 ms re-entry recheck can never be served).
- **Effort: 2-4 engineer-days.**
- **Hard rule for whoever builds it: never split the pair across two
  pickles.** Separate blobs break the `SawType` aliasing above and the
  symptom is a struct compiled against another struct's layout, with
  no diagnostic.

## Unit 4 — tier C (precompiled std object): FEASIBLE ON IDENTITY, BLOCKED ON EXCLUSIONS

Measured over 13 examples plus a synthetic `allstd` importing every
import-required std module. Provenance taken from DWARF
`DISubprogram → DIFile`, so std/user attribution is exact, not
name-guessed.

**The prize is large.** std is **70.2% of defined functions and 90.1%
of emitted IR body lines**; user code is 0.6% / 1.3%. `hello.saw`
emits 12 lines of user IR against 21,838 lines of std. Six of the
thirteen programs emit the *identical* 312 std defs / 21,838 std IR
lines, and all of std (`allstd`) is only 29% more code than the
prelude floor.

**The generic/concrete split.** Codegen has two disjoint regimes:
concrete decls are emitted unconditionally and reachability-blind
(`codegen/core.py:1670-1676`), generics on demand at the use site's
type args, deduped by mangled name (`codegen/generics.py:57,375`).
Within std: **54.5% of IR is non-generic** — the option-(b) ceiling,
i.e. 49% of ALL emitted IR. Of the 294 distinct monomorphized std
symbols, **142 appear in 13/13 binaries and carry 92.3% of the
monomorphized-std IR weight** — and they come from std instantiating
ITSELF (TaskGroup's `Vector<Int>`/`Vector<Bool>` slot arrays,
`String.split`'s `Vector<String>`, the executor's
`Vector<Box<any Resumable>>`), not from user code. That set is a
property of the std sources, knowable offline. Non-generic plus the
universal instantiations covers **~96.5% of std IR ≈ 87% of all IR.**

**Does std's emitted code vary per program? Essentially no.** Peeling
normalizations one at a time over the 312 std functions common to all
12 hosted programs:

| normalization | std bodies still differing |
|---|---|
| raw text | 312 / 312 |
| strip `!dbg !N` | 197 / 312 |
| + resolve `.sawstr.N` / `.rawbytes.N` to CONTENT | 17 / 312 |
| + normalize `__closure_N` | 1 / 312 |
| + normalize `__task_tramp_N` | **0 / 312** |

Nothing semantic varies. No program paths leak (design 122's panic
strings carry the std file BASENAME + line, definition-site and
program-independent); no allocator variance (a user allocator makes a
new mangled name, not a different body); statics are already
module-qualified. The four counters are DF-164c.

**Design 144 makes tier C feasible — verified, not assumed.** 312 std
symbols carry byte-identical mangled names across all 12 hosted
programs AND across targets (the x86_64-linux freestanding build).
Structurally guaranteed: `mangle_named` is a pure function of base
identity + type args, and design 144 fuses only the DEFINING module
into the base, which for std is the identity function.

**The blocker is `compute_std_codegen_exclusions` (`sawc.py:401-469`).**
Over all 2^12 subsets of `IMPORT_REQUIRED_STD_MODULES` there are **288
distinct compiled-std sets** (14-24 files; always-compiled floor of
14). So "std" is not one fixed body of code — it is one of 288. And a
fixed whole-std object re-opens the exact collision design 82/84
closed, verified reproducibly at the object level: a user
`struct File` plus `import std.file` gives
`error: ambiguous struct File: defined in both <builtins> and <entry>`,
and the emitted symbols hard-collide (`_File_read`). The reason it
cannot be patched at the namespace layer alone is design 144's std
exemption (`type_identity.py:36-49`): std types and root-module user
types share one flat symbol space by explicit decision. **Unblocking
whole-std means module-qualifying std type identities — reversing a
design-144 decision. That is a user question, not an implementation
detail.**

The practical shape is therefore NOT a shipped prebuilt object but a
**content-keyed local cache per (triple, profile, exclusion-set)**,
exactly like `.build/rt/<hash>/`. The sample hit only 6 distinct sets
and real programs cluster hard on the 14-module floor.

- **Effort: 8-12 engineer-days** for option (b), on top of DF-164b and
  DF-164c.
- **Risk beyond the blocker:** `_monomorphize_extension`
  (`generics.py:415`) emits EVERY method of a generic extension when a
  type is instantiated, so a pre-instantiation set is all-or-nothing
  per type. And std is in the coroutine transform's INPUT
  (`imported_ast=merged_ast`, `sawc.py:1043`) — someone who owns that
  file must confirm it never mutates std decls before a shared std
  object is trusted. (Not audited here: that file belongs to the
  concurrent design-163 investigation.)

## Unit 5 — the cache key, designed once

One key serves every tier; only the payload changes. A wrong key is a
stale-cache miscompile, so every choice below is the paranoid one.

```
key = sha256(
    "saw-stdcache-v1"                  # format tag: bump when the payload changes
    sys.version, pickle.HIGHEST_PROTOCOL   # the blob's own compatibility surface
    for each *.py under sawc/, sorted by path relative to sawc/:
        relpath, content                # THE WHOLE TREE, not a curated subset
    freestanding, runtime_build, no_hidden_alloc, target_triple,
    target_features, optimize_level     # everything that changes what is loaded
                                        # or what checking MEANS
    for each of builtin.saw + std/*.saw actually loaded under those flags:
        ABSOLUTE path, content
)[:16]
```

Five decisions, each with its reason:

1. **Digest EVERY `.py` under `sawc/`, not the AST-relevant subset.**
   A curated subset is precisely the bug class this key exists to
   prevent — the day someone edits `lexer.py` and the key does not
   move, the compiler silently uses a stale std. Hashing ~2 MB of
   Python costs ~5 ms, which is 1-2% of the win. `rt_build.py:59`
   already takes this route (it digests its own builder file).
2. **Absolute std paths, not relative.** `source_file` is baked into
   every AST node and feeds `#file`, design-82 provenance and design-
   121 docs. An absolute path makes the key self-invalidating across
   checkouts and across the remote worker's unpacked snapshot — which
   is CORRECT: the worker builds its own cache once per sync and
   reuses it across its jobs, rather than being handed a blob whose
   baked paths do not exist on that machine.
3. **The flags that change what is loaded AND what checking means.**
   `freestanding` drops the hosted std modules; `runtime_build` loads
   none. Beyond the file set, DF-137d makes the target triple change
   what a CHECKED std means (platform `Int` is pointer-width, so a
   literal std accepts on a 64-bit host is a range error on riscv32) —
   `test_runner.py:372` already keys its in-process cache on exactly
   `(freestanding, runtime_build, target_triple)`, and this is that
   key made durable.
4. **Content-addressed, write-once, never overwritten.**
   `.build/stdcache/<key>.blob`, anchored at the COMPILER checkout via
   `__file__` — never the caller's cwd, for the reason `rt_build.py:70-79`
   records (blade invokes sawc from arbitrary directories, and a stale
   scratch file named `rt` once broke every repo-root compile).
   Because nothing is ever overwritten, a stale entry is impossible by
   construction; old entries are inert garbage and `.build/stdcache/`
   is disposable.
5. **Atomic publish, no lock.** Write `<key>.tmp.<pid>`, then
   `os.replace`. A partially written blob is never observable, and
   concurrent sawc processes (the test runner's 8 workers) may
   duplicate the work once but can never corrupt each other.
   `rt_build.py` needs an `flock` because it builds a multi-file
   directory; a single blob does not.

**Never key on a hash of the blob itself.** `pickle.dumps` is not
byte-stable across processes — sets serialize in iteration order and
`PYTHONHASHSEED` is randomized (`tools/irdet.py:44` deliberately
exercises seeds 1 and 424242). Measured: `dumps(x) != dumps(roundtrip(x))`
by 5 bytes. Key on the SOURCES.

**The differential gate, and one correction to how the brief framed
it.** The brief says byte-compare every artifact. On macOS the linked
executable is not a valid oracle: it carries an N_OSO debug-map stab
holding the object's path and mtime, so **two COLD compiles of one
file into different directories already differ** (measured). The
reproducible artifacts are the IR sidecar and the object, plus exit
code / stdout / stderr. The gate must also run **one compile per
process** — see DF-164a, which makes in-process IR text irreproducible
for reasons that have nothing to do with caching.

## Unit 6 — recommendation, with numbers

| tier | ceiling | measured / est. win | effort | risk |
|---|---|---|---|---|
| **A** std AST blob | 14.3% | **~11%** (measured) | 0.5-1 d | LOW — round-trip is astdiff-identical; restore IS the copy |
| **B** typechecked namespace | 24% | **~19%** (est.) | 2-4 d | MEDIUM — `node_id` seeding is mandatory; a wrong restore miscompiles SILENTLY |
| **C** precompiled std object | ~87% of emitted IR (~60% of compile) | est. 3-5x on `hello` | 8-12 d | HIGH — needs DF-164b + DF-164c first, and whole-std needs a design-144 reversal |
| **DF-164b** dead-strip | — | **52-76% binary size** | **0.5 d** | LOW — one line |

**Recommended order — and note that the first item is not a cache.**

1. **Land `-dead_strip` / `--gc-sections` (DF-164b) on its own.** One
   line at `sawc.py:1146`. Every Saw binary today ships 52-76% dead
   std: `hello` is 218 KB of which 155 KB is unreachable, 534 external
   symbols of which 84 are live. It is also the precondition that
   makes any fixed-set std object size-neutral — with dead-strip,
   `allstd` (every std module compiled in) strips to 62,728 bytes,
   **within 16 bytes of `hello`'s 62,712**. Highest value per unit
   effort in the whole investigation, and independent of every tier.
2. **Determinize the four synthesized-symbol counters (DF-164c)** —
   `.sawstr.N`, `.rawbytes.N`, `__closure_N`, `__task_tramp_N` — to
   content- or owner-derived names, and fix DF-164a with them. This is
   the ENTIRE remaining IR-variance obstacle to tier C, and it
   strengthens the design-126/141 reproducibility property on its own
   merits. ~2 d + an `irdet --all` gate.
3. **Then pick a front-half tier.** Tier B subsumes tier A: same
   mechanism, same cache key, one blob instead of two, +8 points of
   win for the `node_id` work. If the appetite is one afternoon, take
   A; if it is a week, take B and skip A entirely. **Taking A now and
   B later means building the same thing twice.**
4. **Tier C last, and only after a user decision** on whether design
   144's std type-identity exemption survives. Without that decision,
   tier C is limited to a content-keyed per-exclusion-set object
   cache — which is still worth most of the win, because real programs
   cluster on the 14-module prelude floor.

**On the tier-A prototype: it is built and gated, and it did NOT
land.** The brief permits it behind a default-off flag; the reason to
decline is that a default-off flag delivering 11% is a code path
nobody enables and everybody maintains, and tier B replaces it
wholesale with the same ~40 lines of plumbing and the same key. The
working prototype is `.build/scratch/sawc_cached.py` (out of tree,
nothing under `sawc/` modified) and is one commit away should the user
want it. See the gate result below.

## Findings filed

- **DF-164a — `__collit_{node_id}` leaks the process-global node
  counter into emitted IR.** `codegen/collections.py:86`. A process
  that compiles more than once emits DIFFERENT IR text for identical
  source: `%"__collit_14189"` vs `%"__collit_29638"` on
  `examples/place_paired_literal_fields.saw` and
  `shadow_owning_lifetime.saw`. Object files are byte-identical (local
  SSA names do not reach the object), so this is IR-text-only today —
  but `tools/irdet.py`'s one-compile-per-process oracle structurally
  CANNOT see it, and design 126 R2 introduced `node_id` precisely to
  make compiler output reproducible. Same class at
  `codegen/match.py:152`, which builds `__match_scrutinee.{id(expr)}`
  from a **raw address** — the exact thing design 126 R2 removed
  everywhere else. Found by the tier-A differential; the cache was
  exonerated by a fresh-vs-fresh repro.
- **DF-164b — the hosted link line has no dead-strip.**
  `sawc.py:1146` is `["clang", obj, *rt_objects, "-o", out]`: no
  `-dead_strip`, no `--gc-sections`, no `-ffunction-sections`. Hosted
  std keeps external linkage (0/312 internal, measured) so `-O1`'s
  `globaldce` cannot reach it either. Relinking the sample with
  `-Wl,-dead_strip` (binaries still run): 52-76% smaller across the
  board; re-verified by hand on `hello`, 218,216 -> 62,712 bytes with
  unchanged output. **Caveat before anyone lands it blind:** an
  `@export`ed symbol in a HOSTED executable that nothing references
  from the entry graph is precisely what dead-strip removes, so
  `@export`/`@section` and the design-149 runtime-provider role need a
  deliberate keep. `examples/export_roundtrip.saw` and the
  `EXPECT-SYMBOL-UNDEFINED` tests are the oracle. Freestanding and
  `--runtime-build` never link, so they are untouched.
- **DF-164c — four synthesized-symbol counters make std's IR
  program-dependent for no reason.** `.sawstr.N`
  (`codegen/core.py:1534`), `.rawbytes.N` (`codegen/calls.py:478`),
  `__closure_N` (`codegen/closures.py:126`), `__task_tramp_N`
  (`codegen/calls.py:1805`). One counter shared by std and user code,
  so any user string literal renumbers every std reference. Normalize
  all four and **0/312 std bodies differ across 12 programs**. Blocks
  tier C; costs nothing else today.
- **DF-164d — the front half re-typechecks std 2-3 times per
  compile.** The place-lowering re-entry (`sawc.py:1005-1024`) and the
  coro-transform re-entry (`:1040-1075`) each re-run
  `build_builtin_namespace` over std. Design 146 removed the
  re-PARSE; the re-CHECK remains, ~150 ms per extra pass, and no cache
  can serve it because the AST being rechecked is the program's own
  mutated std. Whether the second check is NECESSARY (place lowering
  rewrites std bodies, so probably yes) was not established here —
  worth a look, since removing one pass is worth about as much as
  tier A.
