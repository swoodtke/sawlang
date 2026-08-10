"""
Match expression generation for the Saw code generator.

This module provides mixin methods for generating LLVM IR code for match
expressions on enum types.

Usage:
    class CodeGenerator(MatchMixin, ...):
        pass
"""

from llvmlite import ir
from ast_nodes import (
    MatchExpr, Block, Identifier, TypeKind, SelfExpr,
    IntLiteral, BoolLiteral, StringLiteral, UnaryOp, ReferenceExpr,
    WildcardPattern, BindingPattern, LiteralPattern,
    RangePattern, TuplePattern, EnumPattern,
)
from .mangle import mangle_named


class MatchMixin:
    """Mixin providing match expression generation for CodeGenerator.

    Methods:
        _generate_match_expr: Generate code for match expressions
    """

    def _generate_match_expr(self, expr: MatchExpr):
        """Generate code for match expression."""
        # design 63 T1d: value/tuple/guarded matches use the general if-chain
        # lowering; classic enum matches keep the switch below.
        if expr.use_general_match:
            return self._generate_match_general(expr)

        # An arm may `lend` one of its payload bindings (design 146, DF-146d).
        # The binding is still EXTRACTED into an alloca — an enum is
        # `{ i32 tag, [N x i8] payload }`, so a pointer into the payload carries
        # only the tag's alignment and would be under-aligned for whatever the
        # payload holds — and the arm stores it back into the scrutinee when the
        # window closes. Copy-in/copy-out is indistinguishable from aliasing
        # here: a place window borrows the scrutinee's ROOT for its whole
        # extent, so the Law of Exclusivity guarantees nothing else can read the
        # slot while the payload is out.
        lends_payload = any(getattr(arm, 'lent_bindings', None)
                            for arm in expr.arms)
        scrut_ptr = None
        if lends_payload:
            scrut_ptr = self._generate_reference_expr(
                ReferenceExpr(expr=expr.matched_expr, mutable=True,
                              in_argument_position=True))
            matched_val = self.builder.load(scrut_ptr, name="lend_scrutinee")
        else:
            # Generate the matched value
            matched_val = self._generate_expression(expr.matched_expr)

        # Extract the tag
        # Check if enum is simple (i32) or has payload ({ i32, [N x i8] })
        if isinstance(matched_val.type, ir.IntType):
            # Simple enum
            tag = matched_val
        else:
            # Enum with payload
            tag = self.builder.extract_value(matched_val, 0, name="match_tag")

        # Get enum name from typechecker annotation, or fall back to LLVM type matching
        matched_enum_type = expr.matched_enum_type
        if matched_enum_type is not None:
            # Substitute the active monomorphization's type params first, so a
            # match on a generic enum inside a generic body (e.g.
            # `HashSlot<K, V>` in HashMap's methods, design 48) resolves to the
            # concrete registered name rather than `HashSlot$2$K$V`.
            if self.type_param_context:
                matched_enum_type = matched_enum_type.substitute(self.type_param_context)
            # Canonicalize before mangling so the lookup key matches the name the
            # enum was REGISTERED under (design 68). Codegen normalizes an erased
            # `Box<any Trait>` to its native arity-1 form and fills other omitted
            # defaults; the typechecker-stamped `matched_enum_type` uses arity-2
            # `Box<any Trait, Global>`, so without this a `match` on e.g.
            # `Result<T, Box<any Error>>` mangle-misses and the LLVM-type fallback
            # below silently picks a same-sized WRONG monomorphization.
            matched_enum_type = self._canonicalize_type_kind(matched_enum_type)
            # Canonical mangled name for a (possibly generic) enum, matching the
            # name under which it was registered (see codegen/mangle.py).
            enum_name = mangle_named(matched_enum_type.enum_name, matched_enum_type.type_args)
        else:
            enum_name = None
        # Design 145: `match self` inside a monomorphized method of a GENERIC
        # enum. The typechecker stamps the argument-free base (`Maybe`), which
        # is not a registered name — but the enclosing extension context already
        # names the concrete instantiation (`Maybe$1$Int`). Consult it before
        # the LLVM-type scan below, which would otherwise match any same-shaped
        # enum (every payload-free enum is a bare `i32`) and pick a wrong one.
        if ((enum_name is None or enum_name not in self.enum_types)
                and isinstance(expr.matched_expr, SelfExpr)
                and self.self_type_context in self.enum_types):
            enum_name = self.self_type_context
        # Fallback: find the enum name by matching LLVM types (also covers a
        # substitution that did not land on a registered name).
        if enum_name is None or enum_name not in self.enum_types:
            enum_name = None
            for name, (llvm_type, _, _) in self.enum_types.items():
                if llvm_type == matched_val.type:
                    enum_name = name
                    break

        # Ownership model for an OWNED enum scrutinee (design 61, L14/L15).
        #
        # When the matched enum has variants carrying owning (cleanup-needing)
        # payload, a `match owned_value { case V(a, b) -> ... }` CONSUMES the
        # scrutinee: the payload's ownership passes to the arm's bindings. Each
        # owning binding is registered for arm-scope cleanup, so a binding that
        # is not `move`d out is dropped exactly once when the arm ends, and a
        # `move`d one clears its drop flag (the normal conditional-move path) so
        # ownership leaves cleanly. The scrutinee itself is then NOT dropped (its
        # payload is gone), which is what makes Map/Set remove/overwrite/grow —
        # all of which move a slot out and destructure it — release each value
        # exactly once instead of double-freeing (scrutinee drop + moved copy).
        #
        # Gated to owning enums so payload-free / trivial enums (Ordering, the
        # coroutine `__state`, Result<Int,Int>, ...) are completely unaffected.
        variant_cleanup_info = {}
        if enum_name and enum_name in self.enum_types:
            variant_cleanup_info = self.enum_types[enum_name][2]
        enum_has_owning = any(
            any(self._needs_cleanup(ft) for _, ft in flds)
            for flds in variant_cleanup_info.values()
        )
        # The type the scrutinee's own drop glue is driven by, for the arms that
        # claim nothing (below) and for the copy-tier gate. `matched_enum_type`
        # is already substituted and canonicalized above, which is what
        # `enum_name` was mangled from.
        scrut_saw = matched_enum_type
        if scrut_saw is None or scrut_saw.kind != TypeKind.ENUM:
            scrut_saw = self._expr_type(expr.matched_expr)
        # WHICH ENUMS CONSUME (DF-190d). Consuming is a COPY-TIER rule, not an
        # "owns something" one, and this gate used to read `enum_has_owning`
        # alone. An ImplicitCopy-tier enum (`enum Holder { case Full(a:
        # Arc<Res>) }` + `@synthesize extension Holder: ImplicitCopy {}`) owns a
        # refcounted payload and copies for FREE — so the typechecker does NOT
        # mark its scrutinee moved (design 193 u1 / DF-190a) and a second
        # `match h` is legal source. Codegen still handed the payload to the arm
        # bindings and released it at the first arm's end while `h` was live:
        # the second match walked freed memory, silently, exit 0.
        #
        # Two modes now, the scrutinee's tier picking between them:
        #
        # * CONSUME (owning tiers — NoCopy/ExplicitCopy, and anything whose tier
        #   is not knowable here): ownership passes to the arm bindings and the
        #   scrutinee's own drop is suppressed. Unchanged.
        # * RETAIN (the ImplicitCopy tier): the match BORROWS. Each owning
        #   binding is retained at extraction and released at arm end, and the
        #   scrutinee keeps its own reference and drops at ITS scope end — one
        #   allocation, one release, and matching twice is fine.
        #
        # Only a NAMED, non-borrowed local can be in retain mode: a TEMPORARY
        # scrutinee (`match f() {...}`) is owned by nobody whatever its tier, so
        # it keeps taking the consume path below, which is what releases it
        # exactly once.
        # `read_policy` is the shared derivation of design 131's table from
        # design 139's tiers (namespace.py) — the same oracle the typechecker's
        # payload reads and place_uses' value reads ask.
        scrut_policy = self.namespace.read_policy(scrut_saw)
        # The scrutinee is consumable only when it is an OWNED binding in scope
        # (a `let`/param/if-let local). A field/temporary/borrow is left alone —
        # and a borrow is the case that hid: matching through a `&T`/`&var T`
        # binding took the consume path, so `case Occupied(_)` released a
        # payload the container still owned. That reached every `match` inside
        # a `with_ref` body and, since design 146, every match through a place.
        scrut_is_local = (isinstance(expr.matched_expr, Identifier)
                          and expr.matched_expr.name in self.variables
                          and not self._is_borrowed_name(expr.matched_expr.name))
        retain_mode = (enum_has_owning and scrut_is_local
                       and scrut_policy == 'retain')
        consume_name = None
        if enum_has_owning and scrut_is_local and not retain_mode:
            consume_name = expr.matched_expr.name
        # DF-151d: a TEMPORARY scrutinee (`match f() { ... }`, `match E.A(x)`)
        # is owned by NOBODY. It is not a binding, so it was never registered
        # for cleanup, and it is not an lvalue, so the consume path above did
        # not claim it either — its payload simply leaked, silently, on every
        # arm. Give it the storage a named local would have had and run it
        # through the SAME consume model, so `match f() {...}` and
        # `let s = f(); match s {...}` differ only in whether the value has a
        # name. The spill is what makes the drops below addressable: every one
        # of them needs a pointer to the scrutinee, and a temporary has none.
        temp_scrut_name = None
        if (consume_name is None and enum_has_owning
                and self._is_owned_temporary(expr.matched_expr)):
            # design 168 unit 3 (DF-164a): from the scrutinee's source position.
            # This was `id(expr)` — a raw heap ADDRESS, the exact thing design
            # 126 R2 removed everywhere else, and unreproducible between two runs
            # of the same compiler on the same file.
            temp_scrut_name = self._positional_local(expr, "__match_scrutinee")
            scrut_slot = self._entry_alloca(matched_val.type,
                                            name="match_scrutinee")
            self.builder.store(matched_val, scrut_slot)
            self.variables[temp_scrut_name] = scrut_slot
            consume_name = temp_scrut_name
        if consume_name is not None and temp_scrut_name is None:
            # Suppress the scrutinee's own drop on every path: its payload is
            # handed to the arm bindings, or dropped by the unclaimed-arm path
            # below. Clear a runtime drop flag if present (conditional-move
            # machinery) and mark it moved for the flat skip. A temporary has
            # neither, so it is skipped here.
            flag = self.drop_flags.get(consume_name)
            if flag is not None:
                self.builder.store(ir.Constant(ir.IntType(1), 0), flag)
            self.moved_variables.add(consume_name)

        # Create basic blocks for each arm + merge block
        arm_blocks = []
        wildcard_block = None
        for arm in expr.arms:
            arm_block = self.builder.append_basic_block(f"match_arm_{arm.variant_name}")
            arm_blocks.append((arm, arm_block))
            if arm.variant_name == "_":
                wildcard_block = arm_block

        merge_block = self.builder.append_basic_block("match_merge")

        # Create switch instruction
        # Use wildcard as default if present, otherwise first arm
        default_block = wildcard_block if wildcard_block else arm_blocks[0][1]
        switch = self.builder.switch(tag, default_block)

        # Add cases for non-wildcard arms
        if enum_name:
            _, variant_tags, variant_info = self.enum_types[enum_name]
            for arm, arm_block in arm_blocks:
                # Skip wildcard - it's the default case
                if arm.variant_name == "_":
                    continue
                tag_value = variant_tags[arm.variant_name]
                # The case constant must be the SCRUTINEE's width: a raw-backed
                # enum's tag is its declared backing, not i32 (design 145 B2).
                tag_const = ir.Constant(tag.type, tag_value)
                switch.add_case(tag_const, arm_block)

        # Generate code for each arm
        arm_results = []
        # A Void match (every reaching arm is a void call / void block) must NOT
        # build a phi (design 59 C). Void arms below are replaced with an i32
        # placeholder so a value-match phi stays well-formed; this flag records
        # whether ANY arm actually produced a real (non-void) value, so a purely
        # void match returns None instead of an i32 phi over placeholders.
        match_produces_value = False
        for arm, arm_block in arm_blocks:
            self.builder.position_at_end(arm_block)

            # When we take ownership of an owning scrutinee's payload (consume
            # mode), each owning binding is registered into a per-arm cleanup
            # scope so an un-`move`d binding drops exactly once at arm end and an
            # early `return`/`break` cleans it via `_cleanup_all_scopes`.
            arm_scope_pushed = False
            owning_bindings = []
            # The arm's lent payload bindings, as (payload field index, alloca)
            # pairs, plus the struct type the payload is read through — what the
            # write-back below needs (design 146, DF-146d).
            arm_lent = list(getattr(arm, 'lent_bindings', None) or [])
            lent_slots = []
            param_struct_type = None

            # Extract and bind associated values if any (not for wildcard).
            # A fully Void payload (design 92: the Ok arm of `Result<Void, E>`)
            # carries no data — there is nothing to extract, so treat a
            # `case Ok(_)` on it like a payload-free arm.
            _mv_variant_params = (self.enum_types[enum_name][2].get(arm.variant_name)
                                  if not isinstance(matched_val.type, ir.IntType)
                                  and enum_name in self.enum_types else None)
            _mv_all_void = (_mv_variant_params is not None
                            and all(isinstance(self._get_llvm_type(t), ir.VoidType)
                                    for _, t in _mv_variant_params))
            arm_extracts = (arm.variant_name != "_" and arm.bindings
                            and not isinstance(matched_val.type, ir.IntType)
                            and not _mv_all_void)
            # An arm that CLAIMS NOTHING leaves the scrutinee's payload
            # unclaimed: the consume model suppressed the scrutinee's own drop
            # on the strength of the bindings taking it, and this arm has none.
            # A `case _` over an owning variant leaked exactly this way whether
            # the scrutinee was a temporary or a named local — the wildcard is
            # the shape where the compiler cannot know which variant it holds,
            # so the whole scrutinee is dropped and its own tag switch decides
            # what runs. A named variant arm is dropped only when THAT variant
            # actually owns something, so a payload-free `case B` costs nothing.
            if consume_name is not None and not arm_extracts:
                unclaimed = (arm.variant_name == "_"
                             or any(self._needs_cleanup(ft) for _, ft
                                    in variant_cleanup_info.get(
                                        arm.variant_name, ())))
                scrut_ptr_owned = self.variables.get(consume_name)
                if unclaimed and scrut_ptr_owned is not None and scrut_saw is not None:
                    self._emit_drop_at(scrut_ptr_owned, scrut_saw)
            if arm_extracts:
                # Get variant info and enum type
                llvm_enum_type, _, variant_info = self.enum_types[enum_name]
                variant_params = variant_info[arm.variant_name]

                # Extract payload
                payload_bytes = self.builder.extract_value(matched_val, 1, name="payload")

                # Cast to appropriate struct type
                param_types = [self._get_llvm_type(t) for _, t in variant_params]
                param_struct_type = ir.LiteralStructType(param_types)

                # Store bytes to memory, then load as struct
                payload_alloca = self._entry_alloca(llvm_enum_type.elements[1], name="payload_alloca", align=8)
                self.builder.store(payload_bytes, payload_alloca)
                struct_ptr = self.builder.bitcast(payload_alloca,
                                                  ir.PointerType(param_struct_type),
                                                  name="param_struct_ptr")

                if consume_name is not None or retain_mode:
                    self.cleanup_stack.append([])
                    arm_scope_pushed = True

                # Create variables for bindings
                for i, binding_name in enumerate(arm.bindings):
                    # Extract field from struct
                    field_ptr = self.builder.gep(struct_ptr,
                                                [ir.Constant(ir.IntType(32), 0),
                                                 ir.Constant(ir.IntType(32), i)],
                                                inbounds=True)
                    field_val = self.builder.load(field_ptr, name=binding_name)

                    # Store in a variable
                    var_alloca = self._entry_alloca(field_val.type, name=binding_name)
                    self.builder.store(field_val, var_alloca)
                    self.variables[binding_name] = var_alloca
                    if binding_name in arm_lent:
                        lent_slots.append((i, var_alloca))

                    # In consume mode the binding OWNS its payload field: register
                    # cleanup-needing bindings so they drop once at arm end unless
                    # `move`d out (which clears the drop flag). The scrutinee's own
                    # drop was already suppressed above. A `_` discard binding is
                    # NOT registered: it names no value to own, so an owning field
                    # matched `_` is simply not dropped here (used by the Map probe
                    # helpers to inspect a by-value, non-retained slot copy without
                    # releasing its live payload).
                    if arm_scope_pushed and binding_name != "_" and i < len(variant_params):
                        btype = variant_params[i][1]
                        if self._needs_cleanup(btype):
                            # RETAIN mode (DF-190d): the scrutinee keeps its own
                            # reference, so the binding takes one of its OWN
                            # before the cleanup registration below releases it
                            # at arm end. This is design 131's value-read row
                            # for the ImplicitCopy tier — the same retain
                            # `let a = o!` takes out of an optional — applied at
                            # the one point an enum payload becomes a binding.
                            if retain_mode:
                                self._emit_retain_at(var_alloca, btype)
                            self.variable_types[binding_name] = btype
                            self._register_cleanup(binding_name, btype)
                            owning_bindings.append(binding_name)
                    elif (arm_scope_pushed and consume_name is not None
                          and binding_name == "_"
                          and i < len(variant_params)
                          and self._needs_cleanup(variant_params[i][1])):
                        # design 65 (L17): an owning payload field discarded with
                        # `_` under the consume model is UNCLAIMED — the scrutinee's
                        # own drop is suppressed, so nothing else releases it. RELEASE
                        # it now (it is never read in the arm), using the inverse of
                        # the copy-with-retain that `Vector.get` took when this value
                        # was read out of its slot: refcounted (ImplicitCopy) fields
                        # are released, a non-refcounted `Deinit` field (which the
                        # retain never bumped) is left untouched. This balances an
                        # owning String/Arc key in `Map._slot_state`'s `Occupied(_,_)`
                        # peek WITHOUT firing the deinit of a NoCopy-Deinit value the
                        # slot still owns (design-61 exactly-once VALUE tests).
                        self._emit_release_at(var_alloca, variant_params[i][1])

            # Generate arm body
            if isinstance(arm.body, Block):
                arm_result = self._generate_block(arm.body)
                # Get the value from the block
                if arm_result is None:
                    # Block didn't have a value, use void or a placeholder
                    arm_result = ir.Constant(ir.IntType(32), 0)  # Placeholder
                elif isinstance(arm_result.type, ir.VoidType):
                    # Void function call - use placeholder instead
                    arm_result = ir.Constant(ir.IntType(32), 0)  # Placeholder
                else:
                    match_produces_value = True
            else:
                # Route the arm result through the value-transfer path (not a raw
                # expression read): a bare owning binding that ESCAPES as the match
                # value (`case A(s) -> s`, an ImplicitCopy String/Arc payload) must
                # be RETAINED here, because the consume-mode arm cleanup below
                # releases that same binding — without the retain the escaped value
                # is freed out from under the match result (DF12). `move s` clears
                # the binding's drop flag instead (no retain), and a fresh temporary
                # (`case B -> ""`) is not aliasing, so neither is over-copied.
                arm_result = self._gen_transfer_value(arm.body)
                if arm_result is None or isinstance(arm_result.type, ir.VoidType):
                    # No value (e.g. a diverging `panic(...)` arm, design 49) or a
                    # Void expression — use a placeholder. A diverging arm has
                    # already terminated its block with `unreachable`, so this
                    # placeholder is never added to the phi below.
                    arm_result = ir.Constant(ir.IntType(32), 0)  # Placeholder
                else:
                    match_produces_value = True

            # The window has closed, so write each LENT payload binding back
            # into the scrutinee (design 146, DF-146d) — that is what makes a
            # write through the place reach the enum's own storage. `align=1`:
            # the payload byte array sits behind the tag, so its address is not
            # promised to carry the payload type's natural alignment.
            if lent_slots and scrut_ptr is not None and not self.builder.block.is_terminated:
                payload_ptr = self.builder.gep(
                    scrut_ptr,
                    [ir.Constant(ir.IntType(32), 0),
                     ir.Constant(ir.IntType(32), 1)],
                    inbounds=True, name="lend_payload_ptr")
                back_ptr = self.builder.bitcast(
                    payload_ptr, ir.PointerType(param_struct_type),
                    name="lend_writeback_struct")
                for slot_index, slot_alloca in lent_slots:
                    field_back = self.builder.gep(
                        back_ptr,
                        [ir.Constant(ir.IntType(32), 0),
                         ir.Constant(ir.IntType(32), slot_index)],
                        inbounds=True, name="lend_writeback_field")
                    self.builder.store(self.builder.load(slot_alloca),
                                       field_back, align=1)

            # Drop the arm's owning bindings (consume mode): an un-`move`d binding
            # is released here, exactly once. A terminated arm (return/break)
            # already ran `_cleanup_all_scopes` over this scope, so just balance
            # the stack. Done BEFORE reading the arm result into the phi so the
            # cleanup precedes the branch.
            if arm_scope_pushed:
                if not self.builder.block.is_terminated:
                    scope_vars = self.cleanup_stack.pop()
                    self._cleanup_scope(scope_vars)
                else:
                    self.cleanup_stack.pop()

            # Only add to arm_results if block is not terminated (has a return)
            if not self.builder.block.is_terminated:
                arm_results.append((arm_result, self.builder.block))

            # Clean up bindings
            for binding_name in arm.bindings:
                if binding_name in self.variables:
                    del self.variables[binding_name]
            for binding_name in owning_bindings:
                self.variable_types.pop(binding_name, None)
                self.drop_flags.pop(binding_name, None)

            # Branch to merge block (only if block not already terminated)
            if not self.builder.block.is_terminated:
                self.builder.branch(merge_block)

        # The spilled temporary scrutinee's slot is dead now: every arm either
        # handed its payload to bindings or dropped it. Retire the synthetic
        # name so nothing downstream can resolve it (DF-151d).
        if temp_scrut_name is not None:
            self.variables.pop(temp_scrut_name, None)
            self.moved_variables.discard(temp_scrut_name)

        # Position at merge block
        self.builder.position_at_end(merge_block)

        # Create phi node to merge results. A purely void match (no arm produced
        # a real value — the arm_results hold only i32 placeholders) yields no
        # consumable value and must NOT build a phi (design 59 C).
        if arm_results and match_produces_value:
            result_type = arm_results[0][0].type
            phi = self.builder.phi(result_type, name="match_result")
            for val, block in arm_results:
                phi.add_incoming(val, block)
            return phi
        else:
            # Match doesn't produce a value
            return None

    # ===== General pattern match (design 63 T1d) =====

    _SIGNED_INT_KINDS = {
        TypeKind.INT, TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
    }

    def _generate_match_general(self, expr: MatchExpr):
        """Lower a value/tuple/guarded match as a sequential if-chain (design 63).

        Each arm is a test block (`does the pattern match?`) that branches to a
        body block (bind, run the guard, evaluate the body) or to the next arm's
        test on failure. Pattern tests and binding extractions are pure, so they
        are emitted in the test block and used in the dominated body block.
        """
        scrut = self._generate_expression(expr.matched_expr)
        scrut_type = expr.matched_scrutinee_type
        if scrut_type is not None and self.type_param_context:
            scrut_type = scrut_type.substitute(self.type_param_context)

        # DF-151d: this lowering BORROWS its scrutinee — every binding it hands
        # an arm is an alias into the value, and nothing here consumes it. That
        # is already right for a named local, whose own scope drops it; a
        # TEMPORARY (`match f() { ... }`, a guarded or tuple or literal match on
        # a call result) has no owner at all, so its payload leaked. Give it a
        # slot and a cleanup scope of its own, spanning the whole match: the
        # aliases stay valid for every arm, the merge block drops it once on
        # every falling-through path, and an arm that `return`s reaches it
        # through `_cleanup_all_scopes` — after the return value has been
        # transferred, so a returned alias is retained before the drop runs.
        #
        # A scope rather than a statement temporary because a match is an
        # EXPRESSION and can be a function body's tail, where there is no
        # enclosing statement to hang a temporary on (`statement_temps` is None
        # there, so registering one silently did nothing).
        scrut_scope_pushed = False
        if (self._is_owned_temporary(expr.matched_expr)
                and scrut_type is not None
                and self._needs_cleanup(scrut_type)):
            scrut_slot = self._entry_alloca(scrut.type, name="match_scrutinee")
            self.builder.store(scrut, scrut_slot)
            self.cleanup_stack.append(
                [("__match_scrutinee", scrut_type, scrut_slot, None)])
            scrut_scope_pushed = True

        func = self.builder.function
        merge_block = func.append_basic_block("match_merge")
        arm_results = []
        match_produces_value = False

        n = len(expr.arms)
        # Pre-create the test block for each arm; the "no match" target of arm i
        # is the test block of arm i+1. The final fallthrough goes to a dedicated
        # `unreachable` default (the typechecker proved exhaustiveness), so the
        # merge block only ever has body-block predecessors for the phi.
        test_blocks = [func.append_basic_block(f"match_test_{i}") for i in range(n)]
        default_block = func.append_basic_block("match_default")
        self.builder.branch(test_blocks[0])

        for i, arm in enumerate(expr.arms):
            next_block = test_blocks[i + 1] if i + 1 < n else default_block
            body_block = func.append_basic_block(f"match_body_{i}")

            # --- test block: evaluate the pattern condition ---
            self.builder.position_at_end(test_blocks[i])
            cond, bindings = self._match_pattern(arm.pattern, scrut, scrut_type)
            self.builder.cbranch(cond, body_block, next_block)

            # --- body block: bind, guard, body ---
            self.builder.position_at_end(body_block)
            defined = []
            for bname, bval, btype in bindings:
                if bname == "_":
                    continue
                alloca = self._entry_alloca(bval.type, name=bname)
                self.builder.store(bval, alloca)
                self.variables[bname] = alloca
                if btype is not None:
                    self.variable_types[bname] = btype
                defined.append(bname)

            # Guard: on false, fall through to the next arm's test.
            if arm.guard is not None:
                gval = self._generate_expression(arm.guard)
                guard_ok = func.append_basic_block(f"match_guard_ok_{i}")
                self.builder.cbranch(gval, guard_ok, next_block)
                self.builder.position_at_end(guard_ok)

            # Arm body. A bare-expression body goes through the value-transfer
            # path, not a raw expression read, for the same reason the enum
            # lowering does (DF12): an arm binding is an ALIAS into the
            # scrutinee, so a binding that ESCAPES as the match's value must be
            # RETAINED — the scrutinee's own drop (its binding's scope, or the
            # match scope pushed above) releases that same payload afterwards.
            # Without the retain `case A(x) if k > 0 -> x` handed back a value
            # that was freed on the way out.
            if isinstance(arm.body, Block):
                arm_result = self._generate_block(arm.body)
            else:
                arm_result = self._gen_transfer_value(arm.body)
            if arm_result is None or isinstance(arm_result.type, ir.VoidType):
                arm_result = ir.Constant(ir.IntType(32), 0)  # placeholder
            else:
                match_produces_value = True

            if not self.builder.block.is_terminated:
                arm_results.append((arm_result, self.builder.block))
                self.builder.branch(merge_block)

            # Unbind arm-local names so they do not leak into later arms.
            for bname in defined:
                self.variables.pop(bname, None)
                self.variable_types.pop(bname, None)

        # The default (no-arm-matched) block is unreachable after an exhaustive
        # match.
        self.builder.position_at_end(default_block)
        self.builder.unreachable()

        self.builder.position_at_end(merge_block)
        phi = None
        if arm_results and match_produces_value:
            result_type = arm_results[0][0].type
            phi = self.builder.phi(result_type, name="match_result")
            for val, block in arm_results:
                phi.add_incoming(val, block)
        # The temporary scrutinee dies with the match. Merge dominates every arm
        # that fell through, so one drop here covers all of them; an arm that
        # returned already dropped it through `_cleanup_all_scopes` (DF-151d).
        # AFTER the phi — a phi has to lead its block, and the arm result it
        # merges was already retained by the transfer above, so releasing the
        # scrutinee behind it is safe.
        if scrut_scope_pushed:
            self._cleanup_scope(self.cleanup_stack.pop())
        return phi

    def _match_pattern(self, pattern, value, saw_type):
        """Return (i1 condition, bindings) for `pattern` against `value`.

        `bindings` is a list of (name, llvm_value, saw_type). Emitted in the
        current (test) block; extractions are pure and dominate the body block.
        """
        true = ir.Constant(ir.IntType(1), 1)
        rt = self._resolve_type_alias(saw_type) if saw_type is not None else None

        if pattern is None or isinstance(pattern, WildcardPattern):
            return true, []
        if isinstance(pattern, BindingPattern):
            return true, [(pattern.name, value, saw_type)]
        if isinstance(pattern, LiteralPattern):
            return self._match_literal(pattern.value, value, saw_type), []
        if isinstance(pattern, RangePattern):
            start = self._generate_expression(pattern.start)
            end = self._generate_expression(pattern.end)
            if isinstance(value.type, ir.IntType):
                start = self._reconcile_int_width(self.builder, start, value.type)
                end = self._reconcile_int_width(self.builder, end, value.type)
            signed = rt is not None and rt.kind in self._SIGNED_INT_KINDS
            cmp = self.builder.icmp_signed if signed else self.builder.icmp_unsigned
            ge = cmp('>=', value, start, name="rng_lo")
            hi = cmp('<=' if pattern.is_inclusive else '<', value, end, name="rng_hi")
            return self.builder.and_(ge, hi, name="rng"), []
        if isinstance(pattern, TuplePattern):
            elem_types = rt.element_types if (rt is not None and rt.element_types) else [None] * len(pattern.elements)
            cond = true
            bindings = []
            for idx, sub in enumerate(pattern.elements):
                ev = self.builder.extract_value(value, idx, name=f"tup_e{idx}")
                c, b = self._match_pattern(sub, ev, elem_types[idx])
                cond = self.builder.and_(cond, c, name="tup_and")
                bindings += b
            return cond, bindings
        if isinstance(pattern, EnumPattern):
            return self._match_enum_pattern(pattern, value, rt)
        # Unknown pattern: never matches.
        return ir.Constant(ir.IntType(1), 0), []

    def _match_literal(self, lit_expr, value, saw_type):
        """i1 condition for a literal pattern (int / Bool / String)."""
        lit_val = self._generate_expression(lit_expr)
        if isinstance(value.type, ir.IntType) and isinstance(lit_val.type, ir.IntType):
            lit_val = self._reconcile_int_width(self.builder, lit_val, value.type)
        return self._emit_equals(value, lit_val, saw_type)

    def _match_enum_pattern(self, pattern, value, rt):
        """i1 condition + payload bindings for a variant pattern against a user
        enum or an Optional (`{i1, T}`)."""
        # Optional scrutinee: `{ i1 is_some, T }`.
        if rt is not None and rt.kind == TypeKind.OPTIONAL:
            is_some = self.builder.extract_value(value, 0, name="is_some")
            if pattern.variant_name == "None":
                cond = self.builder.not_(is_some, name="is_none")
                return cond, []
            # Some(sub)
            payload = self.builder.extract_value(value, 1, name="opt_payload")
            inner = rt.inner_type
            sub = pattern.subpatterns[0] if pattern.subpatterns else None
            c, b = self._match_pattern(sub, payload, inner)
            return self.builder.and_(is_some, c, name="some_and"), b

        # User enum: mangle to the registered name, extract tag + payload.
        enum_name = None
        if rt is not None and rt.kind == TypeKind.ENUM and rt.enum_name:
            enum_name = mangle_named(rt.enum_name, rt.type_args)
        if enum_name is None or enum_name not in self.enum_types:
            # Fall back by LLVM type shape.
            for name, (llvm_type, _, _) in self.enum_types.items():
                if llvm_type == value.type:
                    enum_name = name
                    break
        if enum_name is None or enum_name not in self.enum_types:
            return ir.Constant(ir.IntType(1), 0), []
        llvm_enum_type, variant_tags, variant_info = self.enum_types[enum_name]
        tag = self.builder.extract_value(value, 0, name="match_tag")
        want = ir.Constant(tag.type, variant_tags[pattern.variant_name])
        cond = self.builder.icmp_signed('==', tag, want, name="tageq")
        bindings = []
        if pattern.subpatterns:
            params = variant_info[pattern.variant_name]
            payload_bytes = self.builder.extract_value(value, 1, name="payload")
            param_types = [self._get_llvm_type(t) for _, t in params]
            param_struct_type = ir.LiteralStructType(param_types)
            payload_alloca = self._entry_alloca(llvm_enum_type.elements[1], name="payload_alloca", align=8)
            self.builder.store(payload_bytes, payload_alloca)
            struct_ptr = self.builder.bitcast(payload_alloca,
                                              ir.PointerType(param_struct_type),
                                              name="param_struct_ptr")
            for idx, sub in enumerate(pattern.subpatterns):
                field_ptr = self.builder.gep(struct_ptr,
                                             [ir.Constant(ir.IntType(32), 0),
                                              ir.Constant(ir.IntType(32), idx)],
                                             inbounds=True)
                field_val = self.builder.load(field_ptr, name=f"field{idx}")
                c, b = self._match_pattern(sub, field_val, params[idx][1])
                cond = self.builder.and_(cond, c, name="payload_and")
                bindings += b
        return cond, bindings
