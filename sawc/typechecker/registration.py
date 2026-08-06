"""
Registration methods for the Saw type checker.

This module provides mixin methods for registering type definitions, structs,
enums, traits, functions, and extensions during the first pass of type checking.

Usage:
    class TypeChecker(RegistrationMixin, ...):
        pass
"""

import copy
from typing import Dict, List, Optional, Tuple
from ast_nodes import (
    TypeDefinition, Struct, Enum, Trait, Function, Extension, Method, Parameter,
    Program, StaticDecl, SawType, TypeKind, Visibility, has_synthesize,
    Block, ReturnStatement, BreakStatement, ContinueStatement, IfExpr,
    IntLiteral, FloatLiteral, BoolLiteral, UnaryOp, ArrayLiteral, StructInit,
    FunctionCall, ExpressionStatement, SourceLocationLiteral
)
from errors import ErrorKind
from namespace import (
    SymbolKind, FunctionSymbol, StructSymbol, EnumSymbol, TraitSymbol,
    TypeAliasSymbol, TraitMethodSymbol, StaticSymbol
)


# Call names the compiler INTERCEPTS in `_check_function_call`
# (typechecker/expressions.py) before any user overload set is consulted. A
# top-level declaration of one of these in user code could never be reached, and
# used to be dropped in silence — the arity/type error at the call site then
# blamed the caller (design 122 unit D / review RS-5). Declaring one is now a
# duplicate-definition error. std/builtin.saw are exempt: `std.task.yield_now`
# is deliberately a wrapper whose body calls the intercepted intrinsic.
BUILTIN_CALL_NAMES = frozenset({
    "print", "panic", "assert", "sleep", "spawn", "cancelled", "yield_now",
    "io_wait", "io_unwait", "sizeof", "alignof",
    # compiler-internal intrinsics (also intercepted, also unreachable if
    # redeclared)
    "__saw_test_suspend", "__saw_suspend", "__saw_io_park", "__saw_box_data",
    "__saw_blk_start", "__saw_blk_done", "__saw_blk_pipe_fd", "__saw_blk_take",
    "__saw_drive", "__saw_drive_steps", "__saw_deinit_in_place", "__saw_forget",
})


