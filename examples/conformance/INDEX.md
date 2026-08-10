# The conformance suite — one row per claimed safety guarantee

Every row of the Aug-8 safety-guarantee audit (`safety_audit.md`, 247 rows
across 14 categories) is listed here with the test that checks it. A row is
either a file in this directory or an existing `examples/` test that already
asserts the same rule at the same position — this table is the record of which,
and the dedup decisions are meant to be audited from it.

**86 rows carry a file here; 194 are covered elsewhere.** (The audit's 247 plus
the rows later briefs added: W02-W05, design 194 unit 4; W06-W19, design 195
unit 1; X41-X45, design 199 unit 1; M31-M35, design 200 unit 1; V26-V30,
design 202 unit 1.)

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
| M26 | `&var self` method on a `let` of an auto-ImplicitCopy struct | `M26_varself_on_let_implicitcopy.saw` |  |
| M27 | interior mutability: Atomic field mutated at `&self` | `atomic_field_self_method.saw` |  |
| M28 | indirection carve-out: `self.rows[0].push` at `&self` | `shared_self_field_call_exemption.saw` |  |
| M29 | `&var` parameter mutation is visible at the caller | `references_basic.saw` |  |
| M30 | writing an immutable module `static` | `errors/static_assign_whole.saw` |  |
| M31 | `&self` method writing through a place window on INLINE storage — the rule's seven-position matrix (DF-176c) | `M31_shared_self_place_window_write.saw` | 200 — the last surviving member of the vanishing-write family; the write landed in the receiver copy and printed `first 1` |
| M32 | indirection carve-out through a place WINDOW: `self.rows[0][0] += 100` at `&self` | `M32_shared_self_place_window_heap_field.saw` | 200 — the accept side of the same ruling: the copy shares the buffer |
| M33 | a place write in the PROLOGUE of a `&self` borrows body | `M33_borrows_body_prologue_place_write.saw` | 200 — RATIFIED as intended: an accessor's receiver travels by pointer, so the write lands |
| M34 | a `#lend_var`-gated place write, exclusive specialization only | `M34_lend_var_gated_place_write.saw` | 200 — ratified with M33; the gate picks the flavor that pays |
| M35 | the same inline-field window write declared `&var self` | `M35_var_self_place_window_write.saw` | 200 — the fix M31's diagnostic names |

## References are parameters only — they can never escape

Claim source: spec 4 *Reference Types*; designs 88, 106, 163d, 188 u1, 193 u5

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
| R25 | spawned task frame taking a reference parameter (design 88) | `coro_spawn_ref_rejected.saw` |  |
| R26 | `Optional<&Int>` spelled via the written name | `R26_optional_written_name_ref.saw` |  |
| R27 | reference inside a nested generic (`Box<Vector<&Int>>`) | `R27_nested_generic_ref.saw` |  |
| R28 | the sanctioned crossing `(&var n) as UnsafePointer<Int>` | `ref_pointer_cast_blessed.saw` |  |
| R29 | `(&x) as Int` — not a pointer target | `errors/ref_cast_to_int_not_blessed.saw` |  |
| R30 | non-escaping borrow capture, closure passed directly | `closures_borrow_capture.saw` |  |
| R31 | `&` as a binary-expression operand | `R31_ref_as_binary_operand.saw` |  |
| R32 | storing a reference in a `Box` | `R32_box_of_ref.saw` |  |
| R33 | `borrows -> &Int` (a place whose type is a reference) | `R33_borrows_lends_ref_type.saw` |  |
| R34 | struct field whose type is a ref-returning function type | `R34_field_of_ref_returning_fn_type.saw` |  |

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
| X33 | two exclusive windows on an AUTO-ImplicitCopy struct (String member) | `X33_two_windows_implicitcopy_struct.saw` | 188 u2 — was a DEVIATION (accepted on the auto-ImplicitCopy tier); refused now |
| X40 | std `Data` (ImplicitCopy, has `d[i]`) — two windows in one call | `errors/place_window_data_corruption.saw` | 188 u2 — was a DEVIATION (std `Data` corrupted: `d0=1 d1=1`); refused now |
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
| V25 | deinit-once through an auto-ImplicitCopy struct copy (design 159 retain) | `V25_implicitcopy_deinit_once.saw` |  |
| V26 | `let b = a` on an `Atomic<Int>` local | `V26_copy_atomic_local.saw` | 202 — DF-186a: copying an atomic forked the counter silently, and had since design 41; move-only now |
| V27 | a struct holding an `Atomic` field with no declared policy | `V27_atomic_field_no_policy.saw` | 202 — an `Atomic` field contributes `NoCopy`, so the containment cascade names the field like any other |
| V28 | control: the declared-NoCopy holder builds, mutates and moves | `V28_atomic_holder_declares_nocopy.saw` | 202 — the accept side; one line of policy is the whole migration |
| V29 | control: a `static Atomic<Int>` mutated in place and lent by `&` | `V29_static_atomic_unaffected.saw` | 202 — statics are unaffected: a NoCopy static is legal and every atomic op takes `&self` |
| V30 | `move` of an `Atomic` local, into a binding, a call and a struct | `V30_move_atomic_local.saw` | 202 — `NoCopy` and deliberately not `NoMove`: nothing pins an atomic's address |

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
| T26 | joining an already-joined `TaskHandle` | `taskgroup_stale_handle_join.saw` |  |

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

