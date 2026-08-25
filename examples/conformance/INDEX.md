# The conformance suite — one row per claimed safety guarantee

Every row of the Aug-8 safety-guarantee audit (`safety_audit.md`, 247 rows
across 14 categories) is listed here with the test that checks it. A row is
either a file in this directory or an existing `examples/` test that already
asserts the same rule at the same position — this table is the record of which,
and the dedup decisions are meant to be audited from it.

**454 rows: 347 carry a file here, 107 are covered elsewhere** (recounted Aug 16
from the table itself — the audit-era "121 here, 198 elsewhere" had gone stale
across the briefs listed below). (The audit's 247 plus
the rows later briefs added: W02-W05, design 194 unit 4; W06-W19, design 195
unit 1; X41-X45, design 199 unit 1; M31-M35, design 200 unit 1; V26-V30,
design 202 unit 1; B09-B12, design 204 unit 1; K14-K20, design 201 unit 1;
K21-K25, design 210 units 1 and 5; S09, O12 and K26, the DF-217a/b/c fixes; O13,
the DF-217l leak their sweep turned up; K29, design 219 unit A1 (renumbered
from K27 at integration — the 218a spec pre-registered K27/K28); U28-U29 and
V31, design 219 unit A2; K27-K28, design 218 unit 1; V32-V35, design 219 wave B;
V36-V47, K30, K31 and U30, design 219 wave C; R39-R42 and M36, design 218
stage 3; G01-G15, design 221 unit B1; G16-G18, design 221 unit B4's return-site
sweep; K32, design 222 unit 1; K33-K39, design 223's suspending-method position
matrix; M37-M42, design 227 unit 1, and M43-M44, the two siblings its unit-3
walk closed; K40-K47, design 224's container-head position matrix; K48-K62,
design 225's TaskGroup wake matrix; K63-K68, design 230 units A, B and C;
D01-D20, design 228's divergence position matrix — D15-D20 are the six that
point at tests written before the brief, which is what makes the fourteen new
files auditable as the ONLY gap it had to fill; U31-U36, design 226 unit 2's
closed-construction rows; R43-R44, the two STORE positions DF-216e's fix
closed; B18-B19, DF-232n's relative-path package identity; B20-B22, the Aug-21
signature-visibility ruling; W20-W24, design 205 unit 1's transfer-position
matrix; K70-K73, design 218 unit 2's scope-end migration and its two
emission residues; K74, DF-219c's bound-aware spawn capture audit; K75,
DF-218v's try/catch error edge — K74/K75 renumbered from K72/K73 at
integration, where the two Aug-21 branches collided; K76, DF-218x's
optional-binding branch scope, K77, DF-218y's discard order, B23,
DF-238c's orphan-rule coherence across import forms, and A02, DF-245a's
`init` declared-return rule.)

## How to read it

- **Row** — the audit's id. `M07`, `X30` and so on are stable across the audit,
  the design briefs that cite them, and this table.
- **Covered by** — the file that checks the row. A path with no directory is
  a file in `examples/conformance/`; anything else is relative to `examples/`.
- **Ruling** — present when a design brief SUPERSEDED the audit's expectation.
  The audit ran before designs 186-189 and 193 landed, so its recorded status
  is history: every row here was re-compiled against the tree and authored to
  what the compiler does now, and where that differs from the audit the brief
  that decided it is named.

## Conventions

- **A row ports when no existing test asserts its rule AT ITS POSITION.**
  Sharing a diagnostic is not enough on its own: `errors/immutable.saw` and
  row M19 (assigning a by-value parameter) print the same message from two
  different positions in the mutability walk, so M19 has its own file. Where
  an existing test does cover the position, the row points at it rather than
  growing a second copy.
- **Every file names its row in the first comment line** (`// Conformance row
  M22 — …`), so a failure report leads back to this table.
- **Helper modules live in `modules/`** and are reached with
  `--module-path <name>={TESTDIR}/modules/<name>`. The runner excludes any
  `modules/` directory from discovery, so they are never run as tests.
- **A regressing row is a red FAIL.** The XFAIL policy applies unchanged: a
  marker is legal only as the pin of a filed DF, cited in its reason.
