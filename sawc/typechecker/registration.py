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
    effective_field_visibility,
    Block, ReturnStatement, BreakStatement, ContinueStatement, IfExpr, WhileExpr,
    IntLiteral, FloatLiteral, BoolLiteral, UnaryOp, ArrayLiteral, StructInit,
    FunctionCall, ExpressionStatement, SourceLocationLiteral, expr_diverges,
    ext_param_aliases, PRIMITIVE_EXT_KINDS
)
from errors import ErrorKind
from namespace import (
    SymbolKind, FunctionSymbol, StructSymbol, EnumSymbol, TraitSymbol,
    TypeAliasSymbol, TraitMethodSymbol, StaticSymbol
)


def _ref_self_type() -> SawType:
    """`&Self` — the right operand of `equals`/`compare` (design 239).

    A fresh node per call, because the derived methods below are written onto
    per-extension AST and every later pass may substitute `Self` into its own
    copy. Named rather than inlined so the derived signature and
    `builtin.saw`'s requirement cannot drift apart silently: the conformance
    check compares them.
    """
    return SawType(TypeKind.REFERENCE, inner_type=SawType(TypeKind.SELF),
                   reference_mutable=False)


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
    "__saw_test_suspend", "__saw_suspend", "__saw_io_park", "__saw_chan_park",
    "__saw_box_data",
    "__saw_blk_start", "__saw_blk_done", "__saw_blk_pipe_fd", "__saw_blk_take",
    "__saw_drive", "__saw_drive_steps", "__saw_deinit_in_place", "__saw_forget",
    "__saw_bt_table",
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
        # Note: Built-in traits (Deinit, Copy, NoCopy) are defined
        # in builtin.saw and loaded automatically by the compiler.

        # Register String as a pseudo-struct so it can be extended
        # String is a primitive type (i8*) but we want to add methods to it
        # PUBLIC, and it is not decoration: the signature-visibility rule ("a
        # public API needs public types", Aug 21) reads a named type's tier, and
        # a compiler-registered symbol has no declaration to read it off. These
        # three registrations — `String`, the primitive pseudo-structs and
        # `Result` — ARE the prelude, so they say so.
        self.namespace.register_struct("String", StructSymbol(
            fields={},
            field_order=[],
            visibility=Visibility.PUBLIC,
            line=0,
            column=0
        ))

        # String is a compiler-known refcounted value type: `Copy` (a copy is a
        # refcount bump) + Deinit (release, free at zero). The copy/deinit
        # bodies are IR-level runtime helpers emitted by codegen, so the
        # conformance is registered here rather than declared in stdlib. This
        # drives value-transfer copy() insertion and scope-exit cleanup.
        self.namespace.register_conformance("String", "Copy")
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

        # Register EVERY primitive as a pseudo-struct so it can carry method
        # extensions and conformances (design 57 Part 5, widened by design 176 /
        # DF-169d). No conformances are registered here: their Copy/Equatable/
        # Comparable/Hashable behavior is handled by the primitive-aware bound
        # checks and the compiler-intercepted copy/hash/compare/format
        # lowerings, all of which run before ordinary struct-method dispatch.
        # The pseudo-struct only makes `extension Int8 { ... }` and
        # value.method() dispatch resolve.
        #
        # This list used to be Int and Float alone (String is registered
        # separately, above), which made `extension UInt8: MyProto` — the
        # wire-vocabulary case — the error "cannot extend undefined struct
        # `UInt8`" while the identical declaration on `Int` compiled. There was
        # no rule behind the split; it was the set someone happened to need.
        for _prim in ("Int", "UInt", "Float", "Bool",
                      "Int8", "Int16", "Int32", "Int64",
                      "UInt8", "UInt16", "UInt32", "UInt64"):
            self.namespace.register_struct(_prim, StructSymbol(
                fields={}, field_order=[], visibility=Visibility.PUBLIC,
                line=0, column=0))

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
            type_params=result_type_params,
            visibility=Visibility.PUBLIC
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
            # A diverging expression (design 49/177/228) exits just like a
            # return, so `guard let x = ... else { panic("...") }` — and
            # `else { fault(p) }` for a `-> Never` fault — is a valid exit.
            if isinstance(stmt, ExpressionStatement) and self._diverges(stmt.expression):
                return True
            # design 177: a conditionless `while { ... }` nothing breaks out of
            # diverges on the same terms, so `guard let v = o else { while { } }`
            # is a valid exit. In STATEMENT position the loop is a statement with
            # no stamped type, so `_diverges` reads its flag — which is stamped
            # while the block is checked, as every caller of this does first.
            if isinstance(stmt, WhileExpr) and self._diverges(stmt):
                return True
            # Check if-else: both branches must have early exits
            if isinstance(stmt, IfExpr) and stmt.else_branch:
                then_exits = self._block_has_early_exit(stmt.then_branch)
                else_exits = self._block_has_early_exit(stmt.else_branch)
                if then_exits and else_exits:
                    return True
        # A block whose trailing expression diverges (e.g. `{ panic("...") }`)
        # also cannot fall through.
        if block.final_expr is not None and self._diverges(block.final_expr):
            return True
        return False

    def _diverges(self, expr) -> bool:
        """True if evaluating `expr` never falls through.

        The typechecker's door onto the one divergence predicate,
        `ast_nodes.expr_diverges` (design 228 leg 1) — read ITS docstring for
        the rule, the entry points and the ordering hazard. It used to be a
        NAME test (`expr.name == "panic"`), the only syntax-list judgment among
        twenty-odd correct `TypeKind.NEVER` tests, which is why a `-> Never`
        call was not a legal `guard ... else` exit while `panic(...)` and a
        break-less `while { }` both were (DF-178d face 1).
        """
        return expr_diverges(expr)

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
        entry_borrows = {id(b) for b in self._task_borrows}
        outer_ids = set()
        scope = outer_scope
        while scope is not None:
            for var_info in scope.variables.values():
                outer_ids.add(var_info.binding_id)
            scope = scope.parent

        self._check_block(body)
        # Design 151: a loop body yields a value only via `break v`, so its
        # tail expression is discarded unconditionally.
        self._check_result_discard(body.final_expr)

        for key, (var_info, name, move_line, move_col, provisional) in list(
                self.moved_bindings.items()):
            if key in entry_moves:
                continue  # already moved before the loop -- caught elsewhere
            if key in outer_ids:
                if provisional:
                    # design 219 wave C, entry point 4: an abstract-tier
                    # transfer that survives to the next iteration is a second
                    # use of the same binding, so the body needs a real
                    # duplicate rather than a move.
                    self._tier_req_second_use(var_info, name, move_line,
                                              move_line)
                    continue
                self._error(
                    ErrorKind.USE_AFTER_MOVE,
                    f"use of moved variable `{name}` across loop iterations",
                    move_line, move_col,
                    hint="a binding moved inside a loop is moved-from on the next "
                         "iteration; reassign it before the loop body ends, or move a fresh value"
                )

        # design 189, the same question for borrows: a spawn inside the body
        # whose handle is not joined before the body ends opens a SECOND
        # exclusive borrow of the same root on the next iteration. One textual
        # spawn, N live borrows — the Law violated by iteration rather than by
        # a second line. Spawn-and-join-in-the-body is untouched (the join
        # released it), and so is a shared `[&x]` capture, which composes.
        # A `&var` ARGUMENT of the spawned call is the same record (design 201),
        # so it takes this rule with nothing added but the word it is named by.
        for b in self._task_borrows:
            if id(b) in entry_borrows or not b.mutable:
                continue
            if b.root_id not in outer_ids:
                continue   # the root is born and dies inside one iteration
            self._error(
                ErrorKind.EXCLUSIVITY_VIOLATION,
                f"exclusive access violation: this task's `&var {b.root_name}` "
                f"{b.kind} is still live when the loop body ends, so the next "
                f"iteration would open a second exclusive borrow of the same "
                f"root: {self._task_borrow_extent(b)}",
                b.spawn_line, b.spawn_column,
                hint="join this task's handle before the body ends (spawn, "
                     "join, then loop), or give each iteration its own root. "
                     "To fan out over ONE piece of shared state, share it "
                     "through an `Arc<Mutex<T>>` or a `Channel`")

        # The loop may execute zero times, so after it we are back to the
        # pre-loop state (any real cross-iteration move was flagged above).
        self.moved_bindings = entry_moves

    def _arm_diverges(self, body) -> bool:
        """True if a match-arm body definitely exits the enclosing scope.

        Used by the move-dataflow merge (design 15 rule 6): a diverging arm
        does not contribute to the may-moved union. A block body reuses
        `_block_has_early_exit`; a bare statement body (return/break/continue)
        diverges directly; a bare EXPRESSION body asks the one divergence
        predicate (design 228 leg 1), so `case A -> fault(p)` counts exactly as
        `case A -> { fault(p) }` does — the braces were never the question.
        """
        if isinstance(body, Block):
            return self._block_has_early_exit(body)
        if isinstance(body, (ReturnStatement, BreakStatement, ContinueStatement)):
            return True
        return self._diverges(body)

    # ---------------------------------------------------------------- #
    # THE ALIAS UNDERLYING-KIND RULE (DF-194b)
    #
    # `type R = L` where `L` is an ENUM is INVALID (user ruling, Aug 17).
    # An alias is a one-directional name: the `as` projection reads it back
    # toward the type it aliases, and that projection reaches the alias chain
    # through `_alias_ancestor_names`, which walks STRUCT chains only. So an
    # enum-underlying alias could be declared and constructed but never read
    # back — `r as Level` reported ``cannot cast `Level` to `Level``, the two
    # names printing identically, a diagnostic at a distance from the thing
    # that was actually wrong. Until a use case exists the alias itself is
    # refused, at its own declaration.
    #
    # It runs as its OWN pass rather than inside `_register_type_definition`,
    # because aliases are registered BEFORE structs and enums are — at
    # registration time no name is knowably an enum yet.
    #
    # ENTRY POINTS (obligation 1), one per registration driver, each calling
    # this once its own four registration passes have run:
    #   * `check` (typechecker/core.py) — the entry program.
    #   * `check_module` (typechecker/core.py) — every other module.
    # ---------------------------------------------------------------- #
    def _alias_underlying_enum(self, t, depth: int = 0) -> Optional[str]:
        """The ENUM an alias right-hand side ultimately names, or None.

        Chases alias-of-alias through each link's WRITTEN type, so with
        `type A = L` and `type B = A` both answer `L`. A bare named type parses
        STRUCT-kinded, so both kinds are asked of the symbol tables rather than
        trusted from the annotation."""
        if t is None or depth > 16:
            return None
        if t.kind == TypeKind.ENUM and t.enum_name:
            name = t.enum_name
        elif t.kind == TypeKind.STRUCT and t.struct_name:
            name = t.struct_name
        else:
            return None
        if (self.get_enum_info(name) is not None
                and self.get_struct_info(name) is None):
            return name
        alias = self.get_type_alias_info(name)
        if alias is not None:
            return self._alias_underlying_enum(
                getattr(alias, 'immediate_type', None), depth + 1)
        return None

    def _immediate_alias_name(self, t) -> Optional[str]:
        """The name an alias right-hand side writes, or None — for naming the
        middle of a chain in the diagnostic below."""
        if t is None:
            return None
        if t.kind == TypeKind.ENUM and t.enum_name:
            return t.enum_name
        if t.kind == TypeKind.STRUCT and t.struct_name:
            return t.struct_name
        return None

    def _reject_enum_underlying_aliases(self, program) -> None:
        """Refuse every `type` alias whose underlying type is an enum."""
        for type_def in getattr(program, 'type_definitions', []):
            written = getattr(type_def, 'defined_type', None)
            enum_name = self._alias_underlying_enum(written)
            if enum_name is None:
                continue
            via = self._immediate_alias_name(written)
            through = ("" if via is None or via == enum_name
                       else f" (through `{via}`)")
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"type alias `{type_def.name}` names the enum "
                f"`{enum_name}`{through}, and an alias of an enum is not "
                f"allowed",
                type_def.line, type_def.column,
                hint=f"use `{enum_name}` itself. An alias is read back to the "
                     f"type it names with `as`, and there is no such reading "
                     f"for an enum — so `{type_def.name}` would be a name with "
                     f"no way out. Aliases of structs and primitives are "
                     f"unaffected",
                source_file=getattr(type_def, 'source_file', None) or None,
            )

    def _register_type_definition(self, type_def: TypeDefinition):
        """Register a type definition (type alias)."""
        # Design 144/204: keyed by IDENTITY — see `_register_struct`.
        identity = self._stamp_type_identity(type_def)
        if self.get_type_alias_info(identity):
            self._error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"type `{type_def.name}` is defined multiple times",
                type_def.line, type_def.column
            )
            return

        # The prelude gate (design 194 unit 4): an alias's right-hand side goes
        # through `_resolve_type_alias`, not `_resolve_type`, so it is the third
        # declaration slot the funnel does not cover on its own. Design 188
        # established that an alias is not a way past a type rule.
        self._gate_written_type(
            type_def.defined_type,
            type_params=self._declared_type_param_names(type_def))
        # …and the module QUALIFIER walk, the third of the three raw slots
        # (DF-194a): `type Alias = dep.Point` kept the dotted spelling, and
        # `_resolve_type_alias` only ever chases alias-of-alias.
        type_def.defined_type = self._resolve_declared_qualified_names(
            type_def.defined_type)

        # Resolve the defined type (it might reference other type aliases)
        resolved_type = self._resolve_type_alias(type_def.defined_type)
        self.namespace.register_type_alias(type_def.name, TypeAliasSymbol(
            aliased_type=resolved_type,
            immediate_type=type_def.defined_type,
            visibility=getattr(type_def, 'visibility', Visibility.PRIVATE),
            type_identity=identity,
            def_module=self._vis_module_for_source(
                getattr(type_def, 'source_file', None))
        ),
            # Design 255 / SL-4: this module's label, so a collision names it.
            source_label=self._module_label(
                self._vis_module_for_source(
                    getattr(type_def, 'source_file', None))))

    def _register_struct(self, struct: Struct):
        """Register a struct definition."""
        # Design 144/204: the redefinition question is asked of the IDENTITY,
        # not the spelling. Two declarations in ONE file share an identity and
        # are still a duplicate; a std file's private `State` and another's are
        # two types and never meet.
        identity = self._stamp_type_identity(struct)
        # A hidden std name this module declares itself: the spelling is the
        # module's from here on. A no-op wherever the std declaration's
        # identity IS its spelling (the usual case, `IoError`); load-bearing
        # for a compiler-emitted type, whose identity is qualified.
        if self._shadows_hidden_std(struct.name):
            self.namespace.rebind_type_name(struct.name, identity)
        if self.namespace.has_struct(identity):
            if not self._shadows_hidden_std(struct.name):
                self._error(
                    ErrorKind.DUPLICATE_FUNCTION,  # We can reuse this error kind
                    f"struct `{struct.name}` is defined multiple times",
                    struct.line, struct.column
                )
                return
            # The registration below overwrites the merged SYMBOL; the
            # conformance table is keyed separately and has to be told too.
            self.namespace.hide_type_conformances(identity)

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
                # The prelude gate (design 194 unit 4): a field's type is stored
                # RAW and read straight off the AST, so it never reaches
                # `_resolve_type` as a unit — one of the three declaration slots
                # the funnel cannot cover on its own.
                self._gate_written_type(
                    field.type,
                    type_params=self._declared_type_param_names(struct))
                # …and, for the same reason, the module QUALIFIER walk (DF-194a).
                # Written back onto the AST so the symbol table and the AST go on
                # sharing one object, exactly as a `let` annotation's write-back
                # does.
                field.type = self._resolve_declared_qualified_names(field.type)
                # A closure-typed field is escaping (design 16/29): the struct
                # value can outlive any call, so a stored closure must be safe to
                # store. Stamp the bit; writing `escaping` here is redundant.
                self._stamp_escaping_roles(
                    field.type, is_param=False,
                    report_at=(getattr(field, 'line', struct.line),
                               getattr(field, 'column', struct.column)))
                fields[field.name] = field.type
                field_order.append(field.name)

        # Member visibility (design 80, amended by design 258): per-field
        # EFFECTIVE visibility + the struct's defining module (keyed on source
        # file so std files each form their own module even under the merged
        # prelude).
        #
        # This map is what `_check_field_visible` reads, so routing it through
        # `effective_field_visibility` is what makes the field READ, the field
        # WRITE and the cross-module memberwise LITERAL agree by construction:
        # all three ask the gate, and the gate asks this map.
        struct_vis = getattr(struct, 'visibility', Visibility.PRIVATE)
        field_visibility = {f.name: effective_field_visibility(f, struct_vis)
                            for f in struct.fields}
        def_module = self._vis_module_for_source(getattr(struct, 'source_file', None))
        self.namespace.register_struct(struct.name, StructSymbol(
            fields=fields,
            field_order=field_order,
            type_params=struct.type_params,
            visibility=struct_vis,
            field_visibility=field_visibility,
            def_module=def_module,
            type_identity=identity,
            is_unsafe=getattr(struct, 'is_unsafe', False),
            line=struct.line,
            column=struct.column,
            ast_node=struct if struct.type_params else None
        ),
            # Design 255 / SL-4: a declaration made HERE carries this module's
            # label, so a collision report names both sides instead of one
            # `<unknown>` (or, for a prelude name declared in a non-entry
            # module, two of them).
            source_label=self._module_label(def_module))

    def _register_enum(self, enum: Enum):
        """Register an enum definition."""
        # Design 144/204: keyed by IDENTITY — see `_register_struct`. The
        # hidden-std allowance joins it here too (DF-153b): design 82 gave it
        # to structs and never to enums, so a user `enum OpenMode` lost to
        # std.file's private one where a user `struct File` did not.
        identity = self._stamp_type_identity(enum)
        # See `_register_struct`: the spelling becomes this module's.
        if self._shadows_hidden_std(enum.name):
            self.namespace.rebind_type_name(enum.name, identity)
        if self.namespace.has_enum(identity):
            if not self._shadows_hidden_std(enum.name):
                self._error(
                    ErrorKind.DUPLICATE_FUNCTION,  # Reuse this error kind
                    f"enum `{enum.name}` is defined multiple times",
                    enum.line, enum.column
                )
                return
            self.namespace.hide_type_conformances(identity)

        # DF-153b's allowance, one line further: a HIDDEN std name is not in the
        # user's namespace, so a user declaration of it is not a clash — and the
        # kind of the declaration it hides has nothing to do with that. The
        # same-kind halves above already say so; this cross-kind one used to
        # refuse a user `enum Slot` against a gated std `struct Slot` while
        # accepting a user `struct IoError` against a gated std `struct
        # IoError`. Shadowing hides the std STRUCT entry too, so a bare `Slot`
        # afterwards is the user's enum and nothing resolves to two types.
        if self.namespace.has_struct(identity):
            if not self._shadows_hidden_std(enum.name):
                self._error(
                    ErrorKind.DUPLICATE_FUNCTION,
                    f"enum `{enum.name}` conflicts with existing struct name",
                    enum.line, enum.column
                )
                return
            self.namespace.hide_struct(identity)
            self.namespace.hide_type_conformances(identity)

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
                # And, like fields, they are stored RAW — so the prelude gate's
                # funnel never sees them and this is one of its three declared
                # extra entry points (design 194 unit 4).
                resolved_payloads = []
                for _payload in (variant.associated_types or []):
                    _pt = _payload[1] if isinstance(_payload, tuple) else _payload
                    self._gate_written_type(
                        _pt, type_params=self._declared_type_param_names(enum))
                    # …and the module QUALIFIER walk, the second of the three raw
                    # slots (DF-194a).
                    _pt = self._resolve_declared_qualified_names(_pt)
                    self._stamp_escaping_roles(
                        _pt, is_param=False, report_at=(enum.line, enum.column))
                    resolved_payloads.append(
                        (_payload[0], _pt) + tuple(_payload[2:])
                        if isinstance(_payload, tuple) else _pt)
                if variant.associated_types:
                    variant.associated_types = resolved_payloads
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
            type_identity=identity,
            ast_node=enum if enum.type_params else None,
            raw_type=raw_type,
            raw_values=raw_values
        ),
            # Design 255 / SL-4: this module's label, so a collision names it.
            source_label=self._module_label(
                self._vis_module_for_source(getattr(enum, 'source_file', None))))

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

    def _check_enum_raw_backing(self, enum: Enum):
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
                # DF-232c: a case whose value was WRITTEN as an expression that
                # did not fold already said so, at the expression, in
                # `_fold_enum_raw_values`. Saying "needs an explicit value"
                # about it too would contradict the source.
                if getattr(variant, 'raw_value_expr', None) is not None:
                    continue
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
        # Design 144/204: keyed by IDENTITY — see `_register_struct`.
        identity = self._stamp_type_identity(trait)
        if self.namespace.has_trait(identity):
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

        # A requirement's parameter and return types are stored RAW on the
        # symbol below and read straight off it — nothing resolves them as a
        # unit — so this is the design-194 funnel's fifth declaration-slot
        # entry (design 241 unit 1). The scope a requirement's names live in is
        # the trait's own type parameters plus its associated types, own and
        # inherited: `func next(&self) -> Item?` names a type this trait
        # declares and no table holds.
        _req_scope = self._declared_type_param_names(trait)
        _req_scope.update(inherited_assoc_types)
        _req_scope.update(at.name for at in trait.associated_types)

        # Build method symbol map from this trait's own methods
        methods = dict(inherited_methods)  # Start with inherited
        for method in trait.methods:
            _method_scope = _req_scope | self._declared_type_param_names(method)
            for _rt in ([p.type for p in method.parameters
                         if p.name != "self"] + [method.return_type]):
                self._gate_written_type(_rt, type_params=_method_scope)

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

            # DF-239b: DECLARATION-TIME RESOLUTION. The gate walk above already
            # asks "does this name denote a type HERE"; the answer was thrown
            # away, and the deep argument check on the generic-bound call path
            # was deferred for want of it. Resolve the same slots now — this is
            # the module that DECLARES the requirement, so its imports are the
            # ones the spelling was written against — and keep the result beside
            # the raw types. A call site in another module then reads a resolved
            # identity instead of trying to resolve a foreign spelling against
            # its own namespace, which is what design 194's provenance rule
            # forbids (`data.Data` in the declaring module's signature is not
            # `data.Data` in a caller that never imported `std.data`).
            #
            # Resolution runs AFTER this module's structs, enums and aliases are
            # registered (the trait pass is fourth of four), so a same-module
            # name resolves; the gate's report is deduplicated per written
            # position, so passing through `_resolve_type` here reports nothing
            # twice. A name that stays abstract — `Self`, an associated type, a
            # type parameter — resolves to itself and is EXCLUDED by
            # `abstract_type_names` rather than by the resolution failing.
            resolved_param_types = []
            for param in method.parameters:
                if param.name == "self":
                    resolved_param_types.append(SawType(TypeKind.VOID))
                elif param.type is None:
                    resolved_param_types.append(None)
                else:
                    resolved_param_types.append(self._resolve_type(param.type))
            resolved_return_type = (self._resolve_type(method.return_type)
                                    if method.return_type is not None else None)

            methods[method.name] = TraitMethodSymbol(
                name=method.name,
                param_types=param_types,
                return_type=method.return_type,
                resolved_param_types=resolved_param_types,
                resolved_return_type=resolved_return_type,
                abstract_type_names=frozenset(_method_scope),
                param_names=param_names,
                self_mutable=method.self_mutable,
                self_is_reference=method.self_is_reference,
                is_sync=getattr(method, 'is_sync', False),
                is_unsafe=getattr(method, 'is_unsafe', False),
                # A `static` requirement (design 169) is called on the type, so
                # there is no receiver to dispatch on and the trait cannot be
                # erased to `any`. Design 236 made staticness a DECLARATION —
                # the requirement spells `static func` and the parser refuses
                # any disagreement with the parameter list — so this reads the
                # keyword rather than inferring from the missing `self`.
                is_static=getattr(method, 'is_static', False),
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
            type_identity=identity
        ),
            # Design 255 / SL-4: this module's label, so a collision names it.
            source_label=self._module_label(
                self._vis_module_for_source(getattr(trait, 'source_file', None))))

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
        #
        # Design 249: SAME-MODULE declarations only. Two modules may hold
        # shape-identical same-named free functions — `std.json.encode` beside
        # `std.cbor.encode` is the point — and a declaration in one module can
        # never be the "other overload" a declaration in another is
        # indistinguishable from. What a bare call does when both are in scope
        # is the use-site ambiguity, raised where it is written.
        def_module = self._vis_module_for_source(
            getattr(func, 'source_file', None))
        new_keys = self._overload_shape_keys(param_types, func.type_params,
                                              default_values, param_names)
        for other in self.namespace.lookup_module_function_overloads(
                func.name, def_module):
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

        visibility = getattr(func, 'visibility', Visibility.PRIVATE)
        symbol_base = self._free_function_symbol_base(
            func.name, def_module, visibility)
        symbol = FunctionSymbol(
            param_types=param_types,
            param_names=param_names,
            return_type=return_type,
            type_params=func.type_params,
            default_values=default_values,
            visibility=visibility,
            is_sync=getattr(func, 'is_sync', False),
            is_unsafe=getattr(func, 'is_unsafe', False),
            def_module=def_module,
            ast_node=func if func.type_params else None,
            decl_node=func,
            symbol_base=symbol_base,
        )
        if symbol_base:
            symbol.mangled_name = symbol_base
            func.mangled_symbol = symbol_base
        self.namespace.register_function(func.name, symbol)

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
        `Header$m$dep$m$dep`. Same shape as DF-146a's `_derivation_slot`.

        Design 204: a std file's declaration qualifies iff it is PRIVATE, which
        is what makes `State` in `std/once.saw` that file's own type while
        `Vector` stays the one every program names. Outside std the visibility
        is irrelevant — design 144 qualifies a user module's types either way.
        """
        from type_identity import type_identity
        existing = getattr(decl, 'type_identity', "")
        if existing:
            return existing
        if getattr(decl, 'is_synthesized', False):
            # A compiler-synthesized type (a coroutine frame) is named by
            # string where it is built and at every reference to it, so it
            # keeps the plain name it was given.
            decl.type_identity = decl.name
            return decl.name
        module = self._vis_module_for_source(getattr(decl, 'source_file', None))
        private = (getattr(decl, 'visibility', Visibility.PRIVATE)
                   == Visibility.PRIVATE)
        identity = type_identity(decl.name, module, private=private)
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

    def _free_function_symbol_base(self, name: str,
                                   def_module: Tuple[str, ...],
                                   visibility: Visibility) -> str:
        """Design 249: the module-tagged codegen base for a free function whose
        name MORE THAN ONE module of this compilation declares, or "" when the
        plain name is unambiguous.

        Two modules owning one free-function name is legal since design 249, so
        the two definitions need two LLVM symbols. The decision is a pure
        function of `free_function_owners` — the (name -> declaring modules)
        census the driver takes over the parsed module set BEFORE any module is
        checked — so it never depends on module order and never renames a
        symbol whose bodies are already checked.

        A PRIVATE declaration of a NON-ROOT module is left to DF-140f's `$m$`
        tag, which already makes it module-local. The root module takes a tag
        like any other (`module_tag(())` is `root`) — std is checked once and
        CACHED across compiles, so its symbols cannot depend on the program
        being compiled, which makes the entry the side that moves when a user
        declaration meets a std one.
        """
        if visibility == Visibility.PRIVATE and def_module:
            return ""
        owners = (getattr(self, 'free_function_owners', None) or {}).get(name)
        if not owners or len(owners) < 2:
            return ""
        return f"{name}$M${self._module_symbol_tag(def_module)}"

    def _stamp_module_private_functions(self):
        """Give this module's private free functions a module-local codegen
        symbol. Runs per module, and only over declarations this module OWNS —
        an imported symbol is the SAME object as the source module's, so
        stamping it here would rename the definition out from under its owner."""
        own_module = self._vis_module_for_source(None)
        # Design 249: ask the module-keyed storage for THIS module's own
        # declarations, so an import that puts another module's same-named
        # function in the bare view no longer hides this one's private tag.
        own_table = self.namespace.module_function_overloads.get(
            tuple(own_module), {})
        for name, overloads in own_table.items():
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

        Design 249: the free-function half walks the MODULE-KEYED storage and
        stamps only the module this pass registers. An overload set is one
        module's own declarations, so an importer that now sees two modules'
        same-named functions in a single bare set never re-mangles either
        module's symbols out from under the bodies already resolved against
        them. The BASE each symbol is built from is the declaration's
        `symbol_base` — the plain name, or the `$M$`-tagged one when more than
        one module declares the name.
        """
        from codegen.mangle import mangle_overload, mangle_method, mangle_type

        def _type_sig(param_types):
            return tuple(mangle_type(p) if p is not None else "Void"
                         for p in param_types)

        own_module = tuple(self._vis_module_for_source(None))
        checking_builtins = bool(getattr(self, '_checking_builtins', False))
        for def_module, table in self.namespace.module_function_overloads.items():
            # std registers many file-modules in ONE pass; every other pass owns
            # exactly the module it is checking.
            if not checking_builtins and tuple(def_module) != own_module:
                continue
            for name, overloads in table.items():
                if len(overloads) < 2:
                    continue
                base = next((s.symbol_base for s in overloads if s.symbol_base),
                            name)
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
                        base, sym.param_types,
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
                            base, sym.param_types,
                            sym.param_names if need_labels else None)
                        sym.mangled_name = mangled
                        if sym.decl_node is not None:
                            sym.decl_node.mangled_symbol = mangled
        # DF-283a: enums carry `methods`/`method_overloads` on exactly the same
        # terms since design 145 (`Namespace.method_owner` is written once for
        # both), but this pass walked `structs` alone — so an enum extension's
        # overload set never got its design-55 signature symbols, both members
        # were declared under the plain `E_name` mangling, and codegen died in
        # `_declare_extension_methods` with a DuplicatedNameError before any
        # call site was reached. Instance and static alike, single-file and
        # cross-module alike.
        for struct_name, struct_sym in list(self.namespace.structs.items()) \
                + list(self.namespace.enums.items()):
            for mname, overloads in struct_sym.method_overloads.items():
                if len(overloads) < 2:
                    continue
                base = mangle_method(struct_name, mname)
                sig_counts = {}
                for sym in overloads:
                    if sym.type_params:
                        continue
                    # The same offset the declaration check and the call-site
                    # resolver use: a STATIC method has no `self` slot to skip,
                    # and slicing one off dropped its first parameter from the
                    # MANGLED name too, so two statics differing only there
                    # collided in the LLVM symbol table (DF-217e).
                    offset = self._overload_cand_offset(sym, True)
                    sig_counts[_type_sig(sym.param_types[offset:])] = \
                        sig_counts.get(_type_sig(sym.param_types[offset:]), 0) + 1
                for sym in overloads:
                    if sym.type_params:
                        continue
                    offset = self._overload_cand_offset(sym, True)
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

        # DF-181e (design 183 unit 2): the offload marshals the C ABI, so the
        # signature must be one the C ABI can carry — the same set `@export`
        # admits, checked at the declaration for the same reason.
        if getattr(extern_func, 'is_blocking', False):
            self._check_blocking_extern_signature(extern_func)

        existing = self.get_function_info(extern_func.name)
        if existing is not None:
            # Allow duplicate extern declarations with the same signature
            # This enables library code (like std/) to declare externs that
            # user code may also declare
            if (existing.param_types == param_types and
                existing.return_type == resolved_return_type):
                # DF-181f (design 183 unit 1): `blocking` is part of an extern's
                # CONTRACT, not a spelling of it, so a redeclaration that
                # disagrees is a contradiction — one of the two is wrong about
                # the symbol. Before this, the second declaration was dropped
                # whole and its annotation with it: every `__saw_rt_*` seam std
                # already declares silently ignored `blocking`, so the one
                # remediation the design-181 audit recommends ("annotate the
                # seam") compiled to a naked thread-blocking call. Design 103
                # promises an offload or a clean error, never silence.
                #
                # The annotation deliberately does NOT win: extern symbols are
                # global by name, so letting a downstream declaration upgrade
                # one would retroactively make a function another module calls a
                # suspension source — an effect change at a distance, landing as
                # errors inside code the author never wrote. Whoever owns the
                # declaration owns the claim.
                if bool(getattr(existing, 'is_blocking', False)) != bool(
                        getattr(extern_func, 'is_blocking', False)):
                    now_blocking = getattr(extern_func, 'is_blocking', False)
                    self._error(
                        ErrorKind.DUPLICATE_FUNCTION,
                        f"`{extern_func.name}` is declared "
                        f"{'`blocking`' if now_blocking else 'without `blocking`'} "
                        f"here, but another declaration of the same symbol says "
                        f"{'the opposite' if now_blocking else '`blocking`'}",
                        extern_func.line, extern_func.column,
                        source_file=getattr(extern_func, 'source_file', None),
                        hint="`blocking` is part of an extern's contract (it makes "
                             "every call a suspension point), so every declaration "
                             "of one symbol must agree — annotate the declaration "
                             "they share, or offload a distinctly-named wrapper of "
                             "your own instead",
                    )
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
        registering = getattr(self, '_registering_static', False)
        self._registering_static = True
        try:
            self._register_static_body(static)
        finally:
            self._registering_static = registering

    def _register_static_body(self, static: StaticDecl):
        """`_register_static`'s work, under DF-283b's declaration-order fence.

        The fence is the whole reason for the split: statics register in
        declaration order, so while one is being registered the const-static
        DECLARATION TABLE — which is built whole, ahead of registration, for the
        type positions that resolve before any symbol exists — may not answer
        for a name that has no symbol yet. That name is one declared BELOW, and
        design 186 unit 7 forbids reading it. See `_const_static_lookup`.
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

        # The prelude gate used to be hand-called here (design 188 unit 7): a
        # gated module is not compiled in at all, so a `static LOCK:
        # SpinLock<Int>` that never names the type in an EXPRESSION reached
        # codegen and died there ("Unknown generic struct: SpinLock") instead of
        # being told to import it. Design 194 unit 4 routed the gate through
        # `_resolve_type`, which the next line calls — so this position is
        # covered by the funnel now, anchored at the annotation rather than at
        # the declaration, and the hand-call is gone.
        resolved_type = self._resolve_type(static.type)

        # DF-226f (ruled Aug 17): an OPTIONAL static is refused AT THE
        # DECLARATION. A static is a fixed, immortal, compile-time-initialized
        # value, so the one thing an optional buys — "the value is not there
        # yet, and code must ask before using it" — is a state a static cannot
        # be in: whichever of `Some`/`None` the initializer names is the value
        # forever, and every read then pays an unwrap for an answer that was
        # decided at compile time. `static SLOT: Int? = 7` used to fall out as
        # an incidental type mismatch (the initializer is an `Int`, the
        # declared type an `Int?`, and statics never auto-wrapped), which named
        # the symptom and not the rule; DF-226d only changed which WIDTH that
        # message reported. Auto-wrap is deliberately NOT added.
        #
        # Asked on the TYPE, before the initializer is looked at, so all four
        # spellings meet the same rule: a bare `7`, a wrapped `Some(7)`, a bare
        # `None`, and no initializer at all. Only the static's OWN top-level
        # type is the target — an optional nested inside a generic
        # (`static V: Vector<Int?>`) is untouched, and so is `unsafe static
        # var`, which is a different question this rule does not reopen.
        #
        # The refusal does NOT return: it suppresses the initializer checks
        # (whose complaint would be the incidental mismatch this rule replaces)
        # and falls through to registration, so every later USE of the name
        # still resolves. Returning here orphaned the symbol and every mention
        # of it drew a second, misleading `is declared after this point`.
        optional_static = self._resolve_type_alias(resolved_type).is_optional()
        if optional_static:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"static `{static.name}` may not have an optional type "
                f"(`{resolved_type}`): a static is initialized once at compile "
                f"time and never changes, so it is always present",
                static.line, static.column, source_file=static.source_file,
                hint="declare it as the payload type and give it a real value "
                     "(`static SLOT: Int = 7`); if absence is genuinely part "
                     "of the state, that state has to be COMPUTED — use "
                     "`static X: Once<T>` (set once) or `unsafe static var`"
            )

        # design 149 unit d: a `SpinLock` static on a target with no atomic
        # instruction. Checked here as well as at every expression, because a
        # lockable static is the headline use and its declaration is not one.
        if not self._atomics_native:
            self._check_spinlock_target(resolved_type, static)

        # design 46: `UnsafeMemory<T, Use>` statics — validate the intent marker
        # is present and explicit (`Device`/`Normal`).
        if self._is_unsafe_memory(resolved_type):
            self._validate_unsafe_memory_type(resolved_type, static.line, static.column)

        # Const-init only. A bare declaration (no initializer) is a zero-init,
        # permitted only for POD / fixed-array statics (design 41 item 2: no
        # repeat-literal exists, so bare zero-init is the chosen mechanism for
        # large zero regions like slab buffers).
        if optional_static:
            pass                      # DF-226f already refused the declaration
        elif static.initializer is None:
            if not self._is_zero_initable_type(resolved_type):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"static `{static.name}` needs an initializer: a static may "
                    f"be declared without one only when all-zero is a valid "
                    f"value of its type",
                    static.line, static.column, source_file=static.source_file,
                    hint="add `= <constant>`, or use a type whose storage is "
                         "scalar throughout (a POD struct, `[T; N]`, "
                         "`Atomic<Int>`, `SpinLock<T>` over one)"
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
            # design 186 unit 7: a static initializer IS a const position. That
            # is what lets `static RW: UInt8 = Perm.Read | Perm.Write` read its
            # operands as the compile-time tags they are (design 185 unit 3)
            # instead of as enum-typed values, which is the second of the two
            # refusals DF-185b was pinned on.
            # design 207's annotation-driven cell at the STATIC slot — the
            # position DF-294d filed from, where a generic head otherwise
            # writes its type twice on a line that cannot break.
            with self._const_position(), self._decl_slot(static.initializer,
                                                         resolved_type):
                init_type = self._check_expression(static.initializer)
            self._stamp_static_init_names(static.initializer)
            self.current_scope = saved_scope
            # design 205: a static initializer is a TRANSFER, but this call is
            # written (declared, actual) — the reverse of `_types_compatible`'s
            # own (source, target) convention — and swapping it outright would
            # change the ALIAS answer too, which is what
            # `static_named_array_type_init` (`unsafe static var ARENA: Region =
            # [0; 8]` for a `type Region = [Int; 8]`) rides. So the integer
            # question, the only one whose answer depends on direction, is asked
            # separately and in the right order; everything else keeps the
            # relation it had.
            _int_refused = (self._int_transfer_pair(init_type, resolved_type)
                            and not self._transfer_compatible(init_type,
                                                              resolved_type))
            if init_type is not None and (
                    _int_refused
                    or not self._types_compatible(resolved_type, init_type)):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"static `{static.name}` has type `{resolved_type}` but its "
                    f"initializer has type `{init_type}`",
                    static.line, static.column, source_file=static.source_file,
                    hint=self._int_conversion_hint(init_type, resolved_type)
                )
            if not self._is_const_init(static.initializer):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"static `{static.name}` must be initialized by a compile-time "
                    f"constant",
                    static.line, static.column, source_file=static.source_file,
                    hint="a static initializer is a CONSTANT EXPRESSION plus "
                         "memberwise aggregation: literals, arithmetic and "
                         "bitwise over them, `sizeof`/`alignof`, the integer "
                         "limits, a raw-backed enum case, an earlier module "
                         "`static`, and struct / fixed-array literals built out "
                         "of those. A user `init` BODY never runs at compile "
                         "time, and neither does a function call, a String or "
                         "any heap type — state that has to be COMPUTED wants "
                         "`static X: Once<T>` (set once) or `unsafe static var` "
                         "(mutated throughout)"
                )

        # Sync-only: an immutable static is reachable from every task, so its
        # type must be Sync (design 21 structural derivation).
        #
        # design 149: an `unsafe static var` is EXEMPT, because Sync is the claim
        # it is already making by hand. The compound state this exists for —
        # a handle table of slots holding raw pointers, PMP shadow state — is
        # structurally non-Sync exactly where it is most wanted, and the
        # serialization argument that makes it safe (interrupts off, single
        # core, boot only) is the thing `unsafe` names. Requiring a derivation
        # the author has already overridden would only push them back to
        # hand-rolled C.
        if not static.is_var and not self.namespace.is_sync(resolved_type):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"static `{static.name}` has non-Sync type `{resolved_type}`; "
                f"statics must be Sync (shared across all tasks)",
                static.line, static.column, source_file=static.source_file,
                hint="use a Sync type — mutation of global state flows only "
                     "through interior-synchronized types like `Atomic<Int>` "
                     "and `SpinLock<T>`, or declare an `unsafe static var` and "
                     "own the serialization argument."
                     + self.namespace.thread_safety_note(resolved_type, True)
            )

        # Immortal: statics never run deinit. v1 of design 149 keeps that true by
        # restricting mutable statics to TRIVIALLY-DESTRUCTIBLE types, so there
        # is never a destructor that should have run and did not.
        if self._static_needs_destruction(resolved_type):
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
        # DF-172j: what this static means in a constant position rides on the
        # symbol, so an importing module gets the same answer — including under
        # a rename, where the simple name no longer finds the declaration.
        const_value, const_reject = (
            getattr(self, '_const_static_decls', None) or {}
        ).get((def_module, static.name), (None, None))
        self.namespace.register_static(static.name, StaticSymbol(
            type=resolved_type,
            mangled_name=mangled,
            visibility=visibility,
            is_var=static.is_var,
            line=static.line,
            column=static.column,
            def_module=def_module,
            const_value=const_value,
            const_reject=const_reject
        ))

    def _is_zero_initable_type(self, t: SawType, seen=None) -> bool:
        """Whether a bare (initializer-less) static of type `t` is allowed.

        The question is whether all-zero is a VALID value of `t` — which is what
        lets the global be emitted as zerofill and cost no image bytes. POD
        (trivially copyable) says yes, and so does a fixed array of one.

        design 149 adds the case a declared copy POLICY was hiding: a struct
        whose storage is entirely zero-initable but which declares `NoCopy`
        (because copying it would be a bug) is not trivially copyable and was
        therefore refused. That is exactly `SpinLock<T>` over a POD payload,
        where all-zero means "unlocked, payload zeroed" — the one spelling that
        makes a lockable static both const-initializable and free. Copyability
        is irrelevant to a static, which is never copied and never moves.
        """
        if t is None:
            return False
        if t.kind == TypeKind.ARRAY:
            return t.array_element_type is not None and \
                self._is_zero_initable_type(t.array_element_type, seen)
        if self.namespace.is_trivially_copyable(t):
            return True
        if t.kind != TypeKind.STRUCT or not t.struct_name:
            return False
        # A struct that would need destruction has state beyond its bytes; zeros
        # are not a valid value of it (a zeroed `String` is a null buffer).
        if self._static_needs_destruction(t):
            return False
        seen = seen or set()
        if t.struct_name in seen:
            return False
        fields = self._static_field_types(t)
        if fields is None:
            return False
        return all(self._is_zero_initable_type(ft, seen | {t.struct_name})
                   for ft in fields.values())

    def _static_field_types(self, t: SawType):
        """Field types of struct `t` with its type arguments substituted, or None
        when the struct's fields are not known.

        `SpinLock<HandleTable>` has to report a `value: HandleTable`, not the
        template's `value: T`, or every question asked about a generic static's
        storage answers about a type parameter instead.
        """
        fields = self.namespace.get_struct_fields(t.struct_name)
        if not fields:
            return None
        sym = self.namespace.lookup_struct(t.struct_name)
        node = getattr(sym, 'ast_node', None) if sym else None
        params = getattr(node, 'type_params', None) or []
        if not (params and t.type_args):
            return dict(fields)
        mapping = {tp.name: ta for tp, ta in zip(params, t.type_args)}
        return {fn: (ft.substitute(mapping) if ft is not None else ft)
                for fn, ft in fields.items()}

    def _static_needs_destruction(self, t: SawType, seen=None) -> bool:
        """Whether never destroying a static of type `t` would drop something real.

        Statics are immortal, so this is the honest form of the immortality rule
        (design 149 replaces the conformance test that stood here). What matters
        is not whether the type DECLARES a copy policy — `NoCopy` says "do not
        duplicate me", which has nothing to say about a value that is never
        duplicated — but whether a destructor exists that would have done work: a
        hand-written `deinit`, or a field that owns a resource. A struct of
        integers declaring `NoCopy` needs no destruction; a `String` field does,
        whoever declares what.

        This is also design 149's v1 restriction on `unsafe static var` —
        trivially-destructible types only — stated once, for every static.
        """
        if t is None:
            return False
        kind = t.kind
        if kind == TypeKind.STRING:
            return True
        if kind == TypeKind.FUNCTION:
            return bool(getattr(t, 'func_is_escaping', False))
        if kind == TypeKind.ARRAY:
            return self._static_needs_destruction(t.array_element_type, seen)
        if kind == TypeKind.OPTIONAL:
            return self._static_needs_destruction(t.inner_type, seen)
        if kind == TypeKind.TUPLE:
            return any(self._static_needs_destruction(e, seen)
                       for e in (t.element_types or []))
        name = (t.struct_name if kind == TypeKind.STRUCT
                else t.enum_name if kind == TypeKind.ENUM else None)
        if name is None:
            return False
        seen = seen or set()
        if name in seen:
            return False
        seen = seen | {name}
        # A hand-written destructor is the thing skipping destruction would drop.
        # The empty `deinit` synthesized for a declared copy policy (design 131)
        # lowers to the structural field drops and nothing else, so it is not one.
        deinit = self.namespace.lookup_method(name, "deinit")
        if deinit is not None and not getattr(
                getattr(deinit, 'ast_node', None), 'is_synthesized', False):
            return True
        enum_info = self.get_enum_info(name)
        if enum_info is not None:
            return any(self._static_needs_destruction(ft, seen)
                       for payload in (enum_info.variants or {}).values()
                       for _fn, ft in payload)
        fields = self._static_field_types(t)
        if not fields:
            return False
        return any(self._static_needs_destruction(ft, seen)
                   for ft in fields.values())

    def _is_const_init(self, expr) -> bool:
        """Whether `expr` is a compile-time constant static initializer.

        TWO TIERS, and the line between them is the whole rule (design 186
        unit 7, absorbing DF-185b):

          * a CONSTANT EXPRESSION — whatever `const_eval` folds. Design 41's
            list was literals-only and lived apart from the evaluator, so
            `static SIZE: Int = 4 * 1024` was refused while the same expression
            folded in every position that CONSUMES a constant. One evaluator now
            answers in all of them.
          * MEMBERWISE AGGREGATION over those — a struct literal, a fixed-array
            literal, an interior cell, `Atomic(<int>)`, `UnsafeMemory(<int>)`.

        A user `init` BODY never runs at compile time, even where it visibly
        would fold: folding bodies is const-fn, and this is deliberately not
        the design that backs into it. A memberwise `Wrap<Int>(v: 3)` is a
        `StructInit` and lands in the second tier; `Wrap<Int>(3)` resolving to a
        hand-written `init` is a call, and falls off the end here.
        """
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
            # MEMBERWISE only. The parser gives `Region(bytes: 1, pages: 2)` and
            # `Region(pages: 2)` the same node shape, and the second reaches a
            # hand-written `init` — whose BODY would have to run to produce the
            # missing fields. Naming every field is what tells them apart, and
            # it is exactly the tier line: aggregation folds, bodies do not.
            from type_identity import declaration_base
            fields = self.namespace.get_struct_fields(
                declaration_base(expr.struct_name or "")) or {}
            written = {n for n, _v in expr.field_inits}
            if not fields or written != set(fields.keys()):
                return False
            return all(self._is_const_init(v) for _n, v in expr.field_inits)
        if isinstance(expr, FunctionCall) and getattr(expr, 'is_atomic_construct', False):
            return all(self._is_const_init(a.value) for a in expr.arguments)
        # design 186: `UnsafeMutableInterior(<const>)` wraps a constant with no
        # storage of its own (the cell is layout-transparent), so a cell is as
        # const-initializable as the value it holds. This is what lets a
        # cell-carrying static be written at a non-zero seed instead of only at
        # the all-zero one.
        if isinstance(expr, FunctionCall) and getattr(
                expr, 'is_interior_cell_construct', False):
            return all(self._is_const_init(a.value) for a in expr.arguments)
        # design 46: `UnsafeMemory(<int>)` is a const-init from an address literal.
        if isinstance(expr, FunctionCall) and getattr(expr, 'is_unsafe_mem_construct', False):
            return all(self._is_const_init(a.value) for a in expr.arguments)
        # design 226: a `FuncPointer` built by COERCION is a LINK-TIME constant —
        # the address of a symbol this compilation unit emits. It folds to no
        # number, so the evaluator tier below cannot answer for it, and it is
        # neither an aggregate nor a call. A dispatch table of handlers is the
        # headline use of the type, and a table is a `static`, so this row is
        # not an afterthought: without it the type's most natural home is the
        # one position that refuses it.
        if getattr(expr, 'funcpointer_target', None) is not None:
            return True
        # The CONSTANT-EXPRESSION tier: anything the one evaluator folds. Asked
        # last so the aggregate arms above keep their own (cheaper, structural)
        # answers, and asked by TRYING rather than by re-listing the grammar —
        # re-listing is what let design 41's rule drift away from the evaluator
        # in the first place.
        return self._folds_as_constant(expr)

    def _stamp_static_init_names(self, expr) -> None:
        """Resolve the constants a static initializer names, onto its own nodes.

        `_stamp_const_names` walks an EXPRESSION; a static initializer is an
        expression OR an aggregate built out of them, and the names live at the
        leaves (`static ONE: Region = Region(bytes: PAGE_SIZE, pages: 1)`). This
        recurses through the aggregate shapes `_is_const_init` accepts and
        stamps each leaf, so the evaluator sees numbers where the source wrote
        names — the same trick DF-172j plays for an array length, applied one
        level down.
        """
        from ast_nodes import ArrayLiteral, StructInit, FunctionCall
        if isinstance(expr, ArrayLiteral):
            for element in expr.elements:
                self._stamp_static_init_names(element)
            if expr.repeat_count is not None:
                self._stamp_static_init_names(expr.repeat_count)
            return
        if isinstance(expr, StructInit):
            for _name, value in expr.field_inits:
                self._stamp_static_init_names(value)
            return
        if isinstance(expr, FunctionCall):
            for arg in expr.arguments:
                self._stamp_static_init_names(arg.value)
            return
        self._stamp_const_names(expr)

    def _folds_as_constant(self, expr) -> bool:
        """Does the one const evaluator fold `expr` to a number here?"""
        from const_eval import const_eval, ConstEvalError
        try:
            const_eval(expr, env=self._const_param_env(),
                       width=self.platform_int_width)
        except ConstEvalError:
            return False
        return True

    # Built-in type names that indicate specialization when used in extension type params
    BUILTIN_TYPE_NAMES = {
        'Int', 'UInt', 'Float', 'Bool', 'String',
        'Int8', 'Int16', 'Int32', 'Int64',
        'UInt8', 'UInt16', 'UInt32', 'UInt64',
    }

    # Primitive types that carry method extensions (design 57): the pseudo-struct
    # name maps to the primitive SawType used for `self`.
    # DF-225d: THE table, not a copy of it — see `ast_nodes.PRIMITIVE_EXT_KINDS`.
    # This one WAS a copy, and it was the copy design 176 did not widen: it held
    # {String, Int, Float} while the conformance and codegen maps held all
    # thirteen, so `self` inside `extension UInt8` was a STRUCT named "UInt8"
    # and every use of it as a value of its own type failed against a type
    # printed identically.
    PRIMITIVE_EXT_SELF_KINDS = PRIMITIVE_EXT_KINDS

    def _primitive_ext_self_type(self, name):
        """The `self` SawType for a method in an extension on a primitive
        pseudo-struct, or None for an ordinary struct.

        Every primitive is one since design 176 — the whole set an
        `extension <primitive>: Trait` may name."""
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

    def _ext_written_self_type(self, extension) -> SawType:
        """`Self` as this extension's SIGNATURE may WRITE it (DF-216r).

        Distinct from `_ext_self_type`, which answers for the RECEIVER. On a
        GENERIC extension that one is deliberately ARGUMENT-FREE — `Wrap`, not
        `Wrap<T>` — because naming the extension's own parameters as arguments
        makes a payload binding and a `T` parameter resolve through different
        routes to two `T`s that do not unify; codegen names the concrete
        monomorphization from `self_type_context` instead.

        A WRITTEN position cannot use that spelling: substituting a bare `Wrap`
        into a signature names a struct no monomorphization ever registered, so
        the clean type error becomes `internal compiler error: Undefined
        struct: Wrap` (verified while fixing DF-216f, which is why
        `_self_type_is_substitutable` exists). What a written `Self` means
        there is the extension APPLIED TO ITS OWN PARAMETERS — `Wrap<T>` for
        `extension Wrap<T>`, `Wrap<U>` for `extension Wrap<U>` — which is
        exactly the spelling a user may write by hand today, and which the
        receiver's type arguments then substitute at the call site through
        machinery that already existed. No new substitution funnel: the fix is
        entirely in what `Self` DENOTES.

        Falls back to the argument-free answer, unchanged, when the extension
        has no parameters, when its `Self` already carries arguments (a
        specialized extension, or design 145's generic enum), or when any
        parameter is a CONST one — a const parameter is a value, not a type
        argument this can spell abstractly, and leaving it alone keeps today's
        clean refusal rather than inventing a wrong answer.
        """
        base = self._ext_self_type(extension.struct_name)
        params = getattr(extension, 'type_params', None) or []
        if not params or base.kind not in (TypeKind.STRUCT, TypeKind.ENUM):
            return base
        if getattr(base, 'type_args', None):
            return base
        if any(getattr(tp, 'is_const', False) for tp in params):
            return base
        # Built and resolved exactly as the HAND-WRITTEN `Wrap<T>` annotation
        # is: a bare name parses STRUCT-kinded with STRUCT-kinded arguments,
        # and `_resolve_type` is what classifies each one (a type parameter in
        # scope, or the concrete type a SPECIALIZED extension names) and what
        # applies design 144's identity rewrite. Composing the SawType by hand
        # instead produced a type that PRINTED `Wrap<T>` and compared unequal
        # to the one a constructor expression yields.
        composed = SawType(
            TypeKind.STRUCT, struct_name=extension.struct_name,
            type_args=[SawType(TypeKind.STRUCT, struct_name=tp.name)
                       for tp in params])
        resolved = self._resolve_type(composed)
        if resolved is None:
            return base
        if base.kind == TypeKind.ENUM and resolved.kind != TypeKind.ENUM:
            # Design 145: an enum written as a bare name resolves STRUCT-kinded
            # on some paths, and a STRUCT-kinded `self` carries no variants.
            import dataclasses
            return dataclasses.replace(
                base, type_args=getattr(resolved, 'type_args', None))
        return resolved

    @staticmethod
    def _nominal_name(t):
        """The bare NAME of a nominal type, or None for anything else."""
        if t is None:
            return None
        if t.kind == TypeKind.STRUCT:
            return t.struct_name
        if t.kind == TypeKind.ENUM:
            return t.enum_name
        return None

    def _init_return_names_receiver(self, candidate, self_type, written_self):
        """Whether `candidate` NAMES an `init`'s receiver.

        The NAME must match; the type ARGUMENTS are compared only where both
        sides spell them, on their rendered form. Both halves of that are
        deliberate. The compiler has two receiver answers and they disagree
        about arguments on purpose (DF-216r): `_ext_self_type` is
        argument-free, `_ext_written_self_type` applies the extension to its own
        parameters — but it BAILS OUT to the argument-free spelling for a
        specialized extension and for a CONST parameter, and std's
        `extension FixedBuf<N>` writes `init() -> FixedBuf<N>` by hand. So where
        the compiler declines to spell the receiver's arguments it cannot hold
        the declaration to them either. Where it does spell them it is the
        authority, which keeps `-> Pair<Int>` inside `extension Pair<A>` refused
        — a declared return the call site would silently disagree with, which is
        the shape DF-245a filed.
        """
        if candidate is None:
            return False
        if candidate.kind == TypeKind.SELF:
            return True
        name = self._nominal_name(candidate)
        if name is None:
            return False
        receivers = ([written_self]
                     if (written_self is not None
                         and getattr(written_self, 'type_args', None))
                     else [written_self, self_type])
        for receiver in receivers:
            if self._nominal_name(receiver) != name:
                continue
            recv_args = getattr(receiver, 'type_args', None) or []
            cand_args = getattr(candidate, 'type_args', None) or []
            if not recv_args or not cand_args:
                return True
            if (len(recv_args) == len(cand_args)
                    and all(str(a) == str(b)
                            for a, b in zip(cand_args, recv_args))):
                return True
        return False

    def _init_declared_return(self, method, self_type, written_self, report):
        """THE `init` DECLARED-RETURN FUNNEL (DF-245a) — the one place that reads
        what an `init` writes after its `->`.

        An `init` may declare exactly two things (user ruling, Aug 24):

          * THE RECEIVER — `Self`, the receiver written out (`Pair<A>` inside
            `extension Pair<A>`), or no return clause at all, which is the
            historical implicit form. `T(args)` types as `T`.
          * `Result<Receiver, E>` — the FALLIBLE constructor. `T(args)` types as
            `Result<T, E>`, so it composes with `try`/`try!`/`try?`/`match`, the
            routing clause and design 151's discard error, and the BODY
            auto-wraps through `_autowrap_into_result` exactly as a
            Result-returning function's body does.

        Everything else is refused HERE, at the declaration, naming the two legal
        forms. An OPTIONAL gets its own wording: an optional creation encodes as
        a `Result`, because a `None` names no cause — the never-hide-errors
        doctrine, at a constructor.

        RETURNS a `(verdict, type)` pair — `('receiver', None)`,
        `('result', <the resolved Result>)`, or `('refused', <what the author
        actually wrote, resolved>)`. The receiver's own SPELLING is the caller's
        business and the two callers disagree about it on purpose (DF-216r
        again), so settling that here would be wrong. A REFUSED declaration
        hands back the author's own type so the body can be checked against the
        signature it was written for: the declaration is already wrong and said
        so once, and re-judging the body against a receiver it never claimed
        would print a second error about the same mistake.

        ENTRY POINTS — the two consumers of an `init`'s signature, whose
        disagreement is precisely what DF-245a filed (the call side derived the
        constructed type from the receiver and ignored the written return; the
        body side checked `return` against the written one; nothing reconciled
        them, so a wrong return type was two types and an unverifiable module):
          1. `register_extension` — the DECLARATION side, which registers the
             symbol every `T(...)` resolves against. REPORTS.
          2. `_check_method`      — the BODY side, which checks the tail and
             every `return` against it. Silent: the declaration has already been
             judged, and reporting at both would double every diagnostic.
        There is no third site. An enum extension refuses `init` outright
        (design 145) and a trait has no `init` requirement, so an extension
        member is the only place an `init` is ever written.
        """
        declared = getattr(method, 'return_type', None)
        # No return clause at all, or the bare `Self` keyword: the receiver.
        if declared is None or declared.kind in (TypeKind.VOID, TypeKind.SELF):
            return ('receiver', None)
        resolved = self._substitute_self_type(
            self._resolve_type(declared), written_self)
        if self._init_return_names_receiver(resolved, self_type, written_self):
            return ('receiver', None)
        ok_payload = resolved.unwrap_result_ok() if resolved.is_result() else None
        if ok_payload is not None and self._init_return_names_receiver(
                ok_payload, self_type, written_self):
            return ('result', resolved)
        if not report:
            return ('refused', resolved)

        receiver_txt = str(written_self if written_self is not None else self_type)
        two_forms = (f"`-> {receiver_txt}` (or `-> Self`) for an initializer "
                     f"that cannot fail, or `-> Result<{receiver_txt}, E>` for "
                     f"one that can")
        if resolved.is_optional():
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`init` may not return an optional — an optional creation "
                f"encodes as `Result<{receiver_txt}, E>`, because a `None` "
                f"names no cause",
                method.line, method.column,
                hint=f"write `-> Result<{receiver_txt}, E>` naming the error "
                     f"the absence meant, and return that error where the "
                     f"`None` was"
            )
        elif ok_payload is not None:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"the `Ok` payload of an `init`'s `Result` must be the receiver "
                f"`{receiver_txt}`, but this one is `{ok_payload}`",
                method.line, method.column,
                hint=f"an `init` builds its own type — write {two_forms}"
            )
        else:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`init` returns `{resolved}`, which is neither the receiver "
                f"`{receiver_txt}` nor `Result<{receiver_txt}, E>` — an `init` "
                f"may declare only those two",
                method.line, method.column,
                hint=f"write {two_forms}"
            )
        return ('refused', resolved)

    @staticmethod
    def ext_param_aliases(ext_type_params, declared_type_params):
        """The shared definition — see `ast_nodes.ext_param_aliases`. Kept as a
        method because the typechecker's three readers spell it `self.`; the
        RULE has exactly one home, which codegen reads directly."""
        return ext_param_aliases(ext_type_params, declared_type_params)

    def _ext_rename_subst(self, extension) -> Dict[str, SawType]:
        """The definition-side half of DF-216h: the type's declared parameters
        expressed in the EXTENSION's names, so a method body reads the type's
        storage in the names its own signature is written in.

        Positional and TOTAL when any position renames — every declared
        parameter gets an entry, identity included — because `_check_method`
        rebuilds the receiver's type arguments from this map's values in order.
        Empty (today's answer, an argument-free receiver) when nothing renames.
        """
        struct_info = (self.get_struct_info(extension.struct_name)
                       or self.get_enum_info(extension.struct_name))
        declared = list(getattr(struct_info, 'type_params', None) or [])
        ext_params = list(getattr(extension, 'type_params', None) or [])
        if not declared or not ext_params:
            return {}
        if any(getattr(tp, 'is_const', False) for tp in ext_params):
            # A const parameter is a VALUE, not a type argument this can spell
            # abstractly — the same carve-out `_ext_written_self_type` makes.
            return {}
        if not self.ext_param_aliases(ext_params, declared):
            return {}
        subst: Dict[str, SawType] = {}
        for i, tp in enumerate(declared):
            alias = (ext_params[i].name if i < len(ext_params) else tp.name)
            subst[tp.name] = SawType(TypeKind.STRUCT, struct_name=alias)
        return subst

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
    _ENUM_POLICY_TRAITS = ("NoCopy", "Copy", "ExplicitCopy")

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

        `Copy` and `ExplicitCopy` derive a payload-deep `copy` — None of
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

    @staticmethod
    def _replace_self_type(t, concrete):
        """Substitute `Self` for `concrete` throughout `t` (design 169).

        `Deserialize` declares `-> Result<Self, DecodeError>`, so the derived
        method's return type is the trait's own with one node swapped. Taking the
        signature FROM THE TRAIT rather than rebuilding it by hand is what keeps
        the derived method's type identical to the requirement it satisfies —
        a hand-built `Result` would be a STRUCT-kinded parse shape that had never
        been through type resolution.
        """
        if t is None:
            return None
        if t.kind == TypeKind.SELF:
            return copy.deepcopy(concrete)
        t.inner_type = RegistrationMixin._replace_self_type(t.inner_type, concrete)
        if t.type_args:
            t.type_args = [RegistrationMixin._replace_self_type(a, concrete)
                           for a in t.type_args]
        return t

    def _serde_derived_signature(self, extension: Extension, trait_name: str,
                                 method_name: str, is_enum: bool):
        """A derived serde method with the trait's signature and an EMPTY body.

        The body is filled by `_synthesize_serde_bodies` after every type is
        registered; only the signature is needed now, so callers type-check and
        the conformance check passes.
        """
        trait_info = self.get_trait_info(trait_name)
        if trait_info is None:
            return None
        tmsym = trait_info.methods.get(method_name)
        tm_ast = getattr(tmsym, 'ast_node', None) if tmsym else None
        if tm_ast is None:
            return None
        concrete = SawType(TypeKind.ENUM, enum_name=extension.struct_name) \
            if is_enum else SawType(TypeKind.STRUCT,
                                    struct_name=extension.struct_name)
        params = copy.deepcopy(tm_ast.parameters)
        for p in params:
            p.type = self._replace_self_type(p.type, concrete)
        return Method(
            name=method_name,
            parameters=params,
            return_type=self._replace_self_type(
                copy.deepcopy(tm_ast.return_type), concrete),
            body=Block(statements=[], final_expr=None,
                       line=extension.line, column=extension.column),
            is_init=False,
            self_mutable=getattr(tm_ast, 'self_mutable', False),
            self_is_reference=getattr(tm_ast, 'self_is_reference', True),
            # design 236: a synthesized Method is not authored source, so it
            # never faces the parser's agreement check — but the kinds it
            # reports must still MATCH the requirement it was built from, since
            # that is what `_check_trait_conformance` compares. `declared_static`
            # carries the same answer so `--emit-docs` renders the derived
            # `deserialize` with the keyword its requirement spells.
            is_static=not any(p.name == "self" for p in params),
            declared_static=not any(p.name == "self" for p in params),
            is_sync=getattr(tm_ast, 'is_sync', False),
            type_params=[],
            line=extension.line,
            column=extension.column,
            source_file=getattr(extension, 'source_file', None),
        )

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
                        # design 236: a default body on a STATIC requirement
                        # synthesizes a static conformer method. Hardcoding
                        # `False` here made the copy claim a receiver it has no
                        # parameter for, which the kind-agreement check would
                        # now report against the conformer.
                        is_static=getattr(tm_ast, 'is_static', False),
                        declared_static=getattr(tm_ast, 'is_static', False),
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
    _RESOURCE_TRAITS = ("Deinit", "NoCopy", "Copy", "ExplicitCopy")

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
                 f"`ExplicitCopy`, or `Copy`, and put the `deinit` body "
                 f"inside it — every copy policy already requires `Deinit`",
            source_file=getattr(extension, 'source_file', None)
        )
        return True

    # Traits the compiler derives structurally and never accepts as a written
    # conformance — rejected on their own terms elsewhere, so the orphan rule
    # stays out of their diagnostics.
    _STRUCTURAL_MARKER_TRAITS = frozenset({"Send", "Sync", "Deinit"})

    # ---------------------------------------------------------- design 186
    # `UnsafeSend` / `UnsafeSync`: the declared thread-safety assertion.

    _THREAD_BOUND_NAMES = ("Send", "Sync")

    def _register_thread_assertion(self, extension: Extension,
                                   trait_name: str) -> None:
        """Check and record one `extension T: UnsafeSend/UnsafeSync {}`.

        The conformance header IS the audited assertion, so the legality rule
        keeps it honest at exactly the line a reviewer reads: you may assert
        only where the DERIVATION FAILED, and only past fields the unsafe domain
        already owns. Asserting past a safe non-`Sync` field would be a claim
        about someone else's invariants, which is the one thing the `Unsafe`
        prefix does not license.

        Conditional headers are supported and are half the point — the bounds
        are recorded and re-checked per instantiation, so
        `extension Mutex<T: Send>: UnsafeSync {}` promises nothing about a
        `Mutex<File>`.
        """
        want_sync = (trait_name == "UnsafeSync")
        derived_name = "Sync" if want_sync else "Send"
        type_name = extension.struct_name
        where = (extension.line, extension.column)
        source_file = getattr(extension, 'source_file', None)

        if self._get_specialization_key(extension):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{trait_name}` cannot be declared on one instantiation of "
                f"`{type_name}`",
                *where, source_file=source_file,
                hint=f"write the conditional form instead — `extension "
                     f"{type_name}<T: {derived_name}>: {trait_name} {{}}` "
                     f"asserts it for exactly the instantiations that qualify")
            return

        sym = (self.namespace.lookup_struct(type_name)
               or self.namespace.lookup_enum(type_name))
        if sym is None:
            self._error(
                ErrorKind.UNDEFINED_VARIABLE,
                f"unknown type `{type_name}`", *where, source_file=source_file)
            return

        params = list(getattr(sym, 'type_params', None) or [])
        ext_params = list(extension.type_params or [])
        # Positional over the TYPE's parameters: the extension names them in
        # the same order, and a header may leave a parameter unbounded.
        bounds_by_index = []
        assume_send, assume_sync = set(), set()
        for index, param in enumerate(params):
            written = ext_params[index] if index < len(ext_params) else None
            names = list(getattr(written, 'bounds', None) or [])
            for bound in names:
                simple = bound.rsplit('.', 1)[-1]
                if simple in ("UnsafeSend", "UnsafeSync"):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"`{simple}` is not usable as a bound",
                        *where, source_file=source_file,
                        hint=f"bound the parameter on the PROPERTY — "
                             f"`{simple[6:]}` — which a declared `{simple}` "
                             f"satisfies through it")
                    return
                if simple == "Send":
                    assume_send.add(getattr(written, 'name', None))
                elif simple == "Sync":
                    assume_sync.add(getattr(written, 'name', None))
            bounds_by_index.append([b.rsplit('.', 1)[-1] for b in names])

        kind = (TypeKind.ENUM if self.namespace.lookup_enum(type_name)
                and not self.namespace.lookup_struct(type_name)
                else TypeKind.STRUCT)
        self_args = [SawType(TypeKind.STRUCT, struct_name=p.name)
                     for p in params]
        self_type = (SawType(kind, enum_name=type_name, type_args=self_args)
                     if kind == TypeKind.ENUM
                     else SawType(kind, struct_name=type_name,
                                  type_args=self_args))
        assume = (assume_send, assume_sync)

        if self.namespace._send_sync(self_type, want_sync, set(), assume):
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`{type_name}` already derives `{derived_name}`, so "
                f"`{trait_name}` asserts nothing",
                *where, source_file=source_file,
                hint=f"delete the declaration — an assertion is only legal "
                     f"where the structural derivation FAILED, and reading one "
                     f"beside a type that derives cleanly would teach the next "
                     f"reader the wrong thing")
            return

        blockers = self.namespace.blocking_members(self_type, want_sync, assume)
        for field_name, field_type in blockers:
            if self._type_tree_has_unsafe(field_type):
                continue
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot declare `{trait_name}` for `{type_name}`: field "
                f"`{field_name}` has type `{field_type}`, which is not "
                f"`{derived_name}` and is not an unsafe type",
                *where, source_file=source_file,
                hint=f"an assertion may cover only what the unsafe domain "
                     f"already owns — an interior cell, an `UnsafePointer`, an "
                     f"`UnsafeMemory`. Asserting past a SAFE field is a claim "
                     f"about someone else's invariants; bound the parameter "
                     f"(`<T: {derived_name}>`) or hold the field behind a type "
                     f"that carries the synchronization")
            return

        if not blockers:
            # Nothing blocked and nothing derived: the type is opaque here
            # rather than proven safe, so there is nothing to assert ABOUT.
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"cannot declare `{trait_name}` for `{type_name}`: it has no "
                f"member that blocks `{derived_name}`",
                *where, source_file=source_file,
                hint="an assertion names something the compiler could not see; "
                     "with nothing blocking, there is nothing to assert")
            return

        table = self.namespace.thread_assertions.setdefault(type_name, {})
        table[trait_name] = bounds_by_index

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
        self._check_consumes_containment(extension)
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

        # Memberwise `copy()` derivation: a struct declaring Copy or
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
            (t for t in ("Copy", "ExplicitCopy")
             if t in extension.conformances), None)
        declares_copy_policy = declared_copy_policy is not None
        has_copy_method, already_derived = self._derivation_slot(
            extension, "copy", "is_derived_copy")
        # design 219 unit A1 (DF-217r): a hand-written `copy()` inside a
        # copy-policy conformance is the RETAIN HOOK — codegen inserts a call to
        # it at every silent transfer, at sites no source construct names. Stamp
        # it so the effect pass makes it a `sync` context and refuses a
        # suspending body AT this declaration rather than at an invisible call.
        if declares_copy_policy and has_copy_method:
            for m in extension.methods:
                if (not m.is_init and m.name == "copy"
                        and not getattr(m, "is_derived_copy", False)):
                    m.copy_policy_hook = declared_copy_policy
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
                        Parameter(name="other", type=_ref_self_type(),
                                  is_reference=True),
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
                        Parameter(name="other", type=_ref_self_type(),
                                  is_reference=True),
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

        # Structural serialization (design 169). Only the SIGNATURE is minted
        # here; the body is built by `_synthesize_serde_bodies` once every type
        # is registered, because the field walk reads a nested type's
        # conformance and an enum's raw backing. Enums come through this path
        # too — Serialize/Deserialize are deliberately NOT in
        # `_ENUM_DERIVABLE_TRAITS`, since unlike equals/compare/hash they mint a
        # real method rather than being inlined at the call site.
        for trait_name, method_name, flag in (
                ("Serialize", "serialize", "is_derived_serialize"),
                ("Deserialize", "deserialize", "is_derived_deserialize")):
            if trait_name not in extension.conformances:
                continue
            has_method, already = self._derivation_slot(
                extension, method_name, flag)
            if has_method:
                continue
            self._demand_synthesize_marker(extension, trait_name, method_name)
            derived_any = True
            if already is None:
                synth = self._serde_derived_signature(
                    extension, trait_name, method_name, is_enum)
                if synth is None:
                    continue
                setattr(synth, flag, True)
                extension.methods.append(synth)
            if trait_name == "Serialize":
                self._derived_serialize_types.add(extension.struct_name)
            else:
                self._derived_deserialize_types.add(extension.struct_name)

        # A marker that derived nothing is a mistake worth naming: either the
        # conformance already has a hand-written body (so nothing is derived) or
        # the trait has no derivation at all (Printable, a user trait).
        if has_synthesize(extension) and not derived_any:
            self._error(
                ErrorKind.TYPE_MISMATCH,
                f"`@synthesize` on `extension {extension.struct_name}` derives "
                f"nothing",
                extension.line, extension.column,
                hint="the derivable conformances are Copy/ExplicitCopy "
                     "(`copy`), Equatable (`equals`), Comparable (`compare`), "
                     "Hashable (`hash`), Serialize (`serialize`) and "
                     "Deserialize (`deserialize`), each with no hand-written body",
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

        # An extension RESOLVES its method signatures here (a free generic
        # function defers that to its body check, where `current_type_params`
        # is built), so this loop is the one place a `T` written in a generic
        # extension is classified with nothing telling the checker that `T` is
        # a parameter. Say so: the extension's own parameters plus, per method,
        # its own. Restored after the loop — see `_ext_type_param_env`.
        _prev_type_params = getattr(self, 'current_type_params', {})
        _ext_type_params = dict(_prev_type_params)
        for _tp in (extension.type_params or []):
            _ext_type_params[_tp.name] = _tp.bounds

        for method in extension.methods:
            self.current_type_params = dict(_ext_type_params)
            for _tp in (getattr(method, 'type_params', None) or []):
                self.current_type_params[_tp.name] = _tp.bounds

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
            # Determine the Self type for this extension. Two answers, and
            # DF-216r is the difference: the RECEIVER's `Self` stays
            # argument-free on a generic extension (codegen resolves it through
            # `self_type_context`), while a `Self` the signature WRITES carries
            # the extension's own parameters — see `_ext_written_self_type`.
            self_type = self._ext_self_type(extension.struct_name)
            written_self = self._ext_written_self_type(extension)

            # Resolve Self types in parameter types
            # Note: 'self' parameter has VOID as placeholder from parser
            param_types = []
            for p in method.parameters:
                if p.name == "self":
                    param_types.append(self_type)
                elif p.type.kind == TypeKind.SELF:
                    # A WRITTEN top-level `Self` — `other: Self`. Not the
                    # receiver, so it takes the written spelling.
                    param_types.append(written_self)
                else:
                    # Resolve type aliases and enum types, then substitute any
                    # NESTED `Self` — `&Self`, `Self?`, `Vector<Self>`,
                    # `(Self, Int)`, `[Self; N]`. The root-only test above is
                    # the whole of what used to happen here (DF-216f).
                    param_types.append(self._substitute_self_type(
                        self._resolve_type(p.type), written_self))
            param_names = [p.name for p in method.parameters]

            # For init methods, override return type to be the struct type
            # For non-init methods, resolve Self in return type
            return_type = method.return_type
            if method.is_init:
                # ENTRY POINT 1 of `_init_declared_return` (DF-245a): the
                # DECLARATION side. Answered before the `Self` test below,
                # because `Self` is one of the receiver spellings the funnel
                # judges and `Result<Self, E>` is one it accepts.
                _verdict, _declared = self._init_declared_return(
                    method, self_type, written_self, report=True)
                if _verdict == 'result':
                    return_type = _declared
                elif return_type.kind == TypeKind.SELF:
                    return_type = written_self
                else:
                    # An `init`'s return is the RECEIVER's spelling, not a
                    # written one — untouched by DF-216r.
                    return_type = self_type
            elif return_type.kind == TypeKind.SELF:
                return_type = written_self
            else:
                # Resolve enum types (e.g., Result<T, E>) that are parsed as
                # STRUCT, then substitute a NESTED `Self`: the root-only test
                # above left `-> Self?` and `-> (Self, Int)` unresolved, which
                # is the half of DF-216f the filing did not notice.
                return_type = self._substitute_self_type(
                    self._resolve_type(return_type), written_self)

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
                # Where this method's LOGICAL parameters start. A hardcoded 1
                # here sliced a `self` off every method, and a STATIC extension
                # method has none in its parameter list — so its first real
                # parameter, type and LABEL together, vanished from the identity
                # and any two statics agreeing on everything after slot 0
                # collided (DF-217e). `_overload_cand_offset` is the notion the
                # call-site resolver already uses; both sides read it now.
                new_offset = self._overload_cand_offset(method, True)
                new_keys = self._overload_shape_keys(
                    param_types[new_offset:], method.type_params,
                    default_values[new_offset:], param_names[new_offset:])
                collides = False
                for other in struct_info.method_overloads.get(method.name, []):
                    # Design 142: only a repeat within this defining module is a
                    # declaration-site duplicate (see the note above).
                    if (getattr(other, 'def_module', ()) or ()) != ext_def_module:
                        continue
                    o_off = self._overload_cand_offset(other, True)
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
                # DF-216h: the extension's OWN parameter names, so a call site
                # can bind them when they rename the struct's (see
                # `_receiver_type_subst`). Empty for a specialized extension —
                # its signatures are already concrete.
                owner_type_params=([] if is_specialized
                                   else list(extension.type_params or [])),
                is_unsafe=getattr(method, 'is_unsafe', False),
                is_consumes=getattr(method, 'is_consumes', False),
                visibility=getattr(method, 'visibility', Visibility.PRIVATE),
                def_module=ext_def_module,
                satisfies_trait=(method.name in trait_method_names
                                 or getattr(method, 'is_derived_copy', False)
                                 or getattr(method, 'is_derived_equals', False)
                                 or getattr(method, 'is_derived_compare', False)
                                 or getattr(method, 'is_derived_hash', False)
                                 or getattr(method, 'is_derived_serialize', False)
                                 or getattr(method, 'is_derived_deserialize', False)),
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

        self.current_type_params = _prev_type_params

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
                    hint=f"remove `: {trait_name}` - a type is {trait_name} "
                         f"automatically iff all its fields are; to ASSERT it "
                         f"where the derivation cannot see why it holds, "
                         f"declare `Unsafe{trait_name}` (design 186)"
                )
                continue
            # design 186: the declared thread-safety assertion. Legality is
            # checked here, at the declaration, because that is the line a
            # reviewer reads.
            if trait_name in ("UnsafeSend", "UnsafeSync"):
                self._register_thread_assertion(extension, trait_name)
                continue
            # Handle module-qualified trait names (e.g., "lib.Describable")
            if '.' in trait_name:
                # Module-qualified: look up in module namespace
                parts = trait_name.rsplit('.', 1)
                module_name, simple_trait_name = parts[0], parts[1]
                module_sym = self.namespace.modules.get(module_name)
                if module_sym and module_sym.namespace:
                    # design 229: a trait reached through a module comes off
                    # that module's surface like every other name.
                    trait_info = module_sym.namespace.resolve(
                        simple_trait_name, check_visibility=True,
                        accessor_module=self._accessor_vis_module(),  # DF-232j
                        through_import=True
                    )
                    if trait_info is None or trait_info.kind != SymbolKind.TRAIT:
                        self._error(
                            ErrorKind.UNDEFINED_VARIABLE,
                            f"unknown trait `{trait_name}`",
                            extension.line, extension.column,
                            hint=(self._not_reexported_hint(
                                      module_sym.namespace, simple_trait_name,
                                      module_name)
                                  or self._retired_trait_hint(trait_name))
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
                        extension.line, extension.column,
                        hint=self._retired_trait_hint(trait_name)
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

            # design 236 rule 4: the KINDS must agree. A static requirement is
            # satisfied only by a static, an instance requirement only by an
            # instance method. The two are not interchangeable in either
            # direction: a static has no receiver for a caller to supply, and an
            # instance method has no way to be reached without one — so a
            # mismatch is a conformance that could never be called through, and
            # the shared name is the only thing the two have in common. Since
            # design 236 both sides SPELL their kind, so this compares
            # declarations rather than inferring from the parameter list.
            if getattr(trait_method, 'is_static', False) != getattr(
                    impl_method, 'is_static', False):
                if getattr(trait_method, 'is_static', False):
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"method `{method_name}` must be declared `static` to "
                        f"conform to trait `{trait_info.name}`, whose "
                        f"requirement is static: it is called on the TYPE, so "
                        f"there is no receiver for this implementation's "
                        f"`self` to come from",
                        extension.line, extension.column,
                        hint=f"write `static func {method_name}(...)` and drop "
                             f"the `&self`/`&var self` parameter")
                else:
                    self._error(
                        ErrorKind.TYPE_MISMATCH,
                        f"method `{method_name}` may not be declared `static`: "
                        f"trait `{trait_info.name}` requires an INSTANCE "
                        f"method, which a caller reaches through a receiver "
                        f"this implementation does not take",
                        extension.line, extension.column,
                        hint=f"remove the `static` and take `&self` — "
                             f"`func {method_name}(&self, ...)`")
                continue

            # design 260 §4, the OTHER half of the no-trait-`consumes` fence.
            # The parser refuses `consumes` ON a requirement; this refuses a
            # consuming method SATISFYING one. A requirement is callable through
            # an erased `&any Trait` receiver, where the caller's `move` cannot
            # be spelled and there is no binding to retire — so a conforming
            # consuming body would release the referent out from under a caller
            # that never transferred it.
            if getattr(impl_method, 'is_consumes', False):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"method `{method_name}` is declared `consumes`, so it may "
                    f"not satisfy a requirement of trait `{trait_info.name}` "
                    f"(design 260 v1): a call through the requirement cannot "
                    f"spell the `(move x).{method_name}()` that transfers the "
                    f"receiver",
                    extension.line, extension.column,
                    hint=f"drop `consumes` from `{method_name}`, or give the "
                         f"consuming operation its own name outside the "
                         f"conformance")

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

            # design 188 unit 6 (DF-188h): a conformer of an `unsafe`
            # requirement must DECLARE the effect. The spec has said so since
            # design 130 — "a conformer of an unsafe trait requirement needs to
            # make [the promise]" — and nothing checked it, in either direction.
            #
            # This direction is the one that matters to a reader: the
            # requirement is what a caller through the existential sees, so an
            # impl that quietly drops the marker makes the vtable slot's
            # contract and the body's declaration disagree. It is not unsound
            # (an impl safer than its requirement is harmless, and the check
            # that protects the boundary — an UNDECLARED unsafe body reached
            # through a SAFE requirement — does fire), which is exactly why it
            # went unnoticed.
            #
            # The reverse direction stays legal: an `unsafe`-declared impl of a
            # safe requirement is rule 7's redundant declaration, allowed and
            # meaningful only about the body.
            if getattr(trait_method, 'is_unsafe', False) and not getattr(
                    impl_method, 'is_unsafe', False):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"method `{method_name}` must declare `unsafe` to conform "
                    f"to trait `{trait_info.name}`, whose requirement declares "
                    f"it: a caller reaching this through the requirement is "
                    f"promised an unsafe contract, so the implementation says "
                    f"so too",
                    extension.line, extension.column,
                    hint=f"write the effect in the post-parameter slot — "
                         f"`func {method_name}(&self) unsafe -> ...` (design "
                         f"136). The reverse is fine: an `unsafe` implementation "
                         f"of a SAFE requirement is allowed, and says something "
                         f"about the body only"
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
            else:
                self._check_conformance_param_references(
                    extension, type_name, trait_info, method_name,
                    trait_method, impl_method)

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

    def _check_conformance_param_references(self, extension, type_name,
                                            trait_info, method_name,
                                            trait_method, impl_method) -> None:
        """A conformance's parameters must MIRROR the requirement's borrows.

        The requirement is what a caller sees — through the operator lowering,
        through a generic bound, through a vtable — so an implementation that
        takes by value what the requirement lends, or lends what the requirement
        gives away, has a different ownership contract under one name. Design
        239 made that reachable: `Equatable.equals(&self, other: &Self)` and
        `Comparable.compare(&self, other: &Self)` are the requirements the
        comparison operators lower to, and a by-value `other` beneath one is the
        exact shape DF-216b's double free was made of.

        Reference-ness only, deliberately. Deep parameter typing is not checked
        here (it never was, and `Self` plus associated types make it a bigger
        question than this rule needs); the borrow SPELLING is decidable from
        the two declarations as written, is what the ABI depends on, and is what
        the reader was told.

        The mutability half rides along: a `&var` requirement satisfied by a `&`
        implementation promises the caller a write it cannot perform.
        """
        t_types = list(trait_method.param_types or [])
        t_names = list(trait_method.param_names or [])
        i_types = list(impl_method.param_types or [])
        i_names = list(impl_method.param_names or [])
        t_off = len(t_types) - len(t_names)
        i_off = 1 if (i_names and i_names[0] == "self") else 0
        for idx in range(len(t_names)):
            t_type = t_types[idx + t_off] if idx + t_off < len(t_types) else None
            i_type = i_types[idx + i_off] if idx + i_off < len(i_types) else None
            if t_type is None or i_type is None:
                continue
            t_ref = t_type.kind == TypeKind.REFERENCE
            i_ref = i_type.kind == TypeKind.REFERENCE
            name = t_names[idx]
            if t_ref and not i_ref:
                written = self._resolve_trait_type(
                    t_type, type_name, trait_info.name)
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"parameter `{name}` of `{method_name}` must be a "
                    f"reference: trait `{trait_info.name}` declares it "
                    f"`{t_type}`, and this implementation takes it by value "
                    f"(`{i_type}`)",
                    extension.line, extension.column,
                    hint=f"write `func {method_name}(&self, {name}: {t_type})` "
                         f"— on `{type_name}` that is `{written}`. A by-value "
                         f"parameter says the body may consume what it is "
                         f"given, and every caller of the requirement hands it "
                         f"a borrow")
            elif i_ref and not t_ref:
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"parameter `{name}` of `{method_name}` may not be a "
                    f"reference: trait `{trait_info.name}` declares it "
                    f"`{t_type}`, which transfers ownership to the body",
                    extension.line, extension.column,
                    hint=f"write `func {method_name}(&self, {name}: {t_type})`")
            elif t_ref and i_ref and (bool(t_type.reference_mutable)
                                      != bool(i_type.reference_mutable)):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"parameter `{name}` of `{method_name}` borrows "
                    f"`{i_type}` but trait `{trait_info.name}` declares "
                    f"`{t_type}`",
                    extension.line, extension.column,
                    hint="call sites mirror the requirement's reference "
                         "spelling, so the two have to agree")

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
        elif trait_type.kind == TypeKind.REFERENCE and trait_type.inner_type:
            # `&Self` — design 239's `equals`/`compare` operand, and the first
            # requirement type to nest `Self` behind a reference. Rebuilt around
            # the substituted referent, mutability carried, exactly as the
            # OPTIONAL arm below does: this walk RESOLVES, so it must return the
            # wrapper it was given.
            return SawType(
                TypeKind.REFERENCE,
                inner_type=self._resolve_trait_type(
                    trait_type.inner_type, self_type_name, trait_name),
                reference_mutable=trait_type.reference_mutable)
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
