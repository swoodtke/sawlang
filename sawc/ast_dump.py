"""
AST Dumper for Saw Language

Emits the canonical textual AST. Two consumers:

  * `sawc <file> --emit-ast`, for debugging;
  * `tools/astdiff.py` (`make astdiff`), the acceptance oracle for the coming
    Saw parser port -- the same role `tools/lexdiff.py` plays for the lexer.

Because it is an oracle, two properties are load-bearing (design 126 R11):

  * COMPLETE. Every AST node type has an arm. A node type with no arm used to
    fall through to `<unknown ...>` -- silently, in the middle of an otherwise
    plausible dump -- so `ReferenceExpr` (308 occurrences in the corpus) and
    `WhileExpr` in statement position (280) were simply invisible. Fallbacks are
    still emitted rather than raising, but they are RECORDED in `self.unknown`
    so the harness can fail on them instead of a caller having to grep.
  * DETERMINISTIC. Field order is fixed by hand-written emit sequences, and
    nothing address-like reaches the output. `node_id` is deliberately EXCLUDED
    unless `ids=True`: ids are stable within a run but carry no cross-
    implementation meaning, so a Saw port must not have to reproduce them.

The format is documented in `docs/AST_DUMP.md`, which the port is written against.
"""

from typing import Any, Optional
# Design 144: a type REFERENCE slot carries the module-qualified identity; the
# dump renders the short name and puts the module in a field of its own.
from type_identity import display_name as _short
from ast_nodes import (
    Program, Struct, Function, Extension, Enum, Trait, TypeDefinition, ExternBlock,
    Method, Parameter, StructField, EnumVariant, TraitMethod, AssociatedType, TypeAssignment,
    Block, Statement, Expression, LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    WhileExpr, BreakStatement, ContinueStatement, ForLoop, GuardLetStatement,
    LendStatement,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, StringInterpolation,
    FormatPlaceholder,
    Identifier, BinaryOp, UnaryOp, MoveExpr, CastExpr, FunctionCall, IfExpr,
    TupleLiteral, TupleIndex, ArrayLiteral, ArrayIndex, MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain, MethodCall, SelfExpr,
    IfLetExpr, EnumInit, MatchArm, MatchExpr, RangeExpr, ClosureExpr, ClosureParam,
    SawType, TypeParameter, Argument, ExternFunction,
    # design 126 R11: the previously-uncovered node types.
    ReferenceExpr, MapLiteral, SetLiteral, SourceLocationLiteral,
    BindOptional, OptionalEvalExpr, OptionalChainAssign, OptionalWrap,
    ResultOkWrap, ResultErrWrap, ErasedErrWrap, TryExpr, TryCatchExpr,
    DestructuringLet, CompoundAssignStatement, StaticDecl,
    Pattern, WildcardPattern, BindingPattern, LiteralPattern, RangePattern,
    TuplePattern, EnumPattern,
    CaptureSpec, Attribute, ImportDecl, ModuleDecl, ExportDecl, StaticAssert,
)


