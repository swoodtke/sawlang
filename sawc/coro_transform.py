"""design 44 — the source-level coroutine transform.

Post-typecheck, pre-codegen AST rewrite. A function that is DRIVEN (reached from
a `__drive(...)` / `__drive_steps(...)` site — design 44's test-only executor
entry) is rewritten into an ordinary synthesized Saw struct (the *frame*: params
+ across-suspension locals + a state Int [+ drop-flag Bools + a result slot]) and
a `resume` method that dispatches on the state field and runs the body split at
`__suspend()` boundaries. Both are then compiled by the EXISTING codegen/deinit
machinery — nothing here emits IR.

Governing rules honoured (all decided upstream, do NOT re-open):
  * Colorless: which functions suspend is effect-inferred (design 22 graph).
  * The transform is OFF by construction for non-driven code — if a program has
    no `__drive` site, `transform_program` is never called (the pipeline skips
    it), so the whole existing suite takes the byte-identical path.
  * No forced destroy: there are no per-suspension-point destroy paths. Cleanup
    is normal control flow only; a frame dies by its own code reaching an exit.

Staging (this file grows across the brief's items):
  * v1 (landed): straight-line driven bodies over POD (Int/Bool/fixed-width)
    params, across-suspend locals, and result. State split at top-level
    `__suspend()`; the driver loops `resume` to Done.
  * later: cleanup-needing locals via frame-resident drop flags + flag-aware
    frame Deinit; nested driven calls embedded by value; suspending-recursion
    diagnostic; control flow (if/while/match) spanning a suspension.

`transform_program(program, typechecker)` mutates `program` in place and returns
True iff it changed anything (i.e. there were driven roots).
"""

import dataclasses
from ast_nodes import (
    ASTNode, Expression, Statement, Block, Argument,
    Identifier, MemberAccess, SelfExpr, IntLiteral, BoolLiteral,
    FunctionCall, MethodCall, BinaryOp, UnaryOp, EnumInit,
    IfExpr, MatchExpr, MatchArm, WhileExpr, ReturnStatement,
    ExpressionStatement, LetStatement, AssignStatement, WhileExpr,
    Function, Struct, StructField, Enum, EnumVariant, Extension, Method,
    Parameter, SawType, TypeKind, Visibility,
)


class CoroTransformError(Exception):
    """A driven construct the v1 transform cannot yet express soundly. Surfaced
    as a compile error rather than a silent miscompile (hazard discipline)."""
    def __init__(self, message, line=0, column=0):
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column


# --------------------------------------------------------------------------- #
# small AST builders
# --------------------------------------------------------------------------- #

def _self_field(name, line=0, column=0):
    return MemberAccess(object=SelfExpr(line=line, column=column),
                        member=name, line=line, column=column)


def _int(n):
    return IntLiteral(value=n)


def _poll(variant):
    return EnumInit(enum_name="__Poll", variant_name=variant, arguments=[])


def _is_suspend_stmt(stmt):
    """True for a bare `__suspend()` statement — a state boundary."""
    return (isinstance(stmt, ExpressionStatement)
            and isinstance(stmt.expression, FunctionCall)
            and stmt.expression.name == "__suspend")


def _is_pod(saw_type):
    """Conservative POD test for the v1 transform: a type that needs no cleanup
    and can be zero-initialised in the frame's struct-init. Widened to
    cleanup-needing types once frame drop flags land."""
    if saw_type is None:
        return False
    return saw_type.kind in (
        TypeKind.INT, TypeKind.UINT, TypeKind.BOOL,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
    )


def _zero_of(saw_type):
    if saw_type.kind == TypeKind.BOOL:
        return BoolLiteral(value=False)
    return _int(0)


# --------------------------------------------------------------------------- #
# identifier -> self.field rewriting
# --------------------------------------------------------------------------- #

def _rewrite_val(val, names):
    if isinstance(val, list):
        return [_rewrite_val(v, names) for v in val]
    if isinstance(val, tuple):
        return tuple(_rewrite_val(v, names) for v in val)
    if isinstance(val, Argument):
        val.value = _rewrite_node(val.value, names)
        return val
    if isinstance(val, ASTNode):
        return _rewrite_node(val, names)
    return val


