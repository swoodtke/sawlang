"""The compile-time constant evaluator.

ONE evaluator, callable from any phase. It began (design 53) as a method on the
codegen `Compiler`, because `static_assert` was the only caller and `sizeof<T>()`
needs LLVM's ABI layout. Design 148 gave it three more callers that run EARLIER —
an array length `[T; N]`, a repeat-literal count `[v; N]`, and a const generic
argument `FixedBuf<2 * 128>` all have to be known while types are still being
resolved — so the phase-dependent parts became parameters instead:

  `env`     name -> int, for the identifiers that denote compile-time integers.
            The typechecker binds const generic parameters here; an identifier
            absent from it is rejected as non-constant, which is what keeps a
            runtime `let` out of a constant position. A module `static` takes
            the other route (DF-172j): the typechecker stamps its value on the
            identifier node, because the question "which `SIZE` is this, and may
            this file see it" is a namespace question and this file has none.
  `metric`  the layout oracle behind `sizeof<T>()` / `alignof<T>()`. Codegen
            passes one; the typechecker passes None, since it knows the word
            width but not struct layout, and `sizeof` in a type-resolution
            position is then rejected by name rather than answered wrongly.
  `width`   the platform integer width, for `Int.max` / `UInt.min`.

Growing a second evaluator was the alternative and is the thing to keep not
doing: two of them drift, and the drift is silent — a `static_assert` and the
array length beside it would disagree about the same expression.

The accepted grammar is exactly what design 53 documented, plus `env`:
integer/Bool literals, unary `-`/`not`, `+ - * / %`, the comparisons, `&&`/`||`,
`sizeof<T>()`/`alignof<T>()`, the `Int.max`/`.min` limits, and a bound name —
plus a raw-BACKED enum's case and an `as` between integer types, which are what
let a `static_assert` pin a wire table against the enum that declares it
(`static_assert((SysOp.Shutdown as UInt) == 1, ...)`) instead of against a
hand-copied number that could drift from it silently.
Division and modulo truncate toward zero, matching Saw's runtime semantics
(`LANGUAGE_SPEC.md`, Integer Arithmetic Semantics), so a constant-folded
expression and its runtime twin can never disagree.
"""

from ast_nodes import (
    BoolLiteral, IntLiteral, UnaryOp, BinaryOp, FunctionCall, MemberAccess,
    Identifier, CastExpr, TypeKind,
)

# (type name) -> (bit width, or None to mean the platform word) x (is signed).
INT_LIMIT_SPECS = {
    'Int': (None, True), 'UInt': (None, False),
    'Int8': (8, True), 'Int16': (16, True),
    'Int32': (32, True), 'Int64': (64, True),
    'UInt8': (8, False), 'UInt16': (16, False),
    'UInt32': (32, False), 'UInt64': (64, False),
}

# The integer kinds an `as` may target in a constant, on the same (width,
# signed) terms — `None` is the platform word, resolved from `width`.
CAST_INT_KINDS = {
    TypeKind.INT: (None, True), TypeKind.UINT: (None, False),
    TypeKind.INT8: (8, True), TypeKind.INT16: (16, True),
    TypeKind.INT32: (32, True), TypeKind.INT64: (64, True),
    TypeKind.UINT8: (8, False), TypeKind.UINT16: (16, False),
    TypeKind.UINT32: (32, False), TypeKind.UINT64: (64, False),
}


# The hint every const-required LENGTH position gives. Shared (rather than
# written twice) because the two positions are two spellings of one rule and are
# reported from two different phases — the repeat count in the typechecker, the
# declared array length in codegen — so a drift between them would read as a
# disagreement about what a length may be.
CONST_LENGTH_HINT = (
    "a length is fixed at compile time — use a literal, a const generic "
    "parameter, arithmetic over them, or a module `static` of type `Int` or "
    "`UInt` initialized by a plain integer literal"
)


class ConstEvalError(Exception):
    """An expression that is not a compile-time constant.

    `what` names the offending construct ("division by zero", "call to `read`")
    and nothing else, so each caller can frame it for its own position — the
    `static_assert` condition, an array length, a repeat count. `line`/`column`
    come off the offending expression, so a long constant expression reports the
    sub-expression that failed rather than its first token.
    """

    def __init__(self, what: str, line: int = 0, column: int = 0):
        super().__init__(what)
        self.what = what
        self.line = line
        self.column = column


def _reject(expr, what):
    raise ConstEvalError(what, getattr(expr, 'line', 0),
                         getattr(expr, 'column', 0))


