# Splice-all instance-check census — the FULL population (design 218 unit 1.5, stage 3c-2)

Read-only census, main @ `2b3a500d`. Nothing tracked was changed. Probes and
raw data: `/Users/shawn/Projects/sawlang/.build/scratch/census_splice/`;
machine-readable records: `/Users/shawn/Projects/sawlang/.build/scratch/census_splice_all.jsonl`
(one JSON object per diagnostic; fields `scope, population, file, instance_key,
instance_display, instance_kind, template_base, method, flavor, class, message,
hint, err_file, err_line, err_column, note, site, in_body_index`).

## Verdict

Over **224,768 registered instances / 667,851 materialized (instance, body)
pairs across 1,617 compilation units**, the §1c instance check reports
**10,311 diagnostics in 20 primary classes** (25 classes counting
cascade-only and scope-only ones) — and **the single largest structural
finding is not a class at all**: the instrument the stage-3c agent measured
with (and `measure_splice_all` itself) runs the check with the compile's
*ambient* namespace as the lend source, which is **not** the merged namespace,
and that alone accounts for 2,195 of the diagnostics (12,506 -> 10,311) and
**four entire classes**. The class list looks CLOSED at the margin (see §7).

## 1. The instrument, and how it differs from `measure_splice_all`

`census_lib.py` replaces `monomorphize.measure_splice_all` (module-global
lookup in `run_monomorphization`) and drives the compiler front half only
(`sawc._prepare_codegen`, which includes the place-lowering re-entry and the
coroutine-transform re-entry — so the spec's phase 6 is inside the census).
Three differences from the shipped instrument, each a measurement-quality
property the 3c bounded probe lacked:

1. **Method-GENERIC instances are materialized.** `measure_splice_all` handles
   only registry kinds `fn` and `struct`/`enum`; kind `method` — 76,870 of the
   224,768 instances, **34%** — is materialized by nothing today. Modelled on
   `_build_generic_struct_method_mono` (method-generic on a generic struct's
   extension) and `_build_method_mono` (design 40 item 9's method-generic on a
   non-generic extension). *This is where the biggest class lives.*
2. **A fresh `ErrorReporter` per instance.** `_checking_instance`
   (`typechecker/core.py:2903`) mutes an instance when
   `self.reporter.has_errors()`. `measure_splice_all` installs ONE throwaway
   reporter for the whole loop, so after the first failing instance every later
   instance in that compile is silently muted. Per-instance reporters make the
   count complete; this is why the corpus numbers are far larger than 115.
3. **A scope dimension** (`CENSUS_SCOPE`):
   - `home` — byte-for-byte what `measure_splice_all` does: `_home_module_scope`
     with whatever `typechecker.namespace` happens to be at phase-2 time as the
     lend source for `_lend_instantiation_types`.
   - `merged` — the same check with `mono.namespace` (the MERGED program
     namespace, the one codegen sees) installed as the lend source first.
   Measured fact: at phase-2 time `typechecker.namespace is mono.namespace` is
   **False in every one of the 1,617 compiles** (`ns_is_not_merged` counter).

Both scopes were run over every population. `merged` is the honest floor for a
cutover (a cutover would obviously install the right namespace); `home` is what
the existing instrument reports and therefore what A3/DF-286b measured.

## 2. Coverage (the fraction Amendment B can quote)

| population | files probed | instances | pairs (fn / type-method / method-generic) | diagnostics (home / merged) |
|---|---|---|---|---|
| `examples/` (suite corpus) | 1558 | 215,028 | 639,625 (250 / 565,864 / 73,511) | 11,753 / 9,958 |
| `blade/src/main.saw` (+3 module paths) | 1 | 552 | 1,584 (0 / 1,370 / 214) | 42 / 18 |
| `blade/tests/` | 25 | 5,085 | 14,482 (0 / 12,761 / 1,721) | 417 / 173 |
| `libs/{toml,semver,imgformat}` tests + lib entries | 13 | 1,551 | 4,618 (0 / 4,071 / 547) | 85 / 65 |
| `devtools/{irdet,bench,dogfood}` + `selfhost/lexer` (entry + tests) | 19 | 2,441 | 7,212 (0 / 6,387 / 825) | 204 / 92 |
| std's own closure (`examples/hello.saw -c`) | 1 | 111 | 330 (0 / 292 / 38) | 5 / 5 |
| **total** | **1,617** | **224,768** | **667,851 (250 / 590,745 / 76,856)** | **12,506 / 10,311** |

(`stdclosure` is `hello.saw` again under `-c`; the registry is identical either
way, which is itself a measured fact: instance EXISTENCE does not depend on
`-c`, exactly as §1b says.)

**Method-generic subtotal: 76,856 pairs (11.5% of pairs), 76,870 instances
(34% of instances)** — the population DF-286b explicitly records as
"NOT COUNTED".

### What is NOT covered, and why

- **`examples/` skips (911 files):** 489 `// EXPECT: error`, 341 under
  `examples/errors/`, 67 `// EXPECT: skip`, 7 XFAIL, 7 `--emit-docs` tests.
  None of these reaches a green registry, per the task's own rule.
- **71 `examples/` files refused their own compile**: every one is a MODULE
  SUPPORT file (`examples/modules/**`, `examples/conformance/modules/**`) with
  no `main`, which the suite never compiles standalone either. Their bodies ARE
  censused, through the entry files that import them.
- **8 other refusals**: `devtools/dogfood/programs/w1_{chatroom,filesearch,
  limiter,mapreduce,pipeline}.saw` and 3 `blade/tests/fixtures/**` packages —
  they need flags/resolution my driver does not model (dogfood specs, blade's
  own resolver).
- **14 method-generic instances in `examples/` had no pristine template**
  (`no_template_method`) and were not materialized — a real coverage hole in
  the census AND a hole a cutover must answer (the same store lookup would
  fail there).
- **DF-286c face 4 (`-> T?` tail auto-wrap emitting invalid IR) is INVISIBLE to
  this instrument**: the census stops before codegen.
  `examples/generic_optional_tail_return.saw` produces **zero** census
  diagnostics. Face 4 is neither confirmed nor refuted here.
- No `--target`/freestanding-only sweep beyond whatever `// COMPILE-FLAGS:`
  the corpus files carry (those ARE honored).
- 0 materialization crashes across all populations (no ICE inside the funnel).

## 3. The mechanisms (evidence first)

### M1 — the home-module scope cannot answer ANY question about a type argument

`_home_module_scope` (typechecker/core.py:961) installs the template's module
namespace and lends the instantiation's type arguments across with
`_lend_instantiation_types`. **The lend does not work for corpus types.**

Probe `probe_conf.py`, `examples/ref_no_escape_alias_boundary.saw`,
instance `Vector<Handle, GlobalAllocator>.sort` (home module `('<std>','vector')`):

```
   merged: {'tier': 'free', 'Copy': True, 'ExplicitCopy': True, 'Equatable': True,
            'Comparable': True, 'Hashable': True, 'Send': True, 'Sync': True}
   home:   {'tier': 'abstract', 'Copy': False, 'ExplicitCopy': False, 'Equatable': False,
            'Comparable': False, 'Hashable': False, 'Send': False, 'Sync': False}
   DIFFER: ['Comparable','Copy','Equatable','ExplicitCopy','Hashable','Send','Sync','tier']
```

Probe `probe_lend2.py`, same instance:

```
  merged: {'lookup_struct': False, '_lookup_struct_deep': False,
           'is_abstract_type_name': False, 'resolve_identity': 'Handle'}
  home:   {'lookup_struct': False, '_lookup_struct_deep': False,
           'is_abstract_type_name': True,  'resolve_identity': 'Handle'}
```

and `probe_scope_tier.py` on `blade/src/main.saw`:

```
Vector<PlacedSeg, GlobalAllocator>.copy  arg=PlacedSeg
   outside(merged) {'copy_tier': 'free'}
   inside(home)    {'copy_tier': 'abstract', 'module': ('<std>', 'vector')}
```

So inside the template's home scope the argument is an *unresolved name*, i.e.
`is_abstract_type_name` -> True -> every tier/conformance/bound/method-set
question fails closed. `_lend_instantiation_types` tests `name in src_ns.structs`
/ `.enums` with the type's own `struct_name`/`enum_name`, while the merged
namespace answers those names only through the deep/identity lookups — so it
copies nothing for a type declared in the entry module or another module.

M1 produces, wholly or partly: `type X is not Copy`, `type X has no method Y:
requires ..., and Z does not conform`, `type argument X does not satisfy bound
Y`, `map key type` / `set element type must be copyable`, `cannot compare` /
`cannot order`, `undefined function FailAlloc`, and their `undefined variable`
cascades. Four of those classes vanish entirely once the lend source is the
merged namespace; the rest shrink (762 -> 169, 973 -> 1, 392 -> 102 raw).

**M1a — the same-name face.** Where the argument's name also EXISTS in the home
scope, it silently re-resolves to the WRONG declaration and the diagnostic reads
absurdly:

- `argument 1 expects &var Slot<Int> but got &var Slot<Int>` —
  `examples/coro_generic_struct_method.saw` declares `struct Slot<T>`; the check
  of `UnsafeRef<Slot<Int>>.deref` runs in `std/compiler/frame.saw`'s scope where
  `Slot` is std's frame `Slot` (37 records, 21 instances, 9 files).
- `cannot assign Header to element of type Header` /
  `argument value expects Header but got Header` /
  `method copy should return Vector<Header,...> but returns Vector<Header,...>`
  — `examples/d144_private_type_identity.saw`, two modules with a private
  `Header` each (design 144's own test) (16 + 10 + 4 records).

M1a survives the merged lend source; it is a home-scope property, not a lend
property.

### M2 — the `borrows` lowering makes EVERY accessor a method-generic whose instance check refuses its own body

The place lowering (`place_transform.py:270-302`) rewrites a `borrows` method
into a method-generic over `__R` (the window's result type) returning `__R`,
with the body's `lend` rewritten to `return __window(...)`. At the overwhelmingly
common use — a statement-position window — `__R = Void`, so the substituted
clone is a `-> Void` function whose body is `return <Void-typed call>`, and
`_check_return` (`typechecker/statements.py:3364`,
`value_type and expected.kind == TypeKind.VOID`) refuses it:

```
function returns void but return has a value of type `Void`
  sawc/std/vector.saw:119   note: in the instantiation `Vector<CborLevel, GlobalAllocator>.[]`
```

**7,750 primary / 9,760 raw diagnostics, 45 instances, 15 templates, in 1,538 of
the 1,617 files — i.e. essentially EVERY program in the tree.** 12 of them are
in USER accessors, not std: `Pair.at`, `Ledger.at`, `Board.slot`, `Holder.run`,
`Bag.__lend_var_at_late`, `Table.__lend_var_at`, `Holder<String>.__lend_var_[]`
(`examples/place_window_exclusivity_boundary.saw:39`,
`examples/lend_var_generic_and_match.saw:42`, …).

Nothing today materializes these instances, which is why the class had never
been seen.

### M3 — a const-generic parameter is a VALUE the copier does not carry (DF-286c face 1), and it reaches STD

`undefined variable N` — confirmed, and WIDER than DF-286c's four examples: it
hits `sawc/std/fixedbuf.saw`'s own `FixedBuf<N>` / `FixedStringBuilder<N>`
(`init`, `capacity`, `get`, `set`) at every corpus instantiation, plus user
`Ring<8>`, `Ring<256>`, `slots<2>`'s `BITS`. 78 primary records, 20 templates,
16 files; its same-body cascade is the `method X should return Y but body has no
value` class (36 records, 0 primary).

### M4 — the associated-type return (DF-286c face 2)

`function getItem$1$StringBox should return Item but returns String`
(`examples/associated_type_generic.saw:31`) — 2 instances, 1 template. Confirmed
exactly as filed.

### M5 — the design-130 per-instance unsafe trigger (the safety surface)

118 records, 3 message shapes (signature-receives / signature-returns /
body-names), 4-7 templates, 23 files. The corpus shape is **not**
`Vector<UnsafePointer<Int8>>` but the coroutine frame's own `Slot<T>`:

- `Slot<UnsafePointer<Bool>>.{empty,of,put,take,clear,is_occupied}` —
  `examples/net_cancel_precise.saw`, `net_deinit_across_parks.saw`, … The type
  argument is an unsafe pointer because the COMPILER's frame synthesis put it
  there; no user wrote it.
- `Slot<Data>.value<UnsafePointer<Int8>>` — here the unsafe type is the WINDOW
  RESULT type `__R` from M2's lowering, i.e. it arrives from the place lowering,
  not from a user type argument at all.

Design 219 wave C's per-instance rule (`tierreq.py:414
_tier_check_instance_unsafe`) is a REFUSAL anchored at the CALL, not a
derivation — and it never fires for these, because there is no user call site:
the instantiations come from synthesized frames.

## 4. Twin tests (run, with output)

| twin | file | result |
|---|---|---|
| **M2 window twin** — concrete non-generic `Bag` with a `borrows []`, used at a statement window and a value read | `.build/scratch/census_splice/twin_window.saw` | **COMPILES AND RUNS**: `twin_window: 10 0`. Its own registry still carries 5 instances of the class. Plus 12 corpus USER accessors in green suite tests carry it. => class (b) |
| **M5 unsafe twin** — hand-written concrete `struct Holder { p: UnsafePointer<Bool>? }` with non-`unsafe` methods | `.build/scratch/census_splice/twin_unsafe.saw` | **REFUSED**, identical diagnostic: ``method `Holder.put` is not declared `unsafe`, but its signature receives a value of unsafe type (`UnsafePointer<Bool>`)`` => the check is the language rule; the question is whether an instance-arrived unsafe type triggers it |
| **NoMove twin** — `let moved = move value` on a NoMove by-value parameter | `.build/scratch/census_splice/twin_nomove.saw` | **REFUSED**, identical diagnostic: ``cannot `move` `value`: `Anchor` is `NoMove`, …`` => `Box<Anchor>.make`'s census diagnostic is tier (c) |
| **M1 scope twin** — the same instance checked with the merged namespace as lend source | `CENSUS_SCOPE=merged` over all populations | `alloc_custom_allocator.saw` 31 -> 5; `enum_payload_free_as_key.saw` 165 -> 13; corpus 12,506 -> 10,311 => the difference is environment, not judgment |
| **the programs themselves** | every population | all are green suite / bootstrap / battery members today, so every diagnostic below is against code that compiles and runs |

## 5. The class table (merged scope = the honest floor)

Tier key: **(a)** funnel defect · **(b)** second-judgment artifact · **(c)**
apparently real catch · **(env)** artifact of the ambient namespace at
phase-2 time · **OPEN** = undetermined.

| # | class (message shape) | primary raw (home / merged) | instances | templates | files | populations | mechanism | tier (evidence) |
|---|---|---|---|---|---|---|---|---|
| 1 | `function returns void but return has a value of type X` | 7750 / 7750 | 45 | 15 | 1538 | all six | M2 | **(b)** — twin runs; §1c has no skip at a `return` whose expected type arrived by substitution (skip 4 covers by-value PARAMETERS only) |
| 2 | `type X is not Copy; .copy() requires a trivially-copyable, Copy, or ExplicitCopy type` | 634 / 161 | 63 | 5 | 35 | blade, bladetests, examples | M1 (+ skip 3's gap) | **(env)** for the 473 that vanish; **(b)** for the residue — `copy_tier` says `free`/`implicit` in the merged ns and `abstract` in the home ns; skip 3 tests `== 'implicit'` only |
| 3 | `undefined variable X` | 78 / 78 | 53 | 20 | 16 | examples | M3 (const-generic `N`), plus M1 cascades | **(a)** DF-286c face 1, WIDER than filed (std `FixedBuf`/`FixedStringBuilder` included) |
| 4 | `method X is not declared unsafe, but its signature receives a value of unsafe type (Y)` | 58 / 61 | 13 | 4 | 23 | devtools, examples | M5 | **RULING OWED** — concrete twin refused too |
| 5 | `argument N expects X but got X` (identical spellings) | 33 / 37 | 21 | 5 | 9 | examples | M1a | **(env/b)** — user `Slot` vs std `Slot` re-resolution in the home scope |
| 6 | `method X is not declared unsafe, but its body names a value of unsafe type (Y)` | 29 / 31 | 11 | 7 | 14 | examples | M5 | **RULING OWED** |
| 7 | `method X is not declared unsafe, but its signature returns a value of unsafe type (Y)` | 24 / 26 | 6 | 2 | 13 | examples | M5 | **RULING OWED** |
| 8 | `cannot assign X to element of type X` | 14 / 16 | 6 | 2 | 8 | examples | M1a | **(env/b)** — `d144_private_type_identity` |
| 9 | `expected return type X but got Y (doesn't match Ok type … or Err type …)` | 7 / 10 | 6 | 2 | 8 | examples | M1a cascade | **(env/b)** |
| 10 | `argument X expects Y but got Y` | 7 / 10 | 5 | 2 | 8 | examples | M1a | **(env/b)** |
| 11 | `ambiguous Result auto-wrap … same Ok and Err type` | 5 / 5 | 2 | 2 | 3 | examples | authored form unambiguous abstractly | **(b)** — DF-286b class 5, unchanged; `generic_result_direct_consume.saw` is green |
| 12 | `function X should return Item but returns String` | 2 / 2 | 2 | 1 | 1 | examples | M4 | **(a)** DF-286c face 2, confirmed |
| 13 | `expected return type Result<Result<Int,Boom>?, ChannelError> but got Result<Int,Boom>` | 1 / 2 | 2 | 2 | 1 | examples | nested-Result auto-wrap at one instantiation | **(b)** — same family as 11 (`Channel<Result<Int,Boom>>`, conformance K47) |
| 14 | `undefined function boost` | 27 / 1 | 1 | 1 | 1 | examples | home scope lost a USER module's private sibling | **OPEN / (a)** — this is conformance row **K22**'s own shape (`examples/conformance/modules/embedmod/lib.saw:59` fails while line 31 in the same file succeeds) |
| 15 | `type X has no method Y: requires Z, and W does not conform` | 362 / 1 | 1 | 1 | 1 | examples | M1 | **(env)** for 361; residue `Vector<Handle>.sort` is M1 too (probe above) |
| 16 | `yield_now is a stdlib-internal cooperative-yield intrinsic and cannot be called bare` | 1 / 1 | 2 | 2 | 2 | examples | instance re-check of a std-internal-calling user module (K39/K22) | **(b)** — the gate is an authored-form rule |
| 17 | `cannot return NoCopy type Res without move in function run_and_return$1$Res` | 1 / 1 | 1 | 1 | 1 | examples | skip 4's mechanism at a RETURN | **(b)** — DF-286b class 6, unchanged; conformance **V47** pins the program legal |
| 18 | `cannot return NoCopy type Res? without move in method _take_value` | 0 / 1 | 1 | 1 | 1 | examples | same as 17, std side (`std/map.saw:164`) | **(b)** — a SECOND position of class 17's mechanism |
| 19 | `cannot move value: Anchor is NoMove …` | 0 / 1 | 1 | 1 | 1 | examples | `Box<T,A>.make`'s placement-move at a NoMove payload (`std/box.saw:45`) | **(c) REAL CATCH candidate** — twin refused; `examples/nomove_tier.saw:75` calls `try! Box<Anchor>.make(Anchor(n: 5))` and RUNS today |
| 20 | `cannot order values of type Handle with >: Handle does not conform to Comparable` | 2 / 1 | 1 | 1 | 1 | examples | M1 | **(env/b)** |
| 21 | `type argument X does not satisfy bound Y on struct Z` | 116 / 0 | — | — | 14 | examples | M1 | **(env)** — gone under the merged lend source |
| 22 | `map key type X must be copyable …` | 15 / 0 | — | — | 4 | examples | M1 | **(env)** |
| 23 | `set element type X must be copyable …` | 18 / 0 | — | — | 3 | examples | M1 | **(env)** |
| 24 | `cannot compare values of type Color with ==: Color does not conform to Equatable` | 5 / 0 | — | — | 4 | examples | M1 | **(env)** |
| 25 | cascade-only: `method X should return Y but body has no value` (36), `function X should return Y but body has no value` (5), `method X should return Y but returns Y` (4) | — | — | — | — | examples | cascades of 3, 8, 10 | **cascade** |

## 6. Mapping onto DF-286b's six classes and DF-286c's four faces

| filed | census verdict |
|---|---|
| DF-286b 1 — const-generic `undefined variable N` | CONFIRMED, wider: std's own `FixedBuf`/`FixedStringBuilder` are in it (row 3) |
| DF-286b 2 — design-130 trigger at an unsafe type argument | CONFIRMED and BIGGER: three message shapes, 118 records, and the real corpus carrier is the coroutine frame's `Slot<T>` + M2's window result type, not `Vector<UnsafePointer<Int8>>` (rows 4/6/7) |
| DF-286b 3 — `MapSlot<String,Cell> is not Copy` | PARTLY ENVIRONMENT: 62% of the class dies with the lend-source fix; the residue is real and skip 3 does not cover it (row 2) |
| DF-286b 4 — `Map.…_key_ref requires V: ExplicitCopy` (bounds filter) | **NOT a bounds-filter defect**: the registry's `_bounds_satisfied` agrees with the merged namespace (probe `probe_bounds.py`: `MapSlot<Int,Int> : ExplicitCopy -> True`); it is M1, and it vanishes under the merged lend source (row 15) |
| DF-286b 5 — ambiguous Result auto-wrap | CONFIRMED, unchanged (rows 11, 13) |
| DF-286b 6 — NoCopy return without `move` | CONFIRMED, and it has a SECOND position (std `Map._take_value`, row 18) |
| DF-286c face 1 — const-generic values | CONFIRMED (row 3) |
| DF-286c face 2 — associated-type return | CONFIRMED (row 12) |
| DF-286c face 3 — conditional-conformance bounds filter | **REFRAMED** — see DF-286b 4 above; the filter answers correctly |
| DF-286c face 4 — `-> T?` tail auto-wrap / invalid IR | **NOT VISIBLE to this instrument** (typechecker-only); zero diagnostics on `generic_optional_tail_return.saw` |

## 7. Is the class list closed?

Evidence that it is, at the margin: going from 1 program (A3's `hello.saw`,
5 classes with method-generics included) to 1,617 programs added classes only in
the first two populations. `examples/` alone contributed 20 of the 20 merged
primary classes; blade + blade tests + libs + devtools + selfhost, run
afterwards, contributed **zero classes that `examples/` did not already have**
(their 3 classes are all subsets). Six of the 20 classes have exactly one
instance in the whole tree, which is the shape of a saturated inventory rather
than a growing one. What is genuinely NOT bounded by this census: DF-286c face 4
and anything else that only manifests in EMITTED IR, and the 14
no-pristine-template method-generic instances.

## 8. Reproducing

```
cd /Users/shawn/Projects/sawlang
./.venv/bin/python .build/scratch/census_splice/census_run.py  examples   --workers 8
CENSUS_SCOPE=merged ./.venv/bin/python .build/scratch/census_splice/census_run2.py examples --workers 8
./.venv/bin/python .build/scratch/census_splice/final.py       # writes the JSONL + tables
```
Per-file worker: `census_worker.py OUT.json SRC.saw [-- flags]`. Wall time:
537 s for `examples/` at 8 workers per scope; the small populations ~45 s each.
