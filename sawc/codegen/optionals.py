"""
Optional type handling for the Saw code generator.

This module provides mixin methods for generating code that handles optional types,
including None literals, force unwrap (!), nil coalescing (??), and optional
chaining (?.).

Optional representation:
- Optionals are represented as { i1, T } where i1 indicates presence (is_some)
- None is { 0, undefined }
- Some(value) is { 1, value }

Usage:
    class CodeGenerator(OptionalsMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import (
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain, OptionalWrap,
    BindOptional, OptionalEvalExpr, OptionalChainAssign,
    MemberAccess, MethodCall, Identifier, ArrayIndex, SelfExpr, TupleIndex,
    SawType, TypeKind,
)


class OptionalsMixin:
    """Mixin providing optional type handling methods for CodeGenerator.

    Methods:
        _wrap_in_optional: Wrap a value in an optional (Some)
        _is_optional_type: Check if an LLVM type is an optional
        _generate_none_literal: Generate code for None
        _generate_force_unwrap: Generate code for expr!
        _generate_nil_coalesce: Generate code for expr ?? default
        _generate_optional_chain: Generate code for expr?.member
    """

    def _wrap_in_optional(self, value):
        """Wrap a value in an optional type (for implicit wrapping)."""
        if isinstance(value.type, ir.VoidType):
            # `Void?` carries an `i8` PLACEHOLDER payload — LLVM has no
            # void-in-struct — and only the is_some flag is ever read (design
            # 111). There is no payload to insert, so set the flag and stop.
            # Reached when a `Void`-instantiated generic local becomes an
            # opt-encoded coroutine frame field (design 132 unit C).
            optional_type = ir.LiteralStructType([ir.IntType(1), ir.IntType(8)])
            optional_val = ir.Constant(optional_type, ir.Undefined)
            return self.builder.insert_value(
                optional_val, ir.Constant(ir.IntType(1), 1), 0)
        optional_type = ir.LiteralStructType([ir.IntType(1), value.type])
        optional_val = ir.Constant(optional_type, ir.Undefined)

        # Set is_some to true
        true_val = ir.Constant(ir.IntType(1), 1)
        optional_val = self.builder.insert_value(optional_val, true_val, 0)

        # Set the value
        optional_val = self.builder.insert_value(optional_val, value, 1)

        return optional_val

    def visit_OptionalWrap(self, expr: OptionalWrap):
        """Generate code for OptionalWrap (T -> T?).

        This is inserted by the typechecker when a value of type T
        is used where T? is expected.

        Design 40 item 5 (L10): the value escapes into the Some payload — a
        transfer site. Generate it through _gen_transfer_value so an owned
        ImplicitCopy value auto-wrapped into `Some(...)` is retained, closing
        the same premature-free hole the Result Ok/Err auto-wrap had.
        """
        value = self._gen_transfer_value(expr.value)
        return self._wrap_in_optional(value)

    def _is_optional_type(self, llvm_type) -> bool:
        """Check if an LLVM type is an optional (struct with i1 flag and value)."""
        return (isinstance(llvm_type, ir.LiteralStructType) and
                len(llvm_type.elements) == 2 and
                llvm_type.elements[0] == ir.IntType(1))

    def _fit_optional_slot(self, value, slot_type):
        """`value`, wrapped as many times as `slot_type` is asking for.

        Every store into an optional slot used to ask "is the slot an optional
        and the value not one" — a SHAPE test, which cannot tell an already-fit
        value from one that needs another layer. At a NESTED optional both
        answers are "optional" and the wrap was skipped, so an `Int?` was stored
        into an `Int??` slot (DF-174b: `group.spawn(work())` where
        `work() -> Int?`, whose result cell is `T?` at `T = Int?`).

        Comparing the value against the slot's PAYLOAD type answers both cases
        exactly, and the shape test is kept as the fallback so a value that
        merely needs a later coercion (a narrower integer, say) still wraps
        where it always did.

        DF-174g: the payload comparison answers "one more layer", and a slot can
        ask for two. Naming the type (`let a: Optional<Int?> = 5`) puts a bare
        value TWO layers below its slot, where the containers — the only source
        of a nested optional before — always put it one (their payload is
        already a layer down). So the fit recurses into the slot's payload
        first: whatever number of layers separates the two, each one is a real
        `Some`, and the peel that reads them back finds a value at every depth
        instead of `undef` under a present tag.
        """
        if value is None or not self._is_optional_type(slot_type):
            return value
        if value.type == slot_type:
            return value
        payload = slot_type.elements[1]
        if value.type == payload:
            return self._wrap_in_optional(value)
        if self._is_optional_type(payload):
            inner = self._fit_optional_slot(value, payload)
            if inner.type == payload:
                return self._wrap_in_optional(inner)
        if not self._is_optional_type(value.type):
            return self._wrap_in_optional(value)
        return value

    def _generate_none_literal(self, expr: NoneLiteral):
        """Generate code for None literal.

        Creates an optional with is_some = false. The inner type is determined
        from the typechecker's resolved_type annotation or the current function's
        return type.
        """
        # Create an optional with is_some = false. The inner type comes from the
        # typechecker annotation via the single accessor (which substitutes
        # generic bindings). A bare `None` whose optional inner type was never
        # pinned contextually falls back to the current function's return type.
        none_type = self._expr_type(expr)  # OPTIONAL, inner_type may be None
        inner_type = none_type.inner_type

        if inner_type is None:
            # The expectation the checker pushed down from the surrounding slot
            # (DF-146l). `_apply_literal_expected_type` stamps it on the literal
            # before checking it, exactly as it stamps a fixed width on a bare
            # integer, so a `None` in a Map/Vector/Set/tuple ELEMENT position —
            # every slot reached only through that recursion — carries its
            # payload type here. The checker keeps returning the untyped form so
            # the literal still unifies with any `T?`.
            expected = expr.expected_type
            if expected is not None and expected.is_optional():
                inner_type = expected.inner_type
                if inner_type and self.type_param_context:
                    inner_type = inner_type.substitute(self.type_param_context)

        if inner_type is None and self.current_return_type and self.current_return_type.is_optional():
            inner_type = self.current_return_type.inner_type
            if inner_type and self.type_param_context:
                inner_type = inner_type.substitute(self.type_param_context)

        if inner_type is None:
            # DF-146l's hardening rule: a `None` that reached here with no
            # payload type is a program no slot pinned, not a compiler-invariant
            # violation. Report it where the author wrote it.
            from .core import CodegenUserError
            raise CodegenUserError(
                "cannot tell what this `None` is a `None` OF — no annotation, "
                "parameter, field, return type or element type in scope fixes "
                "its payload type",
                expr.line, expr.column or 1,
                hint="annotate the slot it flows into (`let absent: Int? = "
                     "None`), or give the call an explicit type argument",
                source_file=self._di_current_basename())

        # Lower the OPTIONAL, not the payload: `Void?` has no void-in-struct
        # representation and carries an `i8` placeholder instead, and that rule
        # lives in `_get_llvm_type`'s OPTIONAL branch. Assembling `{i1, payload}`
        # here bypassed it and produced a `{i1, void}` that no `Void?` slot would
        # accept — which is what a `Void`-instantiated generic local hit when the
        # coroutine transform gave it a frame field (design 132 unit C).
        optional_type = self._get_llvm_type(
            SawType(TypeKind.OPTIONAL, inner_type=inner_type))
        optional_val = ir.Constant(optional_type, ir.Undefined)

        # Set is_some to false
        false_val = ir.Constant(ir.IntType(1), 0)
        optional_val = self.builder.insert_value(optional_val, false_val, 0)

        return optional_val

    def _generate_force_unwrap(self, expr: ForceUnwrap):
        """Generate code for force unwrap (expr!).

        Extracts the value from an optional, panicking at runtime if the
        optional is None.

        design 131: when the typechecker marked this unwrap `payload_needs_copy`
        it is a VALUE READ out of a place the source keeps (`let a = o!`,
        `f(o!)`, `return o!`), so the extracted payload is retained here — at the
        extraction — and the new owner's later drop is balanced. Borrow uses
        (`o!.m()`, `&o!`, `o!.field`) are never marked, so they still read in
        place with no traffic.
        """
        optional_val = self._generate_expression(expr.expr)

        # Extract the is_some flag
        is_some = self.builder.extract_value(optional_val, 0, name="is_some")

        # Runtime check: panic if None
        func = self.builder.function
        unwrap_ok_bb = func.append_basic_block(name="unwrap.ok")
        unwrap_panic_bb = func.append_basic_block(name="unwrap.panic")

        self.builder.cbranch(is_some, unwrap_ok_bb, unwrap_panic_bb)

        # Panic block: emit the panic via the saw_panic seam.
        self.builder.position_at_end(unwrap_panic_bb)
        self._emit_panic("force unwrap of None", line=expr.line)

        # OK block: extract and return the value
        self.builder.position_at_end(unwrap_ok_bb)
        payload = self.builder.extract_value(optional_val, 1, name="unwrapped")
        return self._retain_read_payload(expr, payload)

    def _retain_read_payload(self, node, payload):
        """design 131: honor a `payload_needs_copy` mark on a payload-extraction
        node by retaining the extracted value against the payload's own type."""
        if not node.payload_needs_copy:
            return payload
        payload_type = self._payload_saw_type(node)
        if payload_type is None:
            return payload
        return self._generate_copy(payload, payload_type)

    def _payload_saw_type(self, node) -> SawType:
        """The Saw type of the payload a design-131 extraction node yields."""
        src = getattr(node, 'optional_expr', None) or getattr(node, 'expr', None)
        if src is None:
            return None
        opt_type = self._expr_type(src)
        if opt_type is None or opt_type.kind != TypeKind.OPTIONAL:
            return None
        inner = opt_type.inner_type
        if inner is not None and self.type_param_context:
            inner = inner.substitute(self.type_param_context)
        return inner

    def _generate_nil_coalesce(self, expr: NilCoalesce):
        """Generate code for nil coalescing (expr ?? default).

        Returns the unwrapped value if present, otherwise evaluates and
        returns the default expression.

        design 131: `a ?? b` yields an OWNED value, so each arm hands over its
        own reference. The Some arm retains the payload it read out of `a` (when
        the typechecker's place rule says so); the None arm goes through the
        ordinary transfer path, which retains a named/field default. Retaining
        per-ARM rather than on the merged result is what keeps a fresh default
        (`opt ?? "fallback"`) from being over-retained.
        """
        optional_val = self._generate_expression(expr.expr)

        # Extract the is_some flag
        is_some = self.builder.extract_value(optional_val, 0, name="is_some")

        # Create blocks for the conditional
        func = self.builder.function
        some_bb = func.append_basic_block(name="some")
        none_bb = func.append_basic_block(name="none")
        merge_bb = func.append_basic_block(name="coalesce_merge")

        self.builder.cbranch(is_some, some_bb, none_bb)

        # Some branch - extract the value
        self.builder.position_at_start(some_bb)
        some_val = self.builder.extract_value(optional_val, 1, name="some_value")
        some_val = self._retain_read_payload(expr, some_val)
        # design 195 rule 2: the payload's half of the merge. The DEFAULT was
        # widened in the typechecker, which could wrap the expression it had; the
        # payload is an `extractvalue` with no AST node to wrap, so it is extended
        # here — by the PAYLOAD's own signedness, which is what preserves the
        # value. Emitted in the some-block, before the branch, so it dominates the
        # phi.
        merged = getattr(expr, 'resolved_type', None)
        if merged is not None and isinstance(some_val.type, ir.IntType):
            merged_llvm = self._get_llvm_type(merged)
            if (isinstance(merged_llvm, ir.IntType)
                    and merged_llvm.width > some_val.type.width):
                opt_saw = getattr(expr.expr, 'resolved_type', None)
                payload = opt_saw.inner_type if opt_saw is not None else None
                some_val = self._widen_int_value(some_val, merged_llvm, payload)
        self.builder.branch(merge_bb)
        some_bb = self.builder.block

        # None branch - evaluate default
        self.builder.position_at_start(none_bb)
        none_val = self._gen_transfer_value(expr.default)
        self.builder.branch(merge_bb)
        none_bb = self.builder.block

        # Merge
        self.builder.position_at_start(merge_bb)
        phi = self.builder.phi(some_val.type, name="coalesced")
        phi.add_incoming(some_val, some_bb)
        phi.add_incoming(none_val, none_bb)

        return phi

    def _generate_optional_chain(self, expr: OptionalChain):
        """Generate code for optional chaining (expr?.member).

        If the optional contains a value, accesses the member and wraps the
        result in a new optional. If None, propagates None.
        """
        optional_val = self._generate_expression(expr.expr)

        # Extract the is_some flag
        is_some = self.builder.extract_value(optional_val, 0, name="is_some")

        # Create blocks
        func = self.builder.function
        some_bb = func.append_basic_block(name="chain_some")
        none_bb = func.append_basic_block(name="chain_none")
        merge_bb = func.append_basic_block(name="chain_merge")

        self.builder.cbranch(is_some, some_bb, none_bb)

        # Some branch - unwrap and access member
        self.builder.position_at_start(some_bb)
        unwrapped = self.builder.extract_value(optional_val, 1, name="unwrapped")

        # Access the member (assuming struct)
        # Find the struct type and field index
        unwrapped_type = unwrapped.type
        struct_name = None
        if hasattr(unwrapped_type, 'name') and unwrapped_type.name in self.struct_types:
            struct_name = unwrapped_type.name
        else:
            for name, (llvm_type, _) in self.struct_types.items():
                if str(unwrapped_type) == str(llvm_type):
                    struct_name = name
                    break

        member_val = None
        if struct_name:
            _, field_order = self.struct_types[struct_name]
            if expr.member in field_order:
                field_index = field_order.index(expr.member)
                member_val = self.builder.extract_value(unwrapped, field_index)

        if member_val is None:
            raise ValueError(f"Cannot find field {expr.member} for type {unwrapped_type}")

        # Wrap the result in an optional
        result_optional_type = ir.LiteralStructType([ir.IntType(1), member_val.type])
        some_result = ir.Constant(result_optional_type, ir.Undefined)
        some_result = self.builder.insert_value(some_result, ir.Constant(ir.IntType(1), 1), 0)
        some_result = self.builder.insert_value(some_result, member_val, 1)

        self.builder.branch(merge_bb)
        some_bb = self.builder.block

        # None branch - return None
        self.builder.position_at_start(none_bb)
        none_result = ir.Constant(result_optional_type, ir.Undefined)
        none_result = self.builder.insert_value(none_result, ir.Constant(ir.IntType(1), 0), 0)
        self.builder.branch(merge_bb)
        none_bb = self.builder.block

        # Merge
        self.builder.position_at_start(merge_bb)
        phi = self.builder.phi(result_optional_type, name="chained")
        phi.add_incoming(some_result, some_bb)
        phi.add_incoming(none_result, none_bb)

        return phi

    # ==================================================================== #
    # Design 111 — full optional chaining.
    #
    # An OptionalEvalExpr wraps the maximal postfix run; each `?.` hop is a
    # BindOptional marking an unwrap-or-short-circuit. Codegen flattens the spine
    # into a segment list and lowers it as a linear address-based walk: every
    # optional hop tests `is_some` in place and, on None, jumps to a shared
    # none-block (skipping the REST of the chain, including method arguments).
    # Intermediate payloads are borrowed IN PLACE (a pointer into the optional's
    # payload) — never copied, never consumed. Owned mid-chain temporaries (an
    # rvalue head, a non-final method result) are spilled to slots and dropped
    # EXACTLY ONCE on every path: each short-circuit block drops the temps created
    # before it; the some-completion drops them all.
    # ==================================================================== #
    _I32_0 = None  # (documented) — helpers below build i32 constants inline.

    def _flatten_optional_chain(self, spine):
        """Walk an OptionalEvalExpr spine outer->inner into (head, segments).

        Each segment is `(kind, node, is_optional)` with kind in {'field',
        'method'} and `is_optional` True when the segment is reached through a
        `?.` hop (its receiver is a BindOptional). `segments` is ordered
        inner->outer (head first)."""
        segments = []
        node = spine
        while True:
            if isinstance(node, MemberAccess):
                obj = node.object
                is_opt = isinstance(obj, BindOptional)
                base = obj.expr if is_opt else obj
                segments.append(('field', node, is_opt))
                node = base
            elif isinstance(node, MethodCall):
                obj = node.object
                is_opt = isinstance(obj, BindOptional)
                base = obj.expr if is_opt else obj
                segments.append(('method', node, is_opt))
                node = base
            else:
                head = node
                break
        segments.reverse()
        return head, segments

    def _is_chain_lvalue(self, head) -> bool:
        """A chain head that already denotes real storage — borrowed in place, not
        spilled/consumed. Everything else (a call/constructor result) is an owned
        rvalue the chain spills and drops. A tuple projection is storage on the
        same terms a struct field is (DF-151j)."""
        return isinstance(
            head, (Identifier, MemberAccess, ArrayIndex, SelfExpr, TupleIndex))

    def _chain_head_pointer(self, head):
        """Return `(ptr, temps)` for a chain head. An lvalue is addressed in place
        (no drop); an owned rvalue is spilled to a slot the chain drops."""
        temps = []
        if self._is_chain_lvalue(head):
            ptr = self._get_lvalue_pointer(head)
        else:
            val = self._generate_expression(head)
            slot = self._entry_alloca(val.type, name="chain_head")
            self.builder.store(val, slot)
            ptr = slot
            head_saw = self._expr_type(head)
            if head_saw is not None:
                head_saw = self._substitute_saw_type(head_saw, self.type_param_context)
                if self._needs_cleanup(head_saw):
                    temps.append((slot, head_saw))
        return ptr, temps

    def _chain_field_gep(self, base_ptr, member):
        """GEP the field `member` from a pointer to a struct value. Returns
        `(field_ptr, field_saw, struct_name)`."""
        pointee = base_ptr.type.pointee
        struct_name = None
        if hasattr(pointee, 'name') and pointee.name in self.struct_types:
            struct_name = pointee.name
        else:
            for name, (lt, _) in self.struct_types.items():
                if str(pointee) == str(lt):
                    struct_name = name
                    break
        if struct_name is None:
            raise ValueError(f"optional chain: cannot resolve struct for field `{member}`")
        _, field_order = self.struct_types[struct_name]
        idx = field_order.index(member)
        field_ptr = self.builder.gep(
            base_ptr,
            [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), idx)],
            name=f"chain_{member}")
        field_saw = self._struct_field_saw_type(struct_name, member)
        return field_ptr, field_saw, struct_name

    def _drop_chain_temps(self, temps):
        """Deinit the chain's owned temporaries LIFO (in the CURRENT block)."""
        for slot, saw in reversed(temps):
            self._emit_drop_at(slot, saw)

    def _chain_optional_gate(self, cur_ptr, none_bb, chain_temps):
        """Emit the in-place `is_some` test for a `?.` hop. On None, drop the
        temps created so far and jump to `none_bb`. Returns the payload pointer on
        the continue path (builder left positioned there)."""
        func = self.builder.function
        is_some_ptr = self.builder.gep(
            cur_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
            name="chain_flag_ptr")
        is_some = self.builder.load(is_some_ptr, name="chain_is_some")
        cont_bb = func.append_basic_block(name="chain_cont")
        sc_bb = func.append_basic_block(name="chain_sc")
        self.builder.cbranch(is_some, cont_bb, sc_bb)
        self.builder.position_at_start(sc_bb)
        self._drop_chain_temps(chain_temps)
        self.builder.branch(none_bb)
        self.builder.position_at_start(cont_bb)
        return self.builder.gep(
            cur_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)],
            name="chain_payload")

    def visit_BindOptional(self, expr: BindOptional):
        # BindOptional never lowers on its own — the OptionalEvalExpr routine
        # consumes the spine directly. Reaching here is a compiler bug.
        raise ValueError("BindOptional lowered outside an optional chain")

    def visit_OptionalEvalExpr(self, expr: OptionalEvalExpr):
        return self._generate_optional_eval(expr)

    def visit_OptionalChainAssign(self, expr: OptionalChainAssign):
        return self._generate_optional_chain_assign(expr)

    def _generate_optional_eval(self, expr: OptionalEvalExpr):
        """Lower a read chain `a?.b?.c()` to short-circuit control flow."""
        head, segments = self._flatten_optional_chain(expr.expr)
        result_saw = self._expr_type(expr)
        result_llvm = self._get_llvm_type(result_saw)

        cur_ptr, chain_temps = self._chain_head_pointer(head)
        func = self.builder.function
        none_bb = func.append_basic_block(name="chain_none")
        merge_bb = func.append_basic_block(name="chain_merge")

        final_val = None
        n = len(segments)
        for idx, (kind, node, is_opt) in enumerate(segments):
            last = (idx == n - 1)
            if is_opt:
                base_ptr = self._chain_optional_gate(cur_ptr, none_bb, chain_temps)
            else:
                base_ptr = cur_ptr
            if kind == 'field':
                field_ptr, field_saw, _ = self._chain_field_gep(base_ptr, node.member)
                if last:
                    final_val = self.builder.load(field_ptr, name="chain_leaf")
                    if field_saw is not None:
                        final_val = self._generate_copy(final_val, field_saw)
                else:
                    cur_ptr = field_ptr
            else:  # method
                result = self._generate_method_call(node, receiver_ptr=base_ptr)
                if last:
                    final_val = result
                else:
                    slot = self._entry_alloca(result.type, name="chain_mtmp")
                    self.builder.store(result, slot)
                    res_saw = self._expr_type(node)
                    if res_saw is not None:
                        res_saw = self._substitute_saw_type(res_saw, self.type_param_context)
                    cur_ptr = slot
                    if res_saw is not None and self._needs_cleanup(res_saw):
                        chain_temps.append((slot, res_saw))

        # Some-completion path: wrap (unless the final segment is already the
        # result Optional — flattening) and drop all owned temporaries.
        if final_val.type == result_llvm:
            some_val = final_val
        else:
            some_val = self._wrap_in_optional(final_val)
        self._drop_chain_temps(chain_temps)
        some_end_bb = self.builder.block
        self.builder.branch(merge_bb)

        # None path.
        self.builder.position_at_start(none_bb)
        none_val = ir.Constant(result_llvm, ir.Undefined)
        none_val = self.builder.insert_value(none_val, ir.Constant(ir.IntType(1), 0), 0)
        self.builder.branch(merge_bb)
        none_end_bb = self.builder.block

        self.builder.position_at_start(merge_bb)
        phi = self.builder.phi(result_llvm, name="chain_result")
        phi.add_incoming(some_val, some_end_bb)
        phi.add_incoming(none_val, none_end_bb)
        return phi

    def _generate_optional_chain_assign(self, expr: OptionalChainAssign):
        """Lower `x?.y = v` (design 111): write the RHS through the payload field
        in place iff every optional hop is non-None; skip the RHS entirely on
        short-circuit. Yields `Void?` — Some(unit) written, None skipped."""
        target = expr.target
        head, segments = self._flatten_optional_chain(target.expr)
        result_llvm = ir.LiteralStructType([ir.IntType(1), ir.IntType(8)])

        cur_ptr, chain_temps = self._chain_head_pointer(head)
        func = self.builder.function
        none_bb = func.append_basic_block(name="chainw_none")
        merge_bb = func.append_basic_block(name="chainw_merge")

        n = len(segments)
        for idx, (kind, node, is_opt) in enumerate(segments):
            last = (idx == n - 1)
            if is_opt:
                base_ptr = self._chain_optional_gate(cur_ptr, none_bb, chain_temps)
            else:
                base_ptr = cur_ptr
            if last:
                # The typechecker guarantees the final segment is a field.
                field_ptr, field_saw, _ = self._chain_field_gep(base_ptr, node.member)
                if field_saw is not None:
                    field_saw = self._substitute_saw_type(field_saw, self.type_param_context)
                # RHS is generated HERE, on the all-some path only.
                value = self._generate_expression(expr.value)
                if field_saw is not None and self._needs_cleanup(field_saw):
                    self._emit_drop_at(field_ptr, field_saw)
                if field_saw is not None and isinstance(expr.value, Identifier):
                    value = self._generate_copy_for_dest(value, field_saw)
                expected_field_type = field_ptr.type.pointee
                value = self._fit_optional_slot(value, expected_field_type)
                self.builder.store(value, field_ptr)
            elif kind == 'field':
                field_ptr, _, _ = self._chain_field_gep(base_ptr, node.member)
                cur_ptr = field_ptr
            else:  # method
                result = self._generate_method_call(node, receiver_ptr=base_ptr)
                slot = self._entry_alloca(result.type, name="chainw_mtmp")
                self.builder.store(result, slot)
                res_saw = self._expr_type(node)
                if res_saw is not None:
                    res_saw = self._substitute_saw_type(res_saw, self.type_param_context)
                cur_ptr = slot
                if res_saw is not None and self._needs_cleanup(res_saw):
                    chain_temps.append((slot, res_saw))

        # Some-completion: drop temps, produce Some(unit).
        self._drop_chain_temps(chain_temps)
        some_val = ir.Constant(result_llvm, ir.Undefined)
        some_val = self.builder.insert_value(some_val, ir.Constant(ir.IntType(1), 1), 0)
        some_val = self.builder.insert_value(some_val, ir.Constant(ir.IntType(8), 0), 1)
        some_end_bb = self.builder.block
        self.builder.branch(merge_bb)

        self.builder.position_at_start(none_bb)
        none_val = ir.Constant(result_llvm, ir.Undefined)
        none_val = self.builder.insert_value(none_val, ir.Constant(ir.IntType(1), 0), 0)
        self.builder.branch(merge_bb)
        none_end_bb = self.builder.block

        self.builder.position_at_start(merge_bb)
        phi = self.builder.phi(result_llvm, name="chainw_result")
        phi.add_incoming(some_val, some_end_bb)
        phi.add_incoming(none_val, none_end_bb)
        return phi
