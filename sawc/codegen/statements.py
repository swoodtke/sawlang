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
    WhileExpr, ForLoop, Identifier, MemberAccess, ArrayLiteral, ArrayIndex,
    SelfExpr, TupleIndex, MoveExpr, NoneLiteral, SawType, TypeKind,
    WildcardPattern, BindingPattern, TuplePattern,
    requested_align,
)
from ast_walk import pattern_binding_names


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

        Each full statement gets its own statement-scoped temporary list:
        owned Deinit-needing values produced mid-statement that no binding
        takes ownership of (a method-call receiver, a discarded call result) are
        registered here and released LIFO once the statement finishes. Loops
        manage their own per-iteration scopes, so they keep the outer context.
        """
        # Point the DWARF line table at this statement's source line before
        # lowering it (a line-0 synthesized node inherits the prior line).
        self._di_set_line(stmt.line, stmt.column)

        # The breadcrumb: the statement half of the pair sawc.py's catch-all
        # reads to anchor an internal compiler error. See
        # `CodeGenerator._generate_expression` and `sawc._ice_location`.
        old_node = getattr(self, '_current_node', None)
        self._current_node = stmt

        # Handle dual-purpose nodes (Expressions used as Statements)
        if isinstance(stmt, WhileExpr):
            self._generate_while_expr(stmt)
            self._current_node = old_node
            return
        if isinstance(stmt, ForLoop):
            self._generate_for_loop(stmt)
            self._current_node = old_node
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
        # Restored only on the success path, deliberately: an exception on the
        # way through leaves the innermost node that was being lowered stamped,
        # which is the one the report wants to name.
        self._current_node = old_node

    # ===== Statement Visitor Methods =====

    def visit_StaticAssert(self, stmt):
        """A statement-position `static_assert`: evaluated at compile time,
        emits no code (a false result is a clean compile error)."""
        self._eval_static_assert(stmt)

    def visit_LetStatement(self, stmt: LetStatement):
        if stmt.name == "_":
            self._generate_discard_let(stmt)
            return
        self._generate_let_statement(stmt)

    def visit_DestructuringLet(self, stmt):
        """`let (a, b) = pair` / `var (x, y) = point` (design 63 T1d).

        Evaluate the source once and bind each component. Whether the source
        stays live — and therefore whether each owning component is retained via
        `_generate_copy` — is the shared transfer oracle's answer; a `move`
        source (or a fresh tuple) transfers without a retain, while a
        projection source (`let (a, b) = h.pair`) retains, since `h` still owns
        that storage."""
        value = self._generate_expression(stmt.value)
        is_copy_source = self._transfer_site_needs_copy(stmt.value)
        src_type = self._expr_type(stmt.value)
        self._destructure_bind(stmt.pattern, value, src_type,
                               stmt.mutable, is_copy_source)

    def _pattern_binding_names(self, pattern):
        """All binding names a pattern introduces (skips `_`); see
        `ast_walk.pattern_binding_names`, the one definition of this walk."""
        return pattern_binding_names(pattern)

    def _destructure_bind(self, pattern, value, saw_type, mutable, copy):
        """Bind an irrefutable tuple pattern's leaves (design 63 T1d).

        Two passes, because the leaves answer to two different orders. Named
        leaves are bound in declaration order, which makes the cleanup scope
        release them in reverse (design 128's rule for every structural
        teardown). A `_` leaf names no binding to register, so its component
        is dropped here instead, and discard order is reverse-declaration too.
        The walk collects the discards and this entry point flushes them in
        reverse, since a forward emission cannot spell a reverse order.
        """
        discards = []
        self._destructure_walk(pattern, value, saw_type, mutable, copy, discards)
        for comp, comp_type in reversed(discards):
            slot = self._entry_alloca(comp.type, name="discard")
            self.builder.store(comp, slot)
            self._emit_drop_at(slot, comp_type)

    def _destructure_walk(self, pattern, value, saw_type, mutable, copy, discards):
        """The recursive half of `_destructure_bind`: binds every NAMED leaf and
        appends every owning `_` leaf's `(value, SawType)` to `discards`, in
        declaration order, for the caller to drop in reverse."""
        if isinstance(pattern, WildcardPattern):
            # Per-position `_`: the component is dropped by the caller's flush,
            # so the discard consumes exactly once, but only when the source
            # handed its ownership over.
            #
            # `copy` is the same source-ownership answer the named arm below
            # reads: a copied source (a projection, whose container keeps
            # owning it) hands over nothing, so dropping the component would
            # release a reference the destructure never acquired. `if let _ =
            # opt` asks the same question through `_optional_source_hands_over`
            # (conditionals.py). A fresh or `move`d source drops exactly once.
            if (not copy) and saw_type is not None and self._needs_cleanup(saw_type):
                discards.append((value, saw_type))
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
                self._destructure_walk(sub, comp, elem_types[idx], mutable, copy,
                                       discards)

    def _generate_discard_let(self, stmt: LetStatement):
        """`let _ = expr` evaluates the RHS, takes ownership, and drops it at
        the end of this statement (like an unused temporary); no binding is
        created. A Copy lvalue is copied so the source is untouched and the
        copy is what gets released."""
        value = self._generate_expression(stmt.value)
        var_type = (self._resolve_type_alias(stmt.type_annotation)
                    if stmt.type_annotation else self._expr_type(stmt.value))
        # A discard has no destination slot (nothing is stored, so nothing
        # wraps), while the annotation may still be opt-encoded (`let _:
        # String? = s`). Reconcile it with the value in hand once, up front:
        # both the retain below and the drop registered after it are glue over
        # this same value, so both must be driven by the same type.
        var_type = self._transfer_type_for(value, var_type)
        # A discard is a transfer into a home that dies at the end of this
        # statement, so it takes the same copy decision as every other transfer
        # site: `_transfer_site_needs_copy`, the shared oracle. A projection
        # (`let _ = h.s`) must retain, or the drop below releases storage the
        # source still owns.
        if var_type and self._transfer_site_needs_copy(stmt.value):
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
        #
        # A statement-position `if` / `match` is control flow rather than a
        # value: the typechecker deliberately leaves it unannotated and
        # `need_result=False` means codegen built nothing either. The producer
        # taxonomy answers BRANCHES for those nodes like any other, so the
        # value question is asked first; `_expr_type` fails loud on an
        # unannotated node, which is right everywhere it is a value.
        if (value is not None
                and getattr(stmt.expression, 'resolved_type', None) is not None
                and self._is_owned_temporary(stmt.expression)
                and not self.builder.block.is_terminated):
            self._register_stmt_temp(value, self._expr_type(stmt.expression))

    def _generate_memory_destination_rhs(self, value_expr, name):
        """Generate an RHS for a caller that has a memory destination.

        A memberwise struct literal is first built in a staging destination.
        Replacement assignments require that staging slot: every RHS read and
        side effect completes before the old destination is dropped, so
        `x = Pair(a: x.b, b: x.a)` cannot clobber its own inputs.  Let/var
        initialization uses the same path so frame construction never creates
        an SSA insert chain.  Real custom initializers and function-call
        reinterpretations remain ordinary value-producing calls.
        """
        if self._can_materialize_struct_init(value_expr):
            return self._materialize_struct_value(value_expr, name=name)
        return self._generate_expression(value_expr)

    def _generate_let_statement(self, stmt: LetStatement):
        """Generate code for a let binding."""
        # Exact memberwise struct lets have their final alloca before any field
        # is generated, so the literal lands directly in its binding (the frame
        # `__f` path).  Optional/result wrappers and real init calls fall through
        # to the value path below.
        if self._can_materialize_struct_init(stmt.value):
            direct_annotation = (
                self._resolve_type_alias(stmt.type_annotation)
                if stmt.type_annotation else None)
            direct_type = (
                self._canonicalize_type_kind(direct_annotation)
                if direct_annotation is not None
                else self._expr_type(stmt.value))
            direct_llvm = self._get_llvm_type(direct_type)
            alloca = self._entry_alloca(
                direct_llvm, name=stmt.name, align=requested_align(stmt))
            if self._materialize_wrapped_struct_init(
                    stmt.value, alloca):
                if self.builder.block.is_terminated:
                    return
                # A derived same-scope redefinition still evaluates the whole
                # RHS against the old binding before retiring it.
                self._drop_redefined_same_scope(
                    getattr(stmt, 'coro_redefines', None) or stmt.name)
                self.variables[stmt.name] = alloca
                self.void_variables.discard(stmt.name)
                self.variable_types[stmt.name] = direct_type
                if self.cleanup_stack and self._needs_cleanup(direct_type):
                    self._register_cleanup(stmt.name, direct_type)
                return
        value = self._generate_memory_destination_rhs(
            stmt.value, name=f"{stmt.name}.init")

        # The initializer diverged (`let x = panic("...")`, `let x = while { }`):
        # it produced no value and terminated the block with `unreachable`.
        # There is nothing to bind and nowhere to bind it; appending the store
        # would put instructions after a terminator, which is invalid IR.
        if value is None and self.builder.block.is_terminated:
            return

        # Resolve type alias in annotation
        resolved_annotation = self._resolve_type_alias(stmt.type_annotation) if stmt.type_annotation else None

        # Determine the variable type early for copy behavior. A written
        # annotation may omit trailing default type args (`Map<Int, R>`) or tag an
        # enum as STRUCT; canonicalize so the binding's kind/identity match the
        # monomorphized type; otherwise its deinit/cleanup lookup misses and the
        # element/buffer leaks at scope end.
        if resolved_annotation is not None:
            var_type = self._canonicalize_type_kind(resolved_annotation)
        else:
            var_type = self._expr_type(stmt.value)

        # A `let` initializer is a transfer into a new home, so it takes the same
        # copy decision as every other transfer site: `_transfer_needs_copy`, the
        # oracle that reads the typechecker's `needs_copy` mark and re-derives the
        # projection rules codegen owns. A projection (`let c = h.s`) retains,
        # since the source still owns that storage; a `move` initializer
        # transfers ownership and copies nothing.
        if var_type and self._transfer_site_needs_copy(stmt.value):
            value = self._generate_copy(value, var_type)

        # Handle None literal type conversion if assigning to optional with different inner type
        if resolved_annotation and resolved_annotation.kind == TypeKind.OPTIONAL:
            is_already_optional = (isinstance(value.type, ir.LiteralStructType) and
                                   len(value.type.elements) == 2 and
                                   isinstance(value.type.elements[0], ir.IntType) and
                                   value.type.elements[0].width == 1)

            # A `None` literal generated at the i64 placeholder payload, retagged
            # into the slot's own optional type. There is no payload to carry
            # (`None` is the flag and an undef), so rebuilding from the flag
            # alone is right here and nowhere else. The test asks the AST, not
            # the shape: a genuine `Int?` value bound for an `Int??` slot has
            # the same shape as the placeholder, and rebuilding it would drop
            # its payload.
            if is_already_optional and isinstance(stmt.value, NoneLiteral):
                current_inner_type = value.type.elements[1]
                target_inner_type = self._get_llvm_type(resolved_annotation.inner_type)

                needs_conversion = (isinstance(current_inner_type, ir.IntType) and
                                    current_inner_type.width == 64 and
                                    not (isinstance(target_inner_type, ir.IntType) and
                                         target_inner_type.width == 64))

                if needs_conversion:
                    correct_optional_type = ir.LiteralStructType([ir.IntType(1), target_inner_type])

                    # Extract is_some flag (should be false for None)
                    is_some = self.builder.extract_value(value, 0, name="is_some")

                    # Create new optional with correct type
                    new_optional = ir.Constant(correct_optional_type, ir.Undefined)
                    new_optional = self.builder.insert_value(new_optional, is_some, 0)
                    # Don't set the value - it's undef for None anyway

                    value = new_optional

            # Then fit it. The typechecker inserts one `OptionalWrap` however
            # deep the slot is, so a value two layers below its annotation
            # arrives one layer short; the fit wraps as many layers as the
            # annotation asks for, so the alloca takes the slot's type.
            value = self._fit_optional_slot(
                value, self._get_llvm_type(resolved_annotation))

        # Narrow a fixed-width integer local to its annotated storage width. A
        # bare-literal RHS (`let a: Int32 = 5`) is generated at platform width
        # (i64); without this the binding allocas i64, so a later `-a` /
        # overflow check runs at the wrong width and a wire-format struct store
        # reads too many bytes. The typechecker already range-checked the
        # literal against the annotation, so the truncation is
        # value-preserving. Suffixed/cast RHS values already carry the right
        # width (no-op here). Only integer annotations are coerced.
        #
        # A widen goes through `_widen_int_value`, by the source's signedness,
        # so `let wide: Int = someUInt32` zero-extends (design 195).
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
                else:
                    value = self._widen_int_value(
                        value, target_llvm,
                        getattr(stmt.value, 'resolved_type', None))

        # A derived same-scope redefinition replaces the old binding (design
        # 107). The initializer above already consumed (`move`) or copied the
        # old value; drop the old binding now if it still owns one (a `.copy()`
        # derivation), retiring its scope-exit cleanup so it never double-frees.
        #
        # `coro_redefines` is the coroutine transform's answer for a body it
        # alpha-renamed: every binding there has a name unique within the body,
        # so the two halves of a redefinition do not share one, and this match
        # is by name.
        self._drop_redefined_same_scope(
            getattr(stmt, 'coro_redefines', None) or stmt.name)

        # A local at `Void` has no storage to name. The typechecker rejects a
        # concrete `let n = <Void expr>`, but a local typed by the method's own
        # type parameter is checked abstractly and only becomes Void at an
        # instantiation (the natural body of `Mutex.lock<R>`, where a critical
        # section that computes nothing is the common case). `alloca(void)` is
        # invalid, and there is nothing to store and nothing to clean up, so
        # record the name as void-valued and read it back as Void (design 132).
        if isinstance(value.type, ir.VoidType):
            # A Void binding has no storage, so an alignment request on it
            # could only be dropped. Refuse instead of dropping.
            if requested_align(stmt) is not None:
                from .core import CodegenUserError
                raise CodegenUserError(
                    f"`@align` cannot be written on `{stmt.name}`: it binds a "
                    f"`Void` value, which occupies no storage",
                    getattr(stmt, 'line', 0), getattr(stmt, 'column', 0),
                    hint="only a binding with storage can state an alignment")
            self.void_variables.add(stmt.name)
            self.variables.pop(stmt.name, None)
            return

        # `@align(N)` on this local, already folded and validated by the
        # typechecker's align funnel. `_entry_alloca` takes the maximum of the
        # request and the type's own ABI alignment, so an `@align` can only
        # ever strengthen a slot, never weaken one.
        alloca = self._entry_alloca(value.type, name=stmt.name,
                                    align=requested_align(stmt))
        # `let b = a` on an aggregate is a copy, and one `llvm.memcpy` is what
        # it should be rather than a field walk (design 261).
        self._store_materialized_or_transfer(
            value, alloca, final_use=True)
        self.variables[stmt.name] = alloca
        self.void_variables.discard(stmt.name)

        # Track variable type for resource management
        if var_type:
            self.variable_types[stmt.name] = var_type
            # Track for cleanup if type implements Deinit/Copy/NoCopy.
            # A `let`/`var` binding can be `move`d, so register it with a drop flag
            # (design 42) for conditional-move correctness.
            if self.cleanup_stack and self._needs_cleanup(var_type):
                self._register_cleanup(stmt.name, var_type)

    def _transfer_site_needs_copy(self, value_expr) -> bool:
        """Whether a transfer into a binding or slot (a `let` initializer, an
        assignment RHS, a destructure, a discard, a struct-literal field, a
        collection `for` head) must retain the value it reads.

        The answer is the shared transfer oracle's, with one carve-out:
        indexing a raw pointer. `self.buffer[i]` inside `Vector`/`Map` is the
        unsafe domain's manual bookkeeping, not a read out of storage the
        compiler tracks ownership of; std takes a bare alias there and decides
        the retain at the subsequent use (`Vector.get` retains when it returns
        the element, while `Vector.swap_out` `move`s the alias out, which must
        stay at exactly one reference). Retaining at the read would over-retain
        every `swap_out` result.

        A fixed array (`[T; N]`) index is not this case: it is ordinary safe
        storage the source keeps owning, so it retains like a field.
        """
        if isinstance(value_expr, ArrayIndex):
            base = getattr(value_expr, 'array_expr', None)
            base_type = base.resolved_type if base is not None else None
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
        silent ``None`` here would disable cleanup registration and copy
        insertion and leak resources.
        """
        resolved = expr.resolved_type
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
        value = (None if isinstance(stmt.value, NoneLiteral)
                 else self._generate_memory_destination_rhs(
                     stmt.value, name="assign.init"))
        if value is None and self.builder.block.is_terminated:
            return

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
                var_type = stmt.target.resolved_type

            # Whole-referent replacement through a `&var` reference parameter
            # (design 110). The variable holds a pointer to the caller's value;
            # load it, deinit the old value at that address, then store the new
            # one: the through-ref counterpart of the plain-variable path below.
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

                # An assignment RHS is a transfer into a new home and takes the
                # same copy decision every other transfer site takes; a
                # projection (`a = h.r`) reads a value the source keeps owning.
                if self._frame_owning_read_copy(stmt.value):
                    # A frame-field read; see the field-assignment path below.
                    value = self._generate_copy(value, self._expr_type(stmt.value))
                elif isinstance(stmt.value, Identifier) or \
                        self._transfer_site_needs_copy(stmt.value):
                    value = self._generate_copy_for_dest(value, var_type)

            # The integer-width and optional-layer fits, then the store — the
            # same funnel every other assignment target kind ends at.
            self._store_assigned_value(value, target_ptr, stmt.value)
            # Re-arm the drop flag of a moved-from local. A static target has
            # no drop flag (statics are immortal).
            if not is_static_target:
                self._revive_assigned_binding(stmt.target.name, var_type)

        elif (isinstance(stmt.target, MemberAccess)
                and self._static_global(stmt.target) is not None):
            # `mod.NAME = v`: the module-qualified spelling of the static write
            # the Identifier arm above handles. Same storage (the static's
            # global), same rules: a static is immortal and admits only
            # trivially-destructible types, so there is no old value to deinit
            # and no drop flag to re-arm (design 149). Split out ahead of the
            # field arm below, which would resolve the target's object as a
            # value and find the qualifier names none.
            target_ptr = self._static_global(stmt.target)
            var_type = stmt.target.resolved_type
            if var_type is not None:
                if self._frame_owning_read_copy(stmt.value):
                    value = self._generate_copy(value,
                                                self._expr_type(stmt.value))
                elif isinstance(stmt.value, Identifier) or \
                        self._transfer_site_needs_copy(stmt.value):
                    value = self._generate_copy_for_dest(value, var_type)
            self._store_assigned_value(value, target_ptr, stmt.value)

        elif (isinstance(stmt.target, MemberAccess)
                and getattr(stmt.target, 'tuple_field_index', None) is not None):
            # Named-tuple element write `pair.x = fresh`: the label is a
            # position, so this is the tuple-slot store below under its other
            # spelling. Split out ahead of the field path because a tuple has no
            # `struct_types` entry to look its layout up in.
            idx = stmt.target.tuple_field_index
            self._store_into_tuple_slot(
                stmt, value, self._get_member_pointer(stmt.target),
                self._tuple_element_saw_type(stmt.target.object, idx))

        elif isinstance(stmt.target, TupleIndex):
            # Whole-element tuple write `t.0 = fresh`.
            self._store_into_tuple_slot(
                stmt, value, self._get_tuple_element_pointer(stmt.target),
                self._tuple_element_saw_type(stmt.target.tuple_expr,
                                             stmt.target.index))

        elif isinstance(stmt.target, MemberAccess):
            # Field assignment: obj.field = value
            # Resolve a pointer to the object's real storage (variable, self,
            # nested field, or array/pointer element). _get_lvalue_pointer
            # recurses and unwraps references, so an array-element base
            # (`a[i].field = x`) GEPs into the live array rather than a
            # throwaway copy.
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

            # Live-slot release: a struct field always holds a live value
            # (fields are fully initialized at construction and partial moves
            # are forbidden), so overwriting an owning field must run the old
            # value's drop glue before the store, exactly as the variable- and
            # array-element-assignment paths do; otherwise `self.slots = move
            # new_slots` leaks the old backing buffer. The drop goes through
            # the field's own concrete type, so a `Vector<..., A>` field frees
            # via its allocator `A`, not a default.
            field_saw = self._struct_field_saw_type(struct_name, stmt.target.member)
            if field_saw is not None and self._needs_cleanup(field_saw):
                self._emit_drop_at(field_ptr, field_saw)
            # Copy retain when the RHS is an existing binding (mirrors the
            # variable- and array-element-assignment paths); NoCopy/ExplicitCopy
            # already moved at the value-transfer checkpoint.
            if (field_saw is not None
                    and not self._frame_owning_read_copy(stmt.value)
                    and (isinstance(stmt.value, Identifier)
                         or self._transfer_site_needs_copy(stmt.value))):
                value = self._generate_copy_for_dest(value, field_saw)
            elif self._frame_owning_read_copy(stmt.value):
                # A coroutine frame reading one of its own owned locals
                # (`self.name!`) into another field (`__result` at a `return
                # loc`, a sub-frame's param slot) duplicates it: the source
                # field keeps its drop flag and is released at the task's eager
                # teardown. Copy against the value's type, not the field's (the
                # same rule `_generate_copy_for_dest` applies above) (design 124).
                value = self._generate_copy(value, self._expr_type(stmt.value))

            # Fit and store through the funnel: the integer width first (a
            # `w.b = 2` on a `UInt32` field is an i64 constant here), then the
            # optional layers. `_fit_optional_slot` compares against the
            # slot's payload, so a struct-typed inner also wraps, e.g. an
            # opt-encoded coroutine closure frame field `f: (()->Int)?` whose
            # value is the 3-word closure struct.
            self._store_assigned_value(value, field_ptr, stmt.value)

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
                    # Dynamic bounds check on `arr[i] = v`.
                    self._emit_array_bounds_check(index_val, container_val.type.count, stmt.target.index)
                    # Array: GEP with two indices [0, index]
                    zero = ir.Constant(ir.IntType(64), 0)
                    elem_ptr = self.builder.gep(container_ptr, [zero, index_val], name="elem_ptr")
                    # Live-slot release: a fixed-array element slot always holds
                    # a live value, so overwriting it must run the old value's
                    # drop glue before the store, exactly as the
                    # Identifier-target path releases its prior value. (The
                    # PointerType branch below is the placement primitive and
                    # deliberately does NOT release: it fills uninitialized slots.)
                    container_saw = self._expr_type(container_expr)
                    elem_saw = (container_saw.array_element_type
                                if container_saw is not None else None)
                    if elem_saw is not None and self._needs_cleanup(elem_saw):
                        self._emit_drop_at(elem_ptr, elem_saw)
                    # The incoming element is a transfer site: retain an
                    # Copy value copied from an existing binding (mirrors
                    # the Identifier-target path). NoCopy/ExplicitCopy already
                    # moved at the value-transfer checkpoint.
                    if elem_saw is not None and (
                            isinstance(stmt.value, Identifier)
                            or self._transfer_site_needs_copy(stmt.value)):
                        value = self._generate_copy_for_dest(value, elem_saw)
                elif isinstance(container_val.type, ir.PointerType):
                    # Pointer: GEP with single index.
                    #
                    # Placement-move primitive (see LANGUAGE_SPEC "Placement
                    # writes"): the store to `elem_ptr` below (`ptr[i] = value`)
                    # bitwise-moves `value` into the target slot. The source is
                    # consumed by the value-transfer checkpoint in the
                    # typechecker, but, unlike the Identifier target above, which
                    # calls _generate_deinit_call on the prior value first, this
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
                    # A fixed-array field or nested element (`self.data[i] = b`,
                    # `outer.rows[i] = v`). An array value is not a pointer to
                    # GEP through, so address the real storage, exactly as the
                    # Identifier branch does (the same bounds check, live-slot
                    # release and Copy retain), and the write lands in the field
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
                    # A non-identifier container (e.g. `self.field_ptr[i] = v`):
                    # evaluate it as a value; a pointer-typed one
                    # GEPs like the Identifier pointer branch (placement-move
                    # primitive, no release — the slot is caller-managed raw
                    # memory).
                    container_val = self._generate_expression(container_expr)
                    if isinstance(container_val.type, ir.PointerType):
                        elem_ptr = self.builder.gep(
                            container_val, [index_val], name="ptr_elem")
                    else:
                        raise ValueError(f"Unsupported container expression in assignment: {type(container_expr)}")

            # Fit and store through the funnel. The widen it does carries the
            # assigned expression's own type, so it extends by the source's
            # signedness (`slots[0] = u` for a `UInt32 u` zero-extends). The
            # optional wrap comes after, which is why the copy above is driven
            # by `_generate_copy_for_dest`: the value in hand is the payload.
            self._store_assigned_value(value, elem_ptr, stmt.value)

            # Placement-move bookkeeping: a pointer-target store (`ptr[i] =
            # value`, Vector.push/set's primitive) bitwise-moves the source
            # into the slot. If the source is an owned binding carrying a drop
            # flag, clear it: the value now lives in the buffer and must not
            # also drop at scope exit. Observing this move is what makes
            # registering owning by-value params of instance methods safe (they
            # release when used-and-not-moved, and do not double-free when
            # placement-moved) (design 65).
            if (isinstance(stmt.target.array_expr, Identifier)
                    and isinstance(container_val.type, ir.PointerType)
                    and isinstance(stmt.value, Identifier)):
                flag = self.drop_flags.get(stmt.value.name)
                if flag is not None:
                    self.builder.store(ir.Constant(ir.IntType(1), 0), flag)
                self.moved_variables.add(stmt.value.name)

        elif isinstance(stmt.target, SelfExpr):
            # `self = v` in a `&var self` method (design 110). `self` is bound
            # to the caller's storage pointer directly (methods.py registers the
            # mutable-self arg as the pointer itself), so it already is the
            # referent address: no reference load, unlike the Identifier path.
            self_ptr = self.variables.get("self")
            if self_ptr is None:
                raise ValueError("`self = v` outside a method")
            self._store_replacement_through_ptr(
                stmt, value, self_ptr, self.variable_types.get("self"))

        else:
            raise ValueError(f"Invalid assignment target: {type(stmt.target)}")

    def _store_assigned_value(self, value, slot_ptr, value_expr):
        """The store an assignment makes: fit the value to the slot, then store.

        Two fits, in this order, at every assignment target kind:
        - Integer width. A platform `Int` is assignable to and from any integer
          type (`_types_compatible`), and a bare literal is a platform `Int`
          until some slot tells it otherwise, so a well-typed program arrives
          here with an i64 value for an i32 slot (`v = 4`, or `v = k` for a
          plain `Int` k). Retype the constant, truncate, or widen by the
          source's signedness (design 195).
        - Optional layers. A bare `T` into a `T?` or `T??` slot wraps as many
          times as the slot asks.

        Entry points (a new store site is added by calling this):
          `_generate_assign_statement`'s Identifier arm -- a local, or an `unsafe static var`
          its module-qualified static arm -- `mod.NAME = v`
          its MemberAccess arm -- a struct field
          its ArrayIndex arm -- an array or pointer element
          `_store_into_tuple_slot` -- a tuple slot (`t.0`, `p.x`)
          `_store_replacement_through_ptr` -- a `&var` referent, or `self`
          `_generate_optional_chain_assign` (optionals.py) -- `x?.y = v`
        """
        if self._store_none_optional_tag(value_expr, slot_ptr):
            return
        if (value is not None
                and self._store_present_optional_value(value, slot_ptr)):
            return
        slot_type = slot_ptr.type.pointee
        if (isinstance(value.type, ir.IntType)
                and isinstance(slot_type, ir.IntType)
                and value.type.width != slot_type.width):
            value = self._coerce_int_llvm(
                value, slot_type, getattr(value_expr, 'resolved_type', None))
        value = self._fit_optional_slot(value, slot_type)
        # This is the assignment funnel for every target kind, so routing it
        # here puts every aggregate assignment on the memcpy without touching
        # any of the arms (design 261).
        self._store_materialized_or_transfer(
            value, slot_ptr, final_use=True)

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
        """Store a whole-element tuple write into its slot.

        Mirrors the struct-field path step for step, because a tuple element is
        the same kind of storage: the slot always holds a live value (a tuple is
        fully initialized at construction and partial moves are forbidden), so
        the overwritten element's drop glue runs before the store and it deinits
        exactly once; a Copy RHS that is an existing binding is
        retained; a coroutine frame reading one of its own owned locals
        duplicates against the value's type (design 124); a bare `T` into an
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
        self._store_assigned_value(value, elem_ptr, stmt.value)

    def _store_replacement_through_ptr(self, stmt, value, referent_ptr,
                                       referent_saw):
        """Replacement-assignment store (design 110): release the old referent
        value at `referent_ptr`, then install `value`. Mirrors the plain-variable
        and through-ref field-assignment paths (deinit old, Copy-retain a
        plain-binding RHS, optional-wrap, store); `referent_ptr` already points at
        the caller's real storage, so the write lands in the caller's slot."""
        # A generic `&var T` param records the abstract `T` referent in
        # variable_types (params are stored unsubstituted); substitute the active
        # monomorphization so the drop glue and copy tier are the concrete
        # instantiation's. An abstract `T` reads as non-owning and would leak the
        # replaced value (its deinit never runs).
        if referent_saw is not None:
            referent_saw = self._substitute_saw_type(
                referent_saw, self.type_param_context)
        if referent_saw is not None and self._needs_cleanup(referent_saw):
            self._emit_drop_at(referent_ptr, referent_saw)
        # A Copy RHS that is an existing binding is retained (mirrors the
        # variable/field/element paths); NoCopy/ExplicitCopy already moved at the
        # value-transfer checkpoint, and `move v`/temporaries are not Identifiers.
        if referent_saw is not None and (
                isinstance(stmt.value, Identifier)
                or self._transfer_site_needs_copy(stmt.value)):
            value = self._generate_copy_for_dest(value, referent_saw)
        self._store_assigned_value(value, referent_ptr, stmt.value)

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
            # Field compound assignment: obj.field += value, through the lvalue
            # funnel rather than straight to `_get_member_pointer`, so a
            # module-qualified static (`mod.N += v`) gets the same address every
            # other write shape gets.
            field_ptr = self._get_lvalue_pointer(stmt.target)
            current_val = self.builder.load(field_ptr, name="field_val")
            rhs = self._generate_expression(stmt.value)
            new_val = self._apply_compound_op(stmt.op, current_val, rhs, signed)
            self.builder.store(new_val, field_ptr)

        elif isinstance(stmt.target, TupleIndex):
            # Tuple element compound assignment `t.0 += value`: the element
            # slot, loaded and stored back through the same address.
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
                    # Dynamic bounds check on `arr[i] += v`.
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
                # A non-identifier container. The coroutine transform makes a
                # reference param a frame-resident pointer, so `n += 1` on a
                # `&var Int` param after a suspension arrives as `self.n[0]`: an
                # `ArrayIndex` over a `MemberAccess`. The two arms below mirror
                # the assignment path minus its ownership bookkeeping: a
                # compound-assign target is a number, so there is no old value
                # to drop and no incoming value to retain.
                container_saw = self._expr_type(container_expr)
                if (container_saw is not None
                        and container_saw.kind == TypeKind.ARRAY):
                    # A fixed-array field or nested element (`self.data[i] += 1`).
                    container_ptr = self._get_lvalue_pointer(container_expr)
                    pointee = container_ptr.type.pointee
                    if not isinstance(pointee, ir.ArrayType):
                        raise ValueError(
                            f"compound-assignment target is not array storage: "
                            f"{pointee}")
                    self._emit_array_bounds_check(
                        index_val, pointee.count, stmt.target.index)
                    zero = ir.Constant(ir.IntType(64), 0)
                    elem_ptr = self.builder.gep(
                        container_ptr, [zero, index_val], name="elem_ptr")
                else:
                    container_val = self._generate_expression(container_expr)
                    if isinstance(container_val.type, ir.PointerType):
                        elem_ptr = self.builder.gep(
                            container_val, [index_val], name="ptr_elem")
                    else:
                        raise ValueError(
                            f"Unsupported container expression in compound "
                            f"assignment: {type(container_expr)}")

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

        Unlike the binary-operator path these checks pass no explicit panic
        line: a compound assignment is the statement, so the line the statement
        walk already announced is the operator's own line.
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
            # The same signed/unsigned split as the binary operator: sdiv with
            # the INT_MIN / -1 check, or udiv for an unsigned target (SL-370).
            self._check_divisor_nonzero(right)
            if signed:
                self._check_div_no_overflow(left, right)
                return self.builder.sdiv(left, right, name="divtmp")
            return self.builder.udiv(left, right, name="udivtmp")
        elif op == '%':
            self._check_divisor_nonzero(right)
            if signed:
                self._check_div_no_overflow(left, right)
                return self.builder.srem(left, right, name="modtmp")
            return self.builder.urem(left, right, name="umodtmp")
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
            # `return <diverging>`: a `panic(...)` or a `-> Never` call as the
            # returned expression never produces a value, and emitting it
            # already terminated this block with `unreachable`. There is no
            # `ret` to write and no cleanup to run; control does not reach here.
            #
            # The question is the builder's, not the type's: an expression can
            # be typed `Never` and still fall through (a window result `__R`),
            # so "did the emission terminate this block" is the only sound
            # proxy once lowering has begun (design 228).
            if self.builder.block.is_terminated:
                return
        else:
            value = None

        # Drain statement-scoped temporaries produced while evaluating the return
        # expression -- e.g. the `makeR()` receiver in `return makeR().value()`.
        # The end-of-statement drain in `_generate_statement` is skipped once
        # `return` terminates the block, so it must run here,
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

        # A `return` inside `main` crosses to the C entry's `i32` through the
        # one funnel, exactly as the fall-through epilogue does: the value's
        # shape decides, not the position it left from.
        if self._is_c_entry(self.builder.function):
            self._emit_main_exit_return(value)
            return
        if value is not None:
            ret_type = self.builder.function.function_type.return_type
            if isinstance(ret_type, ir.VoidType):
                # Instantiation uniformity: a generic `-> R` body writes
                # `return <expr>` and must compile at every instantiation,
                # `R = Void` included (design 132). A Void value is zero-sized
                # and this instantiation's LLVM signature returns void, so the
                # expression is evaluated for its effect and nothing is handed
                # back — `ret void %val` is not an instruction.
                self.builder.ret_void()
                return
            value = self._coerce_ret_value(value, stmt.value)
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
