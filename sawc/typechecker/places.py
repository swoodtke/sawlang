"""Element places: `lend` diagnostics, and recognizing a place USE.

The syntactic rules of a `borrows` body — the coverage rule, the no-lend-in-a-
loop rule, "a place is storage, not a temporary" — all live in
`place_transform.py`, which lowers a `borrows` declaration into its
window-closure form before type checking starts. By the time the checker runs,
a well-formed borrows body has no `lend` left in it.

Two things remain here.

The first is the one case the transform deliberately does NOT rewrite: a `lend`
in a body that never declared `borrows`. That statement reaches the checker
intact, and this is where it gets told what it is missing.

The second is the USE side (design 146). A call to a lowered accessor is not an
ordinary call: `v[i]` and `v.get(i)` name a PLACE, and the window closures the
declaration lowering added are compiler-supplied trailing parameters no author
writes. So the checker recognizes the shape, checks the arguments the author
DID write against the parameters in front of those closures, and types the
expression as the lent `T` (or `T?` for a conditional lend) — leaving the node
annotated for `place_uses.py`, which runs after checking and synthesizes the
window call. Checking has to happen first because the synthesis needs the
receiver's type: `__window`'s parameter type is where `&var T` comes from.

Deliberately NOT decided here: whether a use is a value read or a borrow. That
is a property of the smallest enclosing expression, not of this node, so the
copy-policy table (design 131) is applied by the transform, which is the pass
that computes the window's extent anyway.
"""

from ast_nodes import LendStatement, SawType, TypeKind


class PlacesMixin:
    # =====================================================================
    # Place USES (design 141 semantics, design 146 machinery)
    # =====================================================================

    def _place_accessor_node(self, method_info):
        """The declaration AST behind `method_info` if it is a lowered `borrows`
        accessor, else None. `is_borrows` survives the declaration lowering as
        the author's own record of what was written."""
        if method_info is None:
            return None
        node = getattr(method_info, 'ast_node', None)
        if node is None or not getattr(node, 'is_borrows', False):
            return None
        # A borrows declaration that failed its coverage check is left
        # un-lowered on purpose, so the checker reports against the authored
        # form. Such a declaration has no place to hand out.
        if getattr(node, 'place_type', None) is None:
            return None
        return node

    def _place_type_subst(self, struct_info, obj_type):
        """`{type param -> type arg}` for the receiver's instantiation."""
        subst = {}
        if struct_info is not None and struct_info.type_params and obj_type.type_args:
            for tp, ta in zip(struct_info.type_params, obj_type.type_args):
                subst[tp.name] = ta
        return subst

    def _check_place_use(self, expr, method_info, struct_name, obj_type,
                         method_name, args):
        """Check one place use and annotate it for the use-site lowering.

        Returns the place's type — `T`, or `T?` when the accessor lends
        conditionally — or None if the use does not type-check.
        """
        from errors import ErrorKind
        node = self._place_accessor_node(method_info)
        if node is None:
            return None
        optional = bool(getattr(node, 'place_optional', False))

        # The declaration lowering appended `__window` (and `__absent` for a
        # conditional lend) to the parameter list. Those are the compiler's, not
        # the author's: an accessor takes exactly the parameters in front of
        # them, with `param_types[0]` the receiver slot.
        windows = 2 if optional else 1
        first, last = 1, len(method_info.param_types) - windows
        declared = method_info.param_types[first:last]
        names = method_info.param_names[first:last]

        struct_info = self.get_struct_info(struct_name, from_type=obj_type)
        subst = self._place_type_subst(struct_info, obj_type)

        if len(args) != len(declared):
            self._error(
                ErrorKind.WRONG_ARGUMENT_COUNT,
                f"`{struct_name}.{method_name}` lends a place for "
                f"{len(declared)} argument(s), but {len(args)} were given",
                expr.line, expr.column)
            return None

        for i, arg in enumerate(args):
            want = declared[i]
            if want is not None and subst:
                want = want.substitute(subst)
            got = self._check_expression(arg)
            if got is not None and want is not None and not self._arg_type_ok(
                    arg, got, want, False):
                self._error(
                    ErrorKind.TYPE_MISMATCH,
                    f"argument `{names[i]}` expects `{want}` but got `{got}`",
                    arg.line, arg.column)

        elem = getattr(node, 'place_type', None)
        if elem is not None and subst:
            elem = elem.substitute(subst)

        expr.place_struct = struct_name
        expr.place_method = method_name
        expr.place_elem_type = elem
        expr.place_optional = optional

        # A borrows body is `sync` by construction (the v1 fence), but record the
        # edge anyway so the effect graph stays complete and a future suspending
        # lend reports at the call rather than at codegen.
        self._effect_call_method(
            method_info, f"`{struct_name}.{method_name}`", expr.line)

        if optional:
            return SawType(TypeKind.OPTIONAL, inner_type=elem)
        return elem

    def _check_place_index(self, expr, container_type):
        """`v[i]` where `v`'s type declares a `[]` borrows accessor.

        Returns None — not an error — when there is no such accessor, so the
        ordinary "cannot index into type" diagnostic still owns that case.
        """
        struct_name = container_type.struct_name
        if struct_name is None:
            return None
        struct_info = self.get_struct_info(struct_name, from_type=container_type)
        if struct_info is None:
            return None
        info = self._lookup_method(struct_info, "[]", container_type.type_args)
        if self._place_accessor_node(info) is None:
            return None
        return self._check_place_use(expr, info, struct_name, container_type,
                                     "[]", [expr.index])

    def _check_lend_statement(self, stmt: LendStatement) -> None:
        decl = self.current_method or self.current_function
        name = getattr(decl, 'name', None) if decl is not None else None
        fixit = (f"func {name}(...) borrows -> T" if name
                 else "func f(...) borrows -> T")

        from errors import ErrorKind
        self._error(
            ErrorKind.TYPE_MISMATCH,
            "`lend` is only legal in a `borrows` body — add `borrows` to the "
            f"effect slot (`{fixit}`) if this declaration means to yield a "
            "place for a window rather than return a value",
            stmt.line, stmt.column)

        # Check the place anyway, so a second mistake inside it is reported in
        # the same run rather than on the next compile.
        self._check_expression(stmt.place)
