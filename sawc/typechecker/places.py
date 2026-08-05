"""Element places: what the type checker still has to say about `lend`.

The syntactic rules of a `borrows` body — the coverage rule, the no-lend-in-a-
loop rule, "a place is storage, not a temporary" — all live in
`place_transform.py`, which lowers a `borrows` declaration into its
window-closure form before type checking starts. By the time the checker runs,
a well-formed borrows body has no `lend` left in it.

What remains is the one case the transform deliberately does NOT rewrite: a
`lend` in a body that never declared `borrows`. That statement reaches the
checker intact, and this is where it gets told what it is missing.
"""

from ast_nodes import LendStatement


class PlacesMixin:
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