## Concurrency safety

Claim source: spec 6 *Send and Sync* + *Cooperative tasks*; designs 75, 88, 103, 186, 188 u5, 189, 193 u6

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| K01 | a non-Send parameter crossing into a `threads: N` group | `errors/taskgroup_threads_nonsend_reject.saw` | 186 — `Vector<Int>` IS `Send` (a container is Send iff its contents are), so the audit's probe proved nothing; the covering test uses a `Vector` of closures |
| K02 | a non-Send across-suspend local in an MT group | `K02_nonsend_across_suspend_local_mt.saw` | 186 — same ruling; re-authored here with a `Vector` of closures as the non-Send local |
| K03 | a non-Send RESULT type from an MT-spawned task | `errors/spawn_result_not_send.saw` | 186 + 193 u6 — same ruling for the result type; the covering test uses a struct holding an `UnsafePointer` |
| K04 | a reference parameter at a spawned task root (design 88) | `coro_spawn_ref_rejected.saw` |  |
| K05 | a reference to a task-LOCAL inside a spawned body is fine | `coro_spawn_nested_ref.saw` |  |
| K06 | a `static` of a non-Sync type | `errors/static_non_sync.saw` |  |
| K07 | a suspending call inside a `SpinLock.lock` body (`sync` enforced) | `errors/spinlock_suspending_body.saw` |  |
| K08 | a suspending call in a `sync`-declared function | `errors/sync_direct_suspend.saw` |  |
| K09 | a `blocking` extern called from a `sync` context | `errors/blocking_extern_sync_reject.saw` |  |
| K10 | a `blocking` extern in the freestanding profile | `errors/offload_freestanding_reject.saw` |  |
| K11 | a `SpinLock` captured into a closure (NoCopy) | `K11_spinlock_captured.saw` |  |
| K12 | `Mutex.lock` body mutating through `&var T` | `mutex_lock_result.saw` |  |
| K13 | MT group accumulating into an `Arc<Mutex<Int>>` | `K13_mt_sum_under_mutex.saw` |  |

## Visibility and module boundaries

Claim source: spec 8 *Visibility* + *The prelude*; designs 80, 82, 142, 188 u7

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

## Integer width agreement

Claim source: spec 5 *Integer Conversions* + *Arithmetic* ; design 195

Rule 1: all typed operands of an operation have the SAME type — implicit
promotion happens from bare literals and nowhere else. Rule 2: value-branch
arms are TRANSFERS, so a lossless widening arm is legal exactly as at a
`return` and a lossy one is the ordinary transfer error. The rows are design
195's position matrix, one per line; W11 and W17 are the two CONTROLS that pin
what the rules do not touch.

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

## Optionals and payload reads

