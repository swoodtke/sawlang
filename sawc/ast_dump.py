"""
AST Dumper for Saw Language

Dumps the AST with type annotations for debugging purposes.
"""

from typing import Any, Optional
from ast_nodes import (
    Program, Struct, Function, Extension, Enum, Interface, TypeDefinition, ExternBlock,
    Method, Parameter, StructField, EnumVariant, InterfaceMethod, AssociatedType, TypeAssignment,
    Block, Statement, Expression, LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    WhileExpr, BreakStatement, ContinueStatement, ForLoop, GuardLetStatement,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, StringInterpolation,
    Identifier, BinaryOp, UnaryOp, MoveExpr, CastExpr, FunctionCall, IfExpr,
    TupleLiteral, TupleIndex, ArrayLiteral, ArrayIndex, MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain, MethodCall, SelfExpr,
    IfLetExpr, EnumInit, MatchArm, MatchExpr, RangeExpr, ClosureExpr, ClosureParam,
    SawType, TypeParameter, Argument, ExternFunction
)


class ASTDumper:
    """Dumps AST nodes with type annotations."""

    def __init__(self, include_stdlib: bool = False):
        self.indent = 0
        self.include_stdlib = include_stdlib
        self.output_lines: list[str] = []

    def dump(self, program: Program) -> str:
        """Dump the entire program AST."""
        self.output_lines = []
        self._dump_program(program)
        return "\n".join(self.output_lines)

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

    def _dump_program(self, prog: Program):
        self._emit("Program {")
        self._indent()

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

        # Interfaces
        if prog.interfaces:
            self._emit("interfaces: [")
            self._indent()
            for iface in prog.interfaces:
                self._dump_interface(iface)
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

    def _dump_struct(self, struct: Struct):
        type_params = ""
        if struct.type_params:
            params = ", ".join(tp.name for tp in struct.type_params)
            type_params = f"<{params}>"
        self._emit(f"Struct {struct.name}{type_params} {{")
        self._indent()
        for field in struct.fields:
            self._emit(f"{field.name}: {self._type_str(field.type)}")
        self._dedent()
        self._emit("}")

    def _dump_enum(self, enum: Enum):
        type_params = ""
        if enum.type_params:
            params = ", ".join(tp.name for tp in enum.type_params)
            type_params = f"<{params}>"
        self._emit(f"Enum {enum.name}{type_params} {{")
        self._indent()
        for variant in enum.variants:
            if variant.associated_types:
                types = ", ".join(f"{name}: {self._type_str(t)}" for name, t in variant.associated_types)
                self._emit(f"case {variant.name}({types})")
            else:
                self._emit(f"case {variant.name}")
        self._dedent()
        self._emit("}")

    def _dump_interface(self, iface: Interface):
        parents = ""
        if iface.parent_interfaces:
            parents = ": " + ", ".join(iface.parent_interfaces)
        self._emit(f"Interface {iface.name}{parents} {{")
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
        type_params = ""
        if ext.type_params:
            params = ", ".join(tp.name for tp in ext.type_params)
            type_params = f"<{params}>"
        conformances = ""
        if ext.conformances:
            conformances = ": " + ", ".join(ext.conformances)
        self._emit(f"Extension {ext.struct_name}{type_params}{conformances} {{")
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

        self._emit(f"{static}{prefix} {method.name}({params_str}) -> {self._type_str(method.return_type)} {{")
        self._indent()
        self._dump_block(method.body)
        self._dedent()
        self._emit("}")

    def _dump_function(self, func: Function):
        type_params = ""
        if func.type_params:
            params = ", ".join(tp.name for tp in func.type_params)
            type_params = f"<{params}>"

        params = []
        for p in func.parameters:
            default = ""
            if p.default_value:
                default = f" = {self._expr_summary(p.default_value)}"
            params.append(f"{p.name}: {self._type_str(p.type)}{default}")
        params_str = ", ".join(params)

        self._emit(f"Function {func.name}{type_params}({params_str}) -> {self._type_str(func.return_type)} {{")
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

        else:
            self._emit(f"<unknown statement: {type(stmt).__name__}>")

    def _dump_expression(self, expr: Expression):
        if isinstance(expr, IntLiteral):
            self._emit(f"IntLiteral({expr.value}) : Int")

        elif isinstance(expr, FloatLiteral):
            self._emit(f"FloatLiteral({expr.value}) : Float")

        elif isinstance(expr, BoolLiteral):
            self._emit(f"BoolLiteral({expr.value}) : Bool")

        elif isinstance(expr, StringLiteral):
            escaped = expr.value.replace('"', '\\"')
            self._emit(f'StringLiteral("{escaped}") : String')

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
            self._emit(f"StructInit {expr.struct_name}{type_args}{resolved}")
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
            self._emit(f"EnumInit {expr.enum_name}{type_args}.{expr.variant_name}")
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
                self._emit(f"case {arm.variant_name}{bindings} ->")
                self._indent()
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
            self._emit("RangeExpr ..")
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

        else:
            self._emit(f"<unknown expression: {type(expr).__name__}>")

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
            return f"{expr.enum_name}.{expr.variant_name}"
        elif isinstance(expr, MethodCall):
            return f"...{expr.method_name}()"
        else:
            return f"<{type(expr).__name__}>"


def dump_ast(program: Program, include_stdlib: bool = False) -> str:
    """Dump a program's AST to a string."""
    dumper = ASTDumper(include_stdlib)
    return dumper.dump(program)