def _rewrite_node(node, names):
    """Replace every `Identifier(name)` with `self.name` for name in `names`,
    recursively over the AST. Function/struct/enum names live in plain string
    fields (FunctionCall.name, StructInit.struct_name, MemberAccess.member) and
    are untouched; only bare Identifier EXPRESSIONS are rewritten."""
    if isinstance(node, Identifier) and node.name in names:
        return _self_field(node.name, node.line, node.column)
    if isinstance(node, ASTNode):
        for f in dataclasses.fields(node):
            setattr(node, f.name, _rewrite_val(getattr(node, f.name), names))
    return node


# --------------------------------------------------------------------------- #
# per-function transform
# --------------------------------------------------------------------------- #

class _FrameBuilder:
    def __init__(self, func: Function):
        self.func = func
        self.name = func.name
        self.frame_name = f"__Frame_{func.name}"
        self.ret = func.return_type or SawType(TypeKind.VOID)
        self.is_void = (self.ret.kind == TypeKind.VOID)

    def _collect_frame_locals(self):
        """v1 conservative-by-scope liveness: every top-level `let`/`var` in the
        function body has a lexical scope that spans the whole body (which
        contains the suspensions), so it is frame-resident. Locals in nested
        blocks are handled when nested control flow lands; for v1 straight-line
        bodies there are none."""
        locals_ = []  # (name, SawType)
        seen = set()
        for stmt in self.func.body.statements:
            if isinstance(stmt, LetStatement):
                t = stmt.type_annotation or getattr(stmt.value, 'resolved_type', None)
                if t is None:
                    raise CoroTransformError(
                        f"coroutine transform: local `{stmt.name}` in driven "
                        f"`{self.name}` has no resolved type", stmt.line, stmt.column)
                if stmt.name not in seen:
                    seen.add(stmt.name)
                    locals_.append((stmt.name, t))
        return locals_

    def _check_pod(self, kind, name, t, line, column):
        if not _is_pod(t):
            raise CoroTransformError(
                f"coroutine transform (v1): {kind} `{name}` of driven "
                f"`{self.name}` has non-POD type `{t}`; cleanup-needing frame "
                f"fields are a later item of design 44", line, column)

    def build(self):
        func = self.func
        params = func.parameters
        frame_locals = self._collect_frame_locals()

        # v1 restriction: POD only (no frame drop flags yet).
        for p in params:
            self._check_pod("parameter", p.name, p.type, func.line, func.column)
        for lname, lt in frame_locals:
            self._check_pod("local", lname, lt, func.line, func.column)
        if not self.is_void:
            self._check_pod("result", self.name, self.ret, func.line, func.column)

        frame_field_names = {p.name for p in params} | {n for n, _ in frame_locals}

        # ---- frame struct ------------------------------------------------- #
        fields = []
        for p in params:
            fields.append(StructField(name=p.name, type=p.type))
        for lname, lt in frame_locals:
            fields.append(StructField(name=lname, type=lt))
        fields.append(StructField(name="__state", type=SawType(TypeKind.INT)))
        if not self.is_void:
            fields.append(StructField(name="__result", type=self.ret))
        frame_struct = Struct(name=self.frame_name, fields=fields,
                              line=func.line, column=func.column,
                              source_file=getattr(func, 'source_file', ""))

        # ---- state split -------------------------------------------------- #
        # Segments of top-level statements split at each `__suspend()`.
        segments = [[]]
        for stmt in func.body.statements:
            if _is_suspend_stmt(stmt):
                segments.append([])
            else:
                segments[-1].append(stmt)
        final_expr = func.body.final_expr

        # ---- resume method body ------------------------------------------- #
        resume_stmts = []
        n_states = len(segments)  # states 0 .. n_states-1; last is completion
        for k, seg in enumerate(segments):
            seg_stmts = [self._lower_stmt(s, frame_field_names) for s in seg]
            if k < n_states - 1:
                # A suspending state: run the segment, advance, yield Pending.
                seg_stmts.append(AssignStatement(
                    target=_self_field("__state"), value=_int(k + 1)))
                seg_stmts.append(ReturnStatement(value=_poll("Pending")))
                resume_stmts.append(ExpressionStatement(
                    expression=IfExpr(
                        condition=BinaryOp(op="==", left=_self_field("__state"),
                                           right=_int(k)),
                        then_branch=Block(statements=seg_stmts, final_expr=None))))
            else:
                # The completion state: run the tail, store the result, mark done.
                resume_stmts.extend(seg_stmts)
                if not self.is_void and final_expr is not None:
                    resume_stmts.append(AssignStatement(
                        target=_self_field("__result"),
                        value=_rewrite_node(final_expr, frame_field_names)))
                resume_stmts.append(AssignStatement(
                    target=_self_field("__state"), value=_int(n_states)))
                resume_stmts.append(ReturnStatement(value=_poll("Done")))

        resume = Method(
            name="resume",
            # Self type is the parser's VOID placeholder; registration fills it in
            # with the extension's struct type (`__Frame_<f>`).
            parameters=[Parameter(name="self", type=SawType(TypeKind.VOID),
                                  is_reference=True, reference_mutable=True)],
            return_type=SawType(TypeKind.ENUM, enum_name="__Poll"),
            body=Block(statements=resume_stmts, final_expr=None),
            self_mutable=True, self_is_reference=True,
            line=func.line, column=func.column,
            source_file=getattr(func, 'source_file', ""))
        resume_ext = Extension(struct_name=self.frame_name, methods=[resume],
                              line=func.line, column=func.column,
                              source_file=getattr(func, 'source_file', ""))

        return frame_struct, resume_ext, params, frame_locals

    def _lower_stmt(self, stmt, frame_field_names):
        """Rewrite a body statement for the resume method: a top-level `let`/`var`
        of a frame-resident local becomes an assignment to `self.<name>` (the
        field is pre-declared and initialised at frame construction); every other
        statement just has its identifier references rewritten to `self.<field>`."""
        if isinstance(stmt, LetStatement) and stmt.name in frame_field_names:
            value = _rewrite_node(stmt.value, frame_field_names)
            return AssignStatement(target=_self_field(stmt.name, stmt.line, stmt.column),
                                   value=value, line=stmt.line, column=stmt.column)
        return _rewrite_node(stmt, frame_field_names)


