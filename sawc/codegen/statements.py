"""
Statement generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for statements
including let bindings, assignments, and return statements.

Usage:
    class CodeGenerator(StatementsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import (
    Statement, LetStatement, AssignStatement, CompoundAssignStatement, ReturnStatement,
    GuardLetStatement, BreakStatement, ContinueStatement, ExpressionStatement,
    WhileExpr, ForLoop, Identifier, MemberAccess, ArrayIndex, SelfExpr,
    TupleIndex, MoveExpr, SawType, TypeKind,
    WildcardPattern, BindingPattern, TuplePattern,
)


class StatementsMixin:
    """Mixin providing statement generation methods for CodeGenerator.

    Methods:
        _generate_statement: Dispatch to appropriate statement generator
        _generate_let_statement: Generate let binding
        _expr_type: Read a checked expression's type annotation (fail-loud)
        _generate_assign_statement: Generate assignment
        _generate_return_statement: Generate return statement
    """

    def _generate_statement(self, stmt: Statement):
        """Generate code for a statement.

        Each full statement gets its own statement-scoped temporary list (item
        4): owned Deinit-needing values produced mid-statement that no binding
        takes ownership of (a method-call receiver, a discarded call result) are
        registered here and released LIFO once the statement finishes. Loops
        manage their own per-iteration scopes, so they keep the outer context.
        """
        # design 69: point the DWARF line table at this statement's source line
        # before lowering it (a line-0 synthesized node inherits the prior line).
        self._di_set_line(getattr(stmt, 'line', 0), getattr(stmt, 'column', 0))

        # Handle dual-purpose nodes (Expressions used as Statements)
        if isinstance(stmt, WhileExpr):
            self._generate_while_expr(stmt)
            return
        if isinstance(stmt, ForLoop):
            self._generate_for_loop(stmt)
            return

        # Visitor dispatch for all other statements
        method_name = f'visit_{stmt.__class__.__name__}'
        visitor = getattr(self, method_name, None)
        if visitor is None:
            raise ValueError(f"Unknown statement type: {type(stmt)}")

        saved_temps = self.statement_temps
        self.statement_temps = []
        try:
            visitor(stmt)
            temps = self.statement_temps
            # Release statement temporaries in reverse creation order (LIFO),
            # unless the statement already terminated the block (e.g. `return`,
            # which cleaned up through the scope machinery instead).
            if temps and not self.builder.block.is_terminated:
                for slot, saw_type in reversed(temps):
                    self._emit_drop_at(slot, saw_type)
        finally:
            self.statement_temps = saved_temps

    # ===== Statement Visitor Methods =====

    def visit_StaticAssert(self, stmt):
        """Design 53: a statement-position `static_assert` — evaluated at compile
        time, emits no code (a false result is a clean compile error)."""
        self._eval_static_assert(stmt)

    def visit_LetStatement(self, stmt: LetStatement):
        if stmt.name == "_":
            self._generate_discard_let(stmt)
            return
        self._generate_let_statement(stmt)

    def visit_DestructuringLet(self, stmt):
        """`let (a, b) = pair` / `var (x, y) = point` (design 63 T1d).

        Evaluate the source once and bind each component. When the source is a
        bare Identifier (copy semantics — ImplicitCopy/POD), each owning
        component is retained via `_generate_copy` since the source stays live;
        a `move` source (or a fresh tuple) transfers without a retain."""
        value = self._generate_expression(stmt.value)
        is_copy_source = isinstance(stmt.value, Identifier)
        src_type = self._expr_type(stmt.value)
        self._destructure_bind(stmt.pattern, value, src_type,
                               stmt.mutable, is_copy_source)

    def _pattern_binding_names(self, pattern):
        """All binding names introduced by an irrefutable pattern (skips `_`)."""
        if isinstance(pattern, BindingPattern):
            return [pattern.name]
        if isinstance(pattern, TuplePattern):
            names = []
            for e in pattern.elements:
                names += self._pattern_binding_names(e)
            return names
        return []

    def _destructure_bind(self, pattern, value, saw_type, mutable, copy):
        """Recursively bind an irrefutable tuple pattern's leaves."""
        if isinstance(pattern, WildcardPattern):
            # Per-position `_`: drop the component here (owning components are
            # released so the discard consumes exactly once).
            if saw_type is not None and self._needs_cleanup(saw_type):
                slot = self._entry_alloca(value.type, name="discard")
                self.builder.store(value, slot)
                self._emit_drop_at(slot, saw_type)
            return
        if isinstance(pattern, BindingPattern):
            comp = value
            if copy and saw_type is not None:
                comp = self._generate_copy(comp, saw_type)
            alloca = self._entry_alloca(comp.type, name=pattern.name)
            self.builder.store(comp, alloca)
            self.variables[pattern.name] = alloca
            if saw_type is not None:
                self.variable_types[pattern.name] = saw_type
                if self.cleanup_stack and self._needs_cleanup(saw_type):
                    self._register_cleanup(pattern.name, saw_type)
            return
        if isinstance(pattern, TuplePattern):
            rt = self._resolve_type_alias(saw_type) if saw_type is not None else None
            elem_types = rt.element_types if (rt is not None and rt.element_types) else [None] * len(pattern.elements)
            for idx, sub in enumerate(pattern.elements):
                comp = self.builder.extract_value(value, idx, name=f"destr_{idx}")
                self._destructure_bind(sub, comp, elem_types[idx], mutable, copy)

    def _generate_discard_let(self, stmt: LetStatement):
        """Design 53 / DF1: `let _ = expr` evaluates the RHS, takes ownership,
        and drops it at the end of THIS statement (immediately, like an unused
        temporary) — no binding is created. An ImplicitCopy lvalue is copied so
        the source is untouched and the COPY is what gets released."""
        value = self._generate_expression(stmt.value)
        var_type = (self._resolve_type_alias(stmt.type_annotation)
                    if stmt.type_annotation else self._expr_type(stmt.value))
        # A discard has no destination SLOT — nothing is stored, so nothing
        # wraps — while the annotation may still be opt-encoded (`let _:
        # String? = s`). Reconcile it with the value in hand ONCE, up front:
        # both the retain below and the drop registered after it are glue over
        # this same value, so both must be driven by the same type (DF-151c).
        var_type = self._transfer_type_for(value, var_type)
        if (var_type and isinstance(stmt.value, Identifier)
                and not isinstance(stmt.value, MoveExpr)):
            value = self._generate_copy(value, var_type)
        if (var_type and self._needs_cleanup(var_type)
                and not self.builder.block.is_terminated):
            self._register_stmt_temp(value, var_type)

    def visit_AssignStatement(self, stmt: AssignStatement):
        self._generate_assign_statement(stmt)

    def visit_CompoundAssignStatement(self, stmt: CompoundAssignStatement):
        self._generate_compound_assign_statement(stmt)

    def visit_ReturnStatement(self, stmt: ReturnStatement):
        self._generate_return_statement(stmt)

    def visit_GuardLetStatement(self, stmt: GuardLetStatement):
        self._generate_guard_let_statement(stmt)

    def visit_BreakStatement(self, stmt: BreakStatement):
        self._generate_break_statement(stmt)

    def visit_ContinueStatement(self, stmt: ContinueStatement):
        self._generate_continue_statement(stmt)

    def visit_ExpressionStatement(self, stmt: ExpressionStatement):
        # Expression used as statement - we don't need its result value
        value = self._generate_expression(stmt.expression, need_result=False)
        # A top-level owned temporary whose result is discarded (e.g. the final
        # link of a `a().b().c()` chain) is neither bound nor transferred, so it
        # must be released at statement end too. Register it LAST so it drops
        # FIRST (LIFO), before any receiver temporaries it was built from.
        if (self._is_owned_temporary(stmt.expression)
                and not self.builder.block.is_terminated):
            self._register_stmt_temp(value, self._expr_type(stmt.expression))

    def _generate_let_statement(self, stmt: LetStatement):
        """Generate code for a let binding."""
        value = self._generate_expression(stmt.value)

        # Resolve type alias in annotation
        resolved_annotation = self._resolve_type_alias(stmt.type_annotation) if stmt.type_annotation else None

        # Determine the variable type early for copy behavior. A written
        # annotation may omit trailing default type args (`Map<Int, R>`) or tag an
        # enum as STRUCT; canonicalize so the binding's kind/identity match the
        # monomorphized type — otherwise its deinit/cleanup lookup misses (design
        # 61): the element/buffer would leak at scope end.
        if resolved_annotation is not None:
            var_type = self._canonicalize_type_kind(resolved_annotation)
        else:
            var_type = self._expr_type(stmt.value)

        # A `let` initializer is a TRANSFER into a new home, so it takes the same
        # copy decision as every other transfer site — `_transfer_needs_copy`, the
        # oracle that reads the typechecker's `needs_copy` mark and re-derives the
        # projection rules codegen owns.
        #
        # DF-139a: this used to ask only "is the initializer a bare Identifier?".
        # That retained a whole-binding read (`let c = s`) but bitwise-aliased
        # every PROJECTION — `let c = h.s`, `let c = t.0`, `let c = arr[i]` — even
        # though the typechecker had marked the retain and every OTHER transfer
        # site (call argument, return, aggregate element) honored it. The source
        # still owned that storage, so overwriting it (`h.s = build(2)`) released
        # the value out from under the live copy, and the copy's own scope-exit
        # drop then freed it a second time.
        #
        # A `move` initializer transfers ownership and is not in the oracle's
        # aliasing set, so it still copies nothing.
        if var_type and self._transfer_site_needs_copy(stmt.value):
            value = self._generate_copy(value, var_type)

        # Handle None literal type conversion if assigning to optional with different inner type
        if resolved_annotation and resolved_annotation.kind == TypeKind.OPTIONAL:
            is_already_optional = (isinstance(value.type, ir.LiteralStructType) and
                                   len(value.type.elements) == 2 and
                                   isinstance(value.type.elements[0], ir.IntType) and
                                   value.type.elements[0].width == 1)

            if is_already_optional:
                # Value is optional, but check if it's a None literal with i64 placeholder
                # that needs to be converted to match a different expected type
                current_inner_type = value.type.elements[1]
                target_inner_type = self._get_llvm_type(resolved_annotation.inner_type)

                # Only convert if current is i64 (None literal placeholder) and target is something else
                needs_conversion = (isinstance(current_inner_type, ir.IntType) and
                                    current_inner_type.width == 64 and
                                    not (isinstance(target_inner_type, ir.IntType) and
                                         target_inner_type.width == 64))

                if needs_conversion:
                    # This is a None literal (i64 placeholder) being assigned to a different optional type
                    correct_optional_type = ir.LiteralStructType([ir.IntType(1), target_inner_type])

                    # Extract is_some flag (should be false for None)
                    is_some = self.builder.extract_value(value, 0, name="is_some")

                    # Create new optional with correct type
                    new_optional = ir.Constant(correct_optional_type, ir.Undefined)
                    new_optional = self.builder.insert_value(new_optional, is_some, 0)
                    # Don't set the value - it's undef for None anyway

                    value = new_optional

        # Rider (design 77 item 8 follow-up): NARROW a fixed-width integer LOCAL
        # to its annotated storage width. A bare-literal RHS (`let a: Int32 = 5`)
        # is generated at PLATFORM width (i64); without this the binding allocas
        # i64, so a later `-a` / overflow check runs at the wrong width and a
        # wire-format struct store reads too many bytes. The typechecker already
        # range-checked the literal against the annotation (design 65), so the
        # truncation is value-preserving; a widen is sign/zero-extended by
        # signedness. Suffixed/cast RHS values already carry the right width
        # (no-op here). Only same-family integer annotations are coerced.
        _signed_ints = {TypeKind.INT, TypeKind.INT8, TypeKind.INT16,
                        TypeKind.INT32, TypeKind.INT64}
        _unsigned_ints = {TypeKind.UINT, TypeKind.UINT8, TypeKind.UINT16,
                          TypeKind.UINT32, TypeKind.UINT64}
        if (resolved_annotation is not None and var_type is not None
                and var_type.kind in (_signed_ints | _unsigned_ints)
                and isinstance(value.type, ir.IntType)):
            target_llvm = self._get_llvm_type(resolved_annotation)
            if (isinstance(target_llvm, ir.IntType)
                    and target_llvm.width != value.type.width):
                if target_llvm.width < value.type.width:
                    value = self.builder.trunc(value, target_llvm)
                elif var_type.kind in _unsigned_ints:
                    value = self.builder.zext(value, target_llvm)
                else:
                    value = self.builder.sext(value, target_llvm)

        # Design 107: a DERIVED same-scope redefinition REPLACES the old binding.
        # The initializer above already consumed (`move`) or copied the old
        # value; drop the old binding now if it still owns one (a `.copy()`
        # derivation), retiring its scope-exit cleanup so it never double-frees.
        self._drop_redefined_same_scope(stmt.name)

        # A local at `Void` has no storage to name (design 132 unit C / DF-123b).
        # The typechecker already rejects a CONCRETE `let n = <Void expr>`
        # (design 122), but a local typed by the method's own type parameter is
        # checked abstractly and only becomes Void at an instantiation — which is
        # the natural body of `Mutex.lock<R>`, where a critical section that
        # computes nothing is the common case. That reached `alloca(void)` and
        # tripped an llvmlite assertion, surfacing as an `internal compiler
        # error:` with an EMPTY message. There is nothing to store and nothing to
        # clean up, so record the name as void-valued and read it back as Void.
        if isinstance(value.type, ir.VoidType):
            self.void_variables.add(stmt.name)
            self.variables.pop(stmt.name, None)
            return

        alloca = self._entry_alloca(value.type, name=stmt.name)
        self.builder.store(value, alloca)
        self.variables[stmt.name] = alloca
        self.void_variables.discard(stmt.name)

        # Track variable type for resource management
        if var_type:
            self.variable_types[stmt.name] = var_type
            # Track for cleanup if type implements Deinit/ImplicitCopy/NoCopy.
            # A `let`/`var` binding can be `move`d, so register it with a drop flag
            # (design 42) for conditional-move correctness.
            if self.cleanup_stack and self._needs_cleanup(var_type):
                self._register_cleanup(stmt.name, var_type)

    def _transfer_site_needs_copy(self, value_expr) -> bool:
        """Whether a `let` initializer or an ASSIGNMENT RHS must retain the value
        it reads (DF-139a, extended to assignments by DF-151h).

        The answer is the shared transfer oracle's, with ONE carve-out: indexing
        a RAW POINTER. `self.buffer[i]` inside `Vector`/`Map` is the unsafe
        domain's manual bookkeeping, not a read out of storage the compiler
        tracks ownership of, and std deliberately takes a bare alias there and
        decides the retain at the SUBSEQUENT use — `Vector.get` retains when it
        returns the element, while `Vector.swap_out` overwrites the slot and
        `move`s the alias out, which must stay at exactly one reference. Making
        the read itself retain left every `swap_out` result over-retained (a leak
        the Map/Set refcount-balance oracles catch).

        A fixed array (`[T; N]`) index is NOT this case: it is ordinary safe
        storage the source keeps owning, so it retains like a field.
        """
        if isinstance(value_expr, ArrayIndex):
            base = getattr(value_expr, 'array_expr', None)
            base_type = getattr(base, 'resolved_type', None) if base is not None else None
            if base_type is not None and base_type.kind == TypeKind.POINTER:
                return False
        return self._transfer_needs_copy(value_expr)

    def _expr_type(self, expr) -> SawType:
        """Return the SawType of an expression from its typechecker annotation.

        This is the single accessor codegen uses for expression types. It reads
        ``expr.resolved_type`` (stamped by the typechecker at its
        ``_check_expression`` chokepoint) and, when that type mentions generic
        type parameters, substitutes the current monomorphization bindings.

        It fails *loud*, never silent: an unannotated expression is a compiler
        bug (the typechecker must annotate every expression it checks, and
        codegen-synthesized nodes must set ``resolved_type`` at creation). A
        silent ``None`` here is exactly what previously disabled cleanup
        registration and copy insertion and leaked resources.
        """
        resolved = getattr(expr, 'resolved_type', None)
        if resolved is None:
            node = type(expr).__name__
            line = getattr(expr, 'line', '?')
            column = getattr(expr, 'column', '?')
            raise ValueError(
                f"internal compiler error: expression node `{node}` at "
                f"{line}:{column} reached codegen without a resolved_type; "
                f"the typechecker must annotate every expression before codegen"
            )
        # Substitute generic type parameters using the active monomorphization
        # bindings (empty outside of a specialized generic body).
        if self.type_param_context:
            resolved = resolved.substitute(self.type_param_context)
        return resolved

    def _generate_assign_statement(self, stmt: AssignStatement):
        """Generate code for an assignment statement."""
        value = self._generate_expression(stmt.value)

        if isinstance(stmt.target, Identifier):
            # Simple variable assignment — or a whole-value write to an
            # `unsafe static var`, whose storage is a global (design 149).
            target_ptr = self._identifier_storage(stmt.target)

            # Get the variable's type for resource management. A static has no
            # entry in `variable_types`; the typechecker stamps its type on the
            # target node instead.
            is_static_target = stmt.target.name not in self.variables
            var_type = self.variable_types.get(stmt.target.name)
            if var_type is None:
                var_type = getattr(stmt.target, 'resolved_type', None)

            # Design 110: whole-referent replacement through a `&var` reference
            # parameter. The variable holds a POINTER to the caller's value; load
            # it, deinit the old value at that address, then store the new one —
            # the through-ref counterpart of the plain-variable path below.
            if var_type is not None and var_type.kind == TypeKind.REFERENCE:
                referent_ptr = self.builder.load(
                    self.variables[stmt.target.name],
                    name=f"{stmt.target.name}_ref")
                self._store_replacement_through_ptr(
                    stmt, value, referent_ptr, var_type.inner_type)
                return

            if var_type:
                # Call deinit on the old value before overwriting. Never for a
                # static: statics are immortal, and design 149 keeps that honest
                # by admitting only trivially-destructible types, so there is no
                # destructor here that should have run.
                if self._needs_cleanup(var_type) and not is_static_target:
                    self._generate_deinit_call(stmt.target.name, var_type)

                # An assignment RHS is a TRANSFER into a new home and takes the
                # same copy decision every other transfer site takes (DF-151h).
                # It used to ask only "is the RHS a bare Identifier?" — the very
                # question DF-139a had already retired at the `let` path one
                # statement kind over — so `a = h.r` / `a = t.0` / `a = arr[i]`
                # bitwise-aliased a value the source keeps owning, and both
                # halves then released it.
                if self._frame_owning_read_copy(stmt.value):
                    # design 124: see the field-assignment path below.
                    value = self._generate_copy(value, self._expr_type(stmt.value))
                elif isinstance(stmt.value, Identifier) or \
                        self._transfer_site_needs_copy(stmt.value):
                    value = self._generate_copy_for_dest(value, var_type)

                # Wrap in optional if assigning T to T?
                expected_type = self._get_llvm_type(var_type)
                if (var_type.is_optional() and
                    self._is_optional_type(expected_type) and
                    not self._is_optional_type(value.type)):
                    value = self._wrap_in_optional(value)

            self.builder.store(value, target_ptr)
            # DF-146h: re-arm the drop flag of a moved-from local. A static
            # target has no drop flag (statics are immortal).
            if not is_static_target:
                self._revive_assigned_binding(stmt.target.name, var_type)

        elif (isinstance(stmt.target, MemberAccess)
                and getattr(stmt.target, 'tuple_field_index', None) is not None):
            # NAMED-TUPLE element write `pair.x = fresh` (DF-151j): the label is
            # a position, so this is the tuple-slot store below under its other
            # spelling. Split out ahead of the field path because a tuple has no
            # `struct_types` entry to look its layout up in.
            idx = stmt.target.tuple_field_index
            self._store_into_tuple_slot(
                stmt, value, self._get_member_pointer(stmt.target),
                self._tuple_element_saw_type(stmt.target.object, idx))

        elif isinstance(stmt.target, TupleIndex):
            # WHOLE-ELEMENT TUPLE WRITE `t.0 = fresh` (DF-151j).
            self._store_into_tuple_slot(
                stmt, value, self._get_tuple_element_pointer(stmt.target),
                self._tuple_element_saw_type(stmt.target.tuple_expr,
                                             stmt.target.index))

        elif isinstance(stmt.target, MemberAccess):
            # Field assignment: obj.field = value
            # Resolve a pointer to the object's REAL storage (variable, self,
            # nested field, or array/pointer element). _get_lvalue_pointer
            # recurses and unwraps references, so an array-element base
            # (`a[i].field = x`) GEPs into the live array rather than a
            # throwaway copy (design 39 item 1).
            obj_expr = stmt.target.object
            struct_ptr = self._get_lvalue_pointer(obj_expr)

            # Determine struct type and field index
            # Get the actual struct type (dereference if it's a pointer)
            pointee_type = struct_ptr.type.pointee

            # Find which struct this is
            struct_name = None
            if hasattr(pointee_type, 'name') and pointee_type.name in self.struct_types:
                # Identified type - name is directly available
                struct_name = pointee_type.name
            else:
                # Fallback to string comparison for literal types
                for name, (st, _) in self.struct_types.items():
                    if str(st) == str(pointee_type):
                        struct_name = name
                        break

            if not struct_name:
                raise ValueError("Cannot determine struct type for field assignment")

            # Get field index
            _, field_order = self.struct_types[struct_name]
            if stmt.target.member not in field_order:
                raise ValueError(f"Struct {struct_name} has no field {stmt.target.member}")

            field_index = field_order.index(stmt.target.member)

            # Generate GEP to get pointer to field
            field_ptr = self.builder.gep(struct_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), field_index)
            ], name=f"{stmt.target.member}_ptr")

            # LIVE-SLOT RELEASE (design 39 item 2, extended to struct fields): a
            # struct field always holds a live value — fields are fully
            # initialized at construction and partial moves are forbidden
            # (design 35) — so overwriting an owning field must run the old
            # value's drop glue BEFORE the store, exactly as the variable- and
            # array-element-assignment paths do. Without this, `self.field =
            # move new` (e.g. Map._grow's `self.slots = move new_slots`) leaks
            # the old field's backing buffer. The drop goes through the field's
            # OWN concrete type, so a `Vector<..., A>` field frees via its
            # allocator `A`, not a default.
            field_saw = self._struct_field_saw_type(struct_name, stmt.target.member)
            if field_saw is not None and self._needs_cleanup(field_saw):
                self._emit_drop_at(field_ptr, field_saw)
            # ImplicitCopy retain when the RHS is an existing binding (mirrors the
            # variable- and array-element-assignment paths); NoCopy/ExplicitCopy
            # already moved at the value-transfer checkpoint.
            if (field_saw is not None
                    and not self._frame_owning_read_copy(stmt.value)
                    and (isinstance(stmt.value, Identifier)
                         or self._transfer_site_needs_copy(stmt.value))):
                value = self._generate_copy_for_dest(value, field_saw)
            elif self._frame_owning_read_copy(stmt.value):
                # design 124: a coroutine frame reading one of its own owned
                # locals (`self.name!`) into another field — `__result` at a
                # `return loc`, a sub-frame's param slot — duplicates it: the
                # source field keeps its drop flag and is released at the task's
                # eager teardown. Copy against the VALUE's type, not the field's
                # (the same rule `_generate_copy_for_dest` applies above).
                value = self._generate_copy(value, self._expr_type(stmt.value))

            # Check if we need to wrap in optional (non-optional value for optional
            # field). Use `_is_optional_type` (a 2-element {i1, T}) rather than a
            # bare "not a struct" test, so a struct-typed inner also wraps — e.g. an
            # opt-encoded coroutine closure frame field `f: (()->Int)?` whose value
            # is the 3-word closure struct (design 77 item 4).
            expected_field_type = field_ptr.type.pointee
            if (self._is_optional_type(expected_field_type)
                    and not self._is_optional_type(value.type)):
                value = self._wrap_in_optional(value)

            # Store value to field
            self.builder.store(value, field_ptr)

        elif isinstance(stmt.target, ArrayIndex):
            # Array or pointer element assignment: arr[i] = value or ptr[i] = value
            container_expr = stmt.target.array_expr
            index_val = self._generate_expression(stmt.target.index)

            # Get pointer to the container
            if isinstance(container_expr, Identifier):
                container_ptr = self._identifier_storage(container_expr)

                # Load the container value to check its type
                container_val = self.builder.load(container_ptr, name="container")

                if isinstance(container_val.type, ir.ArrayType):
                    # Dynamic bounds check (design 63 T1b) on `arr[i] = v`.
                    self._emit_array_bounds_check(index_val, container_val.type.count, stmt.target.index)
                    # Array: GEP with two indices [0, index]
                    zero = ir.Constant(ir.IntType(64), 0)
                    elem_ptr = self.builder.gep(container_ptr, [zero, index_val], name="elem_ptr")
                    # LIVE-SLOT RELEASE (design 39 item 2): a fixed-array element
                    # slot always holds a live value, so overwriting it must run
                    # the old value's drop glue BEFORE the store — exactly as the
                    # Identifier-target path releases its prior value. (The
                    # PointerType branch below is the placement primitive and
                    # deliberately does NOT release: it fills uninitialized slots.)
                    container_saw = self._expr_type(container_expr)
                    elem_saw = (container_saw.array_element_type
                                if container_saw is not None else None)
                    if elem_saw is not None and self._needs_cleanup(elem_saw):
                        self._emit_drop_at(elem_ptr, elem_saw)
                    # The incoming element is a transfer site: retain an
                    # ImplicitCopy value copied from an existing binding (mirrors
                    # the Identifier-target path). NoCopy/ExplicitCopy already
                    # moved at the value-transfer checkpoint.
                    if elem_saw is not None and (
                            isinstance(stmt.value, Identifier)
                            or self._transfer_site_needs_copy(stmt.value)):
                        value = self._generate_copy_for_dest(value, elem_saw)
                elif isinstance(container_val.type, ir.PointerType):
                    # Pointer: GEP with single index.
                    #
                    # PLACEMENT-MOVE PRIMITIVE (see LANGUAGE_SPEC "Placement
                    # writes"): the store to `elem_ptr` below (`ptr[i] = value`)
                    # bitwise-moves `value` into the target slot. The source is
                    # consumed by the value-transfer checkpoint in the
                    # typechecker, but — unlike the Identifier target above, which
                    # calls _generate_deinit_call on the prior value first — this
                    # path performs NO destination release. It assumes the slot
                    # is uninitialized; using it on a slot that holds a live
                    # value leaks that value (its deinit never runs). This is the
                    # primitive stdlib containers use to fill fresh buffer slots;
                    # the canonical user is Vector.push, which only ever writes
                    # the never-yet-written tail slot at `length`.
                    elem_ptr = self.builder.gep(container_val, [index_val], name="ptr_elem")
                else:
                    raise ValueError(f"Cannot index into type: {container_val.type}")
            else:
                container_saw = self._expr_type(container_expr)
                if (container_saw is not None
                        and container_saw.kind == TypeKind.ARRAY):
                    # A fixed-array FIELD or nested element (`self.data[i] = b`,
                    # `outer.rows[i] = v`). This used to fall through to the
                    # pointer branch below and raise an internal compiler error:
                    # the container was evaluated as a VALUE, and an array value
                    # is not a pointer to GEP through. Address the real storage
                    # instead, exactly as the Identifier branch does — the same
                    # bounds check, the same live-slot release, the same
                    # ImplicitCopy retain — so the write lands in the field
                    # rather than in a copy of it.
                    container_ptr = self._get_lvalue_pointer(container_expr)
                    pointee = container_ptr.type.pointee
                    if not isinstance(pointee, ir.ArrayType):
                        raise ValueError(
                            f"array assignment target is not array storage: "
                            f"{pointee}")
                    self._emit_array_bounds_check(
                        index_val, pointee.count, stmt.target.index)
                    zero = ir.Constant(ir.IntType(64), 0)
                    elem_ptr = self.builder.gep(
                        container_ptr, [zero, index_val], name="elem_ptr")
                    elem_saw = container_saw.array_element_type
                    if elem_saw is not None and self._needs_cleanup(elem_saw):
                        self._emit_drop_at(elem_ptr, elem_saw)
                    if elem_saw is not None and (
                            isinstance(stmt.value, Identifier)
                            or self._transfer_site_needs_copy(stmt.value)):
                        value = self._generate_copy_for_dest(value, elem_saw)
                else:
                    # A non-identifier container (e.g. `self.field_ptr[i] = v`,
                    # design 52b): evaluate it as a value; a pointer-typed one
                    # GEPs like the Identifier pointer branch (placement-move
                    # primitive, no release — the slot is caller-managed raw
                    # memory).
                    container_val = self._generate_expression(container_expr)
                    if isinstance(container_val.type, ir.PointerType):
                        elem_ptr = self.builder.gep(
                            container_val, [index_val], name="ptr_elem")
                    else:
                        raise ValueError(f"Unsupported container expression in assignment: {type(container_expr)}")

            # Coerce value type if needed (e.g., Int -> Int8)
            elem_type = elem_ptr.type.pointee
            if isinstance(value.type, ir.IntType) and isinstance(elem_type, ir.IntType):
                if value.type.width > elem_type.width:
                    # Truncate larger int to smaller
                    value = self.builder.trunc(value, elem_type, name="trunc")
                elif value.type.width < elem_type.width:
                    # Extend smaller int to larger (sign extend)
                    value = self.builder.sext(value, elem_type, name="sext")

            # Wrap a bare `T` into `T?` when the SLOT is opt-encoded — the same
            # last step the variable and field assignment paths take, and the
            # reason the copy above is driven by `_generate_copy_for_dest`
            # (DF-151c: the value in hand is the payload, the wrap comes after).
            # Missing here until DF-151e, because no `[T?; N]` could be built to
            # reach it: `b[0] = s` on a `[String?; 2]` stored a bare `i8*` into a
            # `{i1, i8*}` slot.
            if (self._is_optional_type(elem_type)
                    and not self._is_optional_type(value.type)):
                value = self._wrap_in_optional(value)

            # Store value to element
            self.builder.store(value, elem_ptr)

            # Placement-MOVE bookkeeping (design 65): a pointer-target store
            # (`ptr[i] = value`, Vector.push/set's primitive) bitwise-MOVES the
            # source into the slot. If the source is an owned binding carrying a
            # drop flag, clear it — the value now lives in the buffer and must NOT
            # also drop at scope exit. This is the move a drop flag previously
            # "could not observe"; observing it here is what makes registering
            # owning by-value params of instance methods safe (they release when
            # used-and-not-moved, and do not double-free when placement-moved).
            if (isinstance(stmt.target.array_expr, Identifier)
                    and isinstance(container_val.type, ir.PointerType)
                    and isinstance(stmt.value, Identifier)):
                flag = self.drop_flags.get(stmt.value.name)
                if flag is not None:
                    self.builder.store(ir.Constant(ir.IntType(1), 0), flag)
                self.moved_variables.add(stmt.value.name)

        elif isinstance(stmt.target, SelfExpr):
            # Design 110: `self = v` in a `&var self` method. `self` is bound to
            # the caller's storage pointer directly (methods.py registers the
            # mutable-self arg as the pointer itself), so it already IS the
            # referent address — no reference load, unlike the Identifier path.
            self_ptr = self.variables.get("self")
            if self_ptr is None:
                raise ValueError("`self = v` outside a method")
            self._store_replacement_through_ptr(
                stmt, value, self_ptr, self.variable_types.get("self"))

        else:
            raise ValueError(f"Invalid assignment target: {type(stmt.target)}")

    def _tuple_element_saw_type(self, tuple_expr, index):
        """The SawType of element `index` of the tuple `tuple_expr` denotes, or
        None if the annotation is not a usable tuple type."""
        tuple_saw = self._expr_type(tuple_expr)
        if tuple_saw is None:
            return None
        tuple_saw = self._resolve_type_alias(tuple_saw)
        elements = getattr(tuple_saw, 'element_types', None)
        if not elements or index < 0 or index >= len(elements):
            return None
        return elements[index]

    def _store_into_tuple_slot(self, stmt, value, elem_ptr, elem_saw):
        """Store a whole-element tuple write into its slot (DF-151j).

        Mirrors the struct-field path step for step, because a tuple element is
        the same kind of storage: the slot always holds a LIVE value (a tuple is
        fully initialized at construction and partial moves are forbidden), so
        the overwritten element's drop glue runs BEFORE the store and it deinits
        exactly once; an ImplicitCopy RHS that is an existing binding is
        retained; a coroutine frame reading one of its own owned locals
        duplicates against the VALUE's type (design 124); a bare `T` into an
        opt-encoded slot wraps last.
        """
        if elem_saw is not None and self._needs_cleanup(elem_saw):
            self._emit_drop_at(elem_ptr, elem_saw)
        if (elem_saw is not None
                and not self._frame_owning_read_copy(stmt.value)
                and (isinstance(stmt.value, Identifier)
                     or self._transfer_site_needs_copy(stmt.value))):
            value = self._generate_copy_for_dest(value, elem_saw)
        elif self._frame_owning_read_copy(stmt.value):
            value = self._generate_copy(value, self._expr_type(stmt.value))
        expected_type = elem_ptr.type.pointee
        if (self._is_optional_type(expected_type)
                and not self._is_optional_type(value.type)):
            value = self._wrap_in_optional(value)
        self.builder.store(value, elem_ptr)

    def _store_replacement_through_ptr(self, stmt, value, referent_ptr,
                                       referent_saw):
        """Design 110 replacement-assignment store: release the old referent
        value at `referent_ptr`, then install `value`. Mirrors the plain-variable
        and through-ref field-assignment paths (deinit old, ImplicitCopy-retain a
        plain-binding RHS, optional-wrap, store); `referent_ptr` already points at
        the caller's real storage, so the write lands in the caller's slot."""
        # A generic `&var T` param records the ABSTRACT `T` referent in
        # variable_types (params are stored unsubstituted); substitute the active
        # monomorphization so the drop glue and copy tier are the concrete
        # instantiation's — an abstract `T` reads as non-owning and would LEAK the
        # replaced value (its deinit never runs).
        if referent_saw is not None:
            referent_saw = self._substitute_saw_type(
                referent_saw, self.type_param_context)
        if referent_saw is not None and self._needs_cleanup(referent_saw):
            self._emit_drop_at(referent_ptr, referent_saw)
        # An ImplicitCopy RHS that is an existing binding is retained (mirrors the
        # variable/field/element paths); NoCopy/ExplicitCopy already moved at the
        # value-transfer checkpoint, and `move v`/temporaries are not Identifiers.
        if referent_saw is not None and (
                isinstance(stmt.value, Identifier)
                or self._transfer_site_needs_copy(stmt.value)):
            value = self._generate_copy_for_dest(value, referent_saw)
        expected_type = referent_ptr.type.pointee
        if (self._is_optional_type(expected_type)
                and not self._is_optional_type(value.type)):
            value = self._wrap_in_optional(value)
        self.builder.store(value, referent_ptr)

    def _generate_compound_assign_statement(self, stmt: CompoundAssignStatement):
        """Generate code for a compound assignment statement (+=, -=, *=, /=, %=).

        For regular variables: x += 1 becomes x = x + 1
        For references: y += 1 loads through pointer, computes, stores back
        """
        # `x += y` is `x = x + y`, so it takes the same overflow-checked path as
        # the binary operators (design 31). Signedness comes from the target's
        # annotated type (references and unannotated targets default to signed,
        # which is harmless: only the integer add/sub/mul/div branches consult
        # it, and unsigned targets are reliably annotated).
        signed = self._int_is_signed(stmt.target)

        # Get pointer to target
        if isinstance(stmt.target, Identifier):
            var_name = stmt.target.name
            target_ptr = self._identifier_storage(stmt.target)

            # Check if this is a reference type - if so, it's already a pointer to the data
            var_type = self.variable_types.get(var_name)
            if var_type and var_type.kind == TypeKind.REFERENCE:
                # For references, the variable holds a pointer to the actual data
                # Load the pointer (which points to the referenced value)
                actual_ptr = self.builder.load(target_ptr, name=f"{var_name}_ref")
                # Load current value through the pointer
                current_val = self.builder.load(actual_ptr, name=f"{var_name}_val")
                # Compute new value
                rhs = self._generate_expression(stmt.value)
                new_val = self._apply_compound_op(stmt.op, current_val, rhs, signed)
                # Store back through the pointer
                self.builder.store(new_val, actual_ptr)
            else:
                # Regular variable - load, compute, store
                current_val = self.builder.load(target_ptr, name=f"{var_name}_val")
                rhs = self._generate_expression(stmt.value)
                new_val = self._apply_compound_op(stmt.op, current_val, rhs, signed)
                self.builder.store(new_val, target_ptr)

        elif isinstance(stmt.target, MemberAccess):
            # Field compound assignment: obj.field += value
            field_ptr = self._get_member_pointer(stmt.target)
            current_val = self.builder.load(field_ptr, name="field_val")
            rhs = self._generate_expression(stmt.value)
            new_val = self._apply_compound_op(stmt.op, current_val, rhs, signed)
            self.builder.store(new_val, field_ptr)

        elif isinstance(stmt.target, TupleIndex):
            # Tuple element compound assignment `t.0 += value` (DF-151j) — the
            # element slot, loaded and stored back through the same address.
            elem_ptr = self._get_tuple_element_pointer(stmt.target)
            current_val = self.builder.load(elem_ptr, name="tuple_elem_val")
            rhs = self._generate_expression(stmt.value)
            new_val = self._apply_compound_op(stmt.op, current_val, rhs, signed)
            self.builder.store(new_val, elem_ptr)

        elif isinstance(stmt.target, ArrayIndex):
            # Array element compound assignment: arr[i] += value
            container_expr = stmt.target.array_expr
            index_val = self._generate_expression(stmt.target.index)

            if isinstance(container_expr, Identifier):
                container_ptr = self._identifier_storage(container_expr)

                # Load the container value to check its type
                container_val = self.builder.load(container_ptr, name="container")

                if isinstance(container_val.type, ir.ArrayType):
                    # Dynamic bounds check (design 63 T1b) on `arr[i] += v`.
                    self._emit_array_bounds_check(index_val, container_val.type.count, stmt.target.index)
                    # Array: GEP with two indices [0, index]
                    zero = ir.Constant(ir.IntType(64), 0)
                    elem_ptr = self.builder.gep(container_ptr, [zero, index_val], name="elem_ptr")
                elif isinstance(container_val.type, ir.PointerType):
                    # Pointer: GEP with single index
                    elem_ptr = self.builder.gep(container_val, [index_val], name="ptr_elem")
                else:
                    raise ValueError(f"Cannot index into type: {container_val.type}")
            else:
                raise ValueError(f"Unsupported container expression in compound assignment: {type(container_expr)}")

            current_val = self.builder.load(elem_ptr, name="elem_val")
            rhs = self._generate_expression(stmt.value)
            new_val = self._apply_compound_op(stmt.op, current_val, rhs, signed)
            self.builder.store(new_val, elem_ptr)

        else:
            raise ValueError(f"Invalid compound assignment target: {type(stmt.target)}")

    def _apply_compound_op(self, op: str, left, right, signed: bool = True):
        """Apply a compound assignment operator and return the result.

        Integer +/-/* are overflow-checked and integer //% are zero-divisor and
        INT_MIN/-1 checked, exactly as the corresponding binary operators
        (design 31) -- `x += y` must not silently wrap where `x = x + y` panics.
        Float ops are untouched.

        Unlike the binary-operator path these checks pass no explicit panic line
        (design 122 unit I): a compound assignment IS the statement, so the line
        the statement walk already announced is the operator's own line.
        """
        is_float = isinstance(left.type, ir.DoubleType)

        if op == '+':
            if is_float:
                return self.builder.fadd(left, right, name="addtmp")
            return self._checked_arith('+', left, right, signed)
        elif op == '-':
            if is_float:
                return self.builder.fsub(left, right, name="subtmp")
            return self._checked_arith('-', left, right, signed)
        elif op == '*':
            if is_float:
                return self.builder.fmul(left, right, name="multmp")
            return self._checked_arith('*', left, right, signed)
        elif op == '/':
            if is_float:
                return self.builder.fdiv(left, right, name="divtmp")
            self._check_divisor_nonzero(right)
            if signed:
                self._check_div_no_overflow(left, right)
            return self.builder.sdiv(left, right, name="divtmp")
        elif op == '%':
            self._check_divisor_nonzero(right)
            if signed:
                self._check_div_no_overflow(left, right)
            return self.builder.srem(left, right, name="modtmp")
        elif op in ('&', '|', '^'):
            # Bitwise compound assignment (design 50): `x &= y` is `x = x & y`.
            return self._emit_bitwise(op, left, right)
        elif op in ('<<', '>>'):
            # `x <<= y` / `x >>= y` reuse the range-checked shift lowering; the
            # target's signedness picks arithmetic vs logical `>>`.
            return self._emit_shift(op, left, right, signed)
        else:
            raise ValueError(f"Unknown compound operator: {op}")

    def _generate_return_statement(self, stmt: ReturnStatement):
        """Generate code for a return statement."""
        # Generate return value first (before cleanup, in case it uses local vars)
        if stmt.value is not None:
            value = self._gen_transfer_value(stmt.value)
        else:
            value = None

        # Drain statement-scoped temporaries produced while evaluating the return
        # expression -- e.g. the `makeR()` receiver in `return makeR().value()`
        # (brief 23 item 3). The end-of-statement drain in `_generate_statement`
        # is skipped once `return` terminates the block, so it must run HERE,
        # before the terminator, in LIFO order. The returned value is exempt: it
        # is never registered as a statement temp (only unbound owned receivers
        # and discarded results are), so it is not released here -- we never free
        # what we return.
        if self.statement_temps:
            for slot, saw_type in reversed(self.statement_temps):
                self._emit_drop_at(slot, saw_type)
            self.statement_temps = []

        # Cleanup all scopes before returning
        self._cleanup_all_scopes()

        # Now return
        if value is not None:
            ret_type = self.builder.function.function_type.return_type
            if isinstance(ret_type, ir.VoidType):
                # design 132 unit C's instantiation-uniformity rule: a generic
                # `-> R` body writes `return <expr>` and must compile at EVERY
                # instantiation, `R = Void` included. A Void value is zero-sized
                # and this instantiation's LLVM signature returns void, so the
                # expression is evaluated for its effect and nothing is handed
                # back — `ret void %val` is not an instruction.
                self.builder.ret_void()
                return
            value = self._coerce_ret_value(value)
            self.builder.ret(value)
        else:
            # A valueless `return` in a Saw void function. main() is the one such
            # function whose LLVM signature is NOT void: it lowers to i32 for the
            # process exit code. Emitting `ret void` there crashes verification,
            # so match the LLVM return type -- `ret i32 0` for main, mirroring the
            # implicit-fallthrough behavior; `ret void` for every other case.
            ret_type = self.builder.function.function_type.return_type
            if isinstance(ret_type, ir.VoidType):
                self.builder.ret_void()
            else:
                self.builder.ret(ir.Constant(ret_type, 0))
