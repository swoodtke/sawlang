# Saw Tracker — Archived Recaps (Sep 2 – Sep 8, 2026)

Landed / closed / decided entries moved VERBATIM out of designs/todo.md,
opened at the Sep-2 split (first move Sep 3). Section order and text are
as found there; every open item stayed in todo.md — including DF-290a,
DF-291b, DF-286b and DF-286c (filed by the same 218/1.5 stage-3 work but
open), and the design 218 unit 1.5 entry itself, which rotates only after
stages 4/5 close. DF-292a has no standalone tracker lines — its record is
the 218c spec's Amendment C and the 218 entry, and travels with them.
Queue/backlog records for moved work travel here with their entries.
Append-only history.

## Backlog records (moved Sep 3, first rotation — the 218/1.5 stage-3 batch)

- DF-287c — CLOSED Sep 1, design 260 LANDED (entry below): `func f(&var self) consumes` at the declaration, `(move b).f()` at the call. Two v1 fences the landing added beyond the brief's list are reported for ratification; the `Task`/`Thread` fate migration stays a separate brief (260 §5)
- DF-288a — CLOSED Sep 2, FIXED (entry below): the registration funnel stamps `VariableInfo.borrows_referent` and `_check_move_expr` refuses. Six faces closed, not three — the sweep added a FIELD scrutinee, a re-borrow, and the COPY TIER (un-retained too, so the refusal is tier-blind); blade's own `main` was a live latent double free and is migrated in the same commit. Conformance rows V60-V63. N10 remains open and is still unpaired
- DF-289c — CLOSED Sep 2, FIXED (entry below): the store holds a LIST per (struct, method NAME); the six by-NAME readers take the first through `_first_pristine` (behaviourally identical — std collides on exactly three keys, none of them reachable by the design-70/74 builders) and the materializer asks `pristine_method_for`, which tells siblings apart by the mangler's own discriminators. Pinned by `examples/generic_same_named_inits_and_overloads.saw`
- DF-289d — CLOSED Sep 2, FIXED (entry below): at a declared `-> T?`, a bare `None` ARM of the tail's value branch is the OUTER absence and a VALUE arm owes exactly one wrap. `_wrap_tail_into_optional` DISTRIBUTES the wrap into the arms — one funnel, four tail positions, the closure one of them (it had never asked `_tail_owes_optional_wrap` at all) — instead of wrapping the merged expression and putting the layer in twice. Fully CONCRETE: `func f(flag: Bool, x: Int?) -> Int?? { if flag { None } else { x } }` was invalid IR on main. Pinned by `examples/nested_optional_tail_branch_arms.saw`, conformance row O16
- DF-289e — CLOSED Sep 2 by stage 3c-2c(2) (entry below): the method half LANDED, with the recorded shape re-applied verbatim. The residual consumer sweep the entry owed is DONE and found NOTHING — 175 generic std methods, 59 with an owning by-value parameter, 11 of those suspending, all eleven probed from a driven body with an `Arc<Res>` refcount + deinit witness before and after: byte-identical. The `df151c` SIGTRAP was never a member of that family — it is DF-291a
- DF-291a — CLOSED Sep 2, FIXED (entry below, filed by design 218 unit 1.5 stage 3c-2c(2)'s agent; PRE-EXISTING, latent). A `Never` that arrives by SUBSTITUTION was read as the diverging DECLARATION `-> Never` makes, at both spendings — `void` + `noreturn` at the declaration and `unreachable` after the call. Design 141's window result `__R` is `Never` in every coroutine-frame dispatch, so `Slot<T>.value<Never>` was emitted as a function that must not return and then called as one that does: SIGTRAP with no message, which is the `df151c_optional_dest_copy` failure the DF-289e stop recorded as an ownership interaction. Design 132's substituted-`Void` ruling at the return position. Pinned by `examples/D21_substituted_never_is_a_value.saw`, conformance row D21

## DF-289a — ~~a SPLICED or SYNTHESIZED declaration made its host module claim
## the file it came from~~ (filed + FIXED Sep 2 by design 218 unit 1.5 stage
## 3c-2a's agent; PRE-EXISTING)

MECHANISM (obligation 4). A monomorphized clone and a transform-synthesized
frame both keep the ORIGINAL's source spans — that is what makes their
diagnostics anchor at the author's own line — and design 210 unit 4's per-file
home-scope map read those spans as OWNERSHIP. `_module_source_files` walked a
module AST's declarations for their `source_file`, so `amplify$1$Lo` and
`__Frame_Cell$m$embedmod_charge$1$Lo`, both living in the ENTRY ast after the
coroutine transform, made the ENTRY module claim `embedmod/lib.saw` — and the
entry is checked LAST, so its claim overwrote the real owner's.

WHAT IT COST: on the transform's re-entry the template's home scope was the
entry's namespace, where `boost` is not a name. That is census class 14
(`undefined function boost`, 27 records), conformance row K22's own shape, and
DF-206e's costume worn one pipeline stage later. Invisible before splice-all
because the instance check that reads that scope reported nothing.

FIXED at the one walk (`_module_source_files` skips every declaration no author
wrote) and at both capture points (`setdefault` — first claim wins, and modules
are checked in dependency order with the entry last). Its regression test is
`examples/conformance/K22_cross_module_generic_embed_private_sibling.saw`, which
becomes load-bearing the moment splice-all checks every instance.
[218c B1]

## DF-289b — ~~a RESOLVED SYMBOL is the identity, and two paths dropped it~~
## (filed + FIXED Sep 2 by the same agent; PRE-EXISTING)

MECHANISM (obligation 4). `_canonical_type_name` answers "what does this NAME
denote in the module asking" — right for a name an author wrote, wrong for a
type that already knows which declaration it is. Two paths handed it the second
kind:

  1. `_resolve_type`'s STRUCT and ENUM arms canonicalized the written name even
     when the `SawType` carried a resolved `symbol`;
  2. `SawType.substitute` DROPPED `symbol` whenever it rebuilt a STRUCT or ENUM
     with type arguments — only the arguments changed, so the head still names
     the same declaration.

WHAT IT COST: an instance check runs in the TEMPLATE's module, so a substituted
`Slot<Res>` reaching `std/vector` was re-pointed at `std.compiler.frame`'s
`Slot` and the diagnostic read ``argument 1 expects `&Slot<Res>` but got
`&Slot<Res>` ``. Census classes 5/8/9/10, mechanism M1a — 61 records at the
merged scope, the last 21 of them the generic spelling.

FIXED at both paths, plus `monomorphize.identify`, which attaches the symbol the
REGISTRY's own arguments never had (they are minted by canonicalization, not
resolved through one) from the merged namespace at the one place it is in hand.
[218c B1]

## DF-289c — ~~the PRISTINE TEMPLATE STORE is keyed by (struct, method NAME), so
## two same-named methods of one type COLLIDE~~ (filed Sep 2 by the same agent;
## PRE-EXISTING; **CLOSED + FIXED Sep 2 by stage 3c-2c(2)**)

MECHANISM (obligation 4). `_capture_pristine_templates` writes
`self._pristine_generic_struct_methods[(ext.struct_name, m.name)] = (copy, ext)`
— one slot per NAME. `sawc/std/vector.saw` declares TWO inits, `init()` at line
67 and `init(capacity: Int)` at line 79, so one of them is not in the store at
all; a generic extension's method OVERLOADS collide the same way, and so do two
extensions on one type that declare the same name.

WHY IT IS INVISIBLE TODAY. The design-70/74 builders ask by name and use
whatever the slot holds, which is a template of the right name and (for their
driven/spawn population) has always been the right one. The stage-3c
materialization funnel guards with `entry[1] is not ext` and SKIPS silently,
which is why the Sep-2 re-census reports zero over 671,208 pairs while the store
cannot answer for `Vector.init()` at all.

WHAT IT BLOCKS. 3c-2c's second half splices a concrete method per (instance,
body) pair, so a method the store cannot answer for is a method nothing
declares: `Vector<String>()` in `std/string.saw`'s `split` became ``internal
compiler error … 'Vector$2$String$GlobalAllocator_init_'``.

WHAT LANDED (Sep 2), as the fix direction predicted. The bucket is a LIST; the
six by-NAME readers take the first through `_first_pristine` (`effects.py`'s two
builders, `expressions.py`'s drive path, `coro_transform.py`'s two promotions),
and the materializer asks `TypeChecker.pristine_method_for`, which discriminates
in the MANGLER's own order: the owning extension, then the design-55 overload
symbol, then the parameter names an `init`'s symbol is keyed on.

"FIRST" IS BEHAVIOURALLY IDENTICAL, measured rather than assumed: std collides
on exactly THREE keys — `FixedStringBuilder.append` (4, all in one extension,
told apart by `$OL$`), `Set.init` (2) and `Vector.init` (2) — none of them
method-generic and none reachable by the design-70/74 builders, so first-vs-last
decides nothing. (The old dict kept the LAST written; the readers never noticed
because their population never collided.) Pinned by
`examples/generic_same_named_inits_and_overloads.saw`, which declares two inits
and two method overloads on one generic type and calls all four.
[218c stage 3c-2c]