class ASTDumper:
    """Dumps AST nodes with type annotations."""

    def __init__(self, include_stdlib: bool = False, ids: bool = False):
        self.indent = 0
        self.include_stdlib = include_stdlib
        self.ids = ids
        self.output_lines: list[str] = []
        # Node type names that hit a dispatcher fallback during this dump.
        # `tools/astdiff.py` requires this to stay empty over the whole corpus.
        self.unknown: list[str] = []
        self._tagged_lines: set[int] = set()

    def dump(self, program: Program) -> str:
        """Dump the entire program AST."""
        self.output_lines = []
        self.unknown = []
        self._tagged_lines = set()
        self._dump_program(program)
        return "\n".join(self.output_lines)

    def _unknown(self, kind: str, node) -> None:
        """Record and emit a dispatcher miss. Never silent."""
        name = type(node).__name__
        self.unknown.append(f"{kind}:{name}")
        self._emit(f"<unknown {kind}: {name}>")

    def _id_tag(self, node) -> str:
        """Deprecated inline form, kept for the `MatchArm` header which is not
        emitted through a dispatcher. Prefer `_tagged`."""
        if not self.ids:
            return ""
        return f" #{getattr(node, 'node_id', 0)}"

    def _tagged(self, node, dump_fn) -> None:
        """Run `dump_fn(node)` and, with `--ids`, append ` #N` to the HEADER line
        it produced.

        Doing it here rather than in each arm is what keeps `--ids` uniform: a
        per-arm tag has to be remembered ~60 times and was silently missing from
        every pre-existing arm. A node reachable through two dispatchers (a
        `while` is both statement and expression) is tagged once -- the first
        wrapper to claim the line wins.
        """
        start = len(self.output_lines)
        dump_fn(node)
        if not self.ids or len(self.output_lines) <= start:
            return
        if start in self._tagged_lines:
            return
        self._tagged_lines.add(start)
        self.output_lines[start] += f" #{getattr(node, 'node_id', 0)}"

    def _emit(self, text: str):
        """Emit a line with current indentation."""
        prefix = "  " * self.indent
        self.output_lines.append(f"{prefix}{text}")

    def _indent(self):
        self.indent += 1

    def _dedent(self):
        self.indent -= 1

    def _type_str(self, t: Optional[SawType]) -> str:
        """Convert a type to string representation."""
        if t is None:
            return "<?>"
        return str(t)

    def _quote(self, s: Optional[str]) -> str:
        if s is None:
            return '""'
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _dump_program(self, prog: Program):
        self._emit("Program {")
        self._indent()

        # Module / import / export declarations (design 126 R11). These were
        # never dumped, so an oracle comparing two parsers could not see the
        # module header at all. They are not ASTNode subclasses yet (that is a
        # later brief), which is exactly why they were easy to miss.
        if getattr(prog, 'module_decls', None):
            self._emit("module_decls: [")
            self._indent()
            for md in prog.module_decls:
                vis = "public " if md.is_public else ""
                kind = " (inline)" if md.is_inline else ""
                self._emit(f"{vis}module {md.name}{kind}")
                if md.is_inline and md.body is not None:
                    self._indent()
                    self._dump_program(md.body)
                    self._dedent()
            self._dedent()
            self._emit("]")

        if getattr(prog, 'imports', None):
            self._emit("imports: [")
            self._indent()
            for imp in prog.imports:
                path = ".".join(imp.path)
                if imp.is_glob:
                    self._emit(f"import {path}.*")
                elif imp.symbols:
                    self._emit(f"import {path}.{{{', '.join(imp.symbols)}}}")
                elif imp.alias:
                    self._emit(f"import {path} as {imp.alias}")
                else:
                    self._emit(f"import {path}")
            self._dedent()
            self._emit("]")

        if getattr(prog, 'exports', None):
            self._emit("exports: [")
            self._indent()
            for ex in prog.exports:
                path = ".".join(ex.path)
                suffix = ".*" if ex.is_glob else (f" as {ex.alias}" if ex.alias else "")
                self._emit(f"export {path}{suffix}")
            self._dedent()
            self._emit("]")

        if getattr(prog, 'static_asserts', None):
            self._emit("static_asserts: [")
            self._indent()
            for sa in prog.static_asserts:
                self._emit(f"static_assert {self._quote(sa.message)}")
                self._indent()
                self._dump_expression(sa.condition)
                self._dedent()
            self._dedent()
            self._emit("]")

        # Type definitions
        if prog.type_definitions:
            self._emit("type_definitions: [")
            self._indent()
            for td in prog.type_definitions:
                self._emit(f"type {td.name} = {self._type_str(td.defined_type)}")
            self._dedent()
            self._emit("]")

        # Enums
        if prog.enums:
            self._emit("enums: [")
            self._indent()
            for enum in prog.enums:
                self._dump_enum(enum)
            self._dedent()
            self._emit("]")

        # Traits
        if prog.traits:
            self._emit("traits: [")
            self._indent()
            for trait in prog.traits:
                self._dump_trait(trait)
            self._dedent()
            self._emit("]")

        # Structs
        if prog.structs:
            self._emit("structs: [")
            self._indent()
            for struct in prog.structs:
                self._dump_struct(struct)
            self._dedent()
            self._emit("]")

        # Extensions
        if prog.extensions:
            self._emit("extensions: [")
            self._indent()
            for ext in prog.extensions:
                self._dump_extension(ext)
            self._dedent()
            self._emit("]")

        # Statics (design 41)
        statics = getattr(prog, 'statics', None)
        if statics:
            self._emit("statics: [")
            self._indent()
            for st in statics:
                vis = "public " if getattr(st, 'visibility', None) and \
                    st.visibility.name == "PUBLIC" else ""
                init = f" = {self._expr_summary(st.initializer)}" \
                    if st.initializer is not None else " (zero-init)"
                self._emit(f"{vis}static {st.name}: {self._type_str(st.type)}{init}")
            self._dedent()
            self._emit("]")

        # Extern blocks
        if prog.extern_blocks:
            self._emit("extern_blocks: [")
            self._indent()
            for eb in prog.extern_blocks:
                self._dump_extern_block(eb)
            self._dedent()
            self._emit("]")

        # Functions
        if prog.functions:
            self._emit("functions: [")
            self._indent()
            for func in prog.functions:
                self._dump_function(func)
            self._dedent()
            self._emit("]")

        self._dedent()
        self._emit("}")

    def _module_suffix(self, decl) -> str:
        """The design-144 module half of a type declaration's identity, as a
        FIELD appended to the header line — ` module=dep` — or empty.

        Empty for the whole corpus the oracle sweeps: `tools/dump_ast.py` parses
        ONE file with no module context, and `--emit-ast` type-checks a single
        file, whose module is the root. The field exists so a module-aware
        producer has a place to put the qualifier that is not the NAME, which
        stays what the author wrote."""
        from type_identity import identity_tag
        tag = identity_tag(getattr(decl, 'type_identity', "") or "")
        return f" module={tag}" if tag else ""

    @staticmethod
    def _type_params_str(type_params) -> str:
        """Render a generic parameter list. A const VALUE parameter shows its
        `const N: Int` spelling (design 148) — the dump is an oracle, so two
        parameters that mean different things must not print alike."""
        if not type_params:
            return ""
        parts = []
        for tp in type_params:
            if getattr(tp, 'is_const', False):
                parts.append(f"const {tp.name}: {tp.const_type}")
            else:
                parts.append(tp.name)
        return "<" + ", ".join(parts) + ">"

    def _dump_struct(self, struct: Struct):
        type_params = self._type_params_str(struct.type_params)
        unsafe = "unsafe " if getattr(struct, 'is_unsafe', False) else ""
        self._emit(f"{unsafe}Struct {struct.name}{type_params}"
                   f"{self._module_suffix(struct)} {{")
        self._indent()
        for field in struct.fields:
            self._emit(f"{field.name}: {self._type_str(field.type)}")
        self._dedent()
        self._emit("}")

    def _dump_enum(self, enum: Enum):
        type_params = self._type_params_str(enum.type_params)
        self._emit(f"Enum {enum.name}{type_params}"
                   f"{self._module_suffix(enum)} {{")
        self._indent()
        for variant in enum.variants:
            if variant.associated_types:
                types = ", ".join(f"{name}: {self._type_str(t)}" for name, t in variant.associated_types)
                self._emit(f"case {variant.name}({types})")
            else:
                self._emit(f"case {variant.name}")
        self._dedent()
        self._emit("}")

    def _dump_trait(self, iface: Trait):
        from type_identity import display_name
        parents = ""
        if iface.parent_traits:
            parents = ": " + ", ".join(display_name(p)
                                       for p in iface.parent_traits)
        self._emit(f"Trait {iface.name}{parents}"
                   f"{self._module_suffix(iface)} {{")
        self._indent()
        for at in iface.associated_types:
            self._emit(f"type {at.name}")
        for method in iface.methods:
            params = ", ".join(f"{p.name}: {self._type_str(p.type)}" for p in method.parameters)
            mut = "var " if method.self_mutable else ""
            self._emit(f"func {method.name}({mut}{params}) -> {self._type_str(method.return_type)}")
        self._dedent()
        self._emit("}")

    def _dump_extension(self, ext: Extension):
        type_params = self._type_params_str(ext.type_params)
        from type_identity import display_name
        conformances = ""
        if ext.conformances:
            conformances = ": " + ", ".join(display_name(c)
                                            for c in ext.conformances)
        # `struct_name` is a type REFERENCE, so it carries the identity; the
        # dump shows the short name plus the module as its own field.
        self._emit(f"Extension {display_name(ext.struct_name)}{type_params}"
                   f"{conformances}{self._module_suffix(ext)} {{")
        self._indent()

        for ta in ext.type_assignments:
            self._emit(f"type {ta.name} = {self._type_str(ta.assigned_type)}")

        for method in ext.methods:
            self._dump_method(method)

        self._dedent()
        self._emit("}")

    def _dump_method(self, method: Method):
        params = []
        if not method.is_static:
            mut = "var " if method.self_mutable else ""
            params.append(f"{mut}self")
        for p in method.parameters:
            default = ""
            if p.default_value:
                default = f" = {self._expr_summary(p.default_value)}"
            params.append(f"{p.name}: {self._type_str(p.type)}{default}")
        params_str = ", ".join(params)

        prefix = "init" if method.is_init else "func"
        static = "[static] " if method.is_static else ""
        # designs 136/141: `unsafe` and `borrows` ride the post-parameter
        # effect slot, in canonical order.
        unsafe = " unsafe" if getattr(method, 'is_unsafe', False) else ""
        borrows = " borrows" if getattr(method, 'is_borrows', False) else ""

        self._emit(f"{static}{prefix} {method.name}({params_str}){unsafe}{borrows} -> {self._type_str(method.return_type)} {{")
        self._indent()
        self._dump_block(method.body)
        self._dedent()
        self._emit("}")

    def _dump_function(self, func: Function):
        type_params = self._type_params_str(func.type_params)

        params = []
        for p in func.parameters:
            default = ""
            if p.default_value:
                default = f" = {self._expr_summary(p.default_value)}"
            params.append(f"{p.name}: {self._type_str(p.type)}{default}")
        params_str = ", ".join(params)

        # designs 136/141: `unsafe` and `borrows` ride the post-parameter
        # effect slot, in canonical order.
        unsafe = " unsafe" if getattr(func, 'is_unsafe', False) else ""
        borrows = " borrows" if getattr(func, 'is_borrows', False) else ""
        self._emit(f"Function {func.name}{type_params}({params_str}){unsafe}{borrows} -> {self._type_str(func.return_type)} {{")
        self._indent()
        self._dump_block(func.body)
        self._dedent()
        self._emit("}")

    def _dump_extern_block(self, eb: ExternBlock):
        self._emit(f'extern "{eb.abi}" {{')
        self._indent()
        for func in eb.functions:
            params = ", ".join(f"{p.name}: {self._type_str(p.type)}" for p in func.parameters)
            self._emit(f"func {func.name}({params}) -> {self._type_str(func.return_type)}")
        self._dedent()
        self._emit("}")

    def _dump_block(self, block: Block):
        for stmt in block.statements:
            self._dump_statement(stmt)
        if block.final_expr:
            self._emit("final_expr:")
            self._indent()
            self._dump_expression(block.final_expr)
            self._dedent()

    def _dump_statement(self, stmt: Statement):
        self._tagged(stmt, self._dump_statement_node)

    def _dump_statement_node(self, stmt: Statement):
        if isinstance(stmt, LetStatement):
            mut = "var" if stmt.mutable else "let"
            type_ann = f": {self._type_str(stmt.type_annotation)}" if stmt.type_annotation else ""
            self._emit(f"LetStatement {mut} {stmt.name}{type_ann} =")
            self._indent()
            self._dump_expression(stmt.value)
            self._dedent()

        elif isinstance(stmt, AssignStatement):
            self._emit("AssignStatement")
            self._indent()
            self._emit("target:")
            self._indent()
            self._dump_expression(stmt.target)
            self._dedent()
            self._emit("value:")
            self._indent()
            self._dump_expression(stmt.value)
            self._dedent()
            self._dedent()

        elif isinstance(stmt, ReturnStatement):
            if stmt.value:
                self._emit("ReturnStatement")
                self._indent()
                self._dump_expression(stmt.value)
                self._dedent()
            else:
                self._emit("ReturnStatement (void)")

        elif isinstance(stmt, LendStatement):
            self._emit("LendStatement")
            self._indent()
            self._dump_expression(stmt.place)
            self._dedent()

        elif isinstance(stmt, ExpressionStatement):
            self._emit("ExpressionStatement")
            self._indent()
            self._dump_expression(stmt.expression)
            self._dedent()

        elif isinstance(stmt, BreakStatement):
            if stmt.value:
                self._emit("BreakStatement")
                self._indent()
                self._dump_expression(stmt.value)
                self._dedent()
            else:
                self._emit("BreakStatement")

        elif isinstance(stmt, ContinueStatement):
            self._emit("ContinueStatement")

        elif isinstance(stmt, GuardLetStatement):
            mut = "var" if stmt.mutable else "let"
            self._emit(f"GuardLetStatement guard {mut} {stmt.name} =")
            self._indent()
            self._dump_expression(stmt.optional_expr)
            self._emit("else:")
            self._indent()
            self._dump_block(stmt.else_branch)
            self._dedent()
            self._dedent()

        elif isinstance(stmt, ForLoop):
            result_type = f" : {self._type_str(stmt.result_type)}" if stmt.result_type else ""
            self._emit(f"ForLoop for {stmt.variable} in{result_type}")
            self._indent()
            self._emit("iterable:")
            self._indent()
            self._dump_expression(stmt.iterable)
            self._dedent()
            self._emit("body:")
            self._indent()
            self._dump_block(stmt.body)
            self._dedent()
            self._dedent()

        elif isinstance(stmt, DestructuringLet):
            mut = "var" if stmt.mutable else "let"
            self._emit(f"DestructuringLet {mut}")
            self._indent()
            self._emit("pattern:")
            self._indent()
            self._dump_pattern(stmt.pattern)
            self._dedent()
            self._emit("value:")
            self._indent()
            self._dump_expression(stmt.value)
            self._dedent()
            self._dedent()

        elif isinstance(stmt, CompoundAssignStatement):
            self._emit(f"CompoundAssignStatement {stmt.op}")
            self._indent()
            self._emit("target:")
            self._indent()
            self._dump_expression(stmt.target)
            self._dedent()
            self._emit("value:")
            self._indent()
            self._dump_expression(stmt.value)
            self._dedent()
            self._dedent()

        elif isinstance(stmt, StaticAssert):
            self._emit(f"StaticAssert {self._quote(stmt.message)}")
            self._indent()
            self._dump_expression(stmt.condition)
            self._dedent()

        # `WhileExpr` and `ForLoop` are reachable through BOTH dispatchers: the
        # parser puts a `while` straight into `Block.statements` while a `for`
        # used for its value arrives as an expression. Neither had an arm on its
        # other side, which made 280 `while` statements dump as `<unknown>`.
        elif isinstance(stmt, (WhileExpr, Expression)):
            self._dump_expression(stmt)

        else:
            self._unknown("statement", stmt)

    def _dump_expression(self, expr: Expression):
        if expr is None:
            # A genuinely absent child, not a coverage gap: a bare `return` in a
            # `Result<Void, E>` function auto-wraps into a `ResultOkWrap` whose
            # value is `Ok(())`, i.e. no expression at all.
            self._emit("<none>")
            return
        self._tagged(expr, self._dump_expression_node)

    def _dump_expression_node(self, expr: Expression):
        if isinstance(expr, IntLiteral):
            self._emit(f"IntLiteral({expr.value}) : Int")

        elif isinstance(expr, FloatLiteral):
            self._emit(f"FloatLiteral({expr.value}) : Float")

        elif isinstance(expr, BoolLiteral):
            self._emit(f"BoolLiteral({expr.value}) : Bool")

        elif isinstance(expr, StringLiteral):
            escaped = expr.value.replace('"', '\\"')
            self._emit(f'StringLiteral("{escaped}") : String')

        elif isinstance(expr, FormatPlaceholder):
            # design 137: an empty `{}` slot inside a format string.
            self._emit("FormatPlaceholder")

        elif isinstance(expr, StringInterpolation):
            self._emit("StringInterpolation : String")
            self._indent()
            for i, part in enumerate(expr.parts):
                escaped = part.replace('"', '\\"')
                self._emit(f'part[{i}]: "{escaped}"')
                if i < len(expr.expressions):
                    self._emit(f"expr[{i}]:")
                    self._indent()
                    self._dump_expression(expr.expressions[i])
                    self._dedent()
            self._dedent()

        elif isinstance(expr, Identifier):
            type_args = ""
            if expr.type_args:
                args = ", ".join(self._type_str(t) for t in expr.type_args)
                type_args = f"<{args}>"
            self._emit(f"Identifier({expr.name}{type_args})")

        elif isinstance(expr, BinaryOp):
            self._emit(f"BinaryOp({expr.op})")
            self._indent()
            self._emit("left:")
            self._indent()
            self._dump_expression(expr.left)
            self._dedent()
            self._emit("right:")
            self._indent()
            self._dump_expression(expr.right)
            self._dedent()
            self._dedent()

        elif isinstance(expr, UnaryOp):
            self._emit(f"UnaryOp({expr.op})")
            self._indent()
            self._dump_expression(expr.operand)
            self._dedent()

        elif isinstance(expr, MoveExpr):
            self._emit(f"MoveExpr({expr.variable})")

        elif isinstance(expr, CastExpr):
            self._emit(f"CastExpr as {self._type_str(expr.target_type)}")
            self._indent()
            self._dump_expression(expr.expr)
            self._dedent()

        elif isinstance(expr, FunctionCall):
            type_args = ""
            if expr.type_args:
                args = ", ".join(self._type_str(t) for t in expr.type_args)
                type_args = f"<{args}>"
            self._emit(f"FunctionCall {expr.name}{type_args}()")
            self._indent()
            for i, arg in enumerate(expr.arguments):
                name = f"{arg.name}: " if arg.name else ""
                self._emit(f"arg[{i}]: {name}")
                self._indent()
                self._dump_expression(arg.value)
                self._dedent()
            self._dedent()

        elif isinstance(expr, MethodCall):
            self._emit(f"MethodCall .{expr.method_name}()")
            self._indent()
            self._emit("object:")
            self._indent()
            self._dump_expression(expr.object)
            self._dedent()
            for i, arg in enumerate(expr.arguments):
                name = f"{arg.name}: " if arg.name else ""
                self._emit(f"arg[{i}]: {name}")
                self._indent()
                self._dump_expression(arg.value)
                self._dedent()
            self._dedent()

        elif isinstance(expr, MemberAccess):
            self._emit(f"MemberAccess .{expr.member}")
            self._indent()
            self._dump_expression(expr.object)
            self._dedent()

        elif isinstance(expr, SelfExpr):
            self._emit("SelfExpr")

        elif isinstance(expr, StructInit):
            type_args = ""
            if expr.type_args:
                args = ", ".join(self._type_str(t) for t in expr.type_args)
                type_args = f"<{args}>"
            resolved = ""
            if expr.resolved_init_params is not None:
                resolved = f" [resolved: init({', '.join(expr.resolved_init_params)})]"
            self._emit(f"StructInit {_short(expr.struct_name)}"
                       f"{type_args}{resolved}")
            self._indent()
            for name, value in expr.field_inits:
                self._emit(f"{name}:")
                self._indent()
                self._dump_expression(value)
                self._dedent()
            self._dedent()

        elif isinstance(expr, EnumInit):
            type_args = ""
            if expr.type_args:
                args = ", ".join(self._type_str(t) for t in expr.type_args)
                type_args = f"<{args}>"
            self._emit(f"EnumInit {_short(expr.enum_name)}"
                       f"{type_args}.{expr.variant_name}")
            self._indent()
            for i, arg in enumerate(expr.arguments):
                name = f"{arg.name}: " if arg.name else ""
                self._emit(f"arg[{i}]: {name}")
                self._indent()
                self._dump_expression(arg.value)
                self._dedent()
            self._dedent()

        elif isinstance(expr, NoneLiteral):
            resolved = self._type_str(expr.resolved_type) if expr.resolved_type else "<unresolved>"
            self._emit(f"NoneLiteral : {resolved}")

        elif isinstance(expr, ForceUnwrap):
            self._emit("ForceUnwrap !")
            self._indent()
            self._dump_expression(expr.expr)
            self._dedent()

        elif isinstance(expr, NilCoalesce):
            self._emit("NilCoalesce ??")
            self._indent()
            self._emit("expr:")
            self._indent()
            self._dump_expression(expr.expr)
            self._dedent()
            self._emit("default:")
            self._indent()
            self._dump_expression(expr.default)
            self._dedent()
            self._dedent()

        elif isinstance(expr, OptionalChain):
            self._emit(f"OptionalChain ?.{expr.member}")
            self._indent()
            self._dump_expression(expr.expr)
            self._dedent()

        elif isinstance(expr, IfExpr):
            self._emit("IfExpr")
            self._indent()
            self._emit("condition:")
            self._indent()
            self._dump_expression(expr.condition)
            self._dedent()
            self._emit("then:")
            self._indent()
            self._dump_block(expr.then_branch)
            self._dedent()
            if expr.else_branch:
                self._emit("else:")
                self._indent()
                self._dump_block(expr.else_branch)
                self._dedent()
            self._dedent()

        elif isinstance(expr, IfLetExpr):
            mut = "var" if expr.mutable else "let"
            self._emit(f"IfLetExpr if {mut} {expr.name} =")
            self._indent()
            self._emit("optional:")
            self._indent()
            self._dump_expression(expr.optional_expr)
            self._dedent()
            self._emit("then:")
            self._indent()
            self._dump_block(expr.then_branch)
            self._dedent()
            if expr.else_branch:
                self._emit("else:")
                self._indent()
                self._dump_block(expr.else_branch)
                self._dedent()
            self._dedent()

        elif isinstance(expr, WhileExpr):
            result_type = f" : {self._type_str(expr.result_type)}" if expr.result_type else ""
            if expr.condition:
                self._emit(f"WhileExpr{result_type}")
                self._indent()
                self._emit("condition:")
                self._indent()
                self._dump_expression(expr.condition)
                self._dedent()
            else:
                self._emit(f"WhileExpr (infinite){result_type}")
                self._indent()
            self._emit("body:")
            self._indent()
            self._dump_block(expr.body)
            self._dedent()
            self._dedent()

        elif isinstance(expr, MatchExpr):
            self._emit("MatchExpr")
            self._indent()
            self._emit("matched:")
            self._indent()
            self._dump_expression(expr.matched_expr)
            self._dedent()
            for arm in expr.arms:
                bindings = ""
                if arm.bindings:
                    bindings = f"({', '.join(arm.bindings)})"
                self._emit(f"case {arm.variant_name}{bindings} ->{self._id_tag(arm)}")
                self._indent()
                # A pattern arm carries its shape here rather than in
                # variant_name/bindings; without this the whole design-63
                # pattern family never reached the dump.
                if arm.pattern is not None:
                    self._emit("pattern:")
                    self._indent()
                    self._dump_pattern(arm.pattern)
                    self._dedent()
                if arm.guard is not None:
                    self._emit("guard:")
                    self._indent()
                    self._dump_expression(arm.guard)
                    self._dedent()
                self._dump_expression(arm.body)
                self._dedent()
            self._dedent()

        elif isinstance(expr, TupleLiteral):
            self._emit("TupleLiteral")
            self._indent()
            for i, elem in enumerate(expr.elements):
                self._emit(f"[{i}]:")
                self._indent()
                self._dump_expression(elem)
                self._dedent()
            self._dedent()

        elif isinstance(expr, TupleIndex):
            self._emit(f"TupleIndex .{expr.index}")
            self._indent()
            self._dump_expression(expr.tuple_expr)
            self._dedent()

        elif isinstance(expr, ArrayLiteral):
            if expr.repeat_count is not None:
                # Repeat literal `[v; N]` (design 148): one value, a count.
                self._emit("ArrayLiteral [repeat]")
                self._indent()
                self._emit("value:")
                self._indent()
                self._dump_expression(expr.elements[0])
                self._dedent()
                self._emit("count:")
                self._indent()
                self._dump_expression(expr.repeat_count)
                self._dedent()
                self._dedent()
                return
            self._emit(f"ArrayLiteral [{len(expr.elements)} elements]")
            self._indent()
            for i, elem in enumerate(expr.elements):
                self._emit(f"[{i}]:")
                self._indent()
                self._dump_expression(elem)
                self._dedent()
            self._dedent()

        elif isinstance(expr, ArrayIndex):
            self._emit("ArrayIndex")
            self._indent()
            self._emit("array:")
            self._indent()
            self._dump_expression(expr.array_expr)
            self._dedent()
            self._emit("index:")
            self._indent()
            self._dump_expression(expr.index)
            self._dedent()
            self._dedent()

        elif isinstance(expr, RangeExpr):
            self._emit(f"RangeExpr {'..=' if expr.is_inclusive else '..'}")
            self._indent()
            self._emit("start:")
            self._indent()
            self._dump_expression(expr.start)
            self._dedent()
            self._emit("end:")
            self._indent()
            self._dump_expression(expr.end)
            self._dedent()
            self._dedent()

        elif isinstance(expr, ClosureExpr):
            if expr.parameters:
                params = ", ".join(p.name for p in expr.parameters)
            elif expr.shorthand_param_count > 0:
                params = ", ".join(f"${i}" for i in range(expr.shorthand_param_count))
            else:
                params = ""
            captures = ""
            if expr.captures:
                captures = f" [captures: {', '.join(expr.captures)}]"
            self._emit(f"ClosureExpr {{ {params} in ... }}{captures}")
            self._indent()
            self._dump_block(expr.body)
            self._dedent()

        elif isinstance(expr, Block):
            self._emit("Block")
            self._indent()
            self._dump_block(expr)
            self._dedent()

        elif isinstance(expr, ForLoop):
            # A `for` in value position; the statement dispatcher renders the
            # same shape.
            self._dump_statement(expr)

        elif isinstance(expr, ReferenceExpr):
            sigil = "&var" if expr.mutable else "&"
            arg = " (argument position)" if expr.in_argument_position else ""
            self._emit(f"ReferenceExpr {sigil}{arg}")
            self._indent()
            self._dump_expression(expr.expr)
            self._dedent()

        elif isinstance(expr, MapLiteral):
            self._emit(f"MapLiteral [{len(expr.entries)} entries]")
            self._indent()
            for i, (k, v) in enumerate(expr.entries):
                self._emit(f"key[{i}]:")
                self._indent()
                self._dump_expression(k)
                self._dedent()
                self._emit(f"value[{i}]:")
                self._indent()
                self._dump_expression(v)
                self._dedent()
            self._dedent()

        elif isinstance(expr, SetLiteral):
            self._emit(f"SetLiteral [{len(expr.elements)} elements]")
            self._indent()
            for i, elem in enumerate(expr.elements):
                self._emit(f"[{i}]:")
                self._indent()
                self._dump_expression(elem)
                self._dedent()
            self._dedent()

        elif isinstance(expr, SourceLocationLiteral):
            self._emit(f"SourceLocationLiteral #{expr.kind}")

        elif isinstance(expr, BindOptional):
            self._emit(f"BindOptional ?")
            self._indent()
            self._dump_expression(expr.expr)
            self._dedent()

        elif isinstance(expr, OptionalEvalExpr):
            self._emit(f"OptionalEvalExpr")
            self._indent()
            self._dump_expression(expr.expr)
            self._dedent()

        elif isinstance(expr, OptionalChainAssign):
            self._emit(f"OptionalChainAssign")
            self._indent()
            self._emit("target:")
            self._indent()
            self._dump_expression(expr.target)
            self._dedent()
            self._emit("value:")
            self._indent()
            self._dump_expression(expr.value)
            self._dedent()
            self._dedent()

        # The four typechecker-inserted wraps (design 30/56/57). The parser never
        # builds them, so they appear only in a post-typecheck dump.
        elif isinstance(expr, OptionalWrap):
            self._emit(f"OptionalWrap : {self._type_str(expr.target_type)}")
            self._indent()
            self._dump_expression(expr.value)
            self._dedent()

        elif isinstance(expr, ResultOkWrap):
            self._emit(f"ResultOkWrap : {self._type_str(expr.result_type)}")
            self._indent()
            self._dump_expression(expr.value)
            self._dedent()

        elif isinstance(expr, ResultErrWrap):
            self._emit(f"ResultErrWrap : {self._type_str(expr.result_type)}")
            self._indent()
            self._dump_expression(expr.value)
            self._dedent()

        elif isinstance(expr, ErasedErrWrap):
            self._emit(f"ErasedErrWrap to any {expr.trait_name} : "
                       f"{self._type_str(expr.result_type)}")
            self._indent()
            self._dump_expression(expr.value)
            self._dedent()

        elif isinstance(expr, TryExpr):
            self._emit(f"TryExpr {expr.variant}")
            self._indent()
            self._dump_expression(expr.expr)
            if expr.catch_block is not None:
                self._emit("catch:")
                self._indent()
                self._dump_block(expr.catch_block)
                self._dedent()
            self._dedent()

        elif isinstance(expr, TryCatchExpr):
            binding = f" ({expr.error_binding})" if expr.error_binding else ""
            self._emit(f"TryCatchExpr{binding}")
            self._indent()
            self._emit("try:")
            self._indent()
            self._dump_block(expr.try_block)
            self._dedent()
            self._emit("catch:")
            self._indent()
            self._dump_block(expr.catch_block)
            self._dedent()
            self._dedent()

        else:
            self._unknown("expression", expr)

    # ---------------------------------------------------------------- patterns
    def _dump_pattern(self, pat: Optional[Pattern]):
        if pat is None:
            self._emit("<no pattern>")
            return
        self._tagged(pat, self._dump_pattern_node)

    def _dump_pattern_node(self, pat: Pattern):
        """Patterns (design 63). Previously dumped NOWHERE: `MatchArm.pattern`
        was not read at all, so every literal / range / tuple / nested-enum arm
        rendered as a bare `case ->` and all six pattern classes were invisible
        to the oracle."""
        if pat is None:
            self._emit("<no pattern>")

        elif isinstance(pat, WildcardPattern):
            self._emit(f"WildcardPattern _")

        elif isinstance(pat, BindingPattern):
            self._emit(f"BindingPattern {pat.name}")

        elif isinstance(pat, LiteralPattern):
            self._emit(f"LiteralPattern")
            self._indent()
            self._dump_expression(pat.value)
            self._dedent()

        elif isinstance(pat, RangePattern):
            op = "..=" if pat.is_inclusive else ".."
            self._emit(f"RangePattern {op}")
            self._indent()
            self._emit("start:")
            self._indent()
            self._dump_expression(pat.start)
            self._dedent()
            self._emit("end:")
            self._indent()
            self._dump_expression(pat.end)
            self._dedent()
            self._dedent()

        elif isinstance(pat, TuplePattern):
            self._emit(f"TuplePattern [{len(pat.elements)} elements]")
            self._indent()
            for i, sub in enumerate(pat.elements):
                self._emit(f"[{i}]:")
                self._indent()
                self._dump_pattern(sub)
                self._dedent()
            self._dedent()

        elif isinstance(pat, EnumPattern):
            self._emit(f"EnumPattern {pat.variant_name}")
            self._indent()
            for i, sub in enumerate(pat.subpatterns):
                self._emit(f"[{i}]:")
                self._indent()
                self._dump_pattern(sub)
                self._dedent()
            self._dedent()

        else:
            self._unknown("pattern", pat)

    def _expr_summary(self, expr: Expression) -> str:
        """Get a short summary of an expression for inline display."""
        if isinstance(expr, IntLiteral):
            return str(expr.value)
        elif isinstance(expr, FloatLiteral):
            return str(expr.value)
        elif isinstance(expr, BoolLiteral):
            return str(expr.value).lower()
        elif isinstance(expr, StringLiteral):
            return f'"{expr.value}"'
        elif isinstance(expr, Identifier):
            return expr.name
        elif isinstance(expr, NoneLiteral):
            return "None"
        elif isinstance(expr, EnumInit):
            return f"{_short(expr.enum_name)}.{expr.variant_name}"
        elif isinstance(expr, MethodCall):
            return f"...{expr.method_name}()"
        elif isinstance(expr, FunctionCall):
            return f"{expr.name}(...)"
        elif isinstance(expr, StructInit):
            return f"{_short(expr.struct_name)}(...)"
        elif isinstance(expr, ArrayLiteral):
            if expr.repeat_count is not None:
                return (f"[{self._expr_summary(expr.elements[0])}; "
                        f"{self._expr_summary(expr.repeat_count)}]")
            return f"[{len(expr.elements)} elements]"
        elif isinstance(expr, UnaryOp):
            return f"{expr.op}{self._expr_summary(expr.operand)}"
        elif isinstance(expr, BinaryOp):
            return (f"{self._expr_summary(expr.left)} {expr.op} "
                    f"{self._expr_summary(expr.right)}")
        elif isinstance(expr, FormatPlaceholder):
            return "{}"
        elif isinstance(expr, StringInterpolation):
            return '"..."'
        elif isinstance(expr, SourceLocationLiteral):
            return f"#{expr.kind}"
        elif isinstance(expr, CastExpr):
            return f"{self._expr_summary(expr.expr)} as {self._type_str(expr.target_type)}"
        elif isinstance(expr, MemberAccess):
            return f"{self._expr_summary(expr.object)}.{expr.member}"
        else:
            self.unknown.append(f"summary:{type(expr).__name__}")
            return f"<{type(expr).__name__}>"


def dump_ast(program: Program, include_stdlib: bool = False,
             ids: bool = False) -> str:
    """Dump a program's AST to a string."""
    dumper = ASTDumper(include_stdlib, ids=ids)
    return dumper.dump(program)