def _make_driver(fb: _FrameBuilder, mode, params, frame_locals):
    """Synthesize the driver function that steps a frame to completion.

    value: `func __drive_<f>(<params>) -> R { var __f = <frame>; loop resume; __f.__result }`
    steps: `func __drive_steps_<f>(<params>) -> Int { ...; count Pendings; __n }`
    """
    # Frame construction: params from the driver's own args, everything else
    # zero-initialised (locals are (re)assigned in resume before use; POD, so a
    # zero placeholder needs no cleanup).
    field_inits = []
    for p in params:
        field_inits.append((p.name, Identifier(name=p.name)))
    for lname, lt in frame_locals:
        field_inits.append((lname, _zero_of(lt)))
    field_inits.append(("__state", _int(0)))
    if not fb.is_void:
        field_inits.append(("__result", _zero_of(fb.ret)))

    from ast_nodes import StructInit
    frame_init = StructInit(struct_name=fb.frame_name, field_inits=field_inits)

    stmts = [LetStatement(name="__f", type_annotation=None, value=frame_init,
                          mutable=True)]

    resume_call = MethodCall(object=Identifier(name="__f"), method_name="resume",
                             arguments=[])
    done_flag_set = AssignStatement(target=Identifier(name="__done"),
                                    value=BoolLiteral(value=True))

    if mode == "steps":
        stmts.append(LetStatement(name="__n", type_annotation=None,
                                  value=_int(0), mutable=True))
        pending_body = Block(statements=[AssignStatement(
            target=Identifier(name="__n"),
            value=BinaryOp(op="+", left=Identifier(name="__n"), right=_int(1)))],
            final_expr=None)
    else:
        pending_body = Block(statements=[], final_expr=None)

    stmts.append(LetStatement(name="__done", type_annotation=None,
                              value=BoolLiteral(value=False), mutable=True))

    loop = WhileExpr(
        condition=UnaryOp(op="not", operand=Identifier(name="__done")),
        body=Block(statements=[ExpressionStatement(expression=MatchExpr(
            matched_expr=resume_call,
            arms=[
                MatchArm(variant_name="Pending", bindings=[], body=pending_body),
                MatchArm(variant_name="Done", bindings=[],
                         body=Block(statements=[done_flag_set], final_expr=None)),
            ]))], final_expr=None))
    stmts.append(ExpressionStatement(expression=loop))

    if mode == "steps":
        driver_name = f"__drive_steps_{fb.name}"
        ret = SawType(TypeKind.INT)
        final = Identifier(name="__n")
    else:
        driver_name = f"__drive_{fb.name}"
        ret = fb.ret
        final = _self_field("__result") if False else MemberAccess(
            object=Identifier(name="__f"), member="__result")

    driver_params = [Parameter(name=p.name, type=p.type) for p in params]
    return Function(name=driver_name, parameters=driver_params, return_type=ret,
                    body=Block(statements=stmts, final_expr=final),
                    source_file=getattr(fb.func, 'source_file', ""))


