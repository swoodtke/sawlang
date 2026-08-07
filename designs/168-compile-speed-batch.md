# Design 168 — the compile-speed batch

**Status: APPROVED (user, Aug 7: "we should really focus on any
recommendations by the compile-cache investigation - the test
runtimes are really slowing down development"). Priority-jumped:
dispatches with/after DF-163a, ahead of 166/167, concurrent with the
post-M1 wave (disjoint surfaces). Built from design 164's FINDINGS
section (read it first — the numbers and the run-1 miscompile lesson
are the contract's foundation).**

## The shape of the problem (164's profile)

LLVM opt+object 47% + codegen IR build 17% = the back half is ~64% of
every compile, and 90.1% of emitted IR is std — `hello.saw` (4 lines)
emits 27,922 IR lines / 449 defines. The front half (std parse 14% +
typecheck 10%) re-enters 2-3x per compile. Caching only ever touches
the front half (~19% best case); the back half needs EMISSION to
shrink, not caching.

## Units, in order

1. **DF-164b — the link dead-strip (trivial, first).** The hosted
   link line has no dead-strip: add function/data sections +
   `-Wl,-dead_strip` (darwin) / `--gc-sections` (linux) to the clang
   link. Verified by hand at 218,216 → 62,712 bytes for hello
   (52-76% of every binary is dead std today). Size win, ~zero risk;
   assert sizes in a test.
2. **The pre-LLVM reachability strip — the compile-TIME win, and it
   needs NO cache.** Emit (codegen + LLVM) only the REACHABLE subset:
   walk the checked program from the entry points (main, `@export`s,
   runtime-seam references) through calls, monomorphized
   instantiations, CONFORMANCE vtables of instantiated types, drop
   glue, and the coro-transform's synthesized callees — then codegen
   only that set. hello's 449 defines should collapse to dozens,
   taking the 64% back half down proportionally FOR EVERY COMPILE —
   suite, blade, bootstrap, irdet, the remote worker, all of it.
   SOUNDNESS RULE: when in doubt, keep it — an over-kept symbol
   costs bytes the link strip now removes anyway; an over-stripped
   one is a link error (loud) or a missing vtable entry (make it
   structurally impossible: vtables pull their methods, not the
   reverse). The full suite + gmgate + bootstrap + sos are the
   behavior oracle; irdet --all gets FASTER and stays byte-identical
   per seed-pair by construction (the reachable set is deterministic).
3. **DF-164a + DF-164c — deterministic symbol names (prerequisite
   for tier B, and irdet hygiene NOW).** Node-id-derived generated
   names (`__collit_<id>`, ...) and the four synthesized-symbol
   counters make std's emitted IR program-dependent. Re-key from
   stable coordinates (defining file + position + kind, or a
   content hash) so identical input produces identical names
   regardless of allocation order. 164's run-2 differential (43
   .ll-only divergences, objects byte-identical) is the acceptance
   test: after this unit, that differential is 1114/1114 identical.
4. **Tier B — the front-half cache (after unit 3, with 164's
   lessons).** Serialized parsed+typechecked std restored BEFORE the
   entry file parses (the run-1 miscompile was restoring after —
   node-id collision merged two functions' suspend analysis; the fix
   is order + counter seeding from a stored bound). The ONE cache
   key from 164's unit-5 design: whole sawc/*.py digest + std digest
   + triple + profile flags, content-addressed, atomic publish,
   never keyed on the blob's own bytes. Gate: the STRICT whole-corpus
   differential (rc, stdout, stderr, .o, AND .ll) green, plus the
   battery. Expected: ~19% off CLI-path compiles (blade, bootstrap,
   sos_runner, irdet, remote worker); the suite's smaller win
   (deepcopy → loads) comes free.
5. **DF-164d — the re-entry typechecks (cheapest wins only).** std
   is re-typechecked on each of the 2-3 front-half re-entries;
   establish what actually invalidates std analysis on re-entry
   (user-driven instantiations do; std's own bodies should not) and
   skip what provably cannot change. If nothing is provably
   skippable at small cost, record why and stop — unit 2 already
   moved the big number.

Tier C (precompiled std object, ~87% of IR) stays PARKED on the
user's design-144 exemption decision — unit 2 gets most of its win
per-compile without reopening type identity.

## Gates

Per-unit commits, full battery each (suite zero xfails, lexdiff,
astdiff, irdet --all, bootstrap, sos_runner, gmgate), plus unit-
specific: size assertions (1), the strict differential (3, 4).
Report before/after wall-clock for: hello CLI, full suite, bootstrap,
irdet --all. Findings as DF-168x.

---

# RESULTS (Aug 7) — the batch, built

**The profile inverted, and that changed what the last two units were
worth.** Design 164 sized the front-half cache at ~19% because the back
half was 64% of a compile. Unit 2 removed ~85% of the back half without
any cache at all, and the same unchanged front-half work became roughly
two thirds of a compile — so tier B came in at 39%, double its estimate,
and DF-164d's re-entry type-checks are now the single largest stage in
the compiler.

| stage (`hello.saw`) | design 164 | after unit 2 | after unit 4 |
|---|---|---|---|
| std parse | 14.3% | 39.3% | 0 (cached) |
| std type-check incl. re-entries | 9.8% | 28.5% | 30.3% |
| codegen (IR build) | 17.3% | 1.9% | 4.0% |
| LLVM opt + object | 47.3% | 4.8% | 9.1% |
| place lowering | 5.0% | — | 24.5% |
| stdcache restore | — | — | 12.8% |

**On measurement.** This box demotes busy work to efficiency cores, so
identical work drifted 2.6x in wall clock across the session while
sibling agents came and went (load average ranged 3 to 71). Every
figure below is an INTERLEAVED A/B ratio against a sibling worktree —
A, B, A, B — per the DF-156a method, or a back-to-back pair. Absolute
seconds are reported only where both sides were measured minutes apart
under comparable load.

| workload | before | after | |
|---|---|---|---|
| `hello.saw` CLI compile | — | — | **B/A = 0.270, 3.7x** (5 pairs) |
| suite COMPILE phase (`-j` default) | 362.1 s | 138.6 s | **2.6x** (back to back, load 26 / 30) |
| `blade_bootstrap` (stage0→stage2 + lib tests) | 850.1 s | 264.8 s | **3.2x** (back to back, load ~40 both) |
| `hello` binary | 218,216 B | 62,712 B | **-71%** |
| `hello` emitted defines | 449 | 17 | |
| `hello` object's undefined symbols | 534 external | 5 | 4 seams + memcpy |

`irdet --all` was green at unit 2 (902 examples, byte-identical). It
could not be re-run to completion at the tip: two attempts were
SIGTERM-killed after ~4 minutes under load, and at `-j 3` it was
managing 6 files/minute (a ~2.5 hour projection). The 60-example sample
is green at the tip, and the two purpose-built differentials below are
strictly stronger oracles for what this batch could have broken — the
re-emit differential catches everything irdet catches PLUS
process-history dependence, and it is 903/903 clean.

## Unit 1 — DF-164b, the link dead-strip

`-Wl,-dead_strip` on mach-O; `-Wl,--gc-sections` plus the design-112
per-symbol section placement on ELF, since the whole program is ONE
object and without section granularity `--gc-sections` has nothing to
collect. That pass grew an `internalize` parameter (a hosted object
keeps external linkage) and a name that is no longer a lie.

`hello` 218,216 → 62,712, exactly the investigation's hand-verified
number. The flag costs nothing measurable: the link is 24 ms with it and
24 ms without, over four interleaved pairs.

Both caveats were checked rather than assumed:

- **An `@export` that nothing references survives.** A hosted program
  whose only export is unreachable from `main` still carries it:
  `nm` reports `0000000100000598 T _probe_unreferenced`. `@llvm.used`
  (design 58) lowers to `.no_dead_strip` on mach-O. The ELF lowering
  cannot be verified from this host, so exports are ALSO passed to the
  linker as `-Wl,-u,<sym>` keep-roots — the guarantee is stated rather
  than inferred.
- **The darwin debug map coexists with the strip.** macOS leaves DWARF
  in the `.o` and points at it with an N_OSO stab, so the worry was
  orphaned line tables. `lldb -o "breakpoint set --file hello.saw --line
  7"` resolves to `main + 16 at hello.saw:7:5` on the stripped and the
  unstripped binary alike.

`examples/link_dead_strip.saw` pins it from inside the language: it
opens argv[0] and seeks to the end, so the binary the runner just built
is its own oracle. 63,120 stripped against 262,632 unstripped, asserted
under 160,000.

## Unit 2 — the pre-LLVM reachability strip

Codegen was reachability-blind in both regimes: every non-generic
function and extension method got a body unconditionally, and NAMING a
generic type ran `_monomorphize_extension`, which declared and queued a
body for every method of every matching extension.

Emission is now demand-driven. **Declaration stays eager**, deliberately:
half of codegen resolves a callee through a bare `self.functions[name]`
lookup with no ensure-call behind it, and a monomorphization's side
effects (`struct_types`, `mono_struct_args`, `method_defaults`) are what
LATER bodies read. Only the body is deferred, behind the symbol it
defines.

**Reachability is decided by reading the emitted IR, not by walking the
AST.** The brief's rule is "when in doubt, keep": an over-kept symbol
costs bytes unit 1 removes anyway, an over-stripped one is a link
failure. An AST call-graph walk would have to re-derive overload
resolution, trait dispatch, drop glue, derived conformances, closure and
trampoline synthesis, and the coroutine transform's callees — and every
gap in that re-derivation is an over-strip. Reading what codegen
actually emitted inverts the risk: a body is kept because emitted code
names its symbol. The scan is textual because llvmlite erases a constant
bitcast into a `FormattedConstant` whose payload is a plain string, so
an object walk has blind spots the rendered text does not; a false
positive (a string literal containing `@main`) over-keeps, which is free.

The fixpoint OWNS the monomorphization and vtable queues rather than
running after them. Filling a vtable emits thunks that call their impls,
so the next scan pulls those impl bodies in — vtables pull their
methods, which is the direction that makes over-stripping structurally
impossible for dynamic dispatch. Roots are `main`, every `@export`, and
every `@section` placement.

Applied only where this compile owns the whole program: an executable
link, or an object that already internalizes everything but its exports
(`--freestanding`, `--runtime-build`). A plain hosted `-c` object is
somebody else's to link and keeps every symbol. With the strip off the
deferred-body registry drains in registration order, which is the order
the old eager passes ran in, so those builds are byte-identical.

| example | defines | IR lines |
|---|---|---|
| hello | 449 → **17** | 27,928 → 1,068 |
| map_basic | 498 → 52 | 31,310 → 3,523 |
| string_methods | 449 → 31 | 28,063 → 2,693 |
| net_http_roundtrip | 518 → 250 | 33,673 → 17,854 |
| trait_simple | 450 → 18 | 27,955 → 1,097 |
| vector_literal_owning_deinit | 467 → 27 | 29,244 → 1,635 |
| **total** | **2831 → 395 (-86.0%)** | **178,173 → 27,870 (-84.4%)** |

**Wall clock: B/A = 0.433 over six pairs — a 2.3x faster compile.**
Binaries barely move (63,096 → 62,728 for hello), because unit 1 was
already removing those bytes at link. The two units compose exactly as
the brief predicted: unit 1 sets the size floor, unit 2 stops paying
LLVM to produce what unit 1 throws away.

`irdet --all` stayed green (902 examples, byte-identical), so the
reachable set is deterministic by construction and no DF-168x was owed.

## Unit 3 — DF-164a + DF-164c, deterministic synthesized names

Seven sites, not six: `.str.N` (`_create_string_constant`) is a fifth
counter DF-164c did not enumerate. Locals take their SOURCE POSITION;
the three literal pools take a CONTENT tag (they were already
content-keyed caches, so the content is the name they should always have
had); closures take their OWNER plus position, and the owner is the
enclosing llvm function, whose name already carries the
monomorphization — so the same source closure under `Vector<Int>.map`
and `Vector<String>.map` is distinct by construction rather than by
counting. A spawn trampoline follows its closure. `hashlib`, never the
builtin `hash()`, which `PYTHONHASHSEED` salts and `tools/irdet.py`
deliberately varies.

**The oracle is new, because none of this was visible to the ones we
had.** `irdet` compiles one file per PROCESS, where a counter-derived
name is perfectly stable. `tools/reemitdiff.py` compiles each example
twice inside ONE interpreter and byte-compares the `.ll` and the `.o` —
which is also the shape the suite runs in, since the persistent workers
compile many files per process.

```
before: 858 identical,  45 DIVERGENT   (every one .ll only, never .o)
after:  903 identical,   0 DIVERGENT
```

That 45 is design 164's 43, found independently, plus the two the fifth
counter contributed. It is the same divergence that turned 164's tier-B
gate red, and clearing it is what let unit 4 pass a byte-level gate.

## Unit 4 — tier B, the front-half cache

The `(builtin_ast, builtin_ns)` pair as ONE 2.08 MB pickle under
`.build/stdcache/<key>.blob`. Never two blobs: the audit found the AST
and the symbol tables share `SawType` objects by identity, which design
144's in-place canonicalization rests on, and two pickles would restore
two graphs that no longer alias — a struct compiled against another
struct's layout, with no diagnostic.

**The stdlib is now built before the entry file is parsed on the COLD
path too, and that is the load-bearing decision.** The cache needs
restore-before-parse for correctness (pickle preserves `node_id`, so a
late restore collides with ids the entry file already took, and design
164's prototype miscompiled 13 of 1,114 examples exactly that way;
`seed_node_ids` closes it in one assignment from a stored bound).
Moving the cold path too is what makes the cache INVISIBLE rather than
merely safe: both paths then allocate node ids in the same order, so a
warm compile is byte-identical to a cold one instead of only equivalent.
Restoring ahead of a cold build that still ran late would have left
every generated name shifted between them.

The key is 164 unit 5's, unchanged. Two things it did not specify:
`.build/stdcache/` keeps its eight most recent blobs (the key moves
whenever any compiler source does, so a day of compiler work would leave
hundreds of megabytes behind), and a process that compiles more than
once holds the blob's BYTES, never the unpickled graph — a compile
mutates both halves of the pair, so the restore IS the reset.
`SAW_NO_STDCACHE=1` is the cold side of the gate and the escape hatch.

**The gate — the strict whole-corpus differential**, exit code, stdout,
stderr, `.ll` and `.o`, one compile per process on both sides (design
164 unit 5's correction: the linked executable is not a reproducible
artifact on macOS, since its N_OSO stab carries the object's path and
mtime):

```
STRICT differential (rc, stdout, stderr, .ll, .o):
  1186/1186 identical, 8 skipped, 0 DIVERGENT
```

So it ships ON by default rather than behind a flag.

**Wall clock: B/A = 0.606 — 39.4% faster, double design 164's estimate,
because unit 2 shrank the denominator.**

## Unit 5 — DF-164d, the re-entry type-checks

Measured, and NOT skippable at small cost — which the brief permits as
an outcome. It is now the largest single stage: **30.3% of a `hello`
compile** (one re-entry; two, ~0.4 s, for a driven program).

The cheap idea fails on a fact worth recording. `hello.saw` is four
lines with no place uses of its own and still forces the re-entry,
because the program `transform_place_uses` rewrites is **std** — 85
extensions of it — and it then `uncheck`s every program in its list once
any one of them changed. std is dirty for essentially every program, so
a per-program dirty flag buys nothing.

What would work is caching std's state AFTER place lowering, since that
state is the same for every program. The blocker is that
`transform_place_uses` is handed ONE merged namespace with no per-module
scoping, so a user `borrows` extension on a std type could in principle
change how std's own bodies lower — either a design-142 scoping
violation to fix first, or a contribution the key must cover. That is a
design question, not an implementation detail. Filed as DF-168b; worth
its own brief, since design 168's cache machinery is most of the work.
