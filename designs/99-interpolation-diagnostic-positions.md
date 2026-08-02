# Design 99 — interpolation sub-expression source positions (bug, queued Aug 2)

User-facing diagnostics bug (found Aug 2, fix-on-discovery; deferred
only until design 82's agent lands — same-file adjacency + suite
serialization). A type error inside a string interpolation reports
`FILE:1:1` instead of the real line:

    error: cannot interpolate value of type `Vector<String, ...>` ...
      --> http_server.saw:1:1        <- WRONG, print was mid-file

## Root cause
`parser/expressions.py::_parse_expression_from_string` re-lexes the
`{...}` text with a fresh sub-lexer (positions start at 1:1) and the
returned expression tree KEEPS those sub-positions; the enclosing
string token's real line/column are used only in syntax-error text.
`typechecker/expressions.py::visit_StringInterpolation` then emits at
`getattr(sub_expr, 'line', 0)` -> the bogus 1:1.

## Fix
After sub-parsing, rebase positions onto the source location:
- Walk the returned expression tree (all nodes with line/column).
- line' = string_line + (line - 1)  (sub-lexer is 1-based).
- column': for nodes on sub-line 1, column' = brace_source_column +
  (column - 1), where brace_source_column is computed from the `{`'s
  offset within raw_value (+1 for the opening quote; escapes shift by
  a char occasionally — close is fine, LINE is what matters). Deeper
  sub-lines keep their column.
- `_parse_interpolated_string` must pass the per-interpolation brace
  offset down (it knows `i` at the `{`).
Also stamp the node the typechecker reads even when getattr misses —
audit that every AST node type constructed by the sub-parse carries
line/column at all.

## Tests
- A non-Printable interpolation on a known line reports THAT line
  (compile-fail test asserting the position, not just the message).
- Multi-interpolation string: second `{...}`'s error points at the
  same line with a column past the first's.
- Existing interpolation tests stay green.

## Notes
Prerequisite-adjacent to design 98 (#file/#line literals): the same
sub-parse must preserve real positions for `#line` inside an
interpolation to be correct. Land 99 before or with 98.

Bars: full suite + bootstrap green; zero xfails. Small, single-commit.