Claim source: spec 3 *Optionals*; designs 111, 131, 174, 187

| Row | Checks | Covered by | Ruling |
|-----|--------|------------|--------|
| O01 | value-read `let a = o!` on an ExplicitCopy payload | `errors/optional_payload_read_explicit_copy.saw` |  |
| O02 | value-read of a NoCopy payload via `if let` | `errors/optional_payload_read_nocopy.saw` |  |
| O03 | an ImplicitCopy payload read retains; the optional stays valid | `optional_payload_read_retains.saw` |  |
| O04 | `move h.field!` — a partial move through a field | `errors/optional_move_unwrap_field.saw` |  |
| O05 | `Optional.take()` works on a field | `optional_take.saw` |  |
| O06 | `?.` final field projection of a move-only field | `errors/optional_chain_nocopy_field.saw` |  |
| O07 | a `?.` short-circuit skips the skipped call's argument side effects | `optional_chain_sideeffect_skip.saw` |  |
| O08 | `??` flattens — it never yields `U??` | `optional_coalesce_peel_depth.saw` |  |
| O09 | DF-174g: a bare value written into a two-layer optional slot — what value comes back? | `optional_nested_wrap_depth.saw` | 187 — was a DEVIATION (DF-174g: silent miscompile, exit 16); a bare value lands intact at any depth now |
| O10 | DF-174h: `??` with a default one layer too deep | `errors/optional_coalesce_default_too_deep.saw` |  |
| O11 | control: the sanctioned nested-optional route (`v.get(i)` on `Vector<Int?>`) | `optional_nested_wrap_depth.saw` |  |

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

24 rows are authored to a RULING rather than to the audit's own
expectation, and one more had a defective probe:

- **K01** — 186 — `Vector<Int>` IS `Send` (a container is Send iff its contents are), so the audit's probe proved nothing; the covering test uses a `Vector` of closures
- **K02** — 186 — same ruling; re-authored here with a `Vector` of closures as the non-Send local
- **K03** — 186 + 193 u6 — same ruling for the result type; the covering test uses a struct holding an `UnsafePointer`
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
- **X33** — 188 u2 — was a DEVIATION (accepted on the auto-ImplicitCopy tier); refused now
- **X40** — 188 u2 — was a DEVIATION (std `Data` corrupted: `d0=1 d1=1`); refused now
- **N05** — the audit's flags could not enter the freestanding profile at all — `--freestanding` alone rejects this host's Mach-O triple first, so the row proved nothing. Retargeted at `riscv32-unknown-none-elf`

All TWELVE of the audit's deviation rows (R10, R20, X18, X30, X31, X33, X40,
P05, P14, P16, O09, W01) are closed by those rulings, and six of its seven note
rows (R24, X15, X16, X20, U24, U25). The seventh is the suite's one open gap:

- **K13** — XFAIL citing DF-191a: an MT group accumulating a per-task amount
  into a shared `Arc<Mutex<Int>>` is refused by the coroutine transform when
  the lock body captures the driven function's own parameter, and the
  diagnostic's suggested workaround trips `Mutex.lock`'s `sync` requirement.

## Rows written ahead of their fix

Obligation 3 asks a safety-surface brief for its rows FIRST, so a row that
states a ruling the compiler has not been taught yet lands as a cited XFAIL and
the unit that teaches it removes the marker.

Open: **V26, V27** — XFAIL citing DF-186a (`Atomic` is bitwise-copyable, so a
`let b = a` forks the counter and a struct holding one owes no policy). Design
202 unit 2 declares `NoCopy` on `Atomic` and removes both markers.

Closed: **M31** — written under an XFAIL citing DF-176c (a `&self` method
writing through a place window on INLINE storage was a silent no-op into the
receiver copy), flipped by design 200 unit 2 and grown into that rule's
seven-position matrix in the same landing.

Closed: **X41, X44, X45** — written under an XFAIL citing DF-188j (a
by-reference argument created by a NESTED call did not join the outer call's
access set, so all three shapes compiled and answered by argument evaluation
order), flipped by design 199 unit 3.