- **A brief that touches a safety guarantee adds or updates its rows FIRST**
  (design 190's third process rule), and the commit that fixes a conformance
  regression updates the row — it never deletes it.

## Running them

```bash
./.venv/bin/python test_runner.py -f conformance/    # the suite alone (~9s)
./.venv/bin/python test_runner.py                    # they run in the battery too
```

## Mutability — a non-`var` binding cannot be mutated

Claim source: spec 2 *Variables and Mutability* + 4 *Reference Types*; designs 40, 132, 146, 176, 179

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| M01 | assigning to a `let` local | `errors/immutable.saw` |  |
| M02 | compound-assigning a `let` local | `errors/compound_assign_immutable.saw` |  |
| M03 | `&var x` where x is a `let` | `errors/ref_sigil_var_on_let.saw` |  |
| M04 | writing a field of a `let` struct | `let_struct_field_assign_error.saw` |  |
| M05 | `&var self` method on a `let` receiver | `let_var_self_method_error.saw` |  |
| M06 | `v.push` on a `let` Vector | `M06_push_on_let_vector.saw` |  |
| M07 | writing a fixed-array element of a `let` | `errors/array_immutable.saw` |  |
| M08 | writing a Vector element of a `let` root | `errors/place_exclusive_window_immutable_root.saw` |  |
| M09 | writing a tuple element of a `let` root | `errors/df151j_tuple_let_root_assign.saw` |  |
| M10 | mutating through a shared `&T` parameter | `M10_write_through_shared_ref.saw` |  |
| M11 | whole-referent replacement through a `&T` | `reference_assign_error.saw` |  |
| M12 | `&var self` method through a `&T` parameter | `M12_varself_method_through_shared_ref.saw` |  |
| M13 | `&self` method writing its own field (design 176) | `errors/shared_self_field_write.saw` |  |
| M14 | `&self` method calling a `&var self` method on self (DF-179b) | `errors/shared_self_var_method_call.saw` |  |
| M15 | `&self` method calling `&var self` on a field (DF-176b) | `errors/shared_self_field_var_method_call.saw` |  |
| M16 | `&self` method projecting `&var self.field` | `errors/var_ref_into_shared_self.saw` |  |
| M17 | assigning to a `for`-loop variable | `M17_assign_for_loop_var.saw` |  |
| M18 | assigning to an `if let` payload binding | `errors/if_let_immutable.saw` |  |
| M19 | assigning to a by-value parameter | `M19_assign_parameter.saw` |  |
| M20 | writing a by-value closure capture (design 132) | `errors/capture_assign_escaping.saw` |  |
| M21 | writing a field of a by-value struct capture | `M21_write_field_of_capture.saw` |  |
| M22 | place write through a `borrows` accessor on a `let` root | `M22_place_write_let_root.saw` |  |
| M23 | writing through the `&T` a shared borrow hands out | `M23_write_through_shared_borrow.saw` |  |
| M24 | `&self` borrows body writing a field in the epilogue (DF-175a) | `errors/shared_self_borrows_epilogue_write.saw` |  |
| M25 | `m[k]! = v` on a `let` Map root | `errors/map_subscript_immutable_root.saw` |  |
| M26 | `&var self` method on a `let` of an auto-Copy struct | `M26_varself_on_let_implicitcopy.saw` |  |
| M27 | interior mutability: Atomic field mutated at `&self` | `atomic_field_self_method.saw` |  |
| M28 | indirection carve-out: `self.rows[0].push` at `&self` | `shared_self_field_call_exemption.saw` |  |
| M29 | `&var` parameter mutation is visible at the caller | `references_basic.saw` |  |
| M30 | writing an immutable module `static` | `errors/static_assign_whole.saw` |  |
| M31 | `&self` method writing through a place window on INLINE storage — the rule's seven-position matrix (DF-176c) | `M31_shared_self_place_window_write.saw` | 200 — the last surviving member of the vanishing-write family; the write landed in the receiver copy and printed `first 1` |
| M32 | indirection carve-out through a place WINDOW: `self.rows[0][0] += 100` at `&self` | `M32_shared_self_place_window_heap_field.saw` | 200 — the accept side of the same ruling: the copy shares the buffer |
| M33 | a place write in the PROLOGUE of a `&self` borrows body | `M33_borrows_body_prologue_place_write.saw` | 200 — RATIFIED as intended: an accessor's receiver travels by pointer, so the write lands |
| M34 | a `#lend_var`-gated place write, exclusive specialization only | `M34_lend_var_gated_place_write.saw` | 200 — ratified with M33; the gate picks the flavor that pays |
| M35 | the same inline-field window write declared `&var self` | `M35_var_self_place_window_write.saw` | 200 — the fix M31's diagnostic names |
| M36 | a `[&self]` capture NARROWS a `&var self` receiver, and the body's write is refused | `M36_shared_self_capture_refuses_write.saw` | 218 §4 — the capture mode joins the rule, through one funnel (`_self_borrow_is_exclusive`) the five write-through-`self` sites share |
| M37 | `let` immutability of INLINE array storage at every write shape — six shapes × plain/compound (DF-225j) | `M37_inline_array_immutability_every_shape.saw` | 227 — two lvalue-root walks each stopped one hop short, so eight of the twelve cells wrote a `let`; one ArrayIndex-transparent walk answers them all |
| M38 | a COMPOUND assignment's RHS may not borrow the path it writes (DF-225i) | `M38_compound_assign_rhs_exclusivity.saw` | 227 — design 193 unit 4's check had an unnamed third entry point; compound also READS the target, so the overlap is read+write |
| M39 | an optional-CHAIN assignment through a `&self` receiver is refused (DF-225k) | `M39_chain_assign_through_shared_self.saw` | 227 — DF-175a's vanishing write, fifth spelling: the chain path deferred `self` to "governed by `&var self`" and nothing governed it |
| M40 | `o?.n += v`, the compound spelling of design 111's chain assignment (DF-225l) | `M40_compound_chain_assign.saw` | 227 — the parser recognized an OptionalEvalExpr target on the plain branch only |
| M41 | the indirection carve-out at every accessor spelling: `Vector`, `Map`'s `m[k]!`, a named accessor, `Data`, a nested chain | `M41_shared_self_indirection_carveout_spellings.saw` | 200 — the accept side of the DF-225g sweep's table, and design 227's must-not-flip pin |
| M42 | a `&self` method writing an INLINE `[T; N]` element, both spellings | `M42_shared_self_inline_array_element.saw` | 200 — the refuse side of the same table; the pair the DF-225g scan mistook for a hole |
| M43 | writing the PAYLOAD of a `let` optional (`o!.n = 5`) | `M43_write_optional_payload_of_let.saw` | 227 — the same one-hop-short walk as M37, on the payload projection |
| M44 | a `&var self` method reached through an INLINE array element of a `let` root | `M44_var_self_call_through_inline_array_element.saw` | 227 — the RECEIVER half of DF-225j: the write spelling was refused and the method spelling ran |

## References are parameters only — they can never escape

Claim source: spec 4 *Reference Types*; designs 88, 106, 163d, 188 u1, 193 u5, 216

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| R01 | free function returning `&Int` | `errors/ref_return_dangles.saw` |  |
| R02 | extension method returning `&Int` | `errors/ref_return_method.saw` |  |
| R03 | trait requirement returning `&Int` | `errors/ref_return_trait_method.saw` |  |
| R04 | `extern func` returning `&Int` | `errors/ref_return_extern.saw` |  |
| R05 | function TYPE naming a reference return | `errors/ref_return_function_type.saw` |  |
| R06 | return type `(Int, &Int)` names a reference | `errors/ref_return_nested_in_tuple.saw` |  |
| R07 | return type `&Int?` | `R07_return_optional_ref.saw` |  |
| R08 | return type `Vector<&Int>` | `R08_return_vector_of_ref.saw` |  |
| R09 | struct field of reference type | `errors/ref_field_type.saw` |  |
| R10 | enum case payload of reference type | `enum_ref_payload_escape.saw` | 188 u1 — was a DEVIATION (accepted, reached `Vector` storage, ICEd on read); refused at the payload now |
| R11 | `let r = &x` binds a reference | `errors/ref_nonarg_binding.saw` |  |
| R12 | `var r = &var x` binds a mutable reference | `errors/ref_sigil_nonarg_position.saw` |  |
| R13 | generic argument in a type position: `Vector<&Int>` | `errors/ref_type_arg_generic_struct.saw` |  |
| R14 | explicit instantiation `idn<&Int>(&x)` | `errors/ref_type_arg_generic_func.saw` |  |
| R15 | closure whose inferred return is a reference | `errors/ref_closure_return_inferred.saw` |  |
| R16 | array literal holding references | `R16_array_literal_of_refs.saw` |  |
| R17 | tuple literal holding a reference | `R17_tuple_literal_holds_ref.saw` |  |
| R18 | Map with a reference value type | `R18_map_value_ref.saw` |  |
| R19 | `static` of reference type | `errors/ref_static_declaration.saw` |  |
| R20 | type alias laundering a reference into a struct field | `typealias_ref_launder.saw` | 188 u1 — was a DEVIATION (the walk read types as written); aliases resolve before the walk now |
| R21 | type alias laundering a reference into a return type | `R21_alias_launders_ref_return.saw` | 188 u1 — failed by accident on a type mismatch; fails by rule now |
| R22 | borrow-capture in an escaping closure bound to a `let` | `errors/capture_borrow_escaping.saw` |  |
| R23 | borrow-capture in a closure returned from a function | `R23_returned_closure_borrow_capture.saw` |  |
| R24 | borrow-capture in a spawned closure | `spawn_capture_after_group.saw` | 188 u5 + 189 — was a NOTE (accepted); the capture is refused because `x` is declared AFTER its group |
| R25 | spawned task frame taking a reference parameter (design 88) | `K14_spawn_ref_param_join_releases.saw` + `K19_spawn_ref_param_mt_send.saw` | 201 — SUPERSEDED. The blanket refusal is retired and the row is an ACCEPTANCE for a single-threaded group: the reference does not escape, it borrows its root for the task's life (K15/K18/K20 are the refusals that makes sound). An MT group still refuses, on Send (K19). The old pin `coro_spawn_ref_rejected.saw` is retired with the rule |
| R26 | `Optional<&Int>` spelled via the written name | `R26_optional_written_name_ref.saw` |  |
| R27 | reference inside a nested generic (`Box<Vector<&Int>>`) | `R27_nested_generic_ref.saw` |  |
| R28 | the sanctioned crossing `(&var n) as UnsafePointer<Int>` | `ref_pointer_cast_blessed.saw` |  |
| R29 | `(&x) as Int` — not a pointer target | `errors/ref_cast_to_int_not_blessed.saw` |  |
| R30 | non-escaping borrow capture, closure passed directly | `closures_borrow_capture.saw` |  |
| R31 | `&` as a binary-expression operand | `R31_ref_as_binary_operand.saw` |  |
| R32 | storing a reference in a `Box` | `R32_box_of_ref.saw` |  |
| R33 | `borrows -> &Int` (a place whose type is a reference) | `R33_borrows_lends_ref_type.saw` |  |
| R34 | struct field whose type is a ref-returning function type | `R34_field_of_ref_returning_fn_type.saw` |  |
| R35 | PLAIN capture of a `&T`/`&var T` PARAMETER by an escaping closure | `closure_captures_reference_param_escaping_error.saw` | 216 — was a DEVIATION (accepted silently). R22-R24 covered the `[&x]` SPELLING only; a reference-typed binding captured plainly is the same pointer-into-the-frame and bypassed the rule, compiling to `store ptr %r` into a HEAP env (DF-216d). One predicate now covers both spellings |
| R36 | a closure naming `self`, escaping the method's frame | `closure_captures_self_escaping_error.saw` | 216 — a receiver IS a borrow, so this is the implicit third spelling of R35. Previously unreachable: any closure naming `self` ICEd (DF-216a) |
| R37 | a closure naming `self` in a NON-escaping closure — the acceptance | `closure_captures_self.saw` | 216 — the legal side, matching R30. Reads see the live receiver and a `&var self` write reaches the caller |
| R38 | the same, inside a SUSPENDING method | `closure_captures_self_suspending.saw` | 216 — was OPEN (DF-216g), CLOSED by 218 stage 3. A frame lends its receiver to a closure by minting a second `UnsafeRef` handle: the env owns it by move, `deref()` lends the referent, and the body reads the live receiver |
| R39 | the EXPLICIT `[&self]` / `[&var self]` spelling, sync and suspending | `R39_explicit_self_borrow_capture.saw` | 218 §4 — the spelling exists so the coroutine transform can EMIT the receiver capture as code a programmer could have written. Same capture as R37's implicit one, same non-escaping rule |
| R40 | `[&var self]` in a `&self` method | `R40_var_self_capture_needs_var_receiver.saw` | 218 §4 — the mode decides whether the body may write through the capture, and a shared receiver has no exclusive borrow to hand out |
| R41 | the explicit `[&self]` spelling, escaping | `R41_explicit_self_capture_escaping_error.saw` | 218 §4 — writing the `&` out loud says nothing new about where the closure goes, so R36's refusal covers it. A new spelling that bypassed the rule would be a hole with an author's signature on it |
| R42 | `[self]` / `[move self]` — not spellings | `errors/capture_self_requires_borrow_sigil.saw` + `errors/capture_self_move_requires_borrow_sigil.saw` | 218 §4 — a receiver's own mode dictates the capture's, so only the `&`-sigilled forms are offered; a consuming `self` receiver captures by value with no list |
| R43 | borrow-capture STORED into a container reached through a `&var` parameter | `escaping_closure_borrow_capture_stored.saw` | DF-216e — was a DEVIATION (accepted, IR-confirmed dangling). `out.push({ n * 2 })` is a call argument like R30's, so the position test accepted it; what separates them is the PARAMETER TYPE, and nothing under a `&var Vector<F>` was ever stamped escaping because the walk skipped REFERENCE |
| R44 | the same store into a LOCAL container, element type written by the constructor | `escaping_closure_borrow_capture_local_container.saw` | DF-216e — the second route to R43's hole: a generic ARGUMENT written in an EXPRESSION reaches no declared-type walk, so `Vector<() sync -> Int>()` bound a non-escaping element. A generic argument is never a parameter role |

## The Law of Exclusivity — one writer XOR many readers

Claim source: spec 4 *Reference Types* + *Places*; designs 34, 106, 141, 188 u2, 193 u4, 199

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| X01 | `f(&var x, &var x)` — same root twice mutably | `exclusivity_swap_same_var.saw` |  |
| X02 | `f(&var x, &x)` — a writer aliased by a reader | `X02_varref_aliased_by_shared.saw` |  |
| X03 | `f(&var p, &p.x)` — whole overlapping its own field | `exclusivity_parent_child.saw` |  |
| X04 | `f(&var p.x, &p.y)` — disjoint fields | `exclusivity_disjoint_fields.saw` |  |
| X05 | `f(&x, &x)` — two shared reads may overlap | `exclusivity_shared_reads.saw` |  |
| X06 | `f(&var a[i], &a[j])` — dynamic indices, conservatively refused | `exclusivity_dynamic_index.saw` |  |
| X07 | `f(&var a[0], &a[1])` — constant distinct indices are disjoint | `exclusivity_const_indices.saw` |  |
| X08 | `f(&var t.0, &t.0)` — same tuple element | `errors/df151j_tuple_element_exclusivity.saw` |  |
| X09 | `f(&var t.0, &t.1)` — disjoint tuple elements | `X09_disjoint_tuple_elements.saw` |  |
| X10 | a `move` argument aliasing a reference argument in one call | `exclusivity_move_and_ref.saw` |  |
| X11 | `&var self` receiver with a `&self.field` argument | `exclusivity_var_self_receiver.saw` |  |
| X12 | forwarding an incoming `&` as `&var` (illegal upgrade) | `errors/ref_forwarding_upgrade.saw` |  |
| X13 | forwarding `g(&var r, &r)` out of one incoming `&var` | `errors/ref_forwarding_exclusivity.saw` |  |
| X14 | `v.push` inside a `with_ref` window on the same vector | `X14_push_inside_with_ref.saw` |  |
| X15 | `v.push` inside a place window (the place charges its root) | `errors/place_window_beside_var_root.saw` | 188 u2 — was refused by the COPY POLICY; an exclusivity diagnostic now |
| X16 | two exclusive place windows on one Vector in one call | `place_window_exclusivity.saw` | 188 u2 — was refused by the COPY POLICY; an exclusivity diagnostic now |
| X17 | nested windows `b[0][1].n += 1` | `X17_nested_windows.saw` |  |
| X18 | `&var` held across a suspension still addresses the caller's value | `coro_ref_param_compound_assign.saw` | 187 — was a DEVIATION (`n += 1` after a suspension ICEd); runs now |
| X19 | a `&var` forwarded three deep still reaches the root | `ref_forwarding.saw` |  |
| X20 | a named accessor's place charges its root against a `&var` of the root | `place_window_exclusivity.saw` | 188 u2 — was refused by the COPY POLICY; an exclusivity diagnostic now |
| X30 | two exclusive windows on a TRIVIALLY copyable struct | `place_window_exclusivity.saw` | 188 u2 — was a DEVIATION (accepted, both writes lost); refused now |
| X31 | a window on a trivial struct beside a `&var` of the same root | `errors/place_window_beside_var_root.saw` | 188 u2 — was a DEVIATION (accepted, the `&var` argument's writes lost); refused now |
| X33 | two exclusive windows on an AUTO-Copy struct (String member) | `X33_two_windows_implicitcopy_struct.saw` | 188 u2 — was a DEVIATION (accepted on the auto-Copy tier); refused now |
| X40 | std `Data` (Copy, has `d[i]`) — two windows in one call | `errors/place_window_data_corruption.saw` | 188 u2 — was a DEVIATION (std `Data` corrupted: `d0=1 d1=1`); refused now |
| X41 | `sink(&var p.a, reset(&var p))` — a nested call's `&var` overlapping a sibling, no place involved | `X41_nested_call_ref_overlaps_sibling.saw` | 199 — the DF-188j shape; was a DEVIATION (accepted, `a=107 b=200` by evaluation order); refused now |
| X42 | `f(&var x, g(&y))` — a nested reference onto a disjoint root | `X42_nested_call_ref_disjoint_roots.saw` | 199 — the accept side of the ruling |
| X43 | a nested reference disjoint from every sibling (different root, and a disjoint field of one root) | `X43_nested_ref_disjoint_from_every_sibling.saw` | 199 — the overlap test is unchanged, only the access set widened |
| X44 | `p.m(reset(&var p))` — a nested call's `&var` overlapping the RECEIVER | `X44_nested_call_ref_overlaps_receiver.saw` | 199 — probed: the receiver borrow did NOT catch it (printed the pre-reset total); refused now |
| X45 | `f(g(&var n), h(&var n))` — two nested calls borrowing one root | `X45_two_nested_calls_one_root.saw` | 199 — was a DEVIATION (accepted, answered by evaluation order); refused now |

## Moves and use-after-move

Claim source: spec 4 *The Copy Trait Family* + *Move-Only Types*; designs 34, 131, 139, 159, 202

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| V01 | using a binding after `move` | `errors/use_after_move.saw` |  |
| V02 | moving one binding twice | `errors/use_after_move_double_move.saw` |  |
| V03 | `move` out of a `&var` parameter | `reference_move_error.saw` |  |
| V04 | `move` out of a `&` parameter | `V04_move_out_of_ref.saw` |  |
| V05 | partial move `move h.v` | `errors/partial_move_field.saw` |  |
| V06 | `move` in a loop body (moved again on the next iteration) | `errors/use_after_move_loop.saw` |  |
| V07 | conditional move followed by an unconditional use | `errors/use_after_move_branch.saw` |  |
| V08 | a moved `var` revived by reassignment is usable again | `use_after_move_revive.saw` |  |
| V09 | implicit copy of an ExplicitCopy value at a transfer | `explicit_copy_requires_move.saw` |  |
| V10 | implicit copy of a NoCopy value at a transfer | `errors/no_copy.saw` |  |
| V11 | `.copy()` on a NoCopy type | `V11_copy_on_nocopy.saw` |  |
| V12 | moving a by-value capture out of a closure body | `V12_move_capture_out_of_closure.saw` |  |
| V13 | use after `move` into a struct literal | `errors/use_after_move_field_init.saw` |  |
| V14 | use after passing by value to a function | `errors/use_after_move_call_arg.saw` |  |
| V15 | `move o!` retires the whole binding, then it is used | `errors/optional_move_unwrap_retires.saw` |  |
| V16 | value-read of a NoCopy element out of `v[i]` | `errors/vector_get_nocopy_alias.saw` |  |
| V17 | value-read of a NoCopy value out of `m.get(k)` (DF-146j) | `errors/map_get_nocopy_value_read.saw` |  |
| V18 | `let _ = <NoCopy binding>` without `move` | `V18_discard_nocopy_without_move.saw` |  |
| V19 | struct owning a Vector with no declared copy policy | `errors/explicit_copy_containment.saw` |  |
| V20 | enum with a NoCopy payload and no declared policy (design 139) | `enum_policy_bare_owning_error.saw` |  |
| V21 | `Vector<Int>?` transferred without move/copy (design 139) | `V21_optional_explicitcopy_transfer.saw` |  |
| V22 | `.copy()` on a tuple with a NoCopy element | `df151i_tuple_copy_nocopy_error.saw` |  |
| V23 | declaring `extension T: Deinit {}` by hand (design 131) | `errors/deinit_needs_copy_policy.saw` |  |
| V24 | calling `deinit()` manually | `errors/manual_deinit.saw` |  |
| V25 | deinit-once through an auto-Copy struct copy (design 159 retain) | `V25_implicitcopy_deinit_once.saw` |  |
| V26 | `let b = a` on an `Atomic<Int>` local | `V26_copy_atomic_local.saw` | 202 — DF-186a: copying an atomic forked the counter silently, and had since design 41; move-only now |
| V27 | a struct holding an `Atomic` field with no declared policy | `V27_atomic_field_no_policy.saw` | 202 — an `Atomic` field contributes `NoCopy`, so the containment cascade names the field like any other |
| V28 | control: the declared-NoCopy holder builds, mutates and moves | `V28_atomic_holder_declares_nocopy.saw` | 202 — the accept side; one line of policy is the whole migration |
| V29 | control: a `static Atomic<Int>` mutated in place and lent by `&` | `V29_static_atomic_unaffected.saw` | 202 — statics are unaffected: a NoCopy static is legal and every atomic op takes `&self` |
| V30 | `move` of an `Atomic` local, into a binding, a call and a struct | `V30_move_atomic_local.saw` | 202 — `NoCopy` and deliberately not `NoMove`: nothing pins an atomic's address |
| V31 | `move v[0]` on a `Vector` — design 35 intact for every SAFE-rooted place | `V31_move_out_of_vector_element.saw` | 219 A2 — the regression fence on the carve-out: the rule is keyed on the place's root, so a place whose occupancy the language tracks keeps the refusal and the occupancy-maintaining outs (`swap_out`, `pop`) |
| V32 | a Copy-family bound is satisfied by the DERIVED tier, not a declaration | `V32_copy_bound_is_tier_derived.saw` | 219 B2 — bounds checked declared conformances while tiers were a separate derivation and the two had never met, so `T: Copy` rejected `Int` AND an auto-tier `Bag { s: String }` (the very type design 139 says is on that tier owing no declaration). Every family on the tier is checked through the one bound: trivial, automatic, declared hook, composite |
| V33 | an ExplicitCopy argument is REFUSED at a silent-copy bound | `V33_explicitcopy_refused_at_silent_bound.saw` | 219 B2 — S1 row 9d was a MISCOMPILE, not a semantic to preserve: `T: Copy` admitted the ceremony tier into a body that duplicates `T` unwritten, and the re-bind lowered to a bitwise copy of a `Vector` (two owners, one buffer). `Copy` now names the silent tier alone, so the refusal lands at the call with the type named |
| V34 | `T: ExplicitCopy` is the whole DUPLICABLE family, and licenses `.copy()` | `V34_explicitcopy_bound_is_the_copyable_family.saw` | 219 B2 — the other half of V33: `Copy` names what duplicates silently, `ExplicitCopy` what duplicates at all. Every Copy-tier type satisfies it (copying one for free is a valid `copy()`), so one bounded body serves `Int`, `String` and `Vector<Int>`, each lowering at its own tier |
| V35 | iterating a `Vector<Vector<Int>>` survives the collapse, via borrows | `vector_nested_each_borrows.saw` | 219 B1 — the shape enforcement would otherwise have broken. The old by-value `each` reached an ExplicitCopy element only because a `T: Copy` bound admitted the ceremony tier; design 216's `&T` closures move iteration to the borrow path FIRST, which is the sequencing constraint judgment site 2 records |
| V36 | a generic body binding a `T` value twice is refused AT THE CALL at a move-only argument | `V36_generic_body_double_bind_refused_at_call.saw` | 219 C1 — DF-217i's head. An abstract `T` answered every copy-tier question most permissively and nothing re-judged the body at instantiation, so this compiled into three releases of one value with a read after two of them. The requirement is inferred from the body once and discharged at every call site |
| V37 | a generic body reading a `T` out of storage it does not own requires `Copy`, however few times the name appears | `V37_generic_body_field_read_requires_copy.saw` | 219 C1 — the DF-217i EXTENSION (S1 p1). No partial move exists out of a borrowed `self`, so a PROJECTION read is a duplicate on sight; only a whole-binding read gets the benefit of the doubt from the move dataflow |
| V38 | the requirement PROPAGATES through a forwarding hop | `V38_generic_requirement_propagates_through_forwarding.saw` | 219 C1 — S1 row 10 widened the leak to six deinits by nesting. Discharge runs to a fixpoint, so a generic wrapper cannot hide a duplicating body behind a move-only-looking signature |
| V39 | the rule reaches a generic METHOD and a generic STRUCT's method, discharged against the RECEIVER's type arguments | `V39_generic_method_body_honors_copy_tier.saw` | 219 C1 — S1 row 12 found both positions leaking identically. The extension's parameter is judged even though no call site writes it |
| V40 | a generic COROUTINE gets the same judgement, BEFORE the transform runs | `V40_generic_coroutine_body_honors_copy_tier.saw` | 219 C1 — S1 row 8a. The post-transform re-check saw the same abstract `T` the first check saw, so "the generated code typechecks" was satisfied vacuously. The requirement is a property of the AUTHORED body |
| V41 | control: branch-exclusive uses are ONE use per path, so the body stays move-only | `V41_branch_exclusive_uses_stay_move_only.saw` | 219 C1 — the false-positive class. `if a < b { b } else { a }` mentions each parameter twice and duplicates neither; a name-counting rule would have tightened three corpus generics. Correct because the inference asks design 15's dataflow, which has merged branches since it was written |
| V42 | control: the duplicating body still works at every tier that can satisfy it | `V42_copy_argument_to_duplicating_body_runs.saw` | 219 C1 — the accept side. Primitives, `String`'s retain and design 139's AUTOMATIC tier all pass one bounded body, each duplicate lowering at its own tier. Without this row the refusal could be delivered by a rule that refuses generic duplication outright |
| V43 | the `.copy()`-needs-a-bound rule over COMPOSITE receivers — `(T, Int)`, `T?`, `[T; N]`, nested | `V43_copy_call_needs_a_bound_through_wrappers.saw` | 219 C2 — DF-217q. The rule was written once, for a bare `T`, so every wrapper reached its own arm instead, and each of those reasons about the WRAPPER: the tuple arm's comment promised the tuple "settles at the instantiation" and nothing ever settled it. One funnel, gated on the abstract tier |
| V45 | a module-PUBLIC generic whose inferred requirement exceeds move-only must DECLARE its bound | `V45_public_generic_must_declare_its_requirement.saw` | 219 C4 — the API-stability trade the brief calls out by name, ruled HARD-REQUIRE: pure inference means editing a body can tighten a published contract with no signature change, and a contract enforced only by an off-by-default warning is not a contract. `public` on a METHOD carries the same obligation, design 80 making members private-by-default |
| V46 | a DECLARED copy-family bound the body exceeds is a definition-time error; a private generic rides inference | `V46_declared_bound_the_body_exceeds.saw` | 219 C4 — `<T: ExplicitCopy>` licenses a SPELLED `.copy()` and nothing more, so a body reading the value out unwritten is design 146's sentence exactly. Caught at the declaration, where the author can act on it. The private control is the other half: the rule is not "every generic must declare" |
| V47 | control: returning a whole binding out of a generic body is a MOVE | `V47_generic_return_of_a_local_is_a_move.saw` | 219 C4 — std's tail-expression idiom (`SpinLock.lock`'s `let result = body(...)` / `result`). It was a live false positive: the tail check runs after the body scope is popped, so the name no longer resolved and every generic returning a local looked like a read out of storage it does not own. Surfaced the moment the public rule reached methods, which is what a hard error buys over a warning |
| V44 | control: the bounded wrapper copies really work, at both duplicable tiers | `V44_bounded_wrapper_copy_runs.saw` | 219 C2 — the accept side, and the fix to the ARRAY arm the row found: `type_satisfies_explicit_copy_bound` answers from the tier alone, so `[T; 2]` under a declared `<T: ExplicitCopy>` came back False and the one spelling the bound exists to license was refused |

## Places (`borrows` / `lend`) — window discipline

Claim source: spec 4 *Places (`borrows` and `lend`)*; designs 141, 146, 179, 188 u3

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| P01 | `return <value>` in a `borrows` body | `errors/borrows_returns_value.saw` |  |
| P02 | a `borrows` path that never lends | `errors/borrows_lend_coverage_partial.saw` |  |
| P03 | two `lend`s on one path | `errors/borrows_lends_twice.saw` |  |
| P04 | `lend` inside a loop | `errors/borrows_lend_in_loop.saw` |  |
| P05 | `lend` of a value the accessor just built | `lend_accessor_local.saw` | 188 u3 — was a DEVIATION (accepted; writes vanished); refused now |
| P06 | `#lend_var` outside a `borrows` body | `errors/lend_var_outside_borrows.saw` |  |
| P07 | `#lend_var` in a `&var self`-declared accessor | `errors/lend_var_in_var_self_accessor.saw` |  |
| P08 | a `borrows` body that suspends (v1 fence: bodies are sync) | `P08_borrows_body_suspends.saw` |  |
| P09 | assignment target that is a non-`borrows` method call | `errors/place_target_not_a_place.saw` |  |
| P10 | conditional lend: the absent path opens no window and runs no epilogue | `place_conditional_lend_uses.saw` |  |
| P11 | a shared window on a `let` root reads fine | `place_shared_window_readonly.saw` |  |
| P12 | place value read in a generic body without a `Copy` bound (design 146) | `errors/place_abstract_value_read_unbounded.saw` |  |
| P13 | epilogues run at window close, LIFO across nested windows | `lend_var_epilogue_nesting.saw` |  |
| P14 | writing through a window over a value the accessor built locally | `lend_accessor_local.saw` | 188 u3 — was a DEVIATION (`c.slot() = 99` was a silent no-op); refused now |
| P15 | reading through a window over an accessor-local (the frame is alive) | `lend_accessor_local.saw` | 188 u3 — the audit expected the READ to keep working; the NARROW rule refuses the lend either way, so this row is a rejection |
| P16 | lending the accessor's own parameter | `errors/lend_accessor_param.saw` | 188 u3 — was a DEVIATION (accepted); refused now |
| P17 | a window body reaches the ENCLOSING scope by borrow, not by copy — six spellings, plus the two names deliberately left as value captures | `place_window_borrows_enclosing_locals.saw` | DF-169h — the window closure is a lowering device, so its body is code from the enclosing scope and must run against the live bindings there. It captured by VALUE, which put the copy tier in front of code that copies nothing (`v[i].serialize(to: &var enc)` over a local encoder; `v[0] = w[1]` over two disjoint containers). The row also pins the exclusions: a REFERENCE-typed binding stays a plain capture (its pointer copy is already a borrow), and so does the receiver's own ROOT |
| P18 | the window's own ROOT is not borrowed from inside the extent, so `v.push`/`v.pop` there stays refused | `errors/place_window_beside_var_root.saw` (X15) | DF-169h's exclusion half, and why it is an exclusion: borrowing the root would put a second access to it inside the open window. The bogus half — a root read that invalidates nothing, `v[0].n = v.len()` — is DF-248a, held for a design |
| P19 | RENDERING a place is a borrow, at every rendering position and both refused tiers | `place_rendering_operand_is_a_borrow.saw` | DF-218i — rendering hands the value to `format(&self, into:)` and keeps nothing, but a bare place read looked the same wherever it sat, so a move-only element could not be printed AT ALL while `v[0].method()` beside it compiled. The row spans the positions the funnel `_borrowing_operand_slots` names (interpolation, single-argument `print`, the format arguments of `print`/`panic`/`assert`) because the split between them is what an audit is for; `place_rendered_frame_local_migrates.saw` is the coroutine face, where the refusal held a whole `Slot<T>` migration family back |
| P20 | COMPARING a place is a borrow, at all six operators and both refused tiers | `place_comparison_operand_is_a_borrow.saw` | DF-248d — design 239 gave `equals`/`compare` an `other: &Self` so that a move-only type with a hand-written comparison IS comparable, and the place path never got the message: `v[0] == w[0]` was the move-only refusal while `a == b` over two locals compiled. Found by DF-218i's obligation-4 sweep and fixed through the same funnel, which is why the two rows sit together |

## The unsafe surface

Claim source: spec 10 *Unsafe Code*; designs 130, 136, 149, 188 u6

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| U01 | `unsafe struct` without the enforced `Unsafe*` name | `errors/unsafe_struct_name_not_prefixed.saw` |  |
| U02 | a plain `struct UnsafeDefaults` gets no unsafe semantics | `U02_plain_struct_unsafe_name.saw` |  |
| U03 | a function binding an `UnsafePointer` without the `unsafe` effect | `errors/unsafe_trigger_undeclared.saw` |  |
| U04 | a function whose PARAMETER is unsafe-typed, undeclared | `U04_unsafe_param_undeclared.saw` |  |
| U05 | a function whose RETURN is unsafe-typed, undeclared | `U05_unsafe_return_undeclared.saw` |  |
| U06 | merely reading an unsafe-typed field (the contact rule) | `U06_reads_unsafe_field_undeclared.saw` |  |
| U07 | `&UnsafePointer<T>` parameter counts as contact | `errors/unsafe_reference_param_triggers.saw` |  |
| U08 | prefix spelling `unsafe func` | `errors/unsafe_keyword_before_decl.saw` |  |
| U09 | reversed effect order `sync unsafe` | `errors/unsafe_effect_slot_order.saw` |  |
| U10 | a line-level `unsafe { ... }` block | `errors/unsafe_expression_marker_removed.saw` |  |
| U11 | function TYPE naming an unsafe type without the marker | `errors/unsafe_fn_type_missing_effect.saw` |  |
| U12 | function TYPE declaring `unsafe` over a safe signature (rule 7) | `errors/unsafe_fn_type_safe_signature.saw` |  |
| U13 | a closure with an unsafe body inside a safe function | `errors/unsafe_closure_in_safe_function.saw` |  |
| U14 | a closure whose signature names an unsafe type, in an `unsafe` slot | `unsafe_closure_domain.saw` |  |
| U15 | a safe closure passed into an unsafe function stays safe | `unsafe_closure_domain.saw` |  |
| U16 | calling an unsafe function from a safe one needs no ceremony | `unsafe_surface_ok.saw` |  |
| U17 | a redundant `unsafe` on a safe-bodied declaration | `unsafe_conformance_effects.saw` |  |
| U18 | naming an `unsafe static var` without declaring `unsafe` (design 149) | `errors/unsafe_static_trigger.saw` |  |
| U19 | `static var` without the `unsafe` half | `errors/static_var_without_unsafe.saw` |  |
| U20 | `unsafe static` without the `var` half | `errors/unsafe_static_without_var.saw` |  |
| U21 | unsafety is not transitive: a safe fn holding a Vector | `unsafe_not_transitive.saw` |  |
| U22 | a safe value derived inside an unsafe function is safe onward | `U22_derivation_does_not_propagate.saw` |  |
| U23 | a generic `(T) sync -> R` slot instantiated at a pointer stays legal | `unsafe_fn_type_generic_slot.saw` |  |
| U24 | a conformer of an `unsafe` trait requirement must declare it | `unsafe_trait_requirement_effect.saw` | 188 u6 — was a NOTE (unenforced); the requirement-to-conformer direction is enforced now |
| U25 | an UNSAFE-bodied conformer satisfying a SAFE trait requirement (the dangerous direction) | `unsafe_conformance_effects.saw` | 188 u6 — the audit expected a refusal; the reverse direction stays LEGAL under rule 7, so this row is an acceptance |
| U26 | a SAFE conformer of an `unsafe` requirement, called through the existential | `unsafe_trait_requirement_effect.saw` | 188 u6 — the audit expected acceptance; a safe conformer of an `unsafe` requirement is refused now |
| U27 | reaching an unsafe body through a safe trait call site | `U27_unsafe_body_via_safe_trait_call.saw` |  |
| U28 | an owning VALUE READ out of a pointer place, unspelled | `U28_pointer_place_read_needs_move.saw` | 219 A2 — the read always transferred (codegen emits a raw load and hands the value on); the refusal now teaches the spelling that says so instead of naming the pointer binding |
| U29 | `move ptr[i]` — the move-out family's fourth member, deinit-exact | `U29_pointer_place_move_out.saw` | 219 A2 — design 35's refusal is keyed on the place's ROOT, and a pointer place tracks no occupancy for a move-out to corrupt; the author keeps it true inside `unsafe`-declared code |
| U30 | the signature rule derived PER INSTANCE: a generic at an unsafe type argument must declare `unsafe` | `U30_generic_instantiation_unsafe_signature.saw` | 219 C3 — DF-217k: the rule ran once with `T` abstract, and abstract `T` names no unsafe type, so an instantiation received and returned an unsafe value with an empty effect slot while the concrete twin was refused at its declaration. A monomorphized signature is a signature; the refusal anchors at the call, where the type argument is written |
| U31 | a zero-capture closure literal coerces to `FuncPointer<F>` — the closed-construction acceptance | `U31_funcpointer_zero_capture_coercion.saw` | 226 — the type is SAFE because construction is CLOSED: every inhabitant is verified code of signature `F`, and code is immortal, so possession and the indirect call are sound for every input |
| U32 | a coerced literal naming an enclosing LOCAL is refused | `U32_funcpointer_capture_local_error.saw` | 226 — the property that keeps the bare ABI sound. A coerced literal is emitted with NO environment parameter, so there is nowhere for a captured value to travel |
| U33 | the same through an EXPLICIT `[x]` capture list | `U33_funcpointer_capture_list_error.saw` | 226 — the check reads the body-names walk, not the list, so both spellings are one rule |
| U34 | the same through a method's implicit `self` | `U34_funcpointer_capture_self_error.saw` | 226 — the DF-216a lesson: a receiver appears in no capture list, and a rule written against the list would have accepted it |
| U35 | `F` must be `sync` — refused at the TYPE, wherever one is written | `errors/funcpointer226_arg_suspending.saw` | 226 — a suspending body runs out of a frame and a bare code address has nowhere to keep one |
| U36 | receiving and holding a `FuncPointer` needs no `unsafe`; only `from_raw` does | `funcpointer226_type.saw` | 226 — design 130's rule 7 satisfied by the closed-construction argument; the Vector precedent applied properly (safe type, one unsafe member) |

## Always-on runtime checks

Claim source: spec 5 *Runtime Semantics and Traps* + *Integer Conversions*; designs 122, 170

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| T01 | signed integer overflow on `+` | `overflow_add_panics.saw` |  |
| T02 | overflow on `*` | `overflow_mul_panics.saw` |  |
| T03 | unsigned underflow on `-` | `overflow_unsigned_panics.saw` |  |
| T04 | division by zero | `div_by_zero_panics.saw` |  |
| T05 | modulo by zero | `div_by_zero_modulo.saw` |  |
| T06 | `Int.min / -1` | `overflow_div_intmin_panics.saw` |  |
| T07 | shift count >= bit width | `shift_out_of_range_panic.saw` |  |
| T08 | negative shift count | `shift_negative_panic.saw` |  |
| T09 | `&+` wraps deliberately without trapping | `wrapping_operators.saw` |  |
| T10 | Vector index out of range | `T10_vector_index_oob.saw` |  |
| T11 | negative Vector index | `T11_vector_negative_index.saw` |  |
| T12 | `Vector.get` out of range yields `None` | `T12_vector_get_none.saw` |  |
| T13 | `Vector.set` out of range | `vector_set_oob_panic.saw` |  |
| T14 | fixed-array index out of range | `array_dynamic_index_oob_panic.saw` |  |
| T15 | `String.byte_at` out of range | `string_byte_at_oob_panic.saw` |  |
| T16 | `String.substring` with a reversed range | `string_substring_reversed_panic.saw` |  |
| T17 | force-unwrapping `None` | `force_unwrap_panic.saw` |  |
| T18 | `m[k]!` on an absent key | `T18_map_forced_absent_key.saw` |  |
| T19 | checked narrowing cast out of range at runtime | `cast170_narrowing_panics.saw` |  |
| T20 | a constant out-of-range cast is a COMPILE error | `errors/cast170_const_out_of_range.saw` |  |
| T21 | sign-flip cast `-1 as UInt8` at runtime | `cast170_sign_change_panics.saw` |  |
| T22 | `UInt8.from(x)` yields `None` out of range | `cast170_from_family.saw` |  |
| T23 | `UInt8.from(truncating:)` wraps without trapping | `cast170_from_family.saw` |  |
| T24 | every panic carries `panic at FILE:LINE:` (design 122) | `panic_source_location.saw` |  |
| T25 | `Data` index out of range | `T25_data_index_oob.saw` |  |
| T26 | joining an already-joined `Task` | `taskgroup_stale_handle_join.saw` |  |

## `main`'s return type and the process exit status

Claim source: spec 8 *Programs and Entry Points*; design 221 (DF-220b, DF-220c)

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| G01 | a sync `main() -> Int` exits with its value | `G01_sync_main_int_exit_status.saw` |  |
| G02 | a suspending `main() -> Int` exits with its value | `G02_suspending_main_int_exit_status.saw` |  |
| G03 | a suspending `main() -> Int` that also SPAWNS (the ambient executor) exits with its value | `G03_ambient_main_int_exit_status.saw` |  |
| G04 | the same over a `threads: N` group | `G04_mt_main_int_exit_status.saw` |  |
| G05 | a suspending `main() -> Void` exits 0 | `G05_suspending_main_void_exit_zero.saw` |  |
| G06 | a panic in a suspending `main` aborts | `G06_panic_in_suspending_main_aborts.saw` |  |
| G07 | a panic in a spawned task under `threads: N` aborts | `G07_panic_in_spawned_task_mt_aborts.saw` |  |
| G08 | a sync `main() -> Result<Int, E>` exits with the Ok payload | `G08_sync_main_result_ok_exit_status.saw` |  |
| G09 | a failing `main() -> Result<Int, E>` renders the error and exits 1 | `G09_sync_main_result_err_exits_one.saw` |  |
| G10 | a suspending `main() -> Result<Int, E>` exits with the Ok payload | `G10_suspending_main_result_ok_exit_status.saw` |  |
| G11 | a failing suspending `main() -> Result<Void, E>` renders the error and exits 1 | `G11_suspending_main_result_void_err_exits_one.saw` |  |
| G12 | `main() -> String` is refused, naming the four legal types | `G12_main_returning_string_refused.saw` |  |
| G13 | `main() -> Bool` is refused | `G13_main_returning_bool_refused.saw` |  |
| G14 | `main() -> Int?` is refused | `G14_main_returning_optional_refused.saw` |  |
| G15 | an `Int` status wider than a byte truncates as POSIX truncates it | `G15_main_int_exit_status_truncates.saw` |  |
| G16 | a bare `try` in `main` propagates to the exit status (the third exit position) | `G16_try_propagates_out_of_main.saw` |  |
| G17 | a written `return` inside `main` sets the exit status (the second) | `G17_early_return_from_main.saw` |  |
| G18 | a `main() -> Result<Void, E>` that succeeds exits 0 | `G18_main_result_void_ok_exit_zero.saw` |  |

## A `Result` must not be silently discarded

Claim source: spec 5 *Discarding a Result*; design 151

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| E01 | a bare-statement call returning `Result` | `result_discard_statement_error.saw` |  |
| E02 | a `Void` body's TAIL expression returning `Result` | `result_discard_positions_error.saw` |  |
| E03 | a loop body's tail returning `Result` | `result_discard_positions_error.saw` |  |
| E04 | a statement-position `if` forwarding a `Result` branch | `result_discard_positions_error.saw` |  |
| E05 | a statement-position `match` forwarding a `Result` arm | `result_discard_match_arm_error.saw` |  |
| E06 | an erased `Result<T, Box<any Error>>` discarded | `result_discard_erased_error.saw` |  |
| E07 | a suspending call returning `Result` discarded | `result_discard_suspending_error.saw` |  |
| E08 | `let _ =` is the accepted explicit discard | `result_discard_legal.saw` |  |
| E09 | `try!` consumes; the `T` it yields is freely droppable | `result_discard_legal.saw` |  |
| E10 | `try!` whose `T` is itself a `Result`, then dropped | `result_discard_try_payload_error.saw` |  |
| E11 | an Optional return is still freely discardable | `result_discard_legal.saw` |  |
| E12 | a bare payload auto-wraps into a `Result` at the ARGUMENT position — every spelling the funnel serves, Err side and `Result<T?, E>` double wrap included | `E12_autowrap_at_the_argument_position.saw` | DF-218f — `Result` wrapped on the way OUT of a function and not on the way IN to one, and Saw spells no `Ok(x)`, so the position had no working spelling at all. RULED (user, Aug 14): extend the argument-position funnel, which is `_arg_type_ok` and nothing else. The erasing wrap (`Result<T, Box<any Error>>` fed a concrete error) is still return-position-only: it needs the allocator and concrete type an `ErasedErrWrap` node carries, and the argument mark carries a type |

## Concurrency safety

Claim source: spec 6 *Send and Sync* + *Cooperative tasks*; designs 75, 88, 103, 186, 188 u5, 189, 193 u6, 201, 206, 210

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| K01 | a non-Send parameter crossing into a `threads: N` group | `errors/taskgroup_threads_nonsend_reject.saw` | 186 — `Vector<Int>` IS `Send` (a container is Send iff its contents are), so the audit's probe proved nothing; the covering test uses a `Vector` of closures |
| K02 | a non-Send across-suspend local in an MT group | `K02_nonsend_across_suspend_local_mt.saw` | 186 — same ruling; re-authored here with a `Vector` of closures as the non-Send local |
| K03 | a non-Send RESULT type from an MT-spawned task | `errors/spawn_result_not_send.saw` | 186 + 193 u6 — same ruling for the result type; the covering test uses a struct holding an `UnsafePointer` |
| K04 | a reference parameter at a spawned task root (design 88) | `K14_spawn_ref_param_join_releases.saw` + `K19_spawn_ref_param_mt_send.saw` | 201 — SUPERSEDED, same ruling as R25: legal in a single-threaded group under the extent rule, refused into a `threads: N` one because a reference is not `Send` |
| K05 | a reference to a task-LOCAL inside a spawned body is fine | `coro_spawn_nested_ref.saw` |  |
| K06 | a `static` of a non-Sync type | `errors/static_non_sync.saw` |  |
| K07 | a suspending call inside a `SpinLock.lock` body (`sync` enforced) | `errors/spinlock_suspending_body.saw` |  |
| K08 | a suspending call in a `sync`-declared function | `errors/sync_direct_suspend.saw` |  |
| K09 | a `blocking` extern called from a `sync` context | `errors/blocking_extern_sync_reject.saw` |  |
| K10 | a `blocking` extern in the freestanding profile | `errors/offload_freestanding_reject.saw` |  |
| K11 | a `SpinLock` captured into a closure (NoCopy) | `K11_spinlock_captured.saw` |  |
| K12 | `Mutex.lock` body mutating through `&var T` | `mutex_lock_result.saw` |  |
| K13 | MT group accumulating into an `Arc<Mutex<Int>>` | `K13_mt_sum_under_mutex.saw` |  |
| K14 | control: a `&var` argument at a spawn, joined, then the root touched again | `K14_spawn_ref_param_join_releases.saw` | 201 — the relaxation's accept side: the argument borrows its root for the TASK's life and `join()` releases it, so spawn-join-use compiles with nothing extra written |
| K15 | a caller READ and a caller WRITE of the root between the spawn and the join | `K15_spawn_ref_param_exclusion_window.saw` | 201 — design 189's one-writer-XOR-many-readers table, at the argument position |
| K16 | control: a SHARED `&` argument composes with other readers | `K16_spawn_shared_ref_param_composes.saw` | 201 — only a writer excludes; two shared borrows and a caller read live at once |
| K17 | a `&var` argument still live when a loop body ends | `K17_spawn_ref_param_across_iterations.saw` | 201 — one textual spawn, N live borrows; design 189's loop rule at the argument position |
| K18 | a `&var` argument whose root is declared AFTER the group | `K18_spawn_ref_param_after_group.saw` | 201 — design 188's LIFO rule does NOT reach an argument on its own (DF-201a probe: the task pushed into the root after the scope ended, exit 0); it does now |
| K19 | a reference argument into a MULTI-THREADED group | `K19_spawn_ref_param_mt_send.saw` | 201 — the fence that stays: a reference is not `Send`, so the Send gate refuses it. Regression row |
| K20 | `move` of a root a spawned task borrows by ARGUMENT | `K20_spawn_ref_param_move_root.saw` | 201 — design 189 probe 5's silent use-after-free, reached through an argument (DF-201a) |
| K21 | a NON-GENERIC method of an imported USER module embeds with its module-private siblings intact | `K21_cross_module_embed_private_sibling.saw` | 210 — the any-depth drive guarantee (96/104) across a module boundary. Design 84 built the embed for std only; 206 pointed it at user modules and DF-206e was the result |
| K22 | a GENERIC template of an imported user module, driven at an entry-module instantiation, keeps its HOME module's scope | `K22_cross_module_generic_embed_private_sibling.saw` | 210 — the generic path: the per-instantiation recheck (70/74) stays, and runs in the callee's home namespace |
| K23 | regression: an imported STD method still embeds and drives | `net_precise_wakeup.saw` + `spawned_task_runs_before_reactor_park.saw` + `channel_receive_through_helper.saw` + `process_run_concurrent.saw` + `coro_nested_yield_wrapper.saw` | 210 — design 84's std-only splice accommodations DISSOLVE into the two uniform paths; these are the rows that say std did not regress with them. Listed rather than copied |
| K24 | a match-arm payload binding live across a suspension is a frame SLOT, not a user copy | `K24_frame_slot_payload_binding_not_a_copy.saw` | 210 — design 131's `frame_place_read` carve-out generalized: the transform is the authority for every slot it fills, not only the reads it routes through `_read_field` |
| K25 | a spliced body's module-private `static` in a CONST position (array length, repeat count) | `K25_cross_module_embed_private_static_const_position.saw` | 210 unit 5 — the position design 84 could only PERMIT (std's statics are merged into every compile and its bodies checked with the gate off). `repeat_count` is a declared annotation, so every structural walker steps over it; the marking walk is the one walk that visits annotations |
| K26 | a closure's capture of a frame-resident local is a frame read judged by the copy tier, not a user `.copy()` | `K26_closure_capture_of_frame_local_not_a_user_copy.saw` | DF-217c — K24's guarantee at a third position. The materialization spelled `.copy()` on every tier without asking `read_policy`, so a NoCopy `[move r]` capture AND an automatic-Copy struct (design 159's tier declares no `copy`) were both refused on programs whose non-suspending twins compile |
| K27 | a place window (`UnsafeRef.deref`, `Slot.value`) never spans a suspension | `K27_receiver_window_never_spans_suspend.saw` | 218 unit 1 — the invariant the frame vocabulary rests on, and it needs no new machinery: a `borrows` body is `sync` (the design-146 v1 fence), so a suspending call inside the window expression is the ordinary sync violation. The row exists because the transform will RELY on it, so it has to be a checked rule rather than an argument about what the ANF hoist happens to leave behind |
| K28 | a `Slot<T>` payload is released exactly once, at every exit | `K28_slot_payload_released_exactly_once.saw` | 218 unit 1 — the property the module buys. A payload leaves by exactly four operations (`take`, `clear`, `put` onto an occupied slot, the synthesized deinit) and each updates the tag in the same body that moves or drops the payload, with the field private so there is no fifth way in. This replaces a theorem about EMISSION PAIRS — a read and a separate `__saw_forget` any site could mispair, which DF-206f, DF-210f and DF-217h each did — with one local property, checked here |
| K31 | an `Arc<T>` at a NON-Sync `T` cannot cross to a worker thread, and the generic path does not launder it | `K31_generic_arc_share_at_non_sync_refused.saw` | 219 C5 — the row S1 left uncovered: `Send` was proven sound at the abstract-`T` boundary on all three axes, the SYNC axis never forced. It holds, by a mechanism the message does not name — `Arc`'s own `Send` derivation is conditioned on `T: Send + Sync` TOGETHER, so a non-Sync payload makes the Arc non-Send. The generic twin is refused even earlier, by the MT spawn's concrete-type-arguments gate |
| K30 | a generic container instantiated at a NoMove payload is itself NoMove, derived per instance | `K30_generic_container_of_pinned_is_pinned.saw` | 219 C3 — DF-217j: `Wrap<TaskGroup>` relocated a live group and died `force unwrap of None`, the abort design 188 exists to prevent, from safe code. The declared cascade stays the rule where a declaration site exists; a generic container has none (`Wrap<T>` cannot say `NoMove` without pinning `Wrap<Int>`), so the property is derived from the type argument exactly as the copy policy already was |
| K29 | a suspending `copy()` on a declared copy-policy conformance is refused AT the conformance | `K29_copy_policy_hook_must_be_sync.saw` | 219 A1 — DF-217r: the retain hook is called at compiler-INSERTED sites, so its suspension was invisible to the effect census and ran inside a `sync`-declared function with no diagnostic. Checked once at the declaration, where the author can act on it. (Renumbered from K27 at integration; the 218a spec pre-registered K27/K28) |
| K33 | a suspending method on an ENUM extension embeds as a frame and cedes to its siblings | `K33_suspending_enum_method_embedded.saw` | 223 — OPEN, XFAIL citing DF-218l. Design 145 gave enums extensions and design 74 gives methods frames; the two had not met, because the transform's call-site classifier reads `struct_name` and an enum receiver carries `enum_name`. THREE properties per row in this family, and the third is the one that matters: a silently-sync call site computes the right value in the right order and only stops interleaving |
| K34 | a suspending method on a GENERIC struct embeds at the EMBEDDED position, not only at the drive root | `K34_suspending_generic_struct_method_embedded.saw` | 223 — OPEN, XFAIL citing DF-218m. The root position monomorphizes the method for the concrete receiver and hands the transform a per-instantiation clone; the embedded position had no clone, so the call was compiled as a plain function with the suspension inlined. `&self` and `&var self` receivers, since the receiver's mode is its own axis |
| K35 | a suspending METHOD-LEVEL generic on a concrete struct embeds as a frame | `K35_suspending_generic_method_embedded.saw` | 223 — OPEN, XFAIL citing DF-223a. The third keying shape: the RECEIVER is concrete, so the classifier named it and the call was classified embeddable, while the method AST it named still carries `<T>` and the closure walk skipped it — a raw `KeyError` with no anchor. M1 and M2 keying different things is the mechanism, which is why they cannot be fixed apart |
| K36 | a suspending method that SATISFIES a trait requirement still satisfies it after the transform | `K36_suspending_conformance_method_embedded.saw` | 223 — OPEN, XFAIL citing DF-218k. The transform strips a driven method's body from its extension and the program is re-typechecked; the extension then no longer implements the conformance it declares. Struct and enum conformances, because the strip is keyed on the extension and an enum extension is one |
| K37 | dispatching to a SUSPENDING conformance body through `any Trait` is REFUSED | `K37_existential_dispatch_suspending_impl_refused.saw` | 223 — OPEN, XFAIL citing DF-223b. A frame is a compile-time identity and dynamic dispatch has none, so there is nothing to embed and no design that says what should happen; the ruling is work-where-the-mechanism-exists, clean-refusal-where-it-does-not. Today it is neither — the dispatch is a merely-CONSERVATIVE suspension source, so no frame is built anywhere and the `yield_now()` inside the impl runs outside a frame, where it is a no-op |
| K38 | a user method whose (type, method) NAME pair collides with a suspending std one gets no frame | `K38_std_name_collision_no_frame_on_sync_method.saw` | 223 — OPEN, XFAIL citing DF-206d, which recorded the shape as "not live" and is falsified. std bodies belong to another typechecker, so their suspending methods arrive as a set of name pairs — the one place the transform asks the question by name rather than by identity. Asserted in the IR in BOTH directions, since over-inclusion is invisible to any runtime check |
| K39 | the same three receiver shapes embed across a MODULE boundary | `K39_cross_module_suspending_method_shapes_embed.saw` | 223 — OPEN, XFAIL citing DF-218l/DF-218m. Design 210's any-module rule for the three shapes K33/K34/K36 pin entry-module. Its own row because the cells failed DIFFERENTLY across the boundary: the entry-module enum ICEs where the cross-module one is silently sync, and the conformance is refused entry-module and compiles cross-module |
| K32 | a spawned task's result and cancel word cross the group-owned cell exactly once | `K32_task_cell_result_and_cancel.saw` | 222 unit 1 — the OBSERVABLE half of design 218's trusted-list item 2. The cell outlives the frame on purpose (design 134), so the frame reaches it through a handle whose validity is a manual argument; what a caller can see of that argument is pinned here — a NoCopy result moved to the joiner and dropped once, a refcounted one crossing with its count intact, an UNJOINED one released once at group teardown, and the cancel word observed through the same handle at both cell shapes (`__ResultCell<T>` and the result-less `__VoidCell`) |
| K40 | a suspension in a `match` SCRUTINEE embeds as a frame and cedes to its siblings | `K40_suspending_match_scrutinee_head.saw` | 224 — the container HEAD slots. A container's head is the expression it evaluates outside any of its blocks, and the transform's nested-call walk descended into the BLOCKS only, so a head suspension was neither embedded nor refused — the third outcome designs 96/101/104 say does not exist. Three suspension kinds per row (free function, cooperative `receive()`, method), because they reach the head through three different classifiers |
| K41 | a suspension in an `if` CONDITION embeds and cedes, at every nesting depth | `K41_suspending_if_condition_head.saw` | 224 — K40's rule at the condition slot, plus the nesting axis: a head inside another `if`, and inside a loop body, are the same walk |
| K42 | a suspension in a `while` CONDITION embeds, cedes, and is RE-EVALUATED per iteration | `K42_suspending_while_condition_head.saw` | 224 — the one head that is not evaluated once. Lifting it to a preceding `let`, which is the answer for `if`/`for`/`match`, would freeze the loop on its first answer, so this row carries a fourth property the other head rows do not |
| K43 | a suspension in a `for` RANGE embeds and cedes, both endpoints, in source order | `K43_suspending_for_range_head.saw` | 224 — a range has TWO head slots and they are evaluated left to right, which a suspending lower bound beside a suspending upper bound is what checks |
| K44 | a suspension in a condition's `&&`/`||` RHS cedes AND keeps its short-circuit | `K44_suspending_condition_shortcircuit_rhs.saw` | 224 — the head-slot gap composed with design 120 stage 2. The head lift has to run first so the ordinary value-conditional lowering sees the operator; what it must not cost is the guarantee the operator exists for, which the row checks by receiving from a channel nobody feeds on the skipped side |
| K45 | a suspension in a COMPOUND ASSIGNMENT's RHS embeds and cedes | `K45_suspending_compound_assign_rhs.saw` | 224 — the ANF hoist's statement dispatch had arms for `let`, `=`, `return` and a bare expression, and none for `n += slow()`. Design 227's chained compound `x?.n += slow()` reaches the same missing arm through its read-modify-writeback, so the two flip together |
| K46 | `return <suspension>` is a boundary for all three suspension kinds | `K46_suspending_return_head.saw` | 224 — the three top-level classifiers answer one question about one set of statement shapes, and the cooperative-`receive()` one was missing the `return` arm its two twins had; a statement that is not nested at all was refused as nested |
| K47 | a channel `receive()` reaches the `if let`/`guard let`/`try` heads on a suspending call's terms | `K47_channel_receive_binding_and_try_heads.saw` | 224 — two disagreeing suspension predicates in one file. The three narrow hoists asked one that omitted the channel receive while the general ANF hoist asked one that included it, so the shapes only the narrow hoists reach were refused where expressible and silently spun where design 104 had already split the binding |
| K48 | a task spawned into a `threads: N` group RUNS before anybody joins it | `K48_mt_group_task_runs_before_join.saw` | 225 — the DF-224b wake matrix's headline cell. `TaskGroup(threads: N)` was the ONLY fork-join member of its family: `__drain_mt` spawned AND joined its workers inside one call, reached only from `join()`/`Deinit`, so nothing outside a drain made an MT group run. Waits on a wall-clock bound rather than hanging, because the pre-fix behavior is a 100%-CPU cooperative spin with no end |
| K49 | an MT group's task feeds a task of a different, SINGLE-THREADED group | `K49_mt_worker_feeds_st_group_task.saw` | 225 — the cell that falsified the sweep's first hypothesis. Nothing here is main-specific: an ordinary cooperative observer in its own group saw exactly the progress main saw, which is none |
| K50 | an MT group's tasks progress while main SLEEPS | `K50_mt_group_progresses_while_main_sleeps.saw` | 225 — the guarantee is about the group being LIVE, not about any one wake path. Main is not waiting on the worker at all here; measured pre-fix, a 400 ms nap elapsed with the worker never started |
| K51 | an MT group's tasks progress while main YIELDS | `K51_mt_group_progresses_while_main_yields.saw` | 225 — K50's twin at the other park, so the fix cannot answer only the timer half. `__enqueue` registered into the ambient scheduler's list only when `workers < 2`, so ceding from main reached nothing of an MT group |
| K52 | TWO tasks of one MT group both deliver before either is joined | `K52_mt_two_workers_deliver_before_join.saw` | 225 — the plural cell: a fix that ran the group on the joining thread would satisfy K48 and fail this. Asserted on the sum, never on arrival order |
| K53 | a driven `for` over a range runs exactly its sync twin's iterations, both flavours | `K53_driven_for_range_iteration_count.saw` | DF-225m — the row the whole colorless claim rests on, at the one loop the transform rewrites. `_split_while` re-emits the author's condition; `_split_for` hand-writes the header and the step out of frame slots, and wrote them for the exclusive range only, so every driven `a..=b` ran one iteration short and a single-iteration `3..=3` ran none. Five cells against their plain twins, the fifth being `Int.max` — the guarded step is why the fix is design 53's shape and not `<=`, which panics `integer overflow` where the sync twin terminates. Nine further rows in `examples/coro_for_inclusive_range_last_iteration.saw` |
| K53 | an MT group's workers PERSIST across spawns, so work enqueued later is picked up by workers already running | `K53_mt_group_stays_live_across_spawns.saw` | 225 — the pool's lifetime as opposed to any one task's, and what makes the long-lived-group shape honest to write. Pre-fix, enqueue was main-thread-only BY CONSTRUCTION, since no worker was alive outside a drain |
| K54 | control: an MT group's task receives what MAIN sent | `K54_mt_task_receives_what_main_sent.saw` | 225 — the direction that already worked. The value is in the channel before the worker is, so the row says the live pool did not cost the fork-join case its determinism |
| K55 | control: two tasks of ONE MT group, one sending and one receiving | `K55_mt_same_group_send_and_receive.saw` | 225 — green in the sweep, and by a mechanism the live pool REPLACES (both frames in one drained queue, versus both simply running). The row that catches a fix that made the cross-group case work by breaking the within-group one |
| K56 | control: the 21b `Thread.spawn {}` thread engine feeds main's cooperative receive | `K56_thread_engine_feeds_main_receive.saw` | 225 — the live-pool PRECEDENT and an evidence line the direction was ruled on: the same program with one engine swapped, and it works |
| K57 | control: main receives an ALREADY-SENT value while an MT group is live | `K57_main_receives_prefilled_with_mt_group_live.saw` | 225 — the isolating cell that separates "main cannot receive while an MT group exists" from "an MT group's tasks do not run". Kept because a live pool adds real concurrency to main's own path |
| K58 | control: main receives after `join()` returned | `K58_main_receives_after_mt_join.saw` | 225 — the fork-join contract's own cell, which the pre-fix engine DID keep. `join()` still means "this task is complete" |
| K59 | control: main receives after the MT group's SCOPE ends | `K59_main_receives_after_mt_group_scope.saw` | 225 — the `Deinit` half of K58, with no join written at all. The live pool redefines what `Deinit` does (signal no-more-work, join the workers, then design 124's eager teardown) and this is the observable it may not change |
| K60 | control: `TaskGroup(threads: 1)` IS the cooperative engine | `K60_threads_one_is_the_single_threaded_engine.saw` | 225 — the boundary of the matrix, byte for byte K48 with a `1` in it. `threads: 2` becomes live; `threads: 1` stays the deterministic interleaving programs may reason about |
| K61 | control: a cooperative group's task feeds main's receive with no join between | `K61_st_group_task_feeds_main_receive.saw` | 225 — design 89's ambient-liveness guarantee, stated here because it is the STANDARD the MT cells were judged against. A regression here would mean the live-pool work broke the engine it was modelled on |
| K62 | control: `join()` on an MT group returns the task's RESULT, and the join is a full barrier | `K62_mt_join_returns_the_task_result.saw` | 225 — the fork-join engine's actual product, kept while its scheduling contract is rewritten around it. Asserted on the sum, never on interleaving |
| K63 | a cooperative channel wait is a PARK with the channel's identity, not a ready yield | `K63_channel_wait_is_a_park.saw` | 230 unit A — `receive()` suspended with wake reason 0 (READY), so a waiter was re-queued as fast as the scheduler spun: 100% of a core for a sole waiter, 143% across two MT workers, and every state the deadlock report keys on unreachable (DQ-225n). CPU is not assertable in a suite, so the row asserts the executor's own vocabulary — the dump says `channel-parked` where it said `ready` — plus the wake reaching two waiters on two channels in order |
| K64 | closing a channel loses none of what is already queued | `K64_close_drains_before_it_reports_closed.saw` | 230 unit C — the Go drain-then-closed rule, and the classic mistake it is written against. It falls out of the ORDER inside `__try_receive_result` (take first, ask about closed second) rather than out of anything a consumer writes, so a regression would be silent: the consumer loop looks identical either way |
| K65 | `close()` wakes a receiver that is ALREADY parked | `K65_close_wakes_a_parked_receiver.saw` | 230 unit C over unit A — a waiting receiver is parked, not spinning, so a close reaches it the same way a send does, by publishing the readiness word. Without that the close would be observed only by a receiver that had not started waiting, which is the opposite of the case it exists for |
| K66 | a second `close()`, and a `send` after one, are reported as values | `K66_send_and_close_after_close_report.saw` | 230 unit C — idempotent WITHOUT being silent: two holders may both believe they are the last producer, so a losing close is `Err(Closed)` and safe to `let _ =`. The row also counts the queue afterwards, because the thing a refused send must never do is land anyway |
| K67 | a quiescent channel deadlock is REPORTED, not waited out | `K67_quiescent_channel_deadlock_is_reported.saw` | 230 unit B — design 225's D-e, buildable at last: the state it keys on was unreachable while a channel wait suspended READY (DQ-225n), and unit A's park created it. Sound by elimination rather than heuristic — no ready or active frame, no io registration, no timer, no readiness word set, no unjoined `Thread.spawn {}` task — because a resume-counting heuristic cannot tell a permanent wait from design 127's force-yielded long computation |
| K68 | control: the deadlock report does NOT fire while anything could still run | `K68_deadlock_report_does_not_fire_on_a_live_program.saw` | 230 unit B, and the half that matters more — an abort that fires on a correct program is worse than the hang it replaces. One satisfiable wait per source the walk must account for: a sleeping sibling, a `Thread.spawn {}` thread-engine task (which no run queue knows about at all, so the walk counts them separately), and an MT-group task |
| K69 | cancellation reaches a task PARKED in `receive()` | `K69_cancel_reaches_a_parked_channel_receive.saw` + `channel_receive_cancel_mt.saw` | DF-230a — the one park in std that did not observe cancellation, so `h.cancel()` on a waiting consumer turned into a hang at the group's `Deinit`. Two halves that only work together: the receive checks at its loop top (`Err(Cancelled)`) and the executor wakes a cancelled parked frame, which design 230 correctly refused to do while no check existed. The check is ahead of the dequeue, so the row also pins that a cancelled receive takes no further message; the MT file is the second engine, whose worker promotes in its own under-the-lock scan |
| K70 | a frame-resident local of a DRIVEN body is released at the end of the scope that owns it, per scope kind | `K70_driven_scope_end_release_matrix.saw` | DF-217p, ruled Aug 20 — deterministic destruction is unconditional, so the driven twin must agree with the sync twin. The transform lifts an across-suspend local into a frame FIELD and a field lived until the frame died, so a `File` bound in a driven loop stayed open for the rest of the frame; the counts always balanced, which is why the corodiff matrix filed 66 cells of it as DEINIT-ORDER and never as LEAK. Seven scope kinds (SC2-SC8 of designs/218b-scope-end-spec.md), each as a twin pair differing only by a `yield_now()` — so the EXPECT block IS the parity claim |
| K71 | a SYNC loop releases the iteration's locals on the `break` and `continue` edges | `loop_exit_releases_body_local.saw` | DF-218r — the other half of K70's guarantee, and its ORACLE: `return` ran `_cleanup_all_scopes` while `break`/`continue` branched to the loop's exit block with no scope cleanup at all, so the iteration's locals LEAKED (counts unbalanced). Five cells: break, continue, the `return` control, a break from a NESTED block (two scopes, LIFO), and a range-`for`'s continue |
| K72 | the DONE path releases in scope order, interleaving the frame's fields with the locals of nested scopes | `coro_done_path_releases_in_scope_order.saw` | DF-218s, ruled Aug 21 — K70's guarantee at the one exit where TWO release systems used to meet. The frame's release is a statement and codegen's `_cleanup_all_scopes` runs AT the lowered `return Poll.Done`, so a surviving real local could only be dropped after the frame's own fields — sync-LIFO inverted. The ruling (forced frame residency for the owning locals of a block that returns) leaves ONE system in charge rather than trying to order two. Four block kinds a nested `return` can sit in, plus the sibling-scope row that pins the in-place fallthrough edge firing ahead of teardown |
| K73 | a driven arm that DISCARDS its payload releases it at extraction, as the sync twin does | `coro_discarded_match_payload_released_at_extraction.saw` | DF-218w — the last of DF-217p's cells, and the one no scope exit could reach: a `_` binding names no value, so it is registered in no cleanup scope. The edge is per-ARM (an arm that claims nothing of the scrutinee releases the hoisted temp at its start), the merge release stays behind it as the idempotent tag-drop, and both lowerings take it. The mixed `case Both(v, _)` shape is the known residue and is pinned XFAIL beside it — a named binding aliases the payload for the arm's length, so an arm-start release would free what it reads |
| K74 | a DECLARED `Send` bound licenses a generic body's spawn capture, and an undeclared one still refuses | `K74_send_bound_licenses_a_generic_spawn_capture.saw` + `k74_refused_unbounded.saw` + `k74_refused_at_the_call.saw` | DF-219c — the capture audit fell through `is_send`'s opaque-type-parameter path, which answers False for every unresolved `T`, so `<T: Send>` bought nothing and `Send`-bounded generic fan-out was unwritable. An OVER-rejection, and one with an asymmetry behind it: the spawn RESULT position beside it already had a `T` bypass, which is the obligation-1 shape. What makes the relaxation sound is the other end, and it is why this row needs THREE files — the bound is a promise the CALLER keeps, checked at the call where the concrete type is known, and an UNBOUNDED `T` still gets the old answer |
| K75 | a SYNC `try { } catch { }` releases the try body's locals on its ERROR edge | `try_catch_error_edge_releases_try_locals.saw` | DF-218v — the third nonlocal exit that is not a return, and the only one that leaked OUTRIGHT: the OK path popped the scope and the propagating no-catch shape ran `_cleanup_all_scopes`, so this one branch left the block with nothing dropped and the counts unbalanced. It also CORRECTS K71's class statement, which said `break` and `continue` were the only two. Six cells, each a different bound for one walk: both edges live at runtime (a double release would show), a catch that `break`s out of the enclosing loop, a nested try/catch, a `for` inside the try body (its owning loop variable is in the unwind), a catch edge beside a propagating `return` in one body, and the OK-path control |
| K76 | a SYNC optional-binding branch releases its binding on the `return`, `break` and `continue` edges | `if_let_binding_released_on_early_exit.saw` | DF-218x — the OTHER half of K71/K75, and the half neither could reach: those rows widened the WALK, and this binding was never on the stack the walk reads. Codegen gave it an ad-hoc alloca plus a drop flag and dropped it inline behind an `is_terminated` test whose comment claimed the terminated edges had cleaned all scopes — false for precisely the one binding no scope held, so every terminated exit LEAKED it. Registering it through `_register_cleanup` into a branch-owned scope is what makes the existing walk sufficient, which is why the fix adds no fourth entry point. Rows: the three edges at `if let`, the fall-through control, the `if var` / `while let` spellings the one lowering also serves, the design-63 tuple pattern (never a leak — its leaves registered into the ENCLOSING scope and outlived the branch), a `move`-out where the drop flag must suppress the scope's drop, the `guard let` and match-arm CONTROLS that were always right, and the driven twins the sync half now matches |
| K77 | a `_`-DISCARDED payload's fields drop in REVERSE declaration order, on both twins | `coro_discarded_match_payload_field_drop_order.saw` | DF-218y, ruled Aug 22 — design 128 says every structural teardown is reverse-declaration, and this was the ONE drop path in the language that was not. Sync dropped a discarded field inline as it EXTRACTED it, so its loop ran forward, while the driven twin releases the frame temp as one value through the enum's synthesized memberwise deinit, which is reverse; the ruling is that forward was an artifact of the emission point and never a contract, so the fix landed on the sync side. The row's own ORACLE is in the file — `named_control` binds all three fields, and a named binding has always been released in reverse by the arm scope that registers it. The obligation-4 sweep found the same forward loop at a SECOND position, the destructuring `let`'s wildcard leaves (`let (_, _)`, `if let (v, _, _)`, the `guard let` twin), which was forward on BOTH twins and so never diverged — it simply disagreed with the language, and moves with the match lowering. Distinct from K73, which pins the discard's release POINT and is untouched by the order |

