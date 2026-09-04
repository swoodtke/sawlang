# Design 264 — by-value closure parameters are owned by the body; std visitors lend

**Status:** RULED Sep 4 2026 (user), authored same day. Closes DF-299c and
DF-291b; retires the DF-146j-family alias at the visitor position by
construction. Supersedes nothing — this is the contract DF-299c found missing.

## The two rulings (user, Sep 4)

**Ruling A — ownership.** A by-value closure parameter IS OWNED BY THE BODY,
on exactly the terms a named function's parameter is: the body owes it a
scope, it is released at body end unless moved into a new owner, and a caller
passing one TRANSFERS it. This is uniform with `methods.py`'s existing
`_needs_cleanup` -> `_register_cleanup` contract and with DF-218h's deferred
move captures ("a deferred-move capture becomes an OWNED local of the body").

**Ruling B — std visitors lend.** Visiting is observation: every std visitor
parameter that today takes an owning value BY VALUE converts to a reference.
The six (DF-299c's census, compile+run evidence at 5853e403):

| API | today | becomes |
|---|---|---|
| `Map.each` | `body: (K, V) -> Void` | `body: (&K, &V) -> Void` |
| `Map.each_key` | `body: (K) -> Void` | `body: (&K) -> Void` |
| `Map.each_value` | `body: (V) -> Void` | `body: (&V) -> Void` |
| `Set.each` | `body: (T) -> Void` | `body: (&T) -> Void` |
| `Vector.sort_by` | `compare: (T, T) -> Ordering` | `compare: (&T, &T) -> Ordering`, and the `T: Copy` bound DROPS (it existed only to license the copy reads; the swap is byte-level) |
| `Vector.fold` | `combine: (Acc, &T) -> Acc` | **UNCHANGED** — the by-value accumulator is the legitimate use of Ruling A: genuine ownership threading, moved in and moved back out |

Vector's visitors (`each`/`map`/`each_indexed`) already lend `&T` and are the
idiom the six converge on. After B, every by-value closure argument left in
std genuinely transfers — which is what makes A's codegen release safe.

## Why B precedes the release (the reverted attempt's finding)

The codegen half alone fixes all six leaks and then traps: `Map.each`'s
`body(move k, move v)` over `if let v = self._get_value(i)` hands a RETAINED
value at the Copy tier and a NON-RETAINED ALIAS at ExplicitCopy (DF-146j's
family at the visitor position) — releasing the parameter frees what the map
still owns. The trap is CONTENT-dependent (string literals clean over 20k
encodes; heap strings fatal on the second). Lending dissolves it: no
ownership handed out, nothing to wrongly release. The reverted-but-proven
codegen fix is preserved under `.build/scratch/sawc_working/`; the probe
suite and arithmetic model under `.build/scratch/` (`notes_df291b.md`,
`f*/g*/s*/p*.saw`).

## Units, in landing order

**U0 — conformance rows FIRST (obligation 3), landing with the unit that
flips each behavior** (soundness-pair precedent: rows + fix in one commit so
the citations lane stays green).
Rows owed: (a) a by-value closure parameter is released exactly once at body
end, body-never-mentions-it face included; (b) `move` into a new owner
transfers — still exactly one release; (c) escaping and non-escaping faces
release identically; (d) visitors LEND — an ExplicitCopy (and a NoCopy where
constructible) map/set is visitable, contents observed in place, zero
copies/retains, mutation of the visited container inside the body is a static
exclusivity error; (e) `fold` threads its accumulator: N elements, one final
owner, one release. INDEX.md rows for each.

**U1 — the std conversion (Ruling B) + in-tree migration, one commit.**
- `sawc/std/map.saw`: `each`/`each_key`/`each_value` lend. The bodies
  restructure off the payload-read-then-`move` spelling onto a borrowing
  read (the DF-146d borrowing-match-arm lend over the slot, or a `borrows`
  accessor — agent's pick, whichever is idiomatic Saw; if the lending
  spelling hits a compiler defect, STOP the unit and file, never work
  around). Internal callers migrate in the same commit: `keys()`/`values()`
  (`{ [&var out] k in try! out.push(move k) }` becomes a lend + copy-tier
  read or spelled `.copy()` — K there is already Copy-bounded).
- `sawc/std/set.saw`: `each` follows through the `each_key` delegation.
- `sawc/std/vector.saw`: `sort_by` comparands lend; `T: Copy` bound removed;
  doc comments updated (they currently promise "copies").
- `sawc/std/json.saw`: `_write`'s Object arm (`fields.each({ ... k, v in`)
  migrates.
- Corpus: `examples/json_map_keys.saw`, `examples/optional_generic_map.saw`,
  `examples/vector_sort_by.saw`, plus whatever the suite surfaces (the suite
  is the oracle; the consumer sweep below found no callers outside std +
  examples).
- Residual std audit closing the unit: grep every remaining `_get_value` /
  payload-read consumer in map.saw and every std closure call site for a
  by-value owning argument; after this unit the set must be exactly
  {`Vector.fold`'s accumulator} — assert that in the landing note.
- Doc surfaces: LANGUAGE_SPEC + saw-lang skill + README where visitor
  signatures appear (saw-docs skill for prose).

**U2 — the codegen release (Ruling A).** One funnel: the by-value arm of
closure parameter setup in `codegen/closures.py` (~line 344) registers owning
parameters for scope cleanup, mirroring `methods.py`'s
`_needs_cleanup` -> `_register_cleanup` exactly — the reverted attempt is the
reference implementation. Regression pins (all from the DF-299c evidence,
each a countable refcount witness, not RSS): the fold repro (5 -> 2, deinit
runs); the `Map<String, Arc<Res>>` triple visit (5 -> 9 -> 13 -> 17 -> flat);
the heap-string JSON object encode loop (the content-dependent trap's exact
shape, now clean); the never-mentions-it, escaping, and move-into-new-owner
faces. Trivial-tier parameters stay zero-cost (no spurious cleanup
registration).

**U3 — the class sweep (obligation 4) + consumer verification (obligation
2).** Census every corpus closure with a by-value owning parameter
(compile+run witnesses, not grep-only), before/after U2: each site must show
leak -> exactly-one-release with no new double free. Verify no caller
anywhere still hands a closure a non-retained alias (only std's payload-read
spelling could mint one; U1 removed it — prove the negative). `Thread.spawn`
brace confirmed still outside this path (measured edge fact — pin it).

## Consumer sweep (obligation 2, lead, Sep 4 — grep basis)

The contract flips are (1) six std signatures by-value -> by-reference and
(2) every by-value closure parameter corpus-wide changing from leak to
release-at-body-end. For (1): callers of the six in tree are std itself
(`keys()`, `values()`, `json._write`, `Set.each` delegation), three example
files (`json_map_keys`, `optional_generic_map`, `vector_sort_by`), and
NOTHING in blade/libs/devtools/rt (grep over all tracked .saw, Sep 4). For
(2): no code can legitimately rely on a leak; the only unsound reliance would
be a caller passing a non-retained alias, which only std's `_get_value`
spelling produced — removed by U1, proven absent by U3. sos migrates at the
next pin bump (visitor closures gain `&` sigils; leaks stop; nothing else).

## Gates, sequencing, ceremony

- Per-commit: full suite + freestanding (both arches). Terminal: FULL battery
  (24 stages). Suite-lock SPLIT form (sandboxed worktree).
- U1 lands before U2 in separate commits — U2's safety depends on U1, and the
  ordering is load-bearing history if either reverts.
- DF range for this dispatch: **DF-301a+**. New findings filed with mechanism
  named (obligation 4); a compiler defect blocking a unit STOPS it.
- Closes IN PLACE in todo.md: DF-299c (U2 lands), DF-291b (fold's leak gone —
  point its entry at U2's commit). DF-299b/DF-299d are NOT this brief's.
- Version: BREAKING std surface — the lead cuts **0.7.0** at integration
  (0.6.0's flow); the agent does NOT touch version.py.
- Out of scope, recorded: a `&var V` mutate-in-place visitor (separate brief
  if sos/blade demand it); DF-299b (value-arm checkpoint); DF-299d.

## U3 — the class sweep and consumer verification, as run (Sep 4)

Method: an INSTRUMENTED compiler rather than grep. `_generate_closure` and
`_register_cleanup` were monkeypatched to record every registration firing at
the design-264 parameter arm, keyed to the closure literal's line:column — so
the census predicate IS the compiler's own
`_needs_cleanup(param_saw_types[i]) and kind != REFERENCE`, not a reading of
it. All 2306 tracked `.saw` files (minus `examples/errors/`, which never reach
codegen) were compiled under it; every one returned rc=0.

THE POPULATION IS 17 SITES IN 7 FILES, all in `examples/`: four in
`arc_forward_generic_method.saw` and three in `plain_type_generic_method.saw`
(a `String` read out of a receiver or field, handed to a generic `body`/`f`),
one in `funcpointer226_call.saw` (the design-226 BARE emission, no env), and
nine in the conformance rows V71 and V73-V76. Every site compiles rc=0, runs
rc=0, matches its recorded output, and shows exactly one release. ZERO rows
came from `sawc/std/`, `sawc/rt/`, `blade/`, `libs/`, `devtools/`, `selfhost/`,
`tools/` or `tests/` — and zero from `V72_std_visitors_lend.saw`, which is the
positive proof that U1's six conversions took effect.

BEFORE/AFTER, same probes under a scratch compiler carrying U1's
`closures.py`: the field-read shape climbed to rc 2003 over 2000 calls and now
holds flat at 3; the basic shapes read 2/3/4/5 with no `drop` at all and now
return to base with one `drop`. Map visits are flat 3/3/3 where the brief
records 5 -> 9 -> 13 -> 17.

NO DOUBLE FREE, no new crash, no SIGTRAP anywhere — including the std
consumers under load: 5000 `keys()`/`values()` rounds, 20000 heap-string JSON
object encodes (the content-dependent trap's exact shape) and 5000 `Set.each`
walks, all with flat counts and intact text.

THE NEGATIVE ON NON-RETAINED ALIASES IS PROVEN three ways. Every closure-typed
parameter declared in `sawc/std/` + `sawc/rt/` was enumerated (there are no
function-typed struct fields and no function-type aliases to hide one): the
by-value OWNING set is exactly {`Vector.fold`'s accumulator}. Every call site
of those parameters lends (`body(&k, &v)`, `&buf[i]`, a `&var` payload or a
pointer). And `_get_value`/`_key_at` survive nowhere in `sawc/` but the comment
that records their deletion. `data.saw`, `cbor.saw` and `channel.saw` declare
no closure-taking API at all.

`Thread.spawn { }` CONFIRMED outside this path, mechanically: the census probe
over a spawn brace capturing an `Arc` yields zero rows, because the bracket
list is a CAPTURE list and not a parameter list. The refcount returns to 1
after each join with one deinit.

TWO PRE-EXISTING DEFECTS FOUND AND FILED, neither this brief's: DF-301a (an
ICE on a suspending function whose closure parameter type is a generic-struct
instantiation — verified byte-identical with U1's `closures.py`, and no corpus
site has the shape) and DF-301b (a closure literal at an ANNOTATED `let` does
not infer its parameter type, then reports the mismatch against an `Int`
fallback — hit while writing V75, whose spelling works around it).

KNOWN GAPS, recorded rather than papered over: `examples/errors/` was audited
by grep only (those files fail typechecking by design, so no census is
possible; all 16 with parameterized closures take `Int`, a reference, an
unsafe type or a payload-free enum); the freestanding cases were compiled
hosted, with the battery's `freestanding` lane as the cross-target evidence;
and a closure inside a generic the corpus never instantiates at an owning type
emits nothing, so the census cannot see it — the one inert declaration is
`W02`'s never-called `fn_type_pos(f: (Path) -> Int)`.
