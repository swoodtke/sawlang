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