def const_eval(expr, env=None, metric=None, width: int = 64):
    """Evaluate `expr` to a Python int/bool, or raise `ConstEvalError`.

    Args:
        expr: the expression AST node.
        env: optional name -> int bindings (design 148 const generic params).
        metric: optional `(saw_type, 'size'|'align') -> int` layout oracle.
        width: platform integer width, for the `Int.max`/`Int.min` limits.
    """
    if isinstance(expr, BoolLiteral):
        return bool(expr.value)
    if isinstance(expr, IntLiteral):
        return int(expr.value)
    if isinstance(expr, Identifier):
        if env is not None and expr.name in env:
            return env[expr.name]
        # DF-172j: a module `static` whose initializer is a plain integer
        # literal. The typechecker owns the resolution — which module the name
        # belongs to, whether it is visible here, whether a local shadows it —
        # and stamps the answer on the node, exactly as it stamps `Int.max` and
        # a raw-backed enum case on a MemberAccess below. Keeping the lookup
        # there is what lets this stay a pure function of the AST, callable from
        # codegen with no namespace in hand.
        value = getattr(expr, 'const_static_value', None)
        if value is not None:
            return int(value)
        reject = getattr(expr, 'const_static_reject', None)
        if reject is not None:
            _reject(expr, reject)
        _reject(expr, f"`{expr.name}`")
    if isinstance(expr, UnaryOp):
        if expr.op == '-':
            return -const_eval(expr.operand, env, metric, width)
        if expr.op == 'not':
            return not const_eval(expr.operand, env, metric, width)
        _reject(expr, f"unary operator `{expr.op}`")
    if isinstance(expr, BinaryOp):
        left = const_eval(expr.left, env, metric, width)
        right = const_eval(expr.right, env, metric, width)
        op = expr.op
        if op == '+': return left + right
        if op == '-': return left - right
        if op == '*': return left * right
        if op == '/':
            if right == 0:
                _reject(expr, "division by zero")
            q = abs(left) // abs(right)
            return -q if (left < 0) ^ (right < 0) else q
        if op == '%':
            if right == 0:
                _reject(expr, "modulo by zero")
            r = abs(left) % abs(right)
            return -r if left < 0 else r
        if op == '==': return left == right
        if op == '!=': return left != right
        if op == '<': return left < right
        if op == '>': return left > right
        if op == '<=': return left <= right
        if op == '>=': return left >= right
        if op == '&&': return bool(left) and bool(right)
        if op == '||': return bool(left) or bool(right)
        _reject(expr, f"operator `{op}`")
    if isinstance(expr, FunctionCall):
        if expr.name in ('sizeof', 'alignof'):
            if metric is None:
                _reject(expr, f"`{expr.name}<T>()`")
            if not expr.type_args or len(expr.type_args) != 1:
                _reject(expr, f"`{expr.name}` needs one type argument")
            which = 'size' if expr.name == 'sizeof' else 'align'
            return metric(expr.type_args[0], which)
        _reject(expr, f"call to `{expr.name}`")
    if isinstance(expr, MemberAccess):
        limit = getattr(expr, 'int_limit', None)
        if limit is not None:
            return int_limit_value(limit, width)
        # A case of a raw-BACKED enum (design 145 unit B2). Its value is pinned
        # by the declaration, so it is as constant as a literal; an unbacked
        # enum's case is stamped with nothing and falls through to the
        # rejection below, because its ordinal is not part of the type.
        raw = getattr(expr, 'enum_raw_value', None)
        if raw is not None:
            return int(raw)
        _reject(expr, "this member access")
    if isinstance(expr, CastExpr):
        value = const_eval(expr.expr, env, metric, width)
        if isinstance(value, bool):
            _reject(expr, "a cast of a Bool")
        spec = CAST_INT_KINDS.get(getattr(expr.target_type, 'kind', None))
        if spec is None:
            _reject(expr, f"a cast to `{expr.target_type}`")
        bits, signed = spec
        if bits is None:
            bits = width
        lo = -(1 << (bits - 1)) if signed else 0
        hi = ((1 << (bits - 1)) - 1) if signed else (1 << bits) - 1
        if not (lo <= value <= hi):
            # Refused rather than wrapped: a constant that does not fit its
            # target is a mistake in the assertion, and silently truncating it
            # would make the `static_assert` agree with nothing.
            _reject(expr, f"`{value}` does not fit `{expr.target_type}`")
        return value
    _reject(expr, type(expr).__name__)


def int_limit_value(limit, width: int) -> int:
    """The value of an `Int.max`-shaped limit the typechecker stamped."""
    type_name, which = limit
    bits, signed = INT_LIMIT_SPECS[type_name]
    if bits is None:
        bits = width
    if which == "max":
        return (1 << (bits - 1)) - 1 if signed else (1 << bits) - 1
    return -(1 << (bits - 1)) if signed else 0