# --------------------------------------------------------------------------- #
# drive-site rewriting
# --------------------------------------------------------------------------- #

def _rewrite_drive_sites(node, roots):
    """Rewrite `__drive(f(args))` -> `__drive_f(args)` and
    `__drive_steps(f(args))` -> `__drive_steps_f(args)` in place, everywhere."""
    if isinstance(node, FunctionCall) and node.name in ("__drive", "__drive_steps"):
        inner = node.arguments[0].value  # validated in the typechecker
        # Recurse into the inner arguments first (they may themselves contain
        # drive sites, though v1 tests do not nest drivers).
        for a in inner.arguments:
            _rewrite_val(a, set())  # no-op ident rewrite; keeps structure
        prefix = "__drive_steps_" if node.name == "__drive_steps" else "__drive_"
        node.name = prefix + inner.name
        node.arguments = inner.arguments
        return node
    if isinstance(node, ASTNode):
        for f in dataclasses.fields(node):
            _rewrite_drive_fields(getattr(node, f.name), roots)
    return node


def _rewrite_drive_fields(val, roots):
    if isinstance(val, list):
        for i, v in enumerate(val):
            if isinstance(v, Argument):
                v.value = _rewrite_drive_sites(v.value, roots)
            elif isinstance(v, ASTNode):
                _rewrite_drive_sites(v, roots)
    elif isinstance(val, Argument):
        val.value = _rewrite_drive_sites(val.value, roots)
    elif isinstance(val, ASTNode):
        _rewrite_drive_sites(val, roots)


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def transform_program(program, typechecker):
    roots = dict(getattr(typechecker, "_driven_roots", {}) or {})
    if not roots:
        return False

    funcs_by_name = {f.name: f for f in program.functions}

    new_structs = []
    new_enums = []
    new_extensions = []
    new_functions = []
    removed = set()

    # The Poll signal enum (once).
    poll_enum = Enum(name="__Poll", variants=[
        EnumVariant(name="Pending", associated_types=[]),
        EnumVariant(name="Done", associated_types=[]),
    ])
    new_enums.append(poll_enum)

    for root_name, modes in roots.items():
        func = funcs_by_name.get(root_name)
        if func is None:
            raise CoroTransformError(
                f"coroutine transform: driven function `{root_name}` not found "
                f"in the entry module (v1 supports driving entry-module free "
                f"functions only)")
        if func.type_params:
            raise CoroTransformError(
                f"coroutine transform (v1): driving generic function "
                f"`{root_name}` is not supported yet", func.line, func.column)
        fb = _FrameBuilder(func)
        frame_struct, resume_ext, params, frame_locals = fb.build()
        new_structs.append(frame_struct)
        new_extensions.append(resume_ext)
        for mode in modes:
            new_functions.append(_make_driver(fb, mode, params, frame_locals))
        removed.add(root_name)

    # Rewrite all `__drive(...)` sites across the entry module's function and
    # method bodies to call the synthesized drivers.
    for f in program.functions:
        _rewrite_drive_sites(f.body, roots)
    for ext in program.extensions:
        for m in ext.methods:
            _rewrite_drive_sites(m.body, roots)

    # Splice: remove driven roots, add synthesized declarations.
    program.functions = [f for f in program.functions if f.name not in removed]
    program.functions.extend(new_functions)
    program.structs.extend(new_structs)
    program.enums.extend(new_enums)
    program.extensions.extend(new_extensions)
    return True