## DF-289d — ~~a value BRANCH's merged type can disagree with its ARMS' stamped
## annotations~~ (filed Sep 2 by the same agent; PRE-EXISTING, exposed by
## DF-286c face 4's fix; **CLOSED + FIXED Sep 2 by stage 3c-2c(2)**)

MECHANISM (obligation 4). A value `if`/`match` is LOWERED from its arms —
codegen's phi takes each arm's own stamped type — while the checker reports a
type it merges from the arms' checked types. An arm annotated from the enclosing
RETURN type before the merge (a bare `None` tail is, by design 87's
propagation) then lowers one layer DEEPER than the merged type says.

MEASURED. `Vector<Int?>.pop` declares `-> T?`, so at `T = Int?` it returns
`Int??`; its tail `if` merges to `Int?` while its `None` arms lower at `Int??`.
Harmless while the tail wrap keyed on "is the value already optional" (it
wrapped nothing); the moment DF-286c face 4 made the wrap key on "is the value
the PAYLOAD" — which it must, or `func f(x: Int?) -> Int?? { x }` emits
`ret {i1, i64}` from a `{i1, {i1, i64}}` function — the same tail got a third
layer and LLVM refused the module.

THE RULE, and it is a RULE rather than a guard (Sep 2). At a declared `-> T?` a
bare `None` ARM of the tail's value branch is the OUTER absence — `case Empty ->
None` in a `-> V?` accessor is "no value here", which is what `std/map.saw`'s
`_get_value` and `std/vector.saw`'s `pop` mean — and a VALUE arm is the payload
and owes exactly one wrap. The contextual-`None` funnel already stamps the arms
on that reading; the WRAP was the half that did not, and applying it to the
MERGED expression put the layer in a second time. `_wrap_tail_into_optional`
distributes it into the arms instead, per LEAF so nesting composes, leaving a
leaf the merge already brought to the target alone.

ONE FUNNEL, four entry points — `_check_method`'s tail, `_reconcile_return_type`'s
free-function twin, `_wrap_optional_tail` (the generic deferred path) and
`_check_closure`'s tail, which had never asked `_tail_owes_optional_wrap` at all
and is why `Map<String, Int?>`'s `_lend_var` window closure was a shape mismatch.

Concrete all along: `func f(flag: Bool, x: Int?) -> Int?? { if flag { None }
else { x } }` was invalid IR on main. The generic side only looked right because
an abstract `V?` owes no wrap, and design 218 unit 1.5 stopped judging an
instance abstractly. Pinned by `examples/nested_optional_tail_branch_arms.saw`
(nine concrete shapes across the four positions), conformance row O16; the
instantiated faces are `optional_generic_vector.saw` and `optional_generic_map.saw`.
[218c, DF-286c face 4]

## DF-289e — ~~3c-2c's SECOND HALF is a behavioural-contract flip and owes its own
## dispatch~~ (filed Sep 2 by the same agent; THE STAGE STOP; **CLOSED Sep 2 —
## the dispatch ran and the half LANDED**)

MECHANISM (obligation 4). Moving every monomorphized method body from
`_generate_method_generic`/`_generate_init_method_generic` onto the ordinary
`_generate_method`/`_generate_init_method` path is what DF-251b's structural
closure IS — the ordinary path registers param cleanups, populates
`variable_types` and sets the ICE breadcrumb, and the generic twin does none of
those. That is a change to OWNERSHIP BOOKKEEPING in every std generic method
with an owning by-value parameter, so it is a behavioural-contract flip in
obligation 2's sense and owes the sweep.

WHAT WAS BUILT AND REVERTED (the branch carries none of it; the shape is
recorded so the next dispatch does not re-derive it): phase 2 splices ONE
concrete `Extension` per mangled receiver carrying every materialized method
clone, with the LLVM symbol stamped at the producer (`init` by parameter names,
a method-generic by its own type arguments, an overload by the `$OL$` signature
moved onto the instantiation's base); codegen registers every registry type
instance's LAYOUT up front (census row S5) and stops monomorphizing extensions;
`_ensure_monomorphized_generic_method` becomes a lookup with ICE-on-miss (row
M4); `_monomorphize_extension`, `_monomorphize_single_extension`,
`_declare_monomorphized_method`, `_generate_method_generic`,
`_generate_init_method_generic` and the `pending_method_bodies` queue all delete
(row M6); `_receiver_saw_type` gives the drop glue the base+args form a mangled
name cannot answer for.

WHERE IT STOPPED, with evidence. `test_runner.py -f generic,optional` went from
160 failures to THREE, and the three are two named families, not a long tail:
DF-289c (the store cannot answer for `Vector.init()`) — fixed on the reverted
branch; DF-289d's family at the place lowering's own window closure
(`Map<String, Int?>` at `map.saw:119`, ``{i1, {i1, i64}} … != {i1, i64}``); and
a SIGTRAP in `examples/df151c_optional_dest_copy.saw`'s
`balance-suspending-arm` — an `Arc<Res>` refcount balance across a suspending
match arm, i.e. the ownership flip meeting the coroutine frame, which is
precisely what the owed consumer sweep is for. DF-251b's XFAIL DID flip
(reported "1 unexpectedly passed"), which is the confirmation that the
structural closure works and the cost is real.

**THE RESIDUAL SWEEP, AND ITS VERDICT (Sep 2).** The family the flip puts at
risk is std's generic methods with an OWNING BY-VALUE PARAMETER whose body
SUSPENDS — where the new cleanup registration meets the coroutine frame.
Enumerated from the builtin typechecker's own effect tables
(`.build/scratch/probe_susp_owning_param.py`): **175** generic (extension- or
method-generic) std methods, **59** with an owning by-value parameter, **11** of
those suspending — `Vector.each` / `map` / `fold` / `each_indexed` / `sort_by`,
`Map.each` / `each_key` / `each_value`, `Set.each`, `String.withCString`, plus
`fold`'s `initial: Acc`, the one NON-closure owning parameter on the list.
All eleven were exercised from a driven body with an `Arc<Res>` refcount +
deinit witness (`.build/scratch/sweep_matrix.saw`), before and after the flip:
**byte-identical output, every row balanced.** The family is clean.

**AND THE SIGTRAP WAS NEVER ITS MEMBER.** `df151c_optional_dest_copy` failed for
DF-291a — a `Never` that arrived by SUBSTITUTION, read as the diverging
declaration — with no ownership in it at all. That is what the sweep bought:
the ownership hypothesis the stop recorded is now DISPROVED by evidence rather
than left as the leading explanation, and the real mechanism has its own entry.
The sweep also turned up DF-291b, a pre-existing `Vector.fold` leak identical on
both sides.
[218c A4, stage 3c-2c]

## DF-291a — ~~a `Never` that arrives by SUBSTITUTION is read as the diverging
## DECLARATION~~ (filed + FIXED Sep 2 by design 218 unit 1.5 stage 3c-2c(2)'s
## agent; PRE-EXISTING and latent)

MECHANISM (obligation 4). `-> Never` is a claim about CONTROL FLOW and codegen
spends it twice: `_lower_declared_return` gives the declaration `void` plus
`noreturn`, and `_terminate_after_noreturn` ends the caller's block with
`unreachable`. Neither is true of a `Never` an INSTANTIATION supplied — design
132 rules exactly that for a substituted `Void`, and the return position is the
same question.

THE CARRIER, and why it had never fired. Design 141 makes every `borrows`
accessor a method-generic over its window result `__R`, and the coroutine
transform calls one on the frame's own `Slot<T>` storage: a local bound ahead of
a `match` whose arm suspends becomes a frame field, and the dispatch reads it
through `Slot<T>.value()`. Every arm of that dispatch resumes or returns, so the
window body never falls through and `__R` is inferred `Never` — while
`Slot<T>.value` itself returns perfectly normally. `_declare_monomorphized_method`
asked the TEMPLATE's return type, which is the type PARAMETER `__R`, so both
spendings were suppressed by accident of where the question was asked. Stage
3c-2c(2) makes an instance an ordinary concrete declaration whose return type IS
`Never`, and both fired at once: `define void @Slot$..._value$1$$Unknown$NEVER
... noreturn` for a function that returns, and `unreachable` after a closure
call that comes back. SIGTRAP, no message — the `df151c_optional_dest_copy`
failure DF-289e recorded as an ownership interaction.

THE FIX carries the fact on the clone rather than re-deriving it: the
materialization funnel stamps `mono_substituted_never` when the clone's return
is `Never` and the template's was not (`ast_nodes.Function`/`Method`, a declared
design-126 annotation). `_lower_declared_return_of` reads it at every
DECLARATION site — the trait vtable slot keeps the type-only
`_lower_declared_return`, because a slot has no declaration — and
`_substituted_never_body` reads it at the closure arm of
`_terminate_after_noreturn`, which is the one arm that cannot judge from the
call's stamped type and whose own docstring already flagged the accessor window
as the shape it gets wrong. Pinned by
`examples/D21_substituted_never_is_a_value.saw`, conformance row D21.
[218c stage 3c-2c, 228 leg 3, 132, 141]

## DF-288a — CLOSED Sep 2, FIXED. SOUNDNESS: a match arm may `move` its payload
## binding through a REFERENCE scrutinee — silent double free (filed Sep 2 by
## the lead from an sos repro; PRE-EXISTING)

LANDED (agent branch, PARKED unbatteried for the lead to cherry-pick after
design 218 stage 3c-2). The registration funnel asks ONE question —
`_match_payload_borrows`, whose docstring names its two entry points — and
stamps the answer on the binding as `VariableInfo.borrows_referent`;
`_check_move_expr` refuses beside its existing `TypeKind.REFERENCE` test.

SIX FACES, not the filed three. The sweep added: a FORWARDED re-borrow; a
FIELD scrutinee off an OWNED local (`match h.s` — codegen aliases it exactly as
it aliases a `&var` parameter); and the COPY TIER, which the filing's reading
would have left out. That last one is the finding that shaped the rule: DF-190d's
Copy-tier RETAIN is gated on the scrutinee being an owned NAMED LOCAL, so a
borrowed scrutinee's binding is un-retained at every tier — probed on an `Arc`
payload, `strong_count()` was UNCHANGED across the move while a second owner
existed. The refusal is therefore TIER-BLIND. A `&var self` receiver is its own
AST node and reached neither the reference test nor a scope lookup, so it
stayed silent after the parameter faces closed and is handled by name.

RULING RECORDED FROM EVIDENCE: a design-260 CONSUMING body does NOT license a
match-payload move. `consumes` licenses `move self.<field>`; the end-of-body
release still runs over the remainder, and the probe showed the payload
released there AND by the moved-out value.

TWO THINGS THE FIX DELIBERATELY DOES NOT DO. A PLACE scrutinee stays design
146's: `place_uses._borrow_match` declines the borrowing lowering for an arm
that moves a binding, which drops the match onto the value-read path, and that
path is already right at every tier (Copy reads out with a retain and the arm
consumes an owned temporary; move-only is refused by the diagnostic that can
name `with_ref`/`swap_out` on the actual receiver). Answering here preempted
that better message AND retired the DF-187b traversal pin, which is how the
first suite run caught it. And SYNTHESIZED code is exempt, on
`_check_payload_read`'s design-218-stage-1 reasoning: the coroutine transform
re-homes an arm payload into a frame slot and emits a `move` of its own, and
the program is re-checked — the author's `move` was judged on pass 1 (pinned by
V57's suspending face and `examples/match_borrowed_payload_in_a_driven_body.saw`).

CORPUS RISK: an AST census over all 2542 tracked `.saw` found exactly ONE site,
and it was a live latent double free — `blade/src/main.saw`'s `case Run(args) ->
b.run(move args)`, moving an `ExplicitCopy` `Vector<String>` out of a field
`parsed_cli` still owned. Migrated to `args.copy()` in the same commit. std,
examples, libs, devtools and selfhost are clean. (The census's FIRST run
reported zero: its walk stopped at `Argument`, which is a plain dataclass and
not an `ASTNode` — the freestanding gate's blade build is what found the site.)

Conformance rows V57-V60 (three refusal rows, one control row counting the four
shapes the fence must not reach). Spec + saw-lang skill updated; README carries
no match-ownership prose, so it needed none.

ONE FINDING FILED BY THE SWEEP AND NOT FIXED HERE: DF-290a, below.

--- as filed ---

```saw
func take_it(s: &var Slot) -> Owned {
    match s {
        case Empty -> { Owned(w: 0) },
        case Full(o) -> { move o },      // compiles; the referent KEEPS o
    }
}
// var s = Slot.Full(o: Owned(w: 7)); let got = take_it(&var s)
// -> got 7 / drop 7 / drop 7 — exit 0, silent
```

THE MATRIX, lead-probed Sep 2 (`.build/scratch/refmatch_*.saw`; cells
recorded here). SILENT DOUBLE FREE at all three reference faces: a `&var`
parameter scrutinee, a SHARED `&` parameter scrutinee (payload theft
through a shared borrow — the worst face), and a `&var self` method
receiver (`match self`). CORRECT at both controls: an OWNED by-value
scrutinee consumes and drops once (the documented consuming match), and a
PLACE scrutinee (`match v[0]`) is refused by the place value-read fence
before the arm question arises. PRE-EXISTING: byte-identical behavior on
the pre-260 compiler (`b17d35e4`), so design 260 is not implicated and the
0.4.0 pin is not newly exposed — sos's 0.3.0 has it too.

MECHANISM (obligation 4): `_check_match_general`'s binding registration
(`typechecker/expressions.py:11495`) creates a plain owned
`VariableInfo(type=param_type, mutable=False)` for every variant-pattern
binding, MODE-BLIND — the scrutinee's reference-ness is never consulted —
so `move o` sees an ordinary owned local and licenses the transfer, and
codegen hands out a non-retained alias while the referent keeps its
payload. The documented model ("matching through a `&`/`&var` binding
stays a borrow — no consume") exists in the docs and in codegen's
Copy-tier retain path, but the typechecker never fences the move. ONE
registration site, so the fix is a funnel already: mark bindings from
reference scrutinees as borrows (the `is_reference`-style flag the move
checker already refuses), yielding the ordinary
cannot-move-out-of-reference error, with `Optional`+`take()` /
`swap_out`-shaped APIs as the named outs. FIX-SWEEP CELLS owed at
dispatch: `if let`/`while let`/`guard let` payload bindings over a
ref-reached optional (the same registration question at the other
lowering), nested patterns and guards (same site, verify), and the
DF-146d borrowing-arm lend path (must stay legal). WORKAROUND for sos
until then: model the slot as `Optional<Owned>` and extract with
`o.take()` — the field-safe move-out built for exactly this. PAIRS WITH
N10 (the `as` transfer-check bypass) as the second member of "the move
checkpoint is lied to" — one fix dispatch covers both, after 3c-2
(typechecker surface). [146, 219, DF-146j's alias family]

## DF-287c — no CONSUMING METHOD RECEIVER exists, in any spelling (filed Sep 1
## by the lead from an sos-relayed need; FEATURE GAP — wants a brief + a user
## spelling ruling)

The shape sos needs: `obj.consume()` where `obj` is invalid after the call —
builder `finish()`, handle `close()`-returning-a-value, `into_` conversions.

THE MATRIX, lead-probed Sep 1 (`.build/scratch/consume_recv*.saw`,
`consume_free.saw`; cells recorded here):
- `func consume(self)` — ``Parse error: 'self' must be a reference: use
  '&self' or '&var self'`` — a DELIBERATE rejection with a fixit (design
  128's family), not an accident.
- `func consume(move self)` — ``Parse error: Expected parameter name``.
- The FREE-FUNCTION twin works TODAY and is the interim idiom:
  `func consume(r: Res) -> Int { r.n }` called `consume(move r)` — compiles,
  the receiver deinits inside the callee (probe prints `drop 5` then `5`),
  and a later use of `r` is the ordinary use-after-move error.

WHY IT IS A REAL FEATURE, not sugar: std already wants it. `Task.join(&self)`
enforces consume-once with a RUNTIME provenance panic (design 242's
drop-fate machinery) where a consuming receiver makes double-join a COMPILE
error; `Optional.take(&var self)` is the field-safe move-out that exists
partly because nothing can consume a receiver.

DESIGN CELLS the brief must put to the user, pre-scouted:
1. **The call-site visibility question is the crux.** Saw's doctrine is
   reader-visibility-trumps (the call-site `&var` precedent), and the
   by-value PARAMETER already demands `consume(move r)` spelled at the
   call. A Rust-style `obj.consume()` that silently kills `obj` cuts
   against both; the visible spellings on the table are ugly in different
   ways (`(move obj).consume()` as a move-into-receiver expression, or
   accepting the decl-visible-only asymmetry with the declaration carrying
   the word). This is the user's ruling to make, not the lead's.
2. Declaration spelling: bare `self` (Rust) vs `move self` (matches the
   transfer vocabulary; the parse errors today reserve both).
3. A `NoMove` type must REFUSE a consuming method (consumption is a move;
   TaskGroup's family) — a derivation rule, not a per-type check.
4. A consuming call through a FIELD (`h.res.consume()`) is a partial move
   and stays refused like `move h.res`; `take()` remains the field
   escape. A place (`v[i].consume()`) likewise follows the place rules
   (`swap_out` remains the vector escape).
5. Expected closures if built: `Task`/`Thread.join` + `detach` + `cancel`
   migrate from runtime provenance panics to compile-time consumption
   (design 242's fate rule becomes structural), and take-shaped APIs stop
   needing an Optional wrapper.

**CLOSED Sep 1 — design 260 LANDED** (`designs/260-consuming-receivers.md`,
ruled over three passes the same night: the `&var self` receiver amendment,
Option A's ratification, and the sos-proposed replacement rule that superseded
the lead's E0509-analog draft). `func finish(&var self) consumes -> T` at the
declaration, `(move b).finish()` at the call; the callee releases what remains
of the referent and the caller's binding releases nothing. Cell answers as
built: (1) BOTH ends marked, the caller word `move`; (2) the receiver stays
`&var self` — no third mode; (3) the `NoMove` refusal is FREE at the caller's
`move`, no derivation rule owed; (4) field and place receivers stay refused by
design 35, with `take()` / `swap_out` now named in the hint; (5) the
`Task`/`Thread` migration is still a separate brief (design 260 §5).
Option A's `move self.<field>` is in, per field on an every-path-or-no-path
rule; a consuming body replaces a hand-written `deinit` BODY for its endpoint,
and `consumes` is therefore declarable only in the receiver type's defining
module. Compiler version bumped 0.3.0 -> 0.4.0 (user: minor for new surface).
TWO v1 FENCES the landing added beyond the brief's list, both named at the
declaration and both reported for ratification: a suspending consuming body may
neither move a field out nor sit on a type with a hand-written `deinit` — a
suspending method's receiver lives in the CALLER's coroutine frame, whose
release is decided per slot, so it can neither skip a field (a cancellation
point between the move and the body's end would need the per-field drop flag
§3 excludes) nor apply §2's deinit-body replacement. Suspending consuming
methods otherwise work, driven and spawned. [128, 242, 219, 260]


## Rotated Sep 3 (second rotation — 218 unit 1.5 closes; 261/263 land)

- Design 218 unit 1.5 — monomorphization becomes a pre-codegen transform (RULED Aug 13; ~~SCHEDULED Aug 24, user: MOVED UP, BEFORE the 238 split~~ ORDERING SUPERSEDED Aug 28, user: 238 goes FIRST — the freestanding suite is the cross-target gate 1.5 lands under, and sawos's first pin bump follows 1.5's landing; rationale in 238's Aug-28 rulings section). Process per the 218 ruling: a FABLE SPEC AGENT authors the census first (every `_ensure_monomorphized_*` call site, the instance-re-check design, error attribution, the per-(template, type-args) cache), lead reviews, user rules, Opus implements. Expected closures ride it: DF-217i/j/k, S1 row p08a, plausibly DF-247a. Brief section: designs/218-enforcement-architecture.md unit 1.5. **SPEC AUTHORED Aug 25 (`designs/218c-monomorphization-spec.md`) and LEAD-RATIFIED same night under the overnight authorization — all six section-8 questions resolved as recommended (rationale in the spec's status header); none touched a user ruling. Probes: DF-247a NOT dissolved (own dispatch after 1.5, OQ5); two new findings (DF-258a: a nested unconditionally-suspending generic silently loses its yield — pinned at stage 0, flips stage 4; DF-258b: recursive instantiation growth HANGS the compiler — fixed by stage 1's depth limit). IMPLEMENTATION HELD (user, Aug 25 morning): the pipeline STOPS after the 234 flip integrates — 1.5's build dispatches on the user's go, against the ratified spec** **GO (user, Aug 31: "we should finally work on 218/1.5"): DISPATCHES NEXT — immediately after designs 256/257 integrate (same typechecker surface; two agents on it concurrently would collide), Opus against the ratified 218c spec. The "first pin bump follows 1.5" clause is SUPERSEDED BY EVENTS: bumps 0.2.0/0.2.1 already shipped for the sos findings batch** **STAGES 0, 1 AND 2 LANDED Sep 1 (branch `worktree-agent-aef37a0f71731cc39`); STAGES 3-5 OPEN. The perf pause is LIFTED (measurement below); stage 2's last step is HELD on DF-284c, a cross-unit blocker — see its entry.** Stage 2: the four `del self.reporter.errors` sites in effects.py are GONE (the charter's "type-stamping device"), §3's attribution note is a `CompilerError.note` field rendered between the caret and the hint, two §1c provenance skips land at their own rules (design 132's visible-Void — the one the instance mark is load-bearing for — and the design-150 warning categories at the `_warning` funnel), and abstract-first is ENFORCED rather than assumed: an instance reports only in a compile the abstract layer accepted. One real bug fixed on the way, invisible while the diagnostics were deleted — `_add_associated_type_bindings`, since a clone has no bounds left and a body naming a bound's associated type kept it unsubstituted (`examples/generic_instance_associated_type_binding.saw`; codegen has bound the same associated types since brief 36). The spec's grep gate joins `citations` as CHECK 3 (a `del` against a reporter's own list, over every tracked `sawc/**.py`, with its own recogniser self-test) — it belongs there because every other gate observes BEHAVIOUR and a check whose diagnostics are deleted behaves exactly like no check at all. **STAGE 2 LANDED Sep 1: `INSTANCE_ERRORS_ARE_REAL` is True.** **USER RULING (Sep 1): the unit-3 primitive-conformance desugar pulled forward into 1.5 to unblock DF-284c; the rest of unit 3 stays its own unit.** The slice is `_builtin_requirement_call` — it stamps design 239's own `comparison_dispatch` for a CONCRETE receiver whose conformance body lives in codegen, so the requirement lowers through `_emit_equals`/`_emit_compare`, the emitters `==` and `<` already use; no body moved and no symbol was minted, which is how behavioural identity is a property of the code rather than a claim. DF-284c CLOSED, with a scope correction the entry records (the set is a predicate with three members, not the two the ruling named — `@synthesize`d ENUMS and String's requirement spelling walked past the first fence) Stage 0: the two pre-registered pins land XFAIL, corodiff gains the `nested_generic_susp` axis value, DF-258a/DF-258b file, and two HARNESS findings were repaired on the way (DF-284a/b — corodiff had been scoring 2408 identically-refusing pairs as clean). Stage 1: `sawc/monomorphize.py` (the demand fixpoint, the registry, the depth limit) + `sawc/mono_identity.py` (the identity funnel, which codegen now delegates to) + four shadow hooks in `codegen/generics.py`. **The registry-completeness proof is DONE and is stage 1's whole point: the full suite passes under `SAWC_MONO_SHADOW=strict` (2318 passed / 8 xfailed, 2326 verdicts, ZERO misses), and so does the freestanding suite (33, both arches).** DF-258b CLOSED by the depth limit. **PERF: WITHIN the spec's §5 envelope — the tripwire never fired** (measured to §5's own instrument on the lead's instruction, Sep 1: uncontended, same machine, under the suite lock, 3-run median, both trees). Full-suite COMPILE median **604.1s baseline → 606.2s branch, +0.35%**; BOOTSTRAP median **158.4s → 164.1s, +3.6%** (envelope +10% on both); peak RSS on §5's three probes **hello 94.9→104.3 MB (+9.9%), a generic-heavy example 122.1→124.1 MB (+1.6%), blade's entry 532.9→532.0 MB (-0.2%)** (envelope +25%). The earlier +27%/+12% readings were CONTENTION, exactly as the lead suspected — a lightly-loaded baseline run against heavily-loaded branch runs; the honest instrument shows the two trees inside each other's run-to-run spread. Applied on the way, none of it speculative: §5 remedy 1 (the phase runs once per SETTLED front half rather than once per place-lowering re-entry), a per-class field cache and a scalar filter in the collection walk (the phase's per-compile cost 0.69s → 0.24s by profile), and one genuine algorithmic bug — an exponential (2^depth) argument descent the 64-deep depth-limit test exposed. §5 remedies 2 and 3 are NOT needed and were not built; the design-168 narrowing of the type closure (bodies deferred to a call demand) is NOT authorized — it changes the instance set for a hosted `-c` object, which is a link-surface question **STAGE 3 IS HELD, Sep 1, on §5's own rule and on two findings the stage-1 registry made measurable for the first time — DF-285b (the pristine template store §1c/§4 write the instance check against is EMPTY in an entry compile: 0/0/0 on hello.saw, against 111 demanded instances, every one of them std's, because std bodies belong to the cached builtin typechecker) and DF-285c (the splice-all costs +83% per compile before any checking — 0.94 s on a 1.13 s compile, 81% of it `copy.deepcopy` over 306 (type instance, method) pairs, and near-CONSTANT across programs because it is std's type closure — against an envelope of +10%, with remedy 1 already applied, remedy 2 able to remove only 0.09 s of it, and remedy 3 plus the design-168 narrowing unauthorized; and the check itself reports ~30 diagnostics per compile against std's own bodies, two of the largest classes verified as refusals of code that compiles and RUNS today).** Stage 3 is ATOMIC by the spec's own argument, so none of it landed. WHAT DID LAND on the way: **DF-285a, a regression stage 2 introduced and the whole battery is blind to** — `substitute_ast_types` cannot reach a type parameter spelled in CALL-NAME position (`A()`, design 37's allocator construction, which `Vector._reserve` and `Box.make` are written around), so a spliced instance named a function that does not exist; main compiles the repro and prints `8` and the branch refused it. Fixed at the funnel, pinned by `examples/generic_instance_constructs_type_param.saw`, full suite 2321 passed / 8 xfailed and freestanding 33 both arches. The two constructive directions DF-285c names, neither of them an agent's to choose: a purpose-built substituting AST copier in place of deepcopy-then-rewrite, and LAZY BODY MATERIALIZATION (the registry still decides every instance; only the instances the coroutine transform must see are spliced eagerly, the rest materialize at design 168's body demand). Stages 4 and 5 are downstream of 3 and were not started **USER RULINGS (Sep 1 evening): (1) the DF-284c scope widening is RATIFIED (recorded in its entry); (2) stages 0-2 + the DF-285a fix INTEGRATE to main NOW (done — main `466812fe`, fast-forward of the terminal-battery-green tip; worktree/branch removed); (3) stage 3 proceeds AMEND-FIRST — the lead authored `designs/218c-monomorphization-spec.md` **Amendment A** (A1 std template-store capture, A2 the two ruled perf remedies — substituting copier + lazy body materialization, BOTH user-ruled — A3 the ~30-diagnostic triage plan, A4 stage 3 restaged as 3a/3b/3c with the envelope binding at 3c). **AMENDMENT A IS USER-RATIFIED (Sep 1), in full — including the one flagged semantic cell, A2(b)'s checked-equals-materialized alignment (an instance demanded but never emitted in an EXECUTABLE build is registered and depth/effect-validated but never instance-checked, so a diagnostic living only there surfaces in `-c` and not in `-o`). Ratified together with a new **A5**, which the user's reversibility question earned and which is what makes the cell ratifiable: (a) a forced-eager mode `SAWC_MONO_MATERIALIZE=all` — sibling to `SAWC_MONO_SHADOW`, off by default, landing with 3c — plus ONE battery lane running the suite under it, so the strict answer stays computable, the corpus is PROVED to carry no latent errors in never-emitted instances (the lax→strict ratchet never accumulates), and a later flip has its evidence already in the gate rather than owed as a migration; the reversal itself is a PREDICATE (widen the eager set from transform-relevant to all-registered — the registry decides every instance either way, and G3/M6/the codegen template stores that 3c deletes are the OLD path, not the eager one); and (b) THE MEASUREMENT DECIDES THE DEFAULT — the +83% that bought laziness was measured with `copy.deepcopy` and 81% of it WAS the deepcopy, which A2(a) removes, so §5's instrument re-measures splice-all at 3b's boundary: inside the +10% envelope and laziness is NOT bought (eager set = everything, the cell is MOOT and never ships, the switch drops and the lane stays as the pin), over it and A2(b) stands as ratified. The 3b landing note records the number and names the branch; the lead confirms the branch before 3c dispatches. Stage 3 DISPATCHES against the amended spec (fresh Opus, fresh worktree, DF range DF-286a+)** **STAGES 3a AND 3b LANDED Sep 1 (branch `worktree-agent-a10a55dcac30150b0`); 3c OPEN, and the lead confirms A5(b)'s branch before it dispatches.** 3a — A1's RECOMMENDED path, the capture extended rather than §4's argument rewritten: `_capture_pristine_templates` is now a funnel with two named entry points, `check_module` (entry + user modules) and `check` (the whole-program path, which is std's), and `check` records the per-file `(module path, namespace)` scope too; both stores ride out on `builtin_ns` and therefore through the ONE stdcache blob, which is where they must be since the pair shares `SawType`s by identity and the scopes hold that namespace. A UNION, not a merge — reads go through `pristine_generic*` / `_module_scope_for_file`, entry first — because merging would silently widen the existing design-70/74 builders, which decline a template with no pristine copy and have never covered a std generic; widening that is 3c's cutover. A1's STOP CONDITION did not fire: snapshot **0.022 s per cache BUILD** (2.7% of `build_builtin_namespace`), blob **6.37 → 7.39 MB (+16.0%)**, `pickle.loads` **0.068 → 0.077 s (+9 ms) per compile**; the checked-clone fallback is not taken. **A3, re-probed and NOT confirmed:** the diagnostic count is IDENTICAL before and after A1 — 30 diagnostics over 295 (type instance, method) pairs, 270 clean, the same set both ways — so the missing std module scope was not what produced them. All 30 are reported and NOT decided; the classification is in the agent's report and every one owes the user a ruling. 3b — `sawc/mono_copy.py`, the substituting copier (A2(a)): one pass, `SawType.substitute` kept as the authority on what substitution means, the caller's own concrete types memo-pinned so they are shared exactly as the old order shared them, DF-285a's call-NAME rewrite applied BY the copier as it builds the node (one definition; `substitute_ast_types` now delegates to it), and the four builders' `deepcopy` + rewrite gone. The oracle is `SAWC_MONO_COPY_ORACLE=1` and it checks TWO properties — structural equality against deepcopy+substitute, and that the clone shares nothing with its template but the map's own types, which is §4 stated as a checkable property of one clone; the whole suite passes under it together with `SAWC_MONO_SHADOW=strict` (2321 / 8 xfailed). **A5(b)'s MEASUREMENT — §5's own instrument, uncontended, one machine, under the suite lock, 3-run median, conditions INTERLEAVED and reuse defeated (0/2329 reused every run): full-suite COMPILE median 330.8 s → 393.0 s, +18.8%; BOOTSTRAP median 232.9 s → 272.0 s, +16.8%. OVER the +10% envelope, so A5(b) selects A2(b) AS RATIFIED: lazy body materialization is the default at 3c, the semantic cell ships, and A5(a)'s forced-eager lane is what keeps it honest.** Peak RSS is not the constraint (hello 189.6 → 195.1 MB, +2.9%; a generic-heavy example 222.2 → 223.7 MB, +0.7%; blade's entry 743.2 → 732.9 MB, −1.4%; envelope +25%). The copier did most of what A2(a) promised — the per-compile splice-all cost is **+14.5% on hello (1.314 → 1.505 s), +13.1% on serde169_derived, +2.7% on json_value_object_serialize**, against DF-285c's +83% — but "most" lands outside the envelope, not inside it. Two things the reader should know about the number: the measurement instrument (`SAWC_MONO_MEASURE=splice-all`, off by default, a THROWAWAY reporter so A3's unruled diagnostics cannot reach a gate) re-materializes on the post-transform re-entry with no cache carried across, which is the PESSIMISTIC end for driven programs — but hello and serde are not driven and are over the envelope on their own; and DF-285c's 81%-was-deepcopy finding was measured against CHECKED templates, while A1 made the store PRISTINE and a pristine template deep-copies in 0.17 ms (all 165 in 18 ms), so most of that 81% was already gone before the copier was written. **DF-286a filed + fixed on the way** (entry above): the registry called every specialized extension generic, because `_build_tables` decided from `Extension.type_args` — a field the parser never fills. Shadow mode is blind to it by construction (it proves codegen's demands are a SUBSET of the registry, and this made the registry bigger). Fixed at a funnel, `mono_identity.extension_specialization_key`, which codegen's copy now delegates to. **STAGE 3a/3b GATE GAP, honestly reported: `tools/freestanding_runner.py` COULD NOT RUN on this machine — qemu-system-riscv32, qemu-system-aarch64 and ld.lld are absent and the sandbox refuses the install (EPERM under `/opt/homebrew` even with the sandbox disabled). Every commit is suite-green; the cross-target gate is OWED and must run before 3a/3b integrate.** **THE OWED GATE RAN (lead, Sep 1, after the user installed qemu+lld — the new machine simply lacked them): freestanding 33 PASSED both arches on the branch tip, GATE=0; 3a/3b INTEGRATED to main `1889c507` (rebase over the lead's doc commits, one todo.md accumulator conflict resolved hunk-by-hunk, both sides verified present; sawc/ byte-identical to the battery-green tip); integration gate (suite + freestanding on main) recorded in `.build/scratch/integ_{suite,fs}_3ab.log`.** **TWO USER RULINGS (Sep 1 evening), recorded in full in the spec's A5(b)/A3 OUTCOME sections: (1) SPLICE-ALL ANYWAY — the +18.8%/+16.8% over-envelope measurement is ACCEPTED and A5(b)'s lazy selection is OVERRIDDEN; the semantic cell never ships, `-c`/`-o` report identically, the slowdown is future targeted-perf/self-host work, the §5 envelope RE-BASES at 3c to the accepted numbers, and `SAWC_MONO_MATERIALIZE` is not built (the default IS materialize-all; A5(a) survives as the demanded-but-never-emitted-diagnostic pin). (2) `Box<any Trait>.value` BORROWS — the A3 real catch is a std API defect; the accessor lends, landing as 3c's first unit with obligation 2's consumer sweep. The 24 remaining A3 residues go to §1c named per-rule skips with lead sign-off at 3c dispatch — a HARD 3c blocker now, since splice-all checks them on every compile.** **STAGES 3c-0 AND 3c-1 LANDED Sep 1 (branch `worktree-agent-ab880ce94128fc9e4`); 3c-2, THE CUTOVER, IS STOPPED ON A FIRED FENCE and is the only piece of stage 3 still open.** 3c-0 — `Box<T, A>.value` is a `borrows` accessor and the `T: ExplicitCopy` bound is GONE with the body that needed it: a place needs no bound, so removing it is part of the fix rather than a widening beside it, and the payload tiers that had no `value()` at all now have the window. The consumer sweep (obligation 2, a by-value->place flip on a std surface) found 65 `.value(` call sites tree-wide and exactly THREE with a `Box` receiver — `box_basic.saw`, `box_string.saw`, `box_make_reports_oom.saw`, every one a Copy-tier payload, every one a place value read that retains, all three still running and printing what they always did; outside `examples/` there is no `Box.value` call at all. Pins both faces (`box_value_lends_the_payload.saw`, `errors/box_value_move_only_read.saw`), conformance row P22, LANGUAGE_SPEC + the skill. Residue 30 -> 24. 3c-1 — the 24 become TWO named §1c skips, not three: skip 3 (`_mono_copy_is_a_retain`, a `.copy()` the SILENT tier answers on a substituted clone) took its six, skip 4 (`_transfer_is_substituted_param`, a transfer of a by-value parameter whose type arrived by substitution, which design 219 wave C's requirement inference already judged and every call site discharged) took its sixteen, and the third family's two `__window` diagnostics were a CASCADE of skip 3 and vanished with it. Skip 4's input comes from one funnel, `monomorphize.substituted_param_names`, whose docstring names its six entry points and the one `_checking_instance` that cannot supply it. The abstract catch is probed intact, not argued: a generic that binds its parameter twice at a move-only argument is still refused AT THE CALL. Residue 24 -> 0 (292 pairs materialized, 292 clean). Both units gated on the full suite (2323 passed / 8 xfailed) + freestanding (33, both arches). **3c-2 STOPPED, with evidence: DF-286b + DF-286c.** A free-function-only slice of the cutover (materialize + splice fn instances, `_instantiate_generic_function` replaced by a symbol lookup) was built and REVERTED — the branch carries 3c-0 and 3c-1 only — and it took `-f generic` from green to 9 failures. The corpus census that followed (`.build/scratch/probe_corpus_instance_check.py`, the A3 probe with a glob) is the number the stage was missing: **115 instance diagnostics over 14 of 122 generic-named examples, 36276 (type instance, method) pairs, in SIX classes of which the 3c-1 sign-off covers TWO** — and method-GENERIC instances, the rest of `examples/`, blade, libs and selfhost are not in it, so it is a floor. Two of the six are DEFECTS in the materialization funnel (DF-286c: a const-generic parameter is a VALUE the copier does not carry; the conditional-conformance bounds filter is not applied to the materialized method set) and two more are funnel faces that produce an ICE or a wrong signature (an unsubstituted associated-type return; a missing `-> T?` tail auto-wrap emitting invalid IR). The other four classes are §1c RULINGS the sign-off does not cover, one of them a design-130 question with teeth (`Vector<UnsafePointer<Int8>>` makes std's own safe methods name an unsafe-typed value, so the per-instance trigger rule refuses seven of them). A3's residue was measured on ONE program and the corpus is a different population; that is the mechanism, and it is why the fence fired rather than the cutover landing. The re-based §5 envelope was NOT measured — 3c-2 never reached a gate **STAGES 3c-2a AND 3c-2b LANDED Sep 2, and 3c-2c LANDED ITS FIRST HALF (branch `worktree-agent-a7777d5974963bfac`); the SECOND half is STOPPED on DF-289e. 3c-2a, five gated commits: B1's namespace funnel (`_home_module_scope` becomes `_instance_check_scope`, whose two inputs are the MERGED namespace for program-wide facts and the template's home module for VISIBILITY — including the namespace's per-module VIEW tables, `_VIEW_TABLES`, because a merged `ambiguous_types`/`directly_accessible` is a view no module has); DF-286c faces 1 and 2 with pins (`generic_instance_const_parameter_value.saw`, `generic_instance_associated_type_return.saw`); the ONE materialization funnel `monomorphize.materialize_instance` over all THREE registry kinds, which the census instrument now DRIVES instead of re-authoring — that is what makes 3c-2b's number the number the cutover produces; §1c skips 5 (B2, the substituted RETURN — read at `_check_return_statement`'s Void arm, `_check_value_transfer`'s `is_return` arm and `_result_autowrap_ambiguous`) and 6 (B3, citing design 136's as-written rule, landing as one more named arm of `_unsafe_check_exempt`); and B4's FRESH-JOURNEY rule as a RULE, with `_no_move_is_fresh_journey`'s three conditions, three pins and conformance rows V57/V58/V59, plus LANGUAGE_SPEC and the skill. Skip 3 widened to BOTH halves of the silent tier on the way. **THREE findings filed and fixed under it: DF-289a** (a spliced or synthesized declaration made its host module claim the file it came from — census class 14, K22's shape, DF-206e one stage later) and **DF-289b** (a resolved SYMBOL is the identity, dropped at `_canonical_type_name` and again at `SawType.substitute` — census classes 5/8/9/10). **3c-2b's GATE: the full-population census re-run answers ZERO over 225,887 instances / 671,208 (instance, body) pairs across 1,627 compilation units**, from 12,506 home-scope / 10,311 merged-scope diagnostics in 20 classes; zero materialize crashes, zero no-template misses (B5's last clause: the 14 were `Box.is`/`Box.take`, which design 51 lowers INLINE from the vtable — the DEMAND is declined and the funnel's miss arm is now an internal error), and the 80 unreached compiles are the census report's own scope notes exactly. 3c-2c(1): phase 2 SPLICES every free-function instance into the MERGED ast (per-pass, so `check_module` never re-reads it) and codegen's `_instantiate_generic_function` becomes a lookup with ICE-on-miss — census row G3 DELETED. Four more faces closed at that gate: DF-286c face 1's CODEGEN half and its typechecker twin (`_const_param_env` populated for an instance, `_const_count` no longer answering ABSTRACT with the value in hand), **DF-286c face 4 CONFIRMED and fixed** — and it was never a generic defect, the concrete twin `func f(x: Int?) -> Int?? { x }` emits invalid IR on main — and design 30 Ruling 1's generic lock-in, carried to the instance as `mono_result_roles` because at `T == E` the clone cannot re-derive which side the abstract layer chose. Per-commit gates: full suite (2347 → 2352 passed, 8 xfailed) + freestanding 33 both arches, every commit. **STOPPED, per conduct, on DF-289e**: the second half moves every monomorphized method body onto the ordinary `_generate_method`/`_generate_init_method` path, which IS DF-251b's structural closure and IS a change to ownership bookkeeping — obligation 2's consumer sweep is owed. Built, measured (`-f generic,optional`: 3 failures, two named families — DF-289c's store collision, DF-289d's branch-layer disagreement at the place lowering's window closure, and a SIGTRAP in `df151c_optional_dest_copy`'s `Arc<Res>` suspending-arm balance) and REVERTED; DF-251b's XFAIL DID flip under it, so the closure works and the cost is real. The shape is recorded verbatim in DF-289e so the next dispatch does not re-derive it. The re-based §5 measurement is NOT owed yet — it binds at the cutover, and the cutover is half-landed** **STAGE 3 IS COMPLETE: 3c-2c(2) LANDED Sep 2 (branch `worktree-agent-ad5005d176ac678b5`), two commits, and CODEGEN NO LONGER INSTANTIATES ANYTHING.** DF-289c first (the pristine store holds a LIST per (struct, method NAME); six by-name readers take the first, the materializer discriminates by the mangler's own order — owning extension, `$OL$` symbol, parameter names). Then the method half: phase 2 splices ONE concrete `Extension` per mangled receiver with the symbol stamped at the producer, codegen registers every registry type instance's LAYOUT up front (row S5), `_ensure_monomorphized_generic_method` becomes a lookup with ICE-on-miss (M4), and M6's six deletions land — `generics.py` 1037 → 521 lines, the `pending_method_bodies` queue and its two reachability hooks with them. A monomorphized body is emitted by `_generate_method`/`_generate_init_method`/`_generate_static_method` now, which IS DF-251b's structural closure: its XFAIL flipped and the fix is a DELETION. **THE RESIDUAL SWEEP (obligation 2) ANSWERED CLEAN AND DISPROVED THE STOP'S HYPOTHESIS:** 175 generic std methods, 59 with an owning by-value parameter, 11 of those suspending, all eleven probed from a driven body with an `Arc<Res>` refcount + deinit witness before and after — byte-identical, every row balanced. The `df151c` SIGTRAP was **DF-291a**, a `Never` that arrived by SUBSTITUTION read as the diverging declaration (design 141's window result `__R` is `Never` in every frame dispatch), with no ownership in it at all. **DF-289d closed as a RULE rather than a guard** — a bare `None` arm of the tail's value branch is the OUTER absence and a value arm owes one wrap, distributed per leaf through one funnel with four entry points; the closure tail had never asked the predicate at all, which is what `map.saw:119` was. Four things the cutover needed that DF-289e's record did not name, each an answer the old path gave by accident of where it stood: `_receiver_saw_type` (plus `mono_enum_args`, since an ENUM receiver resolves `match self`), `mono_substituted_never`, the two instance families codegen INTERCEPTS (layout-transparent wrappers and the erased box, now declined by both sides through `mono_identity.instance_is_lowered_specially`), and DF-289d's distribution. **The deferred tail is done**: DF-251b's marker removed, A5(a)'s pin landed (`errors/never_emitted_instance_reports.saw` — a diagnostic in a demanded-but-never-emitted instance fires in an `-o` build), `SAWC_MONO_COPY_ORACLE` + the deepcopy path RETIRED, and `SAWC_MONO_SHADOW` KEPT with its reason recorded (the two type-instance entries still register a layout on demand, so it is the only instrument with anything left to say; its scaffolding retires at stage 5 with `_process_effect_monos`'s shell, per §7). Conformance rows O16 and D21. One finding filed and NOT fixed: **DF-291b**, a pre-existing `Vector.fold` leak at an owning accumulator, identical on both sides. Stages 4 and 5 remain open **§5 AT THE CUTOVER OVERSHOT AND WAS INVESTIGATED (Sep 2 night, lead measurement: suite +53.8%, bootstrap +46.7% against the re-based +18.8%/+16.8% envelope). The split is in the spec's Amendment C. ONE COMPLIANCE GAP, fixed: DF-292a — the template store's snapshot is only PRISTINE on the first front-half pass, so a driven compile's second monomorphization run cloned templates carrying the previous pass's `resolved_type` stamps, whose `symbol` back-pointers drag `StructSymbol`s and their method declarations into every clone (`Vector.push`: 55 copied objects on pass 1, 1,581 on pass 3; the phase's second run cost 4x its first for the same instance count) — and, as `uncheck` itself records, a per-pass conclusion travelling into an instance check is unsound as well as slow. The snapshot now drops the stamp (and only the stamp — peeling the checker's wraps is what `uncheck_after=False` already declines on this AST, and doing it here ICEs `optional_generic_concurrency`). Driven-program compiles: +2.87s → +0.94s. TWO FINDINGS FILED AND NOT FIXED, both pre-existing and identical on main: **DF-292b** the pristine capture itself deep-copies through those same back-pointers (4.2 s of a 10.5 s profiled driven compile, main and branch alike), **DF-292c** the phase-6 re-run re-materializes and re-instance-checks every instance instead of hitting §4's cache (107 of 111 instances materialized twice on a driven compile), which §7 phase 6 and §5 remedy 1 both say should be cache hits (not fixed HERE because a phase-6 cache hit carries an instance BODY the coroutine transform rewrites in place, so it changes what codegen lowers — a behavioral flip owing obligation 2's sweep, i.e. its own dispatch; Amendment C4). **§5 RE-MEASURED AFTER THE FIX, same protocol: suite 332 → 441 s (+32.8%, was +53.8%), bootstrap 227 → 281 s (+23.8%, was +46.7%), spread 1 s on every cell. 21.0 suite points and 22.9 bootstrap points were the DEFECT; the residual +32.8%/+23.8% — 14.0 and 7.0 points over the re-based envelope — is the architectural cost of splice-all's method half, a per-compile constant living in `mono_copy` (111 instances, 323 materialized bodies, ~71 k copied AST nodes on a four-line `hello.saw`, because the set is std's type closure). STILL OVER: the ACCEPT/REMEDY call is the USER's, and every remedy that would close it (§5 remedies 2/3, A2(b)'s lazy materialization + its semantic cell, the design-168 narrowing) remains unauthorized. Amendment C carries the per-shape census and the evidence. The branch PARKS.** **STAGES 4 AND 5 LANDED Sep 3 (branch `worktree-agent-a531a7b8fad747c7d`, three commits) — the unit is CODE-COMPLETE against what the architecture admits, with ONE census family stopped and filed rather than forced.** Stage 4a — **DF-258a CLOSED, and the prediction held in its architecture but missed one link.** Phase 2 does splice `hop$1$Int` and its instance check does mint the effect node with the `yield_now()` recorded as a direct source (probed); what was missing is that `finalize_effects` ran inside the entry check and refused to run twice, so the fixpoint that turns a direct source into `suspends` had already gone by, the node read `suspends=False`, and the transform classified the call as ordinary. The spec's own phase table says otherwise — phase 2 MONOMORPHIZE, then phase 3 "effect finalize, concrete instances included" — so the fix is the ORDERING: `finalize_effects` becomes a RE-ENTRANT funnel whose docstring names its three entry points, and the driver calls it again right after monomorphization. Sound because the fixpoint is monotone; its three diagnostics (the sync violation, design 260's consuming-suspending fences, DF-223b's existential dispatch) speak once each through an `_effects_reported` ledger. The pin dropped its marker and keeps its name; the stale "clean error" sentence retired from LANGUAGE_SPEC (two faces) and the skill. Stage 4b — the transform ADOPTS instead of building: C1 looks phase 2's registered, instance-checked body up in the merged AST and lifts it into the entry AST instead of cloning its own, and **census row T8 (`_splice_fn_mono`) DELETES** with it, since C1 was its last caller. Measured over 232 coro/generic examples: C1 splices 8 -> 0, rewrites 10 -> 10. Stage 5 — **`SAWC_MONO_SHADOW` RETIRES**, every face of it (`Monomorphizer.shadow`, codegen's `_mono_shadow` and its two call sites, the `_SHADOW`/`_TRACE`/`_DUMP` reads and the four prints they gated, TESTING.md's section rewritten to describe the registry that replaced it and to keep the five demand classes it found). What replaces it is stronger than what it was: every function and method instantiation is a lookup whose miss is an internal error, so the corpus polices the walk on any ordinary run with no switch to remember. **The unit-4 ledger's first entry is authored** in designs/218-enforcement-architecture.md — "what codegen is allowed to know about generics: nothing but the registry", with the layout carve-out stated as representation rather than choice. **STOPPED AND FILED, per conduct: DF-295a** (entry below) — census rows C1-C4, T5's poly-candidate machinery and `_process_effect_monos`'s shell SHRINK rather than delete, and it is ONE mechanism, not four rows: the effect EDGE out of a driven body names the TEMPLATE, because it was recorded when the body was checked, before any instance existed. So a walk over the driven bodies is the only thing that can map a generic call site onto an instance key or give a `sync` caller its edge to a suspending instantiation. PROBED, not argued: with `_effect_record_poly_call` neutralized, `examples/errors/sync_generic_instantiation_suspends.saw` — design 70's key both-ways case — COMPILES, losing the refusal (344 passed / 1 failed on `-f generic,coro,place,poly`). The second half of the mechanism is that an instance body is per-pass (phase 2 splices into the merged AST that `merge_programs` rebuilds), which is DF-292c met from the other side — hence the recommendation to sequence the two together. A real fix DERIVES the effect graph over the monomorphized program; stage 4a's re-entrant finalize is what it would build on. Per-commit gates, all three commits: full suite **2366 passed / 6 xfailed** (2365/7 before, the DF-258a flip and nothing else) + freestanding **33 both arches**. §5 was NOT re-measured: stage 4 adds one monotone fixpoint pass over an existing node dict and stage 5 only deletes, so nothing here touches the `mono_copy` constant Amendment C priced

- Design 263 — panic scratch consolidation + narrow field reads (designs/263-panic-scratch-and-field-reads.md; **USER-RULED Sep 3, all four §3 cells — both L1a+L1b in the split shape, L2 in-brief, L2r in, queue ASAP — and DISPATCHED same day**, Opus worktree, DF range DF-296a+, concurrent with the 218-stages-4/5 branch on disjoint surfaces). The successor to the IMAGE SIZE entry's levers; a back-end size lane (-Oz / machine outliner / riscv save-restore, plus a function-sections+gc-sections emission census cell) is the named NEXT tier after it, unauthored. **ALL UNITS LANDED Sep 3** (branch `worktree-agent-ae3262d1b01283868`, 4 commits) **and the acceptance measurement is the largest image movement this line of work has produced: `process_isolation.elf` .text+.data+.rodata 427,642 -> 140,776 B, -67.1%** (.text section 361,222 -> 81,180, -77.5%; 101,766 -> 25,298 instructions; `end_process` 35,134 -> 5,138 B, -85.4%; `drop_reference`/`staged_count` out of the top twelve entirely; the `andi …, 0x1` bool renorms 2,527 -> 138 and the far-offset `lui`/`sub` triplets 6,082 -> 499). Compile time is unchanged-to-better (clean sos build, warm rt cache: 29.89s real / 29.29s user pre-263 vs 28.32s / 27.69s after). Design 137's observable contract held throughout: all 16 running panic examples produce byte-identical stdout+stderr before and after, `task_backtrace_panic` included. Per unit — **U1** (L1a) one 512-byte panic scratch per FUNCTION via `_panic_scratch`: does what it says (`end_process` 33 -> 1 `alloca [512 x i8]`) but STANDALONE it COSTS 3,122 B, because the backend was already stack-coloring the per-site buffers, so the >=8 KB frame was never the panic scratch and design 261's cause (B) is not downstream of L1a as the census supposed; **U2** (L1b) outlines the assembly into `internal` helpers keyed by message SHAPE plus the panic sink — SIX helpers cover 726 kernel panic sites, -77,036 B (-18.0%), and the seam-ABI fence held (no new `__saw_rt_*`, `rt/ABI.md` untouched); **U3** (L2+L2r) the narrow field read — 1,032 -> 686 aggregate loads in the kernel IR, but +14 B of image, because LLVM's SROA/InstCombine was already doing the narrowing, so it is IR hygiene not a size lever, and L2r's `!range` bool invariant (written out in full beside 261 U2's `_store_transfer`, which rests on the same one) reached only 4 field reads; **U3b** — chasing where U3 did NOT reach found the actual producer, and it is neither panics nor copies: `arr[i]` LOADED THE WHOLE ARRAY and spilled it to an `arr_tmp` alloca just to have something to GEP into, so `PROCESSES[slot].state` cost a 2.4 KB table copy per read. Both the element read and `arr[i].field` now address storage through `_get_element_pointer` — the path every WRITE already took, over the same bounds check — for -286,866 B against baseline. Finding filed: DF-296a (entry below, the `_index_reads_only` allowlist's price)

## ~~DF-258a — a NESTED call to an unconditionally-suspending GENERIC silently
## loses its yield~~ (filed Aug 25 by the 218c spec's probes P3/P3b;
## PRE-EXISTING — pinned at 218 unit 1.5 stage 0)
## **CLOSED Sep 3 by design 218 unit 1.5 stage 4.** The prediction held in its
## architecture and MISSED one link: phase 2 does splice `hop$1$Int` and its
## instance check does mint the effect node with the `yield_now()` recorded as a
## direct source — but `finalize_effects` ran inside the entry check and refused
## to run twice, so the fixpoint that turns a direct source into `suspends` had
## already gone by, the node read `suspends=False`, and the transform classified
## the call as ordinary. The spec's own phase table says otherwise (phase 2
## MONOMORPHIZE, then phase 3 effect finalize "concrete instances included"), so
## the fix is the ORDERING: `finalize_effects` becomes a re-entrant funnel with
## three named entry points, and the driver calls it again immediately after
## monomorphization. Sound because the fixpoint is monotone; its three
## diagnostics speak once each through an `_effects_reported` ledger. The XFAIL
## marker is gone and the pin is the regression test under its own name. Kept
## below as the record.

```saw
func hop<T>(x: T) -> T { yield_now()  x }
func nested(tag: String) -> Int {
    var i = 0
    while i < 2 { let v = hop<Int>(i)  print("{tag} {v}")  i = i + 1 }
    0
}
// two of these spawned into one TaskGroup print `A 0 / A 1 / B 0 / B 1`
```

Both tasks run to completion in turn instead of interleaving: the cooperative
contract is dropped, silently, with no diagnostic. The direct-`yield_now()`
twin interleaves, so the scheduler is not the variable. The emitted
`hop$1$Int` is `ret i64 %x` — the yield is not merely unobserved, it is gone.

MECHANISM: 218b's landing note (c), which found the hole while proving
consumption symmetry sound. Promotion DECLINES for a template that suspends
unconditionally WITHOUT calling a type-parameter method — such a template is
not `poly_candidate`, so no per-instantiation effect node is built and the
coroutine transform has nothing to classify — and codegen's late
monomorphization is then what serves the call. Codegen has no frame machinery,
so it emits the body as a plain function. The documented behaviour promises a
refusal at worst ("suspending calls embed at any nesting depth … or error
cleanly — never silently block"), and LANGUAGE_SPEC + the saw-lang skill both
still carry the sentence that calls this shape a clean error.

Pinned by `examples/coro_nested_generic_call_parks.saw` (cited XFAIL, the
interleaving oracle) and carried as a corodiff axis value
(`nested_generic_susp`), which is the ownership half the parity oracle can see.

CLOSES AT 218 unit 1.5 stage 4, structurally: phase 2 splices the instantiation
as an ordinary concrete function whose own effect node says it suspends, so the
transform's classifier sees an ordinary concrete suspending callee and embeds a
sub-frame — and the path that produced this ("codegen instantiates a suspending
body late, outside the transform") is unrepresentable once codegen can only look
instances up. [218c §6a]

## ~~DF-258b — unbounded RECURSIVE INSTANTIATION has no diagnostic~~ (filed
## Aug 25 by the 218c spec's probe P4; PRE-EXISTING, fuzz-oracle class)
## **CLOSED Sep 1 by design 218 unit 1.5 stage 1**, exactly as the spec staged
## it: the demand fixpoint records `depth = demander's depth + 1` and refuses
## past 64 per CHAIN at the DEMANDING call site, naming the chain in SOURCE
## spelling with the middle elided. Refusal test:
## `examples/errors/generic_instantiation_depth_limit.saw` (ships WITH the fix
## — a hang cannot sit in the corpus as an XFAIL), and it earned its keep
## immediately: a 64-deep `Wrap` chain is what exposed an exponential descent in
## the walk's own argument closure, which had hung a suite worker. Kept below as
## the record.

```saw
struct Wrap<T> { inner: T }
func deepen<T>(x: T, n: Int) -> Int {
    if n <= 0 { return 0 }
    deepen(Wrap<T>(inner: x), n - 1)
}
```

A template that demands ITSELF at a grown argument makes the instance set
infinite. At filing the compiler produced no output in 120 s and was killed;
re-probed Aug 31 it now dies as `internal compiler error … maximum recursion
depth exceeded` at the recursive call, which is Python's own limit arriving
first — an ICE rather than a hang, and the same finding either way. No corpus
pin is legal for a hang, so the refusal test ships WITH the fix.

MECHANISM: `_instantiate_generic_function` recurses through
`_generate_function_call`, building `deepen$1$Wrap$1$…` forever. Nothing counts
depth, because nothing decides the instance set as a whole — codegen discovers
instances lazily and one at a time, so there is no place a chain length exists
to be bounded.

CLOSES AT 218 unit 1.5 stage 1: the demand fixpoint records `depth = demander's
depth + 1` (roots at 0) and refuses past 64 per CHAIN with a clean error at the
DEMANDING call site naming the elided chain. Per-chain, so wide-but-shallow
programs are untouched, and it refuses only what today cannot finish.
[218c §1d, §6b]

## DF-293a..c — filed Sep 3 by design 261; a FIXED in that branch, b and c
## OPEN. Evidence in designs/reviews/261-receiver-flip-consumer-sweep.md

**DF-293a — FIXED (design 261 U1b, commit ec0b7531).** A method receiver whose
path is rooted in a CALL was evaluated TWICE. `_generate_method_call` generates
the receiver expression once to name its type, and the by-pointer arms then
re-walk the same expression to ADDRESS it (`_get_member_pointer`,
`_get_element_pointer`, `_get_tuple_element_pointer`, a `&var` reference for
`o!`). Rooted in a binding the second walk is a GEP and recomputes nothing;
rooted in a call it ran the call again — `mk().c.tick()` printed
`tick=1 mkcalls=2`, the mutation landing in the second result and the first
discarded, silently, exit 0. PRE-EXISTING and reachable only for `&var self`,
cell-carrying and `borrows` receivers, which is why it had never been seen; the
261 flip puts every aggregate `&self` call on those arms, so it was fixed ahead
of the flip rather than filed and left. `_receiver_path_is_lvalue` is the guard
and `examples/receiver_temporary_evaluated_once.saw` the pin (four re-walked
shapes plus two lvalue controls).

**DF-293b — CLOSED Sep 3 (user ruling at 261's integration: the inferred form
is enough; revisit only if llvmlite is bumped for other reasons).** Design 261
U1 rules the flipped
receiver `noalias readonly`. `noalias` is stamped; `readonly` has no supported
spelling — `llvmlite.ir.values.ArgumentAttributes._known` omits the PARAMETER
attribute and lists only the unrelated function-level one, and `add_attribute`
refuses an unlisted name. Reaching into the dependency's table to add one is not
this compiler's business, so `_mark_readonly_arg` tries and reports whether it
landed; a future llvmlite that lists it starts working with no other edit. The
cost is small and measured: sawc emits ONE module, so FunctionAttrs sees every
receiver body and infers the attribute itself —
`define i64 @Big_total(ptr noalias readonly captures(none) %self)` is the
emitted IR. `noalias` is the half inference cannot supply (it is a promise about
the CALLER), which is why that half is stated. Close by bumping llvmlite, or by
deciding the inferred form is enough.

**DF-293c — CLOSED Sep 3, RULED (user, at 261's integration): primitives stay
BY VALUE. The asymmetry is accepted — address identity is the only observable,
nothing relies on it, and the pin's last row is the contract.** Design 261 §4
fences primitive
receivers with two clauses that point opposite ways: "primitive receivers stay
by value" and, of `(&self) as UnsafePointer` on one, "probe it, and if
observable, align it". The probe says it IS observable.
`extension Int { func addr(&self) unsafe -> Int { (&self) as UnsafePointer<Int>
as Int } }` compiles today with no fence and yields the callee's SPILL address,
so `p.addr() == (&p) as UnsafePointer<T> as Int` is `false` for
`Int`/`String`/payload-free enum and, after the flip, `true` for every struct.
Only address IDENTITY differs — a read through the derived pointer gives the
same bits either way and a write is discarded either way — and it is NOT a
regression, since primitives behave identically before and after. What the flip
introduces is the type-dependent ASYMMETRY, where the predicate used to be
uniformly `false` for `&self`. No corpus site relies on either answer. Left as
the headline ruling says (by value) rather than inferred either way; pinned as
the last row of `examples/self_receiver_pointer_reaches_caller.saw`, which will
need its expectation flipped if the ruling goes the other way.