class RegistrationMixin:
    """Mixin providing registration methods for TypeChecker.

    These methods are used in the first pass of type checking to collect
    all type definitions before checking function/method bodies.

    Methods:
        _register_builtins: Register built-in functions and types
        _block_has_early_exit: Check if a block definitely exits early
        _register_type_definition: Register a type alias
        _register_struct: Register a struct definition
        _register_enum: Register an enum definition
        _register_trait: Register a trait definition
        _register_function: Register a function signature
        _register_extern_function: Register an external (FFI) function
        _register_extension: Register methods from an extension
        _check_trait_conformance: Verify type implements trait
        _types_compatible_for_trait: Check type compatibility for traits
        _resolve_trait_type: Resolve Self and associated types in trait
    """

    def _register_builtins(self):
        """Register built-in functions."""
        # print can take any single argument
        # We'll handle it specially in check_function_call
        #
        # Note: Built-in traits (Deinit, ImplicitCopy, NoCopy) are defined
        # in builtin.saw and loaded automatically by the compiler.

        # Register String as a pseudo-struct so it can be extended
        # String is a primitive type (i8*) but we want to add methods to it
        self.namespace.register_struct("String", StructSymbol(
            fields={},
            field_order=[],
            line=0,
            column=0
        ))

        # String is a compiler-known refcounted value type: ImplicitCopy (a copy
        # is a refcount bump) + Deinit (release, free at zero). The copy/deinit
        # bodies are IR-level runtime helpers emitted by codegen, so the
        # conformance is registered here rather than declared in stdlib. This
        # drives value-transfer copy() insertion and scope-exit cleanup.
        self.namespace.register_conformance("String", "ImplicitCopy")
        self.namespace.register_conformance("String", "Deinit")
        # String is Equatable builtin (design 32): content equality via the
        # hand-written `String.equals` in std/string.saw; `==` on String lowers
        # to a call to it (fixing the old pointer-identity comparison, S4).
        self.namespace.register_conformance("String", "Equatable")
        # String is Comparable + Hashable builtin (design 48): byte-lexicographic
        # `compare` and byte-streaming `hash` are hand-written in std/string.saw;
        # `< <= > >=` on String lower to `String.compare`, and `.hash(&h)` on a
        # String dispatches to `String.hash`.
        self.namespace.register_conformance("String", "Comparable")
        self.namespace.register_conformance("String", "Hashable")

        # Register Int and Float as pseudo-structs so they can carry method
        # extensions (design 57 Part 5), the same mechanism String uses. No
        # conformances are registered here: their Copy/Equatable/Comparable/
        # Hashable behavior is handled by the primitive-aware bound checks and
        # the compiler-intercepted copy/hash/compare/format lowerings, all of
        # which run before ordinary struct-method dispatch. The pseudo-struct
        # only makes `extension Int { ... }` / `extension Float { ... }` and
        # value.method() dispatch resolve.
        for _prim in ("Int", "Float"):
            self.namespace.register_struct(_prim, StructSymbol(
                fields={}, field_order=[], line=0, column=0))

        # Register Result<T, E> as a built-in generic enum
        from ast_nodes import TypeParameter

        result_type_params = [
            TypeParameter(name="T", line=0, column=0),
            TypeParameter(name="E", line=0, column=0)
        ]
        self.namespace.register_enum("Result", EnumSymbol(
            variants={
                "Ok": [("value", SawType(TypeKind.TYPE_PARAM, type_param_name="T"))],
                "Err": [("error", SawType(TypeKind.TYPE_PARAM, type_param_name="E"))]
            },
            variant_order=["Ok", "Err"],
            type_params=result_type_params
        ))

        # The `Error` trait (design 56) is defined in builtin.saw as
        # `trait Error: Printable {}`, registered by the ordinary trait pass — no
        # hardcoded registration here.

    def _block_has_early_exit(self, block: Block) -> bool:
        """Check if a block definitely exits early (return, break, continue).

        This checks if the block cannot fall through to the next statement.
        A block has an early exit if:
        - It contains a return/break/continue at the top level
        - It ends with an if-else where both branches have early exits
        """
        for stmt in block.statements:
            if isinstance(stmt, (ReturnStatement, BreakStatement, ContinueStatement)):
                return True
            # A `panic(...)` call (type NEVER, design 49) diverges just like a
            # return, so `guard let x = ... else { panic("...") }` is a valid exit.
            if isinstance(stmt, ExpressionStatement) and self._expr_diverges(stmt.expression):
                return True
            # Check if-else: both branches must have early exits
            if isinstance(stmt, IfExpr) and stmt.else_branch:
                then_exits = self._block_has_early_exit(stmt.then_branch)
                else_exits = self._block_has_early_exit(stmt.else_branch)
                if then_exits and else_exits:
                    return True
        # A block whose trailing expression diverges (e.g. `{ panic("...") }`)
        # also cannot fall through.
        if block.final_expr is not None and self._expr_diverges(block.final_expr):
            return True
        return False

    def _expr_diverges(self, expr) -> bool:
        """True if evaluating `expr` never falls through — i.e. it is a
        `panic(...)` call (design 49). Used to treat a trailing panic as an
        early exit for guard/if divergence analysis."""
        return isinstance(expr, FunctionCall) and expr.name == "panic"

    def _check_loop_body(self, body: Block, outer_scope):
        """Check a loop body with may-repeat move semantics (design 15 rule 7).

        Conservative (shipped) rule: a binding declared OUTSIDE the loop that is
        moved inside the body and NOT definitely reassigned before the body ends
        would be moved-from again on the next iteration -- a use-after-move
        across iterations. Each such binding is flagged at its move site. A move
        followed by a definite reassignment (revival) inside the body is fine:
        the revived binding is not moved at body end, so it is not flagged.

        `outer_scope` is the scope enclosing the loop (for a `for` loop this is
        the scope BEFORE the loop variable is bound, so moving the freshly-bound
        loop variable each iteration is not flagged). After the loop the move
        state is reset to the pre-loop state, since the loop may run zero times.
        """
        entry_moves = self._snapshot_moves()
        outer_ids = set()
        scope = outer_scope
        while scope is not None:
            for var_info in scope.variables.values():
                outer_ids.add(var_info.binding_id)
            scope = scope.parent

        self._check_block(body)

        for key, (var_info, name, move_line, move_col) in list(self.moved_bindings.items()):
            if key in entry_moves:
                continue  # already moved before the loop -- caught elsewhere
            if key in outer_ids:
                self._error(
                    ErrorKind.USE_AFTER_MOVE,
                    f"use of moved variable `{name}` across loop iterations",
                    move_line, move_col,
                    hint="a binding moved inside a loop is moved-from on the next "
                         "iteration; reassign it before the loop body ends, or move a fresh value"
                )

        # The loop may execute zero times, so after it we are back to the
        # pre-loop state (any real cross-iteration move was flagged above).
        self.moved_bindings = entry_moves

    def _arm_diverges(self, body) -> bool:
        """True if a match-arm body definitely exits the enclosing scope.

        Used by the move-dataflow merge (design 15 rule 6): a diverging arm
        does not contribute to the may-moved union. A block body reuses
        `_block_has_early_exit`; a bare statement body (return/break/continue)
        diverges directly; a plain expression body does not.
        """
        if isinstance(body, Block):
            return self._block_has_early_exit(body)
        return isinstance(body, (ReturnStatement, BreakStatement, ContinueStatement))

    def _register_type_definition(self, type_def: TypeDefinition):
        """Register a type definition (type alias)."""
        if self.get_type_alias_info(type_def.name):
            self._error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"type `{type_def.name}` is defined multiple times",
                type_def.line, type_def.column
            )
            return

        # Resolve the defined type (it might reference other type aliases)
        resolved_type = self._resolve_type_alias(type_def.defined_type)
        self.namespace.register_type_alias(type_def.name, TypeAliasSymbol(
            aliased_type=resolved_type,
            immediate_type=type_def.defined_type,
            visibility=getattr(type_def, 'visibility', Visibility.PRIVATE),
            type_identity=self._stamp_type_identity(type_def),
            def_module=self._vis_module_for_source(
                getattr(type_def, 'source_file', None))
        ))

    def _register_struct(self, struct: Struct):
        """Register a struct definition."""
        if self.namespace.has_struct(struct.name) and not self._shadows_hidden_std(struct.name):
            self._error(
                ErrorKind.DUPLICATE_FUNCTION,  # We can reuse this error kind
                f"struct `{struct.name}` is defined multiple times",
                struct.line, struct.column
            )
            return

        # design 130 rule 1: the SEMANTICS come from the `unsafe` keyword, but the
        # NAME is then enforced, so an unsafe type is visible at every use site
        # without the reader consulting its declaration. The converse does not
        # hold — a plain `struct UnsafeDefaults` is an ordinary safe type, since
        # the keyword is the only thing that confers unsafety.
        if getattr(struct, 'is_unsafe', False) and not struct.name.startswith("Unsafe"):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"an unsafe type must be named `Unsafe*`, but this one is "
                f"named `{struct.name}`",
                struct.line, struct.column,
                hint=f"rename it to `Unsafe{struct.name}`, or drop the `unsafe` "
                     f"keyword if the type is safe to name, hold and pass",
            )

        # Check for duplicate fields
        fields = {}
        field_order = []
        seen_fields = set()

        for field in struct.fields:
            if field.name in seen_fields:
                self._error(
                    ErrorKind.DUPLICATE_VARIABLE,  # Reuse this
                    f"field `{field.name}` is defined multiple times in struct `{struct.name}`",
                    struct.line, struct.column
                )
            else:
                seen_fields.add(field.name)
                # A closure-typed field is escaping (design 16/29): the struct
                # value can outlive any call, so a stored closure must be safe to
                # store. Stamp the bit; writing `escaping` here is redundant.
                self._stamp_escaping_roles(
                    field.type, is_param=False,
                    report_at=(getattr(field, 'line', struct.line),
                               getattr(field, 'column', struct.column)))
                fields[field.name] = field.type
                field_order.append(field.name)

        # Member visibility (design 80): per-field visibility + the struct's
        # defining module (keyed on source file so std files each form their own
        # module even under the merged prelude).
        field_visibility = {f.name: getattr(f, 'visibility', Visibility.PRIVATE)
                            for f in struct.fields}
        def_module = self._vis_module_for_source(getattr(struct, 'source_file', None))
        self.namespace.register_struct(struct.name, StructSymbol(
            fields=fields,
            field_order=field_order,
            type_params=struct.type_params,
            visibility=getattr(struct, 'visibility', Visibility.PRIVATE),
            field_visibility=field_visibility,
            def_module=def_module,
            type_identity=self._stamp_type_identity(struct),
            is_unsafe=getattr(struct, 'is_unsafe', False),
            line=struct.line,
            column=struct.column,
            ast_node=struct if struct.type_params else None
        ))

    def _register_enum(self, enum: Enum):
        """Register an enum definition."""
        if self.namespace.has_enum(enum.name):
            self._error(
                ErrorKind.DUPLICATE_FUNCTION,  # Reuse this error kind
                f"enum `{enum.name}` is defined multiple times",
                enum.line, enum.column
            )
            return

        if self.namespace.has_struct(enum.name):
            self._error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"enum `{enum.name}` conflicts with existing struct name",
                enum.line, enum.column
            )
            return

        # Check for duplicate variants
        variants = {}
        variant_order = []
        seen_variants = set()

        for variant in enum.variants:
            if variant.name in seen_variants:
                self._error(
                    ErrorKind.DUPLICATE_VARIABLE,  # Reuse this
                    f"variant `{variant.name}` is defined multiple times in enum `{enum.name}`",
                    enum.line, enum.column
                )
            else:
                seen_variants.add(variant.name)
                # Enum payloads are escaping roles (design 16/29), like fields.
                for _payload in (variant.associated_types or []):
                    _pt = _payload[1] if isinstance(_payload, tuple) else _payload
                    self._stamp_escaping_roles(
                        _pt, is_param=False, report_at=(enum.line, enum.column))
                variants[variant.name] = variant.associated_types
                variant_order.append(variant.name)

        # Raw integer backing (design 145 unit B2).
        raw_type, raw_values = self._check_enum_raw_backing(enum)

        # Register in namespace only
        self.namespace.register_enum(enum.name, EnumSymbol(
            variants=variants,
            variant_order=variant_order,
            type_params=enum.type_params,
            visibility=getattr(enum, 'visibility', Visibility.PRIVATE),
            def_module=self._vis_module_for_source(
                getattr(enum, 'source_file', None)),
            type_identity=self._stamp_type_identity(enum),
            ast_node=enum if enum.type_params else None,
            raw_type=raw_type,
            raw_values=raw_values
        ))

    # Integer kinds a raw backing may name (design 145 unit B2). Any
    # fixed-width int plus platform `Int`/`UInt`; the design-47 wire discipline
    # favours the fixed-width ones and the docs say so.
    _RAW_BACKING_KINDS = (
        TypeKind.INT, TypeKind.UINT,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
    )

    def _int_fits_kind(self, value: int, kind) -> bool:
        """Whether `value` is representable in integer type `kind`.

        DF-137d / DF-140a: platform `Int`/`UInt` are judged at the EFFECTIVE
        target's width, not a fixed 64 — a raw-backed enum case value is ABI, so
        a case that does not fit the target's `Int` must be rejected on that
        target rather than wrapped."""
        rng = self._int_range_for(kind)
        return rng is not None and rng[0] <= value <= rng[1]

    def _check_enum_raw_backing(self, enum: SawEnum):
        """Validate `enum E: <Int> { case A = 0, ... }` and return
        `(raw_type, {case: value})`, or `(None, {})` when no backing is
        declared (design 145 unit B2).

        Three rules, each with its own diagnostic:
          1. PAYLOAD-FREE ONLY. An enum with payloads has no integer identity.
          2. EXPLICIT VALUES REQUIRED, and distinct. Declaring a backing claims
             the numbers are ABI, so nothing is auto-assigned and reordering the
             cases can never silently renumber them.
          3. Every value must fit the backing's range.
        An enum WITHOUT a backing keeps compiler-assigned ordinals and rejects a
        stray `= <int>` — that number would be a promise the language is not
        making.
        """
        raw_type = getattr(enum, 'raw_type', None)
        if raw_type is None:
            for variant in enum.variants:
                if variant.raw_value is None:
                    continue
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"case `{variant.name}` of enum `{enum.name}` gives a raw "
                    f"value, but the enum declares no backing type",
                    variant.raw_line or enum.line,
                    variant.raw_column or enum.column,
                    hint=f"declare one (`enum {enum.name}: UInt8 {{ ... }}`) to "
                         f"pin the case values, or drop the `= ...`",
                    source_file=getattr(enum, 'source_file', None)
                )
            return None, {}

        raw_type = self._resolve_type(raw_type)
        if raw_type is None or raw_type.kind not in self._RAW_BACKING_KINDS:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"enum `{enum.name}` has backing type `{raw_type}`, which is "
                f"not an integer type",
                enum.line, enum.column,
                hint="a raw backing must be a fixed-width integer (`Int8`.."
                     "`UInt64`) or platform `Int`/`UInt`; fixed-width is the "
                     "wire-safe choice",
                source_file=getattr(enum, 'source_file', None)
            )
            return None, {}

        # Rule 1: payload-free only.
        for variant in enum.variants:
            if variant.associated_types:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"case `{variant.name}` of enum `{enum.name}` carries a "
                    f"payload, so the enum cannot declare a backing type: an "
                    f"enum with payloads has no integer identity",
                    enum.line, enum.column,
                    hint=f"drop the `: {raw_type}` backing, or move the payload "
                         f"case to a separate type",
                    source_file=getattr(enum, 'source_file', None)
                )
                return None, {}

        # Rules 2 and 3: explicit, distinct, in range.
        raw_values = {}
        by_value = {}
        for variant in enum.variants:
            if variant.raw_value is None:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"case `{variant.name}` of enum `{enum.name}` needs an "
                    f"explicit value: every case of an enum with a backing type "
                    f"declares its own",
                    enum.line, enum.column,
                    hint=f"write `case {variant.name} = <int>`; declaring a "
                         f"backing type says the numbers are ABI, so none is "
                         f"assigned for you",
                    source_file=getattr(enum, 'source_file', None)
                )
                continue
            if not self._int_fits_kind(variant.raw_value, raw_type.kind):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"raw value {variant.raw_value} for case `{variant.name}` "
                    f"is out of range for backing type `{raw_type}`",
                    variant.raw_line or enum.line,
                    variant.raw_column or enum.column,
                    source_file=getattr(enum, 'source_file', None)
                )
                continue
            prior = by_value.get(variant.raw_value)
            if prior is not None:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cases `{prior}` and `{variant.name}` of enum "
                    f"`{enum.name}` both have raw value {variant.raw_value}",
                    variant.raw_line or enum.line,
                    variant.raw_column or enum.column,
                    hint="raw values identify the cases on the wire, so they "
                         "must be distinct",
                    source_file=getattr(enum, 'source_file', None)
                )
                continue
            by_value[variant.raw_value] = variant.name
            raw_values[variant.name] = variant.raw_value

        return raw_type, raw_values

    def _register_trait(self, trait: Trait):
        """Register a trait definition with inheritance support."""
        if self.namespace.has_trait(trait.name):
            self._error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"trait `{trait.name}` is defined multiple times",
                trait.line, trait.column
            )
            return

        # Validate and collect inherited methods from parent traits
        inherited_methods = {}
        inherited_assoc_types = []
        for parent_name in trait.parent_traits:
            parent_info = self.get_trait_info(parent_name)
            if parent_info is None:
                self._error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"unknown parent trait `{parent_name}`",
                    trait.line, trait.column
                )
                continue
            # Inherit all methods from parent (already TraitMethodSymbol)
            for method_name, method_sym in parent_info.methods.items():
                inherited_methods[method_name] = method_sym
            # Inherit associated types
            for assoc_type in parent_info.associated_types:
                if assoc_type not in inherited_assoc_types:
                    inherited_assoc_types.append(assoc_type)

        # Build method symbol map from this trait's own methods
        methods = dict(inherited_methods)  # Start with inherited
        for method in trait.methods:
            # Collect parameter info (excluding self placeholder type)
            param_names = []
            param_types = []

            for param in method.parameters:
                if param.name == "self":
                    # self has the type of the implementing type (handled during conformance)
                    param_types.append(SawType(TypeKind.VOID))  # Placeholder
                else:
                    param_names.append(param.name)
                    param_types.append(param.type)

            methods[method.name] = TraitMethodSymbol(
                name=method.name,
                param_types=param_types,
                return_type=method.return_type,
                param_names=param_names,
                self_mutable=method.self_mutable,
                self_is_reference=method.self_is_reference,
                is_sync=getattr(method, 'is_sync', False),
                is_unsafe=getattr(method, 'is_unsafe', False),
                # Carry the AST so a conformer can synthesize a Method from the
                # default body (design 56); inherited symbols keep their own
                # ast_node, so defaults propagate through trait inheritance.
                ast_node=method
            )

        # Collect associated type names (own + inherited)
        assoc_type_names = list(inherited_assoc_types)
        for at in trait.associated_types:
            if at.name not in assoc_type_names:
                assoc_type_names.append(at.name)

        self.namespace.register_trait(trait.name, TraitSymbol(
            name=trait.name,
            methods=methods,
            associated_types=assoc_type_names,
            parent_traits=trait.parent_traits,
            visibility=getattr(trait, 'visibility', Visibility.PRIVATE),
            def_module=self._vis_module_for_source(
                getattr(trait, 'source_file', None)),
            type_identity=self._stamp_type_identity(trait)
        ))

    def _register_function(self, func: Function):
        """Register a function signature.

        Overloading (design 55): a name may carry several declarations as long
        as no two share an indistinguishable normalized signature. The old
        "defined multiple times" error now fires only at the declaration-site
        collision below (identical post-alias / bare-type-param signatures).
        """
        # Design 122 unit D: a name the compiler intercepts at every call site
        # cannot be redefined — the declaration would never be reachable.
        if self._reject_builtin_redefinition(func, "function"):
            return

        # Default parameter values (design 53) must be trailing.
        self._check_trailing_defaults(func.parameters, func.line, func.column,
                                      f"function `{func.name}`")
        default_values = [p.default_value for p in func.parameters]

        # For generic functions, don't resolve types yet (they may contain type params)
        if func.type_params:
            param_types = [p.type for p in func.parameters]
            param_names = [p.name for p in func.parameters]
            return_type = func.return_type
        else:
            # Resolve types before registering
            param_types = [self._resolve_type(p.type) for p in func.parameters]
            param_names = [p.name for p in func.parameters]
            return_type = self._resolve_type(func.return_type)
            # Escaping roles (design 16/29): parameter closure types default
            # non-escaping; the return type is an escaping role.
            for _pt in param_types:
                self._stamp_escaping_roles(_pt, is_param=True,
                                           report_at=(func.line, func.column))
            self._stamp_escaping_roles(return_type, is_param=False,
                                       report_at=(func.line, func.column))
            # Update AST with resolved types for codegen. Both the return type AND
            # each parameter annotation are written back so a module-qualified
            # annotation (`p: shapes.Point`) reaches codegen as the resolved simple
            # name instead of the dotted `struct_name` codegen cannot look up (L18,
            # design 68). Without the param write-back only the FunctionSymbol saw
            # the resolved types; `_get_llvm_type(param.type)` still ICE'd.
            func.return_type = return_type
            for _param, _rt in zip(func.parameters, param_types):
                _param.type = _rt

        # Declaration-site overload check (design 55 + design 53): reject a new
        # declaration that no tie-break rule could separate from an existing one.
        # A defaulted parameter expands a declaration into several reachable call
        # SHAPES (full arity down to first-defaulted arity); ANY shape collision
        # with another overload's shape is a declaration-site ambiguity (design
        # 53). Non-defaulted declarations expand to a single shape, so this
        # subsumes design 55's identical-signature rejection.
        new_keys = self._overload_shape_keys(param_types, func.type_params,
                                              default_values, param_names)
        for other in self.namespace.lookup_function_overloads(func.name):
            other_keys = self._overload_shape_keys(
                other.param_types, other.type_params, other.default_values,
                other.param_names)
            if new_keys & other_keys:
                self._error(
                    ErrorKind.DUPLICATE_FUNCTION,
                    f"function `{func.name}` is already defined with an "
                    f"indistinguishable signature (a default-parameter call "
                    f"shape collides with another overload)",
                    func.line, func.column,
                    hint="overloads must differ in arity or parameter types "
                         "(distinct types, not just type aliases of the same "
                         "underlying type); expanded default-value shapes count"
                )
                return

        self.namespace.register_function(func.name, FunctionSymbol(
            param_types=param_types,
            param_names=param_names,
            return_type=return_type,
            type_params=func.type_params,
            default_values=default_values,
            visibility=getattr(func, 'visibility', Visibility.PRIVATE),
            is_sync=getattr(func, 'is_sync', False),
            is_unsafe=getattr(func, 'is_unsafe', False),
            def_module=self._vis_module_for_source(
                getattr(func, 'source_file', None)),
            ast_node=func if func.type_params else None,
            decl_node=func
        ))

    def _overload_sig_key(self, param_types, type_params, param_names=None) -> tuple:
        """Normalized signature key for declaration-site overload distinctness
        (design 55 + design 66).

        Each parameter is mangled after (a) folding any bare type parameter of
        this declaration to a single canonical placeholder — so `f<T>(T)` and
        `f<U>(U)` collide — and (b) resolving distinct-type aliases to their
        underlying type — so `type A = Int; f(A)` and `f(Int)` collide.

        Design 66 makes parameter LABELS part of a function's identity: two
        overloads with the same types but DIFFERENT names are distinct (the
        newly-legal `f(a:b:)` vs `f(type:value:)`). So each part carries its
        parameter name alongside the normalized type; a key collision now
        requires same types AND same names at every position. Two declarations
        with equal keys are indistinguishable and rejected.
        """
        from codegen.mangle import mangle_type
        tp_names = {tp.name for tp in (type_params or [])}
        names = list(param_names) if param_names is not None else []
        parts = []
        for i, t in enumerate(param_types or []):
            nm = names[i] if i < len(names) else None
            if t is None:
                parts.append(("Void", nm))
                continue
            if t.kind == TypeKind.TYPE_PARAM:
                parts.append(("$P", nm))
                continue
            if t.kind == TypeKind.STRUCT and t.struct_name in tp_names:
                parts.append(("$P", nm))
                continue
            norm = t
            if t.kind == TypeKind.STRUCT and self.get_type_alias_info(t.struct_name):
                norm = self._resolve_type_alias(t)
            parts.append((mangle_type(norm), nm))
        return tuple(parts)

    def _check_trailing_defaults(self, parameters, line, column, what):
        """Design 53: a defaulted parameter must be TRAILING — no parameter
        without a default may follow one that has a default. `self` is not a
        real value parameter for this rule."""
        seen_default = False
        for p in parameters:
            if p.name == "self":
                continue
            if p.default_value is not None:
                seen_default = True
            elif seen_default:
                self._error(
                    ErrorKind.SYNTAX,
                    f"{what}: parameter `{p.name}` has no default value but "
                    f"follows a parameter that does — defaulted parameters must "
                    f"be trailing",
                    line, column,
                    hint="move all defaulted parameters to the end of the "
                         "parameter list"
                )
                return

    def _overload_shape_keys(self, param_types, type_params, default_values,
                             param_names=None):
        """Design 53 + 66: the set of reachable call-SHAPE keys for a declaration.

        A declaration with trailing defaults can be called at several arities —
        from the count of required (non-defaulted) parameters up to the full
        arity. Each reachable arity is normalized with `_overload_sig_key` over
        that many leading parameters. A declaration with no defaults yields a
        single key (its full signature). Keys carry parameter LABELS (design 66),
        so a defaulted-arity shape collides with another overload only when the
        types AND names match at every position of that shape.
        """
        pts = list(param_types or [])
        names = list(param_names) if param_names is not None else []
        n = len(pts)
        if default_values and any(dv is not None for dv in default_values):
            required = sum(1 for dv in default_values if dv is None)
        else:
            required = n
        keys = set()
        for arity in range(required, n + 1):
            keys.add(self._overload_sig_key(pts[:arity], type_params,
                                            names[:arity]))
        return keys

    @staticmethod
    def _module_symbol_tag(module: Tuple[str, ...]) -> str:
        """A defining module rendered for an LLVM symbol name: identifier-safe,
        stable, and distinct per module (`("<std>", "data")` -> `std_data`).

        Design 144 shares this rendering for type identities, so the two
        module-qualification schemes agree on how a module is spelled in a
        symbol; it lives in `type_identity` and is re-exported here."""
        from type_identity import module_tag
        return module_tag(module)

    def _stamp_type_identity(self, decl) -> str:
        """The design-144 identity of type declaration `decl`, stamped on it.

        Idempotent: the front half re-enters on the same AST (place lowering,
        the coroutine transform), and re-qualifying an identity would produce
        `Header$m$dep$m$dep`. Same shape as DF-146a's `_derivation_slot`."""
        from type_identity import type_identity
        existing = getattr(decl, 'type_identity', "")
        if existing:
            return existing
        module = self._vis_module_for_source(getattr(decl, 'source_file', None))
        identity = type_identity(decl.name, module)
        decl.type_identity = identity
        return identity

    # ------------------------------------------------------------------ #
    # Module-local codegen identity for PRIVATE top-level declarations
    # (DF-140f, closed under design 142).
    #
    # A module-private declaration is invisible to importers for name
    # resolution — the typechecker resolves against the importing module's own
    # namespace, which never received it. Codegen, though, works from ONE merged
    # namespace keyed by simple name, so two modules that each declare a private
    # `PT_LOAD` (or a private `helper()`) used to land on one key. That was
    # reported to the author as "ambiguous static `PT_LOAD`", making every
    # private constant in a dependency a reserved word for every consumer.
    #
    # A private declaration cannot be named from outside, so its codegen symbol
    # need not be — module-qualifying it makes the two definitions genuinely
    # distinct and the ambiguity disappears. Only NON-ROOT modules are qualified,
    # so single-file programs keep byte-identical IR.
    # ------------------------------------------------------------------ #
    def _module_private_symbol(self, base: str, def_module: Tuple[str, ...],
                               visibility: Visibility) -> Optional[str]:
        """The module-qualified codegen symbol for a private declaration, or
        None when the declaration keeps its plain name (public — importable by
        simple name, so a genuine cross-module clash is a real ambiguity — or
        root-module, where there is nothing to distinguish it from)."""
        if visibility != Visibility.PRIVATE or not def_module:
            return None
        return f"{base}$m${self._module_symbol_tag(def_module)}"

    def _stamp_module_private_functions(self):
        """Give this module's private free functions a module-local codegen
        symbol. Runs per module, and only over declarations this module OWNS —
        an imported symbol is the SAME object as the source module's, so
        stamping it here would rename the definition out from under its owner."""
        own_module = self._vis_module_for_source(None)
        for name, overloads in self.namespace.function_overloads.items():
            if len(overloads) != 1:
                # An overload set already carries signature-mangled symbols; a
                # cross-module private clash inside one is out of scope here.
                continue
            sym = overloads[0]
            if sym.mangled_name or sym.decl_node is None:
                continue
            if sym.type_params:
                # A generic's symbol is the template base its monomorphizations
                # are named from; leave that naming alone.
                continue
            if (getattr(sym, 'def_module', ()) or ()) != own_module:
                continue
            mangled = self._module_private_symbol(
                name, own_module, getattr(sym, 'visibility', Visibility.PRIVATE))
            if mangled is None:
                continue
            sym.mangled_name = mangled
            sym.decl_node.mangled_symbol = mangled

    def _stamp_overload_symbols(self):
        """Assign each member of a 2+ overload set a type-signature-suffixed
        codegen symbol (design 55), stamping both the FunctionSymbol and its
        declaring AST node so the typechecker (call resolution) and codegen
        (definition emission) agree. Single-declaration names are untouched and
        keep their plain symbol. Generic overloads keep their type-argument
        instantiation naming and are left plain here.
        """
        from codegen.mangle import mangle_overload, mangle_method, mangle_type

        def _type_sig(param_types):
            return tuple(mangle_type(p) if p is not None else "Void"
                         for p in param_types)

        for name, overloads in self.namespace.function_overloads.items():
            if len(overloads) < 2:
                continue
            # Design 66: within a set, members that share a parameter-TYPE
            # signature (now legal when their labels differ) need their labels
            # appended to stay distinct; type-unique members keep design-55 symbols.
            sig_counts = {}
            for sym in overloads:
                if sym.type_params:
                    continue
                sig_counts[_type_sig(sym.param_types)] = \
                    sig_counts.get(_type_sig(sym.param_types), 0) + 1
            for sym in overloads:
                if sym.type_params:
                    continue
                need_labels = sig_counts.get(_type_sig(sym.param_types), 0) > 1
                mangled = mangle_overload(
                    name, sym.param_types,
                    sym.param_names if need_labels else None)
                sym.mangled_name = mangled
                if sym.decl_node is not None:
                    sym.decl_node.mangled_symbol = mangled
            # Design 105: two or more GENERIC overloads of one name would both
            # monomorphize to `name$<args>` and collide in codegen. Give each a
            # distinct `$OL$`-tagged base (its declared param-type signature, which
            # includes the type params) so its instantiations are `base$<args>` —
            # collision-free. A lone generic in the set keeps its plain name
            # (the byte-identical single-template path), so this is inert for all
            # existing code (no std/blade/libs set has 2+ generic overloads).
            generic_syms = [s for s in overloads if s.type_params]
            if len(generic_syms) >= 2:
                gsig_counts = {}
                for sym in generic_syms:
                    gsig_counts[_type_sig(sym.param_types)] = \
                        gsig_counts.get(_type_sig(sym.param_types), 0) + 1
                for sym in generic_syms:
                    # Design 66: generic overloads that share a param-TYPE sig
                    # (differ only by label) need their labels appended too.
                    need_labels = gsig_counts.get(_type_sig(sym.param_types), 0) > 1
                    mangled = mangle_overload(
                        name, sym.param_types,
                        sym.param_names if need_labels else None)
                    sym.mangled_name = mangled
                    if sym.decl_node is not None:
                        sym.decl_node.mangled_symbol = mangled
        for struct_name, struct_sym in self.namespace.structs.items():
            for mname, overloads in struct_sym.method_overloads.items():
                if len(overloads) < 2:
                    continue
                base = mangle_method(struct_name, mname)
                sig_counts = {}
                for sym in overloads:
                    if sym.type_params:
                        continue
                    offset = 0 if sym.is_init else 1
                    sig_counts[_type_sig(sym.param_types[offset:])] = \
                        sig_counts.get(_type_sig(sym.param_types[offset:]), 0) + 1
                for sym in overloads:
                    if sym.type_params:
                        continue
                    offset = 0 if sym.is_init else 1
                    tsig = _type_sig(sym.param_types[offset:])
                    need_labels = sig_counts.get(tsig, 0) > 1
                    mangled = mangle_overload(
                        base, sym.param_types[offset:],
                        sym.param_names[offset:] if need_labels else None)
                    sym.mangled_name = mangled
                    if sym.decl_node is not None:
                        sym.decl_node.mangled_symbol = mangled
                # Design 142: two modules may each extend one type with the same
                # method name and the SAME signature — legal declarations that
                # only a call site seeing both can complain about. Their
                # signature manglings are identical, so discriminate the codegen
                # symbols by defining module; otherwise the two definitions
                # collide in the LLVM symbol table before anyone calls either.
                by_symbol: Dict[str, List] = {}
                for sym in overloads:
                    if sym.mangled_name:
                        by_symbol.setdefault(sym.mangled_name, []).append(sym)
                for shared, clashing in by_symbol.items():
                    if len(clashing) < 2:
                        continue
                    for sym in clashing:
                        tag = self._module_symbol_tag(
                            getattr(sym, 'def_module', ()) or ())
                        sym.mangled_name = f"{shared}$M${tag}"
                        if sym.decl_node is not None:
                            sym.decl_node.mangled_symbol = sym.mangled_name

    def _reject_builtin_redefinition(self, decl, what: str) -> bool:
        """Report (and refuse to register) a user declaration whose name the
        compiler intercepts at every call site. Returns True when rejected.

        std and builtin.saw are exempt: they own these names, and
        `std.task.yield_now` is deliberately a wrapper over the intrinsic of the
        same name.
        """
        name = getattr(decl, 'name', None)
        if name not in BUILTIN_CALL_NAMES:
            return False
        source = getattr(decl, 'source_file', None)
        if self._vis_module_for_source(source)[:1] == ("<std>",):
            return False
        self._error(
            ErrorKind.DUPLICATE_FUNCTION,
            f"`{name}` is a compiler built-in and cannot be redefined",
            decl.line, decl.column, source_file=source,
            hint=f"every `{name}(...)` call resolves to the built-in, so this "
                 f"{what} could never be called — give it a different name"
        )
        return True

    def _register_extern_function(self, extern_func):
        """Register an external (FFI) function signature."""
        # Design 122 unit D: an extern declaration of an intercepted name is
        # unreachable for the same reason a Saw one is (this is how an
        # `extern "C" { blocking func sleep(...) }` silently lost to the
        # built-in and produced a confusing type error two lines away).
        if self._reject_builtin_redefinition(extern_func, "declaration"):
            return

        # Resolve types for extern functions
        param_types = [self._resolve_type(p.type) for p in extern_func.parameters]
        param_names = [p.name for p in extern_func.parameters]
        resolved_return_type = self._resolve_type(extern_func.return_type)

        # design 76 (A6): `extern blocking func` needs the hosted offload pool.
        # The freestanding profile has no threads/pool — reject it cleanly.
        if getattr(extern_func, 'is_blocking', False) and self.freestanding:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`extern blocking func {extern_func.name}` is not available in the "
                f"freestanding profile: blocking-call offload needs the hosted "
                f"thread pool, which the freestanding runtime does not provide",
                extern_func.line, extern_func.column,
                hint="drop `blocking` (an unannotated extern promises promptness) "
                     "or gate this module out of the freestanding build",
            )
            return

        existing = self.get_function_info(extern_func.name)
        if existing is not None:
            # Allow duplicate extern declarations with the same signature
            # This enables library code (like std/) to declare externs that
            # user code may also declare
            if (existing.param_types == param_types and
                existing.return_type == resolved_return_type):
                return  # Same signature, allow it
            self._error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"function `{extern_func.name}` is defined multiple times with different signatures",
                extern_func.line, extern_func.column
            )
            return

        self.namespace.register_function(extern_func.name, FunctionSymbol(
            param_types=param_types,
            param_names=param_names,
            return_type=resolved_return_type,
            is_variadic=extern_func.is_variadic,
            is_blocking=getattr(extern_func, 'is_blocking', False)
        ))

    def _register_static(self, static: StaticDecl):
        """Register and validate a module-level `static` declaration (design 41).

        Enforces the ratified statics semantics (design 19 open-questions block):
        the initializer must be a compile-time constant, the type must be `Sync`,
        and the type must not be `Deinit` (statics are immortal — never run
        deinit). There is no `static mut`; the no-mutation rule is enforced at
        assignment / `&var` lend sites, not here.
        """
        # DF-140h: the duplicate check is asked from the DECLARING module, so it
        # sees that module's own statics and the shared (public/root) ones —
        # never another module's private constants. Before this, every private
        # `static` in std reserved its simple name for every Saw program:
        # declaring `ASCII_ZERO`, `SEEK_SET` or `AF_UNIX` in a hello-world was
        # "defined multiple times" against a std internal the author cannot see,
        # name, or even find.
        def_module = self._vis_module_for_source(
            getattr(static, 'source_file', None))
        if self.namespace.has_static(static.name, def_module):
            self._error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"static `{static.name}` is defined multiple times",
                static.line, static.column, source_file=static.source_file
            )
            return

        resolved_type = self._resolve_type(static.type)

        # design 46: `UnsafeMemory<T, Use>` statics — validate the intent marker
        # is present and explicit (`Device`/`Normal`).
        if self._is_unsafe_memory(resolved_type):
            self._validate_unsafe_memory_type(resolved_type, static.line, static.column)

        # Const-init only. A bare declaration (no initializer) is a zero-init,
        # permitted only for POD / fixed-array statics (design 41 item 2: no
        # repeat-literal exists, so bare zero-init is the chosen mechanism for
        # large zero regions like slab buffers).
        if static.initializer is None:
            if not self._is_zero_initable_type(resolved_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"static `{static.name}` needs an initializer: only POD and "
                    f"fixed-array statics may be declared without one (zero-init)",
                    static.line, static.column, source_file=static.source_file,
                    hint="add `= <constant>`, or use a POD / `[T; N]` type for a "
                         "bare zero-initialized static"
                )
        else:
            # Type-check the initializer in a fresh empty scope (a static's
            # initializer can reference no locals) so its expressions are
            # annotated (resolved_type, is_atomic_construct) for codegen, and so
            # the const-init walk sees checked nodes.
            saved_scope = self.current_scope
            self.current_scope = type(saved_scope)()
            # DF-140a: a static initializer takes the SAME literal treatment as
            # every other typed slot — adopt the declared type and range-check at
            # the literal, BEFORE checking it. Statics were skipping this
            # entirely, so `static B: UInt8 = 256` compiled clean while the `let`
            # spelling of it was a clean error, and (with DF-137d) a riscv32
            # `static BASE: Int = 0x80000000` wrapped negative in silence.
            self._apply_literal_expected_type(static.initializer, resolved_type)
            init_type = self._check_expression(static.initializer)
            self.current_scope = saved_scope
            if init_type is not None and not self._types_compatible(resolved_type, init_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"static `{static.name}` has type `{resolved_type}` but its "
                    f"initializer has type `{init_type}`",
                    static.line, static.column, source_file=static.source_file
                )
            if not self._is_const_init(static.initializer):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"static `{static.name}` must be initialized by a compile-time "
                    f"constant",
                    static.line, static.column, source_file=static.source_file,
                    hint="statics allow only literals, POD struct literals with "
                         "constant fields, constant fixed-array literals, and "
                         "`Atomic(<int>)`; function calls, String, and heap types "
                         "are not const-initializable"
                )

        # Sync-only: a static is reachable from every task, so its type must be
        # Sync (design 21 structural derivation).
        if not self.namespace.is_sync(resolved_type):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"static `{static.name}` has non-Sync type `{resolved_type}`; "
                f"statics must be Sync (shared across all tasks)",
                static.line, static.column, source_file=static.source_file,
                hint="use a Sync type — mutation of global state flows only "
                     "through interior-synchronized types like `Atomic<Int>`"
            )

        # Immortal: statics never run deinit. Const-init already excludes Deinit
        # types in practice (String/heap types are not const-initializable); this
        # asserts it rather than building deinit glue for globals.
        if self._is_deinit_type(resolved_type):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"static `{static.name}` has type `{resolved_type}`, which owns a "
                f"resource (Deinit); statics are immortal and never run deinit",
                static.line, static.column, source_file=static.source_file
            )

        static.type = resolved_type  # record resolved type for codegen
        # DF-140f: a PRIVATE static in a non-root module takes a module-local
        # LLVM global name. Nothing outside its module can name it, so nothing
        # outside needs to agree on the symbol — and two dependencies that both
        # declare `PT_LOAD` stop colliding in the merged codegen namespace.
        # `static_globals` is keyed by this name, and the reference sites read
        # the symbol the typechecker stamped on the identifier.
        visibility = getattr(static, 'visibility', Visibility.PRIVATE)
        mangled = self._module_private_symbol(
            f"saw.static.{static.name}", def_module,
            visibility) or f"saw.static.{static.name}"
        static.mangled_symbol = mangled
        self.namespace.register_static(static.name, StaticSymbol(
            type=resolved_type,
            mangled_name=mangled,
            visibility=visibility,
            line=static.line,
            column=static.column,
            def_module=def_module
        ))

    def _is_zero_initable_type(self, t: SawType) -> bool:
        """Whether a bare (initializer-less) static of type `t` is allowed —
        i.e. `t` is POD (trivially copyable) or a fixed array of a POD element."""
        if t is None:
            return False
        if t.kind == TypeKind.ARRAY:
            return t.array_element_type is not None and \
                self._is_zero_initable_type(t.array_element_type)
        return self.namespace.is_trivially_copyable(t)

    def _is_const_init(self, expr) -> bool:
        """Whether `expr` is a compile-time constant static initializer
        (design 41 item 2): literals, a negated numeric literal, POD struct
        literals with constant fields, constant fixed-array literals, and the
        compiler-known `Atomic(<int>)` construction."""
        if isinstance(expr, (IntLiteral, FloatLiteral, BoolLiteral)):
            return True
        # A resolved `#line` literal (design 98) is an Int compile-time constant
        # — const-init-able like any Int literal. `#file`/`#function` are Strings,
        # which are not const-init-able (same as a plain String literal in a
        # static: rejected).
        if isinstance(expr, SourceLocationLiteral):
            return getattr(expr, 'resolved_kind', None) == 'int'
        if isinstance(expr, UnaryOp) and expr.op == '-':
            return isinstance(expr.operand, (IntLiteral, FloatLiteral))
        if isinstance(expr, ArrayLiteral):
            # A repeat literal `[v; N]` holds its single value in `elements`, and
            # its count is a compile-time constant by construction (design 148),
            # so the same test decides both forms: constant elements, constant
            # array. `static BUF: [Int8; 4096] = [0; 4096]` is the point.
            return all(self._is_const_init(e) for e in expr.elements)
        if isinstance(expr, StructInit):
            return all(self._is_const_init(v) for _n, v in expr.field_inits)
        if isinstance(expr, FunctionCall) and getattr(expr, 'is_atomic_construct', False):
            return all(self._is_const_init(a.value) for a in expr.arguments)
        # design 46: `UnsafeMemory(<int>)` is a const-init from an address literal.
        if isinstance(expr, FunctionCall) and getattr(expr, 'is_unsafe_mem_construct', False):
            return all(self._is_const_init(a.value) for a in expr.arguments)
        return False

    # Built-in type names that indicate specialization when used in extension type params
    BUILTIN_TYPE_NAMES = {
        'Int', 'UInt', 'Float', 'Bool', 'String',
        'Int8', 'Int16', 'Int32', 'Int64',
        'UInt8', 'UInt16', 'UInt32', 'UInt64',
    }

    # Primitive types that carry method extensions (design 57): the pseudo-struct
    # name maps to the primitive SawType used for `self`.
    PRIMITIVE_EXT_SELF_KINDS = {
        'String': TypeKind.STRING,
        'Int': TypeKind.INT,
        'Float': TypeKind.FLOAT,
    }

    def _primitive_ext_self_type(self, name):
        """The `self` SawType for a method in an extension on a primitive
        pseudo-struct (String/Int/Float), or None for an ordinary struct."""
        kind = self.PRIMITIVE_EXT_SELF_KINDS.get(name)
        return SawType(kind) if kind is not None else None

    def _ext_self_type(self, name: str, type_args=None) -> SawType:
        """The `self` SawType for a method in `extension <name>` — a primitive
        pseudo-struct, an ENUM (design 145), or an ordinary struct.

        Getting the KIND right here is what makes `match self` work inside an
        enum method: a STRUCT-kinded `self` would carry no variants.

        A generic enum's self stays ARGUMENT-FREE here, matching the struct
        path: naming the enum's own type params as arguments makes the payload
        binding in `case Just(v)` and a `T` parameter resolve through different
        routes to two `T`s that do not unify. Codegen names the concrete
        monomorphization from `self_type_context` instead."""
        prim = self._primitive_ext_self_type(name)
        if prim is not None:
            return prim
        if self.namespace.has_enum(name) and not self.namespace.has_struct(name):
            return SawType(TypeKind.ENUM, enum_name=name, type_args=type_args)
        return SawType(TypeKind.STRUCT, struct_name=name)

    def _is_known_type(self, name: str) -> bool:
        """Check if a name refers to a known type (built-in or user-defined)."""
        return (name in self.BUILTIN_TYPE_NAMES or
                self.namespace.has_struct(name) or
                self.namespace.has_enum(name) or
                self.get_type_alias_info(name) is not None)

    def _get_specialization_key(self, extension: Extension) -> tuple:
        """Check if extension is a specialization and return the type args key.

        Returns tuple of type arg names if specialized (e.g., ("String",)),
        or empty tuple if it's a generic extension.
        """
        if not extension.type_params:
            return ()

        # Check if any type param is actually a known type (specialization)
        type_args = []
        for tp in extension.type_params:
            if self._is_known_type(tp.name):
                type_args.append(tp.name)
            else:
                # If any param is NOT a known type, this is a generic extension
                return ()

        # Design 37: pad omitted trailing parameters with the struct's declared
        # defaults so `extension Vector<String>` keys as `("String", "GlobalAllocator")`,
        # matching a lookup on the fully-applied `Vector<String, Global>`.
        struct_info = self.get_struct_info(extension.struct_name)
        params = getattr(struct_info, 'type_params', None) if struct_info else None
        if params and len(type_args) < len(params):
            for i in range(len(type_args), len(params)):
                default = getattr(params[i], 'default', None)
                if (default is None or default.kind != TypeKind.STRUCT
                        or default.struct_name is None):
                    break
                type_args.append(default.struct_name)

        return tuple(type_args)

    # Traits an enum may opt into with an empty extension body: the compiler
    # synthesizes the operation inline (payload-deep `==` for Equatable, design
    # 32; lexicographic `compare`/field-streaming `hash`, design 48). Each maps
    # to the `_derived_*_types` set codegen consults.
    _ENUM_DERIVABLE_TRAITS = ("Equatable", "Comparable", "Hashable")

    # design 139: the copy policies an enum may DECLARE, giving enums the same
    # struct parity designs 9/128/131 built up. `NoCopy` is a bare marker — it
    # adds no method, so it needs no `@synthesize`. The two copying policies
    # derive a payload-deep `copy` and are gated on the marker exactly as the
    # struct path gates its memberwise one.
    _ENUM_POLICY_TRAITS = ("NoCopy", "ImplicitCopy", "ExplicitCopy")

    def _is_enum_derivable_optin(self, extension: Extension) -> bool:
        """Whether this enum extension is one of the EMPTY opt-in conformances
        the compiler synthesizes inline (designs 32/48/139) rather than an
        ordinary method-carrying extension (design 145).

        The shape is exact: one conformance, from the derivable/policy set, no
        methods and no type assignments. Anything else — a hand-written body for
        the same trait included — is an ordinary extension now."""
        confs = extension.conformances
        supported = self._ENUM_DERIVABLE_TRAITS + self._ENUM_POLICY_TRAITS
        return (len(confs) == 1 and confs[0] in supported
                and not extension.methods and not extension.type_assignments)

    def _reject_enum_inits(self, extension: Extension) -> bool:
        """Reject an `init` in an enum extension (design 145 unit B).

        An enum's CASES are its constructors, so there is nothing an `init`
        could construct that a case does not already name. Returns True when it
        reported (and registration should stop)."""
        reported = False
        for method in extension.methods:
            if not method.is_init:
                continue
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"enum `{extension.struct_name}` cannot declare an `init`: an "
                f"enum's cases are its constructors",
                method.line, method.column,
                hint=f"construct it by naming a case "
                     f"(`{extension.struct_name}.SomeCase`), or add a static "
                     f"method returning `{extension.struct_name}` if it needs "
                     f"to compute which case to build",
                source_file=getattr(extension, 'source_file', None)
            )
            reported = True
        return reported

    def _register_enum_derivable_extension(self, extension: Extension):
        """Register an empty opt-in extension on an enum: a derivable trait
        (designs 32 / 48) or a copy policy (design 139).

        This is the path for a conformance whose body the compiler synthesizes
        INLINE over the active variant — it registers the conformance and
        records the enum in the matching `_derived_*` set, minting no method
        symbol. Method-carrying extensions on enums (design 145) go through the
        ordinary struct-shaped registration instead.
        """
        trait = extension.conformances[0]
        enum_name = extension.struct_name
        if trait in self._ENUM_POLICY_TRAITS:
            self._register_enum_copy_policy(extension, trait)
            return
        # Same gate as the struct path (design 128): an enum's payload-deep body
        # is derived only when the author asks for it.
        self._demand_synthesize_marker(
            extension, trait,
            {"Equatable": "equals", "Comparable": "compare"}.get(trait, "hash"))
        self.namespace.register_conformance(enum_name, trait)
        if trait == "Equatable":
            self._derived_equals_types.add(enum_name)
        elif trait == "Comparable":
            self._derived_compare_types.add(enum_name)
            self._comparable_types.add(enum_name)
        elif trait == "Hashable":
            self._derived_hash_types.add(enum_name)
            self._hashable_types.add(enum_name)

    def _register_enum_copy_policy(self, extension: Extension, trait: str):
        """Register a declared copy policy on an enum (design 139).

        Structs have had to name their transfer class since design 9; enums got
        it inferred from their payloads instead, which meant an author could not
        SAY that an owning enum was move-only and the compiler could not hold
        them to it. Declaring the policy is now how an owning enum is written,
        and `_check_enum_policy_declared` refuses a bare one.

        `ImplicitCopy` and `ExplicitCopy` derive a payload-deep `copy` — None of
        the enum's business to write, since the active variant is chosen at
        runtime — so both take the `@synthesize` marker. `NoCopy` adds nothing
        to derive and takes none, matching `extension Holder: NoCopy {}`.
        """
        enum_name = extension.struct_name
        if trait != "NoCopy":
            self._demand_synthesize_marker(extension, trait, "copy")
            self._derived_copy_enums.add(enum_name)
        self.namespace.register_conformance(enum_name, trait)

    def _trait_and_ancestors(self, trait_name: str):
        """Yield `trait_name` and all its ancestor traits (transitive parents),
        de-duplicated, most-derived first. Used to gather inherited default
        method bodies (design 56)."""
        seen = []
        stack = [trait_name]
        while stack:
            name = stack.pop(0)
            if name in seen:
                continue
            info = self.get_trait_info(name)
            if info is None:
                continue
            seen.append(name)
            for parent in getattr(info, 'parent_traits', []) or []:
                if parent not in seen:
                    stack.append(parent)
        return seen

    def _synthesize_trait_defaults(self, extension: Extension, struct_info):
        """Synthesize per-conformer Methods for trait default bodies (design 56).

        For each conformed trait (and its ancestors), a default-bodied method the
        conformer neither provides in THIS extension nor already carries (from a
        sibling extension — e.g. the split `: Printable` + `: Error` spelling) is
        materialized as a fresh Method whose body is a deep copy of the default.
        The copy is taken pre-typecheck (the parsed body has no resolved_type /
        symbol annotations yet), so each conformer typechecks its own copy with
        Self bound to the concrete type.
        """
        provided = {m.name for m in extension.methods if not m.is_init}
        already = set(getattr(struct_info, 'methods', {}) or {})
        for trait_name in extension.conformances:
            # Skip module-qualified names for default synthesis (rare; the
            # conformance check still applies). Marker traits carry no methods.
            if '.' in trait_name:
                continue
            for tname in self._trait_and_ancestors(trait_name):
                trait_info = self.get_trait_info(tname)
                if trait_info is None:
                    continue
                for mname, tmsym in trait_info.methods.items():
                    if mname in provided or mname in already:
                        continue
                    tm_ast = getattr(tmsym, 'ast_node', None)
                    if tm_ast is None or getattr(tm_ast, 'body', None) is None:
                        continue  # required method (no default) — real conformance check reports it
                    synth = Method(
                        name=mname,
                        parameters=copy.deepcopy(tm_ast.parameters),
                        return_type=copy.deepcopy(tm_ast.return_type),
                        body=copy.deepcopy(tm_ast.body),
                        is_init=False,
                        self_mutable=tm_ast.self_mutable,
                        self_is_reference=tm_ast.self_is_reference,
                        is_static=False,
                        is_sync=getattr(tm_ast, 'is_sync', False),
                        is_unsafe=getattr(tm_ast, 'is_unsafe', False),
                        type_params=[],
                        line=extension.line,
                        column=extension.column,
                        source_file=getattr(extension, 'source_file', None),
                    )
                    extension.methods.append(synth)
                    provided.add(mname)

    # Traits whose contract includes destruction: `Deinit` itself, and the three
    # copy policies that inherit from it. Declaring any of them obliges the type
    # to have a `deinit` — which, since design 128, the compiler supplies.
    _RESOURCE_TRAITS = ("Deinit", "NoCopy", "ImplicitCopy", "ExplicitCopy")

    def _synthesize_implicit_deinits(self, program: Program):
        """Give every resource-conforming type without a hand-written `deinit` a
        synthesized structural one (design 128).

        Destruction is the one part of the resource contract the compiler always
        knows how to write: drop each owning field, in reverse declaration order.
        So `extension Holder: NoCopy {}` no longer has to carry a transcribed
        `func deinit(&var self) {}` whose only job is to let codegen append that
        drop glue.

        The synthesized method is an ordinary `deinit` with an EMPTY body. That
        is the whole implementation: codegen already appends the memberwise
        field cleanup after a `deinit` body (design 17), so an empty body lowers
        to exactly the structural drop, and there is no second destruction path
        to keep in step.

        Runs as a pre-pass over the whole program so it is declaration-order
        independent: a type whose `deinit` lives in a sibling extension (std's
        `Vector`, whose body is on the unconditional extension while its policy
        conformance is bounded) is already covered and gets nothing. A type that
        hand-writes `deinit` always wins — there is never both.
        """
        have_deinit = {
            ext.struct_name for ext in program.extensions
            if any(not m.is_init and m.name == "deinit" for m in ext.methods)
        }
        for ext in program.extensions:
            if ext.struct_name in have_deinit:
                continue
            if not any(t in self._RESOURCE_TRAITS for t in ext.conformances):
                continue
            # An ENUM is destroyed structurally, by the tag-switch glue codegen
            # emits (`_emit_enum_cleanup_at`), not through a `deinit` method —
            # and `_emit_drop_at` prefers a method when one exists, RETURNING
            # before it reaches that glue. Synthesizing an empty `deinit` here
            # would therefore replace the payload cleanup with nothing and leak
            # the active variant. Enums could not declare a resource trait at all
            # until design 139, so this loop never met one before.
            if self.get_enum_info(ext.struct_name) is not None:
                continue
            ext.methods.append(Method(
                name="deinit",
                parameters=[Parameter(name="self", type=SawType(TypeKind.VOID),
                                      is_reference=True,
                                      reference_mutable=True)],
                return_type=SawType(TypeKind.VOID),
                body=Block(statements=[], final_expr=None,
                           line=ext.line, column=ext.column),
                self_mutable=True,
                self_is_reference=True,
                # Never a documented API surface: `deinit` is called by the
                # compiler, never by a user, so it stays out of `--emit-docs`
                # and off the design-80 member gate.
                is_synthesized=True,
                line=ext.line,
                column=ext.column,
                source_file=getattr(ext, 'source_file', None) or "",
            ))
            have_deinit.add(ext.struct_name)

    def _demand_synthesize_marker(self, extension: Extension, trait: str,
                                  method_name: str) -> None:
        """Require `@synthesize` on a declared conformance that would otherwise
        derive `method_name` from an empty body (design 128).

        One rule across every synthesizable trait: writing the conformance means
        the body is yours unless you explicitly ask the compiler for it. The
        marker is the author's acknowledgment that a memberwise body is being
        generated over whatever fields the type happens to have — so adding a
        field silently changes `==`, `compare`, `hash` or `copy`, and that should
        be something they opted into.

        AUTO-conformance is untouched: a POD struct and a payload-free enum still
        conform to Equatable/Hashable with no declaration, hence no marker.

        Reports and returns; the caller synthesizes anyway, so one missing marker
        surfaces as exactly one error rather than also tripping the downstream
        "does not implement required method" conformance check.
        """
        if has_synthesize(extension):
            return
        self._error(
            ErrorKind.TYPE_MISMATCH,
            f"`{extension.struct_name}` declares `{trait}` with no "
            f"`{method_name}`: a derived body must be requested explicitly",
            extension.line, extension.column,
            hint=f"mark the extension `@synthesize` to derive `{method_name}` "
                 f"memberwise, or write `{method_name}` by hand",
            source_file=getattr(extension, 'source_file', None)
        )

    def _reject_deinit_conformance(self, extension: Extension) -> bool:
        """design 131: `Deinit` is NON-DECLARABLE. Report and return True if this
        extension declares it.

        `Deinit` is still a real trait — the base of the policy hierarchy, and
        legal as a generic BOUND (`T: Deinit`). What is gone is the standalone
        CONFORMANCE form, because a type that declares only `Deinit` matched no
        arm of the value-transfer checkpoint: the compiler knew how to destroy it
        but nothing said whether it could be duplicated, so `let s = r` took the
        default bitwise path and both copies ran `deinit` (DF-128a). Requiring a
        copy policy makes that state unreachable rather than diagnosed.

        A hand-written `deinit` body lives inside the policy conformance
        (`extension Res: NoCopy { func deinit(&var self) {...} }`) — the
        requirement is inherited, so nothing else about design 128's synthesis or
        prefix-hook semantics changes.
        """
        if "Deinit" not in extension.conformances:
            return False
        name = extension.struct_name
        self._error(
            ErrorKind.CANNOT_COPY,
            f"`{name}` declares a deinit but no copy policy",
            extension.line, extension.column,
            hint=f"declare one of `extension {name}: NoCopy {{}}` (move-only), "
                 f"`ExplicitCopy`, or `ImplicitCopy`, and put the `deinit` body "
                 f"inside it — every copy policy already requires `Deinit`",
            source_file=getattr(extension, 'source_file', None)
        )
        return True

    # Traits the compiler derives structurally and never accepts as a written
    # conformance — rejected on their own terms elsewhere, so the orphan rule
    # stays out of their diagnostics.
    _STRUCTURAL_MARKER_TRAITS = frozenset({"Send", "Sync", "Deinit"})

    def _check_conformance_coherence(self, extension: Extension) -> bool:
        """The ORPHAN RULE (design 142): `extension T: Trait` is declarable only
        in the module that defines `T` or the module that defines `Trait`.
        Returns True if a violation was reported.

        Method scoping could be made import-relative because a method is chosen
        at a call site, where "which ones can I see" is a fair question. A
        conformance cannot: it mints a per-(type, trait) vtable and backs a
        semantic contract, so two import-scoped conformances of one pair would
        let a `Map` built in one module and probed in another disagree about
        hashing — an incoherence no use-site error can catch, because neither
        site is wrong. Pinning conformances to an owner makes them global, which
        is also why they need no import scoping of their own.
        """
        if not extension.conformances:
            return False
        if getattr(extension, 'is_synthesized', False):
            return False
        ext_module = self._vis_module_for_source(
            getattr(extension, 'source_file', None))
        type_name = extension.struct_name
        type_sym = (self.namespace.lookup_struct(type_name)
                    or self.namespace.lookup_enum(type_name))
        type_module = getattr(type_sym, 'def_module', None) if type_sym else None
        if type_module is not None and type_module == ext_module:
            return False

        reported = False
        for trait_name in extension.conformances:
            simple = trait_name.rsplit('.', 1)[-1]
            if simple in self._STRUCTURAL_MARKER_TRAITS:
                continue
            trait_sym = self.get_trait_info(simple)
            if trait_sym is None:
                continue  # unknown trait — reported by the conformance loop
            trait_module = getattr(trait_sym, 'def_module', ()) or ()
            if trait_module == ext_module:
                continue

            owner_hint = []
            if type_module is not None:
                owner_hint.append(
                    f"`{self._module_label(type_module)}` (which defines "
                    f"`{type_name}`)")
            if trait_module:
                owner_hint.append(
                    f"`{self._module_label(trait_module)}` (which defines "
                    f"`{simple}`)")
            where = " or ".join(owner_hint) if owner_hint else "the owning module"
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{type_name}` cannot be conformed to `{simple}` here: this "
                f"module defines neither the type nor the trait",
                extension.line, extension.column,
                hint=f"declare the conformance in {where}. A conformance is "
                     f"program-wide — two modules minting one for the same "
                     f"(type, trait) pair would disagree about what `{simple}` "
                     f"means for `{type_name}`",
                source_file=getattr(extension, 'source_file', None)
            )
            reported = True
        return reported

    @staticmethod
    def _derivation_slot(extension: Extension, name: str, marker: str):
        """`(an author wrote this method, the derivation we already made)`.

        Registration must be IDEMPOTENT (design 146): the front end re-enters
        over an AST it has already registered — the coroutine transform does it
        today and the place transform does it now — and the derivations below
        WRITE their synthesized method back into the extension. A second pass
        that counted its own `copy`/`equals`/`compare`/`hash` as a hand-written
        body would conclude the `@synthesize` marker derives nothing and report
        that at the user, which is what a `@synthesize` type in a program using
        concurrency used to hit. Separating the two answers lets the second pass
        re-derive exactly what the first did, in place, appending nothing.
        """
        author = derived = None
        for m in extension.methods:
            if m.is_init or m.name != name:
                continue
            if getattr(m, marker, False):
                derived = m
            else:
                author = m
        return author is not None, derived

    def _canonicalize_extension_target(self, extension: Extension):
        """Point `extension` at its target type's IDENTITY (design 144).

        `Extension.struct_name` is a type REFERENCE, not a declaration name, so
        it carries the identity on exactly the terms a `SawType` does. That is
        what gives two modules' `Header` extensions two method families rather
        than one, and it makes every `extension.struct_name`-keyed table below
        — the derivation sets, the method registry, `generic_extensions`,
        `mangle_method`'s receiver — inherit the identity without its own edit.
        Trait names in `conformances` are references too. Idempotent, since the
        front half re-enters on the same AST."""
        extension.struct_name = self._canonical_type_name(extension.struct_name)
        extension.type_identity = extension.struct_name
        if extension.conformances:
            extension.conformances = [self._canonical_type_name(c)
                                      for c in extension.conformances]

    def _adopt_const_params(self, extension: Extension, struct_info):
        """Let `extension FixedBuf<N>` know that `N` is a const parameter.

        An extension re-declares the type's parameters positionally and by name,
        and the natural spelling repeats neither the bounds of a type parameter
        nor the `const N: Int` of a value one. Rather than make const generics
        the one case that must be spelled twice, the constness is adopted from
        the declaration — the same way a bounded extension's `T` is understood
        against the struct's `T` (design 148).

        Writing it out (`extension FixedBuf<const N: Int>`) keeps working; a
        parameter that already says `const` is left alone.
        """
        declared = getattr(struct_info, 'type_params', None) or []
        for i, tp in enumerate(extension.type_params or []):
            if getattr(tp, 'is_const', False) or i >= len(declared):
                continue
            src = declared[i]
            if getattr(src, 'is_const', False):
                tp.is_const = True
                tp.const_type = src.const_type
                tp.bounds = []

    def _register_extension(self, extension: Extension):
        """Register methods from an extension."""
        self._canonicalize_extension_target(extension)
        if self._reject_deinit_conformance(extension):
            return
        if self._check_conformance_coherence(extension):
            return
        # Design 145: an extension on an ENUM is an extension on a struct. Only
        # the EMPTY derivable / copy-policy opt-ins (designs 32/48/139) keep
        # their own path — those register no method symbol at all, because the
        # compiler synthesizes the operation inline over the active variant.
        # Everything else — instance methods, static methods, hand-written trait
        # bodies — goes through the shared registration below, with the enum
        # symbol standing in for the struct symbol (it carries the same method
        # tables since design 145).
        enum_info = self.get_enum_info(extension.struct_name)
        is_enum = enum_info is not None
        if is_enum:
            if self._is_enum_derivable_optin(extension):
                self._register_enum_derivable_extension(extension)
                return
            if self._reject_enum_inits(extension):
                return
            struct_info = enum_info
        else:
            # Verify the struct exists (check namespace)
            struct_info = self.get_struct_info(extension.struct_name)
            if struct_info is None:
                self._error(
                    ErrorKind.UNDEFINED_VARIABLE,
                    f"cannot extend undefined struct `{extension.struct_name}`",
                    extension.line, extension.column
                )
                return

        self._adopt_const_params(extension, struct_info)

        # Memberwise `copy()` derivation: a struct declaring ImplicitCopy or
        # ExplicitCopy without a hand-written `copy` gets a compiler-synthesized
        # memberwise copy. We only register its signature here (so conformance
        # passes and callers type-check `.copy()`); the body is skipped by the
        # typechecker and emitted memberwise by codegen, where every field's
        # copy tier is known regardless of declaration order. Structs needing
        # derivation are recorded for a post-registration NoCopy-field check.
        # Every derivation below is gated on `@synthesize` (design 128): the
        # marker is what turns a declared-but-empty conformance into a derived
        # body. `derived_any` records whether the marker did any work, so a
        # `@synthesize` that derives nothing is itself reported.
        derived_any = False
        declared_copy_policy = next(
            (t for t in ("ImplicitCopy", "ExplicitCopy")
             if t in extension.conformances), None)
        declares_copy_policy = declared_copy_policy is not None
        has_copy_method, already_derived = self._derivation_slot(
            extension, "copy", "is_derived_copy")
        if declares_copy_policy and not has_copy_method:
            self._demand_synthesize_marker(extension, declared_copy_policy, "copy")
            derived_any = True
            # Design 145: an ENUM's derivations are synthesized INLINE over the
            # active variant (design 139), not as a memberwise method body, so
            # it records the type and mints no method. A method-carrying enum
            # extension can therefore still ask for a derived `copy` — this is
            # what lets `extension R: NoCopy { func deinit(&var self) {...} }`
            # and a `@synthesize`d policy coexist with hand-written methods.
            if is_enum:
                self._derived_copy_enums.add(extension.struct_name)
            else:
                if already_derived is None:
                    extension.methods.append(Method(
                        name="copy",
                        parameters=[Parameter(name="self",
                                              type=SawType(TypeKind.VOID),
                                              is_reference=True)],
                        return_type=SawType(TypeKind.SELF),
                        body=Block(statements=[], final_expr=None,
                                   line=extension.line, column=extension.column),
                        self_mutable=False,
                        self_is_reference=True,
                        is_derived_copy=True,
                        line=extension.line,
                        column=extension.column,
                    ))
                self._derived_copy_structs.add(extension.struct_name)

        # Memberwise `equals()` synthesis (design 32): a struct declaring
        # Equatable without a hand-written `equals` gets a compiler-synthesized
        # memberwise `==`. Register the signature here so conformance passes and
        # `.equals()` type-checks; the body is skipped by the typechecker and
        # emitted memberwise by codegen. Runs BEFORE the conformance
        # "missing methods" check below, so an empty body does not error.
        declares_equatable = "Equatable" in extension.conformances
        has_equals_method, already_derived = self._derivation_slot(
            extension, "equals", "is_derived_equals")
        if declares_equatable and not has_equals_method:
            self._demand_synthesize_marker(extension, "Equatable", "equals")
            derived_any = True
            if already_derived is None and not is_enum:
                extension.methods.append(Method(
                    name="equals",
                    parameters=[
                        Parameter(name="self", type=SawType(TypeKind.VOID),
                                  is_reference=True),
                        Parameter(name="other", type=SawType(TypeKind.SELF),
                                  is_reference=False),
                    ],
                    return_type=SawType(TypeKind.BOOL),
                    body=Block(statements=[], final_expr=None,
                               line=extension.line, column=extension.column),
                    self_mutable=False,
                    self_is_reference=True,
                    is_derived_equals=True,
                    line=extension.line,
                    column=extension.column,
                ))
            self._derived_equals_types.add(extension.struct_name)

        # Lexicographic `compare()` synthesis (design 48): a struct declaring
        # Comparable without a hand-written `compare` gets a compiler-synthesized
        # field-order compare. Same shape as the equals synthesis above: register
        # the signature so conformance passes, skip the empty body in the
        # typechecker, and emit it lexicographically in codegen. No auto-conform
        # (field order is a semantic choice) — this fires only on an explicit
        # `extension T: Comparable`.
        declares_comparable = "Comparable" in extension.conformances
        has_compare_method, already_derived = self._derivation_slot(
            extension, "compare", "is_derived_compare")
        if declares_comparable:
            self._comparable_types.add(extension.struct_name)
        if declares_comparable and not has_compare_method:
            self._demand_synthesize_marker(extension, "Comparable", "compare")
            derived_any = True
            if already_derived is None and not is_enum:
                extension.methods.append(Method(
                    name="compare",
                    parameters=[
                        Parameter(name="self", type=SawType(TypeKind.VOID),
                                  is_reference=True),
                        Parameter(name="other", type=SawType(TypeKind.SELF),
                                  is_reference=False),
                    ],
                    return_type=SawType(TypeKind.ENUM, enum_name="Ordering"),
                    body=Block(statements=[], final_expr=None,
                               line=extension.line, column=extension.column),
                    self_mutable=False,
                    self_is_reference=True,
                    is_derived_compare=True,
                    line=extension.line,
                    column=extension.column,
                ))
            self._derived_compare_types.add(extension.struct_name)

        # Field-streaming `hash()` synthesis (design 48): a struct declaring
        # Hashable without a hand-written `hash` gets a compiler-synthesized
        # hash that streams exactly the fields `==` compares (the hash/==
        # contract). Trivial (POD) structs auto-conform via is_hashable and need
        # no extension; this handles the opt-in (e.g. a String-bearing struct).
        declares_hashable = "Hashable" in extension.conformances
        has_hash_method, already_derived = self._derivation_slot(
            extension, "hash", "is_derived_hash")
        if declares_hashable:
            self._hashable_types.add(extension.struct_name)
        if declares_hashable and not has_hash_method:
            self._demand_synthesize_marker(extension, "Hashable", "hash")
            derived_any = True
            if already_derived is None and not is_enum:
                extension.methods.append(Method(
                    name="hash",
                    parameters=[
                        Parameter(name="self", type=SawType(TypeKind.VOID),
                                  is_reference=True),
                        Parameter(name="h", type=SawType(
                            TypeKind.REFERENCE,
                            inner_type=SawType(TypeKind.STRUCT,
                                               struct_name="Hasher"),
                            reference_mutable=True),
                            is_reference=True, reference_mutable=True),
                    ],
                    return_type=SawType(TypeKind.VOID),
                    body=Block(statements=[], final_expr=None,
                               line=extension.line, column=extension.column),
                    self_mutable=False,
                    self_is_reference=True,
                    is_derived_hash=True,
                    line=extension.line,
                    column=extension.column,
                ))
            self._derived_hash_types.add(extension.struct_name)

        # A marker that derived nothing is a mistake worth naming: either the
        # conformance already has a hand-written body (so nothing is derived) or
        # the trait has no derivation at all (Printable, a user trait).
        if has_synthesize(extension) and not derived_any:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`@synthesize` on `extension {extension.struct_name}` derives "
                f"nothing",
                extension.line, extension.column,
                hint="the derivable conformances are ImplicitCopy/ExplicitCopy "
                     "(`copy`), Equatable (`equals`), Comparable (`compare`) and "
                     "Hashable (`hash`), each with no hand-written body",
                source_file=getattr(extension, 'source_file', None)
            )

        # Default method bodies (design 56): for every trait this extension
        # conforms to — and every ancestor trait it thereby inherits — synthesize
        # a per-conformer Method from any default body the conformer does not
        # provide. The synthesized methods are ordinary Methods (real bodies,
        # typechecked + codegen'd per conformer), so `self.<required>()` calls in
        # a default dispatch to THIS conformer's implementation, and the
        # any-vtable builder finds them via the shared conformance record.
        self._synthesize_trait_defaults(extension, struct_info)

        # Check if this is a specialized extension (e.g., extension Vector<String>)
        specialization_key = self._get_specialization_key(extension)
        is_specialized = len(specialization_key) > 0

        # Conditional-conformance bounds: methods declared in a bounded extension
        # (e.g. `extension Vector<T: Copy>`) only exist for instantiations whose
        # type args satisfy the bounds. Record the bounds on each method symbol so
        # a call on an unsatisfying instantiation (Vector<File>.copy()) is caught.
        extension_bounds = {tp.name: list(tp.bounds)
                            for tp in extension.type_params if tp.bounds}

        # Member visibility (design 80): the extension's defining module, and the
        # set of method names required by the traits this extension conforms to.
        # A method satisfying a trait requirement is callable wherever the
        # conformance is visible, so it is exempt from the private-by-default
        # method gate (regardless of an explicit `public` marker).
        ext_def_module = self._vis_module_for_source(
            getattr(extension, 'source_file', None))
        trait_method_names: set = set()
        for _tn in extension.conformances:
            _simple = _tn.rsplit('.', 1)[-1]
            _tinfo = self.get_trait_info(_simple)
            if _tinfo is not None:
                trait_method_names.update(_tinfo.methods.keys())

        # Get the target method dict for duplicate checking (from namespace StructSymbol)
        if is_specialized:
            target_methods = struct_info.specialized_methods.get(specialization_key, {})
        else:
            target_methods = struct_info.methods

        for method in extension.methods:
            # For init methods, allow multiple with different parameter signatures
            # Use parameter names in the key to distinguish them
            if method.is_init:
                param_names = tuple(p.name for p in method.parameters)
                method_key = f"init:{','.join(param_names)}"
            else:
                method_key = method.name

            # Check for duplicate methods in target dict.
            #
            # Overloading (design 55): a non-init method on the ordinary (non-
            # specialized) method table may repeat a name as long as the
            # signatures are distinguishable; that check is deferred to the
            # declaration-site collision test below, once parameter types are
            # resolved. init overloading (name-based) and specialized-extension
            # method tables keep the strict "already defined" rule.
            allow_overload = (not method.is_init) and (not is_specialized)
            # Design 142: the method tables are shared across every module in the
            # link, so a same-named method registered by an UNRELATED module is
            # not a redeclaration — the two modules need not know about each
            # other. Only a clash within one defining module is a duplicate; a
            # cross-module one is diagnosed at a call site that sees both.
            if (method_key in target_methods
                    and (getattr(target_methods[method_key], 'def_module', ())
                         != ext_def_module)):
                allow_overload = True
            if method_key in target_methods and not allow_overload:
                if method.is_init:
                    self._error(
                        ErrorKind.DUPLICATE_FUNCTION,
                        f"init method with parameters ({', '.join(p.name for p in method.parameters)}) is already defined for struct `{extension.struct_name}`",
                        method.line, method.column
                    )
                else:
                    self._error(
                        ErrorKind.DUPLICATE_FUNCTION,
                        f"method `{method.name}` is already defined for struct `{extension.struct_name}`",
                        method.line, method.column
                    )
                continue

            # For instance methods (not init and not static), validate 'self' parameter
            self_mutable = False
            if not method.is_init and not method.is_static:
                if len(method.parameters) == 0:
                    self._error(
                        ErrorKind.WRONG_ARGUMENT_COUNT,
                        f"method `{method.name}` must have 'self' as first parameter",
                        method.line, method.column
                    )
                    continue

                first_param = method.parameters[0]
                if first_param.name != "self":
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"first parameter of method must be named 'self', got `{first_param.name}`",
                        method.line, method.column
                    )
                    continue

                # Get self mutability from the method's AST node
                self_mutable = method.self_mutable

                # Fill in the self parameter type (if it's the placeholder VOID from parser)
                expected_self_type = self._ext_self_type(extension.struct_name)
                if first_param.type.kind == TypeKind.VOID:
                    # Replace placeholder with actual type
                    first_param.type = expected_self_type
                elif not self._types_compatible(first_param.type, expected_self_type):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"'self' parameter must have type `{extension.struct_name}`, got `{first_param.type}`",
                        method.line, method.column
                    )

            # For init methods, check parameter names don't conflict with field names
            if method.is_init:
                param_names_set = {p.name for p in method.parameters}
                field_names_set = set(struct_info.fields.keys())
                if param_names_set == field_names_set:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"init method parameters match field names exactly - this is ambiguous with field initialization",
                        method.line, method.column,
                        hint="use different parameter names to distinguish from field init"
                    )

            # Register method
            # Determine the Self type for this extension
            self_type = self._ext_self_type(extension.struct_name)

            # Resolve Self types in parameter types
            # Note: 'self' parameter has VOID as placeholder from parser
            param_types = []
            for p in method.parameters:
                if p.name == "self" or p.type.kind == TypeKind.SELF:
                    param_types.append(self_type)
                else:
                    # Resolve type aliases and enum types
                    param_types.append(self._resolve_type(p.type))
            param_names = [p.name for p in method.parameters]

            # For init methods, override return type to be the struct type
            # For non-init methods, resolve Self in return type
            return_type = method.return_type
            if return_type.kind == TypeKind.SELF:
                return_type = self_type
            elif method.is_init:
                return_type = self_type
            else:
                # Resolve enum types (e.g., Result<T, E>) that are parsed as STRUCT
                return_type = self._resolve_type(return_type)

            # Escaping roles (design 16/29): method parameter closure types
            # default non-escaping; return type is an escaping role.
            for _pt in param_types:
                self._stamp_escaping_roles(_pt, is_param=True,
                                           report_at=(method.line, method.column))
            self._stamp_escaping_roles(return_type, is_param=False,
                                       report_at=(method.line, method.column))

            # Collect default values for parameters
            default_values = [p.default_value for p in method.parameters]
            # Default parameter values (design 53) must be trailing.
            self._check_trailing_defaults(
                method.parameters, method.line, method.column,
                f"method `{method.name}`")

            # Declaration-site overload check (design 55 + design 53) for ordinary
            # (non-init, non-specialized) methods: reject a repeat that no
            # tie-break rule could separate, expanding default-value call shapes
            # (self excluded from the signature).
            if not method.is_init and not is_specialized:
                new_offset = 1  # exclude self
                new_keys = self._overload_shape_keys(
                    param_types[new_offset:], method.type_params,
                    default_values[new_offset:], param_names[new_offset:])
                collides = False
                for other in struct_info.method_overloads.get(method.name, []):
                    # Design 142: only a repeat within this defining module is a
                    # declaration-site duplicate (see the note above).
                    if (getattr(other, 'def_module', ()) or ()) != ext_def_module:
                        continue
                    o_off = 0 if other.is_init else 1
                    other_keys = self._overload_shape_keys(
                        other.param_types[o_off:], other.type_params,
                        (other.default_values[o_off:] if other.default_values
                         else []),
                        other.param_names[o_off:])
                    if new_keys & other_keys:
                        collides = True
                        break
                if collides:
                    self._error(
                        ErrorKind.DUPLICATE_FUNCTION,
                        f"method `{method.name}` is already defined for struct "
                        f"`{extension.struct_name}` with an indistinguishable "
                        f"signature",
                        method.line, method.column,
                        hint="overloads must differ in arity or parameter types"
                    )
                    continue

            # Register in namespace
            method_symbol = FunctionSymbol(
                kind=SymbolKind.METHOD,
                param_types=param_types,
                param_names=param_names,
                return_type=return_type,
                # Method-level generic type params (brief 36): the `U` in
                # `func map<U>(...)`, distinct from the extension's own params.
                type_params=method.type_params,
                default_values=default_values,
                is_static=method.is_static,
                is_init=method.is_init,
                self_mutable=self_mutable,
                self_is_reference=method.self_is_reference,
                extension_bounds=extension_bounds,
                is_unsafe=getattr(method, 'is_unsafe', False),
                visibility=getattr(method, 'visibility', Visibility.PRIVATE),
                def_module=ext_def_module,
                satisfies_trait=(method.name in trait_method_names
                                 or getattr(method, 'is_derived_copy', False)
                                 or getattr(method, 'is_derived_equals', False)
                                 or getattr(method, 'is_derived_compare', False)
                                 or getattr(method, 'is_derived_hash', False)),
                ast_node=method,
                decl_node=method
            )
            if method.is_init:
                self.namespace.register_init_method(extension.struct_name, method_symbol)
            elif is_specialized:
                # Register specialized method with type specialization key
                self.namespace.register_specialized_method(
                    extension.struct_name, specialization_key, method.name, method_symbol)
            else:
                self.namespace.register_method(extension.struct_name, method.name, method_symbol)

        # Collect type assignments once (shared across all trait conformances)
        local_assignments: Dict[str, SawType] = {}
        for type_assign in extension.type_assignments:
            local_assignments[type_assign.name] = type_assign.assigned_type

        # Check trait conformances
        for trait_name in extension.conformances:
            # Send/Sync are structurally auto-derived marker traits (design 21
            # item 1): explicit conformance is never accepted (no unsafe-impl
            # story in v1). Reject with a clear message and skip registration.
            if trait_name in ("Send", "Sync"):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"cannot explicitly implement `{trait_name}`: it is a marker trait "
                    f"derived structurally by the compiler",
                    extension.line, extension.column,
                    hint=f"remove `: {trait_name}` - a type is {trait_name} automatically "
                         f"iff all its fields are"
                )
                continue
            # Handle module-qualified trait names (e.g., "lib.Describable")
            if '.' in trait_name:
                # Module-qualified: look up in module namespace
                parts = trait_name.rsplit('.', 1)
                module_name, simple_trait_name = parts[0], parts[1]
                module_sym = self.namespace.modules.get(module_name)
                if module_sym and module_sym.namespace:
                    trait_info = module_sym.namespace.resolve(
                        simple_trait_name, check_visibility=True, accessor_module=self.namespace.module_path
                    )
                    if trait_info is None or trait_info.kind != SymbolKind.TRAIT:
                        self._error(
                            ErrorKind.UNDEFINED_VARIABLE,
                            f"unknown trait `{trait_name}`",
                            extension.line, extension.column
                        )
                        continue
                else:
                    self._error(
                        ErrorKind.UNDEFINED_VARIABLE,
                        f"unknown module `{module_name}` in trait `{trait_name}`",
                        extension.line, extension.column
                    )
                    continue
            else:
                trait_info = self.get_trait_info(trait_name)
                if trait_info is None:
                    self._error(
                        ErrorKind.UNDEFINED_VARIABLE,
                        f"unknown trait `{trait_name}`",
                        extension.line, extension.column
                    )
                    continue

            # Register conformance in namespace FIRST (so _check_trait_conformance can read it)
            self.namespace.register_conformance(extension.struct_name, trait_name, local_assignments)

            self._check_trait_conformance(extension.struct_name, trait_info, struct_info, extension)

    def _check_trait_conformance(self, type_name: str, trait_info, struct_info, extension: Extension):
        """Check that a type conforms to a trait by implementing all required methods."""
        for method_name, trait_method in trait_info.methods.items():
            if method_name not in struct_info.methods:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"type `{type_name}` does not implement required method `{method_name}` from trait `{trait_info.name}`",
                    extension.line, extension.column
                )
                continue

            impl_method = struct_info.methods[method_name]

            # Check self mutability matches
            if trait_method.self_mutable != impl_method.self_mutable:
                if trait_method.self_mutable:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"method `{method_name}` should take `&var self` to conform to trait `{trait_info.name}`",
                        extension.line, extension.column
                    )
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"method `{method_name}` should have immutable `self` to conform to trait `{trait_info.name}`",
                        extension.line, extension.column
                    )

            # Check return type matches (allow Self and associated types -> concrete types)
            if not self._types_compatible_for_trait(trait_method.return_type, impl_method.return_type,
                                                         type_name, trait_info.name):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"method `{method_name}` has return type `{impl_method.return_type}` but trait `{trait_info.name}` expects `{trait_method.return_type}`",
                    extension.line, extension.column
                )

            # Check parameter count (excluding self)
            trait_param_count = len(trait_method.param_types) - 1  # Exclude self placeholder
            impl_param_count = len(impl_method.param_types) - 1    # Exclude self
            if trait_param_count != impl_param_count:
                self._error(
                    ErrorKind.WRONG_ARGUMENT_COUNT,
                    f"method `{method_name}` takes {impl_param_count} parameter(s) but trait `{trait_info.name}` expects {trait_param_count}",
                    extension.line, extension.column
                )

        # Check that all required associated types are provided
        type_assigns = self.namespace.get_type_assignments(type_name, trait_info.name)
        for assoc_type_name in trait_info.associated_types:
            if assoc_type_name not in type_assigns:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"type `{type_name}` does not provide required associated type `{assoc_type_name}` from trait `{trait_info.name}`",
                    extension.line, extension.column,
                    hint=f"add `type {assoc_type_name} = SomeType` to the extension"
                )

    def _types_compatible_for_trait(self, trait_type: SawType, impl_type: SawType,
                                         self_type_name: str, trait_name: str = None) -> bool:
        """Check if implementation type matches trait type, with Self and associated type substitution."""
        # Resolve the trait type by substituting Self and associated types
        resolved_trait_type = self._resolve_trait_type(trait_type, self_type_name, trait_name)
        return self._types_compatible(resolved_trait_type, impl_type)

    def _resolve_trait_type(self, trait_type: SawType, self_type_name: str,
                                  trait_name: str = None) -> SawType:
        """Resolve Self and associated types in a trait type."""
        # Handle Self type (TypeKind.SELF)
        if trait_type.kind == TypeKind.SELF:
            # Primitive pseudo-structs (String/Int/Float) map Self to the
            # primitive type, not a struct (design 57); an enum maps to its own
            # kind (design 145).
            return self._ext_self_type(self_type_name)
        if trait_type.kind == TypeKind.STRUCT and trait_type.struct_name:
            # Handle associated types
            if trait_name:
                type_assigns = self.namespace.get_type_assignments(self_type_name, trait_name)
                if trait_type.struct_name in type_assigns:
                    return type_assigns[trait_type.struct_name]
            # Recursively resolve type args
            if trait_type.type_args:
                resolved_args = [self._resolve_trait_type(t, self_type_name, trait_name)
                                 for t in trait_type.type_args]
                return SawType(TypeKind.STRUCT, struct_name=trait_type.struct_name, type_args=resolved_args)
        elif trait_type.kind == TypeKind.OPTIONAL and trait_type.inner_type:
            resolved_inner = self._resolve_trait_type(trait_type.inner_type, self_type_name, trait_name)
            return SawType(TypeKind.OPTIONAL, inner_type=resolved_inner)
        elif trait_type.kind == TypeKind.TUPLE and trait_type.element_types:
            resolved_elems = [self._resolve_trait_type(t, self_type_name, trait_name)
                              for t in trait_type.element_types]
            return SawType(TypeKind.TUPLE, element_types=resolved_elems)
        elif trait_type.kind == TypeKind.ENUM and trait_type.type_args:
            resolved_args = [self._resolve_trait_type(t, self_type_name, trait_name)
                             for t in trait_type.type_args]
            return SawType(TypeKind.ENUM, enum_name=trait_type.enum_name, type_args=resolved_args, symbol=trait_type.symbol)
        return trait_type
