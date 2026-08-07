# Design 175 — investigation: `#lend_var`, flavor-aware borrows bodies

**Status: INVESTIGATION APPROVED (user, Aug 7: "an investigation in the
#exclusive pattern would be useful"). Probe-only — the product is a
feasibility report + effort estimate; implementation is a follow-up decision.
NAMING (user, Aug 7): **`#lend_var`** — the spelling ties to the
nomenclature the language already uses for this exact pair: `&` vs `&var`
at every borrow site, and std's `with_ref`/`with_var_ref` long-window
twins. It is also MORE precise than intent-flavored names: the model is
permission-based (a `&var` argument opens an exclusive window whether or
not a write lands), and "this is a var-lend" states what is true.
Rejected: `#exclusive` (too abstract), `#lend_for_write`/`#borrow_for_write`
(intent-flavored — overpromise a write). Final confirmation rides the
report, but `#lend_var` is the working spelling throughout.
Queue: probe-only and concurrent-eligible; dispatch when a slot frees;
findings compose with 171's probe round (shared places surface).**

## The problem it solves

A `borrows` accessor has ONE body serving both window flavors, and the body
cannot see which is coming — but the COMPILER can: every use site's flavor is
static (a read = shared window, a write/`&var` = exclusive). DF-165c is the
cost: a CoW type must separate storage BEFORE lending a writable place, so
`Data.[]` declared `&var self` and gates unconditionally — and every pure
READ through `d[i]` now demands exclusivity. That broke three real read
sites in one afternoon (irdet's `same_bytes`, both serde169 encoders), each
written by an author reaching for the natural spelling.

## The mechanism (to be validated, not assumed)

A compile-time constant, legal ONLY inside a `borrows` body, in the
`#file`/`#line` magic-literal family:

```saw
public func [](&self, i: Int) borrows -> UInt8 {
    if #lend_var {                    // per-specialization constant
        self.separate_if_shared()     // the CoW gate — write copy only
    }
    if i >= self.length { panic("Data.[]: index out of range") }
    lend self.storage[self.offset + i]
}
```

The accessor compiles as TWO specializations (the const-generic precedent:
folded before mangling, branch statically pruned). The shared copy never
mutates and is honestly callable through `&self`/`let` roots; the write copy
runs the gate and takes the exclusive receiver it always needed. No caller
ceremony — the use site already carries the information.

## Probe matrix

1. **Checker architecture:** can mutation-legality be judged PER
   SPECIALIZATION (the false copy prunes the mutating branch BEFORE the
   `&self`-may-not-mutate check runs; the true copy gets `&var`-receiver
   semantics)? Where in the pass order would specialization have to happen,
   and does the design-146 "borrows changes what &self means" rule already
   carry half of this?
2. **Mangling + one-definition:** two symbols per flavored accessor (the
   `Dual_mix$2$T$U` precedent) — irdet/reemitdiff determinism, `--emit-docs`
   presentation (one accessor, note the flavors), frame layout if the
   accessor is reached from a coro context.
3. **Composition:** conditional lends (`borrows -> T?`) — does the absent
   path specialize too; epilogues per copy; LIFO window nesting; match-arm
   payload lends; a generic accessor with a flavored body; place borrows
   charging the root identically in both copies.
4. **The pilot on paper:** `Data.[]` rewritten under the mechanism — does
   `bytes[i]` on a `let`/`&Data` compile again, does the write path still
   gate, do the three formerly-broken sites compile as originally written,
   and does `get(i)` remain the explicit shared read (yes — the synonym
   ruling DF-146j is unaffected; `[]`-shared and `get` converge, which is
   the point).
5. **Scope fences:** `#lend_var` outside a borrows body = clean error;
   an accessor that never mentions it compiles ONCE exactly as today (no
   code-size tax on the unflavored majority); interaction with `&var self`-
   DECLARED accessors (always-true constant, or an error for redundancy?).
6. **Alternatives worth one paragraph each in the report:** the Swift-style
   two-body `_read`/`_modify` split (more declaration surface, no magic
   constant), and doing nothing (the `get`/`[]` pair as permanent idiom —
   what today's three breakages say about that).

## Deliverables

Report appended to this brief: feasibility verdict per probe, the
recommended spelling with the naming rationale restated, effort estimate,
and a go/no-go recommendation. DF-175x findings for anything the probes
trip over. NO compiler changes — prototypes under .build/scratch/ only.

---

# REPORT (Aug 7, probe-only agent; no sawc/ changes)

**VERDICT: GO, conditional.** `#lend_var` is feasible and cheaper than the
brief assumed — but NOT for the reason the brief gives, and NOT before a
soundness hole the probes turned up is closed. Two corrections to the
brief's premises up front, because everything else follows from them:

1. **The const-generic precedent the mechanism was pitched on does not
   exist.** "Folded before mangling, branch statically pruned" is true of
   *codegen* and false of *checking*: the typechecker checks a generic body
   ONCE, abstractly, with an empty const-param environment
   (`typechecker/expressions.py:4027-4035`), and per-instantiation constant
   evaluation happens later. Probe `p175_constgen_assert_prune` proves it —
   a `static_assert(N > 4)` inside an `if N > 4` branch FIRES for the `N=2`
   instantiation. There is no "check this body under a constant environment"
   machinery to reuse.
2. **It does not matter, because `#lend_var` does not need one.** The
   specialization set is fixed at `{shared, exclusive}` and known with no
   caller information at all — unlike a const generic, whose set is
   caller-derived. So the fold is a SOURCE-LEVEL DUPLICATION in the
   declaration lowering that already runs before the typechecker, and each
   copy is then checked as an ordinary method by machinery that needs no
   changes. That is a much smaller feature than "judge mutation-legality per
   specialization" sounds.

## What the pipeline actually is (the load-bearing finding)

`borrows` is **two source-to-source transforms bracketing the typechecker**,
not a checker feature:

| # | pass | file | entry |
|---|---|---|---|
| 2 | declaration lowering | `sawc/place_transform.py` | `transform_places()` :104, called from `sawc/sawc.py:54-59` **inside `parse_source`** |
| 3 | typecheck pass 1 | `sawc/typechecker/` | accessor is by now an ordinary generic method |
| 4 | use-site lowering | `sawc/place_uses.py` | `transform_place_uses()` :74, `sawc/sawc.py:1054-1073` |
| 5 | `uncheck()` + typecheck pass 2 | `place_uses.py:108` | |

The declaration lowering rewrites
`func [](&self, i: Int) borrows -> T` into
`func []<__R>(&self, i: Int, __window: (&var T) sync -> __R) sync -> __R`,
forces `is_sync = True`, and sets `place_self_by_pointer = True`. The flavor
is decided in `place_uses._chain_is_exclusive` (:653-672) and stamped as the
bool `MethodCall.place_window_exclusive` (`ast_nodes.py:1310`), which is OR'd
into `receiver_mutable` at `typechecker/expressions.py:7403-7435`.

**Pass 2 is the seam that makes `#lend_var` cheap.** The use-site lowering
already runs between two full typechecks, already computes the flavor, and
is already followed by a re-check. So an exclusive use site can be retargeted
at a different method and pass 2 will type-check the retarget honestly.

## Probe-matrix verdicts

### 1. Checker architecture — **FEASIBLE, by duplication, not by per-specialization checking**

Mutation-legality cannot be judged per specialization by the typechecker as
it stands, and does not need to be. The recommended shape: in
`place_transform._lower`, an accessor whose body mentions `#lend_var` is
emitted as TWO methods —

- the **shared** copy keeps the authored `&self`, `#lend_var` folds to
  `false`, the gate branch is pruned;
- the **exclusive** copy is a synthesized sibling with `self_mutable = True`,
  `#lend_var` folds to `true`, the gate branch is kept.

Both then reach the typechecker as ordinary methods and are checked
independently by the existing `&self` / `&var self` rules. Nothing about the
"&self-may-not-mutate" check has to become specialization-aware; the false
copy simply has no mutation left in it to reject.

Does design 146's "borrows changes what `&self` means" rule carry half of
this? **Yes, and precisely the half the brief hoped.** The receiver is
already passed BY POINTER for a borrows method
(`ast_nodes.self_by_pointer` :42-57; IR shows `ptr %self`), so the exclusive
copy's mutating prologue genuinely mutates the caller's value — verified at
runtime, not just in the IR (`p175_mutate_lands`: 5 accessor calls, `hits`
reads 5). The other half — a rule that the polymorphism reaches the `lend`
and nothing else — is **documented but not enforced**; see DF-175a.

The target semantics are expressible in today's language: probe
`p175_hand_specialized` hand-writes exactly the two methods the transform
would synthesize and behaves correctly on every axis (shared read through a
`let` root, 0 separations; exclusive write separates once; second write does
not re-separate). `p175_pilot_let_write` shows the exclusive twin already
produces the *right* diagnostic for a refused write, with no new error text
to author:

```
error: cannot open an exclusive place window on immutable variable `frozen`
hint: consider using `var` instead of `let` to make it mutable
```

### 2. Mangling + one-definition — **NO WORK REQUIRED**

The brief anticipated "two symbols per flavored accessor". The compiler
already emits **N symbols per accessor**, keyed on the window's result type
`__R`. From `p175_baseline`:

```
define i64  @"Grid_[]$1$Int"(ptr %self, i64 %i, { ptr, ptr, ptr } %__window)
define void @"Grid_[]$1$Void"(ptr %self, i64 %i, { ptr, ptr, ptr } %__window)
```

The flavor is NOT part of that key: `p175_symbol_key` puts a shared use
(`look(&g[0])`) and an exclusive use (`poke(&var g[1])`) at the same
`__R = Void` and both resolve to the single `Grid_[]$1$Void`.

Because the recommendation makes the exclusive copy a distinct METHOD NAME,
`mangle_method` yields distinct symbols with **zero mangler change** —
no new key component, no ordering question, so no new determinism surface
for irdet/reemitdiff (the corpus already carries multi-symbol accessors).

Frame layout: `_lower` forces `is_sync = True` on every accessor, so an
accessor never becomes a coroutine frame and `--emit-frame-layout` is
unaffected. A window inside a coroutine works in both flavors across
suspends (`p175_coro_window`, spawned tasks, prints `13 23`).

`--emit-docs`: a `&self` borrows receiver reports `"self": "window"`
(`docs_emit.py:425-442`), and the authored declaration is unchanged under
`#lend_var`, so the accessor still renders once. The synthesized twin must be
suppressed — one filter. (Adjacent nit, DF-175c below: a `&var self` borrows
accessor reports `"self": "borrows-var"`, indistinguishable from a plain
`&var self` method.)

### 3. Composition — **ALL GREEN, one pessimization**

Everything the brief asked about already works with a mutating prologue, so
duplicating the body preserves it:

- **conditional lend** (`p175_cond_lend`): the prologue runs on BOTH paths;
  only post-`return None` code is present-path-only (`gates=2 hits=1`). The
  absent path therefore specializes too, and an author's gate placed before
  the presence test will separate storage on a MISS. That is the author's
  call to make (put the gate after the test), but it deserves a line in the
  docs.
- **LIFO nesting / epilogues** (`p175_nested_windows`): correct in both
  flavors.
- **match-arm payload lend** (`p175_match_payload_lend`, DF-146d): works in
  both flavors with a prologue; the write lands (`103`).
- **generic accessor** (`p175_generic_accessor`): both flavors over two
  instantiations. The specialization set becomes (type args) × (flavor),
  which the distinct-method-name approach handles for free.
- **root charging**: unchanged — the window's receiver is the container, so
  the existing design-8/10 machinery applies identically to both copies.
  (`p175_root_charge` is correctly rejected, but with DF-146l's known bad
  message — "cannot copy value of type `Bag`". Pre-existing, already filed.)
- **PESSIMIZATION (new):** an accessor that FORWARDS another accessor's place
  (`lend self.inner[i]`) works (`p175_nested_forward`), but `lend X` lowers
  to `__window(&var X)`, so the inner accessor is always reached through a
  `&var` argument and would always select the EXCLUSIVE specialization — even
  from the outer accessor's shared copy. Sound but pessimizing: a shared read
  of a nested CoW would separate. Fixable (propagate the enclosing copy's
  flavor into the lend's inner place — `place_uses` knows both), but it is
  extra scope, and it should be stated as a known v1 limit if deferred.

### 4. The `Data.[]` pilot — **works on paper; the gate reads the true refcount**

The pilot's gating question was whether a CoW gate can even function inside a
borrows body: if the receiver arrived by value it would RETAIN the `Arc` and
`strong_count()` would never report 1, making the write copy separate on
every write and the shared copy a lie. **It reads the truth**
(`p175_cow_refcount`): one owner → every receiver kind observes 1; a copied-out
`Arc` → 2. This matters because `data.saw:520-523` already warns that binding
the Arc out would retain it.

Worked patch sketch — `sawc/std/data.saw:205-214` becomes:

```saw
    public func [](&self, index: Int) unsafe borrows -> UInt8 {
        if index < 0 || index >= self.length {
            panic("Data.[]: index out of range")
        }
        if #lend_var {
            if not self._make_ready(self.length) {
                panic("Data.[]: allocation failed")
            }
        }
        let bytes = self.byte_ptr() as UnsafePointer<UInt8>
        lend bytes[index]
    }
```

Three things make this land cleanly:

- `_make_ready` is `&var self` (:555) and appears ONLY under the constant, so
  the shared copy never names a `&var self` method and checks as `&self`.
- `byte_ptr` is `&self unsafe` (:406), legal in both copies.
- the shared copy skipping `_make_ready` is safe: the bounds check already
  proved `length > 0`, hence storage exists.

Answers to the pilot's four questions: `bytes[i]` on a `let`/`&Data` compiles
again (the shared copy is `&self`); the write path still gates (the exclusive
copy keeps `_make_ready`); the three formerly-broken sites compile **as
originally written** — `p175_data_let_read` is today's failure
(`cannot call &var self method [] on immutable variable a`) and the shared
copy is exactly the `&self` accessor that failure asks for; and `get(i)`
remains the None-returning twin.

**DF-146j stays coherent, and gets MORE coherent.** DF-146j ruled `get` is the
borrows synonym of `[]` returning `V?`. Under `#lend_var` the two converge on
the flavor axis instead of diverging: `[]` panics, `get` returns `None`, and
BOTH are shared-readable and exclusive-writable — the ratified
panic-vs-None asymmetry is preserved and the accidental
"`get` = the only shared read" asymmetry that DF-165c forced disappears.
`Data.get` is currently a plain `-> UInt8?` value method (:220-228), not a
place; converting it to `borrows -> UInt8?` is DF-146j's own scope, not this
brief's, and the two compose.

### 5. Scope fences — **CLEAN, and the fence is nearly free**

- `#lend_var` today is already a clean lex error naming the three legal
  directives (`p175_hash_lex`), so the lexer is one table entry
  (`lexer.py:544`) and the magic-literal family (`SourceLocationLiteral`,
  `expressions.py:210-229`) is the shape to copy.
- **"Outside a borrows body = clean error" costs ~10 lines.** Every LEGAL
  occurrence is folded away pre-typecheck by `place_transform`, so a
  typechecker `visit_` for the node that *always* errors is exactly right —
  anything reaching the typechecker is by construction misplaced.
- An accessor that never mentions the constant is untouched: one method, the
  same per-`__R` symbol set as today. **No code-size tax on the unflavored
  majority**, by construction.
- **`&var self`-DECLARED accessors: recommend a clean ERROR, not an
  always-true constant.** In a `&var self` accessor every use site is already
  exclusive, so the constant is always true and the branch always live; a
  silently-always-true constant reads as a live decision and would mislead.
  Error text should point at the fix ("`#lend_var` is always true in a
  `&var self` accessor — declare `&self` to get both specializations").

### 6. Alternatives

**Swift's `_read`/`_modify` two-body split.** More declaration surface, no
magic constant, and it makes the two specializations first-class instead of
derived — which also solves DF-146k (a shared-only accessor is one that
declares only `_read`, giving `Set` an element accessor at last). Against it:
it duplicates the bounds check and the lend target in every accessor that
does not need the split, it is a second declaration grammar for `borrows`
rather than an extension of the one that exists, and the common case (the
gate is two lines inside an otherwise identical body) is exactly where a
whole second body reads worst. `#lend_var` is the smaller language change;
the split is the more general one. If a THIRD flavor-sensitive need ever
appears, the split is the right retreat.

**Doing nothing** (the `get`/`[]` pair as permanent idiom). The cost is on
the record and it is not theoretical: three real read sites broke in one
afternoon — irdet's `same_bytes` and both serde169 encoders — each written by
an author reaching for `d[i]`, the natural spelling, on a `let` binding. The
failure is a compile error rather than a silent bug, and `get(i)!` is a
mechanical fix, so the harm is bounded. But the rule a user has to learn is
"`[]` on `Data` needs a `var` and may copy, unlike `[]` on `Vector`" — a
per-type exception to the places model, which is the thing the places model
exists to avoid. Note that `Vector` never hits this and `Data` only does
because it is CoW; the brief is right that one type does not justify the
change on ergonomics alone. What tips it is that the FIX is small and that a
second CoW type is a matter of time (a CoW `String` slice, a CoW buffer in
std or user code) — the tracker already says "if a second CoW type ever wants
a subscript, splitting `borrows` is the fix".

## DF-175 findings

- **DF-175a (COMPILER, P0-class, filed — INDEPENDENT of this brief and a
  PREREQUISITE for it): a `&self` method may mutate its receiver.** Design
  146 and the skill both state that a field write in a `&self` method is a
  hard error, and `examples/errors/var_ref_into_shared_self.saw` says it
  holds "including the prologue and epilogue of a borrows body". It does not.
  Only the `&var self.<field>` PROJECTION form is checked
  (`typechecker/expressions.py:863-889`); DIRECT field assignment and calling
  a `&var self` method are both unchecked. `_assign_target_immutable_struct_root`
  (`statements.py:1500-1533`) deliberately stops at `SelfExpr`. Two distinct
  consequences, both live today:
  - in a PLAIN `&self` method, `self.hits = self.hits + 1` compiles and is a
    **silent no-op** — the write lands in the by-value receiver copy and is
    discarded (`p175_plain_self_write_lands` prints `hits = 0` after two
    calls; same on a NoCopy receiver, `p175_plain_self_write_nocopy`). This is
    exactly the DF-146b class of bug that the `&var self.<field>` check was
    added to close, through the door that check does not cover.
  - in a `&self` BORROWS body the receiver is by pointer, so the same write
    **lands** — and a pure read through a shared window on an IMMUTABLE root
    mutates it. `p175_shared_window_mutates_let`: two reads of a `let frozen`
    print `hits through a let root = 2`, and it is visible through a `&Grid`
    parameter too. `let` immutability is not holding here.

  Repros: `.build/scratch/p175_mutate_in_shared_body.saw`,
  `p175_mutate_lands.saw`, `p175_mutate_shapes.saw`,
  `p175_plain_self_write_lands.saw`, `p175_plain_self_write_nocopy.saw`,
  `p175_shared_window_mutates_let.saw`, `p175_varref_in_borrows.saw`
  (the checked form, for contrast).

- **DF-175b (LANGUAGE/SOUNDNESS, filed — the risk `#lend_var` inherits):
  a SHARED window is enforced by use-site classification, not by the
  window's type.** The declaration lowering gives every accessor ONE window
  closure shape, `__window: (&var T) sync -> __R` (`place_transform._lower`),
  so a window classified shared still receives a MUTABLE reference to the
  element. Nothing in the callee or in the closure's type prevents a write;
  soundness rests entirely on `place_uses._chain_is_exclusive` (:653-672)
  classifying every use site correctly. Today that is merely untidy, because
  `Data.[]` gates unconditionally and cannot be caught out. Under `#lend_var`
  it becomes the whole safety property of the shared copy: one misclassified
  use site writes through storage a sibling `Data` shares, and value
  semantics break silently with no diagnostic anywhere. **Recommended fix,
  and it is small: give the shared specialization a genuinely immutable
  window, `__window: (&T) sync -> __R`** (with `_window_expr` emitting `&`
  instead of `&var`). Then a write inside a shared window fails to typecheck
  by construction rather than by classification, and every existing accessor
  is retroactively hardened. DF-175a is a live instance of this class.

- **DF-175c (DIAGNOSTIC/DOCS, minor): `--emit-docs` cannot distinguish a
  `&var self` borrows accessor from a plain `&var self` method.** A `&self`
  borrows receiver correctly reports `"self": "window"`, but the `&var self`
  one reports `"self": "borrows-var"` — the same value a non-borrows
  `&var self` method gets, so the window-ness is only recoverable from the
  signature string (`docs_emit.py:425-442`). Probe:
  `p175_cow_refcount.saw --emit-docs-all`. Cheap to fix
  (`"window-var"`), and it matters more once accessors are flavored.

- **DF-175d (ERGONOMICS, minor): a NAMED borrows accessor is not an
  assignment target.** `c.slot(1) = 99` is a parse error ("Invalid assignment
  target") while `v[i] = fresh` works, so whole-element replacement is
  available through the subscript spelling only; the workaround is a `&var`
  argument (`set_to(&var c.slot(1), 99)`). Same family as DF-146n
  (`m[k]! = v`) — assignment-target grammar has not caught up with places.
  Repro: `p175_hand_specialized.saw` (first version).

## Effort estimate

Six units. Unit 1 is a prerequisite that stands on its own merits; units 2-4
are the feature; 5-6 are surface.

| unit | work | size |
|---|---|---|
| 1 | **DF-175a**: extend the `&self`-mutation check to direct field assignment and to `&var self` method calls on `self`; error oracles | S-M, and a soundness fix worth landing regardless |
| 2 | the constant: lexer table entry, AST node, parse, typechecker `visit_` that always errors (the scope fence) | S (~150 lines + tests) |
| 3 | `place_transform`: detect, duplicate, fold, prune, `self_mutable = True` on the twin; reject `#lend_var` in a `&var self` accessor | **M — the real work** (~250-350 lines) |
| 4 | `place_uses`: retarget an exclusive use at the twin; verify pass-2 re-check resolves it | S-M (~60-100 lines); the interaction with `uncheck()`/pass 2 is the risk |
| 5 | `docs_emit` twin suppression (+ DF-175c) | XS |
| 6 | `Data.[]` migration, restore the three sites to their original spelling, spec/skill/README, tracker | M |

Plus **DF-175b's `&T` shared window** — small in code (~30 lines) but it will
surface every existing use site that is classified shared and writes anyway.
That is a feature, but budget for the fallout; it is the one item whose cost
is genuinely unknown before it is tried.

Overall: **one brief of six units**, comparable to design 146 in shape but
smaller in each part, with the caveat that units 1 and DF-175b carry
unbounded-until-attempted migration tails.

## Go / no-go

**GO**, in this order, and stop if unit 1 does not go cleanly:

1. Land **DF-175a** first, on its own, as a soundness fix. It is a live
   silent-write bug in plain `&self` methods independent of anything here,
   and `#lend_var`'s shared copy is only as trustworthy as that rule.
2. Land **DF-175b's `&T` shared window** next, so shared-ness becomes a
   type-level guarantee before anything depends on it.
3. Then `#lend_var` (units 2-6), whose remaining work is mostly the
   duplication in `place_transform`.

If 1 or 2 turns out to have a long migration tail, `#lend_var` should wait
rather than be built on classification alone — the failure mode it would then
have (a silent write through shared CoW storage) is worse than the ergonomic
problem it solves (a compile error with a mechanical fix).

**Naming: `#lend_var` CONFIRMED.** The probes back the rationale rather than
just restating it. The exclusive specialization is literally the one whose
receiver becomes `&var self` and whose window hands out `&var T`; the shared
one is the `&self` / `&T` twin. The constant therefore names the same
distinction `&` vs `&var` names at every borrow site and `with_ref` vs
`with_var_ref` names in std — and it states a PERMISSION, which is what the
use site actually decides, rather than an intent to write, which no probe can
observe and which `p175_symbol_key` shows the compiler never asks about
(`poke(&var g[1])` opens an exclusive window whether or not `poke` writes).

## The one thing most likely to kill it

**DF-175b.** Not the checker architecture, which turned out to be
accommodating, and not mangling, which needs no work at all — but the fact
that "shared" is today a use-site classification rather than a property of
the window's type. `#lend_var` promotes that classification from a tidiness
question to the sole guarantee protecting a CoW type's value semantics, and
DF-175a proves the seam is not currently airtight. Close both and the feature
is small and safe; close neither and it is a silent-corruption generator
wearing an ergonomics improvement.

## Probe index (`.build/scratch/`, driver `probe_run175.py`)

`p175_baseline` · `p175_mutate_in_shared_body` · `p175_mutate_lands` ·
`p175_mutate_shapes` · `p175_mutate_plain_self_method` ·
`p175_plain_self_write_lands` · `p175_plain_self_write_nocopy` ·
`p175_shared_window_mutates_let` · `p175_varref_in_borrows` ·
`p175_var_self_let_root` · `p175_data_let_read` · `p175_data_get_read` ·
`p175_dead_branch_typecheck` · `p175_constgen_assert_prune` ·
`p175_constgen_two_insts` · `p175_symbol_key` · `p175_hash_lex` ·
`p175_cond_lend` · `p175_nested_windows` · `p175_generic_accessor` ·
`p175_match_payload_lend` · `p175_root_charge` · `p175_coro_window` ·
`p175_cow_refcount` · `p175_hand_specialized` · `p175_pilot_let_write` ·
`p175_nested_forward`