## Visibility and module boundaries

Claim source: spec 8 *Visibility* + *The prelude*; designs 80, 82, 142, 188 u7, 204

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| B01 | reading a private field cross-module | `vis80_field_read_error.saw` |  |
| B02 | writing a private field cross-module | `vis80_field_write_error.saw` |  |
| B03 | cross-module memberwise literal naming a private field | `vis80_field_literal_error.saw` |  |
| B04 | calling a private extension method cross-module | `vis80_method_private_error.saw` |  |
| B05 | orphan conformance: a foreign type to a foreign trait | `B05_orphan_conformance.saw` |  |
| B06 | an extension method from a TRANSITIVE dep is invisible (design 142) | `B06_transitive_extension_invisible.saw` |  |
| B07 | control: the public surface IS reachable cross-module | `vis80_public_members_ok.saw` |  |
| B08 | control: importing `deep` DIRECTLY makes its extension visible | `B08_direct_import_extension_visible.saw` |  |
| W01 | review item 4: is `SpinLock` reachable BARE, without importing std.spinlock? | `spinlock_import_gate.saw` | 188 u7 — was a DEVIATION (`SpinLock` resolved bare against a spec that said otherwise); gated now |
| W02 | the gate runs on TYPE ANNOTATIONS — eleven written positions, no import | `W02_import_gate_annotation_positions.saw` | 194 u4 — was a DEVIATION (DF-188k: the gate fired only where a VALUE was built, so a signature that merely RECEIVED a gated type compiled); gated now |
| W03 | control: the QUALIFIED spelling is legal in an annotation | `W03_import_gate_qualified_annotation.saw` | 194 u4 — the over-rejection DF-193d named; the gate judges the author's spelling, not the resolved type |
| W04 | control: both BARE import forms make the same annotation legal | `W04_import_gate_bare_import_forms.saw` |  |
| W05 | a signature naming a gated std type with no import (the DF-188k repro) | `std_import_gate_signature_position.saw` | 194 u4 — XFAIL flipped |
| B09 | a user type whose name a PRIVATE std type also owns (`State`, `MapSlot`, `LockState`) | `B09_user_type_name_vs_private_std_type.saw` | 204 — was a DEVIATION (DF-153b: std's declaration won, and the diagnostic named a declaration the author cannot see, import or find); the user's declaration is the only one in scope now |
| B10 | two std FILES may each own one private type name (DF-153a) | `tools/test_std_private_type_names.py` | 204 — std-authoring-internal, so the vehicle is a compiler-level test, not a `.saw` row: it rebuilds the builtins over a std tree carrying a second private `State` and asserts both identities survive |
| B11 | control: a user type named like a GATED std PUBLIC type (`IoError`, `File`) | `prelude_user_ioerror.saw` | 204 — the design-82 promise, already covered; listed here rather than copied |
| B12 | control: a PRELUDE std type name stays reserved (`Vector`) | `B12_prelude_type_name_stays_reserved.saw` | 204 — the fence on the public surface: private-type freedom must not leak into it |
| B13 | a name a module only IMPORTS is unreachable through it, in all four spellings (bare under a glob, `{X}` selection, `m.X`, chain `m.dep.X`) | `B13_import_is_not_reexport.saw` | 229 — was a DEVIATION (re-export was indiscriminate: everything a module imported was reachable through it, bare and qualified, at the same identity); private by default now |
| B14 | control: `public import` re-exports, and a SELECTIVE one publishes its names without publishing the qualifier beside them | `B14_public_import_reexports.saw` | 229 — the fence on the facade: a curated re-export must not hand on the module it selected from |
| B15 | `public(package)` is unreachable from OUTSIDE the package in every spelling, and no `public import` re-export widens it: direct qualified, selective facade, two stacked facades, glob facade, whole-module chain, and every symbol KIND (function, static, struct) | `module_path_qualified_no_widen_error.saw`, `module_path_reexport_no_widen_error.saw`, `module_path_reexport_twohop_no_widen_error.saw`, `module_path_glob_facade_no_widen_error.saw`, `module_path_whole_facade_no_widen_error.saw`, `module_path_reexport_kinds_no_widen_error.saw`, `module_path_facade_selection_error.saw`, `module_path_package_visibility_error.saw` | 232j — was a DEVIATION and the tier had NO row here, which is part of why it went unseen: design 80's relation had two callers and only the typechecker's computed a package root, so the namespace-side qualified reach decided `public(package)` with an empty root and every spelling that went through it fell open. The tier RIDES the symbol now (`def_module`), so a re-export hands on the NAME and never a wider tier, at any hop count |
| B16 | control: the SIBLING direction — files of one package reach each other's `public(package)` names in every spelling (qualified, `{X}` selection, glob) | `module_path_package_visibility.saw`, `df229c_package_selection_binds.saw`, `module_path_glob_facade_sibling.saw` | 232f/229c/232k — the fence on B15: the tier must not become unusable inside the package it exists to serve. The glob leg was a DEVIATION (232k: the glob-copy arm filtered PUBLIC-only, so an aggregating sibling failed to compile) |
| B17 | control: a whole-module `public import` chain reaches a re-exported dependency's PUBLIC symbol in VALUE position, not only in a type annotation | `export229_whole_chain_call.saw` | 232l — was a DEVIATION (every bound qualifier was stamped `PRIVATE`, so design 229's whole-module form re-exported nothing a value expression could reach); the qualifier now carries the form's own answer |
| B18 | `public(package)` is unreachable from outside a package reached by RELATIVE path — the loading path with no `--module-path` name — at both funnel entry points: the qualified reach and the selective import | `package_tier_foreign_relative_reach_error.saw`, `package_tier_foreign_relative_selection_error.saw` | 232n — was a DEVIATION and the remaining arm of B15's family: the two roots design 80 knew are PREFIXES OF THE MODULE PATH (std's `("<std>",)`, DF-232f's mapped `(name,)`), which a relatively-imported module does not have, so the question reached `check_visibility` rootless and its fail-open arm answered ALLOW. Every module now carries a package IDENTITY — its `Saw.toml` root, else the entry file's tree — and the rootless arm REFUSES |
| B19 | control: the SIBLING direction across the same loading path — an entry inside a package's own manifest root reaches its `public(package)` names by relative import (the `libs/toml/tests` shape), and an ad-hoc manifest-less tree stays one package | `package_tier_same_package_reach.saw`, `visibility_package_access.saw`, `df229c_package_selection_binds.saw`, `vis80_public_members_ok.saw` | 232n — the fence on B18, and the reason the fix is an identity rather than a blanket fail-closed: two behaviors ride the arm B18 removed. `examples/`-style fixtures have no manifest at all (DF-229c ruled a same-package importer binds package names; for a manifest-less tree the entry's tree IS the package), and a package's own tests live under its root |
| B20 | no declaration exposes a type its callers cannot see: a `public` function's parameter and return, and a `public` field's type, are refused where they are written when the type is less visible | `B20_private_type_in_public_signature_error.saw`, and the full position matrix at `private_in_public_positions_error.saw` + `private_in_public_extension_surface_error.saw` | Aug 21 ruling ("a public API needs public types") — was a DEVIATION: the value path let a module-private type out, so a caller could hold and use a value it had no way to NAME. Refused at the declaration now, in the Rust E0446 shape, on design 219's precedent that a `public` declaration hard-requires what an internal one may infer |
| B21 | control: the rule stops at the declaration's own reach — a PRIVATE declaration names anything, and a `public` member of a non-public type is capped at that type's reach (design 80's "legal but inert") | `B21_private_declaration_names_anything.saw` | Aug 21 — the fence on B20, and what makes "narrow the declaration" a real fix rather than a dead end |
| B22 | a module-private type cannot leave its module on the VALUE path or the design-141 PLACE path, and the refusal lands in the module that can fix it | `B22_private_type_escapes_module_error.saw` | 232o face 2 — the cross-module face, and the row that retires the residue: the place path used to fail in the IMPORTING module as ``argument `__window` expects `(&var Hidden) sync -> Hidden` but got `(&var Hidden) -> Void```, naming a synthesized parameter and never saying "visibility". The file's `EXPECT-ERROR-ABSENT: __window` is what pins that no legal program reaches that lowering; `place_cross_module_same_name_type.saw` is the legal half (a design-144 same-named type across the boundary keeps its identity through a read, a write and a conditional lend) |
| B23 | a conformance declared under the ORPHAN RULE is coherent PROGRAM-WIDE — carried by every import form, including a `UnsafeSend`/`UnsafeSync` assertion | `conformance_in_the_traits_module_is_program_wide.saw`, `thread_assertion_survives_a_glob_import.saw` | 238c — was a DEVIATION: a conformance query walked the QUALIFIER bindings, which a GLOB deliberately never makes, so `import m.*` lost every conformance `m` declares for a type declared ELSEWHERE (the rule's second half, whose declaration site is the trait's module) and the diagnostic hinted at adding the extension that was already there. `coherence_search_namespaces` is the one funnel now, and its two entry points are `type_conforms_to` and `_lookup_thread_assertion` — the second is the row's other file, where a globbed `extension Shared: UnsafeSync {}` was invisible and a `static` of that type was refused as non-Sync. Name lookups are deliberately NOT routed through it: those are visibility questions, where a glob's copy already answers |

## Integer width agreement

Claim source: spec 5 *Integer Conversions* + *Arithmetic* ; designs 195, 205

Rule 1: all typed operands of an operation have the SAME type — implicit
promotion happens from bare literals and nowhere else. Rule 2: value-branch
arms are TRANSFERS, so a lossless widening arm is legal exactly as at a
`return` and a lossy one is the ordinary transfer error. Rule 3 (design 205):
the PLAIN transfer takes the same rule — a narrowing or a same-width sign
change through the platform `Int`/`UInt` pair is refused wherever a value lands
in a new home, and design 170's three spellings are how it is said. W06-W19 are
design 195's operator matrix and W20-W24 design 205's transfer matrix, one per
line; W11, W17 and W22-W24 are the CONTROLS that pin what the rules do not
touch.

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| W06 | arithmetic over two typed operands of different WIDTH | `W06_binop_mixed_width_operands.saw` | 195 — was DF-192f, a codegen ICE |
| W07 | arithmetic over a signed and an unsigned operand | `W07_binop_sign_mix_operands.saw` | 195 — compiled SILENTLY, signed division on an unsigned operand |
| W08 | comparison over two typed operands of different WIDTH | `W08_comparison_mixed_width.saw` | 195 — was an LLVM-level ICE |
| W09 | comparison over a signed and an unsigned operand | `W09_comparison_sign_mix.saw` | 195 — compiled SILENTLY, signed compare on an unsigned operand |
| W10 | the wrapping operators `&+ &- &*` over different widths | `W10_wrapping_op_mixed_width.saw` | 195 — was a codegen ICE |
| W11 | control: a SHIFT COUNT need not match the shiftee's width | `W11_shift_count_width_exempt.saw` | 195 — the documented exemption (matrix row 6) |
| W12 | a value `if` whose arms widen losslessly answers with the arm that ran | `W12_if_arms_widen_losslessly.saw` | 195 — was DF-192g, a confirmed WRONG ANSWER |
| W13 | a value-branch arm that cannot widen losslessly, at `if` / `match` / `??` | `W13_if_arms_lossy_refused.saw` | 195 — all three compiled silently |
| W14 | a value `match` whose arms widen losslessly, in both arm orders | `W14_match_arms_widen_losslessly.saw` | 195 — right by accident for a constant arm, an ICE for a variable one |
| W15 | `??`'s payload and default widen losslessly | `W15_coalesce_operands_widen.saw` | 195 — same two behaviors as W14 |
| W16 | a range's two bounds must have the same type | `W16_range_bounds_mixed_types.saw` | 195 — was a rejection, through a message naming one type and no way out |
| W17 | control: a BARE literal still adopts the other operand's type | `W17_bare_literal_adopts_operand_type.saw` | 195 — the NEGATED spelling `n * -2` was an ICE (matrix row 12) |
| W18 | compound assignment over different widths | `W18_compound_assign_mixed_width.saw` | 195 — a position the matrix did not carry; was a codegen ICE |
| W19 | the bitwise `& \| ^` over different widths | `W19_bitwise_mixed_width.saw` | 195 — a position the matrix did not carry; compiled, ZERO-extending a signed operand into a wrong mask |
| W20 | a NARROWING transfer through the platform pair, at all fifteen transfer positions (`let`/`var`, assignment, argument, return, struct field, enum payload, array/tuple/Vector/Map/Set element, optional slot, value-branch home) | `W20_narrowing_transfer_positions_error.saw`, and the two-line repro at `int_narrowing_transfer_through_platform_int.saw` | 205 — was DF-195b, a SOUNDNESS hole: `let b: Int8 = n` on an `Int` holding 300 printed 44 at every one of those positions. `_types_compatible` admitted a platform `Int`/`UInt` into any integer type, a permission that existed for bare-literal adoption (W23) and covered a runtime value losing its high bits |
| W21 | a same-width SIGN FLIP through the platform pair, at the same positions | `W21_sign_flip_transfer_positions_error.saw`, and the two-line repro at `int_sign_flip_transfer_through_platform_int.saw` | 205 — was DF-195c, the other axis of the same admission: `let i: Int = u` on `UInt.max` printed -1, the conversion design 170 checks hardest at a written cast |
| W22 | control: a LOSSLESS widening through the platform pair stays legal at every transfer position, and extends by the SOURCE's signedness | `W22_lossless_widening_transfer_positions.saw`, `int_widening_transfer_preserves_unsigned.saw`, `int_widening_argument_positions.saw` | 205 — the fence on W20/W21, and what makes the admission POSITIONAL rather than a loosening of general assignability. Four positions were wrong when the row was written (DF-205a: the implicit TAIL return, a fixed-array LITERAL element, a tuple element, an optional payload — the array face an outright ICE), which is DF-195a's mechanism at the positions its census did not reach |
| W23 | control: a BARE literal still adopts a fixed-width slot at every transfer position | `W23_bare_literal_adopts_transfer_positions.saw`, and the cross-module position at `qualified_call_literal_adopts_parameter_width.saw` + `qualified_call_threads_the_callee_signature.saw` | 205 — design 205's W17: the ergonomic the closed admission existed for, done properly by design 87's expected-type propagation. DF-238a was a POSITION this row's matrix could not reach, because it is only expressible across a module boundary: a MODULE-QUALIFIED free-function argument, where the callee's signature was never threaded, so the literal did not adopt and design 205's closing of the platform-pair admission turned a silent truncation into a refusal of an ordinary bare literal. Fixed Aug 21; the two files are the refusing and the accepting halves |
| W24 | control: two FIXED widths never convert implicitly at a transfer, either direction, lossless or not | `W24_fixed_width_transfer_never_converts_error.saw` | 205 — the no-code-change row (design 53), and the reference the platform pair was brought into line with: if a later brief loosens one of the two it has to answer for the other |

## Comparison operators must not consume an operand

Claim source: spec 5 *Comparison operators*; designs 32, 48, 216 (DF-216b), 239

`Equatable.equals(&self, other: &Self)` and `Comparable.compare(&self, other:
&Self)` take the right operand BY REFERENCE (design 239), which is what the
operator lowering has always passed. Nothing is transferred, so no conformance
can consume an operand and no checkpoint is owed — the guarantee holds by
construction at every tier and in every position.

It did not always. `other: Self` entitled a hand-written body to `move` the
operand while the lowering handed it a borrow, and the rows below are DF-216b's
seven-position matrix of what that cost, plus the eighth position (C12) found by
probing the stopgap's own premise. Design 216's stopgap refused six of them; the
signature change makes every refusal unrepresentable, so the rows that pinned a
REFUSAL now pin the CAPABILITY: a move-only type with a hand-written comparison
is comparable, and it is sound.

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| C01 | `<` `>` `<=` `>=` on a NoCopy operand with a hand-written `compare` compile and destroy nothing | `C01_order_operator_nocopy_handwritten_compare.saw` | 239 — DF-216b's found instance, restated as the capability; two drops for two values is the proof |
| C02 | `==` `!=` on a NoCopy operand with a hand-written `equals` | `C02_equality_operator_nocopy_handwritten_equals.saw` | 239 — the equality half, same signature |
| C03 | `==` in a MATCH-ARM GUARD | `C03_match_guard_equality_nocopy.saw` | 239 — an ordinary expression position, and the one where a consuming call would have been least visible |
| C04 | a `@synthesize`d memberwise comparison recursing into a member's hand-written body | `C04_synthesized_memberwise_reaches_handwritten.saw` | 239 — the recursion needs no transitive query now: what the emitter passes is what the member's body declares |
| C05 | enum payload-deep `==` reaching the payload type's hand-written body | `C05_enum_payload_reaches_handwritten.saw` | 239 — the same recursion through a payload |
| C06 | tuple `==` reaching an element type's hand-written body | `C06_tuple_element_reaches_handwritten.saw` | 239 — a tuple has no conformance of its own to inspect, and now needs none |
| C07 | `==` / `>` in a GENERIC body under `T: Equatable`/`T: Comparable`, instantiated at a NoCopy conformer | `C07_generic_body_operator_nocopy_instantiation.saw` | 239 — the position no chokepoint could see (a generic body is checked once with `T` abstract). Design 219 wave C answered it by judging the type ARGUMENT at the one discharge point; the signature removes the question, which is what makes generic sort/contains over move-only elements expressible |
| C08 | control: a Copy operand with a hand-written `equals` keeps its operator | `C08_implicitcopy_operand_handwritten_equals_legal.saw` | 239 — the row that said the stopgap's tier condition did not over-reach; there is no tier condition left |
| C09 | control: a NoCopy operand with a FULLY synthesized comparison tree keeps its operators and answers correctly | `C09_nocopy_synthesized_comparison_legal.saw` | 239 — the derived bodies read their operand through the reference too |
| C10 | the DIRECT call is the borrow: `a.equals(&b)` on a NoCopy operand and on an ExplicitCopy one | `C10_direct_call_transfer_spellings.saw` | 239 — the two spellings of one call agree, which is what DF-216b was about; `move b` / `b.copy()` are gone rather than optional |
| C11 | the ExplicitCopy tier | `C11_explicitcopy_operand_handwritten_compare.saw` | 239 — the other tier the stopgap refused, restated as the capability |
| C12 | a comparison destroys neither operand, at any tier | `C12_implicitcopy_operand_survives_consuming_equals.saw` | 239 — the eighth position, past the seven the class sweep probed. The stopgap excluded the Copy tier on the premise that retain semantics made the borrow sound; probed, the retain was never there, so 200 comparisons over-released a heap `String` (SIGTRAP on macOS, tolerated by glibc). The row pins the PROPERTY, and the reference satisfies it at every tier at once |
| C13 | an Equatable/Comparable conformance must take `other` by reference | `C13_comparison_conformance_must_borrow.saw` | 239 — the declaration-site half. The rule is general (a conformance's parameters mirror the requirement's borrows, both directions, `&` vs `&var` included) and reference-ness only; parameter types were previously not compared at all |
| C14 | a comparison body cannot consume its operand | `C14_comparison_body_cannot_consume_operand.saw` | 239 — the by-construction half, and why the class is closed rather than guarded: `move other` is the ordinary "cannot move out of reference", reported in the body at the line that wrote it |

## Shadowing

Claim source: spec 2 *Variables and Mutability*; designs 100, 107

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| S01 | a non-deriving shadow of an enclosing local | `errors/shadow_inner_let.saw` |  |
| S02 | a deriving shadow (`let n = n + 1`) | `shadow_derived.saw` |  |
| S03 | a `match` pattern binding shadowing an outer local | `errors/shadow_match_pattern.saw` |  |
| S04 | a closure parameter shadowing an enclosing local | `errors/shadow_closure_param.saw` |  |
| S05 | a `for` variable shadowing, with a non-deriving sequence | `errors/shadow_for_nonderived.saw` |  |
| S06 | a parameter shadowing a module `static` | `errors/shadow_param.saw` |  |
| S07 | a same-scope non-deriving redefinition | `errors/shadow_redef_nonderived.saw` |  |
| S08 | two same-named bindings across a suspension keep distinct slots | `coro_bind_id_shadow_regressions.saw` |  |
| S09 | a same-scope REDEFINITION of an OWNING local in a driven body | `S09_same_scope_redefinition_owning_across_suspend.saw` | DF-217a — S08's covering test binds an `Int`, where a collapsed slot is invisible (a trivial value has no deinit to run twice). With a NoCopy value the same shape double-freed the consumed original and then read a forgotten field: `force unwrap of None`, SIGABRT, on design 107's own idiom |

## Optionals and payload reads

Claim source: spec 3 *Optionals*; designs 111, 131, 174, 187, 218

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| O01 | value-read `let a = o!` on an ExplicitCopy payload | `errors/optional_payload_read_explicit_copy.saw` |  |
| O02 | value-read of a NoCopy payload via `if let` | `errors/optional_payload_read_nocopy.saw` |  |
| O03 | a Copy payload read retains; the optional stays valid | `optional_payload_read_retains.saw` |  |
| O04 | `move h.field!` — a partial move through a field | `errors/optional_move_unwrap_field.saw` |  |
| O05 | `Optional.take()` works on a field | `optional_take.saw` |  |
| O06 | `?.` final field projection of a move-only field | `errors/optional_chain_nocopy_field.saw` |  |
| O07 | a `?.` short-circuit skips the skipped call's argument side effects | `optional_chain_sideeffect_skip.saw` |  |
| O08 | `??` flattens — it never yields `U??` | `optional_coalesce_peel_depth.saw` |  |
| O09 | DF-174g: a bare value written into a two-layer optional slot — what value comes back? | `optional_nested_wrap_depth.saw` | 187 — was a DEVIATION (DF-174g: silent miscompile, exit 16); a bare value lands intact at any depth now |
| O10 | DF-174h: `??` with a default one layer too deep | `errors/optional_coalesce_default_too_deep.saw` |  |
| O11 | control: the sanctioned nested-optional route (`v.get(i)` on `Vector<Int?>`) | `optional_nested_wrap_depth.saw` |  |
| O12 | an `if let` binding out of a `move` scrutinee releases its payload once INSIDE a coroutine | `O12_iflet_move_binding_released_in_coroutine.saw` | DF-217b — codegen read the ownership off the AST shape (`isinstance(src, MoveExpr)`), and the coroutine transform's rewrite is what deletes that shape; a `self_opt` frame field reads back as a plain `MemberAccess`, so every driven function leaked the payload with no suspension near either binding |
| O13 | `if let _` / `guard let _` over a `move` scrutinee releases the payload it discards | `O13_wildcard_optional_binding_releases_moved_payload.saw` | DF-217l — design 111's `_` rider dropped only a fresh-TEMPORARY payload, so a `move` scrutinee (which retires the source binding just as completely) leaked, with no coroutine involved at all. Found sweeping O12's predicate |
| O14 | a presence test is TIER-INDEPENDENT — same question, same answer, every copy tier, at all three scrutinee spellings | `O14_presence_test_is_tier_independent.saw` | DF-218a — the guarantee was position-dependent, not universal: an UNCONDITIONAL lend of an optional-TYPED place (`Slot<T>.value()` at `T = Res?`) fell through to the value-read path, so a NoCopy payload could not be presence-tested AT ALL and a Copy tier paid a retain for an answer that never reads the payload. Fixed by design 218's ELABORATION PRINCIPLE — the position desugars to `is_some()` rather than growing a fourth classification arm. The row spans all three spellings because the split between them is the thing worth auditing: the conditional lend keeps its own lowering, where the `?` is the window's presence rather than a value |
| O15 | the Optional half of E12 — the parity control the asymmetry was measured against | `E12_autowrap_at_the_argument_position.saw` | DF-218f — every argument spelling in that file carries both payload kinds side by side, which is what makes "the two agree" auditable rather than asserted |

## Freestanding and `--no-hidden-alloc`

Claim source: spec 10 *No hidden allocations* + 8 *Profiles*; designs 113, 135, 137

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| N01 | `--no-hidden-alloc` rejects string interpolation | `no_hidden_alloc_interpolation.saw` |  |
| N02 | `--no-hidden-alloc` rejects a capturing escaping closure | `no_hidden_alloc_escaping_closure.saw` |  |
| N03 | `--no-hidden-alloc` rejects single-arg `print(user_printable)` | `no_hidden_alloc_print_printable.saw` |  |
| N04 | `--no-hidden-alloc` allows format-argument print | `no_hidden_alloc_named_allocations.saw` |  |
| N05 | `--freestanding` rejects a hosted-only std module | `N05_freestanding_hosted_module.saw` | the audit's flags could not enter the freestanding profile at all — `--freestanding` alone rejects this host's Mach-O triple first, so the row proved nothing. Retargeted at `riscv32-unknown-none-elf` |
| N06 | `@export` of a reserved runtime symbol without `--runtime-build` | `export_reserved_symbol_error.saw` |  |
| N07 | `@export` of a non-C-ABI type (String by value) | `export_string_error.saw` |  |

## Divergence — a `Never` expression never falls through

Claim source: spec 3 *Never — the type of an expression that does not return*; designs 49, 58, 177, 228

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| D01 | a diverging call is a valid `guard ... else` exit, at every callee kind | `D01_guard_else_diverging_exit.saw` |  |
| D02 | `return <diverging>` compiles, at every callee kind | `D02_return_diverging_operand.saw` |  |
| D03 | a diverging ARGUMENT aborts the call it was written in | `D03_diverging_call_argument.saw` |  |
| D04 | a diverging `??` default types as the payload | `D04_nil_coalesce_diverging_default.saw` |  |
| D05 | a diverging value-`if`/`match` arm takes the other arm's type, struct-typed and in either arm position | `D05_diverging_value_branch_arms.saw` |  |
| D06 | a diverging TAIL satisfies a struct return, and a `-> Never` body may end in a `-> Never` call | `D06_diverging_tail_and_never_chain.saw` |  |
| D07 | a `-> Never` method, static method, generic function and generic method are `void` + `noreturn` | `D07_never_method_and_generic.saw` |  |
| D08 | the indirect callee kinds diverge too: closure, `any Trait` vtable slot, trait default body | `D08_never_closure_vtable_default.saw` |  |
| D09 | every position behaves identically in the FREESTANDING profile | `D09_diverging_positions_freestanding.saw` |  |
| D10 | `group.spawn` of a `-> Never` body is refused | `D10_spawn_never_body_refused.saw` | 228 unit 5 — v1 REFUSES `suspending -> Never`; blessing the never-Done frame is re-proposable and owes a `NEVER` mangle case, a `Slot<Never>` zero-size story and a ruling on `join` |
| D11 | `Thread.spawn { ... }` with a diverging closure body is refused | `D11_spawn_closure_never_refused.saw` | same ruling |
| D12 | `__saw_drive` of a `-> Never` body is refused | `D12_drive_never_body_refused.saw` | same ruling |
| D13 | control does not continue past a diverging call — behaviourally and in the IR | `D13_no_fallthrough_past_diverging_call.saw` |  |
| D14 | the INDIRECT call shapes (`Arc`/`Box` payload forward, function-typed field) diverge, and an argument AFTER a diverging one is not lowered | `D14_diverging_forwarded_and_later_args.saw` |  |
| D15 | a `-> Never` `extern "C"` declaration and its definition agree on `void` + `noreturn` | `never_extern_module_abi.saw` |  |
| D16 | a break-less `while { }` types `Never` and satisfies a `-> Never` declaration | `while_never_diverges.saw` |  |
| D17 | `while true { }` is NOT `Never` | `errors/while_true_not_never.saw` |  |
| D18 | code after a diverging `while { }` is unreachable | `errors/while_never_unreachable_after.saw` |  |
| D19 | an `@export`ed `-> Never` function is emitted `noreturn` | `export_never_noreturn.saw` |  |
| D20 | a diverging result expression in a SUSPENDING body stores nothing | `coro_panic_value_position.saw` |  |

## Allocator failure — the fallibility tier (design 234)

Claim source: design 234 §1/§5 (the flip), superseding design 123's two-tier
policy. The tier had ZERO conformance rows before this brief: design 123 landed
ahead of the suite, and design 191's audit predates the flip. Rows land WITH the
sub-unit that flips their type, because a row can only assert one of the two
behaviors and the corpus has to agree with it — so this section grows through
unit 3 rather than arriving whole. A02 is the exception to that shape: it is a
DECLARATION rule rather than a flipped signature, so it lands with the brief-let
that makes a fallible constructor expressible at all.

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| A01 | a refused `Channel.send` reports the allocator as a VALUE — nothing panicked, nothing queued, nothing swallowed | `alloc_channel_send_reports_oom.saw` | 234 — supersedes design 123's panic, and DQ-230b's `try_send` twin with it |
| A02 | an `init`'s DECLARED return is checked against its receiver; the fallible form is `Result<Self, E>` and nothing else | `A02_init_declared_return_is_checked.saw` | DF-245a (ruled Aug 24) — the prerequisite for unit 3. Any other declared return was silently TWO types, surfacing as an unverifiable LLVM module rather than a diagnostic; `Self?` is refused on its own terms, since a `None` names no cause |

## Cross-cutting soundness smoke

Claim source: behavioral, not error-message — no single claim section

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| Z01 | reallocating push inside a `with_var_ref` element borrow | `errors/with_var_ref_invalidation.saw` |  |
| Z02 | two `remove`s of one NoCopy Map value (double-free smoke) | `map_owning_remove_overwrite.saw` |  |
| Z03 | replacing the whole container while a place window on it is open | `Z03_replace_container_during_window.saw` |  |
| Z04 | a shared window read leaves a `let` root unmutated | `place_shared_window_readonly.saw` |  |
| Z05 | an escaping closure copied: its captured env is torn down exactly once | `Z05_escaping_closure_env_deinit_once.saw` |  |
| Z06 | a window reached through a FIELD chain — does the write land? | `coro_ref_param_mut.saw` |  |

## What changed since the audit ran

26 rows are authored to a RULING rather than to the audit's own
expectation, and one more had a defective probe:

- **K01** — 186 — `Vector<Int>` IS `Send` (a container is Send iff its contents are), so the audit's probe proved nothing; the covering test uses a `Vector` of closures
- **K02** — 186 — same ruling; re-authored here with a `Vector` of closures as the non-Send local
- **K03** — 186 + 193 u6 — same ruling for the result type; the covering test uses a struct holding an `UnsafePointer`
- **K04** — 201 — SUPERSEDED: a reference parameter at a spawn root is legal in a single-threaded group under the extent rule, and refused into a `threads: N` one on Send
- **R25** — 201 — the same ruling read from the references-cannot-escape side: the reference does not escape, it borrows its root for the task's life
- **O09** — 187 — was a DEVIATION (DF-174g: silent miscompile, exit 16); a bare value lands intact at any depth now
- **P05** — 188 u3 — was a DEVIATION (accepted; writes vanished); refused now
- **P14** — 188 u3 — was a DEVIATION (`c.slot() = 99` was a silent no-op); refused now
- **P15** — 188 u3 — the audit expected the READ to keep working; the NARROW rule refuses the lend either way, so this row is a rejection
- **P16** — 188 u3 — was a DEVIATION (accepted); refused now
- **R10** — 188 u1 — was a DEVIATION (accepted, reached `Vector` storage, ICEd on read); refused at the payload now
- **R20** — 188 u1 — was a DEVIATION (the walk read types as written); aliases resolve before the walk now
- **R21** — 188 u1 — failed by accident on a type mismatch; fails by rule now
- **R24** — 188 u5 + 189 — was a NOTE (accepted); the capture is refused because `x` is declared AFTER its group
- **U24** — 188 u6 — was a NOTE (unenforced); the requirement-to-conformer direction is enforced now
- **U25** — 188 u6 — the audit expected a refusal; the reverse direction stays LEGAL under rule 7, so this row is an acceptance
- **U26** — 188 u6 — the audit expected acceptance; a safe conformer of an `unsafe` requirement is refused now
- **W01** — 188 u7 — was a DEVIATION (`SpinLock` resolved bare against a spec that said otherwise); gated now
- **X15** — 188 u2 — was refused by the COPY POLICY; an exclusivity diagnostic now
- **X16** — 188 u2 — was refused by the COPY POLICY; an exclusivity diagnostic now
- **X18** — 187 — was a DEVIATION (`n += 1` after a suspension ICEd); runs now
- **X20** — 188 u2 — was refused by the COPY POLICY; an exclusivity diagnostic now
- **X30** — 188 u2 — was a DEVIATION (accepted, both writes lost); refused now
- **X31** — 188 u2 — was a DEVIATION (accepted, the `&var` argument's writes lost); refused now
- **X33** — 188 u2 — was a DEVIATION (accepted on the auto-Copy tier); refused now
- **X40** — 188 u2 — was a DEVIATION (std `Data` corrupted: `d0=1 d1=1`); refused now
- **N05** — the audit's flags could not enter the freestanding profile at all — `--freestanding` alone rejects this host's Mach-O triple first, so the row proved nothing. Retargeted at `riscv32-unknown-none-elf`

All TWELVE of the audit's deviation rows (R10, R20, X18, X30, X31, X33, X40,
P05, P14, P16, O09, W01) are closed by those rulings, and all seven of its note
rows (R24, X15, X16, X20, U24, U25, K13). The last one closed:

- **K13** — was an XFAIL citing DF-191a: an MT group accumulating a per-task
  amount into a shared `Arc<Mutex<Int>>` was refused by the coroutine transform
  because the lock body captures the driven function's own parameter, and the
  diagnostic's suggested workaround tripped `Mutex.lock`'s `sync` requirement —
  so the canonical shared-counter idiom had no legal spelling at all. Design 196
  unit 4 routes every position that can host a materialized capture through one
  funnel; the row asserts the SUM now (four tasks adding 1..4 total 10),
  never an interleaving.

## Rows written ahead of their fix

Obligation 3 asks a safety-surface brief for its rows FIRST, so a row that
states a ruling the compiler has not been taught yet lands as a cited XFAIL and
the unit that teaches it removes the marker.

Closed: **G02-G04, G08-G14** — design 221's exit-status and `main`-rule rows,
written before the fix as obligation 3 asks. G02 flipped with unit B2 (the
single-frame executor), G03-G04 with unit B3 (the ambient root's cell), G12-G14
with unit C (the `main` rule), and G08-G11 with unit B4 (the exit funnel). G01,
G05-G07 and G15 passed on the unfixed tree and were the controls the fix had to
leave alone.

Closed: **C01-C08, C11-C12** — design 239's rows, restated ahead of the
signature change as obligation 3 asks and flipped by it. Each states what
`other: &Self` delivers — a comparison that compiles on a move-only operand
with a hand-written body, at every position and every tier, and destroys neither
operand. C09 and C10 are the controls that passed on the unfixed tree and had to
keep passing; C10 is also the evidence that the DIRECT call was never the broken
half. C13 and C14 landed with the mechanism rather than ahead of it — they name
diagnostics that did not exist yet. This subsumes the old entries for C07 (the
generic-body position design 219 wave C closed by judging the type argument) and
C12 (the eighth position, the Copy tier the stopgap's premise excluded): both
are removed by construction rather than answered, and the machinery that
answered them is deleted.

Closed: **K21, K22, K24** — design 210's three pins, all written under DF-206e.
K21 (a non-generic imported method embedding with its private siblings intact)
and K24 (the frame-slot authority) flipped with unit 3's annotation-preserving
splice; K22 (the generic twin) flipped with unit 4's home-scope recheck. K23
never carried a marker — it names the std rows that had to keep passing while
design 84's std-only accommodations were dissolved, and they did. K25 landed
with the unit that closed its position rather than ahead of it.

Closed: **K14-K20** — design 201's seven rows. The four refusals (K15, K17,
K18, K20) flipped with the typechecker in unit 2 — the extent it tracks reports
before the lowering runs; the three remaining rows (K14, K16 accept, K19 the MT
refusal) flipped with the lowering in unit 3, which is where design 88's blanket
confinement refusal was retired.

Closed: **B09** — written under an XFAIL citing DF-153b (a private std type
reserved its simple name for every program in the language, and the reserved
set was unknowable because std's private types are invisible), flipped by
design 204 unit 2. **B10** states the same rule from inside std (DF-153a); its
vehicle is a compiler-level test rather than a `.saw` row, so it landed with
the fix it pins instead of ahead of it.

Closed: **V26, V27** — written under an XFAIL citing DF-186a (`Atomic` was
bitwise-copyable, so a `let b = a` forked the counter silently and a struct
holding one owed no policy), flipped by design 202 unit 2.

Closed: **M31** — written under an XFAIL citing DF-176c (a `&self` method
writing through a place window on INLINE storage was a silent no-op into the
receiver copy), flipped by design 200 unit 2 and grown into that rule's
seven-position matrix in the same landing.

Closed: **X41, X44, X45** — written under an XFAIL citing DF-188j (a
by-reference argument created by a NESTED call did not join the outer call's
access set, so all three shapes compiled and answered by argument evaluation
order), flipped by design 199 unit 3.
